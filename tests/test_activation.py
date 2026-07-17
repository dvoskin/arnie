"""Activation gates (core/activation.py) — earn-your-tabs unlock logic.

The contract under test:
  * Log unlocks at 2 lifetime food entries; Coach at 2 days ≥1000 kcal.
  * Unlocks persist (timestamps on the user row) and NEVER revert.
  * Grandfathered users (created before the feature epoch) are always unlocked.
  * persist=False computes the same answer without committing.
"""
from datetime import date, datetime, timedelta

import pytest

from core.activation import (
    get_activation, activation_context_line,
    LOG_UNLOCK_ENTRIES, COACH_UNLOCK_DAYS, QUALIFYING_DAY_KCAL, ACTIVATION_EPOCH,
)
from db.models import DailyLog, FoodEntry

pytestmark = pytest.mark.asyncio

# A creation date safely inside the gated era.
NEW_ERA = datetime.combine(ACTIVATION_EPOCH, datetime.min.time()) + timedelta(days=30)


async def _add_day(db, uid, d, calories, entries=0):
    log = DailyLog(user_id=uid, date=d, total_calories=calories)
    db.add(log)
    await db.flush()
    for i in range(entries):
        db.add(FoodEntry(daily_log_id=log.id, parsed_food_name=f"food{i}",
                         calories=calories / max(entries, 1)))
    await db.commit()
    return log


async def test_new_user_starts_fully_locked(db, make_user):
    u = await make_user(created_at=NEW_ERA)
    act = await get_activation(db, u)
    assert act["all_unlocked"] is False
    assert act["log"]["unlocked"] is False
    assert act["log"]["progress"] == 0 and act["log"]["goal"] == LOG_UNLOCK_ENTRIES
    assert act["coach"]["unlocked"] is False
    assert act["coach"]["kcal_per_day"] == QUALIFYING_DAY_KCAL


async def test_log_unlocks_at_two_entries_and_persists(db, make_user):
    u = await make_user(created_at=NEW_ERA)
    await _add_day(db, u.id, date(2026, 8, 20), 400, entries=1)
    act = await get_activation(db, u)
    assert act["log"]["unlocked"] is False and act["log"]["progress"] == 1

    await _add_day(db, u.id, date(2026, 8, 21), 300, entries=1)
    act = await get_activation(db, u)
    assert act["log"]["unlocked"] is True
    assert u.log_unlocked_at is not None
    # Coach still locked — no qualifying days yet.
    assert act["coach"]["unlocked"] is False


async def test_coach_unlocks_at_two_qualifying_days(db, make_user):
    u = await make_user(created_at=NEW_ERA)
    await _add_day(db, u.id, date(2026, 8, 20), 1450, entries=2)
    act = await get_activation(db, u)
    assert act["coach"]["progress"] == 1 and act["coach"]["unlocked"] is False

    # A thin day does NOT count toward Coach…
    await _add_day(db, u.id, date(2026, 8, 21), QUALIFYING_DAY_KCAL - 1, entries=1)
    act = await get_activation(db, u)
    assert act["coach"]["progress"] == 1

    # …a full second day does.
    await _add_day(db, u.id, date(2026, 8, 22), 2100, entries=3)
    act = await get_activation(db, u)
    assert act["coach"]["unlocked"] is True and act["all_unlocked"] is True
    assert u.coach_unlocked_at is not None


async def test_unlock_never_reverts_after_entries_deleted(db, make_user):
    u = await make_user(created_at=NEW_ERA)
    log = await _add_day(db, u.id, date(2026, 8, 20), 1500, entries=2)
    await _add_day(db, u.id, date(2026, 8, 21), 1500, entries=2)
    act = await get_activation(db, u)
    assert act["all_unlocked"] is True

    # User deletes everything — the earned timestamps must keep the tabs open.
    await db.delete(log)
    await db.commit()
    act = await get_activation(db, u)
    assert act["all_unlocked"] is True
    assert act["log"]["unlocked"] and act["coach"]["unlocked"]


async def test_grandfathered_user_is_always_unlocked(db, make_user):
    u = await make_user(created_at=datetime(2026, 6, 1))  # pre-epoch beta user
    act = await get_activation(db, u)
    assert act["all_unlocked"] is True
    # And the runtime net persisted the seed for next time.
    assert u.log_unlocked_at is not None and u.coach_unlocked_at is not None


async def test_missing_created_at_never_locks(db, make_user):
    # A row with no creation timestamp predates reliable bookkeeping — never lock.
    u = await make_user()
    u.created_at = None
    await db.commit()
    act = await get_activation(db, u)
    assert act["all_unlocked"] is True


async def test_persist_false_reads_without_committing(db, make_user):
    u = await make_user(created_at=NEW_ERA)
    await _add_day(db, u.id, date(2026, 8, 20), 1500, entries=2)
    await _add_day(db, u.id, date(2026, 8, 21), 1500, entries=2)

    act = await get_activation(db, u, persist=False)
    assert act["all_unlocked"] is True          # computed answer is right…
    assert u.log_unlocked_at is None            # …but nothing was written
    assert u.coach_unlocked_at is None

    # The next persisting read owns the flip.
    act = await get_activation(db, u)
    assert u.log_unlocked_at is not None and u.coach_unlocked_at is not None


async def test_progress_is_capped_at_goal(db, make_user):
    u = await make_user(created_at=NEW_ERA)
    await _add_day(db, u.id, date(2026, 8, 20), 1500, entries=6)
    act = await get_activation(db, u)
    assert act["log"]["progress"] == LOG_UNLOCK_ENTRIES  # 6 entries reads as 2/2


async def test_context_line_only_exists_while_locked():
    locked = {
        "all_unlocked": False,
        "log": {"unlocked": False, "progress": 1, "goal": 2},
        "coach": {"unlocked": False, "progress": 0, "goal": 2, "kcal_per_day": 1000},
    }
    line = activation_context_line(locked)
    assert line and "[ACTIVATION]" in line and "1/2" in line

    assert activation_context_line({"all_unlocked": True}) is None
