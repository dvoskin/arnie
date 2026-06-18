"""
Tests for `notifications.apns_client` (slice 2b — the APNs sender).

Mocks Apple's HTTP/2 endpoint via `httpx.MockTransport` so the JWT-signed
request is built and verified deterministically without real network. A
fresh EC P-256 keypair per test serves as the .p8 stand-in; we decode our
own JWTs against the matching public key to assert claims + headers.
"""
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

from notifications import apns_client


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def p8_keypair():
    """Fresh EC P-256 keypair. Returns (pem_str, public_key) — the PEM is
    what Render stores in APNS_AUTH_KEY_P8; the public key is what we use
    to verify the JWT we just signed."""
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key = load_pem_public_key(public_pem)
    return pem, public_key


@pytest.fixture
def configured_env(monkeypatch, p8_keypair):
    """Set the four required env vars + production environment. Tests that
    want to exercise the unconfigured path use a separate fixture or skip
    this one."""
    pem, _ = p8_keypair
    monkeypatch.setenv("APNS_KEY_ID", "TESTKEYID9")
    monkeypatch.setenv("APNS_TEAM_ID", "TESTTEAM10")
    monkeypatch.setenv("APNS_BUNDLE_ID", "com.tryarnie.app")
    monkeypatch.setenv("APNS_AUTH_KEY_P8", pem)
    monkeypatch.setenv("APNS_ENVIRONMENT", "production")
    # JWT cache is global; clear so each test sees a fresh sign.
    apns_client.reset_jwt_cache()
    yield
    apns_client.reset_jwt_cache()


def _mock_client(handler) -> httpx.AsyncClient:
    """An httpx AsyncClient backed by MockTransport. Skips real HTTP/2
    negotiation (we're unit-testing the sender's request-building, not
    httpx itself)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── Tests ────────────────────────────────────────────────────────────────────


def test_is_configured_requires_all_four_env_vars(monkeypatch):
    """Missing any single required var → not configured."""
    for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID", "APNS_AUTH_KEY_P8"):
        monkeypatch.delenv(k, raising=False)
    assert apns_client.is_configured() is False

    monkeypatch.setenv("APNS_KEY_ID", "x")
    monkeypatch.setenv("APNS_TEAM_ID", "y")
    monkeypatch.setenv("APNS_BUNDLE_ID", "z")
    # Still missing the p8 → still not configured.
    assert apns_client.is_configured() is False

    monkeypatch.setenv("APNS_AUTH_KEY_P8", "---PEM---")
    assert apns_client.is_configured() is True


def test_jwt_has_expected_claims_and_kid_header(configured_env, p8_keypair):
    """The signed JWT must carry `iss = team id`, `iat = ~now`, alg = ES256,
    and a `kid` header equal to the key id — Apple uses `kid` to look up
    the public half of our .p8."""
    _, public_key = p8_keypair
    token = apns_client._get_jwt()
    decoded = jwt.decode(token, public_key, algorithms=["ES256"])
    headers = jwt.get_unverified_header(token)

    assert decoded["iss"] == "TESTTEAM10"
    assert abs(decoded["iat"] - time.time()) < 5
    assert headers["kid"] == "TESTKEYID9"
    assert headers["alg"] == "ES256"


def test_jwt_is_cached_within_ttl(configured_env):
    """Second call to `_get_jwt` reuses the cached token — Apple recommends
    NOT minting a fresh JWT per request (they may flag it as abuse)."""
    first = apns_client._get_jwt()
    second = apns_client._get_jwt()
    assert first == second


def test_jwt_refreshes_after_ttl_expiry(configured_env):
    """If `now` advances past TTL, `_get_jwt` mints a new token. The
    injectable `now` parameter lets us assert this without sleeping 50
    minutes."""
    first = apns_client._get_jwt(now=1000.0)
    later = apns_client._get_jwt(now=1000.0 + apns_client._JWT_TTL_SECONDS + 10)
    assert first != later


@pytest.mark.asyncio
async def test_send_push_returns_not_configured_when_env_missing(monkeypatch):
    """When env vars are absent, `send_push` no-ops with a typed error and
    DOES NOT touch the network."""
    for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID", "APNS_AUTH_KEY_P8"):
        monkeypatch.delenv(k, raising=False)

    def must_not_be_called(request):  # pragma: no cover — assertion fires before this
        raise AssertionError("network must not be touched when unconfigured")

    result = await apns_client.send_push(
        "device-token-xyz", "T", "B", client=_mock_client(must_not_be_called),
    )
    assert result == {"ok": False, "error": "not_configured"}


@pytest.mark.asyncio
async def test_send_push_success_returns_ok(configured_env):
    """A 200 from Apple → `{"ok": True}`."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    result = await apns_client.send_push(
        "abc123token", "Arnie", "Time to log lunch", client=_mock_client(handler),
    )
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_send_push_builds_request_with_jwt_topic_and_payload(
    configured_env, p8_keypair,
):
    """End-to-end request shape: ES256 JWT in Authorization header, bundle
    id in apns-topic, push-type alert, body has the alert dict and a
    `sound` field. Device token interpolated into the path."""
    captured = {}
    _, public_key = p8_keypair

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read()
        return httpx.Response(200)

    await apns_client.send_push(
        "DEVICE_TOK_42", "Pacing nudge", "200g protein to go",
        client=_mock_client(handler),
    )

    assert captured["url"] == "https://api.push.apple.com/3/device/DEVICE_TOK_42"
    assert captured["headers"]["apns-topic"] == "com.tryarnie.app"
    assert captured["headers"]["apns-push-type"] == "alert"

    auth = captured["headers"]["authorization"]
    assert auth.startswith("bearer ")
    decoded = jwt.decode(auth.split(" ", 1)[1], public_key, algorithms=["ES256"])
    assert decoded["iss"] == "TESTTEAM10"

    import json
    body = json.loads(captured["body"])
    assert body["aps"]["alert"] == {"title": "Pacing nudge", "body": "200g protein to go"}
    assert body["aps"]["sound"] == "default"


