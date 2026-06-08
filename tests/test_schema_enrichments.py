"""
T2.3-T2.5 — Schema enrichments tests.

T2.3: FoodEntry.meal_type + meal_time + alcohol_units + from_photo
T2.4: WaterEntry timestamped table (DailyLog.total_water_ml stays cached)
T2.5: BodyMetric.context

These tests verify the schema additions land correctly, the tool schemas
expose the new fields, and the executor persists them.
"""
import pytest
from datetime import datetime


# ── Tool schema surface ─────────────────────────────────────────────────────


def test_log_food_schema_exposes_meal_type():
    from core.tools import build_tools
    tool = next(t for t in build_tools() if t["name"] == "log_food")
    props = tool["input_schema"]["properties"]
    assert "meal_type" in props
    assert "breakfast" in props["meal_type"]["enum"]
    assert "pre_workout" in props["meal_type"]["enum"]


def test_log_food_schema_exposes_alcohol_units_and_from_photo():
    from core.tools import build_tools
    tool = next(t for t in build_tools() if t["name"] == "log_food")
    props = tool["input_schema"]["properties"]
    assert "alcohol_units" in props
    assert "from_photo" in props


def test_log_water_schema_exposes_context_and_date():
    from core.tools import build_tools
    tool = next(t for t in build_tools() if t["name"] == "log_water")
    props = tool["input_schema"]["properties"]
    assert "context" in props
    assert "morning" in props["context"]["enum"]
    assert "post_workout" in props["context"]["enum"]
    assert "date" in props  # past-day water correction


def test_log_body_weight_schema_exposes_context():
    from core.tools import build_tools
    tool = next(t for t in build_tools() if t["name"] == "log_body_weight")
    props = tool["input_schema"]["properties"]
    assert "context" in props
    enum = props["context"]["enum"]
    for ctx in ("morning_fasted", "post_meal", "evening", "post_workout", "unknown"):
        assert ctx in enum


# ── Model fields exist (migration applied) ───────────────────────────────────


def test_food_entry_model_has_new_fields():
    from db.models import FoodEntry
    columns = {c.name for c in FoodEntry.__table__.columns}
    assert {"meal_type", "meal_time", "alcohol_units",
            "micronutrients_json", "from_photo"} <= columns


def test_body_metric_model_has_context_field():
    from db.models import BodyMetric
    columns = {c.name for c in BodyMetric.__table__.columns}
    assert "context" in columns


def test_water_entry_model_exists_with_canonical_shape():
    from db.models import WaterEntry
    columns = {c.name for c in WaterEntry.__table__.columns}
    expected = {"id", "user_id", "daily_log_id", "amount_ml",
                "context", "source_type", "timestamp"}
    assert expected <= columns


# ── Executor persists new fields end-to-end ──────────────────────────────────


@pytest.mark.asyncio
async def test_log_food_persists_meal_type_and_from_photo(make_user, db):
    """log_food with meal_type + from_photo → FoodEntry row carries them."""
    from sqlalchemy import select
    from db.models import FoodEntry
    from db.queries import get_or_create_today_log, reload_user
    from handlers.tool_executor import _dispatch

    user = await make_user(telegram_id="t231")
    log = await get_or_create_today_log(db, user.id, "UTC")
    # Eager-load preferences relationship — log_food's result string reads
    # user.preferences for the calorie / protein target hints.
    user = await reload_user(db, user.id)

    await _dispatch("log_food",
        {"food_name": "chipotle bowl", "quantity": "1 bowl",
         "calories": 890, "protein": 50, "carbs": 95, "fats": 28,
         "confidence": 0.8, "meal_type": "lunch", "from_photo": True},
        user, log, db, source_type="text",
    )

    entries = (await db.execute(
        select(FoodEntry).where(FoodEntry.daily_log_id == log.id)
    )).scalars().all()
    assert len(entries) == 1
    e = entries[0]
    assert e.meal_type == "lunch"
    assert e.from_photo is True
    # from_photo caps confidence at 0.75 even though we passed 0.8.
    assert e.confidence_score <= 0.75
    assert e.estimated_flag is True
    assert e.meal_time is not None


@pytest.mark.asyncio
async def test_log_body_weight_persists_context(make_user, db):
    """log_body_weight with context → BodyMetric row carries it."""
    from sqlalchemy import select
    from db.models import BodyMetric
    from handlers.tool_executor import _dispatch
    from types import SimpleNamespace

    user = await make_user(telegram_id="t232")
    fake_log = SimpleNamespace(
        id=None, total_calories=0, total_protein=0, total_carbs=0,
        total_fats=0, total_water_ml=0,
        workout_completed=False, cardio_completed=False,
        food_entries=[], exercise_entries=[],
    )

    await _dispatch("log_body_weight",
        {"weight": 184, "unit": "lbs", "context": "morning_fasted"},
        user, fake_log, db, source_type="text",
    )

    metrics = (await db.execute(
        select(BodyMetric).where(BodyMetric.user_id == user.id)
    )).scalars().all()
    assert len(metrics) == 1
    assert metrics[0].context == "morning_fasted"
    assert abs(metrics[0].weight_kg - 184 * 0.453592) < 0.01


@pytest.mark.asyncio
async def test_log_water_creates_water_entry_and_updates_aggregate(make_user, db):
    """log_water writes BOTH a WaterEntry row AND updates DailyLog.total_water_ml."""
    from sqlalchemy import select
    from db.models import WaterEntry
    from db.queries import get_or_create_today_log
    from handlers.tool_executor import _dispatch

    user = await make_user(telegram_id="t233")
    log = await get_or_create_today_log(db, user.id, "UTC")

    await _dispatch("log_water",
        {"amount_ml": 500, "context": "morning"},
        user, log, db, source_type="text",
    )

    # WaterEntry row created
    entries = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()
    assert len(entries) == 1
    assert entries[0].amount_ml == 500
    assert entries[0].context == "morning"
    assert entries[0].daily_log_id == log.id

    # DailyLog aggregate updated alongside
    await db.refresh(log)
    assert log.total_water_ml == 500
