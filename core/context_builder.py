"""
Assembles the system-level context string injected into every Arnie prompt.
Keeps retrieval deterministic (pure SQL, no vectors).
"""
from typing import Optional, List
from datetime import datetime, date, timedelta

from db.models import User, DailyLog, UserPreferences, BodyMetric, HealthSnapshot
from db.queries import get_recent_logs, get_recent_weights, get_recent_health_snapshots
from memory.memory_manager import read_memory


def fmt_log(log: Optional[DailyLog]) -> str:
    if not log:
        return "No log started today."

    foods = ""
    if log.food_entries:
        lines = []
        for f in log.food_entries:
            cal = f.calories or 0
            pro = f.protein or 0
            carb = f.carbs or 0
            fat = f.fats or 0
            est = "~" if f.estimated_flag else ""
            # [#id] prefix lets the LLM reference entries for update_food_entry / delete_food_entry
            lines.append(
                f"  • [#{f.id}] {f.parsed_food_name or '?'} ({f.quantity or '?'}): "
                f"{est}{cal:.0f}cal  {pro:.0f}P  {carb:.0f}C  {fat:.0f}F"
            )
        foods = "\nFood:\n" + "\n".join(lines)

    exercises = ""
    if log.exercise_entries:
        lines = []
        for e in log.exercise_entries:
            if e.sets and e.reps:
                w = f" @ {e.weight}" if e.weight else ""
                lines.append(f"  • {e.exercise_name}: {e.sets}×{e.reps}{w}")
            elif e.duration_minutes:
                lines.append(f"  • {e.exercise_name}: {e.duration_minutes:.0f} min")
            else:
                lines.append(f"  • {e.exercise_name}")
        exercises = "\nExercise:\n" + "\n".join(lines)

    return (
        f"TODAY {log.date} [{log.status.upper()}]\n"
        f"Cals {log.total_calories:.0f}  |  "
        f"P {log.total_protein:.0f}g  C {log.total_carbs:.0f}g  F {log.total_fats:.0f}g  |  "
        f"Water {log.total_water_ml:.0f}ml\n"
        f"Workout {'✓' if log.workout_completed else '✗'}  "
        f"Cardio {'✓' if log.cardio_completed else '✗'}"
        f"{foods}{exercises}"
    )


def fmt_profile(user: User, prefs: Optional[UserPreferences]) -> str:
    lines = [
        f"{user.name or 'Unknown'}  age {user.age or '?'}  {user.sex or '?'}",
        f"Height {user.height_cm or '?'}cm  |  "
        f"Weight {user.current_weight_kg or '?'}kg  →  Goal {user.goal_weight_kg or '?'}kg",
        f"Primary goal: {user.primary_goal or 'not set'}  |  "
        f"Experience: {user.training_experience or 'not set'}",
        f"Diet: {user.dietary_preferences or 'none'}  |  "
        f"Injuries: {user.injuries or 'none'}",
    ]
    if prefs:
        lines += [
            f"Coaching: {prefs.coaching_style}  |  Accountability: {prefs.accountability_level}",
            f"Response length: {prefs.preferred_response_length}",
            f"Targets — calories: {prefs.calorie_target or 'not set'}  "
            f"protein: {prefs.protein_target or 'not set'}g",
        ]
    return "\n".join(lines)


def fmt_history(logs: List[DailyLog]) -> str:
    closed = [l for l in logs if l.status == "closed"]
    if not closed:
        return "No closed days yet."
    lines = []
    for l in closed[:5]:
        lines.append(
            f"{l.date}: {l.total_calories:.0f}cal  {l.total_protein:.0f}gP  "
            f"workout={'✓' if l.workout_completed else '✗'}"
        )
    return "\n".join(lines)


def fmt_weight_trend(weights: List[BodyMetric]) -> str:
    if not weights:
        return ""
    pts = [f"{w.weight_kg:.1f}kg ({w.timestamp.strftime('%m/%d')})" for w in weights[:5]]
    return "Weight trend: " + " → ".join(reversed(pts))


def pacing_note(log: Optional[DailyLog], prefs: Optional[UserPreferences],
                user_timezone: str = "UTC") -> str:
    """Calorie/protein remaining with time-of-day awareness."""
    if not log or not prefs:
        return ""
    import pytz
    parts = []
    if prefs.calorie_target:
        rem = prefs.calorie_target - log.total_calories
        pct = int(log.total_calories / prefs.calorie_target * 100)
        parts.append(f"{rem:+.0f} cal remaining ({pct}% used)")
    if prefs.protein_target:
        rem_p = prefs.protein_target - log.total_protein
        pct_p = int(log.total_protein / prefs.protein_target * 100)
        parts.append(f"{rem_p:+.0f}g protein ({pct_p}% hit)")

    # Add time-of-day context
    try:
        tz = pytz.timezone(user_timezone)
        now = datetime.now(tz)
        hour = now.hour
        if hour < 10:
            parts.append("early morning — most calories ahead")
        elif hour < 14:
            parts.append("midday — roughly half the eating day left")
        elif hour < 19:
            parts.append("afternoon — dinner and evening left")
        elif hour < 22:
            parts.append("evening — winding down, be precise now")
        else:
            parts.append("late — close to sleep window")
    except Exception:
        pass

    return "\n".join(parts) if parts else ""


