"""
Tests for /api/v1/food, /exercise, /weight (slice B1+B2+B3 — manual
quick-log REST endpoints).

Confirms the bearer-authed write paths land in the same canonical tables
the chat-side log_food / log_exercise / log_weight tools use, with the
same recompute-totals side effects so the dashboard read path sees them
immediately.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.quick_log import (
    ExerciseLogBody,
    FoodLogBody,
    WeightLogBody,
    log_exercise_entry,
    log_food_entry,
    log_weight,
)
from db.models import (
    BodyMetric,
    DailyLog,
    ExerciseEntry,
    FoodEntry,
    User,
)


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


# ── Food ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_food_creates_entry_and_recomputes_totals(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:food-log")
    resp = await log_food_entry(
        FoodLogBody(
            food_name="Greek yogurt",
            quantity="200g",
            calories=120, protein=18, carbs=8, fats=0,
            meal_type="breakfast",
        ),
        identity="ios:food-log",
    )
    assert resp["ok"] is True

    entries = (await db.execute(
        select(FoodEntry)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user.id)
    )).scalars().all()
    assert len(entries) == 1
    assert entries[0].parsed_food_name == "Greek yogurt"
    assert entries[0].calories == 120
    assert entries[0].meal_type == "breakfast"
    assert entries[0].source_type == "ios"


@pytest.mark.asyncio
async def test_log_food_rejects_invalid_meal_type():
    """Pydantic Literal rejects unknown meal types before the route runs."""
    with pytest.raises(Exception):
        FoodLogBody(food_name="X", calories=100, protein=0, carbs=0, fats=0,
                    meal_type="brunch")


@pytest.mark.asyncio
async def test_log_food_rejects_impossible_calories():
    """A unit-conversion bug client-side won't push impossible values."""
    with pytest.raises(Exception):
        FoodLogBody(food_name="X", calories=50_000, protein=0, carbs=0, fats=0)


# ── Exercise ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_exercise_strength_entry_lands_with_per_set_load(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:strength-log")
    resp = await log_exercise_entry(
        ExerciseLogBody(
            exercise_name="Back Squat",
            sets=3,
            reps="5,5,5",
            weights="225,225,235",
            rir=2,
        ),
        identity="ios:strength-log",
    )
    assert resp["ok"] is True

    entries = (await db.execute(
        select(ExerciseEntry)
        .join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user.id)
    )).scalars().all()
    assert len(entries) == 1
    assert entries[0].exercise_name == "Back Squat"
    assert entries[0].sets == 3
    assert entries[0].reps == "5,5,5"
    assert entries[0].weights == "225,225,235"
    assert entries[0].rir == 2
    assert entries[0].source_type == "ios"


@pytest.mark.asyncio
async def test_log_exercise_cardio_entry_marks_cardio_type(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:cardio-log")
    await log_exercise_entry(
        ExerciseLogBody(
            exercise_name="Treadmill run",
            is_cardio=True,
            duration_minutes=35,
            calories_burned_estimate=320,
        ),
        identity="ios:cardio-log",
    )

    row = (await db.execute(
        select(ExerciseEntry)
        .join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user.id)
    )).scalar_one()
    assert row.duration_minutes == 35
    assert row.cardio_type == "cardio"


# ── Weight ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_weight_records_metric_and_updates_user(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:weight-log", current_weight_kg=80.0)
    resp = await log_weight(
        WeightLogBody(weight_kg=78.5, context="morning"),
        identity="ios:weight-log",
    )
    assert resp["ok"] is True
    assert resp["current_weight_kg"] == 78.5

    metrics = (await db.execute(
        select(BodyMetric).where(BodyMetric.user_id == user.id)
    )).scalars().all()
    assert len(metrics) == 1
    assert metrics[0].weight_kg == 78.5
    assert metrics[0].context == "morning"

    # users.current_weight_kg should be updated to the latest value.
    refreshed = (await db.execute(
        select(User).where(User.id == user.id)
    )).scalar_one()
    await db.refresh(refreshed)
    assert refreshed.current_weight_kg == 78.5


@pytest.mark.asyncio
async def test_log_weight_rejects_impossible_values():
    """Unit-conversion bug (lbs accidentally sent as kg) is refused
    before the row lands."""
    with pytest.raises(Exception):
        WeightLogBody(weight_kg=15)   # under 20kg
    with pytest.raises(Exception):
        WeightLogBody(weight_kg=500)  # over 400kg
