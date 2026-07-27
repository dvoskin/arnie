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
from datetime import timedelta
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

    # ── v3 ───────────────────────────────────────────────────────────────────
    # Behaviour over volume. Everything above counts a number going up; these
    # name something the user actually did. Two are `hidden` — see below.

    # Volume infill. The old ladder left a ~250-day dead zone between 250 and
    # 1,000 foods, and 40 workouts between 10 and 50, with nothing to show for
    # any of it.
    {"id": "foods_100",    "title": "100 foods logged", "line": "Triple digits.",                        "icon": "square.stack.3d.up",  "tier": "small", "rank": 25,  "metal": "silver",   "family": "nutrition",   "metric": "foods",           "target": 100},
    {"id": "foods_500",    "title": "500 foods logged", "line": "Five hundred. You've built a record.",  "icon": "square.stack.3d.up.fill", "tier": "small", "rank": 35, "metal": "gold",  "family": "nutrition",   "metric": "foods",           "target": 500},
    {"id": "workouts_25",  "title": "25 workouts",      "line": "Twenty-five in the book.",              "icon": "figure.strengthtraining.traditional", "tier": "small", "rank": 27, "metal": "silver", "family": "training", "metric": "workouts",     "target": 25},

    # Consistency — rhythm, not just length.
    {"id": "weekend_4",    "title": "Weekend Warrior",  "line": "Saturdays and Sundays too. That's where most people quit.", "icon": "calendar.badge.checkmark", "tier": "small", "rank": 45, "metal": "silver", "family": "consistency", "metric": "weekend_pairs",  "target": 4},
    {"id": "perfect_week", "title": "Seven for Seven",  "line": "A whole calendar week, no gaps.",       "icon": "calendar",            "tier": "big",   "rank": 65,  "metal": "gold",     "family": "consistency", "metric": "perfect_weeks",   "target": 1},
    {"id": "mondays_8",    "title": "Monday Person",    "line": "Mondays don't get a vote.",             "icon": "sunrise",             "tier": "small", "rank": 44,  "metal": "silver",   "family": "consistency", "metric": "mondays",         "target": 8},
    # HIDDEN: showing "come back after a week away" as a target would be
    # telling people to lapse in order to collect it.
    {"id": "comeback",     "title": "The Comeback",     "line": "A week off didn't end it. You came back.", "icon": "arrow.uturn.up",   "tier": "big",   "rank": 75,  "metal": "gold",     "family": "consistency", "metric": "comebacks",       "target": 1, "hidden": True},
    {"id": "streak_150",   "title": "150-day streak",   "line": "Five months unbroken.",                 "icon": "flame.fill",          "tier": "big",   "rank": 105, "metal": "platinum", "family": "consistency", "metric": "streak",          "target": 150},
    {"id": "streak_200",   "title": "200-day streak",   "line": "Two hundred days.",                     "icon": "flame.fill",          "tier": "big",   "rank": 110, "metal": "platinum", "family": "consistency", "metric": "streak",          "target": 200},
    {"id": "streak_365",   "title": "A full year",      "line": "A year. Not a phase.",                  "icon": "laurel.leading",      "tier": "big",   "rank": 120, "metal": "platinum", "family": "consistency", "metric": "streak",          "target": 365},

    # Training — the family was three pure counters.
    {"id": "training_7",   "title": "Seven Sessions",   "line": "Seven training days running.",          "icon": "figure.run",          "tier": "big",   "rank": 55,  "metal": "gold",     "family": "training",    "metric": "training_streak", "target": 7},
    {"id": "iron_weekend", "title": "Iron Weekend",     "line": "Trained when nobody was watching.",     "icon": "dumbbell.fill",       "tier": "small", "rank": 16,  "metal": "bronze",   "family": "training",    "metric": "iron_weekends",   "target": 4},
    {"id": "double_day",   "title": "Double Day",       "line": "Lifted and ran. Same day, five times over.", "icon": "arrow.triangle.2.circlepath", "tier": "small", "rank": 18, "metal": "bronze", "family": "training", "metric": "double_days",  "target": 5},

    # Nutrition — how it was logged, not just how much.
    {"id": "photos_25",    "title": "Shutterbug",       "line": "Twenty-five meals, photographed.",      "icon": "camera.fill",         "tier": "small", "rank": 23,  "metal": "silver",   "family": "nutrition",   "metric": "photos",          "target": 25},
    {"id": "voice_20",     "title": "Talk to Me",       "line": "Twenty logged out loud.",               "icon": "waveform",            "tier": "small", "rank": 17,  "metal": "bronze",   "family": "nutrition",   "metric": "voice_logs",      "target": 20},
    {"id": "water_10",     "title": "Water Discipline", "line": "Hydration is the boring one nobody does.", "icon": "drop.fill",        "tier": "small", "rank": 19,  "metal": "bronze",   "family": "nutrition",   "metric": "water_days",      "target": 10},

    # Precision — the family that had exactly one badge.
    {"id": "protein_30",   "title": "Protein × 30",     "line": "Thirty days on target. That changes what you're made of.", "icon": "target", "tier": "small", "rank": 42, "metal": "gold", "family": "precision", "metric": "protein_days",    "target": 30},
    {"id": "bullseye_5",   "title": "Bullseye",         "line": "Five days inside a hundred calories. That's precision.", "icon": "scope",  "tier": "small", "rank": 33, "metal": "silver", "family": "precision", "metric": "bullseye_days",   "target": 5},
    # HIDDEN: rewarding a correction encourages accuracy over convenience, but
    # advertising it invites fiddling with entries to farm it.
    {"id": "correction_1", "title": "Set the Record Straight", "line": "You corrected it instead of letting it slide.", "icon": "pencil.and.outline", "tier": "small", "rank": 11, "metal": "bronze", "family": "precision", "metric": "corrections", "target": 1, "hidden": True},
]

