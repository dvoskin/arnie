from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, delete
from sqlalchemy.orm import selectinload
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry,
    ExerciseEntry, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
    Feedback,
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


async def get_log_by_date(db: AsyncSession, user_id: int, target_date: date) -> Optional[DailyLog]:
    """Fetch a specific day's log with food/exercise entries eagerly loaded."""
    result = await db.execute(
        select(DailyLog)
        .where(and_(DailyLog.user_id == user_id, DailyLog.date == target_date))
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
    # Add 1-day buffer to avoid UTC edge cases near midnight
    since = date.today() - timedelta(days=days + 1)
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


async def reopen_daily_log(db: AsyncSession, log_id: int) -> DailyLog:
    result = await db.execute(select(DailyLog).where(DailyLog.id == log_id))
    log = result.scalar_one()
    log.status = "open"
    await db.commit()
    return log


async def clear_today_conversations(db: AsyncSession, user_id: int) -> None:
    """Delete all conversation history for a user — called after /reset today."""
    await db.execute(delete(ConversationLog).where(ConversationLog.user_id == user_id))
    await db.commit()


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


async def reset_today_log(db: AsyncSession, user_id: int, user_timezone: str = "UTC") -> bool:
    """
    Wipe all food and exercise entries for today and zero out the daily totals.
    Returns True if a log existed, False if there was nothing to reset.
    """
    log = await get_today_log(db, user_id, user_timezone)
    if not log:
        return False

    await db.execute(delete(FoodEntry).where(FoodEntry.daily_log_id == log.id))
    await db.execute(delete(ExerciseEntry).where(ExerciseEntry.daily_log_id == log.id))

    log.total_calories = 0
    log.total_protein = 0
    log.total_carbs = 0
    log.total_fats = 0
    log.total_water_ml = 0
    log.workout_completed = False
    log.cardio_completed = False
    log.status = "open"
    await db.commit()
    return True


async def reset_all_user_data(db: AsyncSession, user_id: int) -> None:
    """
    Full account wipe — deletes all logs, metrics, conversations, and memory.
    Resets profile fields and forces re-onboarding. Keeps the user row itself
    (same telegram_id) so the user can start fresh without needing a new account.
    """
    # Cascade-delete all daily logs (and their food/exercise entries)
    await db.execute(delete(DailyLog).where(DailyLog.user_id == user_id))
    await db.execute(delete(BodyMetric).where(BodyMetric.user_id == user_id))
    await db.execute(delete(ConversationLog).where(ConversationLog.user_id == user_id))
    await db.execute(delete(MemoryUpdate).where(MemoryUpdate.user_id == user_id))
    await db.execute(delete(HealthSnapshot).where(HealthSnapshot.user_id == user_id))

    # Reset user profile fields
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.preferences))
    )
    user = result.scalar_one()
    for field in ("name", "age", "sex", "height_cm", "current_weight_kg",
                  "goal_weight_kg", "primary_goal", "training_experience",
                  "dietary_preferences", "injuries", "webhook_token"):
        setattr(user, field, None)
    user.timezone = "UTC"
    user.onboarding_completed = False

    # Reset preferences
    if user.preferences:
        p = user.preferences
        p.coaching_style = "balanced"
        p.accountability_level = "medium"
        p.calorie_target = None
        p.protein_target = None
        p.wake_time = "07:00"
        p.sleep_time = "23:00"
        p.proactive_messaging_enabled = False

    await db.commit()


async def get_users_with_whoop(db: AsyncSession) -> List[User]:
    """All users who have connected Whoop (have a refresh token)."""
    result = await db.execute(
        select(User)
        .where(User.whoop_refresh_token.is_not(None))
        .options(selectinload(User.preferences))
    )
    return result.scalars().all()


async def set_whoop_tokens(
    db: AsyncSession,
    user_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
    whoop_user_id: Optional[str] = None,
) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.whoop_access_token = access_token
    user.whoop_refresh_token = refresh_token
    user.whoop_token_expires_at = expires_at
    if whoop_user_id:
        user.whoop_user_id = whoop_user_id
    await db.commit()


