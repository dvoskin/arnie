"""Apple Health snapshot ingestion uses the USER's logging day, not the server's.

Both HealthKit-sync entry points defaulted an omitted `date` to `date.today()`
— the deploying server's day (UTC on Render). A client west of Greenwich
syncing in its own evening, which is the normal Health Auto Export / HealthKit
background-delivery window, filed today's steps/sleep/calories under
tomorrow's UTC date: the same rollover-boundary bug the 07-24 phantom-workout
fix addressed for the workout batch on this exact endpoint, never carried up
to the snapshot date those workouts fall back to.

Fixed by routing both sites through `_user_today`, the one rollover-aware day
this app uses everywhere else. These pin: an omitted date resolves to the
USER's local day even when it differs from the server's UTC day, on both the
legacy Shortcuts webhook (`api/app.py::_process_apple_health`) and the native
bearer-auth endpoint (`api/health_sync.py::post_snapshot`).

Both handlers open their OWN db session (`AsyncSessionLocal()`), which is the
app's global sessionmaker rather than the `db` fixture's engine — so, as in
test_profile_edit_api.py, the module's `AsyncSessionLocal` is patched to the
fixture's engine for the duration of the test.
"""
from datetime import date

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from db.models import HealthSnapshot


@pytest_asyncio.fixture
async def patched_app_session(monkeypatch, engine):
    from api import app as app_module
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(app_module, "AsyncSessionLocal", factory)
    return app_module


@pytest_asyncio.fixture
async def patched_health_sync_session(monkeypatch, engine):
    from api import health_sync as hs_module
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(hs_module, "AsyncSessionLocal", factory)
    return hs_module


async def _snapshot(db, user_id, d):
    return (await db.execute(
        select(HealthSnapshot).where(HealthSnapshot.user_id == user_id,
                                     HealthSnapshot.date == d)
    )).scalar_one_or_none()


async def test_legacy_webhook_omitted_date_uses_user_local_day(
        make_user, db, patched_app_session, monkeypatch):
    app_module = patched_app_session
    u = await make_user(telegram_id="hk-legacy-1", name="Wrist",
                        webhook_token="tok-legacy-1", timezone="UTC")

    # A day nowhere near whenever this test actually runs — the assertion
    # cannot pass by accident on a suite that happens to run on that date, the
    # way it could if this merely compared against `date.today()`. Proves the
    # snapshot date comes from `_user_today`, not the server's own clock: the
    # true regression here would be an unconditional `date.today()` still
    # sitting between `_user_today` and the write, quietly overriding it.
    _sentinel_day = date(2031, 6, 15)
    monkeypatch.setattr(app_module, "_user_today", lambda tz: _sentinel_day)

    payload = app_module.AppleHealthPayload(steps=9000)
    result = await app_module._process_apple_health(payload, "tok-legacy-1")

    assert result["date"] == str(_sentinel_day)
    snap = await _snapshot(db, u.id, _sentinel_day)
    assert snap is not None and snap.steps == 9000


async def test_native_endpoint_omitted_date_uses_user_local_day(
        make_user, db, patched_health_sync_session, monkeypatch):
    hs_module = patched_health_sync_session
    u = await make_user(telegram_id="hk-native-1", name="Wrist", timezone="UTC")

    _sentinel_day = date(2031, 6, 15)
    monkeypatch.setattr(hs_module, "_user_today", lambda tz: _sentinel_day)

    payload = hs_module.HealthSnapshotBody(steps=9000)
    result = await hs_module.post_snapshot(payload, identity=u.telegram_id)

    assert result["date"] == str(_sentinel_day)
    snap = await _snapshot(db, u.id, _sentinel_day)
    assert snap is not None and snap.steps == 9000


async def test_explicit_date_still_wins_on_both_endpoints(
        make_user, db, patched_app_session, patched_health_sync_session):
    """A caller-supplied date is ground truth on either path — unaffected by
    the local-day default, which only fills in what nobody stated."""
    app_module = patched_app_session
    hs_module = patched_health_sync_session

    u1 = await make_user(telegram_id="hk-legacy-2", name="Wrist",
                         webhook_token="tok-legacy-2", timezone="America/Los_Angeles")
    payload1 = app_module.AppleHealthPayload(date="2026-02-10", steps=100)
    result1 = await app_module._process_apple_health(payload1, "tok-legacy-2")
    assert result1["date"] == "2026-02-10"
    assert await _snapshot(db, u1.id, date(2026, 2, 10)) is not None

    u2 = await make_user(telegram_id="hk-native-2", name="Wrist",
                         timezone="America/Los_Angeles")
    payload2 = hs_module.HealthSnapshotBody(date="2026-02-11", steps=200)
    result2 = await hs_module.post_snapshot(payload2, identity=u2.telegram_id)
    assert result2["date"] == "2026-02-11"
    assert await _snapshot(db, u2.id, date(2026, 2, 11)) is not None
