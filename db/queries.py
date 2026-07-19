from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry,
    ExerciseEntry, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
    Feedback, UserFoodMatch, PendingQuestion, WearableDevice, WearableMetric,
    DeviceToken,
)
from datetime import date, datetime, timedelta
from typing import Optional, List
import json
import logging
import os
import pytz

logger = logging.getLogger(__name__)


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


async def find_user_by_apple_sub(db: AsyncSession, apple_sub: str) -> Optional[User]:
    """Look up a user by their bound Apple Sign-in subject. Returns None if no
    user has this sub bound. Used by the session-create flow to recognize a
    returning Apple user (potentially from a different device) and route them
    back to their existing row.

    Eager-loads preferences so callers that snapshot the profile (e.g. the SETUP
    exchange's welcome-back payload) can read `user.preferences` without tripping
    async lazy-load."""
    result = await db.execute(
        select(User)
        .where(User.apple_sub == apple_sub)
        .options(selectinload(User.preferences))
    )
    return result.scalar_one_or_none()


async def set_apple_sub_for_user(db: AsyncSession, user_id: int, apple_sub: str) -> None:
    """Bind an Apple Sign-in subject to a user row. Idempotent: no-op if the
    user already has this exact sub. Raises ValueError if the user already has
    a DIFFERENT sub bound (defensive — should not happen given the unique
    index, but surfaces the bug rather than silently overwriting)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"user {user_id} not found")
    if user.apple_sub == apple_sub:
        return
    if user.apple_sub:
        raise ValueError(
            f"user {user_id} already bound to a different apple_sub"
        )
    user.apple_sub = apple_sub
    await db.commit()


# ── Device tokens (APNs push registration) ────────────────────────────────────


async def upsert_device_token(
    db: AsyncSession,
    user_id: int,
    token: str,
    *,
    platform: str = "apns",
    environment: str = "production",
) -> DeviceToken:
    """Register or re-register a push token for a user. Idempotent on every
    app launch — safe to call repeatedly.

    Three cases:
      1. Token is new → INSERT.
      2. Token exists under this user → bump `last_seen_at`, clear
         `revoked_at` (re-activate if previously revoked), refresh
         platform/environment in case the build channel changed
         (TestFlight → App Store flips environment).
      3. Token exists under a DIFFERENT user (device handoff: someone signed
         in to a new account on the same physical device) → REASSIGN
         user_id rather than insert a duplicate.
    """
    result = await db.execute(select(DeviceToken).where(DeviceToken.token == token))
    existing = result.scalar_one_or_none()
    if existing:
        existing.user_id = user_id
        existing.platform = platform
        existing.environment = environment
        existing.last_seen_at = datetime.utcnow()
        existing.revoked_at = None
        await db.commit()
        return existing
    new = DeviceToken(
        user_id=user_id,
        token=token,
        platform=platform,
        environment=environment,
    )
    db.add(new)
    await db.commit()
    await db.refresh(new)
    return new


async def revoke_device_token(db: AsyncSession, user_id: int, token: str) -> bool:
    """Mark a token revoked. Only the owning user can revoke their token — an
    attempt to revoke another user's token is treated as "not found" and
    returns False (defensive: a leaked session token shouldn't be able to
    silently revoke arbitrary devices). Returns True iff a row was updated.
    """
    result = await db.execute(
        select(DeviceToken).where(
            and_(DeviceToken.token == token, DeviceToken.user_id == user_id)
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.revoked_at = datetime.utcnow()
    await db.commit()
    return True


async def active_device_tokens_for_user(db: AsyncSession, user_id: int) -> List[DeviceToken]:
    """All non-revoked push tokens for a user. Used by the APNs sender (slice
    2b) to fan a single nudge out to every live device the user has
    registered."""
    result = await db.execute(
        select(DeviceToken).where(
            and_(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
        )
    )
    return list(result.scalars().all())


def _gen_link_code() -> str:
    import secrets
    return "LINK-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))


async def generate_link_code(db: AsyncSession, user: User) -> str:
    """Mint a one-time link code (10 min) on the canonical user that generated it."""
    code = _gen_link_code()
    user.link_code = code
    # 30 min, not 10 — a cross-app hop (read the code in Telegram, switch to the
    # iOS app, find the link screen, type it) routinely blew past a 10-min window,
    # surfacing as a confusing "code expired" error for beta testers.
    user.link_code_expires = datetime.utcnow() + timedelta(minutes=30)
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


async def migrate_user_data(db: AsyncSession, consumer: User, canonical: User) -> dict:
    """Move `consumer`'s logged data onto `canonical` so linking an iOS account that
    already has data MERGES it instead of orphaning it (the old 422). Same-date
    daily_logs + health snapshots merge (canonical's snapshot wins a conflict);
    body_metrics + brain attributes de-dup. Returns a small stats dict. Run once,
    at link time, before the link is welded."""
    from sqlalchemy import update as _update
    from db.models import WaterEntry, UserAttribute

    if consumer.id == canonical.id:
        return {}
    stats = {"days_moved": 0, "days_merged": 0, "weights": 0, "snapshots": 0, "attrs": 0}

    # 1) daily_logs (+ the food / exercise / water entries hanging off them)
    c_logs = (await db.execute(
        select(DailyLog).where(DailyLog.user_id == consumer.id))).scalars().all()
    touched: set = set()
    for log in c_logs:
        target = (await db.execute(select(DailyLog).where(and_(
            DailyLog.user_id == canonical.id, DailyLog.date == log.date)))).scalar_one_or_none()
        if target:   # canonical already has this day — fold the entries in, drop the dup log
            for Model in (FoodEntry, ExerciseEntry):
                await db.execute(_update(Model).where(Model.daily_log_id == log.id)
                                 .values(daily_log_id=target.id))
            await db.execute(_update(WaterEntry).where(WaterEntry.daily_log_id == log.id)
                             .values(daily_log_id=target.id, user_id=canonical.id))
            await db.delete(log)
            touched.add(target.id)
            stats["days_merged"] += 1
        else:        # canonical doesn't have this day — just repoint it
            log.user_id = canonical.id
            await db.execute(_update(WaterEntry).where(WaterEntry.daily_log_id == log.id)
                             .values(user_id=canonical.id))
            touched.add(log.id)
            stats["days_moved"] += 1
    # water logged before a daily_log existed (daily_log_id NULL)
    await db.execute(_update(WaterEntry).where(and_(
        WaterEntry.user_id == consumer.id, WaterEntry.daily_log_id.is_(None)))
        .values(user_id=canonical.id))
    await db.flush()
    for lid in touched:
        await recompute_log_totals(db, lid)

    # 2) body_metrics — repoint, dropping a same-(day, source) duplicate
    def _bm_key(b):
        ts = getattr(b, "timestamp", None)
        return (ts.date() if ts else None, getattr(b, "source", None))
    seen = {_bm_key(b) for b in (await db.execute(
        select(BodyMetric).where(BodyMetric.user_id == canonical.id))).scalars().all()}
    for b in (await db.execute(
            select(BodyMetric).where(BodyMetric.user_id == consumer.id))).scalars().all():
        if _bm_key(b) in seen:
            await db.delete(b)
        else:
            b.user_id = canonical.id
            seen.add(_bm_key(b))
            stats["weights"] += 1

    # 3) health_snapshots (unique user_id, date) — canonical's wins a date clash
    can_dates = {s.date for s in (await db.execute(
        select(HealthSnapshot).where(HealthSnapshot.user_id == canonical.id))).scalars().all()}
    for s in (await db.execute(
            select(HealthSnapshot).where(HealthSnapshot.user_id == consumer.id))).scalars().all():
        if s.date in can_dates:
            await db.delete(s)
        else:
            s.user_id = canonical.id
            can_dates.add(s.date)
            stats["snapshots"] += 1

    # 4) user_attributes (unique user_id, key) — bring over only keys canonical lacks
    can_keys = {a.attribute_key for a in (await db.execute(
        select(UserAttribute).where(UserAttribute.user_id == canonical.id))).scalars().all()}
    for a in (await db.execute(
            select(UserAttribute).where(UserAttribute.user_id == consumer.id))).scalars().all():
        if a.attribute_key not in can_keys:
            a.user_id = canonical.id
            can_keys.add(a.attribute_key)
            stats["attrs"] += 1

    await db.commit()
    return stats


def _platform_of(telegram_id: str) -> str:
    """Platform of a namespaced identity string: 'ios:'/'apple:' → iOS (APNs),
    'im:' → iMessage, anything else (numeric chat id) → Telegram."""
    tid = telegram_id or ""
    if tid.startswith(("ios:", "apple:")):
        return "ios"
    if tid.startswith("im:"):
        return "imessage"
    return "telegram"


# Platforms a proactive message can actually be delivered on. 'web' and other
# labels that show up in conversation_logs.platform are not send targets.
_ROUTABLE_PLATFORMS = ("ios", "imessage", "telegram")


async def _last_user_platform(db: AsyncSession, user_id: int) -> Optional[str]:
    """Platform of the user's most recent REAL message (their own turns, not our
    proactive sends) — where the conversation actually lives right now."""
    result = await db.execute(
        select(ConversationLog.platform)
        .where(
            ConversationLog.user_id == user_id,
            ConversationLog.source_type != "proactive",
            ConversationLog.raw_message.isnot(None),
            ConversationLog.raw_message != "",
            ConversationLog.raw_message != "[start]",
            ConversationLog.platform.in_(_ROUTABLE_PLATFORMS),
        )
        .order_by(ConversationLog.timestamp.desc(), ConversationLog.id.desc())
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def resolve_send_target(db: AsyncSession, canonical: User) -> str:
    """
    Decide which platform identity a proactive message to `canonical` should go to.

    Returns the identity string to pass to the scheduler's _send():
      'ios:<uuid>'/'apple:<sub>' routes to APNs push, 'im:<addr>' to iMessage,
      a numeric string to Telegram.

    Priority — proactive messages follow the conversation:
      1. The platform of the user's most recent real message (among identities
         we actually hold). A user who moved from Telegram to the iOS app gets
         their nudges on iOS the moment they start talking there — a stale
         channel_preference from their old platform must not pin them forever
         (Gi kept getting Telegram nudges after going all-in on iOS).
      2. Their explicit channel_preference, when they've never messaged (new
         users) or their activity platform has no identity here.
      3. The canonical row's own identity.

    Fully safe when unlinked (falls back to canonical.telegram_id).
    """
    # Identity per platform, canonical first so it wins platform collisions.
    result = await db.execute(
        select(User).where(User.linked_to_user_id == canonical.id)
    )
    by_platform: dict[str, str] = {}
    for u in [canonical] + list(result.scalars().all()):
        by_platform.setdefault(_platform_of(u.telegram_id), u.telegram_id)

    last_platform = await _last_user_platform(db, canonical.id)
    return _pick_send_target(canonical, by_platform, last_platform)


def _pick_send_target(canonical: User, by_platform: dict, last_platform) -> str:
    """The routing priority shared by resolve_send_target and its batch twin —
    one place so the two can never drift: activity platform → explicit
    preference → canonical identity."""
    if last_platform in by_platform:
        return by_platform[last_platform]
    pref = getattr(canonical, "channel_preference", None)
    if pref in by_platform:
        return by_platform[pref]
    return canonical.telegram_id


async def batch_send_targets(db: AsyncSession, canonicals: list) -> dict:
    """resolve_send_target for MANY canonical users in TWO set queries — the
    30-min scheduler tick used to run two queries per user. Returns
    {canonical_user_id: send_identity}; same priority via _pick_send_target."""
    from sqlalchemy import func as _func
    ids = [u.id for u in canonicals]
    if not ids:
        return {}

    by_user: dict[int, dict] = {
        u.id: {_platform_of(u.telegram_id): u.telegram_id} for u in canonicals
    }
    secondaries = (await db.execute(
        select(User).where(User.linked_to_user_id.in_(ids))
    )).scalars().all()
    for s in secondaries:
        by_user[s.linked_to_user_id].setdefault(
            _platform_of(s.telegram_id), s.telegram_id)

    # Newest real-message platform per user in one query (window function —
    # supported by both Postgres and the SQLite the tests run on).
    rn = _func.row_number().over(
        partition_by=ConversationLog.user_id,
        order_by=(ConversationLog.timestamp.desc(), ConversationLog.id.desc()),
    ).label("rn")
    sub = (
        select(ConversationLog.user_id, ConversationLog.platform, rn)
        .where(
            ConversationLog.user_id.in_(ids),
            ConversationLog.source_type != "proactive",
            ConversationLog.raw_message.isnot(None),
            ConversationLog.raw_message != "",
            ConversationLog.raw_message != "[start]",
            ConversationLog.platform.in_(_ROUTABLE_PLATFORMS),
        )
    ).subquery()
    rows = (await db.execute(
        select(sub.c.user_id, sub.c.platform).where(sub.c.rn == 1)
    )).all()
    last_by_user = {uid: plat for uid, plat in rows}

    return {
        u.id: _pick_send_target(u, by_user[u.id], last_by_user.get(u.id))
        for u in canonicals
    }


# Logging-day rollover: the local hour at which "today" advances to the new
# calendar day. DEFAULT 0 (midnight) — the new day's log is available at 12am,
# matching what the iOS app shows (it uses the device calendar date everywhere).
# A non-zero value adds a small-hours GRACE so a late-night log (e.g. dinner at
# 12:02am) counts toward the PREVIOUS day; that was the old 4am MacroFactor-style
# behavior, but it left the app showing yesterday's totals after midnight. The
# rare late-night case is now covered by retroactive logging ("log it to
# yesterday"). Tunable via env without a code change (set to 4 to restore grace).
# Dedup/recall stay consistent at any value (they all anchor on _user_today).
try:
    LOGGING_DAY_ROLLOVER_HOUR = max(0, min(23, int(os.getenv("LOGGING_DAY_ROLLOVER_HOUR", "0"))))
except (TypeError, ValueError):
    LOGGING_DAY_ROLLOVER_HOUR = 0


def _user_today(user_timezone: str) -> date:
    """The user's current LOGGING day (see LOGGING_DAY_ROLLOVER_HOUR) — the day new
    entries belong to. Before the rollover hour, that's still yesterday."""
    from core.timezones import safe_timezone
    # safe_timezone: a junk users.timezone (pre-validation rows held free text
    # like "Naples, USA") must degrade to UTC here, not 500 every chat turn.
    tz = safe_timezone(user_timezone)
    now = datetime.now(tz)
    d = now.date()
    if now.hour < LOGGING_DAY_ROLLOVER_HOUR:
        d = d - timedelta(days=1)
    return d