_BY_ID = {b["id"]: b for b in BADGES}

#: Which data source computes each metric. Providers are the unit of COST —
#: one fetch or one query each, run at most once, and only when a badge that
#: is still unearned actually needs them. A user's log turns therefore get
#: CHEAPER as they collect badges, instead of paying for the whole registry.
_PROVIDER_OF: dict[str, str] = {
    # entry COUNTs — indexed, no rows materialised
    "foods": "counts", "photos": "counts", "workouts": "counts",
    "voice_logs": "counts",
    # DailyLog COUNTs with a predicate — also indexed
    "protein_days": "days", "water_days": "days", "bullseye_days": "days",
    # one 90-day fetch of DailyLog rows, shared by everything derived from the
    # day sequence (streaks included — this is the fetch that already happened)
    "streak": "window", "training_streak": "window",
    "weekend_pairs": "window", "perfect_weeks": "window", "mondays": "window",
    "comebacks": "window", "iron_weekends": "window", "double_days": "window",
    # a COUNT on the corrections ledger
    "corrections": "corrections",
}

#: A day needs this much water to count. There is no per-user water target on
#: UserPreferences (unlike calories/protein/carbs/fats), so this is a flat
#: rule-of-thumb rather than a personalised one.
WATER_DAY_ML = 2000

#: How close to the calorie target counts as a bullseye.
BULLSEYE_KCAL = 100

_STREAK_IDS = {b["id"]: b["target"] for b in BADGES if b["metric"] == "streak"}

# How many unearned badges carry a `next_up` position — the shelf the client
# renders as "what to shoot for". Three is enough to give the card a row
# without turning the wall into a to-do list.
NEXT_UP_COUNT = 3

_WIRE_KEYS = ("id", "title", "line", "icon", "tier", "metal", "family")

#: metric → how you earn it, as an instruction. DERIVED from the badge's own
#: target rather than written per badge, so retuning a threshold can't leave a
#: stale sentence behind. `{n}` is the target; the second form is used when the
#: target is 1, because "1 weeks with all seven days logged" reads like a bug.
_HOW: dict[str, tuple[str, Optional[str]]] = {
    "foods":           ("Log {n} foods.", "Log your first food."),
    "photos":          ("Log {n} meals from a photo.", "Log a meal from a photo."),
    "workouts":        ("Log {n} workouts.", "Log your first workout."),
    "voice_logs":      ("Log {n} foods with your voice.", "Log a food with your voice."),
    "protein_days":    ("Hit your protein target on {n} days.", None),
    "water_days":      ("Pass 2,000ml of water on {n} days.", None),
    "bullseye_days":   ("Land within 100 calories of your target on {n} days.", None),
    "streak":          ("Log something {n} days in a row.", None),
    "training_streak": ("Train {n} days in a row.", None),
    "weekend_pairs":   ("Log both days of {n} weekends.", "Log a full weekend."),
    "perfect_weeks":   ("Log all seven days of {n} weeks.", "Log all seven days of one week."),
    "mondays":         ("Log {n} Mondays.", None),
    "comebacks":       ("Come back after a week away.", "Come back after a week away."),
    "iron_weekends":   ("Train on both days of {n} weekends.", "Train a full weekend."),
    "double_days":     ("Lift and do cardio on the same day, {n} times.", "Lift and do cardio on the same day."),
    "corrections":     ("Correct {n} logs that weren't right.", "Correct a log that wasn't right."),
}


