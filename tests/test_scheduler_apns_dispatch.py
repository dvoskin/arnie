"""
Tests for the APNs branch of `scheduler.proactive_scheduler._send` (slice 2c).

Confirms the dispatch routes ios:* / apple:* identities to the APNs sender
(instead of attempting `int(telegram_id)` and crashing), fans out to every
active device token a user has, and revokes tokens Apple reports as dead
(BadDeviceToken / Unregistered / 410) so they don't keep getting tried.

The actual HTTP/2 round-trip is the sender's responsibility and is covered
by `tests/test_apns_client.py`; here we monkeypatch `send_push` to a
recorder/stub so the dispatch logic is tested deterministically.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from db.queries import (
    active_device_tokens_for_user,
    upsert_device_token,
)
from scheduler import proactive_scheduler


@pytest_asyncio.fixture(autouse=True)
async def proactive_enabled(monkeypatch):
    """The scheduler's master kill switch defaults off in tests (conftest sets
    PROACTIVE_MESSAGING_ENABLED=false). Flip it on for this module so `_send`
    actually reaches the dispatch branch."""
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Point `db.database.AsyncSessionLocal` at the test engine so `_send_ios`'s
    `async with AsyncSessionLocal()` reads/writes the same in-memory sqlite the
    `db` fixture exposes for assertions."""
    from db import database
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", session_factory)
    return session_factory


@pytest.fixture
def configured_apns(monkeypatch):
    """Pretend APNs is configured so `is_configured()` returns True; the
    `send_push` function itself will be monkey-patched out per-test."""
    monkeypatch.setenv("APNS_KEY_ID", "TESTKEY")
    monkeypatch.setenv("APNS_TEAM_ID", "TESTTEAM")
    monkeypatch.setenv("APNS_BUNDLE_ID", "com.tryarnie.app")
    monkeypatch.setenv("APNS_AUTH_KEY_P8", "any-non-empty-value")
    monkeypatch.setenv("APNS_ENVIRONMENT", "production")