async def clear_whoop_tokens(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.whoop_access_token = None
    user.whoop_refresh_token = None
    user.whoop_token_expires_at = None
    user.whoop_user_id = None
    await db.commit()


async def get_or_create_webhook_token(db: AsyncSession, user_id: int) -> str:
    """Return existing webhook token, or generate + save a new one."""
    import secrets
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    if not user.webhook_token:
        user.webhook_token = secrets.token_urlsafe(20)
        await db.commit()
    return user.webhook_token


async def get_user_by_webhook_token(db: AsyncSession, token: str) -> Optional[User]:
    result = await db.execute(
        select(User)
        .where(User.webhook_token == token)
        .options(selectinload(User.preferences))
    )
    return result.scalar_one_or_none()


async def upsert_health_snapshot(db: AsyncSession, user_id: int,
                                  snapshot_date: date, **kwargs) -> HealthSnapshot:
    """Insert or update a HealthSnapshot for (user_id, date)."""
    result = await db.execute(
        select(HealthSnapshot).where(
            and_(HealthSnapshot.user_id == user_id,
                 HealthSnapshot.date == snapshot_date)
        )
    )
    snap = result.scalar_one_or_none()
    if snap:
        for k, v in kwargs.items():
            if v is not None:
                setattr(snap, k, v)
    else:
        snap = HealthSnapshot(user_id=user_id, date=snapshot_date, **kwargs)
        db.add(snap)
    await db.commit()
    return snap


async def get_recent_health_snapshots(db: AsyncSession, user_id: int,
                                       days: int = 7) -> List[HealthSnapshot]:
    since = date.today() - timedelta(days=days)
    result = await db.execute(
        select(HealthSnapshot)
        .where(and_(HealthSnapshot.user_id == user_id,
                    HealthSnapshot.date >= since))
        .order_by(desc(HealthSnapshot.date))
    )
    return result.scalars().all()


# ── Feedback ──────────────────────────────────────────────────────────────────

async def add_feedback(db: AsyncSession, user_id: int, kind: str, text: str) -> Feedback:
    entry = Feedback(user_id=user_id, kind=kind, text=text)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


# ── Food/Exercise edit + delete (with auto totals recalc) ─────────────────────

async def update_food_entry(
    db: AsyncSession, entry_id: int, user_id: int, **changes
) -> Optional[FoodEntry]:
    """
    Update a food entry and adjust the daily log totals by the delta.
    Returns None if entry doesn't exist or doesn't belong to user_id.
    """
    result = await db.execute(select(FoodEntry).where(FoodEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return None
    # Ownership check via the daily log
    log_result = await db.execute(select(DailyLog).where(DailyLog.id == entry.daily_log_id))
    log = log_result.scalar_one()
    if log.user_id != user_id:
        return None

    # Adjust totals for nutrition deltas
    for field in ("calories", "protein", "carbs", "fats"):
        if field in changes:
            old_val = getattr(entry, field) or 0
            new_val = float(changes[field] or 0)
            diff = new_val - old_val
            total_attr = f"total_{field}"
            setattr(log, total_attr, max(0.0, (getattr(log, total_attr) or 0) + diff))
            setattr(entry, field, new_val)

    # Non-nutrition fields
    for field in ("parsed_food_name", "quantity"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])

    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_food_entry(db: AsyncSession, entry_id: int, user_id: int) -> bool:
    result = await db.execute(select(FoodEntry).where(FoodEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return False
    log_result = await db.execute(select(DailyLog).where(DailyLog.id == entry.daily_log_id))
    log = log_result.scalar_one()
    if log.user_id != user_id:
        return False

    log.total_calories = max(0.0, (log.total_calories or 0) - (entry.calories or 0))
    log.total_protein = max(0.0, (log.total_protein or 0) - (entry.protein or 0))
    log.total_carbs = max(0.0, (log.total_carbs or 0) - (entry.carbs or 0))
    log.total_fats = max(0.0, (log.total_fats or 0) - (entry.fats or 0))

    await db.delete(entry)
    await db.commit()
    return True


async def update_exercise_entry(
    db: AsyncSession, entry_id: int, user_id: int, **changes
) -> Optional[ExerciseEntry]:
    result = await db.execute(select(ExerciseEntry).where(ExerciseEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return None
    log_result = await db.execute(select(DailyLog).where(DailyLog.id == entry.daily_log_id))
    log = log_result.scalar_one()
    if log.user_id != user_id:
        return None

    for field in ("exercise_name", "sets", "reps", "weight",
                  "duration_minutes", "cardio_type", "rir"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])

    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_exercise_entry(db: AsyncSession, entry_id: int, user_id: int) -> bool:
    result = await db.execute(select(ExerciseEntry).where(ExerciseEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return False
    log_result = await db.execute(
        select(DailyLog)
        .where(DailyLog.id == entry.daily_log_id)
        .options(selectinload(DailyLog.exercise_entries))
    )
    log = log_result.scalar_one()
    if log.user_id != user_id:
        return False

    was_cardio = bool(entry.cardio_type) or (entry.duration_minutes and not entry.sets)
    await db.delete(entry)
    await db.commit()

    # Re-evaluate workout/cardio flags from remaining entries
    remaining_result = await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.daily_log_id == log.id)
    )
    remaining = remaining_result.scalars().all()
    log.workout_completed = any(not (e.cardio_type or (e.duration_minutes and not e.sets)) for e in remaining)
    log.cardio_completed = any((e.cardio_type or (e.duration_minutes and not e.sets)) for e in remaining)
    await db.commit()
    return True
