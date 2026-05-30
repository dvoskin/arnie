from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, delete
from sqlalchemy.orm import selectinload
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry,
    ExerciseEntry, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
    Feedback, UserFoodMatch,
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


def linking_enabled() -> bool:
    import os
    return os.getenv("LINKING_ENABLED", "true").lower() in ("true", "1", "yes")


async def resolve_user(db: AsyncSession, platform_id: str) -> User:
    """
    Get the canonical user for a platform identity. Cross-platform continuity:
    if this identity has been linked to another account, return that canonical
    user (so iMessage + Telegram load the same brain). Otherwise behave exactly
    like get_or_create_user.

    Fully gated by LINKING_ENABLED — flip the env var to false to instantly
    revert to per-platform accounts (existing links just stop resolving; no
    data is touched, so it's a clean rollback).
    """
    user = await get_or_create_user(db, platform_id)
    if linking_enabled() and user.linked_to_user_id:
        canonical = await reload_user(db, user.linked_to_user_id)
        if canonical:
            return canonical
    return user


def _gen_link_code() -> str:
    import secrets
    return "LINK-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))


async def generate_link_code(db: AsyncSession, user: User) -> str:
    """Mint a one-time link code (10 min) on the canonical user that generated it."""
    code = _gen_link_code()
    user.link_code = code
    user.link_code_expires = datetime.utcnow() + timedelta(minutes=10)
    await db.commit()
    return code


async def consume_link_code(db: AsyncSession, code: str, consumer: User) -> Optional[User]:
    """
    Link `consumer`'s identity to the canonical user that owns `code`.
    Returns the canonical user on success, None if code invalid/expired/self.
    The consumer's own (throwaway) data is left orphaned — it just repoints.
    """
    code = (code or "").strip().upper()
    result = await db.execute(
        select(User).where(User.link_code == code).options(selectinload(User.preferences))
    )
    canonical = result.scalar_one_or_none()
    if not canonical:
        return None
    if canonical.link_code_expires and datetime.utcnow() > canonical.link_code_expires:
        return None
    if canonical.id == consumer.id:
        return None
    # Follow one level if the canonical itself is linked (avoid chains)
    if canonical.linked_to_user_id:
        canonical = await reload_user(db, canonical.linked_to_user_id) or canonical
    consumer.linked_to_user_id = canonical.id
    # burn the code
    owner = await reload_user(db, canonical.id)
    if owner and owner.link_code == code:
        owner.link_code = None
        owner.link_code_expires = None
    await db.commit()
    return canonical


def _platform_of(telegram_id: str) -> str:
    """Identity strings prefixed 'im:' are iMessage; everything else is Telegram."""
    return "imessage" if (telegram_id or "").startswith("im:") else "telegram"


async def resolve_send_target(db: AsyncSession, canonical: User) -> str:
    """
    Decide which platform identity a proactive message to `canonical` should go to.

    Returns the telegram_id string to pass to the scheduler's _send():
      - 'im:<addr>' routes to iMessage, a numeric string routes to Telegram.

    Logic: if the user picked a channel_preference and we have an identity on that
    platform (the canonical row itself, or a linked secondary row pointing at it),
    send there. Otherwise fall back to the canonical's own identity. Fully safe
    when unlinked (just returns canonical.telegram_id).
    """
    pref = getattr(canonical, "channel_preference", None)
    if not pref:
        return canonical.telegram_id
    if _platform_of(canonical.telegram_id) == pref:
        return canonical.telegram_id
    # Preference is the OTHER platform — find a linked identity that matches it.
    result = await db.execute(
        select(User).where(User.linked_to_user_id == canonical.id)
    )
    for secondary in result.scalars().all():
        if _platform_of(secondary.telegram_id) == pref:
            return secondary.telegram_id
    # No identity on the preferred platform — fall back to canonical.
    return canonical.telegram_id


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


async def get_or_create_log_for_date(
    db: AsyncSession, user_id: int, target_date: date
) -> DailyLog:
    """Get or create a DailyLog for any specific date (used for past-day logging)."""
    log = await get_log_by_date(db, user_id, target_date)
    if not log:
        log = DailyLog(user_id=user_id, date=target_date)
        db.add(log)
        await db.commit()
        log = await get_log_by_date(db, user_id, target_date)
    return log


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


async def recompute_log_totals(db: AsyncSession, daily_log_id: int) -> None:
    """
    Recompute ALL of a DailyLog's summary fields from its entries — the entries
    are the source of truth, so every aggregate is derived and can never drift.

    Covers: food macros (total_*) AND the workout/cardio completion flags. Using
    this after every add/update/delete (instead of incremental delta math or
    set-once flags) means a partial write, race, or mid-write crash can't leave
    the stored aggregate out of sync with what the dashboard shows. Caller commits.
    """
    foods = (await db.execute(
        select(FoodEntry).where(FoodEntry.daily_log_id == daily_log_id)
    )).scalars().all()
    exercises = (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.daily_log_id == daily_log_id)
    )).scalars().all()
    log = (await db.execute(
        select(DailyLog).where(DailyLog.id == daily_log_id)
    )).scalar_one()
    log.total_calories = sum((e.calories or 0) for e in foods)
    log.total_protein = sum((e.protein or 0) for e in foods)
    log.total_carbs = sum((e.carbs or 0) for e in foods)
    log.total_fats = sum((e.fats or 0) for e in foods)
    # Single source of truth for cardio vs strength classification: an entry is
    # cardio if it has a cardio_type, or it's duration-only (time logged, no sets).
    # Everything else is a strength workout. Derived so deleting the last exercise
    # of a kind correctly flips that flag back off.
    def _is_cardio(e):
        return bool(e.cardio_type) or bool(e.duration_minutes and not e.sets)
    log.cardio_completed = any(_is_cardio(e) for e in exercises)
    log.workout_completed = any(not _is_cardio(e) for e in exercises)


