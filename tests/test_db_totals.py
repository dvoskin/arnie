"""DailyLog totals + workout/cardio flags must be DERIVED from entries and never
drift — the bug class that corrupted dashboards this session."""
import datetime as dt
import pytest
from sqlalchemy import select

from db.models import DailyLog
from db.queries import (
    add_food_entry, update_food_entry, delete_food_entry,
    add_exercise_entry, delete_exercise_entry,
    get_or_create_log_for_date, recompute_log_totals,
)

DAY = dt.date(2026, 5, 29)


async def _cal(db, lid):
    return (await db.execute(select(DailyLog).where(DailyLog.id == lid))).scalar_one().total_calories


async def _flags(db, lid):
    lg = (await db.execute(select(DailyLog).where(DailyLog.id == lid))).scalar_one()
    return lg.workout_completed, lg.cardio_completed


async def test_food_totals_derive_through_add_update_delete(make_user, db):
    u = await make_user()
    lg = await get_or_create_log_for_date(db, u.id, DAY)
    e1 = await add_food_entry(db, lg.id, parsed_food_name="eggs", calories=140, protein=12, carbs=1, fats=10)
    e2 = await add_food_entry(db, lg.id, parsed_food_name="rice", calories=200, protein=4, carbs=44, fats=1)
    assert await _cal(db, lg.id) == 340
    await update_food_entry(db, e1.id, u.id, calories=200)
    assert await _cal(db, lg.id) == 400
    await delete_food_entry(db, e2.id, u.id)
    assert await _cal(db, lg.id) == 200


async def test_recompute_heals_drift(make_user, db):
    u = await make_user()
    lg = await get_or_create_log_for_date(db, u.id, DAY)
    await add_food_entry(db, lg.id, parsed_food_name="eggs", calories=140, protein=12)
    # Simulate drift, then heal
    lg2 = (await db.execute(select(DailyLog).where(DailyLog.id == lg.id))).scalar_one()
    lg2.total_calories = 99999
    await db.commit()
    await recompute_log_totals(db, lg.id)
    await db.commit()
    assert await _cal(db, lg.id) == 140


async def test_exercise_flags_derive_and_delete_returns_true(make_user, db):
    u = await make_user()
    lg = await get_or_create_log_for_date(db, u.id, DAY)
    e1 = await add_exercise_entry(db, lg.id, exercise_name="bench", sets=4, reps="5")
    assert await _flags(db, lg.id) == (True, False)
    e2 = await add_exercise_entry(db, lg.id, exercise_name="jog", duration_minutes=30)  # duration-only = cardio
    assert await _flags(db, lg.id) == (True, True)
    ok = await delete_exercise_entry(db, e1.id, u.id)
    assert ok is True                       # was missing-return bug
    assert await _flags(db, lg.id) == (False, True)
    await delete_exercise_entry(db, e2.id, u.id)
    assert await _flags(db, lg.id) == (False, False)
