"""
Regression tests for full-account reset (reset_all_user_data).

CRITICAL: these run against SQLite with foreign keys ENFORCED (PRAGMA
foreign_keys=ON) so they reproduce the production Postgres behavior. The original
bug: reset deleted DailyLog rows while FoodEntry/ExerciseEntry children still
referenced them, which raised a FK violation on Postgres and rolled back the entire
wipe — so "reset" left all the user's data intact. With FKs enforced here, a
regression to bulk-deleting parents-before-children fails this test loudly.
"""
import pytest
import pytest_asyncio
from datetime import date, datetime
from sqlalchemy import event, select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.database import Base, _migrate
from db import models  # noqa: F401 (registers tables)
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry, ExerciseEntry, BodyMetric,
    ConversationLog, MemoryUpdate, HealthSnapshot, WearableDevice, WearableMetric,
    PendingQuestion, Feedback, UserFoodMatch,
)
from db.queries import reset_all_user_data


@pytest_asyncio.fixture
async def fk_engine():
    """In-memory SQLite with foreign-key enforcement ON (mirrors Postgres)."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(eng.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(fk_engine):
    Session = async_sessionmaker(fk_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


async def _seed_full_user(db) -> int:
    """Create a user with at least one row in every user-scoped table."""
    u = User(
        telegram_id="im:+15550001111", name="Daniel", onboarding_completed=True,
        current_weight_kg=86.0, goal_weight_kg=80.0, primary_goal="cut",
        city="NYC", sport="boxing", active_mission="hit 180g protein",
        mission_metric="protein", mission_target=180, mission_date="2026-06-01",
        whoop_refresh_token="tok", whoop_user_id="w123", nudges_sent="slot1",
        # preserved-through-reset fields:
        subscription_status="active", stripe_customer_id="cus_123",
        linked_to_user_id=999, channel_preference="imessage",
    )
    db.add(u)
    await db.flush()
    uid = u.id

    db.add(UserPreferences(user_id=uid, calorie_target=2000, protein_target=180,
                           proactive_messaging_enabled=True, coaching_style="aggressive"))

    log = DailyLog(user_id=uid, date=date.today(), total_calories=1500)
    db.add(log)
    await db.flush()
    db.add(FoodEntry(daily_log_id=log.id, parsed_food_name="eggs", calories=200))
    db.add(ExerciseEntry(daily_log_id=log.id, exercise_name="bench", sets=4))

    db.add(BodyMetric(user_id=uid, weight_kg=86.0))
    db.add(ConversationLog(user_id=uid, raw_message="hi", response="hey"))
    db.add(MemoryUpdate(user_id=uid, update_summary="likes mornings"))
    db.add(HealthSnapshot(user_id=uid, date=date.today(), steps=8000))
    db.add(WearableDevice(user_id=uid, device_type="whoop"))
    db.add(WearableMetric(user_id=uid, device_type="whoop", metric_type="hrv",
                          value=55.0, recorded_at=datetime.utcnow()))
    db.add(PendingQuestion(user_id=uid, kind="profile_stats", question="how tall?"))
    db.add(Feedback(user_id=uid, text="love it"))
    db.add(UserFoodMatch(user_id=uid, name_norm="royo bagel", display_name="Royo Bagel"))
    await db.commit()
    return uid


async def _count(db, model, uid=None) -> int:
    stmt = select(func.count()).select_from(model)
    if uid is not None and hasattr(model, "user_id"):
        stmt = stmt.where(model.user_id == uid)
    return (await db.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_reset_deletes_all_user_data_with_fks_enforced(db):
    """The whole point: with FKs ON, reset must not roll back, and every
    user-scoped table (including DailyLog children) ends empty."""
    uid = await _seed_full_user(db)

    # sanity: data exists before reset
    assert await _count(db, FoodEntry) == 1
    assert await _count(db, UserFoodMatch, uid) == 1

    await reset_all_user_data(db, uid)

    # child tables of daily_logs
    assert await _count(db, FoodEntry) == 0, "FoodEntry survived reset (FK rollback?)"
    assert await _count(db, ExerciseEntry) == 0
    # everything keyed by user_id
    for model in (DailyLog, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
                  WearableDevice, WearableMetric, PendingQuestion, Feedback, UserFoodMatch):
        assert await _count(db, model, uid) == 0, f"{model.__name__} survived reset"


@pytest.mark.asyncio
async def test_reset_wipes_profile_and_forces_reonboarding(db):
    uid = await _seed_full_user(db)
    await reset_all_user_data(db, uid)

    u = (await db.execute(select(User).where(User.id == uid))).scalar_one()
    # profile + coaching state cleared
    assert u.name is None and u.current_weight_kg is None and u.primary_goal is None
    assert u.city is None and u.sport is None
    assert u.active_mission is None and u.mission_metric is None
    assert u.whoop_refresh_token is None and u.whoop_user_id is None
    assert u.nudges_sent == ""
    assert u.onboarding_completed is False
    assert u.timezone == "UTC"


@pytest.mark.asyncio
async def test_reset_preserves_identity_link_and_billing(db):
    """A data wipe must NOT cost the user their account, cross-platform link, or
    paid subscription."""
    uid = await _seed_full_user(db)
    await reset_all_user_data(db, uid)

    u = (await db.execute(select(User).where(User.id == uid))).scalar_one()
    assert u.telegram_id == "im:+15550001111"          # account survives
    assert u.linked_to_user_id == 999                  # cross-platform link survives
    assert u.channel_preference == "imessage"
    assert u.subscription_status == "active"           # billing survives
    assert u.stripe_customer_id == "cus_123"


@pytest.mark.asyncio
async def test_reset_resets_preferences(db):
    uid = await _seed_full_user(db)
    await reset_all_user_data(db, uid)

    p = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == uid)
    )).scalar_one()
    assert p.calorie_target is None and p.protein_target is None
    assert p.coaching_style == "balanced"
    assert p.proactive_messaging_enabled is False
