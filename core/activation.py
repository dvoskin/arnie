"""
Activation gates — earn-your-tabs progression for new users.

The Log and Coach tabs start locked and are earned by doing the one thing the
whole product depends on: logging food.

  Log tab    → unlocks at 2 lifetime food entries (one could be an accident;
               two means the loop has clicked — achievable in the first session)
  Coach tab  → unlocks after 2 distinct days with ≥1000 kcal logged (coach
               cards are noise on thin data, and requiring a second day builds
               the day-2 return visit into the product)

Design rules:
  * The SERVER is the source of truth. Clients render lock state from the
    `activation` block; they never compute it.
  * Unlocks are one-way. The earned timestamp is persisted on the user row and
    never cleared — deleting a food entry must not re-lock a tab.
  * Existing users are grandfathered (migration e7750abe4362 seeds everyone
    who predates the feature; `_grandfathered` is a runtime belt-and-suspenders
    for rows that slip past the seed, e.g. restored from a backup).
  * Chat is never gated — it's how you earn everything else.
"""
from __future__ import annotations

import logging
from datetime import datetime, date

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, DailyLog, FoodEntry

logger = logging.getLogger(__name__)

# Thresholds. If these ever change, only NEW locks are affected — already
# earned tabs stay earned via the persisted timestamps.
LOG_UNLOCK_ENTRIES = 2       # lifetime food entries → Log tab
COACH_UNLOCK_DAYS = 2        # qualifying days → Coach tab
QUALIFYING_DAY_KCAL = 1000   # a day "counts" once this many kcal are logged

# Users created before this date predate the gates entirely. The migration
# already seeded them unlocked; this is the runtime net for any row that
# missed the seed (restored backups, out-of-band inserts).
ACTIVATION_EPOCH = date(2026, 7, 18)


def _grandfathered(user: User) -> bool:
    created = getattr(user, "created_at", None)
    if created is None:
        # No creation timestamp = pre-dates reliable bookkeeping. Never lock.
        return True
    d = created.date() if isinstance(created, datetime) else created
    return d < ACTIVATION_EPOCH


async def _food_entry_count(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count(FoodEntry.id))
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id)
    )
    return int(result.scalar() or 0)


async def _qualifying_day_count(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count(DailyLog.id)).where(and_(
            DailyLog.user_id == user_id,
            DailyLog.total_calories >= QUALIFYING_DAY_KCAL,
        ))
    )
    return int(result.scalar() or 0)


async def get_activation(db: AsyncSession, user: User, persist: bool = True) -> dict:
    """The wire `activation` block; flips + persists unlock timestamps as earned.

    Cheap fast-path: when both tabs are already unlocked (every established
    user after their first two days), this is zero extra queries.

    persist=False computes the same answer without committing — for read paths
    that must not flush someone else's pending session state (context builder
    mid-chat-turn). The flip is then persisted by the next /day or /profile.
    """
    log_at = getattr(user, "log_unlocked_at", None)
    coach_at = getattr(user, "coach_unlocked_at", None)

    if log_at and coach_at:
        return _shape(unlocked=True, entries=None, days=None,
                      log_unlocked=True, coach_unlocked=True)

    if _grandfathered(user):
        if persist:
            now = datetime.utcnow()
            user.log_unlocked_at = user.log_unlocked_at or now
            user.coach_unlocked_at = user.coach_unlocked_at or now
            await db.commit()
        return _shape(unlocked=True, entries=None, days=None,
                      log_unlocked=True, coach_unlocked=True)

    entries = await _food_entry_count(db, user.id)
    days = await _qualifying_day_count(db, user.id)

    flipped = False
    now = datetime.utcnow()
    if log_at is None and entries >= LOG_UNLOCK_ENTRIES:
        log_at = now
        flipped = True
        if persist:
            user.log_unlocked_at = now
            logger.info("activation: user %s unlocked LOG (%d entries)", user.id, entries)
    if coach_at is None and days >= COACH_UNLOCK_DAYS:
        coach_at = now
        flipped = True
        if persist:
            user.coach_unlocked_at = now
            logger.info("activation: user %s unlocked COACH (%d qualifying days)", user.id, days)
    if flipped and persist:
        await db.commit()

    return _shape(unlocked=bool(log_at and coach_at), entries=entries, days=days,
                  log_unlocked=log_at is not None, coach_unlocked=coach_at is not None)


def _shape(*, unlocked: bool, entries, days, log_unlocked: bool, coach_unlocked: bool) -> dict:
    """The wire shape. Counts are capped at their goal so the client can render
    "2/2" progress directly; `all_unlocked` lets it skip the whole code path."""
    return {
        "all_unlocked": unlocked,
        "log": {
            "unlocked": log_unlocked,
            "progress": LOG_UNLOCK_ENTRIES if log_unlocked else min(entries or 0, LOG_UNLOCK_ENTRIES),
            "goal": LOG_UNLOCK_ENTRIES,
        },
        "coach": {
            "unlocked": coach_unlocked,
            "progress": COACH_UNLOCK_DAYS if coach_unlocked else min(days or 0, COACH_UNLOCK_DAYS),
            "goal": COACH_UNLOCK_DAYS,
            "kcal_per_day": QUALIFYING_DAY_KCAL,
        },
    }


def activation_context_line(activation: dict) -> str | None:
    """One compact line for Arnie's chat context so he can nudge naturally
    ("one more logged day and your Coach tab opens"). Null once everything is
    unlocked — established users never carry this token weight."""
    if activation.get("all_unlocked"):
        return None
    parts = []
    log = activation.get("log") or {}
    coach = activation.get("coach") or {}
    if not log.get("unlocked"):
        parts.append(f"Log tab locked ({log.get('progress', 0)}/{log.get('goal')} foods logged)")
    if not coach.get("unlocked"):
        parts.append(
            f"Coach tab locked ({coach.get('progress', 0)}/{coach.get('goal')} days with "
            f"{coach.get('kcal_per_day')}+ kcal logged)"
        )
    if not parts:
        return None
    return "[ACTIVATION] " + "; ".join(parts) + \
        " — encourage logging to unlock; never call it a paywall, it's earned."