async def add_food_entry(db: AsyncSession, daily_log_id: int, **kwargs) -> FoodEntry:
    entry = FoodEntry(daily_log_id=daily_log_id, **kwargs)
    db.add(entry)
    await db.flush()  # entry must be visible to the recompute query
    await recompute_log_totals(db, daily_log_id)
    await db.commit()
    await db.refresh(entry)
    return entry


async def add_exercise_entry(db: AsyncSession, daily_log_id: int,
                              is_cardio: bool = False, **kwargs) -> ExerciseEntry:
    # If caller signals cardio but didn't set cardio_type, mark it so the derived
    # flags (recompute_log_totals) classify this entry correctly.
    if is_cardio and not kwargs.get("cardio_type"):
        kwargs["cardio_type"] = "cardio"
    entry = ExerciseEntry(daily_log_id=daily_log_id, **kwargs)
    db.add(entry)
    await db.flush()  # entry must be visible to the recompute query
    await recompute_log_totals(db, daily_log_id)
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

    # Apply nutrition changes to the entry
    for field in ("calories", "protein", "carbs", "fats"):
        if field in changes:
            setattr(entry, field, float(changes[field] or 0))

    # Non-nutrition fields
    for field in ("parsed_food_name", "quantity"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])

    await db.flush()
    # Totals are derived from entries — recompute so they can never drift.
    await recompute_log_totals(db, entry.daily_log_id)
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

    daily_log_id = entry.daily_log_id
    await db.delete(entry)
    await db.flush()
    # Totals are derived from entries — recompute so they can never drift.
    await recompute_log_totals(db, daily_log_id)
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

    await db.flush()
    # Re-derive flags in case cardio_type/sets/duration changed (workout<->cardio).
    await recompute_log_totals(db, entry.daily_log_id)
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


# ── Subscription ───────────────────────────────────────────────────────────────

async def set_subscription_active(
    db: AsyncSession,
    telegram_id: str,
    stripe_customer_id: str,
    period_end: datetime,
) -> None:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user:
        user.subscription_status = "active"
        user.stripe_customer_id = stripe_customer_id
        user.subscription_ends_at = period_end
        await db.commit()


async def set_subscription_cancelled(db: AsyncSession, stripe_customer_id: str) -> Optional[str]:
    """Mark subscription cancelled. Returns telegram_id so the bot can notify the user."""
    result = await db.execute(
        select(User).where(User.stripe_customer_id == stripe_customer_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.subscription_status = "cancelled"
        await db.commit()
        return user.telegram_id
    return None


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: str) -> Optional[User]:
    result = await db.execute(
        select(User)
        .where(User.telegram_id == telegram_id)
        .options(selectinload(User.preferences))
    )
    return result.scalar_one_or_none()


def is_premium(user) -> bool:
    """True if the user has an active paid subscription or an unexpired trial."""
    if user.subscription_status == "active":
        return True
    if user.subscription_status == "trial":
        if user.trial_ends_at is None:
            return True  # trial not yet bounded — legacy users
        return datetime.utcnow() < user.trial_ends_at
    return False
    return True


# ── Recurring food memory (USDA matches per user) ──────────────────────────────

async def get_user_food_match(db: AsyncSession, user_id: int, name_norm: str):
    """Fetch a user's stored match for a normalized food name, if any."""
    result = await db.execute(
        select(UserFoodMatch).where(and_(
            UserFoodMatch.user_id == user_id,
            UserFoodMatch.name_norm == name_norm,
        ))
    )
    return result.scalar_one_or_none()


async def upsert_user_food_match(db: AsyncSession, user_id: int, name_norm: str,
                                 display_name: str, fdc_id: str, per100: dict,
                                 confidence: str, user_confirmed: bool = False):
    """Store/refresh a user's recurring food match. Bumps usage on repeat."""
    existing = await get_user_food_match(db, user_id, name_norm)
    if existing:
        existing.times_used = (existing.times_used or 1) + 1
        existing.last_used = datetime.utcnow()
        # Upgrade to user-confirmed if the user corrected it; never downgrade.
        if user_confirmed:
            existing.user_confirmed = True
            existing.confidence = "user-confirmed"
        await db.commit()
        return existing
    m = UserFoodMatch(
        user_id=user_id, name_norm=name_norm, display_name=display_name,
        fdc_id=str(fdc_id) if fdc_id else None,
        cal_100=per100.get("calories"), protein_100=per100.get("protein"),
        carbs_100=per100.get("carbs"), fat_100=per100.get("fat"),
        fiber_100=per100.get("fiber"), sugar_100=per100.get("sugar"),
        sodium_100=per100.get("sodium"),
        confidence="user-confirmed" if user_confirmed else confidence,
        user_confirmed=user_confirmed,
    )
    db.add(m)
    await db.commit()
    return m
