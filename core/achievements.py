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
# ─────────────────────────────────────────────────────────────────────────────

BADGES: list[dict] = [
    # Volume — foods
    {"id": "first_food",   "title": "First log",        "line": "First entry in the book.",              "icon": "fork.knife",          "tier": "small", "rank": 10},
    {"id": "first_photo",  "title": "First photo log",  "line": "Snapped it, logged it.",                "icon": "camera",              "tier": "small", "rank": 12},
    {"id": "first_workout","title": "First workout",    "line": "First session on the books.",           "icon": "dumbbell",            "tier": "small", "rank": 14},
    {"id": "foods_50",     "title": "50 foods logged",  "line": "Fifty foods on the record.",            "icon": "square.stack.3d.up",  "tier": "small", "rank": 20},
    {"id": "workouts_10",  "title": "10 workouts",      "line": "Ten sessions logged.",                  "icon": "figure.strengthtraining.traditional", "tier": "small", "rank": 22},
    {"id": "protein_7",    "title": "Protein × 7",      "line": "Seven days of protein targets hit.",    "icon": "target",              "tier": "small", "rank": 24},
    {"id": "foods_250",    "title": "250 foods logged", "line": "250 logs deep. This is a habit.",       "icon": "square.stack.3d.up.fill", "tier": "small", "rank": 30},
    {"id": "workouts_50",  "title": "50 workouts",      "line": "Fifty sessions. Different animal.",     "icon": "figure.strengthtraining.traditional", "tier": "small", "rank": 32},
    {"id": "foods_1000",   "title": "1,000 foods",      "line": "A thousand logs. Elite consistency.",   "icon": "crown",               "tier": "small", "rank": 40},
    # Consistency — streak milestones (the big moments)
    {"id": "streak_3",     "title": "3-day streak",     "line": "Three days straight.",                  "icon": "flame",               "tier": "big",   "rank": 50},
    {"id": "streak_7",     "title": "7-day streak",     "line": "A full week, every single day.",        "icon": "flame",               "tier": "big",   "rank": 60},
    {"id": "streak_14",    "title": "14-day streak",    "line": "Two weeks straight. That's a habit now.","icon": "flame.fill",         "tier": "big",   "rank": 70},
    {"id": "streak_30",    "title": "30-day streak",    "line": "Thirty days. A whole month, no gaps.",  "icon": "flame.fill",          "tier": "big",   "rank": 80},
    {"id": "streak_50",    "title": "50-day streak",    "line": "Fifty days straight.",                  "icon": "flame.fill",          "tier": "big",   "rank": 90},
    {"id": "streak_100",   "title": "100-day streak",   "line": "One hundred days. Legendary.",          "icon": "trophy.fill",         "tier": "big",   "rank": 100},
]

_BY_ID = {b["id"]: b for b in BADGES}

_STREAK_IDS = {f"streak_{n}": n for n in (3, 7, 14, 30, 50, 100)}


def _wire(badge: dict) -> dict:
    """The client-facing shape for one badge (no rank — that's server policy)."""
    return {k: badge[k] for k in ("id", "title", "line", "icon", "tier")}


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


def _conditions(state: dict) -> dict[str, bool]:
    """badge_id → earned? against the computed state."""
    out = {
        "first_food":    state["foods"] >= 1,
        "foods_50":      state["foods"] >= 50,
        "foods_250":     state["foods"] >= 250,
        "foods_1000":    state["foods"] >= 1000,
        "first_photo":   state["photos"] >= 1,
        "first_workout": state["workouts"] >= 1,
        "workouts_10":   state["workouts"] >= 10,
        "workouts_50":   state["workouts"] >= 50,
        "protein_7":     state["protein_days"] >= 7,
    }
    for bid, n in _STREAK_IDS.items():
        out[bid] = state["streak"] >= n
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

async def check_achievements(db: AsyncSession, user: User, *,
                             effect_taken: bool = False) -> Optional[dict]:
    """Award any newly-earned badges and shape the wire block, or None.

    `effect_taken` — this turn already carries a screen effect (first-food
    moment, goal FX); the badge still lands but celebrates silently, keeping
    ONE celebration per turn. A prior badge earned earlier today also mutes
    the celebration (one loud moment per day).
    """
    uid = user.id
    rows = (await db.execute(
        select(Achievement).where(Achievement.user_id == uid))).scalars().all()
    earned = {r.badge_id for r in rows}
    unearned = [b for b in BADGES if b["id"] not in earned]
    if not unearned:
        return None

    state = {
        "foods":        await _food_count(db, uid),
        "photos":       await _food_count(db, uid, photos_only=True),
        "workouts":     await _workout_count(db, uid),
        "protein_days": await _protein_day_count(db, user),
        # Streak logs are only worth fetching when a streak badge is still open.
        "streak": (await _best_streak(db, user)
                   if any(b["id"] in _STREAK_IDS for b in unearned) else 0),
    }
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


async def badge_wall(db: AsyncSession, user: User) -> list[dict]:
    """The trophy sheet: every badge in registry order, earned_at when earned.
    Monochrome and quiet by design — the client ghosts the unearned ones."""
    rows = (await db.execute(
        select(Achievement).where(Achievement.user_id == user.id))).scalars().all()
    earned_at = {r.badge_id: r.earned_at for r in rows}
    return [{
        **_wire(b),
        "earned_at": (earned_at[b["id"]].isoformat() if b["id"] in earned_at else None),
    } for b in BADGES]
