"""Linking an iOS account that already has logged data MERGES it onto the
canonical row instead of orphaning it (the old 422 beta blocker). Covers the
same-date merge + the plain repoint + weight move."""
from datetime import date

import pytest
from sqlalchemy import func, select

from db.models import DailyLog, FoodEntry
from db.queries import (
    add_body_metric,
    add_food_entry,
    get_or_create_log_for_date,
    migrate_user_data,
)


@pytest.mark.asyncio
async def test_migrate_merges_same_day_and_repoints_rest(db, make_user):
    consumer = await make_user(telegram_id="ios:consumer")
    canonical = await make_user(telegram_id="123456")     # Telegram owner

    # consumer: Jun 1 (canonical lacks it → repoint) + Jun 2 (canonical has it → merge)
    c1 = await get_or_create_log_for_date(db, consumer.id, date(2026, 6, 1))
    await add_food_entry(db, c1.id, parsed_food_name="oats", calories=300, protein=10, carbs=50, fats=5)
    c2 = await get_or_create_log_for_date(db, consumer.id, date(2026, 6, 2))
    await add_food_entry(db, c2.id, parsed_food_name="eggs", calories=200, protein=18, carbs=1, fats=14)
    k2 = await get_or_create_log_for_date(db, canonical.id, date(2026, 6, 2))
    await add_food_entry(db, k2.id, parsed_food_name="chicken", calories=250, protein=40, carbs=0, fats=8)
    await add_body_metric(db, consumer.id, weight_kg=80.0)

    stats = await migrate_user_data(db, consumer, canonical)
    assert stats["days_moved"] == 1
    assert stats["days_merged"] == 1
    assert stats["weights"] == 1

    # consumer owns nothing now; canonical owns both days
    c_count = (await db.execute(
        select(func.count(DailyLog.id)).where(DailyLog.user_id == consumer.id))).scalar_one()
    assert c_count == 0
    k_logs = (await db.execute(
        select(DailyLog).where(DailyLog.user_id == canonical.id))).scalars().all()
    assert {l.date for l in k_logs} == {date(2026, 6, 1), date(2026, 6, 2)}

    # Jun 2 merged → BOTH the canonical's chicken and the consumer's eggs
    jun2 = next(l for l in k_logs if l.date == date(2026, 6, 2))
    foods = (await db.execute(
        select(FoodEntry).where(FoodEntry.daily_log_id == jun2.id))).scalars().all()
    assert {f.parsed_food_name for f in foods} == {"chicken", "eggs"}


@pytest.mark.asyncio
async def test_migrate_noop_on_self(db, make_user):
    user = await make_user(telegram_id="ios:self")
    assert await migrate_user_data(db, user, user) == {}
