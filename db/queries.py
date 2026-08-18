from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, delete, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry,
    ExerciseEntry, BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot,
    Feedback, UserFoodMatch, PendingQuestion, WearableDevice, WearableMetric,
    DeviceToken,
)
from enum import Enum
from datetime import date, datetime, timedelta
from typing import Optional, List
import json
import logging
import uuid
import os
import pytz
from core.units import LB_PER_KG
from core import clock

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


# Weigh-ins get a scoped PRE-DAWN GRACE even while the general logging day
# rolls at midnight: a 12:03am smart-scale sync is the END of yesterday, not
# a new morning's reading (Danny, 2026-07-19: evening manual + 12:03am sync
# marked TWO adherence days). Meals after midnight are deliberately "today"
# (see LOGGING_DAY_ROLLOVER_HOUR above) — measurements are not meals.
WEIGHIN_PREDAWN_GRACE_HOUR = 4


def _weighin_day_of(dt_utc: datetime, user_timezone: str) -> date:
    """The day a WEIGH-IN belongs to: user-local date, minus a day before
    the pre-dawn grace hour. Used by the weight upsert, the Apple Health
    backfill dedup, and every weigh-in serialization — one day rule."""
    from core.timezones import safe_timezone
    tz = safe_timezone(user_timezone)
    if dt_utc.tzinfo is None:
        dt_utc = pytz.utc.localize(dt_utc)
    local = dt_utc.astimezone(tz)
    d = local.date()
    if local.hour < WEIGHIN_PREDAWN_GRACE_HOUR:
        d = d - timedelta(days=1)
    return d


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


async def add_food_entry(db: AsyncSession, daily_log_id: int,
                         ledger_source: Optional[str] = None,
                         user_id: Optional[int] = None,
                         claim_id: Optional[int] = None,
                         commit: bool = True,
                         ledger_extra: Optional[dict] = None,
                         **kwargs) -> FoodEntry:
    """Write one food row, and — when the caller names a `ledger_source` — its
    `created` event, in ONE transaction.

    `ledger_extra` merges over the row-derived payload for facts the ROW does
    not hold. It exists so no caller has to write its own event afterwards to
    record them: that shape is the durability defect, not a style preference.
    Returns the entry with `entry.ledger_event_id` set when an event was
    written, so a caller needing the event as a token no longer has to.

    The row used to commit here and the event to commit in a second call by the
    caller. Between those two commits the process can die (a deploy restart, an
    OOM, a dropped connection) and what survives is a food row with no history:
    `ledger_undo` cannot invert it, so "undo that" reaches past it to a row the
    user never mentioned, and the turn↔operation join is missing the operation
    so the turn reads as a reply that claimed a log it never made. Both silent,
    and nothing in the schema says the event was owed.

    `ledger_source` mirrors `add_exercise_entry`, which already carries the
    caller's provenance label instead of letting the caller write a second
    event — the fix the master audit (2026-07-30) landed after finding every
    exercise creation recorded twice by two writers.

    Callers that do NOT pass `ledger_source` keep the old shape exactly: the
    row commits and history is the caller's business. That is what makes this
    safe to adopt one call site at a time.

    `claim_id` closes the crash-replay window in the idempotency contract. The
    claim used to be completed by a SEPARATE commit after this one returned, so
    a process that died in between left the claim `in_progress` while the food
    was already committed — and a retry took the stale claim over and wrote the
    meal a second time. That is the exact failure the claim exists to prevent,
    reached by the timing that matters most. Completing it HERE puts the claim,
    the row and the event in one transaction: after a crash the claim is either
    completed with its result, or the row was never written at all.

    `commit=False` hands the transaction back to the caller, which is what lets
    a MULTI-ITEM meal be one mutation. Committing per row is the reason a
    three-food turn can leave two foods on the board and lose the third: each
    row is its own transaction, so there is no state in which the meal as a
    whole either has or has not landed. The caller then owns the commit AND the
    briefing invalidation below — see the note there for why that one must not
    happen early. Mirrors the `commit=False` that `record_ledger_event` already
    takes, one layer down, for the same reason.
    """
    entry = FoodEntry(daily_log_id=daily_log_id, **kwargs)
    #: THE EVENT THIS WRITE PRODUCED, for callers that need it as a token.
    #: Transient, never a column. The chat lane hands this id to the card as
    #: its one-tap Undo token, and before `ledger_extra` existed that need was
    #: the entire reason the chat lane wrote its own event AFTER the row —
    #: which is the durability defect this parameter closes.
    entry.ledger_event_id = None
    db.add(entry)
    await db.flush()  # entry must be visible to the recompute query
    await recompute_log_totals(db, daily_log_id)
    if ledger_source is not None:
        # BEFORE the commit, deliberately. `commit=False` keeps the duplicate
        # guard's savepoint (a rejected duplicate still soft-fails to None)
        # while leaving the transaction open, so the row and its history land
        # together or not at all.
        if user_id is None:
            log = await db.get(DailyLog, daily_log_id)
            user_id = getattr(log, "user_id", None)
        if user_id is not None:
            # ONE BUILDER, WIDENED — never a second vocabulary. `_entry_event_payload`
            # stays the base because a `deleted` event restores from this payload,
            # and two builders would let undo rebuild a row the recorder never
            # described. `ledger_extra` carries what the ROW cannot: the chat
            # lane's `basis` and `resolution` are the resolution the row was
            # written FROM, and nothing on the entry records them.
            payload = _entry_event_payload(entry)
            for key, value in (ledger_extra or {}).items():
                if value is not None:
                    payload[key] = value
            event = await record_ledger_event(
                db, user_id=user_id, event_type="created", domain="food",
                entry_id=entry.id, daily_log_id=daily_log_id,
                payload=payload, source=ledger_source, commit=False)
            entry.ledger_event_id = getattr(event, "id", None)
    if claim_id is not None:
        # Same transaction as the row and the event. A crash now cannot leave a
        # committed meal behind an unfinished claim.
        from db.models import IdempotencyRecord
        rec = await db.get(IdempotencyRecord, claim_id)
        if rec is not None:
            rec.status = "completed"
            rec.result_entry_id = entry.id
            rec.result_daily_log_id = daily_log_id
            rec.completed_at = datetime.utcnow()
    if not commit:
        # NOT invalidating the briefing here is deliberate, not an omission.
        # The row is still invisible to every other connection, so dropping the
        # cache now lets a concurrent Coach open repopulate it from PRE-write
        # state — the stale-copy bug the invalidation exists to fix, with worse
        # timing, and it would survive a rollback that removed the row. The
        # caller invalidates after its commit.
        return entry
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


#: How long a training session may go quiet before the next set belongs to a
#: NEW workout. This is a claim about training, not about text: sets inside a
#: session are separated by rest, and rest is minutes — a two-hour silence is a
#: different workout even if the movement repeats. Deliberately generous, since
#: splitting one workout in two costs more than merging a quick double session.
WORKOUT_SESSION_GAP_MINUTES = 150


async def current_workout_group(db: AsyncSession, user_id: int,
                                gap_minutes: int = WORKOUT_SESSION_GAP_MINUTES
                                ) -> Optional[str]:
    """The session this user is CURRENTLY in, or None if they are not training.

    A live surface asks this to know what a rest timer is timing and which
    movement to show form cues for; the writer asks it so a set logged mid
    workout joins the session already underway instead of starting its own.
    """
    from db.models import ExerciseEntry
    row = (await db.execute(
        select(ExerciseEntry.workout_group_id, ExerciseEntry.timestamp)
        .join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id)
        .where(ExerciseEntry.workout_group_id.isnot(None))
        .order_by(ExerciseEntry.timestamp.desc())
        .limit(1))).first()
    if not row or not row[0] or not row[1]:
        return None
    quiet = (clock.now() - row[1]).total_seconds() / 60.0
    return row[0] if quiet <= gap_minutes else None


def new_workout_group_id() -> str:
    """An opaque session id. Mirrors `make_meal_group_id` — the value carries
    no meaning, only identity, so nothing downstream can be tempted to parse
    a workout out of it."""
    return f"wk_{uuid.uuid4().hex[:16]}"