class _SendPushRecorder:
    """Replacement for `notifications.apns_client.send_push` that records every
    call and returns a canned result. Tests can swap the canned result per-call
    to model BadDeviceToken / success / generic-failure responses."""
    def __init__(self):
        self.calls: list[tuple[str, str, str, str]] = []
        self.responses: list[dict] = []

    async def __call__(self, device_token, title, body, *, environment=None, **_):
        self.calls.append((device_token, title, body, environment))
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True}


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ios_identity_fans_to_every_active_token(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """An ios:<uuid> user with two registered devices receives two pushes —
    one per active token. Body is the message; title is constant 'Arnie'."""
    user = await make_user(telegram_id="ios:two-devices-user")
    await upsert_device_token(db, user.id, "iphone-token", environment="production")
    await upsert_device_token(db, user.id, "ipad-token", environment="production")

    recorder = _SendPushRecorder()
    monkeypatch.setattr(
        "notifications.apns_client.send_push", recorder,
    )

    await proactive_scheduler._send("ios:two-devices-user", "Time to log lunch")

    tokens_sent = {call[0] for call in recorder.calls}
    assert tokens_sent == {"iphone-token", "ipad-token"}
    bodies = {call[2] for call in recorder.calls}
    assert bodies == {"Time to log lunch"}
    titles = {call[1] for call in recorder.calls}
    assert titles == {"Arnie"}


@pytest.mark.asyncio
async def test_apple_identity_also_routes_to_apns(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """An apple:<sub> identity must go through the same APNs branch — NOT
    fall through to the Telegram numeric-id parse (which would crash with
    ValueError on `int('apple:abc')`)."""
    user = await make_user(telegram_id="apple:001234.xyz.456")
    await upsert_device_token(db, user.id, "post-binding-token", environment="production")

    recorder = _SendPushRecorder()
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send("apple:001234.xyz.456", "Good morning")
    assert len(recorder.calls) == 1


@pytest.mark.asyncio
async def test_bubble_separator_collapsed_to_newlines(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """Multi-bubble proactive messages use ||| as a separator. APNs is a
    single-bubble channel — collapse to a one-blob body with newlines so
    the system banner renders the whole thing."""
    user = await make_user(telegram_id="ios:bubble-test")
    await upsert_device_token(db, user.id, "tok", environment="production")

    recorder = _SendPushRecorder()
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send(
        "ios:bubble-test", "Hey Danny|||Time to log lunch|||Aiming for 50g protein",
    )

    assert recorder.calls[0][2] == "Hey Danny\nTime to log lunch\nAiming for 50g protein"


@pytest.mark.asyncio
async def test_bad_device_token_response_revokes_token(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """Apple's BadDeviceToken response means the token was never valid —
    revoke so the next sweep doesn't waste a round-trip."""
    user = await make_user(telegram_id="ios:dead-token-user")
    await upsert_device_token(db, user.id, "dead", environment="production")

    recorder = _SendPushRecorder()
    recorder.responses.append({"ok": False, "status": 400, "reason": "BadDeviceToken"})
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send("ios:dead-token-user", "nudge")

    active = await active_device_tokens_for_user(db, user.id)
    assert active == []   # the dead token has been revoked


@pytest.mark.asyncio
async def test_unregistered_410_response_revokes_token(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """A 410 Unregistered means the app was uninstalled — same disposition
    as BadDeviceToken: revoke the row so it stops being a recipient."""
    user = await make_user(telegram_id="ios:uninstalled-user")
    await upsert_device_token(db, user.id, "uninstalled", environment="production")

    recorder = _SendPushRecorder()
    recorder.responses.append({"ok": False, "status": 410, "reason": "Unregistered"})
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send("ios:uninstalled-user", "nudge")

    active = await active_device_tokens_for_user(db, user.id)
    assert active == []


@pytest.mark.asyncio
async def test_transient_failure_does_NOT_revoke_token(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """A 5xx or other non-token error is transient (Apple infra blip, JWT
    rotation race, etc.) — the token might still be good. DO NOT revoke;
    the next sweep retries."""
    user = await make_user(telegram_id="ios:flaky-apns")
    await upsert_device_token(db, user.id, "still-good", environment="production")

    recorder = _SendPushRecorder()
    recorder.responses.append({"ok": False, "status": 503, "reason": "ServerError"})
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send("ios:flaky-apns", "nudge")

    active = await active_device_tokens_for_user(db, user.id)
    assert len(active) == 1
    assert active[0].token == "still-good"


@pytest.mark.asyncio
async def test_no_active_tokens_is_a_quiet_no_op(
    patched_session_local, configured_apns, db, make_user, monkeypatch,
):
    """A user with no registered devices (e.g. iOS app installed but APNs
    never granted) is silently skipped — no send_push call, no error."""
    await make_user(telegram_id="ios:no-devices")
    recorder = _SendPushRecorder()
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send("ios:no-devices", "nudge")
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_apns_unconfigured_skips_send_quietly(
    patched_session_local, db, make_user, monkeypatch,
):
    """When the APNs env vars aren't set on this deploy, _send_ios skips
    the send rather than raising. Lets the scheduler keep running TG/iMessage
    proactives even when iOS push hasn't been provisioned yet."""
    for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID", "APNS_AUTH_KEY_P8"):
        monkeypatch.delenv(k, raising=False)
    user = await make_user(telegram_id="ios:unconfigured")
    await upsert_device_token(db, user.id, "tok", environment="production")

    recorder = _SendPushRecorder()
    monkeypatch.setattr("notifications.apns_client.send_push", recorder)

    await proactive_scheduler._send("ios:unconfigured", "nudge")

    assert recorder.calls == []
    # And the token is NOT revoked — it might be fine once env vars land.
    active = await active_device_tokens_for_user(db, user.id)
    assert len(active) == 1