def _how(badge: dict) -> str:
    """The plain requirement, for the wall's expanded detail."""
    plural, singular = _HOW.get(badge["metric"], ("{n}", None))
    if badge["target"] == 1 and singular:
        return singular
    return plural.format(n=f"{badge['target']:,}")


def _wire(badge: dict) -> dict:
    """The client-facing shape for one badge (no rank — that's server policy).

    `hidden` rides along so the client can render an unnamed silhouette: some
    badges must not be shown as targets, because naming them would tell the
    user to do the wrong thing to collect them (see `comeback`).

    `how` says what actually earns it. Until now the wall showed a title, an
    icon and a number and nothing else — `line` has been on the wire since v1
    and no surface but the celebration ever displayed it.
    """
    out = {k: badge[k] for k in _WIRE_KEYS}
    out["hidden"] = bool(badge.get("hidden"))
    out["how"] = _how(badge)
    return out


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


async def _voice_log_count(db: AsyncSession, uid: int) -> int:
    q = (select(func.count(FoodEntry.id))
         .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
         .where(DailyLog.user_id == uid, FoodEntry.source_type == "voice"))
    return int((await db.execute(q)).scalar() or 0)


async def _water_day_count(db: AsyncSession, uid: int) -> int:
    q = (select(func.count(DailyLog.id))
         .where(DailyLog.user_id == uid,
                DailyLog.total_water_ml >= WATER_DAY_ML))
    return int((await db.execute(q)).scalar() or 0)


async def _bullseye_day_count(db: AsyncSession, user: User) -> int:
    """Days landing within BULLSEYE_KCAL of the calorie target.

    Zero-calorie days are excluded explicitly: without that, every untouched
    day in the table would count as a bullseye for anyone whose target happens
    to be under 100.
    """
    # Query the column, don't touch `user.preferences` — it's a lazy
    # relationship, and reading it here raises MissingGreenlet under async
    # SQLAlchemy whenever the caller didn't already eager-load it.
    from db.models import UserPreferences
    ct = (await db.execute(
        select(UserPreferences.calorie_target)
        .where(UserPreferences.user_id == user.id))).scalar()
    if not ct:
        return 0
    q = (select(func.count(DailyLog.id))
         .where(DailyLog.user_id == user.id,
                DailyLog.total_calories > 0,
                func.abs(DailyLog.total_calories - ct) <= BULLSEYE_KCAL))
    return int((await db.execute(q)).scalar() or 0)


async def _correction_count(db: AsyncSession, uid: int) -> int:
    """Times the user corrected a logged entry. Rewards accuracy over
    convenience — the one behaviour nothing else in the app acknowledges."""
    from db.models import FoodCorrection
    q = select(func.count(FoodCorrection.id)).where(FoodCorrection.user_id == uid)
    return int((await db.execute(q)).scalar() or 0)


async def _best_streak(db: AsyncSession, user: User) -> int:
    """Best logging chain inside the streak engine's 90-day window — badges
    award in real time as chains grow, so the window never misses a live one.

    Uses `get_recent_log_days`, not `get_recent_logs`: the walk reads three
    columns off the parent rows, while the latter's selectinload would drag
    every food and exercise entry from the last quarter along with them.
    """
    from core.streaks import compute_streaks
    from db.queries import _user_today, get_recent_log_days
    logs = await get_recent_log_days(db, user.id, days=90)
    streaks = compute_streaks(logs, _user_today(user.timezone or "UTC"))
    chain = streaks.get("logging") or {}
    return max(int(chain.get("current") or 0), int(chain.get("best") or 0))


