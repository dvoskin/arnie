"""
Tests for the Apple Sign-in binding logic in POST /api/v1/auth/session.

Covers the three branches in `api/auth_routes.create_session` for
`provider == "apple"`:

  (1) `apple_sub` is already bound to a user → return THAT user's identity
      (handles a returning sign-in from any device — same Apple ID).
  (2) Caller presents a valid existing session token (Authorization: Bearer)
      → bind `apple_sub` to the presenting user. This is the iOS Profile
      "Sign in with Apple" flow: the device-signed user keeps their history
      and just gains an Apple identity.
  (3) No prior binding, no presenter bearer → create a fresh `apple:<sub>`
      user and record `apple_sub` on the new row.

The Apple-token verification path itself is covered exhaustively in
`tests/test_apple_auth.py`; this file monkey-patches `verify_apple_identity_token`
to a deterministic stub so the binding logic can be exercised with simple
inputs (no crypto setup per test).
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.auth import issue_session_token
from api.auth_routes import SessionRequest, create_session
from db.queries import find_user_by_apple_sub


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_apple_verify(monkeypatch):
    """Replace `verify_apple_identity_token` with a deterministic stub: a
    credential `ok:<sub>` verifies to `apple:<sub>`; anything else raises 401.
    Lets each test express its scenario as a single short string instead of
    minting a real RS256 JWT."""
    from fastapi import HTTPException
    from api import auth as api_auth

    def fake_verify(token: str) -> str:
        if not token or not token.startswith("ok:"):
            raise HTTPException(status_code=401, detail="bad apple token")
        return f"apple:{token.split(':', 1)[1]}"

    monkeypatch.setattr(api_auth, "verify_apple_identity_token", fake_verify)


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Point `api.auth_routes.AsyncSessionLocal` at the test engine so the
    route handler's `async with AsyncSessionLocal() as db:` block reads/writes
    the same in-memory SQLite the `db` fixture exposes for assertions."""
    from api import auth_routes
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(auth_routes, "AsyncSessionLocal", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def existing_device_user(db, make_user):
    """A user already created via the device sign-in path (`telegram_id =
    ios:device-abc`), with a daily log + one food entry so branch-(2) tests
    can verify the prior history stays attached after binding."""
    from datetime import date
    from db.models import DailyLog, FoodEntry

    user = await make_user(telegram_id="ios:device-abc")
    log = DailyLog(user_id=user.id, date=date.today())
    db.add(log)
    await db.flush()
    db.add(FoodEntry(
        daily_log_id=log.id,
        parsed_food_name="oatmeal",
        calories=300, protein=10, carbs=50, fats=5,
    ))
    await db.commit()
    return user


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_branch_3_fresh_signin_creates_apple_user_and_records_sub(
    stub_apple_verify, patched_session_local, db,
):
    """No prior binding + no bearer → fresh `apple:<sub>` user, `apple_sub`
    set on the row (so a later sign-in from another device routes to it via
    branch (1))."""
    resp = await create_session(
        SessionRequest(provider="apple", credential="ok:alice"),
        authorization=None,
    )

    assert resp.identity == "apple:alice"
    user = await find_user_by_apple_sub(db, "alice")
    assert user is not None
    assert user.telegram_id == "apple:alice"
    assert user.apple_sub == "alice"


@pytest.mark.asyncio
async def test_branch_1_returning_apple_signin_finds_existing_user(
    stub_apple_verify, patched_session_local, db,
):
    """Second sign-in with same Apple credential resolves to the same user,
    no duplicate row created. Proves cross-device continuity for the same
    Apple ID."""
    first = await create_session(
        SessionRequest(provider="apple", credential="ok:bob"),
        authorization=None,
    )
    second = await create_session(
        SessionRequest(provider="apple", credential="ok:bob"),
        authorization=None,
    )

    assert first.identity == second.identity == "apple:bob"

    # Defensive: count rows with apple_sub=bob — must be exactly one.
    from sqlalchemy import select, func
    from db.models import User
    count = (await db.execute(
        select(func.count()).select_from(User).where(User.apple_sub == "bob")
    )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_branch_2_binds_apple_sub_to_existing_device_user(
    stub_apple_verify, patched_session_local, db, existing_device_user,
):
    """Valid bearer for the existing device user + Apple sign-in → `apple_sub`
    is bound onto the device user's row, identity returned is the ORIGINAL
    device identity (so the session token's identity claim stays stable and
    `resolve_user` keeps using its existing path)."""
    device_token = issue_session_token("ios:device-abc")
    resp = await create_session(
        SessionRequest(provider="apple", credential="ok:carol"),
        authorization=f"Bearer {device_token}",
    )

    # Identity stays the device one — no token-identity drift.
    assert resp.identity == "ios:device-abc"

    bound = await find_user_by_apple_sub(db, "carol")
    assert bound is not None
    assert bound.id == existing_device_user.id
    assert bound.telegram_id == "ios:device-abc"

    # The prior food entry still belongs to this user — history preserved.
    from sqlalchemy import select
    from db.models import DailyLog, FoodEntry

    logs = (await db.execute(
        select(DailyLog).where(DailyLog.user_id == bound.id)
    )).scalars().all()
    assert len(logs) == 1
    entries = (await db.execute(
        select(FoodEntry).where(FoodEntry.daily_log_id == logs[0].id)
    )).scalars().all()
    assert len(entries) == 1
    assert entries[0].parsed_food_name == "oatmeal"


@pytest.mark.asyncio
async def test_branch_2_invalid_bearer_falls_through_to_branch_3(
    stub_apple_verify, patched_session_local, db,
):
    """An unverifiable bearer is treated as "no bearer" — the route falls
    through to branch (3) and creates a fresh `apple:<sub>` user. This keeps
    the endpoint usable even when an older iOS build presents a stale token
    that the server has rotated past."""
    resp = await create_session(
        SessionRequest(provider="apple", credential="ok:dave"),
        authorization="Bearer not-a-valid-session-token",
    )

    assert resp.identity == "apple:dave"
    user = await find_user_by_apple_sub(db, "dave")
    assert user is not None
    assert user.telegram_id == "apple:dave"


@pytest.mark.asyncio
async def test_repeat_binding_is_idempotent(
    stub_apple_verify, patched_session_local, db, existing_device_user,
):
    """Re-submitting the same Apple sign-in with the same bearer → idempotent.
    `set_apple_sub_for_user` no-ops on same-sub, so the second call does not
    raise its defensive different-sub error. Identity stable across calls."""
    device_token = issue_session_token("ios:device-abc")
    req = SessionRequest(provider="apple", credential="ok:eve")

    first = await create_session(req, authorization=f"Bearer {device_token}")
    second = await create_session(req, authorization=f"Bearer {device_token}")

    assert first.identity == second.identity == "ios:device-abc"
    bound = await find_user_by_apple_sub(db, "eve")
    assert bound.id == existing_device_user.id


@pytest.mark.asyncio
async def test_set_apple_sub_for_user_rejects_conflicting_sub(db, make_user):
    """Direct unit test for the query helper's defensive guard: a row already
    bound to sub A cannot be silently rebound to sub B (the unique index
    would catch this in prod, but the helper surfaces a clearer error before
    the DB constraint fires)."""
    from db.queries import set_apple_sub_for_user

    user = await make_user(telegram_id="ios:test-conflict")
    await set_apple_sub_for_user(db, user.id, "sub-A")

    with pytest.raises(ValueError, match="already bound"):
        await set_apple_sub_for_user(db, user.id, "sub-B")

    # And same-sub stays a no-op (idempotent).
    await set_apple_sub_for_user(db, user.id, "sub-A")