def _logging_day_of(dt_utc: datetime, user_timezone: str) -> date:
    """The LOGGING day a stored (UTC) timestamp belongs to, in the user's tz —
    the same rollover-hour grace window as _user_today. BodyMetric.timestamp is
    written via server_default func.now() (naive UTC), so localize to UTC first,
    then convert to the user's zone before applying the rollover. Used by the
    weight UPSERT to decide whether an existing row is the SAME calendar day."""
    from core.timezones import safe_timezone
    tz = safe_timezone(user_timezone)
    if dt_utc.tzinfo is None:
        dt_utc = pytz.utc.localize(dt_utc)
    local = dt_utc.astimezone(tz)
    d = local.date()
    if local.hour < LOGGING_DAY_ROLLOVER_HOUR:
        d = d - timedelta(days=1)
    return d


async def get_today_log(db: AsyncSession, user_id: int,
                        user_timezone: str = "UTC") -> Optional[DailyLog]:
    _opts = [
        selectinload(DailyLog.food_entries),
        selectinload(DailyLog.exercise_entries),
        selectinload(DailyLog.water_entries),
    ]

    async def _fetch(d: date) -> Optional[DailyLog]:
        # Duplicate-tolerant: uq_daily_log_user_date now guarantees ≤1 row, but a
        # legacy duplicate (created by a race before the constraint shipped) must
        # not hard-crash the coaching turn with MultipleResultsFound. Take the
        # oldest row deterministically instead of raising.
        r = await db.execute(
            select(DailyLog)
            .where(and_(DailyLog.user_id == user_id, DailyLog.date == d))
            .order_by(DailyLog.id)
            .options(*_opts)
        )
        return r.scalars().first()

    today = _user_today(user_timezone)
    log = await _fetch(today)
    if log is not None:
        return log

    utc_today = _user_today("UTC")
    if utc_today != today:
        log = await _fetch(utc_today)
        if log is not None:
            return log