@pytest.mark.asyncio
async def test_send_push_returns_status_and_reason_on_apple_rejection(configured_env):
    """A 410 BadDeviceToken (the most operationally important error code —
    triggers token revocation in slice 2c) surfaces the exact reason
    string so the caller can dispatch on it."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            410, json={"reason": "BadDeviceToken"}, headers={"content-type": "application/json"},
        )

    result = await apns_client.send_push(
        "dead-token", "T", "B", client=_mock_client(handler),
    )
    assert result == {"ok": False, "status": 410, "reason": "BadDeviceToken"}


@pytest.mark.asyncio
async def test_send_push_handles_apple_response_without_json_body(configured_env):
    """Some Apple errors (e.g. 5xx infrastructure blips) return non-JSON
    bodies. The sender must still return a structured failure dict, not
    raise — the scheduler hookup will retry per-token, not whole-batch
    crash."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="<html>Service Unavailable</html>")

    result = await apns_client.send_push(
        "token", "T", "B", client=_mock_client(handler),
    )
    assert result == {"ok": False, "status": 503, "reason": "unknown"}


@pytest.mark.asyncio
async def test_send_push_routes_sandbox_environment_to_sandbox_host(configured_env):
    """A per-call `environment="sandbox"` override routes to the sandbox
    host even though APNS_ENVIRONMENT=production. Lets a single backend
    serve both Debug-registered and production-registered devices side by
    side without redeploys."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200)

    await apns_client.send_push(
        "tok", "T", "B", environment="sandbox", client=_mock_client(handler),
    )
    assert captured["url"].startswith("https://api.sandbox.push.apple.com/")


@pytest.mark.asyncio
async def test_send_push_payload_extra_does_not_overwrite_aps(configured_env):
    """`payload_extra` is for custom fields the client reads (e.g. a deep-
    link route or a category id). It must NOT overwrite Apple's reserved
    `aps` dict — silently dropping that key is the right defense."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200)

    await apns_client.send_push(
        "tok", "T", "B",
        payload_extra={"deep_link": "arnie://today", "aps": {"injected": True}},
        client=_mock_client(handler),
    )

    import json
    body = json.loads(captured["body"])
    assert body["deep_link"] == "arnie://today"
    # The reserved `aps` retains its sender-built alert payload — the
    # attempt to overwrite was dropped.
    assert "injected" not in body["aps"]
    assert "alert" in body["aps"]
