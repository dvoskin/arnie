"""
Tests for /api/v1/water (slice 4 — water quick-log REST endpoints).

Covers POST / PATCH / DELETE end-to-end against the same DB the chat-side
`log_water_entry` tool writes to, so a tap-the-glass UI log and a chat log
land in the same `water_entries` table with the same aggregate sync.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.water import (
    WaterLogBody,
    WaterUpdateBody,
    delete_water,
    log_water,
    update_water,
)
from db.models import DailyLog, WaterEntry


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Point `api.water.AsyncSessionLocal` at the test engine so the route
    handler reads/writes the same in-memory sqlite as the `db` fixture."""
    from api import water
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(water, "AsyncSessionLocal", session_factory)
    return session_factory


# ── POST ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_water_creates_entry_and_daily_log(
    patched_session_local, db, make_user,
):
    """First water log of the day → materializes today's DailyLog (if
    missing), inserts a WaterEntry row, returns the cached total."""
    user = await make_user(telegram_id="ios:water-user")

    resp = await log_water(
        WaterLogBody(amount_ml=240, context="after workout"),
        identity="ios:water-user",
    )

    assert resp["ok"] is True
    assert resp["total_water_ml"] == 240.0
    assert resp["entry_id"] > 0
    assert resp["daily_log_id"] > 0

    # The row is real — same table chat would have written to.
    entries = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()
    assert len(entries) == 1
    assert entries[0].amount_ml == 240.0
    assert entries[0].context == "after workout"
    assert entries[0].source_type == "ios"


@pytest.mark.asyncio
async def test_log_water_accumulates_total_across_calls(
    patched_session_local, db, make_user,
):
    """Two consecutive logs in the same day → total_water_ml is the sum,
    cached on DailyLog so the dashboard read path doesn't have to re-sum."""
    user = await make_user(telegram_id="ios:multi-log")

    first = await log_water(WaterLogBody(amount_ml=200), identity="ios:multi-log")
    second = await log_water(WaterLogBody(amount_ml=350), identity="ios:multi-log")

    assert first["total_water_ml"] == 200.0
    assert second["total_water_ml"] == 550.0
    assert first["daily_log_id"] == second["daily_log_id"]

    log = (await db.execute(
        select(DailyLog).where(DailyLog.user_id == user.id)
    )).scalar_one()
    assert log.total_water_ml == 550.0


@pytest.mark.asyncio
async def test_log_water_rejects_zero_and_negative(patched_session_local, make_user):
    """Pydantic gt=0 enforcement — a body that wouldn't represent a real
    hydration event is refused before any DB write."""
    await make_user(telegram_id="ios:bad-input")
    with pytest.raises(Exception):
        WaterLogBody(amount_ml=0)
    with pytest.raises(Exception):
        WaterLogBody(amount_ml=-100)


@pytest.mark.asyncio
async def test_log_water_rejects_silly_large_values(patched_session_local, make_user):
    """5L per single log is the cap (≈ 169 oz). Anything larger is almost
    certainly a unit-conversion bug client-side. Defense-in-depth."""
    await make_user(telegram_id="ios:huge-input")
    with pytest.raises(Exception):
        WaterLogBody(amount_ml=10_000)


# ── PATCH ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_water_changes_amount_and_resyncs_total(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:edit-water")
    first = await log_water(WaterLogBody(amount_ml=200), identity="ios:edit-water")
    await log_water(WaterLogBody(amount_ml=300), identity="ios:edit-water")

    resp = await update_water(
        first["entry_id"],
        WaterUpdateBody(amount_ml=500),
        identity="ios:edit-water",
    )

    assert resp["ok"] is True
    # Total reflects the edit: 500 (was 200) + 300 = 800.
    assert resp["total_water_ml"] == 800.0


@pytest.mark.asyncio
async def test_update_water_other_users_entry_returns_404(
    patched_session_local, db, make_user,
):
    """Ownership scoping — token A cannot mutate a row owned by user B.
    404 (not 403) so the existence of the row isn't leaked by the error
    shape."""
    await make_user(telegram_id="ios:owner-edit")
    await make_user(telegram_id="ios:attacker-edit")

    own = await log_water(WaterLogBody(amount_ml=200), identity="ios:owner-edit")

    with pytest.raises(HTTPException) as exc:
        await update_water(
            own["entry_id"],
            WaterUpdateBody(amount_ml=999),
            identity="ios:attacker-edit",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_water_missing_entry_returns_404(
    patched_session_local, make_user,
):
    await make_user(telegram_id="ios:ghost-edit")
    with pytest.raises(HTTPException) as exc:
        await update_water(
            999_999,
            WaterUpdateBody(amount_ml=100),
            identity="ios:ghost-edit",
        )
    assert exc.value.status_code == 404


# ── DELETE ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_water_removes_row_and_resyncs_total(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:delete-water")
    first = await log_water(WaterLogBody(amount_ml=200), identity="ios:delete-water")
    await log_water(WaterLogBody(amount_ml=300), identity="ios:delete-water")

    resp = await delete_water(first["entry_id"], identity="ios:delete-water")
    assert resp["ok"] is True

    remaining = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].amount_ml == 300.0

    log = (await db.execute(
        select(DailyLog).where(DailyLog.user_id == user.id)
    )).scalar_one()
    assert log.total_water_ml == 300.0


@pytest.mark.asyncio
async def test_delete_water_other_users_entry_returns_404(
    patched_session_local, db, make_user,
):
    await make_user(telegram_id="ios:owner-delete")
    await make_user(telegram_id="ios:attacker-delete")

    own = await log_water(WaterLogBody(amount_ml=250), identity="ios:owner-delete")

    with pytest.raises(HTTPException) as exc:
        await delete_water(own["entry_id"], identity="ios:attacker-delete")
    assert exc.value.status_code == 404

    # Owner's entry still present + total still 250.
    remaining = (await db.execute(
        select(WaterEntry).where(WaterEntry.id == own["entry_id"])
    )).scalar_one()
    assert remaining is not None
    assert remaining.amount_ml == 250.0