async def batch_today_logs(db: AsyncSession, users: list) -> dict:
    """get_today_log for MANY users in ONE query — the scheduler tick used to
    fetch each user's today-log individually. Per-user candidate days (local
    today + UTC fallback) are computed in memory; every (user, date) pair comes
    back in a single eager-loaded select with the same precedence and
    duplicate-tolerance (lowest id wins) as get_today_log.

    Returns {user_id: DailyLog | None} with an entry for EVERY input user, so
    callers can distinguish "no log" (None) from "not batched" (missing key)."""
    if not users:
        return {}
    utc_today = _user_today("UTC")
    candidates = {
        u.id: (_user_today(getattr(u, "timezone", None) or "UTC"), utc_today)
        for u in users
    }
    all_dates = {d for pair in candidates.values() for d in pair}
    result = await db.execute(
        select(DailyLog)
        .where(DailyLog.user_id.in_(list(candidates)),
               DailyLog.date.in_(list(all_dates)))
        .order_by(DailyLog.id)
        .options(
            selectinload(DailyLog.food_entries),
            selectinload(DailyLog.exercise_entries),
            selectinload(DailyLog.water_entries),
        )
    )
    by_key: dict = {}
    for log in result.scalars().all():
        by_key.setdefault((log.user_id, log.date), log)   # ordered by id → oldest wins
    return {
        uid: by_key.get((uid, local_d)) or by_key.get((uid, utc_d))
        for uid, (local_d, utc_d) in candidates.items()
    }


