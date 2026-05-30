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
            # [#id] lets the LLM reference entries for update_exercise_entry / delete_exercise_entry
            if e.sets and e.reps:
                w = f" @ {round(e.weight * 2.20462, 1)}lb" if e.weight else ""
                lines.append(f"  • [#{e.id}] {e.exercise_name}: {e.sets}×{e.reps}{w}")
            elif e.duration_minutes:
                lines.append(f"  • [#{e.id}] {e.exercise_name}: {e.duration_minutes:.0f} min")
            else:
                lines.append(f"  • [#{e.id}] {e.exercise_name}")
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
    for l in closed[:7]:
        line = (
            f"{l.date}: {l.total_calories:.0f}cal  {l.total_protein:.0f}gP  "
            f"workout={'✓' if l.workout_completed else '✗'}"
        )
        lines.append(line)
    return "\n".join(lines)


def fmt_exercise_history(logs: List[DailyLog]) -> str:
    """Per-session exercise history with weights/reps for progressive overload context."""
    sessions = []
    for l in logs:
        if not l.exercise_entries:
            continue
        entries = []
        for e in l.exercise_entries:
            if e.sets and e.reps:
                w = f" @ {e.weight * 2.20462:.0f}lb" if e.weight else ""
                entries.append(f"    {e.exercise_name}: {e.sets}×{e.reps}{w}")
            elif e.duration_minutes:
                ct = f" ({e.cardio_type})" if e.cardio_type else ""
                entries.append(f"    {e.exercise_name}: {e.duration_minutes:.0f}min{ct}")
            else:
                entries.append(f"    {e.exercise_name}")
        if entries:
            sessions.append(f"  {l.date}:\n" + "\n".join(entries))
    if not sessions:
        return "No exercise history yet."
    return "\n".join(sessions[:6])


def fmt_weight_trend(weights: List[BodyMetric]) -> str:
    if not weights:
        return ""
    pts = [f"{w.weight_kg:.1f}kg ({w.timestamp.strftime('%m/%d')})" for w in weights[:5]]
    return "Weight trend: " + " → ".join(reversed(pts))


def fmt_weight_progress(weights: List[BodyMetric], user: User) -> str:
    """Extended weight trend for progress_timeline skill — up to 8 weeks."""
    if not weights:
        return ""
    if len(weights) < 2:
        return "WEIGHT PROGRESS: only 1 entry — need more weigh-ins for trend"

    sorted_w = sorted(weights, key=lambda w: w.timestamp)
    earliest = sorted_w[0]
    latest = sorted_w[-1]
    delta = latest.weight_kg - earliest.weight_kg
    days_span = max((latest.timestamp - earliest.timestamp).days, 1)
    weeks = days_span / 7
    rate_per_week = delta / weeks if weeks > 0 else 0

    # Recent 5 data points
    recent_pts = [
        f"{w.weight_kg:.1f}kg ({w.timestamp.strftime('%m/%d')})"
        for w in sorted_w[-5:]
    ]
    trend_str = " → ".join(recent_pts)

    goal_str = ""
    if user.goal_weight_kg:
        to_go = latest.weight_kg - user.goal_weight_kg
        goal_str = f"  |  Goal {user.goal_weight_kg:.1f}kg ({to_go:+.1f}kg to go)"

    return (
        f"WEIGHT PROGRESS ({len(weights)} entries, {weeks:.1f} weeks): "
        f"{earliest.weight_kg:.1f}kg → {latest.weight_kg:.1f}kg "
        f"({delta:+.2f}kg total, {rate_per_week:+.2f}kg/wk)\n"
        f"  Recent: {trend_str}"
        f"{goal_str}"
    )


