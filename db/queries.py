from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, delete, update
from sqlalchemy.orm import selectinload
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry,
    ExerciseEntry, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
    Feedback, UserFoodMatch, PendingQuestion, WearableDevice, WearableMetric,
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


def search_enabled() -> bool:
    import os
    return os.getenv("SEARCH_ENABLED", "false").lower() in ("true", "1", "yes")


def location_enabled() -> bool:
    """Gate for the find_nearby_places tool (Google Places). Default OFF — mirrors
    search_enabled so the location capability is inert until LOCATION_ENABLED=true
    AND a GOOGLE_PLACES_API_KEY is set. Same pattern as web_search: zero impact on
    existing behavior while disabled."""
    import os
    return os.getenv("LOCATION_ENABLED", "false").lower() in ("true", "1", "yes")


async def enable_check_ins(db: AsyncSession, user_id: int) -> None:
    """
    Turn proactive check-ins ON for a user — called natively when onboarding completes,
    so every finisher gets check-ins (and a reset-then-re-onboard re-enables them).
    Creates a preferences row if one is somehow missing. Queries prefs directly so it
    doesn't depend on the User.preferences relationship being eager-loaded.

    NOTE: this is the PER-USER opt-in. The global PROACTIVE_MESSAGING_ENABLED switch
    still gates whether the scheduler actually sends anything.
    """
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
    prefs.proactive_messaging_enabled = True
    await db.commit()


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
    _opts = [
        selectinload(DailyLog.food_entries),
        selectinload(DailyLog.exercise_entries),
        selectinload(DailyLog.water_entries),
    ]

    async def _fetch(d: date) -> Optional[DailyLog]:
        r = await db.execute(
            select(DailyLog)
            .where(and_(DailyLog.user_id == user_id, DailyLog.date == d))
            .options(*_opts)
        )
        return r.scalar_one_or_none()

    today = _user_today(user_timezone)
    log = await _fetch(today)
    if log is not None:
        return log

    utc_today = _user_today("UTC")
    if utc_today != today:
        log = await _fetch(utc_today)
        if log is not None:
            return log