async def get_log_by_date(db: AsyncSession, user_id: int, target_date: date) -> Optional[DailyLog]:
    """Fetch a specific day's log with food/exercise/water entries eagerly loaded."""
    result = await db.execute(
        select(DailyLog)
        .where(and_(DailyLog.user_id == user_id, DailyLog.date == target_date))
        .order_by(DailyLog.id)
        .options(
            selectinload(DailyLog.food_entries),
            selectinload(DailyLog.exercise_entries),
            selectinload(DailyLog.water_entries),
        )
    )
    # Duplicate-tolerant (see get_today_log._fetch) — never raise on a legacy dup.
    return result.scalars().first()


async def get_or_create_log_for_date(
    db: AsyncSession, user_id: int, target_date: date
) -> DailyLog:
    """Get or create a DailyLog for any specific date (used for past-day logging)."""
    log = await get_log_by_date(db, user_id, target_date)
    if not log:
        log = DailyLog(user_id=user_id, date=target_date)
        db.add(log)
        try:
            await db.commit()
        except IntegrityError:
            # Lost the create race (uq_daily_log_user_date) — read the winner back.
            await db.rollback()
        log = await get_log_by_date(db, user_id, target_date)
    return log


async def get_or_create_today_log(db: AsyncSession, user_id: int,
                                  user_timezone: str = "UTC") -> DailyLog:
    log = await get_today_log(db, user_id, user_timezone)
    if not log:
        today = _user_today(user_timezone)
        log = DailyLog(user_id=user_id, date=today)
        db.add(log)
        try:
            await db.commit()
        except IntegrityError:
            # Lost the create race to a concurrent request (uq_daily_log_user_date).
            # The winner's row exists — roll back ours and read it back instead of
            # creating a duplicate (the bug this constraint exists to prevent).
            await db.rollback()
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


def _invalidate_briefing_for_log(daily_log_id_or_user: int, by_user: bool = False) -> None:
    """Drop the cached coach briefing for the user behind `daily_log_id` (or
    the user directly when `by_user=True`). Called from add_* writes so a log
    immediately invalidates the cached hero/insights — the next /briefing fetch
    regenerates against the fresh day. Best-effort: a failed import / closed
    session must never break the write path."""
    try:
        from api.insights import invalidate_briefing
        if by_user:
            invalidate_briefing(daily_log_id_or_user)
        else:
            # daily_log → user_id via the loaded DailyLog row in the SAME unit
            # of work; we look it up cheaply on the same db session via a
            # SELECT below in the call sites that have a db handy. Here we just
            # accept a user_id when the caller can provide it (less plumbing).
            pass
    except Exception:
        pass


async def add_food_entry(db: AsyncSession, daily_log_id: int, **kwargs) -> FoodEntry:
    entry = FoodEntry(daily_log_id=daily_log_id, **kwargs)
    db.add(entry)
    await db.flush()  # entry must be visible to the recompute query
    await recompute_log_totals(db, daily_log_id)
    await db.commit()
    await db.refresh(entry)
    # Drop cached briefing so the next Coach open regenerates against the new
    # totals — without this the user logs and still sees the stale hero copy.
    try:
        log = await db.get(DailyLog, daily_log_id)
        if log: _invalidate_briefing_for_log(log.user_id, by_user=True)
    except Exception:
        pass
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
    try:
        log = await db.get(DailyLog, daily_log_id)
        if log: _invalidate_briefing_for_log(log.user_id, by_user=True)
    except Exception:
        pass
    return entry


