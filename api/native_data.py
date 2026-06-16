"""
Focused data fetchers for the native /api/v1 dashboard endpoints.

Each /api/v1 tab needs only a slice of the data, but the legacy
`_build_stats_for_user` fetches EVERYTHING (60d history, 90d weights, health,
Whoop tokens, attributes, analytics, streak, reminder gates) on every call. The
Today tab loading all of that just to show today's macros is the over-fetch.

These fetchers pull ONLY what each endpoint needs and produce the SAME shaped
pieces (`targets`, `day`, `history`, `weights`) the endpoints already consume — so
the wire output is byte-identical (verified by golden diff). The prod-shared
`_build_stats_for_user` (used by the legacy HTML dashboard / insights) is untouched.
"""
from __future__ import annotations

from datetime import datetime, date as _date, timedelta

from db.queries import (
    get_or_create_today_log,
    get_recent_logs,
    get_recent_weights,
    get_recent_health_snapshots,
    _user_today,
)


def _targets(user) -> dict:
    prefs = user.preferences
    return {
        "calories": prefs.calorie_target if prefs else None,
        "protein": prefs.protein_target if prefs else None,
        "carbs": prefs.carb_target if prefs else None,
        "fats": prefs.fat_target if prefs else None,
    }


def _log_to_day(log) -> dict | None:
    """Shape a DailyLog into the `day` dict. Mirrors _build_stats_for_user._log_to_day."""
    if not log:
        return None
    return {
        "date": str(log.date),
        "calories": round(log.total_calories or 0),
        "protein": round(log.total_protein or 0),
        "carbs": round(log.total_carbs or 0),
        "fats": round(log.total_fats or 0),
        "water_ml": round(log.total_water_ml or 0),
        "workout_completed": log.workout_completed,
        "cardio_completed": log.cardio_completed,
        "food_entries": [
            {
                "id": e.id, "name": e.parsed_food_name or "?",
                "quantity": e.quantity or "",
                "calories": round(e.calories or 0), "protein": round(e.protein or 0),
                "carbs": round(e.carbs or 0), "fats": round(e.fats or 0),
                "estimated": bool(e.estimated_flag),
                "from_photo": bool(getattr(e, "from_photo", False)),
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in sorted(
                (log.food_entries or []),
                key=lambda e: (e.timestamp or datetime.min, e.id or 0),
            )
        ],
        "exercise_entries": [
            {
                "id": e.id, "name": e.exercise_name or "?",
                "sets": e.sets, "reps": e.reps,
                "weight": round(e.weight * 2.20462, 1) if e.weight else None,
                "duration_minutes": e.duration_minutes,
                "is_cardio": bool(e.cardio_type),
                "cardio_type": e.cardio_type,
            }
            for e in (log.exercise_entries or [])
        ],
    }


async def day_data(db, user, target_date=None) -> dict:
    """Log + targets + weight record for `target_date` (defaults to today).
    Past dates are fetched read-only — if no log exists for that date the
    `day` dict is None and the client renders an empty state. Today is
    auto-created so live coaching always has a log to write into. The
    `weight` block is the same across dates (user-scoped, not day-scoped) —
    we send it on every Today fetch so the screen has the recent trend at
    hand without a second round-trip."""
    from db.queries import get_log_by_date, get_recent_weights
    if target_date is None or target_date == _user_today_date(user):
        log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
    else:
        log = await get_log_by_date(db, user.id, target_date)

    weights = await get_recent_weights(db, user.id, days=30)
    weight_block = _weight_block(weights, user)
    return {"targets": _targets(user), "day": _log_to_day(log), "weight": weight_block}


def _weight_block(weights, user) -> dict | None:
    """Shape the weight record for the Today screen: latest reading, the
    user's goal, and recent readings (most-recent-first, capped at 14) for a
    sparkline. Returns None when nothing's ever been logged."""
    if not weights:
        return None
    sorted_weights = sorted(weights, key=lambda w: w.timestamp)
    recent = [
        {
            "date": w.timestamp.strftime("%Y-%m-%d"),
            "kg":   round(w.weight_kg, 1),
            "lbs":  round(w.weight_kg * 2.20462, 1),
        }
        for w in sorted_weights[-14:]
    ]
    latest = recent[-1] if recent else None
    goal = None
    if getattr(user, "goal_weight_kg", None) is not None:
        goal = {
            "kg":  round(user.goal_weight_kg, 1),
            "lbs": round(user.goal_weight_kg * 2.20462, 1),
        }
    return {"latest": latest, "goal": goal, "recent": recent}


def _user_today_date(user):
    """The user's local 'today' as a date. Mirrors `_user_today` in db.queries."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(user.timezone or "UTC")
    except Exception:
        from datetime import timezone
        tz = timezone.utc
    return datetime.now(tz).date()


async def week_data(db, user) -> dict:
    """Targets + recent daily history + recent weights — enough for the 7-day window
    and weight trend, without health/Whoop/attributes."""
    history = await get_recent_logs(db, user.id, days=10)
    weights = await get_recent_weights(db, user.id, days=30)
    hist_data = [
        {
            "date": str(log.date),
            "calories": round(log.total_calories or 0),
            "protein": round(log.total_protein or 0),
            "carbs": round(log.total_carbs or 0),
            "fats": round(log.total_fats or 0),
            "workout": log.workout_completed,
        }
        for log in sorted(history, key=lambda l: l.date)
    ]
    weight_data = [
        {
            "date": w.timestamp.strftime("%Y-%m-%d"),
            "kg": round(w.weight_kg, 1),
            "lbs": round(w.weight_kg * 2.20462, 1),
        }
        for w in sorted(weights, key=lambda w: w.timestamp)
    ]
    return {"targets": _targets(user), "history": hist_data, "weights": weight_data}


# ── Fitness + Profile (shared health/whoop/streak helpers) ───────────────────

async def _merged_health_snaps(db, user):
    """Health snapshots for the user, merged with any linked identities — mirrors
    the merge in _build_stats_for_user so output matches exactly."""
    from sqlalchemy import select
    from db.models import User as _U

    snaps = await get_recent_health_snapshots(db, user.id, days=14)
    linked = (await db.execute(select(_U).where(_U.linked_to_user_id == user.id))).scalars().all()
    if not snaps and linked:
        for lu in linked:
            linked_snaps = await get_recent_health_snapshots(db, lu.id, days=14)
            if linked_snaps:
                snaps = linked_snaps
                break
    elif linked:
        covered = {s.date for s in snaps}
        for lu in linked:
            for ls in await get_recent_health_snapshots(db, lu.id, days=14):
                if ls.date not in covered:
                    snaps.append(ls)
                    covered.add(ls.date)
    return snaps


async def _whoop_connected(db, user) -> bool:
    from sqlalchemy import select
    from db.models import User as _U
    if user.whoop_access_token or user.whoop_refresh_token:
        return True
    linked = (await db.execute(select(_U).where(_U.linked_to_user_id == user.id))).scalars().all()
    return any(u.whoop_access_token or u.whoop_refresh_token for u in linked)


def _shape_health(snaps) -> list:
    # Only the fields the fitness endpoint consumes (date/recovery/strain/sleep/hrv/rhr),
    # with the same rounding _build_stats_for_user applies.
    return [
        {
            "date": str(s.date),
            "recovery_score": s.recovery_score,
            "strain": s.strain,
            "sleep_hours": s.sleep_hours,
            "hrv": round(s.hrv) if s.hrv else None,
            "resting_hr": round(s.resting_hr) if s.resting_hr else None,
        }
        for s in snaps
    ]


def _height_ft(user) -> str:
    if not user.height_cm:
        return ""
    total_in = user.height_cm / 2.54
    return f"{int(total_in // 12)}'{int(total_in % 12)}\""


def _compute_streak(hist_rows: list, user) -> int:
    logged = {h["date"] for h in hist_rows if (h.get("calories") or 0) > 0 or h.get("workout")}
    if not logged:
        return 0
    try:
        cur = _date.fromisoformat(_user_today(user.timezone or "UTC").isoformat())
    except Exception:
        cur = _date.fromisoformat(max(logged))
    streak = 0
    while cur.isoformat() in logged:
        streak += 1
        cur = cur - timedelta(days=1)
    return streak


async def fitness_data(db, user) -> dict:
    """Health/readiness + training flags — no food/weights/attributes/analytics."""
    snaps = await _merged_health_snaps(db, user)
    history = await get_recent_logs(db, user.id, days=10)
    hist = [{"date": str(log.date), "workout": log.workout_completed}
            for log in sorted(history, key=lambda l: l.date)]
    return {
        "profile": {
            "whoop_connected": await _whoop_connected(db, user),
            "apple_health_connected": any(s.source == "apple_health" for s in snaps),
        },
        "health": _shape_health(snaps),
        "history": hist,
    }


async def profile_data(db, user) -> dict:
    """The profile dict the Profile endpoint consumes — no weights/attributes/analytics."""
    prefs = user.preferences
    history = await get_recent_logs(db, user.id, days=60)
    hist = [{"date": str(log.date), "calories": round(log.total_calories or 0),
             "workout": log.workout_completed}
            for log in sorted(history, key=lambda l: l.date)]
    snaps = await _merged_health_snaps(db, user)

    return {
        "profile": {
            "name": user.name or "User",
            "age": user.age,
            "sex": user.sex,
            "height_cm": user.height_cm,
            "height_ft": _height_ft(user),
            "current_weight_lbs": round(user.current_weight_kg * 2.20462, 1) if user.current_weight_kg else None,
            "goal_weight_lbs": round(user.goal_weight_kg * 2.20462, 1) if user.goal_weight_kg else None,
            "primary_goal": user.primary_goal,
            "training_experience": user.training_experience,
            "non_training_activity": user.non_training_activity,
            "dietary_preferences": user.dietary_preferences,
            "injuries": user.injuries,
            "coaching_style": prefs.coaching_style if prefs else None,
            "calorie_target": prefs.calorie_target if prefs else None,
            "protein_target": prefs.protein_target if prefs else None,
            "carb_target": prefs.carb_target if prefs else None,
            "fat_target": prefs.fat_target if prefs else None,
            "reminder_frequency": (prefs.reminder_frequency if prefs else None) or "moderate",
            "reminders_on": bool(prefs.proactive_messaging_enabled) if prefs else False,
            "food_logging_mode": (getattr(prefs, "food_logging_mode", None) or "moderate") if prefs else "moderate",
            "whoop_connected": await _whoop_connected(db, user),
            "apple_health_connected": any(s.source == "apple_health" for s in snaps),
            "streak_days": _compute_streak(hist, user),
        }
    }