def _window_metrics(logs: list, today) -> dict:
    """Everything derivable from the sequence of days, in one pass.

    `DailyLog.date` is ALREADY the user's local logging day (db.queries writes
    it that way), so weekday arithmetic here needs no timezone conversion —
    which is what makes the rhythm badges cheap rather than a per-entry fetch.

    Future-dated rows are dropped for the same reason the streak engine drops
    them: old LLM date bugs left rows ahead of today.
    """
    from core.streaks import compute_streaks

    rows = [r for r in logs if r.date <= today]
    logged = {r.date for r in rows
              if (r.total_calories or 0) > 0 or bool(r.workout_completed)}
    trained = {r.date for r in rows if bool(r.workout_completed)}
    did_cardio = {r.date for r in rows if bool(getattr(r, "cardio_completed", False))}

    chains = compute_streaks(rows, today)
    logging_chain = chains.get("logging") or {}
    training_chain = chains.get("training") or {}

    # Weekend pairs: Saturday AND Sunday of the same weekend. Keyed off the
    # Saturday so a Sunday-only weekend can't double-count.
    weekend_pairs = sum(
        1 for d in logged
        if d.weekday() == 5 and (d + timedelta(days=1)) in logged)
    iron_weekends = sum(
        1 for d in trained
        if d.weekday() == 5 and (d + timedelta(days=1)) in trained)

    # Perfect weeks: all 7 days of an ISO week. Only weeks fully inside the
    # window can qualify, so a partially-fetched edge week never counts.
    by_week: dict = {}
    for d in logged:
        by_week.setdefault(d.isocalendar()[:2], set()).add(d)
    perfect_weeks = sum(1 for days in by_week.values() if len(days) == 7)

    # Returning after a real absence. A gap of ≥7 days between consecutive
    # logged days, with the return inside the window.
    ordered = sorted(logged)
    comebacks = sum(1 for a, b in zip(ordered, ordered[1:])
                    if (b - a).days >= 8)

    return {
        "streak": max(int(logging_chain.get("current") or 0),
                      int(logging_chain.get("best") or 0)),
        "training_streak": max(int(training_chain.get("current") or 0),
                               int(training_chain.get("best") or 0)),
        "weekend_pairs": weekend_pairs,
        "iron_weekends": iron_weekends,
        "perfect_weeks": perfect_weeks,
        "mondays": sum(1 for d in logged if d.weekday() == 0),
        "comebacks": comebacks,
        "double_days": len(trained & did_cardio),
    }


#: Counters for a user with nothing left to chase. Earned badges read full
#: from their Achievement rows, not from these, so a zeroed state is correct
#: (not merely safe) whenever every badge is already minted.
ZERO_STATE: dict = {m: 0 for m in _PROVIDER_OF}


async def _provider_counts(db: AsyncSession, user: User) -> dict:
    return {
        "foods":      await _food_count(db, user.id),
        "photos":     await _food_count(db, user.id, photos_only=True),
        "workouts":   await _workout_count(db, user.id),
        "voice_logs": await _voice_log_count(db, user.id),
    }


async def _provider_days(db: AsyncSession, user: User) -> dict:
    return {
        "protein_days":  await _protein_day_count(db, user),
        "water_days":    await _water_day_count(db, user.id),
        "bullseye_days": await _bullseye_day_count(db, user),
    }


async def _provider_window(db: AsyncSession, user: User) -> dict:
    """The one expensive provider: a 90-day fetch of DailyLog rows.

    Everything rhythm-shaped comes out of it — streaks, weekend pairs, perfect
    weeks, comebacks — so the cost is paid once no matter how many of those
    badges are open.
    """
    from db.queries import _user_today, get_recent_log_days
    logs = await get_recent_log_days(db, user.id, days=90)
    return _window_metrics(logs, _user_today(user.timezone or "UTC"))


async def _provider_corrections(db: AsyncSession, user: User) -> dict:
    return {"corrections": await _correction_count(db, user.id)}


_PROVIDERS = {
    "counts": _provider_counts,
    "days": _provider_days,
    "window": _provider_window,
    "corrections": _provider_corrections,
}


async def compute_state(db: AsyncSession, user: User, *,
                        metrics: Optional[set] = None) -> dict:
    """The counters the registry reads — running only the providers needed.

    `metrics` is the set still worth computing (i.e. metrics of UNEARNED
    badges). Providers whose metrics are all already earned never run, which
    is what stops a 33-badge registry from costing 33 queries a turn: as a
    user collects badges their turns get cheaper, and the expensive 90-day
    window stops being fetched at all once the rhythm badges are done.

    `None` means everything — used by callers that want a full snapshot.
    """
    wanted = set(_PROVIDER_OF) if metrics is None else set(metrics)
    needed = {_PROVIDER_OF[m] for m in wanted if m in _PROVIDER_OF}

    state = dict(ZERO_STATE)
    for name in ("counts", "days", "window", "corrections"):
        if name in needed:
            state.update(await _PROVIDERS[name](db, user))
    return state


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
        # Only the metrics an unearned badge still reads — so the providers
        # behind already-collected badges (and the 90-day window in
        # particular) stop being paid for.
        state = await compute_state(db, user,
                                    metrics={b["metric"] for b in unearned})
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
    # Hidden badges are never queued — "next up: come back after a week away"
    # would be instructing the user to lapse.
    by_id = {b["id"]: b for b in BADGES}
    queue = sorted(
        (w for w in wall
         if w["earned_at"] is None and w["progress"]["pct"] < 1.0
         and not w["hidden"]),
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
        state = await compute_state(db, user,
                                    metrics={b["metric"] for b in unearned})
        await check_achievements(db, user, effect_taken=True, state=state)
    except Exception:
        logger.warning("achievement backfill on wall read failed", exc_info=True)
    return await badge_wall(db, user, state=state)