async def add_body_metric(db: AsyncSession, user_id: int,
                          weight_kg: float, source: str = "manual",
                          when: Optional[datetime] = None,
                          **kwargs) -> BodyMetric:
    # Source-aware, ONE-row-per-(user, calendar-day, source) UPSERT.
    #
    # Weight arrives from two independent worlds that must not collide:
    #   • "manual"        — the user's DELIBERATE weigh-in (chat log_body_weight,
    #                       web /api/weight/log, iOS quick-log). This is the
    #                       headline number.
    #   • "apple_health"  — a PASSIVE wearable/HealthKit sync. Useful for trend
    #                       fill-in, but must never overwrite the user's own
    #                       reading.
    #
    # The old guard folded only NEAR-IDENTICAL (<0.06 kg / 30 min) readings, so a
    # manual 84.73 and a HealthKit 85.28 nine minutes later (~0.55 kg apart, a
    # normal scale/HealthKit discrepancy) escaped the fold and STACKED — four rows
    # oscillating across one morning, the dashboard headlining the latest (passive)
    # value, and the user's deliberate number buried (Danny 2026-06-27).
    #
    # Fix: collapse by (user, local logging day, source). A repeat write from the
    # SAME source on the SAME day — a HealthKit re-deliver, or a manual correction
    # ("188 actually") — UPDATES the existing row in place instead of inserting a
    # new one, so each source contributes at most ONE row per day. manual and
    # apple_health are kept as SEPARATE rows; one is never folded into the other.
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    tz = getattr(user, "timezone", None) or "UTC"
    # `when` (a naive-UTC datetime) BACKFILLS a past weigh-in; default is now. All
    # day-matching is by the user's LOGGING day so it honors the rollover hour for
    # both a live weigh-in and a retroactive one.
    ts = when if when is not None else datetime.utcnow()
    target_day = _logging_day_of(ts, tz)

    # Pull rows in a ±48h window AROUND the target timestamp (covers both today and
    # a backfilled past date) and match the SAME source + SAME logging day in
    # Python — timestamps are stored as naive UTC, so the day boundary must be
    # computed in the user's zone rather than via a SQL date() on the raw column.
    rows = (await db.execute(
        select(BodyMetric)
        .where(BodyMetric.user_id == user_id,
               BodyMetric.timestamp >= ts - timedelta(hours=48),
               BodyMetric.timestamp <= ts + timedelta(hours=48))
        .order_by(desc(BodyMetric.timestamp))
    )).scalars().all()

    existing = next(
        (r for r in rows
         if (r.source or "manual") == source
         and r.timestamp is not None
         and _logging_day_of(r.timestamp, tz) == target_day),
        None,
    )

    # Does a MANUAL reading already exist for the target day? (Across either
    # branch.) An apple_health write must not touch current_weight_kg when one
    # does — the user's deliberate weigh-in stays the headline.
    manual_day_exists = any(
        (r.source or "manual") == "manual"
        and r.timestamp is not None
        and _logging_day_of(r.timestamp, tz) == target_day
        for r in rows
    )

    # A backfilled PAST weigh-in writes that day's row + feeds the trend, but is
    # NOT the user's CURRENT weight — only a today/live reading moves the headline.
    is_current_day = target_day >= _user_today(tz)

    def _sync_current_weight():
        # manual always wins. apple_health updates current_weight_kg only when
        # there's no manual reading for the day to defer to. Past backfills never
        # move the headline.
        if not is_current_day:
            return
        if source == "manual" or not manual_day_exists:
            user.current_weight_kg = weight_kg

    if existing is not None:
        # Same source, same day → update in place (correction or re-deliver).
        existing.weight_kg = weight_kg
        existing.timestamp = ts
        if kwargs.get("context") is not None:
            existing.context = kwargs["context"]
        if kwargs.get("bodyfat_estimate") is not None:
            existing.bodyfat_estimate = kwargs["bodyfat_estimate"]
        if kwargs.get("waist_cm") is not None:
            existing.waist_cm = kwargs["waist_cm"]
        if kwargs.get("photo_reference") is not None:
            existing.photo_reference = kwargs["photo_reference"]
        _sync_current_weight()
        await db.commit()
        await db.refresh(existing)
        _invalidate_briefing_for_log(user_id, by_user=True)
        return existing

    metric = BodyMetric(user_id=user_id, weight_kg=weight_kg, source=source,
                        timestamp=ts, **kwargs)
    db.add(metric)
    _sync_current_weight()

    await db.commit()
    await db.refresh(metric)
    _invalidate_briefing_for_log(user_id, by_user=True)
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
    _invalidate_briefing_for_log(user_id, by_user=True)
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


async def get_recent_conversations_linked(db: AsyncSession, user: User,
                                          limit: int = 8,
                                          source_types: Optional[List[str]] = None
                                          ) -> List[ConversationLog]:
    """Recent turns across EVERY identity linked to the same canonical account
    (Telegram + iMessage + iOS), newest-first — so a user who chats on Telegram
    and opens the app sees ONE unified thread instead of just the app's turns.

    The canonical account is `user.linked_to_user_id or user.id`; we gather that
    row plus every identity that points at it. Falls back to a solo `user.id`
    when nothing is linked, so single-surface users are unaffected.
    """
    canonical_id = user.linked_to_user_id or user.id
    id_rows = await db.execute(
        select(User.id).where(
            (User.id == canonical_id) | (User.linked_to_user_id == canonical_id)
        )
    )
    ids = list(id_rows.scalars().all()) or [user.id]
    stmt = select(ConversationLog).where(ConversationLog.user_id.in_(ids))
    if source_types is not None:
        stmt = stmt.where(ConversationLog.source_type.in_(source_types))
    stmt = stmt.order_by(desc(ConversationLog.timestamp)).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_conversation_by_idempotency_key(
    db: AsyncSession, user_id: int, key: str
) -> Optional[ConversationLog]:
    """Return this user's already-persisted turn for `key`, or None.

    The lookup behind deterministic retry dedup: an inbound request carries a
    stable per-send id (iOS UUID / Telegram update_id / iMessage GUID). If a row
    with that key already exists, the inbound is a retry / webhook redelivery —
    the caller replays (iOS) or skips (webhook) instead of re-running the turn.
    Scoped to user_id so keys only need to be unique per user."""
    if not key:
        return None
    return (await db.execute(
        select(ConversationLog)
        .where(ConversationLog.user_id == user_id,
               ConversationLog.idempotency_key == key)
        .order_by(ConversationLog.id.desc())
        .limit(1)
    )).scalars().first()