def fmt_strength_prs(logs: List[DailyLog]) -> str:
    """Estimated 1RMs from best recent sets using the Epley formula.
    Injected into context so the strength_programming skill has real data."""
    if not logs:
        return ""

    best: dict = {}  # exercise_name -> (weight_kg, reps, e1rm, date)

    for log in logs:
        for e in (log.exercise_entries or []):
            if not (e.weight and e.reps and e.sets):
                continue
            # e.reps may be "5" or "5,5,4" — use first value
            try:
                reps = int(str(e.reps).split(",")[0].strip())
            except (ValueError, AttributeError):
                continue
            if reps < 1 or reps > 20:
                continue  # Epley unreliable outside this range
            # Epley: 1RM = weight × (1 + reps/30)
            e1rm = e.weight * (1.0 + reps / 30.0)
            name = (e.exercise_name or "").strip()
            if not name:
                continue
            if name not in best or e1rm > best[name][2]:
                best[name] = (e.weight, reps, e1rm, log.date)

    if not best:
        return ""

    # Sort by e1rm descending, show top 7 lifts
    top = sorted(best.items(), key=lambda x: x[1][2], reverse=True)[:7]
    lines = ["ESTIMATED 1RMs (Epley, best sets last 28 days):"]
    for name, (w_kg, reps, e1rm, d) in top:
        w_lbs = w_kg * 2.20462
        e1rm_lbs = e1rm * 2.20462
        lines.append(
            f"  {name}: ~{e1rm_lbs:.0f}lb / ~{e1rm:.1f}kg "
            f"(from {w_lbs:.0f}lb × {reps}reps on {d})"
        )

    return "\n".join(lines)


def fmt_food_history(logs: List[DailyLog]) -> str:
    """
    Builds a deduped lookup of previously logged foods from the last 90 days.
    Most recent entry for each food name wins. Sorted by most recently logged.
    Injected as [FOOD HISTORY] so Arnie can re-use macros without asking.
    """
    seen: dict = {}  # normalized_name -> (display_name, qty, cal, P, C, F, date)

    for log in sorted(logs, key=lambda l: l.date):  # oldest first → newest overwrites
        for f in (log.food_entries or []):
            name = (f.parsed_food_name or "").strip()
            if not name:
                continue
            norm = name.lower()
            seen[norm] = (
                name,
                f.quantity or "",
                f.calories or 0,
                f.protein or 0,
                f.carbs or 0,
                f.fats or 0,
                log.date,
            )

    if not seen:
        return ""

    # Sort by most recently logged
    entries = sorted(seen.values(), key=lambda x: x[6], reverse=True)[:30]
    lines = ["FOOD HISTORY (previously logged — use these macros when user references a past food):"]
    for name, qty, cal, pro, carb, fat, d in entries:
        qty_str = f" ({qty})" if qty else ""
        lines.append(
            f"  {name}{qty_str} — {cal:.0f} cal | {pro:.0f}P | {carb:.0f}C | {fat:.0f}F  [logged {d}]"
        )
    return "\n".join(lines)