async def get_log_by_date(db: AsyncSession, user_id: int, target_date: date) -> Optional[DailyLog]:
    """Fetch a specific day's log with food/exercise/water entries eagerly loaded."""
    result = await db.execute(
        select(DailyLog)
        .where(and_(DailyLog.user_id == user_id, DailyLog.date == target_date))
        .options(
            selectinload(DailyLog.food_entries),
            selectinload(DailyLog.exercise_entries),
            selectinload(DailyLog.water_entries),
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


async def add_water_entry(db: AsyncSession, user_id: int, daily_log_id: int,
                          amount_ml: float, context: Optional[str] = None,
                          source_type: str = "text"):
    """T2.4 — Persist a timestamped water log. DailyLog.total_water_ml stays
    as the cached aggregate (updated by the caller alongside) for backward
    compat with existing dashboards; the WaterEntry row is the canonical
    source for hydration timing coaching and future per-event analytics."""
    from db.models import WaterEntry
    entry = WaterEntry(
        user_id=user_id,
        daily_log_id=daily_log_id,
        amount_ml=amount_ml,
        context=context,
        source_type=source_type,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def recompute_water_total(db: AsyncSession, daily_log_id: int) -> float:
    """Re-sum a day's WaterEntry rows into DailyLog.total_water_ml.

    Called after any manual water edit/delete from the dashboard so the cached
    aggregate the tile/context read stays in sync with the canonical rows.
    Returns the new total."""
    from db.models import WaterEntry
    rows = (await db.execute(
        select(WaterEntry.amount_ml).where(WaterEntry.daily_log_id == daily_log_id)
    )).scalars().all()
    total = float(sum(a or 0 for a in rows))
    log = await db.get(DailyLog, daily_log_id)
    if log is not None:
        log.total_water_ml = total
        await db.commit()
    return total


async def update_water_entry(db: AsyncSession, entry_id: int, user_id: int,
                             amount_ml: float):
    """Update a single WaterEntry's amount, then resync the day total.

    Scoped by user_id so a token can only touch its own rows. Returns the
    refreshed entry, or None if not found / not owned."""
    from db.models import WaterEntry
    entry = await db.get(WaterEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        return None
    entry.amount_ml = amount_ml
    await db.commit()
    if entry.daily_log_id:
        await recompute_water_total(db, entry.daily_log_id)
    await db.refresh(entry)
    return entry


async def delete_water_entry(db: AsyncSession, entry_id: int, user_id: int) -> bool:
    """Delete a single WaterEntry, then resync the day total.

    Scoped by user_id. Returns True if a row was removed."""
    from db.models import WaterEntry
    entry = await db.get(WaterEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        return False
    daily_log_id = entry.daily_log_id
    await db.delete(entry)
    await db.commit()
    if daily_log_id:
        await recompute_water_total(db, daily_log_id)
    return True


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
    # Add 1-day buffer to avoid UTC edge cases near midnight.
    # Upper bound (today) excludes any future-dated logs created by LLM date bugs
    # — those must never appear in history or available_dates on the dashboard.
    since = date.today() - timedelta(days=days + 1)
    today = date.today()
    result = await db.execute(
        select(DailyLog)
        .where(and_(
            DailyLog.user_id == user_id,
            DailyLog.date >= since,
            DailyLog.date <= today,
        ))
        .options(
            selectinload(DailyLog.food_entries),
            selectinload(DailyLog.exercise_entries),
        )
        .order_by(desc(DailyLog.date))
    )
    return result.scalars().all()


async def get_recent_conversations(db: AsyncSession, user_id: int,
                                   limit: int = 8,
                                   source_types: Optional[List[str]] = None
                                   ) -> List[ConversationLog]:
    stmt = (
        select(ConversationLog)
        .where(ConversationLog.user_id == user_id)
    )
    if source_types is not None:
        stmt = stmt.where(ConversationLog.source_type.in_(source_types))
    stmt = stmt.order_by(desc(ConversationLog.timestamp)).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def log_conversation(db: AsyncSession, user_id: int, raw_message: str,
                           response: str, parsed_intent: str = None,
                           source_type: str = "text",
                           skills_fired: str | None = None,
                           platform: str | None = None):
    """Persist one conversation turn.

    `platform` tags which surface the turn happened on ("telegram" | "imessage"
    | "web"). Optional + defaults to the model default ("telegram") so existing
    callers are unchanged; the dashboard web-chat passes platform="web" so the
    unified thread can label it correctly across all surfaces."""
    entry = ConversationLog(
        user_id=user_id,
        raw_message=raw_message,
        parsed_intent=parsed_intent,
        response=response,
        source_type=source_type,
        skills_fired=skills_fired,
    )
    if platform is not None:
        entry.platform = platform
    db.add(entry)
    await db.commit()


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
    await db.commit()
    return True


async def reset_all_user_data(db: AsyncSession, user_id: int) -> None:
    """
    Full account wipe — deletes ALL logs, metrics, conversations, memory, food
    memory, pending questions, and wearable data. Resets profile + coaching state
    and forces re-onboarding. KEEPS the user row (same telegram_id), the
    cross-platform link, and subscription/billing so the user starts fresh without
    losing their account or their paid plan.

    NOTE: child tables (FoodEntry/ExerciseEntry) must be deleted BEFORE their parent
    DailyLog. The ORM `cascade="all, delete-orphan"` does NOT fire on bulk Core
    delete() statements, and Postgres enforces the foreign key — so deleting a
    DailyLog with surviving children raises a FK violation and rolls back the entire
    reset. This was the bug behind "reset didn't actually clear my data."
    """
    # 1. Children of daily_logs first (subquery on the user's log ids).
    log_ids = select(DailyLog.id).where(DailyLog.user_id == user_id)
    await db.execute(delete(FoodEntry).where(FoodEntry.daily_log_id.in_(log_ids)))
    await db.execute(delete(ExerciseEntry).where(ExerciseEntry.daily_log_id.in_(log_ids)))

    # 2. Everything keyed directly by user_id.
    for model in (
        DailyLog, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
        WearableDevice, WearableMetric, PendingQuestion, Feedback, UserFoodMatch,
    ):
        await db.execute(delete(model).where(model.user_id == user_id))

    # 3. Reset user profile + coaching/engagement state via Core UPDATE (bypasses
    #    the identity map so a stale cached object can't resurrect old values).
    #    Preserved on purpose: telegram_id, the cross-platform link, channel
    #    preference, units, and all subscription/billing fields.
    await db.execute(
        update(User).where(User.id == user_id).values(
            name=None, age=None, sex=None, height_cm=None,
            current_weight_kg=None, goal_weight_kg=None, primary_goal=None,
            training_experience=None, dietary_preferences=None, injuries=None,
            city=None, sport=None, webhook_token=None,
            timezone="UTC", onboarding_completed=False,
            # wearable connection (we deleted the WearableDevice rows above)
            whoop_access_token=None, whoop_refresh_token=None,
            whoop_token_expires_at=None, whoop_user_id=None,
            # proactive-engagement state
            nudges_sent="", whoop_last_notified=None, weekly_recap_week=None,
            # open coaching loop
            active_mission=None, mission_metric=None,
            mission_target=None, mission_date=None,
        )
    )

    # 4. Reset preferences.
    await db.execute(
        update(UserPreferences).where(UserPreferences.user_id == user_id).values(
            coaching_style="balanced", accountability_level="medium",
            calorie_target=None, protein_target=None,
            wake_time="07:00", sleep_time="23:00",
            proactive_messaging_enabled=False,
        )
    )

    await db.commit()


async def get_users_with_whoop(db: AsyncSession) -> List[User]:
    """All users who have connected Whoop (have a non-empty refresh token)."""
    result = await db.execute(
        select(User)
        .where(
            User.whoop_refresh_token.is_not(None),
            User.whoop_refresh_token != "",
        )
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


async def create_pre_registration(db: AsyncSession, profile: dict) -> str:
    """
    Persist a pre-registration profile from the landing-page form.
    Returns the one-time SETUP-XXXXXX code the user will pass to /start.
    Generates a new code until it finds one that doesn't already exist (collision
    probability is negligible for 36^6 ≈ 2B possibilities, but be safe).
    """
    import secrets
    import json
    from db.models import PreRegistration

    for _ in range(5):
        code = "SETUP-" + "".join(
            secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6)
        )
        existing = (await db.execute(
            select(PreRegistration).where(PreRegistration.code == code)
        )).scalar_one_or_none()
        if not existing:
            break

    entry = PreRegistration(
        code=code,
        profile_json=json.dumps(profile),
        expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    db.add(entry)
    await db.commit()
    return code


async def consume_pre_registration(db: AsyncSession, code: str) -> Optional[dict]:
    """
    Validate and consume a pre-registration code.
    Returns the stored profile dict on success, None if invalid/expired/already used.
    Marks the record consumed so it can't be replayed.
    """
    import json
    from db.models import PreRegistration

    result = await db.execute(
        select(PreRegistration).where(PreRegistration.code == code.upper())
    )
    entry = result.scalar_one_or_none()

    if not entry:
        return None
    if entry.consumed_at is not None:
        return None   # already used
    if entry.expires_at < datetime.utcnow():
        return None   # expired

    entry.consumed_at = datetime.utcnow()
    await db.commit()
    return json.loads(entry.profile_json)


async def get_user_by_webhook_token(
    db: AsyncSession, token: str, *, follow_link: bool = True
) -> Optional[User]:
    """Resolve a dashboard webhook token to a user.

    By default this follows `linked_to_user_id` to the CANONICAL account, so the
    dashboard reads and writes the exact same brain the bot does (the bot uses
    resolve_user, which also canonicalizes). Without this, an edit/delete made on
    a linked identity's dashboard lands on a different DailyLog than the one the
    bot reads — e.g. deleting water on the dashboard wouldn't show up in chat.

    Pass follow_link=False to get the raw token-owner row unchanged — used by the
    Whoop OAuth callback/sync so wearable tokens stay on the row they were stored
    on. Unlinked users are unaffected either way (linked_to_user_id is null)."""
    result = await db.execute(
        select(User)
        .where(User.webhook_token == token)
        .options(selectinload(User.preferences))
    )
    user = result.scalar_one_or_none()
    if user and follow_link and linking_enabled() and user.linked_to_user_id:
        canonical = await reload_user(db, user.linked_to_user_id)
        if canonical:
            return canonical
    return user


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


# ── Pending questions (context-aware follow-up state) ─────────────────────────
# An open question Arnie asked that's awaiting an answer. The reminders module
# reads open rows to decide whether to re-ask; the conversation path resolves
# them when the user answers (data-driven where possible). See db.models.PendingQuestion.

async def record_pending_question(
    db: AsyncSession, user_id: int, kind: str, question: str,
    tier: str = "casual", hook_style: str = "question",
) -> PendingQuestion:
    """
    Open a pending-question loop. If an unanswered row of the same kind already
    exists, update it in place (one open question per kind) rather than stacking
    duplicates — keeps follow-up logic from re-asking the same thing twice.

    hook_style: "question" (ends with ?) or "engagement" (ends with "let me know"
    etc.) — controls the re-ask template in _llm_followup.
    """
    existing = await get_open_pending_question(db, user_id, kind)
    if existing:
        existing.question = question
        existing.tier = tier
        existing.hook_style = hook_style
        await db.commit()
        await db.refresh(existing)
        return existing
    pq = PendingQuestion(user_id=user_id, kind=kind, question=question, tier=tier,
                         hook_style=hook_style)
    db.add(pq)
    await db.commit()
    await db.refresh(pq)
    return pq


async def get_open_pending_question(
    db: AsyncSession, user_id: int, kind: str
) -> Optional[PendingQuestion]:
    """The single open (unanswered) question of `kind` for this user, if any."""
    result = await db.execute(
        select(PendingQuestion)
        .where(and_(PendingQuestion.user_id == user_id,
                    PendingQuestion.kind == kind,
                    PendingQuestion.answered_at.is_(None)))
        .order_by(desc(PendingQuestion.asked_at))
    )
    return result.scalars().first()


async def get_open_pending_questions(
    db: AsyncSession, user_id: int
) -> List[PendingQuestion]:
    """All open (unanswered) questions for a user, newest first."""
    result = await db.execute(
        select(PendingQuestion)
        .where(and_(PendingQuestion.user_id == user_id,
                    PendingQuestion.answered_at.is_(None)))
        .order_by(desc(PendingQuestion.asked_at))
    )
    return result.scalars().all()


async def mark_pending_question_followed_up(
    db: AsyncSession, question_id: int
) -> None:
    """Record that we just re-asked: bump the count and the last-asked timestamp."""
    result = await db.execute(
        select(PendingQuestion).where(PendingQuestion.id == question_id)
    )
    pq = result.scalar_one_or_none()
    if pq is None:
        return
    pq.follow_up_count = (pq.follow_up_count or 0) + 1
    pq.last_asked_at = datetime.utcnow()
    await db.commit()


async def resolve_pending_questions(
    db: AsyncSession, user_id: int, kinds: Optional[List[str]] = None
) -> int:
    """
    Mark open questions answered (sets answered_at=now). If `kinds` is given,
    only those kinds are resolved; otherwise all open questions for the user.
    Returns the number of rows closed. Idempotent — already-answered rows are skipped.
    """
    conds = [PendingQuestion.user_id == user_id,
             PendingQuestion.answered_at.is_(None)]
    if kinds:
        conds.append(PendingQuestion.kind.in_(kinds))
    result = await db.execute(select(PendingQuestion).where(and_(*conds)))
    rows = result.scalars().all()
    now = datetime.utcnow()
    for pq in rows:
        pq.answered_at = now
    if rows:
        await db.commit()
    return len(rows)


async def resolve_pending_questions_for_logged_items(
    db: AsyncSession, user_id: int, logged_names: List[str],
) -> int:
    """
    Close ONLY the food_clarification rows whose item_referenced matches one of
    the foods just logged. Used by the log_food auto-resolve so a log of item A
    no longer silently closes an open question about item B.

    Match rules (any one closes the row):
      • exact normalized-name match
      • one normalized name contains the other (substring)
      • shared non-filler content token (so 'protein bar' question closes when
        'built bar' is logged — 'bar' overlaps, the user named the specific brand)

    Returns the number of rows closed.
    """
    from core.food_intelligence import normalize_name, _FOOD_FILLER
    logged_norm = [normalize_name(n) for n in (logged_names or []) if n]
    logged_norm = [n for n in logged_norm if n]
    if not logged_norm:
        return 0
    conds = [
        PendingQuestion.user_id == user_id,
        PendingQuestion.answered_at.is_(None),
        PendingQuestion.kind == "food_clarification",
    ]
    result = await db.execute(select(PendingQuestion).where(and_(*conds)))
    rows = result.scalars().all()
    now = datetime.utcnow()
    closed = 0
    for pq in rows:
        item = (pq.item_referenced or "").strip()
        if not item:
            continue
        item_norm = normalize_name(item)
        if not item_norm:
            continue
        item_tokens = set(item_norm.split()) - _FOOD_FILLER
        matched = False
        for n in logged_norm:
            if item_norm == n or item_norm in n or n in item_norm:
                matched = True
                break
            n_tokens = set(n.split()) - _FOOD_FILLER
            if item_tokens and n_tokens and (item_tokens & n_tokens):
                matched = True
                break
        if matched:
            pq.answered_at = now
            closed += 1
    if closed:
        await db.commit()
    return closed


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

    old_log_id = entry.daily_log_id
    # Day move: reassigning the entry to another date's log (passed as new_daily_log_id).
    # This is how "move that coffee to yesterday" / "this was all yesterday" work —
    # the SAME primitive as editing a value, just changing which day it belongs to.
    new_log_id = changes.pop("new_daily_log_id", None)

    # Apply nutrition changes to the entry
    for field in ("calories", "protein", "carbs", "fats"):
        if field in changes:
            setattr(entry, field, float(changes[field] or 0))

    # Non-nutrition fields
    for field in ("parsed_food_name", "quantity"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])

    moved = bool(new_log_id and new_log_id != old_log_id)
    if moved:
        entry.daily_log_id = new_log_id

    await db.flush()
    # Totals are derived from entries — recompute every affected day so the dashboard
    # can never drift from the conversation. A move touches BOTH days.
    await recompute_log_totals(db, entry.daily_log_id)
    if moved:
        await recompute_log_totals(db, old_log_id)
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

    old_log_id = entry.daily_log_id
    new_log_id = changes.pop("new_daily_log_id", None)  # day move (same primitive as edit)

    for field in ("exercise_name", "sets", "reps", "weight",
                  "duration_minutes", "cardio_type", "rir"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])

    moved = bool(new_log_id and new_log_id != old_log_id)
    if moved:
        entry.daily_log_id = new_log_id

    await db.flush()
    # Re-derive flags in case cardio_type/sets/duration changed (workout<->cardio),
    # and recompute BOTH days on a move so neither dashboard drifts.
    await recompute_log_totals(db, entry.daily_log_id)
    if moved:
        await recompute_log_totals(db, old_log_id)
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

    daily_log_id = entry.daily_log_id
    await db.delete(entry)
    await db.flush()
    # Re-derive flags from whatever remains (single source of truth).
    await recompute_log_totals(db, daily_log_id)
    await db.commit()
    return True


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


_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_natural_period(period: str, today):
    """Resolve a period string to a (since, until) inclusive date range.

    Accepts: existing 'last_N' tags, 'YYYY-MM-DD' single dates, 'YYYY-MM-DD:YYYY-MM-DD'
    ranges, and natural-language inputs: 'today', 'yesterday', 'N days ago',
    'monday'/'sun'/'sunday', 'last monday'/'last sun', 'this week',
    'last week', 'june 7', 'june 7 2026'.

    Returns (since: date, until: date) or None if unparseable. Pure helper —
    no DB access, so it's cheap to unit-test.
    """
    from datetime import date as _date, timedelta as _td
    import re as _re0
    if not period:
        return None
    p = period.strip().lower()

    # Normalize time-of-day qualifiers — they don't change the DAY, but their
    # presence ("last friday NIGHT", "yesterday evening") used to break parsing
    # and force the model to compute the date itself (→ wrong-day narration).
    p = _re0.sub(r"\blast night\b", "yesterday", p)
    p = _re0.sub(r"\b(tonight|this (?:morning|afternoon|evening|night))\b", "today", p)
    p = _re0.sub(r"\s+(?:in the\s+)?(?:morning|afternoon|evening|night)s?$", "", p).strip()

    # 'last_N' window aliases — accept any positive integer so the model can
    # pull arbitrarily long windows ("last_120", "last_365"). The DB stores
    # entries indefinitely; nothing here imposes an upper cap.
    import re as _re
    m_last = _re.match(r"^last_(\d+)$", p)
    if m_last:
        n = int(m_last.group(1))
        if n > 0:
            return (today - _td(days=n), today)

    # 'YYYY-MM-DD:YYYY-MM-DD' range
    if ":" in p:
        a, b = p.split(":", 1)
        try:
            d1 = _date.fromisoformat(a.strip())
            d2 = _date.fromisoformat(b.strip())
            if d1 > d2:
                d1, d2 = d2, d1
            return (d1, d2)
        except ValueError:
            return None

    # Single ISO date
    try:
        d = _date.fromisoformat(p)
        return (d, d)
    except ValueError:
        pass

    # Natural language single days
    if p in ("today", "now"):
        return (today, today)
    if p in ("yesterday", "yday", "y'day"):
        d = today - _td(days=1)
        return (d, d)
    if p in ("tomorrow",):
        return None  # never log forward
    # "N days ago"
    import re
    m = re.match(r"^(\d+)\s*days?\s*ago$", p)
    if m:
        d = today - _td(days=int(m.group(1)))
        return (d, d)
    # word-numbers for small N
    _word_n = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    m = re.match(r"^(one|two|three|four|five|six|seven|eight|nine|ten)\s+days?\s+ago$", p)
    if m:
        d = today - _td(days=_word_n[m.group(1)])
        return (d, d)
    # "N weeks ago" → single day exactly N*7 days back
    m = re.match(r"^(\d+)\s*weeks?\s*ago$", p)
    if m:
        d = today - _td(days=int(m.group(1)) * 7)
        return (d, d)
    m = re.match(r"^(one|two|three|four|five|six|seven|eight|nine|ten)\s+weeks?\s+ago$", p)
    if m:
        d = today - _td(days=_word_n[m.group(1)] * 7)
        return (d, d)
    # "N months ago" → approximate as N*30 days (good enough for recap intent,
    # which is "give me roughly that time period" not "give me a precise
    # calendar month"). User can always switch to ISO if they need exact.
    m = re.match(r"^(\d+)\s*months?\s*ago$", p)
    if m:
        d = today - _td(days=int(m.group(1)) * 30)
        return (d, d)
    m = re.match(r"^(one|two|three|four|five|six|seven|eight|nine|ten)\s+months?\s+ago$", p)
    if m:
        d = today - _td(days=_word_n[m.group(1)] * 30)
        return (d, d)
    # "last week" / "this week" → 7-day windows
    if p == "this week":
        # ISO week: Monday is start
        start = today - _td(days=today.weekday())
        return (start, today)
    if p == "last week":
        start_this = today - _td(days=today.weekday())
        start_last = start_this - _td(days=7)
        end_last = start_this - _td(days=1)
        return (start_last, end_last)

    # Weekday names with optional "last" prefix → most recent occurrence
    # "monday" / "sunday" / "last monday" / "last sun"
    parts = p.split()
    if 1 <= len(parts) <= 2:
        candidate = parts[-1]
        if candidate in _WEEKDAYS:
            target = _WEEKDAYS[candidate]
            # Days back from today: weekday() - target (mod 7).
            # If today IS that weekday, "monday" today means today; "last monday" means 7 days back.
            diff = (today.weekday() - target) % 7
            if diff == 0 and (len(parts) == 2 and parts[0] == "last"):
                diff = 7
            d = today - _td(days=diff)
            return (d, d)

    # "june 7" / "june 7 2026" / "june 7, 2026"
    m = re.match(r"^([a-z]+)\s+(\d{1,2})(?:[,\s]+(\d{4}))?$", p)
    if m:
        mon_name = m.group(1)
        day_num = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        mon = _MONTHS.get(mon_name)
        if mon and 1 <= day_num <= 31:
            try:
                d = _date(year, mon, day_num)
                # If no year was provided and the resolved date is in the future
                # (e.g. "december 31" said in january), it likely meant LAST year.
                if not m.group(3) and d > today:
                    d = _date(year - 1, mon, day_num)
                return (d, d)
            except ValueError:
                return None

    return None


async def query_history_stats(
    db: AsyncSession,
    user_id: int,
    period: str,
    metric: str,
    exercise_name: str = None,
    user_timezone: str = "UTC",
) -> dict:
    """
    Pull historical stats for a user beyond the 7-day context window.

    period:
      • 'last_7'|'last_14'|'last_30'|'last_60'|'last_90' — rolling window
      • 'YYYY-MM-DD' — single date
      • 'YYYY-MM-DD:YYYY-MM-DD' — inclusive range
      • natural language: 'today', 'yesterday', 'N days ago', 'sunday',
        'last monday', 'this week', 'last week', 'june 7'

    metric:
      • aggregates (legacy): 'calories'|'protein'|'workouts'|'all'
      • single-domain (legacy): 'weight'|'exercise'
      • per-entry (new): 'food_entries'|'exercise_entries'|'water'|
        'body_metrics'|'day_detail'

    Returns a dict the executor formats into a result string.
    """
    tz = pytz.timezone(user_timezone or "UTC")
    today = datetime.now(tz).date()

    # Resolve period to a date range — supports legacy + natural-language.
    parsed = parse_natural_period(period, today)
    if parsed is None:
        return {"error": f"Unrecognised period: {period!r}"}
    since, until = parsed
    single_date = since if since == until else None

    if metric in ("calories", "protein", "workouts", "all"):
        logs = (await db.execute(
            select(DailyLog)
            .where(and_(
                DailyLog.user_id == user_id,
                DailyLog.date >= since,
                DailyLog.date <= until,
            ))
            .options(
                selectinload(DailyLog.food_entries),
                selectinload(DailyLog.exercise_entries),
            )
            .order_by(DailyLog.date)
        )).scalars().all()

        if not logs:
            return {"metric": metric, "period": period, "days_with_data": 0, "rows": []}

        rows = []
        for l in logs:
            row: dict = {"date": str(l.date)}
            if metric in ("calories", "all"):
                row["calories"] = round(l.total_calories or 0)
            if metric in ("protein", "all"):
                row["protein"] = round(l.total_protein or 0)
            if metric in ("workouts", "all"):
                row["workout"] = bool(l.workout_completed)
                row["cardio"] = bool(l.cardio_completed)
            rows.append(row)

        # Aggregates
        out: dict = {"metric": metric, "period": period, "days_with_data": len(rows), "rows": rows}
        if metric in ("calories", "all") and rows:
            cals = [r["calories"] for r in rows]
            out["avg_calories"] = round(sum(cals) / len(cals))
            out["min_calories"] = min(cals)
            out["max_calories"] = max(cals)
        if metric in ("protein", "all") and rows:
            pros = [r["protein"] for r in rows]
            out["avg_protein"] = round(sum(pros) / len(pros))
        if metric in ("workouts", "all") and rows:
            out["workout_days"] = sum(1 for r in rows if r.get("workout"))
            out["cardio_days"] = sum(1 for r in rows if r.get("cardio"))
        return out

    if metric == "weight":
        metrics = (await db.execute(
            select(BodyMetric)
            .where(and_(
                BodyMetric.user_id == user_id,
                BodyMetric.timestamp >= datetime.combine(since, datetime.min.time()),
                BodyMetric.timestamp <= datetime.combine(until, datetime.max.time()),
            ))
            .order_by(BodyMetric.timestamp)
        )).scalars().all()

        if not metrics:
            return {"metric": "weight", "period": period, "entries": 0}

        weights = [{"date": m.timestamp.strftime("%Y-%m-%d"), "weight_kg": round(m.weight_kg, 2)}
                   for m in metrics]
        delta = weights[-1]["weight_kg"] - weights[0]["weight_kg"] if len(weights) > 1 else 0
        return {
            "metric": "weight", "period": period,
            "entries": len(weights), "data": weights,
            "start_kg": weights[0]["weight_kg"], "end_kg": weights[-1]["weight_kg"],
            "delta_kg": round(delta, 2),
        }

    if metric == "exercise":
        if not exercise_name:
            return {"error": "exercise_name required when metric='exercise'"}
        name_lower = exercise_name.strip().lower()
        logs = (await db.execute(
            select(DailyLog)
            .where(and_(
                DailyLog.user_id == user_id,
                DailyLog.date >= since,
                DailyLog.date <= until,
            ))
            .options(selectinload(DailyLog.exercise_entries))
            .order_by(DailyLog.date)
        )).scalars().all()

        sessions = []
        for log in logs:
            matches = [
                e for e in (log.exercise_entries or [])
                if name_lower in (e.exercise_name or "").lower()
            ]
            if matches:
                for e in matches:
                    w_lbs = round(e.weight * 2.20462, 1) if e.weight else None
                    sessions.append({
                        "date": str(log.date),
                        "sets": e.sets, "reps": e.reps,
                        "weight_lbs": w_lbs, "weight_kg": round(e.weight, 2) if e.weight else None,
                    })

        return {
            "metric": "exercise", "exercise": exercise_name,
            "period": period, "sessions": len(sessions), "data": sessions,
        }

    # ── NEW PER-ENTRY METRICS ────────────────────────────────────────────────

    if metric == "food_entries":
        logs = (await db.execute(
            select(DailyLog)
            .where(and_(
                DailyLog.user_id == user_id,
                DailyLog.date >= since,
                DailyLog.date <= until,
            ))
            .options(selectinload(DailyLog.food_entries))
            .order_by(DailyLog.date)
            .execution_options(populate_existing=True)
        )).scalars().all()
        rows = []
        for l in logs:
            for f in (l.food_entries or []):
                rows.append({
                    "date": str(l.date),
                    "food_name": f.parsed_food_name or "",
                    "quantity": f.quantity or "",
                    "calories": round(f.calories or 0),
                    "protein": round(f.protein or 0),
                    "carbs": round(f.carbs or 0),
                    "fats": round(f.fats or 0),
                    "estimated": bool(f.estimated_flag),
                })
        return {
            "metric": "food_entries", "period": period,
            "days_with_data": sum(1 for l in logs if l.food_entries),
            "entries": len(rows),
            "rows": rows,
        }

    if metric == "exercise_entries":
        logs = (await db.execute(
            select(DailyLog)
            .where(and_(
                DailyLog.user_id == user_id,
                DailyLog.date >= since,
                DailyLog.date <= until,
            ))
            .options(selectinload(DailyLog.exercise_entries))
            .order_by(DailyLog.date)
            .execution_options(populate_existing=True)
        )).scalars().all()
        rows = []
        for l in logs:
            for e in (l.exercise_entries or []):
                w_lbs = round(e.weight * 2.20462, 1) if e.weight else None
                rows.append({
                    "date": str(l.date),
                    "exercise_name": e.exercise_name or "",
                    "sets": e.sets, "reps": e.reps,
                    "weight_lbs": w_lbs,
                    "weight_kg": round(e.weight, 2) if e.weight else None,
                    "duration_minutes": e.duration_minutes,
                    "cardio_type": e.cardio_type,
                })
        return {
            "metric": "exercise_entries", "period": period,
            "days_with_data": sum(1 for l in logs if l.exercise_entries),
            "entries": len(rows),
            "rows": rows,
        }

    if metric == "water":
        try:
            from db.models import WaterEntry
        except ImportError:
            WaterEntry = None
        rows = []
        if WaterEntry is not None:
            entries = (await db.execute(
                select(WaterEntry)
                .where(and_(
                    WaterEntry.user_id == user_id,
                    WaterEntry.timestamp >= datetime.combine(since, datetime.min.time()),
                    WaterEntry.timestamp <= datetime.combine(until, datetime.max.time()),
                ))
                .order_by(WaterEntry.timestamp)
            )).scalars().all()
            for w in entries:
                rows.append({
                    "date": w.timestamp.strftime("%Y-%m-%d"),
                    "amount_ml": round(w.amount_ml or 0),
                    "context": w.context or "",
                })
        # Also include daily aggregates from DailyLog for days in range
        logs = (await db.execute(
            select(DailyLog)
            .where(and_(
                DailyLog.user_id == user_id,
                DailyLog.date >= since,
                DailyLog.date <= until,
            ))
            .order_by(DailyLog.date)
        )).scalars().all()
        daily_totals = [
            {"date": str(l.date), "total_water_ml": round(l.total_water_ml or 0)}
            for l in logs
        ]
        return {
            "metric": "water", "period": period,
            "entries": len(rows),
            "rows": rows,
            "daily_totals": daily_totals,
        }

    if metric == "body_metrics":
        snaps = (await db.execute(
            select(HealthSnapshot)
            .where(and_(
                HealthSnapshot.user_id == user_id,
                HealthSnapshot.date >= since,
                HealthSnapshot.date <= until,
            ))
            .order_by(HealthSnapshot.date)
        )).scalars().all()
        rows = []
        for s in snaps:
            rows.append({
                "date": str(s.date),
                "sleep_hours": s.sleep_hours,
                "sleep_efficiency_pct": s.sleep_efficiency_pct,
                "hrv": s.hrv,
                "resting_hr": s.resting_hr,
                "recovery_score": s.recovery_score,
                "strain": s.strain,
                "steps": s.steps,
                "active_calories": s.active_calories,
                "exercise_minutes": s.exercise_minutes,
                "source": s.source,
            })
        return {
            "metric": "body_metrics", "period": period,
            "entries": len(rows),
            "rows": rows,
        }

    if metric == "day_detail":
        # Comprehensive single-day or range view: food + exercise + water +
        # body weight + health snapshot. The recap-friendly metric.
        logs = (await db.execute(
            select(DailyLog)
            .where(and_(
                DailyLog.user_id == user_id,
                DailyLog.date >= since,
                DailyLog.date <= until,
            ))
            .options(
                selectinload(DailyLog.food_entries),
                selectinload(DailyLog.exercise_entries),
            )
            .order_by(DailyLog.date)
            .execution_options(populate_existing=True)
        )).scalars().all()
        days = []
        for l in logs:
            days.append({
                "date": str(l.date),
                "totals": {
                    "calories": round(l.total_calories or 0),
                    "protein": round(l.total_protein or 0),
                    "carbs": round(l.total_carbs or 0),
                    "fats": round(l.total_fats or 0),
                    "water_ml": round(l.total_water_ml or 0),
                },
                "workout_completed": bool(l.workout_completed),
                "cardio_completed": bool(l.cardio_completed),
                "food": [{
                    "food_name": f.parsed_food_name or "",
                    "quantity": f.quantity or "",
                    "calories": round(f.calories or 0),
                    "protein": round(f.protein or 0),
                    "carbs": round(f.carbs or 0),
                    "fats": round(f.fats or 0),
                    "estimated": bool(f.estimated_flag),
                } for f in (l.food_entries or [])],
                "exercise": [{
                    "exercise_name": e.exercise_name or "",
                    "sets": e.sets, "reps": e.reps,
                    "weight_lbs": (round(e.weight * 2.20462, 1) if e.weight else None),
                    "duration_minutes": e.duration_minutes,
                    "cardio_type": e.cardio_type,
                } for e in (l.exercise_entries or [])],
            })
        return {
            "metric": "day_detail", "period": period,
            "days_with_data": sum(1 for d in days if d["food"] or d["exercise"]),
            "days": days,
        }

    return {"error": f"Unknown metric: {metric!r}"}


async def upsert_user_metric(
    db: AsyncSession,
    user_id: int,
    metric_type: str,
    value: float,
    unit: str = None,
    recorded_at: datetime = None,
) -> "WearableMetric":
    """
    Store a user-reported health/performance metric in WearableMetric (time-series)
    and, for known fields, also mirror it into today's HealthSnapshot.

    True upsert keyed on (user_id, metric_type, recorded_at, device_type='user_stated').
    If a matching row already exists, update value/unit in place — prevents duplicate
    rows when the model re-fires the same track_metric calls on follow-up turns. Only
    user_stated rows participate in the dedup; wearable-sourced rows have their own
    dedup paths and are untouched here.
    """
    from db.models import WearableMetric, HealthSnapshot

    ts = recorded_at or datetime.utcnow()
    snap_date = ts.date() if hasattr(ts, "date") else ts

    existing = (await db.execute(
        select(WearableMetric).where(and_(
            WearableMetric.user_id == user_id,
            WearableMetric.metric_type == metric_type,
            WearableMetric.recorded_at == ts,
            WearableMetric.device_type == "user_stated",
        ))
    )).scalar_one_or_none()

    if existing is not None:
        existing.value = value
        if unit:
            existing.unit = unit
        entry = existing
    else:
        entry = WearableMetric(
            user_id=user_id,
            device_type="user_stated",
            metric_type=metric_type,
            value=value,
            unit=unit,
            recorded_at=ts,
        )
        db.add(entry)

    # Mirror into HealthSnapshot for context_builder to pick up
    _snap_field_map = {
        "resting_hr": "resting_hr", "resting_heart_rate": "resting_hr",
        "hrv": "hrv", "heart_rate_variability": "hrv",
        "sleep_hours": "sleep_hours", "sleep": "sleep_hours",
        "steps": "steps",
        "active_calories": "active_calories",
        "spo2": "spo2_percentage", "blood_oxygen": "spo2_percentage",
        "skin_temp_celsius": "skin_temp_celsius", "skin_temp": "skin_temp_celsius",
        "recovery_score": "recovery_score",
        "strain": "strain",
        "exercise_minutes": "exercise_minutes",
        "avg_hr": "avg_hr", "average_hr": "avg_hr",
        "respiratory_rate": "respiratory_rate",
        "sleep_performance_pct": "sleep_performance_pct",
    }
    snap_field = _snap_field_map.get(metric_type.lower().replace(" ", "_"))
    if snap_field:
        snap = (await db.execute(
            select(HealthSnapshot).where(and_(
                HealthSnapshot.user_id == user_id,
                HealthSnapshot.date == snap_date,
            ))
        )).scalar_one_or_none()
        if snap is None:
            snap = HealthSnapshot(user_id=user_id, date=snap_date, source="user_stated")
            db.add(snap)
        setattr(snap, snap_field, value)

    await db.commit()
    await db.refresh(entry)
    return entry


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