async def has_real_conversation(db: AsyncSession, user_id: int) -> bool:
    """True if the user's thread holds anything beyond the seeded '[start]'
    intro. Used to guard the intro seed: if the user already started talking
    (or a proactive went out), a greeting would land MID-conversation with a
    now-timestamp — skip it rather than read broken."""
    result = await db.execute(
        select(ConversationLog.id)
        .where(
            ConversationLog.user_id == user_id,
            ConversationLog.raw_message != "[start]",
        )
        .limit(1)
    )
    return result.first() is not None


async def log_conversation(db: AsyncSession, user_id: int, raw_message: str,
                           response: str, parsed_intent: str = None,
                           source_type: str = "text",
                           skills_fired: str | None = None,
                           platform: str | None = None,
                           cards: Optional[list] = None,
                           idempotency_key: str | None = None):
    """Persist one conversation turn.

    `platform` tags which surface the turn happened on ("telegram" | "imessage"
    | "web"). Optional + defaults to the model default ("telegram") so existing
    callers are unchanged; the dashboard web-chat passes platform="web" so the
    unified thread can label it correctly across all surfaces.

    `cards` is the turn's typed inline-card list (Response.cards). Stored as JSON
    so native clients can rehydrate the rich cards on history restore. Only
    written when non-empty — text-only / chat-bot turns leave it null.

    `idempotency_key` stamps the inbound request's stable id so a later retry of
    the SAME send is recognized via get_conversation_by_idempotency_key and
    replayed/skipped instead of re-running. Nullable for callers that don't supply
    one (they keep the text-window fallback)."""
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
    if cards:
        entry.cards_json = json.dumps(cards)
    if idempotency_key:
        entry.idempotency_key = idempotency_key
    db.add(entry)
    await db.commit()

    # A new turn may carry a near-term plan the Coach brief must respect ("with
    # family tonight"), so drop the cached brief — the next open regenerates with
    # this turn in context. Lazy import avoids a db→api import cycle; best-effort.
    try:
        from api.insights import invalidate_briefing
        invalidate_briefing(user_id)
    except Exception:
        pass
    # The row is the turn's stable identity — native clients dedup history by
    # its id, so callers surface it on the wire (turn.log_id → payload/history).
    return entry


async def clear_today_conversations(db: AsyncSession, user_id: int, tz: str = "UTC") -> None:
    """Delete TODAY's conversation history for a user in their local timezone —
    called after /reset today. Was previously wiping the entire conversation
    history (bug); now scoped to the user's local calendar day."""
    try:
        zone = pytz.timezone(tz)
    except Exception:
        zone = pytz.utc
    now_local = datetime.now(zone)
    start_local = zone.localize(datetime(now_local.year, now_local.month, now_local.day))
    start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
    await db.execute(
        delete(ConversationLog).where(
            and_(
                ConversationLog.user_id == user_id,
                ConversationLog.timestamp >= start_utc,
            )
        )
    )
    await db.commit()