async def get_workout_session(db: AsyncSession, user_id: int,
                              group_id: Optional[str] = None) -> dict:
    """One training session, shaped for a live surface.

    Returns `{group_id, started_at, last_set_at, seconds_since_last_set,
    exercises: [{name, sets:[...]}], total_sets}` — or an empty dict when the
    user is not mid-workout and no session was named.

    This is what a rest timer times and what a form cue points at: the timer
    needs the moment the last set landed, the cue needs the movement that just
    happened, and neither can be derived from a scatter of rows that do not
    know they belong together.
    """
    from db.models import ExerciseEntry
    gid = group_id or await current_workout_group(db, user_id)
    if not gid:
        return {}
    rows = (await db.execute(
        select(ExerciseEntry)
        .join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id)
        .where(ExerciseEntry.workout_group_id == gid)
        .order_by(ExerciseEntry.timestamp.asc()))).scalars().all()
    if not rows:
        return {}
    by_move: dict = {}
    for r in rows:
        # Grouped in ENCOUNTER order, so the view lists movements the way the
        # session actually went rather than alphabetically.
        by_move.setdefault((r.exercise_name or "").strip(), []).append({
            "entry_id": r.id, "reps": r.reps, "weight": r.weight,
            "rir": r.rir, "at": r.timestamp,
            "duration_minutes": r.duration_minutes})
    last = rows[-1].timestamp
    return {
        "group_id": gid,
        "started_at": rows[0].timestamp,
        "last_set_at": last,
        "seconds_since_last_set": (
            (clock.now() - last).total_seconds() if last else None),
        "exercises": [{"name": k, "sets": v} for k, v in by_move.items()],
        "total_sets": len(rows),
    }


async def add_exercise_entry(db: AsyncSession, daily_log_id: int,
                              is_cardio: bool = False,
                              ledger_source: Optional[str] = None,
                              claim_id: Optional[int] = None,
                              **kwargs) -> ExerciseEntry:
    # If caller signals cardio but didn't set cardio_type, mark it so the derived
    # flags (recompute_log_totals) classify this entry correctly.
    if is_cardio and not kwargs.get("cardio_type"):
        kwargs["cardio_type"] = "cardio"
    # THE SESSION THIS SET BELONGS TO. Supplied by a caller that already knows
    # (a live workout view holding its own session), otherwise joined to the
    # one underway, otherwise opened. Never guessed after the fact.
    _log = await db.get(DailyLog, daily_log_id)
    if not kwargs.get("workout_group_id") and _log is not None:
        try:
            kwargs["workout_group_id"] = (
                await current_workout_group(db, _log.user_id)
                or new_workout_group_id())
        except Exception as e:
            logger.debug(f"workout session id unavailable: {e}")

    entry = ExerciseEntry(daily_log_id=daily_log_id, **kwargs)
    db.add(entry)
    await db.flush()  # entry must be visible to the recompute query
    await recompute_log_totals(db, daily_log_id)
    # NO COMMIT HERE. The row, its `created` event and the idempotency claim
    # commit together below. Committing the row first left the same window food
    # had: a crash before the event produced a set with no history, and a crash
    # before the claim left a committed set behind an unfinished claim that a
    # retry would write a second time.
    # HISTORY, on the same contract food already rides — and THIS IS THE ONLY
    # WRITER of the exercise `created` event. The master audit (2026-07-30)
    # found every exercise creation recorded twice, 0s apart: once here under
    # domain="fitness", once by the caller under domain="exercise". Two
    # writers, two vocabularies — and `ledger_undo._invert` handles only
    # "exercise", so this event was UNINVERTIBLE on its own; the caller's
    # duplicate had been masking that. One writer (this one, the chokepoint
    # every path already passes through), one domain (the one undo and the
    # update/delete events already speak), and the caller's provenance label
    # arrives as `ledger_source` instead of a second event.
    if _log is not None:
        try:
            await record_ledger_event(
                db, _log.user_id, "created", domain="exercise",
                entry_id=entry.id, daily_log_id=daily_log_id,
                source=(ledger_source or kwargs.get("source_type")
                        or "fitness"),
                payload={"exercise_name": entry.exercise_name,
                         "sets": entry.sets, "reps": entry.reps,
                         "weight_kg": entry.weight,
                         "duration_minutes": entry.duration_minutes,
                         "is_cardio": bool(entry.cardio_type),
                         "workout_group_id": entry.workout_group_id},
                commit=False)
        except Exception as e:
            logger.debug(f"exercise ledger event not recorded: {e}")
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry.id, daily_log_id)
    # ONE commit for the row, its event and the claim. They used to be three,
    # and a crash between them left an exercise with no history, or a committed
    # set behind an unfinished claim that a retry would write again.
    await db.commit()
    await db.refresh(entry)
    try:
        if _log: _invalidate_briefing_for_log(_log.user_id, by_user=True)
    except Exception:
        pass
    return entry


async def _complete_claim_in_txn(db, claim_id, entry_id, daily_log_id) -> None:
    """Mark an idempotency claim completed WITHOUT committing.

    The caller owns the transaction, so the claim lands with the row it
    describes. Completing it in a later commit left a window where the write
    was durable and the claim was not, and a retry took the stale claim over
    and executed the command a second time.
    """
    from db.models import IdempotencyRecord
    rec = await db.get(IdempotencyRecord, claim_id)
    if rec is not None:
        rec.status = "completed"
        rec.result_entry_id = entry_id
        rec.result_daily_log_id = daily_log_id
        rec.completed_at = datetime.utcnow()


async def add_body_metric(db: AsyncSession, user_id: int,
                          weight_kg: float, source: str = "manual",
                          when: Optional[datetime] = None,
                          ledger_source: Optional[str] = None,
                          claim_id: Optional[int] = None,
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
    target_day = _weighin_day_of(ts, tz)

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
         and _weighin_day_of(r.timestamp, tz) == target_day),
        None,
    )

    # Does a MANUAL reading already exist for the target day? (Across either
    # branch.) An apple_health write must not touch current_weight_kg when one
    # does — the user's deliberate weigh-in stays the headline.
    manual_day_exists = any(
        (r.source or "manual") == "manual"
        and r.timestamp is not None
        and _weighin_day_of(r.timestamp, tz) == target_day
        for r in rows
    )

    # A backfilled PAST weigh-in writes that day's row + feeds the trend, but is
    # NOT the user's CURRENT weight — only a today/live reading moves the
    # headline. BOTH sides use the weigh-in clock (pre-dawn grace): comparing
    # a graced target_day against ungraced _user_today made every LIVE
    # midnight-to-4am weigh-in read as a past backfill and skip the headline.
    is_current_day = target_day >= _weighin_day_of(datetime.utcnow(), tz)

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
        _prior_weight = existing.weight_kg
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
        if ledger_source is not None:
            # An UPSERT is a correction, and undo needs what it replaced —
            # `previous_weight_kg` is the whole reason this is an event and not
            # just a mutated row. Same transaction as the write, so weight gets
            # the audit contract food and exercise already have.
            await record_ledger_event(
                db, user_id=user_id, event_type="updated", domain="weight",
                entry_id=existing.id,
                payload={"weight_kg": weight_kg,
                         "previous_weight_kg": _prior_weight,
                         "source": source,
                         "context": kwargs.get("context")},
                source=ledger_source, commit=False)
        if claim_id is not None:
            await _complete_claim_in_txn(db, claim_id, existing.id, None)
        await db.commit()
        await db.refresh(existing)
        _invalidate_briefing_for_log(user_id, by_user=True)
        return existing

    metric = BodyMetric(user_id=user_id, weight_kg=weight_kg, source=source,
                        timestamp=ts, **kwargs)
    db.add(metric)
    _sync_current_weight()
    if ledger_source is not None or claim_id is not None:
        await db.flush()          # the event needs the metric's id
    if ledger_source is not None:
        await record_ledger_event(
            db, user_id=user_id, event_type="created", domain="weight",
            entry_id=metric.id,
            payload={"weight_kg": weight_kg, "source": source,
                     "context": kwargs.get("context")},
            source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, metric.id, None)

    await db.commit()
    await db.refresh(metric)
    _invalidate_briefing_for_log(user_id, by_user=True)
    return metric


