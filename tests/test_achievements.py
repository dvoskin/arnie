"""Achievements engine (core/achievements.py) — quiet trophies, loud moments.

The contract under test:
  * Badges award ONCE (idempotent), based on real aggregate counts.
  * Several badges in one turn → one `primary` (highest rank), all in `new`.
  * `effect_taken` mutes the celebration; the badge still lands.
  * A badge earned earlier today mutes later celebrations (one/day).
  * badge_wall returns the full registry in order with earned_at markers.
"""
from datetime import date, datetime, timedelta

import pytest

from core.achievements import (
    BADGES, check_achievements, badge_wall,
)
from db.models import Achievement, DailyLog, ExerciseEntry, FoodEntry

pytestmark = pytest.mark.asyncio


async def _add_day(db, uid, d, calories=500, foods=0, workouts=0,
                   protein=0.0, from_photo=False):
    log = DailyLog(user_id=uid, date=d, total_calories=calories,
                   total_protein=protein)
    db.add(log)
    await db.flush()
    for i in range(foods):
        db.add(FoodEntry(daily_log_id=log.id, parsed_food_name=f"food{i}",
                         calories=300, from_photo=from_photo))
    for i in range(workouts):
        db.add(ExerciseEntry(daily_log_id=log.id, exercise_name=f"lift{i}"))
    await db.commit()
    return log


async def test_registry_integrity():
    ids = [b["id"] for b in BADGES]
    assert len(ids) == len(set(ids)), "duplicate badge ids"
    for b in BADGES:
        assert b["tier"] in ("big", "small")
        assert b["line"] and b["title"] and b["icon"] and b["rank"] > 0


async def test_first_food_awards_once(db, make_user):
    u = await make_user()
    await _add_day(db, u.id, date(2026, 7, 10), foods=1)
    ach = await check_achievements(db, u)
    assert ach is not None and "first_food" in ach["new"]

    # Second check with no new data: nothing new, no duplicate row.
    again = await check_achievements(db, u)
    assert again is None or "first_food" not in (again["new"] if again else [])
    rows = [b for b in await badge_wall(db, u) if b["id"] == "first_food"]
    assert rows[0]["earned_at"] is not None


async def test_primary_is_highest_rank_and_photo_counts(db, make_user):
    u = await make_user()
    # 3-day streak + first food + first photo all land in one check.
    for i in range(3):
        await _add_day(db, u.id, date(2026, 7, 10) + timedelta(days=i),
                       calories=1200, foods=1, from_photo=True)
    ach = await check_achievements(db, u)
    assert ach is not None
    assert {"first_food", "first_photo", "streak_3"} <= set(ach["new"])
    assert ach["primary"]["id"] == "streak_3"          # big > small
    assert ach["primary"]["tier"] == "big"


async def test_effect_taken_mutes_celebration_but_awards(db, make_user):
    u = await make_user()
    await _add_day(db, u.id, date(2026, 7, 10), foods=1)
    ach = await check_achievements(db, u, effect_taken=True)
    assert ach is not None and ach["celebrate"] is False
    assert "first_food" in ach["new"]


async def test_one_celebration_per_day(db, make_user):
    u = await make_user()
    # A badge already earned today → later badges land quietly.
    db.add(Achievement(user_id=u.id, badge_id="first_photo",
                       earned_at=datetime.utcnow()))
    await db.commit()
    await _add_day(db, u.id, date(2026, 7, 10), foods=1)
    ach = await check_achievements(db, u)
    assert ach is not None and "first_food" in ach["new"]
    assert ach["celebrate"] is False


async def test_workout_and_protein_badges(db, make_user):
    u = await make_user()
    u.protein_target = 150
    for i in range(7):
        await _add_day(db, u.id, date(2026, 7, 1) + timedelta(days=i),
                       workouts=2, protein=160)
    ach = await check_achievements(db, u)
    assert ach is not None
    assert {"first_workout", "workouts_10", "protein_7"} <= set(ach["new"])


async def test_badge_wall_full_registry_in_order(db, make_user):
    u = await make_user()
    wall = await badge_wall(db, u)
    assert [b["id"] for b in wall] == [b["id"] for b in BADGES]
    assert all(b["earned_at"] is None for b in wall)
