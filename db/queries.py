from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import selectinload
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry,
    ExerciseEntry, BodyMetric, ConversationLog, MemoryUpdate,
)
from datetime import date, datetime, timedelta
from typing import Optional, List
import pytz


async def get_or_create_user(db: AsyncSession, telegram_id: str) -> User:
    result = await db.execute(
        select(User)
        .where(User.telegram_id == telegram_id)
        .options(selectinload(User.preferences))
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(telegram_id=telegram_id)
        db.add(user)
        prefs = UserPreferences(user=user)
        db.add(prefs)
        await db.commit()
        await db.refresh(user)
        # Re-load with relationships
        result = await db.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.preferences))
        )
        user = result.scalar_one()

    return user


def _user_today(user_timezone: str) -> date:
    tz = pytz.timezone(user_timezone or "UTC")
    return datetime.now(tz).date()


async def get_today_log(db: AsyncSession, user_id: int,
                        user_timezone: str = "UTC") -> Optional[DailyLog]:
    today = _user_today(user_timezone)
    result = await db.execute(
        select(DailyLog)
        .where(and_(DailyLog.user_id == user_id, DailyLog.date == today))
        .options(
            selectinload(DailyLog.food_entries),
            selectinload(DailyLog.exercise_entries),
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_today_log(db: AsyncSession, user_id: int,
                                  user_timezone: str = "UTC") -> DailyLog:
    log = await get_today_log(db, user_id, user_timezone)
    if not log:
        today = _user_today(user_timezone)
        log = DailyLog(user_id=user_id, date=today)
        db.add(log)
        await db.commit()
        log = await get_today_log(db, user_id, user_timezone)
    return log


async def add_food_entry(db: AsyncSession, daily_log_id: int, **kwargs) -> FoodEntry:
    entry = FoodEntry(daily_log_id=daily_log_id, **kwargs)
    db.add(entry)

    result = await db.execute(select(DailyLog).where(DailyLog.id == daily_log_id))
    log = result.scalar_one()
    log.total_calories = (log.total_calories or 0) + (kwargs.get("calories") or 0)
    log.total_protein = (log.total_protein or 0) + (kwargs.get("protein") or 0)
    log.total_carbs = (log.total_carbs or 0) + (kwargs.get("carbs") or 0)
    log.total_fats = (log.total_fats or 0) + (kwargs.get("fats") or 0)

    await db.commit()
    await db.refresh(entry)
    return entry


async def add_exercise_entry(db: AsyncSession, daily_log_id: int,
                              is_cardio: bool = False, **kwargs) -> ExerciseEntry:
    entry = ExerciseEntry(daily_log_id=daily_log_id, **kwargs)
    db.add(entry)

    result = await db.execute(select(DailyLog).where(DailyLog.id == daily_log_id))
    log = result.scalar_one()
    if is_cardio or kwargs.get("cardio_type"):
        log.cardio_completed = True
    else:
        log.workout_completed = True

    await db.commit()
    await db.refresh(entry)
    return entry


async def add_body_metric(db: AsyncSession, user_id: int,
                          weight_kg: float, **kwargs) -> BodyMetric:
    metric = BodyMetric(user_id=user_id, weight_kg=weight_kg, **kwargs)
    db.add(metric)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.current_weight_kg = weight_kg

    await db.commit()
    await db.refresh(metric)
    return metric


async def get_recent_weights(db: AsyncSession, user_id: int,
                             days: int = 14) -> List[BodyMetric]:
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(BodyMetric)
        .where(and_(BodyMetric.user_id == user_id, BodyMetric.timestamp >= since))
        .order_by(desc(BodyMetric.timestamp))
    )
    return result.scalars().all()


async def get_recent_logs(db: AsyncSession, user_id: int,
                          days: int = 7) -> List[DailyLog]:
    since = date.today() - timedelta(days=days)
    result = await db.execute(
        select(DailyLog)
        .where(and_(DailyLog.user_id == user_id, DailyLog.date >= since))
        .options(
            selectinload(DailyLog.food_entries),
            selectinload(DailyLog.exercise_entries),
        )
        .order_by(desc(DailyLog.date))
    )
    return result.scalars().all()


async def get_recent_conversations(db: AsyncSession, user_id: int,
                                   limit: int = 8) -> List[ConversationLog]:
    result = await db.execute(
        select(ConversationLog)
        .where(ConversationLog.user_id == user_id)
        .order_by(desc(ConversationLog.timestamp))
        .limit(limit)
    )
    return result.scalars().all()


async def log_conversation(db: AsyncSession, user_id: int, raw_message: str,
                           response: str, parsed_intent: str = None,
                           source_type: str = "text"):
    entry = ConversationLog(
        user_id=user_id,
        raw_message=raw_message,
        parsed_intent=parsed_intent,
        response=response,
        source_type=source_type,
    )
    db.add(entry)
    await db.commit()


async def close_daily_log(db: AsyncSession, log_id: int) -> DailyLog:
    result = await db.execute(select(DailyLog).where(DailyLog.id == log_id))
    log = result.scalar_one()
    log.status = "closed"
    await db.commit()
    return log


async def reload_user(db: AsyncSession, user_id: int) -> User:
    """Re-query a user with all relationships eagerly loaded."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.preferences))
    )
    return result.scalar_one()


async def get_all_active_users(db: AsyncSession) -> List[User]:
    result = await db.execute(
        select(User)
        .where(User.onboarding_completed == True)
        .options(selectinload(User.preferences))
    )
    return result.scalars().all()