async def add_water_entry(db: AsyncSession, user_id: int, daily_log_id: int,
                          amount_ml: float, context: Optional[str] = None,
                          source_type: str = "text",
                          ledger_source: Optional[str] = None,
                          claim_id: Optional[int] = None):
    """T2.4 — Persist a timestamped water log. DailyLog.total_water_ml stays
    as the cached aggregate (updated by the caller alongside) for backward
    compat with existing dashboards; the WaterEntry row is the canonical
    source for hydration timing coaching and future per-event analytics.

    `ledger_source` / `claim_id` mirror `add_food_entry` exactly — see its
    docstring for why both belong in the row's OWN transaction. Water had
    THREE writers and each handled history differently: the dashboard
    (`api/app.py`) and the chat lane (`handlers/tool_executor.py`) each wrote
    the `created` event in a second commit, and `api/water.py` — the iOS tap
    surface — wrote no event at all, so a tap-logged pour was invisible to
    `ledger_undo` and to the turn↔operation join. Passing `ledger_source`
    makes this function the one writer.

    Callers that do NOT pass `ledger_source` keep the old shape exactly, so
    the two existing second-commit call sites stay correct until they move.
    """
    from db.models import WaterEntry
    entry = WaterEntry(
        user_id=user_id,
        daily_log_id=daily_log_id,
        amount_ml=amount_ml,
        context=context,
        source_type=source_type,
    )
    db.add(entry)
    if ledger_source is not None:
        # BEFORE the commit. `commit=False` folds the event into this
        # transaction, so the pour and its history land together or not at
        # all — a crash between two commits used to leave a WaterEntry that
        # `ledger_undo` could not invert.
        await db.flush()   # the event needs the row's id
        await record_ledger_event(
            db, user_id=user_id, event_type="created", domain="water",
            entry_id=entry.id, daily_log_id=daily_log_id,
            # The shape `core.ledger_undo._invert` reads for domain="water".
            payload={"amount_ml": amount_ml, "context": context},
            source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry.id, daily_log_id)
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
                             amount_ml: float,
                             ledger_source: Optional[str] = None,
                             claim_id: Optional[int] = None):
    """Update a single WaterEntry's amount, then resync the day total.

    Scoped by user_id so a token can only touch its own rows. Returns the
    refreshed entry, or None if not found / not owned.

    With `ledger_source`, the `updated` event carries the BEFORE state in the
    same transaction as the edit — the shape food and exercise already use, so
    a correction stays reversible rather than overwriting the only record of
    what the amount used to be.
    """
    from db.models import WaterEntry
    entry = await db.get(WaterEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        return None
    before = {"amount_ml": entry.amount_ml, "context": entry.context}
    entry.amount_ml = amount_ml
    if ledger_source is not None:
        await record_ledger_event(
            db, user_id=user_id, event_type="updated", domain="water",
            entry_id=entry.id, daily_log_id=entry.daily_log_id,
            payload={"amount_ml": amount_ml, "before": before},
            source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry.id, entry.daily_log_id)
    await db.commit()
    if entry.daily_log_id:
        await recompute_water_total(db, entry.daily_log_id)
    await db.refresh(entry)
    return entry


async def delete_water_entry(db: AsyncSession, entry_id: int, user_id: int,
                             ledger_source: Optional[str] = None,
                             claim_id: Optional[int] = None) -> bool:
    """Delete a single WaterEntry, then resync the day total.

    Scoped by user_id. Returns True if a row was removed.

    With `ledger_source`, the `deleted` event is captured from the row BEFORE
    it goes and committed in the same transaction as the delete — the same
    payload shape `api/app.py` already records, so a pour deleted from any
    surface leaves one restorable history entry rather than none.
    """
    from db.models import WaterEntry
    entry = await db.get(WaterEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        return False
    daily_log_id = entry.daily_log_id
    # Read the state off the row while it still exists — after the delete
    # there is nothing left to describe, and a `deleted` event with no payload
    # cannot be restored from.
    before = {"amount_ml": entry.amount_ml, "context": entry.context,
              "daily_log_id": daily_log_id}
    await db.delete(entry)
    if ledger_source is not None:
        # Flushed so the row is gone before the event references it; the
        # event still names `entry_id` because that is the token undo and the
        # turn↔operation join look the row up by.
        await db.flush()
        await record_ledger_event(
            db, user_id=user_id, event_type="deleted", domain="water",
            entry_id=entry_id, daily_log_id=daily_log_id, payload=before,
            source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry_id, daily_log_id)
    await db.commit()
    if daily_log_id:
        await recompute_water_total(db, daily_log_id)
    return True


async def get_recent_weights(db: AsyncSession, user_id: int,
                             days: int = 14) -> List[BodyMetric]:
    since = clock.now() - timedelta(days=days)
    result = await db.execute(
        select(BodyMetric)
        .where(and_(BodyMetric.user_id == user_id, BodyMetric.timestamp >= since))
        .order_by(desc(BodyMetric.timestamp))
    )
    return result.scalars().all()


async def get_recent_logs(db: AsyncSession, user_id: int,
                          days: int = 7) -> List[DailyLog]:
    # THE UPPER BOUND IS THE USER'S DAY, NOT THE SERVER'S.
    #
    # This was `date.today()` — the SERVER's calendar date — while every
    # DailyLog is dated by `_user_today(tz)`, the user's own logging day. Those
    # are not the same date, and whenever the user's day is ahead the query
    # excluded THE LOG THEY ARE CURRENTLY WRITING INTO.
    #
    # Timezones run UTC-12..UTC+14, so a user's local date is at most one
    # calendar day ahead of a UTC server's: everyone from Europe eastward
    # crosses midnight before the server does, and for those hours their live
    # log vanished from every consumer of this function. The streak read 0 with
    # a meal already logged (`test_widget_endpoint`, reproduced 2026-07-31
    # 00:26 UTC), and the same hole reaches history, trends and the dashboard's
    # available_dates.
    #
    # The guard itself stays — its job is the LLM date bug that wrote logs days
    # and months into the future, and one day of slack does not reopen that.
    # `since` already carried a 1-day buffer for the mirror-image case; this is
    # the other half of the same edge, which only ever got half a fix.
    since = date.today() - timedelta(days=days + 1)
    today = date.today() + timedelta(days=1)
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


async def get_recent_log_days(db: AsyncSession, user_id: int,
                              days: int = 90) -> List[DailyLog]:
    """`get_recent_logs` without the child rows — for callers that only read
    columns off the DailyLog itself.

    The streak walk is the motivating case: it reads `date`, `total_calories`
    and `workout_completed` off the PARENT rows, but went through
    `get_recent_logs`, whose `selectinload` pulls every food and exercise entry
    in the window. At the 90 days the streak engine asks for, that materialised
    a quarter of a user's entries on every badge check to read three columns.

    Same window arithmetic and the same future-date exclusion, so the two
    return identical DailyLog sets — this one just doesn't drag the children
    along.
    """
    since = date.today() - timedelta(days=days + 1)
    today = date.today()
    result = await db.execute(
        select(DailyLog)
        .where(and_(
            DailyLog.user_id == user_id,
            DailyLog.date >= since,
            DailyLog.date <= today,
        ))
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


#: Computed once per process: the build identity cannot change without a
#: restart, and stamping must never cost the turn anything.
_BUILD_STAMP_CACHE = None


def _build_stamp() -> dict:
    """What is running: the deployed SHA and the flags that shape a turn.

    Render injects RENDER_GIT_COMMIT at deploy; locally it is absent and the
    stamp says so honestly rather than guessing from git state — a dev
    checkout's HEAD is not a deployment. The flag list is the small set whose
    value changes routing/behaviour attribution in audits; each is recorded as
    the RAW env value so "unset" and "false" stay distinguishable.
    """
    global _BUILD_STAMP_CACHE
    if _BUILD_STAMP_CACHE is None:
        _BUILD_STAMP_CACHE = {
            "sha": (os.getenv("RENDER_GIT_COMMIT") or "local")[:12],
            "flags": {name: os.getenv(name) for name in (
                "STRUCTURED_FOOD", "FOOD_GATE_MODEL", "FOOD_GATE_OPEN",
                "FOOD_COMPOSER", "FOOD_FAST_PATH", "FOOD_FAST_PATH_SHADOW",
                "FOOD_ANSWER_APPLY", "NUTRITION_RESOLVER_MODE",
                "TURN_COORDINATOR_MODE", "TURN_OBLIGATIONS")},
        }
    return _BUILD_STAMP_CACHE


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
                           idempotency_key: str | None = None,
                           reasoning: Optional[dict] = None,
                           turn_id: str | None = None):
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
    # The canonical turn identity — same value the ledger contextvar stamps on
    # this turn's operations, making turn⋈operation one indexed join.
    if turn_id:
        entry.turn_id = turn_id
    # The turn's reasoning receipt, and THE TURN NAMING THE BUILD THAT MADE IT.
    #
    # Two things live here. The receipt is the "Arnie's Thoughts" disclosure,
    # which without this vanishes on every history reload. The build stamp is
    # why three audits in a row spent their first hour inferring the deployed
    # SHA from behavioural markers ("does this pending carry log_date?") —
    # deploys are manual and nothing recorded them. `/health` says what runs
    # NOW; only the turn can say what ran WHEN, which is what makes a
    # mixed-deployment window one query and lets a closure claim name the SHA
    # it was verified against.
    #
    # STAMPED WHETHER OR NOT THE CALLER HAS A RECEIPT (I1). This was gated on
    # `if reasoning:`, so a caller with nothing to add wrote NULL — the comment
    # claimed "the single write site", which was true of the site and false of
    # the behaviour. Measured over 7 days: 130 turns carried no reasoning_json
    # at all, and they were not scattered — they were three whole surfaces,
    # each 100% blank (`proactive` 79, `dashboard_edit` 35, `text` 16). No
    # build, no flags, invisible to every audit query in this repository; the
    # 79 proactive sends could not be checked for delivery even in principle
    # (audits/D2_DEFECTS_2026-07-30.md).
    #
    # Deliberately only the BUILD is added. A turn that made no routing
    # decision must not be given a route here — inventing one would poison the
    # exact analytics D5 exists to repair. An empty receipt that names its
    # build is honest; a fabricated one is not.
    #
    # `dict(reasoning or {})` so a caller's dict is never mutated, and a caller
    # without one still lands a row that names its build.
    entry.reasoning_json = json.dumps({**dict(reasoning or {}),
                                       "build": _build_stamp()})
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

    EVERY REMOVED ROW GETS ITS `deleted` EVENT, in this transaction.

    MEASURED IN PRODUCTION 2026-08-07 14:59:07: "Clear my day" removed fourteen
    rows — four of them `canonical:create` — and wrote nothing. Undo was
    impossible and the canonical lane's own commits vanished with no trace of
    what they had been. The instrument was not the problem: 123 food `deleted`
    events exist and `delete_food_entry` ran sixteen times the same week, so
    the ledger can record this. The bulk `delete()` below simply never told it.

    THE PAYLOAD IS READ WHILE THE ROWS STILL EXIST, for the reason
    `delete_food_entry` gives: `ledger_undo._restore_plan` rebuilds an entry
    from the payload alone, so an event without it is a delete that cannot be
    taken back. `daily_log_id` rides IN the payload — without it a food cleared
    from Tuesday returns on whatever day the restore happens to run.
    """
    log = await get_today_log(db, user_id, user_timezone)
    if not log:
        return False

    # Read before deleting. A bulk `delete()` returns a rowcount, not the rows,
    # and the rows are the only place their own history exists.
    doomed = []
    for model, domain in ((FoodEntry, "food"), (ExerciseEntry, "exercise")):
        rows = (await db.execute(
            select(model).where(model.daily_log_id == log.id))).scalars().all()
        doomed += [(row.id, domain,
                    {**_entry_event_payload(row), "daily_log_id": log.id})
                   for row in rows]

    await db.execute(delete(FoodEntry).where(FoodEntry.daily_log_id == log.id))
    await db.execute(delete(ExerciseEntry).where(ExerciseEntry.daily_log_id == log.id))

    # ONE TRANSACTION, so a process dying mid-clear cannot leave rows gone and
    # their history unwritten — `commit=False` on every event, one commit below.
    for entry_id, domain, payload in doomed:
        await record_ledger_event(
            db, user_id=user_id, event_type="deleted", domain=domain,
            entry_id=entry_id, daily_log_id=log.id, payload=payload,
            source="clear_day_log", commit=False)

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


async def get_users_with_oura(db: AsyncSession) -> List[User]:
    """All users who have connected Oura (have a non-empty refresh token)."""
    result = await db.execute(
        select(User)
        .where(
            User.oura_refresh_token.is_not(None),
            User.oura_refresh_token != "",
        )
        .options(selectinload(User.preferences))
    )
    return result.scalars().all()


async def set_oura_tokens(
    db: AsyncSession,
    user_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.oura_access_token = access_token
    user.oura_refresh_token = refresh_token
    user.oura_token_expires_at = expires_at
    await db.commit()


async def clear_oura_tokens(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.oura_access_token = None
    user.oura_refresh_token = None
    user.oura_token_expires_at = None
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
        user.goal_weight_kg = round(profile["goal_weight_lbs"] / LB_PER_KG, 2)
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
    try:
        # SAVEPOINT — same reasoning as record_ledger_event: a session-level
        # rollback expires every loaded object and poisons the turn.
        async with db.begin_nested():
            db.add(pq)
            await db.flush()
    except IntegrityError:
        # uq_pending_open_per_user_kind (pendinguniq001): a concurrent turn
        # opened the same kind between our get and this insert. The loser of
        # the race adopts the winner's row — which is exactly what the
        # update-in-place branch above would have done had the row existed a
        # moment earlier.
        existing = await get_open_pending_question(db, user_id, kind)
        if existing is not None:
            existing.question = question
            existing.tier = tier
            existing.hook_style = hook_style
            await db.commit()
            await db.refresh(existing)
            return existing
        raise
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

#: Ledger sources that mean "the canonical lane wrote this row". A row created
#: by one of these is OWNED by the canonical lane.
CANONICAL_SOURCES = ("canonical:",)


class MutationAuthority(str, Enum):
    """⭐ WHAT AUTHORITY A WRITER IS EXERCISING — declared, never inferred.

    THE FIRST TWO VERSIONS OF THIS WERE BOTH WRONG, and the second failure is
    the more instructive one.

    v1 said "only the canonical lane may mutate a canonical row". The suite
    refused it in under a minute: `ios_edit` is a user opening the editor on
    their own row and has every right to.

    v2 replaced that with a DENYLIST of writer-name prefixes
    (`structured_food:*`, `legacy`). It produced the right answer for the four
    callers that exist today, and reintroduced — in miniature — the exact
    shape this migration has spent months deleting. A future inferred writer
    named `coach_agent:v3` would mutate canonical rows because nobody
    remembered to extend a tuple. Worse, `mutation_rejected` could not save
    us: an undenied writer is never rejected, so no event would exist to say
    it escaped. A permission system whose failure mode is SILENCE is the
    failure mode of this entire project.

    So the capability is carried by the CALL, not derived from the caller's
    name. `ios_edit` is not trusted because its string starts with `ios_`; it
    is trusted because the mutation declares that a user pointed at a row.
    `ledger_undo` is not trusted because it is on a list; it is trusted
    because it declares that it is replaying a recorded inverse.

    UNKNOWN IS THE DEFAULT, AND IT IS REFUSED on canonical rows. A new
    mutation surface — `apple_watch_edit`, `voice_edit` — therefore BREAKS
    until it declares what authority it exercises. That is the point: making a
    surface state its authority is cheap, and silent permission is what
    destroyed six canonical rows in production.
    """
    #: The canonical lane mutating what it owns.
    CANONICAL_OWNER = "canonical_owner"
    #: A human pointed at this row and changed it. The user is the authority.
    EXPLICIT_USER_ACTION = "explicit_user_action"
    #: Replaying an inverse that was WRITTEN DOWN. Not a guess — undo.
    RECORDED_REPLAY = "recorded_replay"
    #: A model DECIDED that prose referred to this row. On 2026-08-10 it
    #: decided wrong and overwrote a canonical chicken row with salmon.
    INFERRED_INTERPRETATION = "inferred_interpretation"
    #: Nothing was declared. Refused on canonical rows, deliberately.
    UNKNOWN = "unknown"


#: WHO MAY MUTATE A CANONICALLY OWNED ROW. Everything absent is refused,
#: including UNKNOWN — the list is what may proceed, not what may not.
AUTHORITY_OVER_CANONICAL = frozenset({
    MutationAuthority.CANONICAL_OWNER,
    MutationAuthority.EXPLICIT_USER_ACTION,
    MutationAuthority.RECORDED_REPLAY,
})


class CrossOwnerMutation(Exception):
    """A writer without authority tried to mutate a canonically-owned row.

    ⭐ MEASURED IN PRODUCTION 2026-08-10, and it was silent data loss:

        13:56:31  created  entry=2947  canonical:create        Chicken, roasted 200
        13:56:43  updated  entry=2947  structured_food:…v2  -> Salmon 263

    The user said "I had some salmon" — a plain new-food statement with no
    correction language — twelve seconds after logging chicken. The legacy
    interpreter classified it as a CORRECTION and overwrote the canonical row
    in place. The reply was "Updated to salmon." The chicken log survived only
    in its `created` event.

    Raised rather than returned, and deliberately: `update_food_entry` already
    returns None for "no such entry" and "not your entry", and a refusal that
    looks like those two would be handled by callers as a lookup miss. This is
    not a miss — it is a writer being told it does not own what it is holding.
    """

    def __init__(self, entry_id: int, owner: str, authority: str,
                 writer: str = ""):
        self.entry_id, self.owner = entry_id, owner
        self.authority, self.writer = authority, writer
        super().__init__(
            f"entry {entry_id} is owned by {owner!r}; a mutation with "
            f"authority {authority!r} (writer {writer!r}) may not change it")


def _is_canonical(source: Optional[str]) -> bool:
    return bool(source) and str(source).startswith(CANONICAL_SOURCES)


async def creating_source(db: AsyncSession, entry_id: int) -> Optional[str]:
    """WHO CREATED THIS ROW, from its own `created` event.

    Ownership needs no new column: every row's provenance was already recorded
    by the 2026-08-07 ledger work, and invariant I3 guarantees exactly one
    `created` event per entry. The firewall reads evidence that already exists.
    """
    from db.models import LedgerEvent

    row = (await db.execute(
        select(LedgerEvent.source)
        .where(LedgerEvent.entry_id == entry_id,
               LedgerEvent.domain == "food",
               LedgerEvent.event_type == "created")
        .limit(1))).first()
    return row[0] if row else None


async def update_food_entry(
    db: AsyncSession, entry_id: int, user_id: int,
    ledger_source: Optional[str] = None, claim_id: Optional[int] = None,
    authority: "MutationAuthority" = MutationAuthority.UNKNOWN,
    **changes
) -> Optional[FoodEntry]:
    """
    Update a food entry and adjust the daily log totals by the delta.
    Returns None if entry doesn't exist or doesn't belong to user_id.

    With `ledger_source`, the `updated` event and the caller's idempotency
    claim commit in THIS transaction — see `add_food_entry` for the crash
    window that closes. The edit surfaces wrote the event in a second commit,
    so a process dying in between left a rescaled entry whose original macros
    existed nowhere.
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

    # ⭐ THE OWNERSHIP FIREWALL, AT THE MUTATION BOUNDARY.
    #
    # Placed here rather than in the correction classifier on purpose: every
    # food-row update in the system funnels through this function, so a guard
    # here rejects a cross-owner write no matter which interpretation path
    # reached it. A special case in the classifier would only cover the one
    # route that was observed failing.
    #
    # THE ATTEMPT IS RECORDED, not just refused. A firewall that silently
    # drops writes is its own blind spot — the rejected event is how anyone
    # discovers that a legacy path is still trying, and how often.
    _owner = await creating_source(db, entry_id)
    if _owner is None:
        # PRE-LEDGER ROWS FAIL OPEN, and are COUNTED. Ownership cannot be
        # established without creation provenance, and refusing every such row
        # would break corrections across the entire historical corpus. Emitted
        # so the size of that corpus is measurable and the exception can
        # eventually be removed on evidence rather than on nerve.
        logger.info("event=ownership_check result=unknown_provenance entry=%s "
                    "authority=%s", entry_id, getattr(authority, "value",
                                                      authority))
    elif _is_canonical(_owner) and authority not in AUTHORITY_OVER_CANONICAL:
        try:
            await record_ledger_event(
                db, user_id=user_id, event_type="mutation_rejected",
                domain="food", entry_id=entry_id,
                daily_log_id=entry.daily_log_id,
                payload={"owner": _owner, "writer": ledger_source or "",
                         "authority": getattr(authority, "value", str(authority)),
                         "attempted": {k: v for k, v in changes.items()
                                       if v is not None}},
                source=ledger_source or "unknown", commit=False)
        except Exception:
            logger.warning("could not record rejected mutation on entry %s",
                           entry_id, exc_info=True)
        logger.error(
            "event=cross_owner_mutation_refused entry=%s owner=%s "
            "authority=%s writer=%s", entry_id, _owner,
            getattr(authority, "value", authority), ledger_source)
        raise CrossOwnerMutation(
            entry_id, _owner, getattr(authority, "value", str(authority)),
            ledger_source or "unknown")

    # Captured before any setattr below. A portion edit rescales fiber, sugar,
    # sodium and the micro panel too, so "what it was" is more than the four
    # macros the client sent.
    before_state = _entry_event_payload(entry) if ledger_source is not None else None

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

    # Non-nutrition fields (meal_type: "that turkey was my lunch" re-slots the
    # entry so the Log timeline regroups it under the right meal heading)
    for field in ("parsed_food_name", "quantity", "meal_type"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])

    # ⭐ B-1.8b — THE CANONICAL OWNER MAY REWRITE THE PANEL AND THE RECEIPT.
    # A repair supplies EXACT rescaled fiber/sugar/sodium/micros (the calorie-
    # ratio rescale above becomes a no-op because the numbers already agree),
    # and moves the P17f receipt's factor and resolved mass with the
    # correction. Gated on authority: a legacy caller cannot reach these
    # columns through this function, so the receipt stays the owner's record.
    if authority == MutationAuthority.CANONICAL_OWNER:
        for field in ("fiber", "sugar", "sodium", "micronutrients_json",
                      "scaling_factor", "resolved_grams"):
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
    if ledger_source is not None:
        await record_ledger_event(
            db, user_id=user_id, event_type="updated", domain="food",
            entry_id=entry.id, daily_log_id=entry.daily_log_id,
            # `before` is the key `core.ledger_undo._invert` reads to roll a
            # food edit back.
            payload={"changes": {k: v for k, v in changes.items()
                                 if v is not None},
                     "before": before_state},
            source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry.id, entry.daily_log_id)
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_food_entry(db: AsyncSession, entry_id: int, user_id: int,
                            ledger_source: Optional[str] = None,
                            claim_id: Optional[int] = None) -> bool:
    """Delete a food row, and — with `ledger_source` — its `deleted` event and
    the caller's claim, in ONE transaction. The payload is read off the row
    while it exists: `ledger_undo._restore_plan` rebuilds the entry from it,
    so a `deleted` event without it is a delete that cannot be taken back."""
    result = await db.execute(select(FoodEntry).where(FoodEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return False
    log_result = await db.execute(select(DailyLog).where(DailyLog.id == entry.daily_log_id))
    log = log_result.scalar_one()
    if log.user_id != user_id:
        return False

    daily_log_id = entry.daily_log_id
    # `daily_log_id` rides in the PAYLOAD, not just the event column: restore
    # rebuilds the row from the payload alone, and without it a food deleted
    # from Tuesday comes back on whatever day the restore happens to run.
    before_state = ({**_entry_event_payload(entry), "daily_log_id": daily_log_id}
                    if ledger_source is not None else None)
    await db.delete(entry)
    await db.flush()
    # Totals are derived from entries — recompute so they can never drift.
    await recompute_log_totals(db, daily_log_id)
    if ledger_source is not None:
        await record_ledger_event(
            db, user_id=user_id, event_type="deleted", domain="food",
            entry_id=entry_id, daily_log_id=daily_log_id,
            payload=before_state, source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry_id, daily_log_id)
    await db.commit()
    return True


async def update_exercise_entry(
    db: AsyncSession, entry_id: int, user_id: int,
    ledger_source: Optional[str] = None, claim_id: Optional[int] = None,
    **changes
) -> Optional[ExerciseEntry]:
    """Edit one exercise row, and — with `ledger_source` — its `updated` event
    and the caller's idempotency claim, in ONE transaction.

    Mirrors `add_food_entry`; see its docstring for the crash window this
    closes. The edit surfaces recorded their event in a SECOND commit after
    this one returned, so a process that died in between left a changed row
    whose previous values existed nowhere — an edit that cannot be rolled back
    and does not appear in the audit trail.
    """
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

    # Captured before the setattr loop — after it there is no record of what
    # the row used to be, which is exactly what an `updated` event is for.
    before_state = {
        "exercise_name": entry.exercise_name, "sets": entry.sets,
        "reps": entry.reps, "weight": entry.weight,
        "duration_minutes": entry.duration_minutes,
        "cardio_type": entry.cardio_type, "rir": entry.rir,
    } if ledger_source is not None else None

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
    if ledger_source is not None:
        await record_ledger_event(
            db, user_id=user_id, event_type="updated", domain="exercise",
            entry_id=entry.id, daily_log_id=entry.daily_log_id,
            # `before` is the key `core.ledger_undo._invert` reads to roll an
            # exercise edit back.
            payload={"changes": {k: v for k, v in changes.items()
                                 if v is not None},
                     "before": before_state},
            source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry.id, entry.daily_log_id)
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_exercise_entry(db: AsyncSession, entry_id: int, user_id: int,
                                ledger_source: Optional[str] = None,
                                claim_id: Optional[int] = None) -> bool:
    """Delete one exercise row, and — with `ledger_source` — its `deleted`
    event and the caller's claim, in ONE transaction. The event's payload is
    read off the row while it still exists, so a delete stays restorable."""
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
    # Read while the row exists. A `deleted` event with no payload names
    # something that can no longer be described, so it cannot be restored.
    # `daily_log_id` is part of it for the same reason as food: restore reads
    # the payload, and without it the set returns on the wrong day.
    before_state = ({**_entry_event_payload(entry), "daily_log_id": daily_log_id}
                    if ledger_source is not None else None)
    # Auto-imported rows (apple_health replace-on-sync, whoop ref-upsert) would
    # resurrect on the next sync — tombstone the ref so a delete is FINAL.
    if entry.source_ref:
        from db.models import HealthImportTombstone
        exists = (await db.execute(
            select(HealthImportTombstone).where(
                HealthImportTombstone.user_id == user_id,
                HealthImportTombstone.source_ref == entry.source_ref,
            ))).scalar_one_or_none()
        if exists is None:
            db.add(HealthImportTombstone(user_id=user_id,
                                         source_ref=entry.source_ref))
    await db.delete(entry)
    await db.flush()
    # Re-derive flags from whatever remains (single source of truth).
    await recompute_log_totals(db, daily_log_id)
    if ledger_source is not None:
        await record_ledger_event(
            db, user_id=user_id, event_type="deleted", domain="exercise",
            entry_id=entry_id, daily_log_id=daily_log_id,
            payload=before_state, source=ledger_source, commit=False)
    if claim_id is not None:
        await _complete_claim_in_txn(db, claim_id, entry_id, daily_log_id)
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
                    w_lbs = round(e.weight * LB_PER_KG, 1) if e.weight else None
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
                w_lbs = round(e.weight * LB_PER_KG, 1) if e.weight else None
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
                    "weight_lbs": (round(e.weight * LB_PER_KG, 1) if e.weight else None),
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

async def address_has_one_authority(db: AsyncSession, name_norm: str) -> bool:
    """Can this normalized address establish a SINGLE source authority?

    ⛔⛔ AMBIGUOUS HISTORICAL MEMORY IS NEVER AUTHORITATIVE, REGARDLESS OF WHICH
    SETTLEMENT OWNER READS IT *(Danny, 2026-08-16)*. `user_food_matches` records
    no canonical identity — a row is keyed by a lossy surface normalization, so
    it is evidence about a STRING. Measured fleet-wide: 28 addresses are bound
    to more than one set of per-100g numbers.

    ⭐ IT LIVES HERE, BESIDE THE ROWS, BECAUSE BOTH LANES MUST OBEY IT. The
    canonical rung already abstained on `cucumber` (10 vs 179 kcal/100g) — and
    then LEGACY priced the same meal from the same corrupt address at 179 x 1.5
    = 268 kcal for 150 g. Declining to a known-unsafe owner reproduced the exact
    error canonical had just prevented, and legacy still writes ~52% of meals.
    A guard on one lane is a guard with a longer fuse — the same argument
    `get_user_food_match` makes below for the letterless-key rule.
    
    ⚠ AGREEMENT, NOT PLAUSIBILITY. Bindings asserting the SAME numbers are one
    authority re-cached; different numbers are competing ones. Exact agreement,
    no tolerance — a threshold is where nutrition judgement gets smuggled in.
    This reads no food name, no user, and no calorie range.
    """
    from db.models import UserFoodMatch

    rows = (await db.execute(
        select(UserFoodMatch.cal_100, UserFoodMatch.protein_100,
               UserFoodMatch.carbs_100, UserFoodMatch.fat_100)
        .where(UserFoodMatch.name_norm == name_norm,
               UserFoodMatch.cal_100.isnot(None)))).all()
    return len({tuple(r) for r in rows}) <= 1


async def get_user_food_match(db: AsyncSession, user_id: int, name_norm: str):
    """Fetch a user's stored match for a normalized food name, if any.

    ⛔ A KEY WITH NO LETTERS ADDRESSES NOTHING. Enforced HERE rather than at
    each call site because the same key reaches durable memory from the legacy
    pricer, the canonical `assemble()`, the cache writer and the cache
    invalidator — four doors, and a guard on three of them is a defect with a
    longer fuse. `memory_key_is_addressable` carries the production evidence.
    """
    from core.food_intelligence import memory_key_is_addressable

    if not memory_key_is_addressable(name_norm):
        logger.info(
            "event=memory_key_refused user=%s key=%r reason=no_semantic_content "
            "— a normalized key that kept no letters cannot identify a food, "
            "and addressing memory with one returns whichever food shares its "
            "digits", user_id, name_norm)
        return None
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


#: The coarse `confidence` string is the only origin signal legacy rows carry.
#: Deliberately pessimistic — "exact" is the one value implying a branded or
#: label match, and anything unrecognised reads as generic rather than
#: inheriting user authority by default.
_ORIGIN_BY_CONFIDENCE = {
    "user-confirmed": "user_regular",
    "exact": "branded_exact",
    "likely": "generic_exact",
    "estimated": "estimated",
}


async def upsert_user_food_match(db: AsyncSession, user_id: int, name_norm: str,
                                 display_name: str, fdc_id: str, per100: dict,
                                 confidence: str, user_confirmed: bool = False,
                                 origin_tier: str = "", serving_text: str = ""):
    """Store/refresh a user's recurring food match. Bumps usage on repeat.

    `origin_tier` is the authority that produced these numbers. It exists so a
    reader can tell a cache of our own lookup from something the user actually
    vouched for — those must not re-enter resolution at the same authority.
    Defaults to generic rather than user authority: this function is called
    automatically after every successful lookup, so the common case is a cache.
    """
    # ⛔ AND A CACHE MAY NOT STORE A FOOD IT CANNOT NAME. The read guard alone
    # would be worse than none here: `get_user_food_match` returning None for a
    # letterless key makes this function take its CREATE branch, so every
    # non-Latin food would mint a fresh `'2'` row on every log — turning a
    # collision into an unbounded pile of them. Both doors, one rule.
    from core.food_intelligence import memory_key_is_addressable

    if not memory_key_is_addressable(name_norm):
        logger.info(
            "event=memory_write_refused user=%s key=%r display=%r "
            "reason=no_semantic_content", user_id, name_norm, display_name)
        return None

    # A CACHE MAY NOT STORE AN IMPOSSIBLE FOOD. Fat is 9 calories per gram, so
    # nothing edible exceeds 900 per 100 g — anything above that is a unit
    # error, usually kilojoules in a kcal field or a per-container figure in a
    # per-100g slot. Found in production: a monk fruit row cached at 5030
    # cal/100g, carrying a USDA id, which would price every later log of it.
    # Refusing the write leaves the food to resolve fresh next time, which is
    # strictly better than remembering a number that cannot be true.
    try:
        _cal100 = float((per100 or {}).get("calories") or 0)
    except (TypeError, ValueError):
        _cal100 = 0.0
    if _cal100 > 900:
        logger.warning(
            "refusing to cache %r for user %s: %.0f cal/100g is not a food",
            name_norm, user_id, _cal100)
        return None

    micros = _extract_micros_100(per100)
    origin = (origin_tier or ("user_regular" if user_confirmed
                              else _ORIGIN_BY_CONFIDENCE.get(confidence,
                                                             "generic_exact")))
    existing = await get_user_food_match(db, user_id, name_norm)
    if existing:
        existing.times_used = (existing.times_used or 1) + 1
        existing.last_used = datetime.utcnow()
        # Self-heal the cache: rows created before the micro panel existed have
        # micros_100_json=NULL. Backfill it the first time a richer profile flows
        # through (e.g. a USDA re-lookup), so the food keeps its micros thereafter.
        if micros and not existing.micros_100_json:
            existing.micros_100_json = json.dumps(micros)
        # Self-heal the serving panel the same way. Rows cached before
        # serving001 hold per-100g alone, which is what makes a counted portion
        # unanswerable; the first lookup that carries a label fills it in and
        # every later log of that food can divide the serving instead of
        # guessing. Never CLEARS a stored panel with an empty one.
        if serving_text and not existing.serving_text:
            existing.serving_text = serving_text
        # Upgrade to user-confirmed if the user corrected it; never downgrade.
        if user_confirmed:
            existing.user_confirmed = True
            existing.confidence = "user-confirmed"
            existing.origin_tier = "user_regular"
        elif not existing.origin_tier:
            # Legacy row, or one written before this column existed. Record what
            # we can infer now; never let a refresh RAISE the stored authority.
            existing.origin_tier = origin
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
        serving_text=(serving_text or None),
        confidence="user-confirmed" if user_confirmed else confidence,
        user_confirmed=user_confirmed,
        origin_tier=origin,
    )
    db.add(m)
    await db.commit()
    return m


async def frequent_foods(db, user_id: int, days: int = 30, limit: int = 8):
    """The user's REGULARS — most-logged foods in the window, each with the most
    recent row's macros. Feeds the structured logger's context so 'a Barebells'
    resolves to THEIR Barebells (exact history macros, flavor-aware ask) instead
    of an invented estimate (Danny 2026-07-23)."""
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from db.models import DailyLog, FoodEntry

    since = clock.now() - timedelta(days=days)
    rows = (await db.execute(
        select(FoodEntry.parsed_food_name, FoodEntry.quantity, FoodEntry.calories,
               FoodEntry.protein, FoodEntry.carbs, FoodEntry.fats,
               FoodEntry.timestamp)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id, FoodEntry.timestamp >= since)
    )).all()
    by_name: dict = {}
    for name, qty, cal, pro, carb, fat, ts in rows:
        n = (name or "").strip()
        if not n or len(n) < 3:
            continue
        slot = by_name.setdefault(n.lower(), {"count": 0, "name": n})
        slot["count"] += 1
        if ts is not None and (slot.get("ts") is None or ts > slot["ts"]):
            slot.update(ts=ts, qty=qty or "", cal=round(cal or 0),
                        protein=round(pro or 0), carbs=round(carb or 0),
                        fats=round(fat or 0))
    top = sorted(by_name.values(), key=lambda s: -s["count"])[:limit]
    return [{"name": s["name"], "qty": s.get("qty", ""), "count": s["count"],
             "calories": s.get("cal", 0), "protein": s.get("protein", 0),
             "carbs": s.get("carbs", 0), "fats": s.get("fats", 0)}
            for s in top if s["count"] >= 2]


# ── ledger events + exactly-once (FOOD_LEDGER_V2 Phase 2) ─────────────────────
# Domain-scoped by design (Danny 2026-07-24): food and fitness ride the SAME
# event history; weight/water join as they migrate onto the contract.
async def record_ledger_event(
    db: AsyncSession, user_id: int, event_type: str, domain: str = "food",
    entry_id: Optional[int] = None, daily_log_id: Optional[int] = None,
    payload: Optional[dict] = None, source: Optional[str] = None,
    commit: bool = True,
):
    """Append one row to the ledger's event history and return it (the id is
    the undo token cards surface). The canonical turn identity is stamped
    from the ambient contextvar (core/turn_identity) so every write traces
    to its inbound turn without threading a parameter through the executor.
    Callers wrap this in try/except — history must never break the write it
    describes."""
    from db.models import LedgerEvent
    from core.turn_identity import current_turn_id
    ev = LedgerEvent(
        user_id=user_id, domain=domain, entry_id=entry_id,
        daily_log_id=daily_log_id, event_type=event_type,
        payload_json=json.dumps(payload) if payload is not None else None,
        source=source, turn_id=current_turn_id())
    try:
        # SAVEPOINT, not a session-level rollback. When the
        # uq_ledger_events_created_entry guard (ledgerdedup001) rejects a
        # duplicate, only this insert must roll back: a full rollback expires
        # every loaded object in the session, and the next attribute access
        # mid-turn dies with a greenlet error — the session poisoning the
        # guard's soft-fail exists to prevent, reintroduced by the soft-fail
        # itself (caught by the tap-log undo test, not by reading the code).
        async with db.begin_nested():
            db.add(ev)
            await db.flush()   # the violation surfaces here, inside the savepoint
    except IntegrityError:
        # The guard did its job: the duplicate is rejected, history keeps one
        # event, and the caller gets None exactly as on any other best-effort
        # failure. Logged loudly — this firing at all means a duplicate
        # writer exists again.
        logger.warning(
            f"event=ledger_dup_blocked domain={domain} "
            f"entry_id={entry_id} type={event_type} source={source!r} — "
            f"a second writer attempted a duplicate created event")
        return None
    # `commit=False` lets a caller that is mid-transaction fold this event into
    # ITS commit, so a domain row and its history land together instead of in
    # two commits with a crash window between them. The savepoint above is
    # unaffected either way — a duplicate is still rejected softly.
    if commit:
        await db.commit()
    return ev


def _entry_event_payload(entry) -> dict:
    """The entry's state at event time, in the ledger's vocabulary.

    Shared by both writers of a `created` event — `add_food_entry` (inside the
    row's own transaction) and `record_created_from_row` (for callers that
    still write history separately). One builder because a `deleted` event
    restores from this payload: two vocabularies would mean undo could rebuild
    a row the recorder never described.
    """
    payload = {}
    for key, attr in (("food_name", "parsed_food_name"),
                      ("exercise_name", "exercise_name"),
                      ("quantity", "quantity"), ("calories", "calories"),
                      ("protein", "protein"), ("carbs", "carbs"),
                      ("fats", "fats"), ("meal_type", "meal_type"),
                      ("sets", "sets"), ("reps", "reps"),
                      ("weight_kg", "weight"),
                      ("duration_minutes", "duration_minutes"),
                      ("is_cardio", "is_cardio")):
        value = getattr(entry, attr, None)
        if value is not None:
            payload[key] = value
    return payload


async def record_created_from_row(
    db: AsyncSession, user_id: int, entry, domain: str, daily_log_id: int,
    source: str,
):
    """The `created` event for a row written OUTSIDE the chat lane.

    Audit O-1. `add_food_entry` / `add_exercise_entry` write the row; the
    ledger event is a separate call, and the tap-log endpoints in
    `api/quick_log.py` and `api/app.py` never made it. `ledger_undo.build_plan`
    takes the last event UNCONDITIONALLY, so the sequence

        tap-log a banana  ->  "undo that"

    inverted the previous CHAT-logged item: a row the user had not asked about
    and was not looking at. Silent, destructive, and reachable from the primary
    iOS surface.

    Reads the COMMITTED ROW rather than the request body, on the same reasoning
    as 2a4c839: the row is what the undo will have to invert, and anything the
    write normalised, rounded or defaulted belongs in the record of it.

    Best-effort, like every other call site — history must never break the
    write it describes.
    """
    payload = _entry_event_payload(entry)
    try:
        return await record_ledger_event(
            db, user_id, "created", domain=domain,
            entry_id=getattr(entry, "id", None),
            daily_log_id=daily_log_id, payload=payload, source=source)
    except Exception as e:
        logger.warning(f"{domain} event (created) skipped: {e}")
        return None


async def get_ledger_events(
    db: AsyncSession, user_id: int, domain: Optional[str] = None,
    entry_id: Optional[int] = None, limit: int = 50,
):
    """Event history, newest first — the audit trail behind 'why did you log
    6 oz?' and the payload source for restoring a deleted entry."""
    from db.models import LedgerEvent
    q = select(LedgerEvent).where(LedgerEvent.user_id == user_id)
    if domain is not None:
        q = q.where(LedgerEvent.domain == domain)
    if entry_id is not None:
        q = q.where(LedgerEvent.entry_id == entry_id)
    res = await db.execute(q.order_by(desc(LedgerEvent.created_at),
                                      desc(LedgerEvent.id)).limit(limit))
    return res.scalars().all()


async def ledger_revision(db: AsyncSession, user_id: int,
                          since: Optional[datetime] = None) -> int:
    """Monotonic version of a user's logged state (P0.2 Phase 4).

    The count of ledger events, which only ever grows — a delete appends an
    event rather than removing one. That makes it a usable optimistic-
    concurrency token: a card built at revision N can be detected as stale
    when the day has moved to N+1, without a schema column to keep in sync.

    `since` scopes it to a day (pass the day's start) — the common case, since
    a card renders one day.
    """
    from db.models import LedgerEvent
    q = select(func.count(LedgerEvent.id)).where(LedgerEvent.user_id == user_id)
    if since is not None:
        q = q.where(LedgerEvent.created_at >= since)
    try:
        return int((await db.execute(q)).scalar() or 0)
    except Exception as e:
        logger.debug(f"ledger_revision unavailable: {e}")
        return 0


async def claim_processed_turn(
    db: AsyncSession, user_id: int, idem_key: str,
    result_summary: str = "", window_minutes: int = 60,
) -> bool:
    """Durable exactly-once claim for a structured food commit.

    True  → this turn is first; the claim is recorded, proceed with the writes.
    False → the same (user, key) was claimed inside the window (resend,
            double-tap, cross-device race, post-restart redelivery) — answer
            from the prior outcome, write nothing.

    A claim older than the window is re-claimed: the identical message a day
    later ('had a banana') is a genuinely new turn. The unique constraint is
    the last word under concurrency; its violation is absorbed in a SAVEPOINT
    so the caller's session survives."""
    from db.models import ProcessedTurn
    now = datetime.utcnow()
    res = await db.execute(select(ProcessedTurn).where(and_(
        ProcessedTurn.user_id == user_id, ProcessedTurn.idem_key == idem_key)))
    row = res.scalars().first()
    if row is not None:
        if (now - (row.created_at or now)) <= timedelta(minutes=window_minutes):
            return False
        row.created_at = now
        row.result_summary = (result_summary or "")[:500]
        await db.commit()
        return True
    try:
        async with db.begin_nested():
            db.add(ProcessedTurn(user_id=user_id, idem_key=idem_key,
                                 result_summary=(result_summary or "")[:500]))
        await db.commit()
        return True
    except IntegrityError:
        # A concurrent claim (other device / worker) won the insert race.
        try:
            await db.rollback()
        except Exception:
            pass
        return False


async def record_surface_mutation(
    db: AsyncSession, user_id: int, event_type: str, *, domain: str,
    entry_id: Optional[int] = None, daily_log_id: Optional[int] = None,
    payload: Optional[dict] = None, surface: str = "dashboard",
) -> None:
    """Best-effort ledger event for a NON-CHAT mutation — dashboard edits, API
    quick-logs, health imports (P0.6). Stamps a surface turn identity so the
    write traces back to the action that caused it, and NEVER raises: history
    must never break the edit it describes.

    Same events, same payload shapes as the chat executor, so undo/restore and
    the audit trail reach every surface rather than just the chat lane.

    A CANONICAL TURN ID ALWAYS WINS. The synthetic id below is a fallback for
    surfaces that have no turn identity of their own — it is derived from
    `(surface, event_type, entry_id)`, so it is stable rather than unique: two
    edits of the same row a day apart produce the SAME id, and the
    turn↔operation join cannot tell them apart. That is acceptable as a floor
    and wrong as an override, so a handler that has already opened a real turn
    scope (B2's `_turn_scope`) keeps its id and this function only supplies the
    provenance label.

    Overwriting it was not hypothetical: as each surface moves onto the
    mutation contract, its handler sets the canonical id and then calls a
    helper that reaches here — and the event would have been stamped
    `ios_edit:updated:41` instead of the turn the request actually was, so the
    surface would look migrated while its events stayed unjoinable.

    The previous value is restored in `finally` for the same reason
    `_turn_scope` does it: this runs mid-request, and leaving a synthetic id
    set behind would stamp every LATER write in the same request with it.
    """
    from core.turn_identity import CURRENT_TURN_ID
    token = None
    try:
        if CURRENT_TURN_ID.get() is None:
            token = CURRENT_TURN_ID.set(
                f"{surface}:{event_type}:{entry_id or '-'}")
        await record_ledger_event(
            db, user_id, event_type, domain=domain, entry_id=entry_id,
            daily_log_id=daily_log_id, payload=payload, source=surface)
    except Exception as e:
        logger.warning(f"surface ledger event skipped ({surface}/{domain}/{event_type}): {e}")
    finally:
        if token is not None:
            CURRENT_TURN_ID.reset(token)


# ── durable background jobs (P0.7) ────────────────────────────────────────────
async def enqueue_background_job(
    db: AsyncSession, user_id: int, kind: str,
    payload: Optional[dict] = None, dedup_key: Optional[str] = None,
    dedup_window_min: int = 30, commit: bool = True,
    turn_id: Optional[str] = None,
) -> Optional[int]:
    """Queue durable post-turn work. Returns the row id, or None when a live
    row with the same dedup_key already covers it (a busy conversation must
    not queue twenty profile rebuilds). Never raises — the fast in-process
    task still runs either way.

    `commit=False` is what makes this an OUTBOX rather than a second write.
    Committing here while a caller held an open transaction would commit their
    half-finished domain work as a side effect — a hidden commit inside a
    helper, which is the transaction-ownership rule this codebase already
    learned the hard way with ledger events. With `commit=False` the job row
    lands in the SAME transaction as the mutation that asked for it: either
    both are durable or neither happened, and there is no window where the
    food is committed and the work it owes was lost.

    `turn_id` ties the queued work to the request that caused it. Defaults to
    the ambient turn when one is bound, so existing callers gain traceability
    without changing.
    """
    from db.models import BackgroundJob
    try:
        if dedup_key:
            cutoff = clock.now() - timedelta(minutes=dedup_window_min)
            existing = (await db.execute(
                select(BackgroundJob).where(and_(
                    BackgroundJob.user_id == user_id,
                    BackgroundJob.dedup_key == dedup_key,
                    BackgroundJob.created_at >= cutoff,
                    BackgroundJob.status.in_(("pending", "done")),
                )).limit(1))).scalars().first()
            if existing is not None:
                return None
        if turn_id is None:
            try:
                from core.turn_identity import current_turn_id
                turn_id = current_turn_id()
            except Exception:
                turn_id = None
        job = BackgroundJob(
            user_id=user_id, kind=kind,
            payload_json=json.dumps(payload) if payload is not None else None,
            dedup_key=dedup_key, status="pending",
            turn_id=turn_id, build_sha=_build_stamp().get("sha"),
            next_attempt_at=datetime.utcnow())
        db.add(job)
        # Flush FIRST and keep the id. Reading `job.id` after a commit reloads
        # an expired object, which is a needless round trip and — on the shared
        # aiosqlite connection the tests use — a place to hang. The id is
        # assigned by the flush; nothing after it can change it.
        await db.flush()
        job_id = job.id
        if commit:
            await db.commit()
        return job_id
    except Exception as e:
        logger.warning(f"enqueue_background_job skipped ({kind}): {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def claim_due_background_jobs(db: AsyncSession, limit: int = 20) -> list:
    """Pending jobs whose attempt time has arrived, oldest first — CLAIMED.

    This used to be a plain SELECT, so two sweepers running at once both picked
    up the same rows and did the work twice. That was survivable while the only
    kinds were idempotent (profile synthesis throttles, reflection dedups) and
    stops being survivable the moment anything user-visible joins the queue:
    sending a push notification twice is not a no-op.

    Rows are now marked `processing` with a `claimed_at` stamp inside the
    selecting transaction, under `FOR UPDATE SKIP LOCKED` where the database
    supports it — a second worker skips the locked rows and takes the next
    ones instead of blocking or duplicating.

    A worker that dies mid-job leaves the row `processing`; `requeue_stale_jobs`
    returns it to pending. At-least-once, which is what these jobs want, but no
    longer at-least-once PER SWEEPER.
    """
    from db.models import BackgroundJob
    now = datetime.utcnow()
    stmt = (select(BackgroundJob)
            .where(and_(BackgroundJob.status == "pending",
                        or_(BackgroundJob.next_attempt_at.is_(None),
                            BackgroundJob.next_attempt_at <= now)))
            .order_by(BackgroundJob.created_at)
            .limit(limit))
    # SKIP LOCKED is Postgres (production). SQLite has no row locks and no
    # concurrent writers, so the plain select is already exclusive there.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    jobs = (await db.execute(stmt)).scalars().all()
    for job in jobs:
        job.status = "processing"
        job.claimed_at = now
    if jobs:
        await db.commit()
    return jobs


async def requeue_stale_jobs(db: AsyncSession, older_than_min: int = 15) -> int:
    """Return jobs abandoned by a dead worker to `pending`.

    A worker that crashes between claiming and finishing leaves its rows
    `processing` forever, and a queue that quietly stops draining is worse than
    one that visibly backs up. Bounded by `attempts`, so a job that keeps
    killing its worker still reaches dead_letter rather than looping.
    """
    from db.models import BackgroundJob
    cutoff = clock.now() - timedelta(minutes=older_than_min)
    rows = (await db.execute(
        select(BackgroundJob).where(and_(
            BackgroundJob.status == "processing",
            BackgroundJob.claimed_at.isnot(None),
            BackgroundJob.claimed_at <= cutoff)))).scalars().all()
    for job in rows:
        job.status = "pending"
        job.claimed_at = None
        job.last_error = "requeued after worker went away"
    if rows:
        await db.commit()
        logger.warning(f"event=outbox_requeued count={len(rows)}")
    return len(rows)


async def outbox_health(db: AsyncSession) -> dict:
    """Backlog size and oldest pending age — a queue nobody can see is a queue
    nobody notices has stopped."""
    from db.models import BackgroundJob
    out: dict = {}
    try:
        for status in ("pending", "processing", "failed", "dead_letter"):
            out[status] = int((await db.execute(
                select(func.count()).select_from(BackgroundJob)
                .where(BackgroundJob.status == status))).scalar() or 0)
        oldest = (await db.execute(
            select(func.min(BackgroundJob.created_at))
            .where(BackgroundJob.status == "pending"))).scalar()
        out["oldest_pending_age_s"] = (
            int((clock.now() - oldest).total_seconds()) if oldest else 0)
    except Exception as e:                       # pragma: no cover
        out["error"] = type(e).__name__
    return out


async def finish_background_job(
    db: AsyncSession, job_id: int, ok: bool, error: str = "",
    max_attempts: int = 3, retry_delay_min: int = 10,
) -> None:
    """Mark a job done, or schedule its retry with backoff until max_attempts."""
    from db.models import BackgroundJob
    try:
        job = await db.get(BackgroundJob, job_id)
        if job is None:
            return
        job.attempts = (job.attempts or 0) + 1
        if ok:
            job.status = "done"
            job.completed_at = datetime.utcnow()
        elif job.attempts >= max_attempts:
            # DEAD LETTER, not "failed". `failed` read like a transient outcome
            # and nothing distinguished "will retry" from "gave up forever" —
            # so exhausted work was invisible. This status exists to be alerted
            # on.
            job.status = "dead_letter"
            job.last_error = (error or "")[:500]
            logger.error(
                f"event=outbox_dead_letter job={job.id} kind={job.kind} "
                f"turn={job.turn_id or '-'} attempts={job.attempts} "
                f"err={(error or '')[:120]}")
        else:
            job.last_error = (error or "")[:500]
            # BACK TO PENDING. Claiming moves a row to `processing`, so a retry
            # that only set `next_attempt_at` would leave it claimed forever
            # and it would never be swept again — the queue would drain to a
            # stop with every failure. Caught by the existing durability tests,
            # which is exactly what they were written for.
            job.status = "pending"
            job.claimed_at = None
            job.next_attempt_at = datetime.utcnow() + timedelta(
                minutes=retry_delay_min * job.attempts)
        await db.commit()
    except Exception as e:
        logger.warning(f"finish_background_job failed for {job_id}: {e}")
