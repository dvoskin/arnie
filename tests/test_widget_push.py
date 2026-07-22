"""
Widget-reload push — the silent APNs primitive + the fan-out helper.

`send_background_push` is the content-available silent push that wakes the iOS
app to reload its widget timelines; `notify_widget_reload` fans it out to every
active device (with a cross-environment retry) and revokes tokens APNs reports
dead. These tests pin the silent-push wire contract (which differs from an alert
push in ways Apple rejects if you get them wrong), the fan-out + revoke, and the
inert-when-unconfigured / no-loop safety paths.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from notifications import apns_client, widget_push


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def configured_env(monkeypatch):
    """Set the four APNs env vars with a real EC P-256 key so `_get_jwt` can
    actually ES256-sign. Clears the global JWT cache around the test."""
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    monkeypatch.setenv("APNS_KEY_ID", "TESTKEYID9")
    monkeypatch.setenv("APNS_TEAM_ID", "TESTTEAM10")
    monkeypatch.setenv("APNS_BUNDLE_ID", "com.tryarnie.app")
    monkeypatch.setenv("APNS_AUTH_KEY_P8", pem)
    monkeypatch.setenv("APNS_ENVIRONMENT", "production")
    apns_client.reset_jwt_cache()
    yield
    apns_client.reset_jwt_cache()


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── send_background_push: the silent-push wire contract ──────────────────────


@pytest.mark.asyncio
async def test_background_push_builds_silent_request(configured_env):
    """A silent push is `apns-push-type: background`, `apns-priority: 5`, body
    `{"aps": {"content-available": 1}}` with NO alert/sound — and `payload_extra`
    is merged at the top level for the client to branch on."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read()
        return httpx.Response(200)

    result = await apns_client.send_background_push(
        "TOK_42",
        payload_extra={"purpose": "widget-reload"},
        client=_mock_client(handler),
    )

    assert result == {"ok": True}
    assert captured["url"] == "https://api.push.apple.com/3/device/TOK_42"
    assert captured["headers"]["apns-push-type"] == "background"
    assert captured["headers"]["apns-priority"] == "5"
    assert captured["headers"]["apns-topic"] == "com.tryarnie.app"

    body = json.loads(captured["body"])
    assert body["aps"] == {"content-available": 1}
    assert "alert" not in body["aps"] and "sound" not in body["aps"]
    assert body["purpose"] == "widget-reload"


@pytest.mark.asyncio
async def test_background_push_routes_sandbox_to_sandbox_host(configured_env):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200)

    await apns_client.send_background_push(
        "TOK_S", environment="sandbox", client=_mock_client(handler),
    )
    assert captured["url"].startswith("https://api.sandbox.push.apple.com/")


@pytest.mark.asyncio
async def test_background_push_payload_extra_never_overwrites_aps(configured_env):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200)

    await apns_client.send_background_push(
        "TOK_X",
        payload_extra={"aps": "hijack", "k": "v"},   # `aps` must be ignored
        client=_mock_client(handler),
    )
    body = json.loads(captured["body"])
    assert body["aps"] == {"content-available": 1}
    assert body["k"] == "v"


@pytest.mark.asyncio
async def test_background_push_not_configured_is_no_op(monkeypatch):
    for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID", "APNS_AUTH_KEY_P8"):
        monkeypatch.delenv(k, raising=False)
    result = await apns_client.send_background_push("TOK")
    assert result == {"ok": False, "error": "not_configured"}


# ── notify_widget_reload: fan-out + revoke ───────────────────────────────────


def _point_helper_session_at(engine, monkeypatch):
    """Point `notify_widget_reload`'s own `AsyncSessionLocal` at the test
    engine (it opens its own session, since it runs fire-and-forget)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    import db.database as dbmod
    monkeypatch.setattr(
        dbmod, "AsyncSessionLocal",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )


@pytest.mark.asyncio
async def test_notify_widget_reload_fans_out_to_active_tokens(db, make_user, monkeypatch, engine):
    from db.queries import upsert_device_token

    user = await make_user(telegram_id="ios:push1")
    await upsert_device_token(
        db, user_id=user.id, token="TOKAAA", platform="apns", environment="production",
    )
    _point_helper_session_at(engine, monkeypatch)

    monkeypatch.setattr(apns_client, "is_configured", lambda: True)
    sent = []

    async def fake_send(token, **kw):
        sent.append((token, kw.get("environment")))
        return {"ok": True}

    monkeypatch.setattr(apns_client, "send_background_push", fake_send)

    result = await widget_push.notify_widget_reload(user.id)

    assert result == {"ok": True, "sent": 1}
    assert sent == [("TOKAAA", "production")]


@pytest.mark.asyncio
async def test_notify_widget_reload_revokes_dead_token(db, make_user, monkeypatch, engine):
    from db.queries import upsert_device_token, active_device_tokens_for_user

    user = await make_user(telegram_id="ios:push2")
    await upsert_device_token(
        db, user_id=user.id, token="DEADTOK", platform="apns", environment="production",
    )
    _point_helper_session_at(engine, monkeypatch)

    monkeypatch.setattr(apns_client, "is_configured", lambda: True)

    async def fake_send(token, **kw):
        # Dead on BOTH environments → the helper should revoke.
        return {"ok": False, "status": 410, "reason": "Unregistered"}

    monkeypatch.setattr(apns_client, "send_background_push", fake_send)

    result = await widget_push.notify_widget_reload(user.id)

    assert result["sent"] == 0
    # A fresh read on the test session sees the revocation the helper committed.
    assert await active_device_tokens_for_user(db, user.id) == []


@pytest.mark.asyncio
async def test_notify_widget_reload_no_devices(db, make_user, monkeypatch, engine):
    user = await make_user(telegram_id="ios:push3")
    _point_helper_session_at(engine, monkeypatch)
    monkeypatch.setattr(apns_client, "is_configured", lambda: True)

    result = await widget_push.notify_widget_reload(user.id)
    assert result == {"ok": True, "sent": 0, "no_devices": True}


@pytest.mark.asyncio
async def test_notify_widget_reload_inert_when_unconfigured(monkeypatch):
    """No credentials → no DB touched, typed no-op."""
    monkeypatch.setattr(apns_client, "is_configured", lambda: False)

    async def _boom(*a, **k):  # pragma: no cover — must never be reached
        raise AssertionError("must not touch the DB when APNs is unconfigured")

    import db.queries as q
    monkeypatch.setattr(q, "active_device_tokens_for_user", _boom)

    result = await widget_push.notify_widget_reload(123)
    assert result == {"ok": False, "error": "not_configured"}


# ── schedule_widget_reload: fire-and-forget safety ───────────────────────────


def test_schedule_widget_reload_no_running_loop_is_silent_noop():
    """Called from a sync context (no running loop): swallows the RuntimeError
    from `create_task` and returns without raising."""
    widget_push.schedule_widget_reload(1)  # must not raise


def test_schedule_widget_reload_none_user_returns_immediately():
    widget_push.schedule_widget_reload(None)  # must not raise