async def reload_user(db: AsyncSession, user_id: int) -> User:
    """Re-query a user with all relationships eagerly loaded."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.preferences))
    )
    return result.scalar_one()


async def save_user_location(db: AsyncSession, user_id: int,
                             lat: float, lng: float,
                             city: Optional[str] = None) -> None:
    """Persist a freshly shared Telegram location. Sets lat/lng + timestamp, and
    backfills city/timezone ONLY when we resolved them and they're not already set
    (never clobbers a city the user told us themselves). Used by the location
    handler; gated end-to-end by LOCATION_ENABLED."""
    user = await db.get(User, user_id)
    if not user:
        return
    user.lat = float(lat)
    user.lng = float(lng)
    user.location_updated_at = datetime.utcnow()
    if city and not user.city:
        user.city = city
        # Best-effort timezone from the city, mirroring how onboarding resolves it.
        try:
            from core.timezones import resolve_timezone
            tz = resolve_timezone(city)
            if tz and (not user.timezone or user.timezone == "UTC"):
                user.timezone = tz
        except Exception:
            pass
    await db.commit()


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


async def apply_landing_profile_to_user(
    db: AsyncSession, user: "User", profile: dict
) -> None:
    """
    Apply a consumed pre_registration profile dict to a user row.
    Mirrors the inline logic in bot/telegram_handler.py SETUP-XXX consumption;
    extracted so iOS (api/auth_routes.py) and Telegram stay in sync as new form
    fields are added. Telegram's call site is still inline today — swap in a
    follow-up slice once the iOS path is verified in production.

    Sets onboarding_completed=True and persists macro targets via UserPreferences.
    Caller is responsible for db.commit() and any platform-specific follow-ups
    (Telegram webhook tokens, iOS session issuance).
    """
    from db.models import UserPreferences

    user.name                = profile.get("name") or user.name
    user.age                 = profile.get("age") or user.age
    user.sex                 = profile.get("sex") or user.sex
    user.height_cm           = profile.get("height_cm") or user.height_cm
    user.current_weight_kg   = profile.get("weight_kg") or user.current_weight_kg
    user.primary_goal        = profile.get("primary_goal") or user.primary_goal
    user.training_experience = profile.get("training_experience") or user.training_experience
    if profile.get("dietary_preferences"):
        user.dietary_preferences = profile["dietary_preferences"]
    if profile.get("timezone"):
        # Pre-registration rows may predate intake validation — only a
        # normalized IANA zone may land in users.timezone (junk 500s turns).
        from core.timezones import normalize_timezone
        _tz = normalize_timezone(profile["timezone"])
        if _tz:
            user.timezone = _tz
    if profile.get("goal_weight_lbs"):
        user.goal_weight_kg = round(profile["goal_weight_lbs"] / 2.20462, 2)
    user.onboarding_completed = True

    if any(profile.get(k) is not None for k in
           ("calorie_target", "protein_target", "carb_target", "fat_target")):
        prefs = user.preferences
        if not prefs:
            prefs = UserPreferences(user_id=user.id)
            db.add(prefs)
        if profile.get("calorie_target") is not None:
            prefs.calorie_target = int(profile["calorie_target"])
        if profile.get("protein_target") is not None:
            prefs.protein_target = int(profile["protein_target"])
        if profile.get("carb_target") is not None:
            prefs.carb_target = int(profile["carb_target"])
        if profile.get("fat_target") is not None:
            prefs.fat_target = int(profile["fat_target"])


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


# Source priority for the ONE merged snapshot per (user, day). Apple Health
# supplies steps/sleep/HR; Whoop supplies recovery/strain/HRV. Both write the
# same daily row — so the `source` LABEL must reflect the richest contributor,
# not whoever wrote last. Without this, Apple Health's frequent steps pushes kept
# relabeling a Whoop recovery row to "apple_health" (Danny saw Apple Health on
# the wearable card while his recovery score was clearly Whoop's).
_SNAPSHOT_SOURCE_RANK = {"whoop": 2, "apple_health": 1}


def _source_rank(s: Optional[str]) -> int:
    return _SNAPSHOT_SOURCE_RANK.get(s or "", 0)


# Metrics BOTH wearables report for the same day. Once a higher-ranked source
# (Whoop) owns the row, a lower-ranked write (Apple Health) may only FILL a
# still-empty field — never replace one. Without this, the day's energy kept
# BOUNCING between Whoop's active+resting and Apple's active-only read on every
# alternate sync (Danny 2026-07-03: 1,440 ↔ 230 kcal). Apple-only fields
# (steps, stand_hours, exercise_minutes) aren't listed, so they always merge.
_CONTESTED_FIELDS = {
    "active_calories", "resting_calories", "hrv", "resting_hr", "avg_hr",
    "sleep_hours", "sleep_deep_hours", "sleep_rem_hours",
    "sleep_performance_pct", "sleep_need_hours", "sleep_efficiency_pct",
    "respiratory_rate", "spo2_percentage", "skin_temp_celsius",
}


def _merge_snapshot_fields(snap: HealthSnapshot, kwargs: dict) -> None:
    """Apply non-None updates to an existing snapshot WITHOUT downgrading its
    source: the label never ranks down, and contested metrics from a
    lower-ranked source fill gaps but never overwrite the richer source's
    values. Then promote the label to 'whoop' if the row carries whoop-only
    metrics (recovery/strain) — those can't come from Apple Health."""
    incoming_rank = _source_rank(kwargs.get("source"))
    row_rank = _source_rank(snap.source)
    for k, v in kwargs.items():
        if v is None:
            continue
        if k == "source" and incoming_rank < row_rank:
            continue  # never relabel a richer source down
        if (k in _CONTESTED_FIELDS and incoming_rank < row_rank
                and getattr(snap, k, None) is not None):
            continue  # lower-ranked source fills gaps only, never replaces
        setattr(snap, k, v)
    if (snap.recovery_score is not None or snap.strain is not None) \
            and _source_rank(snap.source) < _source_rank("whoop"):
        snap.source = "whoop"


