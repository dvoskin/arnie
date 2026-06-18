"""
Tests for /api/v1/devices/apns-token (slice 2a of the APNs delivery work).

Covers the upsert/reassign/revoke lifecycle implemented in
`db.queries.upsert_device_token` / `revoke_device_token` and the thin route
wrappers in `api/devices.py`. The actual APNs SENDER (slice 2b) and
proactive-scheduler hookup (slice 2c) ship later — this slice only tests
that tokens land on the server and stay tied to the right user.

The route handlers are called directly (no httpx/TestClient) — keeps these
fast and lets the existing in-memory sqlite `db`/`engine`/`make_user`
fixtures drive both sides of the call without HTTP serialization noise.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.devices import APNSTokenBody, delete_apns_token, post_apns_token
from db.queries import active_device_tokens_for_user


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Point `api.devices.AsyncSessionLocal` at the test engine so the route
    handler's `async with AsyncSessionLocal() as db:` writes go where the
    test's `db` fixture reads."""
    from api import devices
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(devices, "AsyncSessionLocal", session_factory)
    return session_factory


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_registers_new_token(
    patched_session_local, db, make_user,
):
    """First call for a token → INSERT a row with the expected fields."""
    user = await make_user(telegram_id="ios:user-a")

    resp = await post_apns_token(
        APNSTokenBody(token="hex-token-a", environment="production"),
        identity="ios:user-a",
    )
    assert resp == {"status": "ok"}

    rows = await active_device_tokens_for_user(db, user.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.token == "hex-token-a"
    assert row.platform == "apns"
    assert row.environment == "production"
    assert row.user_id == user.id
    assert row.revoked_at is None


@pytest.mark.asyncio
async def test_post_same_token_twice_is_idempotent(
    patched_session_local, db, make_user,
):
    """Re-registering the same token under the same user → still one row.
    Models the every-app-launch refresh pattern."""
    user = await make_user(telegram_id="ios:user-b")

    body = APNSTokenBody(token="hex-token-b", environment="production")
    await post_apns_token(body, identity="ios:user-b")
    await post_apns_token(body, identity="ios:user-b")

    rows = await active_device_tokens_for_user(db, user.id)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_post_same_token_different_user_reassigns(
    patched_session_local, db, make_user,
):
    """Device handoff: same physical device, two different signed-in users
    over time → the token row's user_id flips, no duplicate row created.
    Without this, a hand-me-down iPhone would accumulate dead rows pointing
    at the previous owner."""
    user_a = await make_user(telegram_id="ios:owner-a")
    user_b = await make_user(telegram_id="ios:owner-b")

    body = APNSTokenBody(token="shared-device-token", environment="production")
    await post_apns_token(body, identity="ios:owner-a")
    await post_apns_token(body, identity="ios:owner-b")

    a_rows = await active_device_tokens_for_user(db, user_a.id)
    b_rows = await active_device_tokens_for_user(db, user_b.id)
    assert len(a_rows) == 0
    assert len(b_rows) == 1
    assert b_rows[0].token == "shared-device-token"


@pytest.mark.asyncio
async def test_post_environment_switch_is_recorded(
    patched_session_local, db, make_user,
):
    """A build channel change (sandbox Debug → production TestFlight) must
    update the row so the sender routes to the right APNs host on the next
    push."""
    user = await make_user(telegram_id="ios:env-switch")

    await post_apns_token(
        APNSTokenBody(token="env-test", environment="sandbox"),
        identity="ios:env-switch",
    )
    await post_apns_token(
        APNSTokenBody(token="env-test", environment="production"),
        identity="ios:env-switch",
    )

    rows = await active_device_tokens_for_user(db, user.id)
    assert len(rows) == 1
    assert rows[0].environment == "production"


@pytest.mark.asyncio
async def test_delete_revokes_token_so_sender_filters_it(
    patched_session_local, db, make_user,
):
    """DELETE marks the row revoked. The "active tokens" helper excludes
    revoked rows — that's the seam the sender uses to skip them."""
    user = await make_user(telegram_id="ios:revoker")
    await post_apns_token(
        APNSTokenBody(token="to-revoke", environment="production"),
        identity="ios:revoker",
    )

    resp = await delete_apns_token("to-revoke", identity="ios:revoker")
    assert resp == {"status": "revoked"}

    active = await active_device_tokens_for_user(db, user.id)
    assert len(active) == 0


@pytest.mark.asyncio
async def test_post_reactivates_revoked_token(
    patched_session_local, db, make_user,
):
    """Re-registering a revoked token must clear `revoked_at` — covers the
    sign-out-then-sign-back-in flow on the same device."""
    user = await make_user(telegram_id="ios:reactivator")
    body = APNSTokenBody(token="back-from-the-dead", environment="production")
    await post_apns_token(body, identity="ios:reactivator")
    await delete_apns_token("back-from-the-dead", identity="ios:reactivator")
    await post_apns_token(body, identity="ios:reactivator")

    active = await active_device_tokens_for_user(db, user.id)
    assert len(active) == 1
    assert active[0].revoked_at is None


@pytest.mark.asyncio
async def test_delete_other_users_token_returns_404(
    patched_session_local, db, make_user,
):
    """A token owned by user A cannot be revoked by user B's bearer.
    Defensive against a leaked session token being used to kill arbitrary
    devices. Returns 404 (not 403) to avoid leaking token existence."""
    user_a = await make_user(telegram_id="ios:owner")
    user_b = await make_user(telegram_id="ios:attacker")
    await post_apns_token(
        APNSTokenBody(token="owner-token", environment="production"),
        identity="ios:owner",
    )

    with pytest.raises(HTTPException) as exc:
        await delete_apns_token("owner-token", identity="ios:attacker")
    assert exc.value.status_code == 404

    # Owner's token still active.
    active = await active_device_tokens_for_user(db, user_a.id)
    assert len(active) == 1


@pytest.mark.asyncio
async def test_delete_nonexistent_token_returns_404(
    patched_session_local, make_user,
):
    """DELETE of a token that was never registered → 404 (same shape as the
    other-user case so the response surface stays uniform)."""
    await make_user(telegram_id="ios:ghost")
    with pytest.raises(HTTPException) as exc:
        await delete_apns_token("does-not-exist", identity="ios:ghost")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_active_tokens_returns_only_unrevoked(
    patched_session_local, db, make_user,
):
    """Direct unit test for the sender-facing query: a user with one live +
    one revoked token sees only the live one in `active_device_tokens_for_user`."""
    user = await make_user(telegram_id="ios:two-devices")
    await post_apns_token(
        APNSTokenBody(token="iphone", environment="production"),
        identity="ios:two-devices",
    )
    await post_apns_token(
        APNSTokenBody(token="ipad", environment="production"),
        identity="ios:two-devices",
    )
    await delete_apns_token("ipad", identity="ios:two-devices")

    active = await active_device_tokens_for_user(db, user.id)
    assert {row.token for row in active} == {"iphone"}
