"""Achievements — quiet trophies, loud moments.

A badge layer over data Arnie already tracks: streak milestones, volume,
training, and precision. The UI philosophy (per Danny): badges live tucked
away in a monochrome trophy sheet; the CELEBRATION is the feature — earned
in the conversation via screen effects and Arnie's own voice, never a
"🏆 Badge Unlocked!" system banner.

Guardrails baked in server-side:
  • one celebration per day, max — later badges accrue silently;
  • never stacked on a turn that already carries a screen effect
    (first-food moment, activation unlock, daily-goal FX);
  • when several badges land in one turn, the highest-ranked one is the
    `primary` (the one worth saying out loud) and the rest accrue.

Checks run only on turns that actually WROTE a log, and every count is a
single aggregate query — the engine adds no meaningful latency to a turn.
Fail-open everywhere: a broken badge check must never break a coaching turn.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, DailyLog, FoodEntry, ExerciseEntry, Achievement

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Registry — the single source of truth for what badges exist.
# rank orders celebration priority (higher = bigger moment). `line` is what
# Arnie says when it's earned — his voice, sentence case, no software language.
#
# v2 fields (2026-07):
#   metal   — bronze | silver | gold | platinum. The LADDER: what the mark is
#             cast in, so a 100-day streak visibly outranks a first log instead
#             of every badge arriving in the same ember gold.
#   family  — nutrition | training | consistency | precision. Groups the wall.
#   metric  — which counter in the computed state this badge reads.
#   target  — the value of that counter which earns it.
#
# metric+target are the ONE source for both the earn condition and the progress
# bar, so "7 of 10 workouts" can never disagree with when the badge actually
# mints. `tier` (big|small) stays on the wire untouched — build 359 in the wild
# keys its confetti and gold rings off it.
# ─────────────────────────────────────────────────────────────────────────────

BADGES: list[dict] = [
    # Volume — foods
    {"id": "first_food",   "title": "First log",        "line": "First entry in the book.",              "icon": "fork.knife",          "tier": "small", "rank": 10,  "metal": "bronze",   "family": "nutrition",   "metric": "foods",        "target": 1},
    {"id": "first_photo",  "title": "First photo log",  "line": "Snapped it, logged it.",                "icon": "camera",              "tier": "small", "rank": 12,  "metal": "bronze",   "family": "nutrition",   "metric": "photos",       "target": 1},
    {"id": "first_workout","title": "First workout",    "line": "First session on the books.",           "icon": "dumbbell",            "tier": "small", "rank": 14,  "metal": "bronze",   "family": "training",    "metric": "workouts",     "target": 1},
    {"id": "foods_50",     "title": "50 foods logged",  "line": "Fifty foods on the record.",            "icon": "square.stack.3d.up",  "tier": "small", "rank": 20,  "metal": "silver",   "family": "nutrition",   "metric": "foods",        "target": 50},
    {"id": "workouts_10",  "title": "10 workouts",      "line": "Ten sessions logged.",                  "icon": "figure.strengthtraining.traditional", "tier": "small", "rank": 22, "metal": "silver", "family": "training", "metric": "workouts", "target": 10},
    {"id": "protein_7",    "title": "Protein × 7",      "line": "Seven days of protein targets hit.",    "icon": "target",              "tier": "small", "rank": 24,  "metal": "silver",   "family": "precision",   "metric": "protein_days", "target": 7},
    {"id": "foods_250",    "title": "250 foods logged", "line": "250 logs deep. This is a habit.",       "icon": "square.stack.3d.up.fill", "tier": "small", "rank": 30, "metal": "gold",  "family": "nutrition",   "metric": "foods",        "target": 250},
    {"id": "workouts_50",  "title": "50 workouts",      "line": "Fifty sessions. Different animal.",     "icon": "figure.strengthtraining.traditional", "tier": "small", "rank": 32, "metal": "gold",   "family": "training", "metric": "workouts", "target": 50},
    {"id": "foods_1000",   "title": "1,000 foods",      "line": "A thousand logs. Elite consistency.",   "icon": "crown",               "tier": "small", "rank": 40,  "metal": "platinum", "family": "nutrition",   "metric": "foods",        "target": 1000},
    # Consistency — streak milestones (the big moments)
    {"id": "streak_3",     "title": "3-day streak",     "line": "Three days straight.",                  "icon": "flame",               "tier": "big",   "rank": 50,  "metal": "silver",   "family": "consistency", "metric": "streak",       "target": 3},
    {"id": "streak_7",     "title": "7-day streak",     "line": "A full week, every single day.",        "icon": "flame",               "tier": "big",   "rank": 60,  "metal": "silver",   "family": "consistency", "metric": "streak",       "target": 7},
    {"id": "streak_14",    "title": "14-day streak",    "line": "Two weeks straight. That's a habit now.","icon": "flame.fill",         "tier": "big",   "rank": 70,  "metal": "gold",     "family": "consistency", "metric": "streak",       "target": 14},
    {"id": "streak_30",    "title": "30-day streak",    "line": "Thirty days. A whole month, no gaps.",  "icon": "flame.fill",          "tier": "big",   "rank": 80,  "metal": "gold",     "family": "consistency", "metric": "streak",       "target": 30},
    {"id": "streak_50",    "title": "50-day streak",    "line": "Fifty days straight.",                  "icon": "flame.fill",          "tier": "big",   "rank": 90,  "metal": "platinum", "family": "consistency", "metric": "streak",       "target": 50},
    {"id": "streak_100",   "title": "100-day streak",   "line": "One hundred days. Legendary.",          "icon": "trophy.fill",         "tier": "big",   "rank": 100, "metal": "platinum", "family": "consistency", "metric": "streak",       "target": 100},
]

_BY_ID = {b["id"]: b for b in BADGES}

_STREAK_IDS = {b["id"]: b["target"] for b in BADGES if b["metric"] == "streak"}

# How many unearned badges carry a `next_up` position — the shelf the client
# renders as "what to shoot for". Three is enough to give the card a row
# without turning the wall into a to-do list.
NEXT_UP_COUNT = 3

_WIRE_KEYS = ("id", "title", "line", "icon", "tier", "metal", "family")


def _wire(badge: dict) -> dict:
    """The client-facing shape for one badge (no rank — that's server policy)."""
    return {k: badge[k] for k in _WIRE_KEYS}


# ─────────────────────────────────────────────────────────────────────────────
# State — cheap aggregates over existing tables
# ─────────────────────────────────────────────────────────────────────────────

async def _food_count(db: AsyncSession, uid: int, photos_only: bool = False) -> int:
    q = (select(func.count(FoodEntry.id))
         .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
         .where(DailyLog.user_id == uid))
    if photos_only:
        q = q.where(FoodEntry.from_photo.is_(True))
    return int((await db.execute(q)).scalar() or 0)


async def _workout_count(db: AsyncSession, uid: int) -> int:
    q = (select(func.count(ExerciseEntry.id))
         .join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
         .where(DailyLog.user_id == uid))
    return int((await db.execute(q)).scalar() or 0)


async def _protein_day_count(db: AsyncSession, user: User) -> int:
    pt = getattr(user, "protein_target", None)
    if not pt:
        return 0
    q = (select(func.count(DailyLog.id))
         .where(DailyLog.user_id == user.id, DailyLog.total_protein >= pt))
    return int((await db.execute(q)).scalar() or 0)


async def _best_streak(db: AsyncSession, user: User) -> int:
    """Best logging chain inside the streak engine's 90-day window — badges
    award in real time as chains grow, so the window never misses a live one."""
    from core.streaks import compute_streaks
    from db.queries import _user_today, get_recent_logs
    logs = await get_recent_logs(db, user.id, days=90)
    streaks = compute_streaks(logs, _user_today(user.timezone or "UTC"))
    chain = streaks.get("logging") or {}
    return max(int(chain.get("current") or 0), int(chain.get("best") or 0))


#: Counters for a user with nothing left to chase. Earned badges read full
#: from their Achievement rows, not from these, so a zeroed state is correct
#: (not merely safe) whenever every badge is already minted.
ZERO_STATE: dict = {"foods": 0, "photos": 0, "workouts": 0,
                    "protein_days": 0, "streak": 0}


async def compute_state(db: AsyncSession, user: User, *,
                        with_streak: bool = True) -> dict:
    """Every counter the registry reads, in one pass.

    Shared by the award engine and the wall so opening the trophy sheet costs
    the same queries as a log turn — the endpoint runs the backfill AND builds
    the wall from a single computation. `with_streak=False` skips the 90-day
    log fetch, which is by far the most expensive thing in this module and is
    pure waste once every streak badge is earned.
    """
    return {
        "foods":        await _food_count(db, user.id),
        "photos":       await _food_count(db, user.id, photos_only=True),
        "workouts":     await _workout_count(db, user.id),
        "protein_days": await _protein_day_count(db, user),
        "streak":       await _best_streak(db, user) if with_streak else 0,
    }


def _conditions(state: dict) -> dict[str, bool]:
    """badge_id → earned? against the computed state.

    Derived from each badge's own metric/target, so the condition and the
    progress bar the client draws are guaranteed to be the same rule.
    """
    return {b["id"]: state.get(b["metric"], 0) >= b["target"] for b in BADGES}


def _progress(badge: dict, state: dict, earned: bool) -> dict:
    """`{current, target, pct}` for one badge.

    `current` is the real counter (it can exceed target on an earned badge);
    `pct` is clamped to 0…1 so the client can drive a ring straight off it.
    Earned badges read full regardless of the live counter — a streak badge
    stays earned after the chain breaks, and a half-drawn ring under an earned
    mark would read as though it had been taken away.
    """
    target = badge["target"]
    current = target if earned else min(int(state.get(badge["metric"], 0)), target)
    return {
        "current": current,
        "target": target,
        "pct": 1.0 if earned else round(min(current / target, 1.0), 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

async def check_achievements(db: AsyncSession, user: User, *,
                             effect_taken: bool = False,
                             state: Optional[dict] = None) -> Optional[dict]:
    """Award any newly-earned badges and shape the wire block, or None.

    `effect_taken` — this turn already carries a screen effect (first-food
    moment, goal FX); the badge still lands but celebrates silently, keeping
    ONE celebration per turn. A prior badge earned earlier today also mutes
    the celebration (one loud moment per day).

    `state` — a precomputed `compute_state` dict. The wall endpoint passes the
    one it already needs so a wall read doesn't count everything twice.
    """
    uid = user.id
    rows = (await db.execute(
        select(Achievement).where(Achievement.user_id == uid))).scalars().all()
    earned = {r.badge_id for r in rows}
    unearned = [b for b in BADGES if b["id"] not in earned]
    if not unearned:
        return None

    if state is None:
        # Streak logs are only worth fetching when a streak badge is still open.
        state = await compute_state(
            db, user,
            with_streak=any(b["id"] in _STREAK_IDS for b in unearned))
    hit = _conditions(state)
    new = [b for b in unearned if hit.get(b["id"])]
    if not new:
        return None

    for b in new:
        db.add(Achievement(user_id=uid, badge_id=b["id"]))
    await db.commit()

    # One loud moment per day: if any PRIOR badge was earned today, stay quiet.
    from db.queries import _user_today
    today = _user_today(user.timezone or "UTC")
    celebrated_today = any(
        r.earned_at is not None and r.earned_at.date() == today for r in rows)

    primary = max(new, key=lambda b: b["rank"])
    return {
        "primary": _wire(primary),
        "new": [b["id"] for b in new],
        "celebrate": (not effect_taken) and (not celebrated_today),
    }


async def badge_wall(db: AsyncSession, user: User, *,
                     state: Optional[dict] = None) -> list[dict]:
    """The trophy sheet: every badge in registry order, earned_at when earned.

    v2 adds, per badge:
      progress — `{current, target, pct}` against the same metric/target that
                 earns it, so unearned marks can show how close they are.
      next_up  — 0-based position in the "what to shoot for next" queue, or
                 null. RANKED BY HOW CLOSE THE BADGE ACTUALLY IS, which
                 registry order only approximates: a user 240 foods deep is
                 nearer to foods_250 than to a 3-day streak they just broke.

    `state` — precomputed counters (see `compute_state`); the endpoint passes
    the one its backfill already built.
    """
    rows = (await db.execute(
        select(Achievement).where(Achievement.user_id == user.id))).scalars().all()
    earned_at = {r.badge_id: r.earned_at for r in rows}
    if state is None:
        state = await compute_state(db, user)

    wall = [{
        **_wire(b),
        "earned_at": (earned_at[b["id"]].isoformat() if b["id"] in earned_at else None),
        "progress": _progress(b, state, earned=b["id"] in earned_at),
    } for b in BADGES]

    # Nearest-first among the unearned. Ties (everything at 0% for a brand-new
    # user) fall back to rank, so the opening shelf is the gentle three.
    # A badge sitting at 100% but unminted is mid-award (the caller skipped the
    # backfill, or it threw) — it's not something to shoot for, and "50 of 50"
    # on the next-up row reads as broken. Leave it out until it mints.
    by_id = {b["id"]: b for b in BADGES}
    queue = sorted(
        (w for w in wall if w["earned_at"] is None and w["progress"]["pct"] < 1.0),
        key=lambda w: (-w["progress"]["pct"], by_id[w["id"]]["rank"]),
    )[:NEXT_UP_COUNT]
    for i, w in enumerate(queue):
        w["next_up"] = i
    for w in wall:
        w.setdefault("next_up", None)
    return wall


async def wall_with_backfill(db: AsyncSession, user: User) -> list[dict]:
    """The GET /achievements read: backfill, then build the wall, computing the
    counters at most ONCE and only as far as they're actually needed.

    The cost is driven entirely by what's still open:
      • everything earned      → no counters at all, just the Achievement rows
                                 (as cheap as the wall was before progress);
      • no streak badge open   → counters WITHOUT the 90-day log fetch;
      • otherwise              → the full pass, shared by backfill and wall.

    Fail-open: a broken counter pass degrades to no progress bars, never to a
    blank wall — earned marks come from the rows, not the counters.
    """
    rows = (await db.execute(
        select(Achievement).where(Achievement.user_id == user.id))).scalars().all()
    unearned = [b for b in BADGES if b["id"] not in {r.badge_id for r in rows}]
    if not unearned:
        return await badge_wall(db, user, state=ZERO_STATE)

    state = ZERO_STATE
    try:
        state = await compute_state(
            db, user,
            with_streak=any(b["metric"] == "streak" for b in unearned))
        await check_achievements(db, user, effect_taken=True, state=state)
    except Exception:
        logger.warning("achievement backfill on wall read failed", exc_info=True)
    return await badge_wall(db, user, state=state)