async def upsert_health_snapshot(db: AsyncSession, user_id: int,
                                  snapshot_date: date, **kwargs) -> HealthSnapshot:
    """Insert or update a HealthSnapshot for (user_id, date)."""
    async def _fetch() -> Optional[HealthSnapshot]:
        result = await db.execute(
            select(HealthSnapshot).where(
                and_(HealthSnapshot.user_id == user_id,
                     HealthSnapshot.date == snapshot_date)
            ).order_by(HealthSnapshot.id)
        )
        # Duplicate-tolerant (uq_health_snapshot_user_date) — never raise on a legacy dup.
        return result.scalars().first()

    snap = await _fetch()
    if snap:
        _merge_snapshot_fields(snap, kwargs)
        await db.commit()
        return snap

    snap = HealthSnapshot(user_id=user_id, date=snapshot_date, **kwargs)
    db.add(snap)
    try:
        await db.commit()
    except IntegrityError:
        # Lost the create race to a concurrent webhook — update the winner's row.
        await db.rollback()
        snap = await _fetch()
        if snap is not None:
            _merge_snapshot_fields(snap, kwargs)
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

    # A serving/portion edit scales the WHOLE nutrient profile, not just the
    # macros the client sends: fiber, sugar, sodium, and the micronutrient
    # panel follow the calorie ratio, so the inspector's readout stays honest
    # after "make it 200g". (The iOS editor deliberately doesn't display
    # micros — it relies on this.) Ratio guard: only when both sides are
    # positive and the change is a real rescale, not a hand-corrected zero.
    if "calories" in changes:
        _old_cal = float(entry.calories or 0)
        _new_cal = float(changes["calories"] or 0)
        if _old_cal > 0 and _new_cal > 0 and abs(_new_cal - _old_cal) > 0.5:
            _r = _new_cal / _old_cal
            for _f in ("fiber", "sugar", "sodium"):
                _v = getattr(entry, _f, None)
                if _v is not None:
                    setattr(entry, _f, round(float(_v) * _r, 2))
            # Sodium sanity: a portion upscale can push a vetted value past
            # any plausible single-entry amount (3000mg × a 3× edit = 9000).
            # Cap at the shared enrichment bound rather than drop — the
            # pre-edit value already passed the clamp, so the food IS salty;
            # keep the signal, bound the absurdity.
            from core.food_intelligence import SODIUM_IMPLAUSIBLE_MG
            if entry.sodium is not None and entry.sodium > SODIUM_IMPLAUSIBLE_MG:
                logger.warning(
                    f"serving edit scaled sodium to {entry.sodium:.0f}mg for "
                    f"entry {entry.id} ({entry.parsed_food_name!r}) — capping "
                    f"at {SODIUM_IMPLAUSIBLE_MG}mg"
                )
                entry.sodium = float(SODIUM_IMPLAUSIBLE_MG)
            if entry.micronutrients_json:
                try:
                    _micros = json.loads(entry.micronutrients_json)
                    entry.micronutrients_json = json.dumps({
                        k: round(float(v) * _r, 3)
                        for k, v in _micros.items()
                        if isinstance(v, (int, float))
                    })
                except (ValueError, TypeError):
                    pass  # malformed panel — leave untouched, never block the edit

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

    # `timestamp` marks last-logged-at — the incremental-append path bumps it so
    # a growing session row reflects its latest set (and the refire guard works).
    for field in ("exercise_name", "sets", "reps", "weight",
                  "duration_minutes", "cardio_type", "rir", "weights", "notes",
                  "timestamp"):
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

    # Open-ended "whole history" phrasings — the natural way a user asks for the
    # LAST time / full history of something ("when did I last bench?", "my squat
    # history", "have I ever hit 315?", "all-time"). Before this these returned
    # None → a hard "Unrecognised period" error, so movement/food recall across
    # months silently failed and the model would either deflect or confabulate.
    # Map them to a wide trailing window (the DB keeps everything; nothing caps
    # the upper range — widen here if a user ever needs >1y).
    if (
        p in (
            "last time", "ever", "all time", "all-time", "alltime", "all the time",
            "history", "so far", "since the start", "since the beginning",
            "all of it", "any time", "anytime", "all",
        )
        or p.endswith(" history")     # "bench history", "my squat history"
    ):
        return (today - _td(days=365), today)
    # "this year" / "last year" → calendar-year windows.
    if p == "this year":
        return (_date(today.year, 1, 1), today)
    if p == "last year":
        return (_date(today.year - 1, 1, 1), _date(today.year - 1, 12, 31))
    # "last/past N <unit>" → a RANGE ending today (distinct from "N <unit> ago",
    # which is a single day). Covers "last 3 months", "past 2 weeks", "last 10 days".
    _unit_days = {"day": 1, "week": 7, "month": 30, "year": 365}
    m = re.match(r"^(?:last|past)\s+(\d+)\s*(day|week|month|year)s?$", p)
    if m:
        n = int(m.group(1))
        if n > 0:
            return (today - _td(days=n * _unit_days[m.group(2)]), today)
    m = re.match(
        r"^(?:last|past)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(day|week|month|year)s?$", p)
    if m:
        return (today - _td(days=_word_n[m.group(1)] * _unit_days[m.group(2)]), today)

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
    # Anchor to the user's LOGGING day (honors LOGGING_DAY_ROLLOVER_HOUR) — the same
    # day new entries are filed under, NOT the raw clock date. Using datetime.now()
    # made every relative period ('today', 'yesterday', weekday names) resolve to the
    # wrong calendar day between midnight and the rollover hour, so query_history
    # returned an empty result for a day that actually had data.
    today = _user_today(user_timezone)

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


async def delete_user_food_match(db: AsyncSession, user_id: int, name_norm: str) -> bool:
    """Drop a user's cached match for a normalized food name. Used when a
    correction proves the cached profile wrong (material macro change on a
    portion we can't derive per-100g from) — next log re-resolves fresh."""
    m = await get_user_food_match(db, user_id, name_norm)
    if m is None:
        return False
    await db.delete(m)
    await db.commit()
    return True


def _extract_micros_100(per100: dict) -> dict:
    """The per-100g micronutrient subset of a nutrient profile (vitamins/minerals/
    fat breakdown) — what we cache so repeat-logged foods keep their micros."""
    if not per100:
        return {}
    from api.usda import MICRO_KEYS
    return {k: per100[k] for k in MICRO_KEYS if per100.get(k) is not None}


async def upsert_user_food_match(db: AsyncSession, user_id: int, name_norm: str,
                                 display_name: str, fdc_id: str, per100: dict,
                                 confidence: str, user_confirmed: bool = False):
    """Store/refresh a user's recurring food match. Bumps usage on repeat."""
    micros = _extract_micros_100(per100)
    existing = await get_user_food_match(db, user_id, name_norm)
    if existing:
        existing.times_used = (existing.times_used or 1) + 1
        existing.last_used = datetime.utcnow()
        # Self-heal the cache: rows created before the micro panel existed have
        # micros_100_json=NULL. Backfill it the first time a richer profile flows
        # through (e.g. a USDA re-lookup), so the food keeps its micros thereafter.
        if micros and not existing.micros_100_json:
            existing.micros_100_json = json.dumps(micros)
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
        micros_100_json=(json.dumps(micros) if micros else None),
        confidence="user-confirmed" if user_confirmed else confidence,
        user_confirmed=user_confirmed,
    )
    db.add(m)
    await db.commit()
    return m