def adherence_insights(logs: List[DailyLog], prefs: Optional[UserPreferences]) -> str:
    """Streak, weekly adherence, and trend callouts."""
    if not logs:
        return ""
    lines = []

    # Logging streak
    today_date = date.today()
    streak = 0
    check = today_date
    log_dates = {l.date for l in logs}
    while check in log_dates:
        streak += 1
        check -= timedelta(days=1)
    if streak > 1:
        lines.append(f"Logging streak: {streak} days in a row")

    # Weekly workout count
    week_ago = today_date - timedelta(days=7)
    workout_days = sum(1 for l in logs if l.date >= week_ago and l.workout_completed)
    if workout_days:
        lines.append(f"Workouts this week: {workout_days}")

    # Average daily calories this week (closed days only)
    closed = [l for l in logs if l.status == "closed" and l.date >= week_ago]
    if closed and prefs and prefs.calorie_target:
        avg_cal = sum(l.total_calories for l in closed) / len(closed)
        diff = avg_cal - prefs.calorie_target
        lines.append(f"Avg calories this week: {avg_cal:.0f} ({diff:+.0f} vs target)")

    return "\n".join(lines) if lines else ""


def goal_progress(user: User) -> str:
    """Percentage progress toward goal weight."""
    if not user.current_weight_kg or not user.goal_weight_kg:
        return ""
    # We need starting weight — use current as proxy if no history
    start = user.current_weight_kg  # will be overridden by caller with initial weight
    current = user.current_weight_kg
    goal = user.goal_weight_kg
    if abs(start - goal) < 0.01:
        return ""
    kg_to_go = abs(current - goal)
    lbs_to_go = kg_to_go * 2.20462
    return f"Goal: {current:.1f}kg → {goal:.1f}kg  ({lbs_to_go:.1f} lbs to go)"


def fmt_health(snaps: List[HealthSnapshot]) -> str:
    if not snaps:
        return ""
    latest = snaps[0]
    parts = []
    # Recovery + strain first (Whoop primary signals)
    if latest.recovery_score is not None:
        parts.append(f"Recovery {latest.recovery_score}%")
    if latest.strain is not None:
        parts.append(f"Strain {latest.strain:.1f}")
    if latest.sleep_hours is not None:
        sleep_str = f"Sleep {latest.sleep_hours:.1f}h"
        if latest.sleep_deep_hours or latest.sleep_rem_hours:
            extras = []
            if latest.sleep_deep_hours:
                extras.append(f"deep {latest.sleep_deep_hours:.1f}h")
            if latest.sleep_rem_hours:
                extras.append(f"REM {latest.sleep_rem_hours:.1f}h")
            sleep_str += f" ({', '.join(extras)})"
        parts.append(sleep_str)
    if latest.hrv is not None:
        parts.append(f"HRV {latest.hrv:.0f}ms")
    if latest.resting_hr is not None:
        parts.append(f"Resting HR {latest.resting_hr:.0f}bpm")
    if latest.steps is not None:
        parts.append(f"Steps {latest.steps:,}")
    if latest.active_calories is not None:
        parts.append(f"Active cal {latest.active_calories:.0f}")
    if latest.stand_hours is not None:
        parts.append(f"Stand {latest.stand_hours}h")
    if not parts:
        return ""
    src = "Whoop" if latest.source == "whoop" else "Apple Health"
    return f"{src} ({latest.date}): " + "  |  ".join(parts)


async def build_context(user: User, today_log: Optional[DailyLog], db) -> str:
    recent_logs = await get_recent_logs(db, user.id, days=14)
    recent_weights = await get_recent_weights(db, user.id, days=14)
    recent_health = await get_recent_health_snapshots(db, user.id, days=3)
    memory = await read_memory(user.telegram_id)

    prefs = user.preferences
    pace = pacing_note(today_log, prefs, user.timezone or "UTC")
    adherence = adherence_insights(recent_logs, prefs)
    progress = goal_progress(user)
    health_str = fmt_health(recent_health)

    sections = [
        "=== PROFILE ===",
        fmt_profile(user, prefs),
        (progress if progress else ""),
        "",
        "=== TODAY ===",
        fmt_log(today_log),
        (f"[PACING]\n{pace}" if pace else ""),
        (f"[WEARABLE]\n{health_str}" if health_str else ""),
        "",
        "=== INSIGHTS ===",
        (adherence if adherence else "No adherence data yet."),
        "",
        "=== RECENT HISTORY ===",
        fmt_history(recent_logs),
        fmt_weight_trend(recent_weights),
        "",
        "=== MEMORY ===",
        (memory[:1800] if memory else "No memory yet."),
    ]
    return "\n".join(s for s in sections if s is not None)