def fmt_weekly_breakdown(logs: List[DailyLog], prefs: Optional[UserPreferences]) -> str:
    """Per-week nutrition and workout averages for the last 4 weeks.
    Used by weekly_summary and progress_timeline skills."""
    if not logs:
        return ""

    today_date = date.today()
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None
    lines = []

    for week_offset in range(4):
        week_end = today_date - timedelta(days=week_offset * 7)
        week_start = week_end - timedelta(days=6)
        week_logs = [
            l for l in logs
            if week_start <= l.date <= week_end and l.status == "closed"
        ]
        if not week_logs:
            continue

        n = len(week_logs)
        avg_cal = sum(l.total_calories for l in week_logs) / n
        avg_pro = sum(l.total_protein for l in week_logs) / n
        workouts = sum(1 for l in week_logs if l.workout_completed)

        cal_str = f"{avg_cal:.0f}"
        if cal_t:
            cal_str += f"/{cal_t} ({avg_cal - cal_t:+.0f})"

        pro_str = f"{avg_pro:.0f}g"
        if pro_t:
            pro_str += f"/{pro_t}g"

        label = "this week" if week_offset == 0 else f"{week_start}"
        lines.append(
            f"  {label}: cal {cal_str}  protein {pro_str}  "
            f"workouts {workouts}/{n}d"
        )

    if not lines:
        return ""
    return "WEEKLY BREAKDOWN:\n" + "\n".join(lines)


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
    from core.coaching_state import compute_coaching_state

    recent_logs = await get_recent_logs(db, user.id, days=90)
    recent_weights = await get_recent_weights(db, user.id, days=56)
    recent_health = await get_recent_health_snapshots(db, user.id, days=7)

    # Long-term context: the adaptive Profile Matrix is primary; fall back to the
    # legacy freeform memory only if no profile exists yet.
    from memory.profile_manager import read_profile
    profile = await read_profile(user.telegram_id)
    memory = profile if profile else await read_memory(user.telegram_id)

    prefs = user.preferences
    pace = pacing_note(today_log, prefs, user.timezone or "UTC")
    adherence = adherence_insights(recent_logs, prefs)
    progress = goal_progress(user)
    health_str = fmt_health(recent_health)
    weight_progress = fmt_weight_progress(recent_weights, user)
    weekly_breakdown = fmt_weekly_breakdown(recent_logs, prefs)
    strength_prs = fmt_strength_prs(recent_logs)
    food_history = fmt_food_history(recent_logs)

    # Compute structured coaching state from wearable data
    coaching_state = compute_coaching_state(recent_health, recent_logs, user)
    coaching_state_str = coaching_state.to_context_string()

    # Momentum score + discovery layer (projection / pattern / records)
    from core.momentum import compute_momentum, fmt_momentum
    from core.insights_engine import (
        weight_projection, discover_pattern, personal_records, fmt_records,
    )
    momentum_str = fmt_momentum(compute_momentum(recent_logs, prefs, recent_weights, user))
    projection = weight_projection(recent_weights, user)
    pattern = discover_pattern(recent_logs, prefs)
    records_str = fmt_records(personal_records(recent_logs, recent_weights))
    discovery_lines = []
    if projection:
        discovery_lines.append(f"[PROJECTION] {projection}")
    if pattern:
        discovery_lines.append(f"[PATTERN — surface this if it fits naturally] {pattern}")

    # Detect workout mode: exercises already logged today
    in_workout = bool(today_log and today_log.exercise_entries)

    sections = [
        "=== PROFILE ===",
        fmt_profile(user, prefs),
        (progress if progress else ""),
        "",
        # Coaching state goes at top so every skill sees it first
        (coaching_state_str if coaching_state_str else ""),
        "",
        "=== TODAY ===",
        fmt_log(today_log),
        (f"[PACING]\n{pace}" if pace else ""),
        (f"[WEARABLE]\n{health_str}" if health_str else ""),
        ("" if not in_workout else "[WORKOUT MODE: ACTIVE]"),
        "",
        "=== MOMENTUM & DISCOVERY ===",
        (momentum_str if momentum_str else ""),
        ("\n".join(discovery_lines) if discovery_lines else ""),
        (records_str if records_str else ""),
        "",
        "=== INSIGHTS ===",
        (adherence if adherence else "No adherence data yet."),
        "",
        "=== RECENT HISTORY ===",
        fmt_history(recent_logs),
        (weight_progress if weight_progress else fmt_weight_trend(recent_weights)),
        (weekly_breakdown if weekly_breakdown else ""),
        "",
        "=== FOOD HISTORY ===",
        (food_history if food_history else "No food history yet."),
        "",
        "=== EXERCISE HISTORY ===",
        fmt_exercise_history(recent_logs),
        (strength_prs if strength_prs else ""),
        "",
        "=== USER PROFILE ===",
        (memory[:3200] if memory else "No profile yet — still learning this user."),
    ]
    return "\n".join(s for s in sections if s is not None)
