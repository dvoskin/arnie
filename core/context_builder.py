"""
Assembles the system-level context string injected into every Arnie prompt.
Keeps retrieval deterministic (pure SQL, no vectors).
"""
from typing import Optional, List
from datetime import datetime, date, timedelta

from db.models import User, DailyLog, UserPreferences, BodyMetric, HealthSnapshot
from db.queries import get_recent_logs, get_recent_weights, get_recent_health_snapshots
from memory.memory_manager import read_memory


_CLARIFICATION_FRESHNESS = {
    "quick": 15,       # quick mode: fewer questions, shorter window — don't block flow
    "moderate": 30,    # default: standard 30-minute window
    "strict": 60,      # strict mode: user wants accuracy, questions stay live longer
}


def render_pending_clarification_block(
    pending_rows, now=None, freshness_minutes: int = 30, food_mode: str = None
) -> str:
    """Render the [PENDING CLARIFICATION] context block from a list of
    PendingQuestion rows. Filters to food_clarification kind, freshness window,
    unanswered. Pure + testable — no DB dependency. now= injectable for tests.

    freshness_minutes scales with food_logging_mode: quick=15, moderate=30, strict=60.
    Caps at 3 rows so the prompt stays lean even if the model accumulated many.
    Returns "" when nothing fresh — context_builder will skip the line entirely.
    """
    from datetime import datetime as _dt, timedelta as _td
    now = now or _dt.utcnow()
    if food_mode:
        freshness_minutes = _CLARIFICATION_FRESHNESS.get(
            food_mode.strip().lower(), freshness_minutes
        )
    cutoff = now - _td(minutes=freshness_minutes)

    fresh = [
        p for p in (pending_rows or [])
        if getattr(p, "kind", None) == "food_clarification"
        and getattr(p, "asked_at", None) is not None
        and p.asked_at >= cutoff
        and getattr(p, "answered_at", None) is None
    ]
    if not fresh:
        return ""
    # Newest-first so the [:3] cap surfaces the most recently asked questions —
    # the ones the user is most likely responding to. Stable secondary sort by
    # item_referenced so the order is deterministic when ties occur.
    fresh.sort(
        key=lambda p: (p.asked_at, getattr(p, "item_referenced", "") or ""),
        reverse=True,
    )

    lines = [
        "[PENDING CLARIFICATION] You asked these RECENTLY about foods. "
        "The user's current message MAY be answering you, or may be a NEW "
        "food unrelated to the question. DON'T re-ask either way. Then decide: "
        "IF this turn answers your question → log ALL the foods from that "
        "original turn (every item the user mentioned, not just the asked-about ones). "
        "IF this turn is a NEW food (not an answer) → log ONLY the new food and "
        "leave the pending question open for the user to answer later:"
    ]
    for p in fresh[:3]:
        age_min = max(0, int((now - p.asked_at).total_seconds() / 60))
        item = getattr(p, "item_referenced", None) or "the food"
        question = (p.question or "").strip()
        lines.append(f'  - {age_min}m ago about "{item}": you asked "{question}"')
    return "\n".join(lines)


def food_mode_directive(mode: Optional[str]) -> str:
    """Render the per-turn [FOOD LOGGING MODE] override for the user's food_logging_mode.

    Pure + tiny so it's unit-testable and the only place the override prose lives.
    "moderate" (or None / unknown) returns "" — the static FOOD_ACCURACY block in the
    system prompt is the baseline, and only quick/strict deviate from it. Mirrors the
    ACCURACY MODE section the system prompt points the model at.
    """
    m = (mode or "moderate").strip().lower()
    if m == "quick":
        return (
            "[FOOD LOGGING MODE: quick] Log food immediately on your best estimate. "
            "Do NOT ask the usual >120 cal clarifying question — only ask when the prep gap "
            "is extreme (>300 cal, e.g. grilled vs deep-fried). Favor flow over confirmation."
        )
    if m == "strict":
        return (
            "[FOOD LOGGING MODE: strict] Confirm cook method AND quantity before logging any "
            "ambiguous item, even when the swing is under 120 cal. Surface the uncertainty out "
            "loud rather than silently estimating. (Still skip the question if they said 'just log it'.)"
        )
    return ""  # moderate / unknown = static system prompt default


def _exercise_load_str(e) -> str:
    """The weight portion of a logged-exercise context line: a single '@ Xlb' for
    a uniform load, or per-set '@ a/b/clb' when the row carries a per-set `weights`
    CSV (a pyramid / drop set). Without this, mixed-load sets showed NO weight in
    [TODAY]/[EXERCISE HISTORY] and a recap couldn't recall them."""
    wcsv = str(getattr(e, "weights", "") or "").strip()
    if wcsv:
        lbs = []
        for t in wcsv.split(","):
            try:
                lbs.append(str(round(float(t.strip()) * 2.20462)))
            except (ValueError, TypeError):
                continue
        if lbs:
            return f" @ {lbs[0]}lb" if len(set(lbs)) == 1 else " @ " + "/".join(lbs) + "lb"
    if getattr(e, "weight", None):
        return f" @ {round(e.weight * 2.20462, 1)}lb"
    return ""


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
                w = _exercise_load_str(e)
                lines.append(f"  • [#{e.id}] {e.exercise_name}: {e.sets}×{e.reps}{w}")
            elif e.duration_minutes:
                lines.append(f"  • [#{e.id}] {e.exercise_name}: {e.duration_minutes:.0f} min")
            else:
                lines.append(f"  • [#{e.id}] {e.exercise_name}")
        exercises = "\nExercise:\n" + "\n".join(lines)

    return (
        f"TODAY {log.date}\n"
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
        # The user PICKED these in Settings — so they must actually shape every
        # reply, not sit as inert labels the model has to interpret. Render each as
        # an explicit behavioral directive keyed off the stored value.
        _style = {
            "strict": "Coaching style STRICT — direct and demanding; hold them to the plan, call out misses plainly, minimal cushioning.",
            "balanced": "Coaching style BALANCED — firm but warm; push when they slack, encourage when earned.",
            "supportive": "Coaching style SUPPORTIVE — encouraging and gentle; lead with what they did well, nudge softly, never harsh.",
        }.get((prefs.coaching_style or "balanced").strip().lower(),
              "Coaching style BALANCED — firm but warm.")
        _acct = {
            "low": "Accountability LOW — let them lead; don't chase missed logs or workouts.",
            "medium": "Accountability MEDIUM — note gaps and nudge once, but don't nag.",
            "high": "Accountability HIGH — actively hold them to it; surface skipped logs/workouts and ask about them.",
        }.get((prefs.accountability_level or "medium").strip().lower(),
              "Accountability MEDIUM — note gaps, don't nag.")
        _len = {
            "short": "Response length SHORT — 1-2 tight sentences, no preamble. Hard ceiling: never wall-of-text them.",
            "medium": "Response length MEDIUM — 2-4 sentences; one idea delivered well.",
            "long": "Response length LONG — fuller explanations welcome when they genuinely help.",
        }.get((prefs.preferred_response_length or "medium").strip().lower(),
              "Response length MEDIUM — 2-4 sentences.")
        lines += [
            "[COACHING PREFERENCES — the user set these; honor them every reply]",
            f"  {_style}",
            f"  {_acct}",
            f"  {_len}",
            f"Targets — calories: {prefs.calorie_target or 'not set'}  "
            f"protein: {prefs.protein_target or 'not set'}g  "
            f"carbs: {prefs.carb_target or 'not set'}g  "
            f"fat: {prefs.fat_target or 'not set'}g",
        ]
    return "\n".join(lines)


def fmt_history(logs: List[DailyLog]) -> str:
    # Past days only — today's totals are still moving until bedtime.
    today_d = date.today()
    past = [l for l in logs if l.date < today_d]
    if not past:
        return "No prior days logged yet."
    lines = []
    for l in past[:7]:
        line = (
            f"{l.date}: {l.total_calories:.0f}cal  {l.total_protein:.0f}gP  "
            f"workout={'✓' if l.workout_completed else '✗'}"
        )
        lines.append(line)
    return "\n".join(lines)


def fmt_recent_day_detail(logs: List[DailyLog], days: int = 3) -> str:
    """
    Lists every food entry from the last `days` PAST days (excluding today,
    which has its own [TODAY] block). Lets the model answer "what did I eat
    yesterday?" / "Sunday?" / "2 days ago?" directly from context, without
    promising to "pull that up" and going silent.

    Each entry: name + quantity + macros. Same shape the user sees on the
    dashboard. Capped at `days` days to keep the prompt lean.
    """
    today_d = date.today()
    past = sorted(
        [l for l in (logs or []) if l.date < today_d],
        key=lambda l: l.date,
        reverse=True,
    )[:days]
    if not past:
        return ""
    blocks = []
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for l in past:
        day_name = weekdays[l.date.weekday()]
        header = f"{l.date} ({day_name}):"
        if not l.food_entries:
            blocks.append(f"{header}\n  (no food logged that day)")
            continue
        lines = [header]
        for f in l.food_entries:
            cal = f.calories or 0
            pro = f.protein or 0
            qty = f"({f.quantity}) " if f.quantity else ""
            est = "~" if f.estimated_flag else ""
            lines.append(
                f"  • {f.parsed_food_name or '?'} {qty}— {est}{cal:.0f} cal, {pro:.0f}g protein"
            )
        lines.append(
            f"  total: {l.total_calories:.0f} cal, {l.total_protein:.0f}g protein"
        )
        blocks.append("\n".join(lines))
    return "[RECENT DAY DETAIL — per-entry food logs for the last few days]\n" + "\n\n".join(blocks)


def fmt_exercise_history(logs: List[DailyLog]) -> str:
    """Per-session exercise history with weights/reps for progressive overload context."""
    sessions = []
    for l in logs:
        if not l.exercise_entries:
            continue
        entries = []
        for e in l.exercise_entries:
            if e.sets and e.reps:
                w = _exercise_load_str(e)
                entries.append(f"    {e.exercise_name}: {e.sets}×{e.reps}{w}")
            elif e.duration_minutes:
                ct = f" ({e.cardio_type})" if e.cardio_type else ""
                entries.append(f"    {e.exercise_name}: {e.duration_minutes:.0f}min{ct}")
            else:
                entries.append(f"    {e.exercise_name}")
        if entries:
            # Include the WEEKDAY explicitly — never make the model convert a date
            # to a day of week (LLMs get this wrong, e.g. calling a Wed session
            # "Tuesday"). The listed exercises ARE the session's focus; read them.
            try:
                day = f" ({l.date.strftime('%A')})"
            except Exception:
                day = ""
            sessions.append(f"  {l.date}{day}:\n" + "\n".join(entries))
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
        # Past finalized days only — today's totals are still in flight.
        week_logs = [
            l for l in logs
            if week_start <= l.date <= week_end and l.date < today_date
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
    # Honor the user's pacing toggle — when they've turned pacing OFF in Settings,
    # don't inject the remaining-calories/protein nudge into context at all.
    if not getattr(prefs, "pacing_enabled", True):
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

    # Average daily calories this week — past days only (today still in flight).
    finalized = [l for l in logs if l.date < today_date and l.date >= week_ago]
    if finalized and prefs and prefs.calorie_target:
        avg_cal = sum(l.total_calories for l in finalized) / len(finalized)
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
    src = "Whoop" if latest.source == "whoop" else "Apple Health"

    # ── Latest snapshot (today / most recent) ────────────────
    today_parts = []
    if latest.recovery_score is not None:
        today_parts.append(f"Recovery {latest.recovery_score}%")
    if latest.strain is not None:
        today_parts.append(f"Strain {latest.strain:.1f}/21")
    if latest.sleep_hours is not None:
        sleep_str = f"Sleep {latest.sleep_hours:.1f}h"
        extras = []
        if latest.sleep_deep_hours:
            extras.append(f"deep {latest.sleep_deep_hours:.1f}h")
        if latest.sleep_rem_hours:
            extras.append(f"REM {latest.sleep_rem_hours:.1f}h")
        if latest.sleep_efficiency_pct:
            extras.append(f"eff {latest.sleep_efficiency_pct:.0f}%")
        if extras:
            sleep_str += f" ({', '.join(extras)})"
        today_parts.append(sleep_str)
    if getattr(latest, "sleep_performance_pct", None) is not None:
        today_parts.append(f"Sleep quality {latest.sleep_performance_pct:.0f}%")
    if getattr(latest, "sleep_need_hours", None) is not None:
        today_parts.append(f"Sleep need {latest.sleep_need_hours:.1f}h")
    if latest.hrv is not None:
        today_parts.append(f"HRV {latest.hrv:.0f}ms")
    if latest.resting_hr is not None:
        today_parts.append(f"RHR {latest.resting_hr:.0f}bpm")
    if latest.avg_hr is not None:
        today_parts.append(f"Avg HR {latest.avg_hr:.0f}bpm")
    if getattr(latest, "respiratory_rate", None) is not None:
        today_parts.append(f"Resp rate {latest.respiratory_rate:.1f}br/min")
    if getattr(latest, "spo2_percentage", None) is not None:
        today_parts.append(f"SpO2 {latest.spo2_percentage:.1f}%")
    if getattr(latest, "skin_temp_celsius", None) is not None:
        today_parts.append(f"Skin temp {latest.skin_temp_celsius:.1f}°C")
    if latest.steps is not None:
        today_parts.append(f"Steps {latest.steps:,}")
    if latest.active_calories is not None:
        today_parts.append(f"Active cal {latest.active_calories:.0f}")
    # Workout summary
    if getattr(latest, "whoop_workouts", None):
        try:
            import json as _j
            wos = _j.loads(latest.whoop_workouts)
            wo_strs = []
            for w in wos:
                s = w.get("sport", "Workout")
                strain = w.get("strain")
                dur = w.get("duration_min")
                parts_w = []
                if strain:
                    parts_w.append(f"strain {strain}")
                if dur:
                    parts_w.append(f"{int(dur)}min")
                wo_strs.append(s + (f" ({', '.join(parts_w)})" if parts_w else ""))
            if wo_strs:
                today_parts.append("Workouts: " + "; ".join(wo_strs))
        except Exception:
            pass
    if not today_parts:
        return ""

    result = f"{src} ({latest.date}): " + "  |  ".join(today_parts)

    # ── 7-day trend summary (when we have multiple days) ─────
    if len(snaps) >= 3:
        recoveries = [s.recovery_score for s in snaps if s.recovery_score is not None]
        hrvs       = [s.hrv            for s in snaps if s.hrv            is not None]
        sleeps     = [s.sleep_hours    for s in snaps if s.sleep_hours    is not None]
        strains    = [s.strain         for s in snaps if s.strain         is not None]

        trend_parts = []
        if len(recoveries) >= 3:
            avg_rec = sum(recoveries) / len(recoveries)
            lo, hi  = min(recoveries), max(recoveries)
            # HRV trend: compare last 2 days vs prior days
            if len(recoveries) >= 4:
                recent_avg  = sum(recoveries[:2]) / 2
                earlier_avg = sum(recoveries[2:]) / len(recoveries[2:])
                arrow = "⬇" if recent_avg < earlier_avg - 5 else ("⬆" if recent_avg > earlier_avg + 5 else "→")
                trend_parts.append(f"Recovery avg {avg_rec:.0f}% (range {lo}–{hi}%, {arrow})")
            else:
                trend_parts.append(f"Recovery avg {avg_rec:.0f}% (range {lo}–{hi}%)")
        if len(hrvs) >= 3:
            avg_hrv = sum(hrvs) / len(hrvs)
            if len(hrvs) >= 4:
                recent_hrv  = sum(hrvs[:2]) / 2
                earlier_hrv = sum(hrvs[2:]) / len(hrvs[2:])
                arrow = "⬇" if recent_hrv < earlier_hrv - 3 else ("⬆" if recent_hrv > earlier_hrv + 3 else "→")
                trend_parts.append(f"HRV avg {avg_hrv:.0f}ms ({arrow})")
            else:
                trend_parts.append(f"HRV avg {avg_hrv:.0f}ms")
        if len(sleeps) >= 3:
            avg_sleep = sum(sleeps) / len(sleeps)
            trend_parts.append(f"Sleep avg {avg_sleep:.1f}h")
        if len(strains) >= 3:
            avg_strain = sum(strains) / len(strains)
            peak_strain = max(strains)
            trend_parts.append(f"Strain avg {avg_strain:.1f} peak {peak_strain:.1f}")
        # Sleep quality trend
        sleep_perfs = [s.sleep_performance_pct for s in snaps if getattr(s, "sleep_performance_pct", None) is not None]
        if len(sleep_perfs) >= 3:
            avg_perf = sum(sleep_perfs) / len(sleep_perfs)
            trend_parts.append(f"Sleep quality avg {avg_perf:.0f}%")
        resp_rates = [s.respiratory_rate for s in snaps if getattr(s, "respiratory_rate", None) is not None]
        if len(resp_rates) >= 3:
            avg_resp = sum(resp_rates) / len(resp_rates)
            trend_parts.append(f"Resp rate avg {avg_resp:.1f}br/min")
        # Workout count from Whoop
        wo_days = sum(1 for s in snaps if getattr(s, "whoop_workouts", None))
        if wo_days > 0:
            trend_parts.append(f"Workout days logged {wo_days}/{len(snaps)}")

        if trend_parts:
            result += f"\n{src} 7-day trend: " + "  |  ".join(trend_parts)

    return result


async def build_context(user: User, today_log: Optional[DailyLog], db,
                        platform: str = "telegram", user_message: str = "") -> str:
    from core.coaching_state import compute_coaching_state

    # Expire all cached attributes and fetch fresh from DB so OAuth token changes
    # (e.g. Whoop just connected in the same session) are reflected immediately.
    # reload_user() on the same session hits SQLAlchemy's identity map cache —
    # db.refresh() bypasses it and actually hits the DB.
    await db.refresh(user)

    recent_logs = await get_recent_logs(db, user.id, days=35)
    recent_weights = await get_recent_weights(db, user.id, days=56)
    recent_health = await get_recent_health_snapshots(db, user.id, days=7)

    # Health snapshots may be on a linked identity — check linked users if empty
    if not recent_health:
        try:
            from sqlalchemy import select as _sel
            from db.models import User as _U
            _linked = (await db.execute(
                _sel(_U).where(_U.linked_to_user_id == user.id)
            )).scalars().all()
            for _lu in _linked:
                _snaps = await get_recent_health_snapshots(db, _lu.id, days=7)
                if _snaps:
                    recent_health = _snaps
                    break
        except Exception:
            pass

    # Long-term context now lives in user_attributes (queryable, current within
    # seconds of a store_attribute call). The legacy markdown profile and freeform
    # arnie_memory.md are kept as read-only fallbacks for users created before the
    # attribute store became authoritative; new writes do not touch them.
    from memory.profile_manager import read_profile
    profile = await read_profile(user.telegram_id)
    raw_notes = await read_memory(user.telegram_id)

    # AI profile — all active attributes injected at the top of context as
    # the central source of truth for what Arnie knows about this user.
    from memory.attribute_store import get_attributes_for_context
    try:
        attr_block = await get_attributes_for_context(db, user.id, user_message or "")
    except Exception:
        attr_block = ""

    # T2.2 — Pending food clarifications (open questions Arnie asked but the
    # user hasn't answered yet). Freshness window scales with food_logging_mode:
    # quick=15 min (don't block flow), moderate=30 min (default), strict=60 min
    # (user wants accuracy, questions stay live longer). Auto-resolves on log_food.
    pending_clarification_block = ""
    try:
        from db.queries import get_open_pending_questions
        _pending = await get_open_pending_questions(db, user.id)
        _food_mode = getattr(user.preferences, "food_logging_mode", None) if user.preferences else None
        pending_clarification_block = render_pending_clarification_block(_pending, food_mode=_food_mode)
    except Exception as e:
        # Telemetry only — never fail the turn for a clarification fetch error.
        import logging as _l
        _l.getLogger(__name__).warning(f"pending clarification fetch failed: {e}")

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

    # Active mission (open coaching loop) — live progress so Arnie can close it
    from core.missions import mission_progress
    mission_str = mission_progress(user, today_log)
    if mission_str:
        discovery_lines.append(mission_str)

    # Detect workout mode: exercises already logged today
    in_workout = bool(today_log and today_log.exercise_entries)

    # Current local time — so Arnie answers time/date questions correctly and
    # times its coaching to the user's actual day (not the UTC server clock).
    import pytz as _pytz
    if user.timezone and user.timezone != "UTC":
        try:
            _now = datetime.now(_pytz.timezone(user.timezone))
            _t = _now.strftime("%-I:%M %p").lstrip("0")
            current_time_line = (
                f"[CURRENT TIME] Today is {_now.strftime('%A, %B %-d, %Y')}, {_t} "
                f"for the user (timezone {user.timezone}). Use this EXACT date and "
                f"weekday TOGETHER for any date question (today is "
                f"{_now.strftime('%A')}) — never convert a date to a weekday yourself, "
                f"and never guess the time."
            )
        except Exception:
            current_time_line = ""
    else:
        _now = datetime.now(_pytz.utc)
        current_time_line = (
            f"[CURRENT TIME] User's timezone is unknown, so local time is uncertain. "
            f"Server time is {_now.strftime('%A, %B %-d, %Y %-I:%M %p')} UTC — use this "
            f"exact date and weekday together; never convert a date to a weekday yourself. "
            f"If asked the time, say you're not sure of their timezone and ask what city they're in. "
            f"Do NOT state a specific local time as fact."
        )

    # Cross-platform link status — gates whether Arnie may offer to connect the
    # other platform. Linked = this account points somewhere, or something points here.
    from db.queries import linking_enabled
    linked = False
    if linking_enabled():
        if user.linked_to_user_id:
            linked = True
        else:
            from sqlalchemy import select, func
            res = await db.execute(
                select(func.count()).select_from(User).where(User.linked_to_user_id == user.id)
            )
            linked = (res.scalar() or 0) > 0
    plat_name = {"imessage": "iMessage", "ios": "the Arnie app"}.get(platform, "Telegram")
    other = "Telegram" if platform in ("imessage", "ios") else "iMessage"
    if linked:
        link_status = (f"[LINK STATUS] you're on {plat_name}. this person is ALREADY linked "
                       f"across both platforms — do NOT bring up linking.")
    else:
        link_status = (f"[LINK STATUS] you're on {plat_name}. NOT linked to {other}. "
                       f"only offer to connect {other} if THEY organically bring it up.")

    # Training program (workout split) — read from DB if saved
    training_program_str = ""
    _prog_parsed = None  # also used by [SESSION STATE] below
    try:
        import json as _json
        from sqlalchemy import select as _select
        from db.models import WorkoutProgram as _WP
        _wp_row = (await db.execute(
            _select(_WP).where(_WP.user_id == user.id)
        )).scalar_one_or_none()
        if _wp_row and _wp_row.program_json:
            _prog = _json.loads(_wp_row.program_json)
            _prog_parsed = _prog
            _days_txt = []
            for _d in (_prog.get("days") or []):
                _ex = ", ".join(e["name"] for e in (_d.get("exercises") or []) if e.get("name"))
                _goals = ", ".join(_d.get("goals") or [])
                _days_txt.append(
                    f"  {_d.get('name','')} [{_d.get('priority','')}]"
                    + (f" — goals: {_goals}" if _goals else "")
                    + (f"\n    Exercises: {_ex}" if _ex else "")
                )
            training_program_str = (
                f"=== TRAINING PROGRAM ===\n"
                f"Split: {_prog.get('split_name','')}\n"
                f"Focus: {_prog.get('focus','')}\n"
                f"Rotation: {' → '.join(_prog.get('rotation',[]))}\n"
                + "\n".join(_days_txt)
            )
    except Exception:
        pass

    # Builder-generated program — fall back to this when the legacy parsed
    # split isn't set. The science-based propose_workout_program tool writes
    # to generated_workout_programs (multi-session relational), and Arnie
    # needs to SEE it in context so he can reference the user's split, name
    # the upcoming session, and avoid prescribing a one-off plan that
    # conflicts with the user's stored program.
    if not training_program_str:
        try:
            from db.workout_program_queries import get_active_generated_program
            _gen = await get_active_generated_program(db, user.id)
            if _gen and _gen.sessions:
                import json as _json
                _sess_txt = []
                for s in _gen.sessions:
                    try:
                        _exs = _json.loads(s.exercises_json or "[]")
                    except Exception:
                        _exs = []
                    _names = ", ".join(
                        e.get("canonical", "") for e in _exs if e.get("canonical")
                    )
                    _sess_txt.append(
                        f"  Day {s.position} {s.name}: {_names}" if _names
                        else f"  Day {s.position} {s.name}"
                    )
                training_program_str = (
                    f"=== TRAINING PROGRAM (science-based, Arnie-built) ===\n"
                    f"Name: {_gen.name}\n"
                    f"Goal: {_gen.goal} | Days/week: {_gen.days_per_week} | "
                    f"Experience: {_gen.experience_level}\n"
                    + "\n".join(_sess_txt)
                )
                # Build the _prog_parsed shape the session-state builder
                # expects (days[] with name + exercises[].name). That keeps
                # live workout awareness working off the builder program too.
                _prog_parsed = {
                    "split_name": _gen.name,
                    "focus":      f"{_gen.goal} program",
                    "rotation":   [s.name for s in _gen.sessions],
                    "days": [
                        {
                            "name": s.name,
                            "priority": "primary",
                            "goals": [],
                            "exercises": [
                                {"name": e.get("canonical", ""),
                                 "category": ("main" if (e.get("notes") or "").startswith("main")
                                              else "accessory")}
                                for e in _json.loads(s.exercises_json or "[]")
                            ],
                        }
                        for s in _gen.sessions
                    ],
                }
        except Exception:
            pass

    # [SESSION STATE] — live workout awareness. Built whenever the user has
    # exercise entries today (in_workout=True). Works WITH or WITHOUT a
    # training program — the freeform path still surfaces muscle coverage,
    # rest windows, and movement order so the model can coach actionably.
    # See core/session_state.py for details.
    session_state_str = ""
    if in_workout:
        try:
            from core.session_state import build_session_state as _bss
            session_state_str = _bss(
                today_log,
                program_json=_prog_parsed,
                now_dt=_now if hasattr(_now, "year") else datetime.utcnow(),
            )
        except Exception:
            # Never let session-state failure block the rest of the context
            session_state_str = ""

    # Wearable / connection status for Arnie to reference
    # Check Whoop connection on canonical AND any linked identities (tokens may
    # be on a linked row before the user runs /whoop disconnect + /connect whoop)
    _has_whoop = bool(user.whoop_access_token or user.whoop_refresh_token)
    if not _has_whoop:
        try:
            from sqlalchemy import select as _sel
            from db.models import User as _U
            _linked = (await db.execute(
                _sel(_U).where(_U.linked_to_user_id == user.id)
            )).scalars().all()
            _has_whoop = any(bool(u.whoop_access_token or u.whoop_refresh_token) for u in _linked)
        except Exception:
            pass
    whoop_status = (
        "Whoop: CONNECTED — can see recovery, HRV, sleep, strain via /whoop or wearable data above."
        if _has_whoop
        else "Whoop: NOT connected. If user asks about Whoop data or connection status, tell them to run /connect whoop in Telegram to link it."
    )
    apple_status = (
        "Apple Health: CONNECTED — receiving health metrics."
        if any(s.source == "apple_health" for s in recent_health)
        else "Apple Health: NOT connected."
    )

    # Location-on-file signal. Without this, the model has no way to know
    # whether the user has shared coords, so it would either always ask
    # ("share your location?") or always blindly call find_nearby_places
    # and let the handler fall back to None. The status line plus the
    # LOCATION_RULES prompt block ("once a location is on file, reuse it")
    # closes that loop. Gated by LOCATION_ENABLED — when the tool isn't
    # exposed at all, the status line is irrelevant.
    from db.queries import location_enabled as _location_enabled
    _has_location = bool(
        _location_enabled()
        and user.lat is not None
        and user.lng is not None
    )
    if _location_enabled():
        if _has_location:
            # Street-precision readback: reverse-geocode the stored lat/lng to
            # an actual formatted address ("116 Central Park S, New York, NY")
            # so the model can answer "where am I right now?" precisely instead
            # of just naming the city. 6h cache in core/geocode; on a miss/
            # missing key it returns None and we fall back to city-only — never
            # raises, never blocks the turn.
            from core.geocode import reverse_address as _reverse_address
            try:
                _street = await _reverse_address(user.lat, user.lng)
            except Exception:
                _street = None
            if _street:
                location_status = (
                    f"Location: ON FILE ({_street}) — that's the user's exact "
                    f"shared spot, to ~1m precision. When the user asks 'where "
                    f"am I?' relay this address directly. When they ask about "
                    f"places nearby, call find_nearby_places — it auto-uses "
                    f"the precise lat/lng on file, so 'closest to me' searches "
                    f"from this exact point, NOT the city center. Do NOT ask "
                    f"them to share again."
                )
            else:
                _city_part = f" ({user.city})" if user.city else ""
                location_status = (
                    f"Location: ON FILE{_city_part} — exact lat/lng on file, "
                    f"call find_nearby_places directly when the user asks "
                    f"anything nearby; do NOT ask them to share again."
                )
        else:
            location_status = (
                "Location: NOT on file. If the user asks about nearby places, "
                "call find_nearby_places anyway — the app will surface a one-tap "
                "'share location' button under your reply."
            )
    else:
        location_status = ""

    # Food logging mode — quick/strict inject an override; moderate is the static default.
    food_mode_inj = food_mode_directive(getattr(prefs, "food_logging_mode", None))

    # Goal weight nudge — inject once if cut/bulk user has no goal weight set.
    # Arnie asks naturally at the right moment; never blocks or repeats.
    _needs_goal_wt = (
        user.primary_goal in ("cut", "bulk")
        and not user.goal_weight_kg
        and user.onboarding_completed
    )
    goal_wt_nudge = (
        "[COACH NOTE] This user is on a {} plan but hasn't set a goal weight yet. "
        "If it comes up naturally in the next message (e.g. they mention targets, "
        "progress, or where they want to get to), ask once: what weight are you "
        "aiming for? Then call update_profile(goal_weight_lbs=...). "
        "Don't force it if the message is about something unrelated.".format(user.primary_goal)
        if _needs_goal_wt else ""
    )

    # Targets-missing nudge — inject when user has no calorie target set.
    # Includes the math-derived recommendation so Arnie can offer concrete
    # numbers in a single turn instead of guessing. The recommended values
    # match what the dashboard "Calculate for me" button would compute
    # (same compute_auto_macro_targets() helper). Fact-style block, not a
    # directive — Arnie decides if the conversational moment fits.
    _needs_targets = (
        user.onboarding_completed
        and (not prefs or not prefs.calorie_target)
    )
    targets_nudge = ""
    if _needs_targets:
        try:
            from api.app import compute_auto_macro_targets
            rec = compute_auto_macro_targets(user)
        except Exception:
            rec = None
        if rec:
            targets_nudge = (
                "[COACH NOTE — targets_unset] User has no calorie/macro targets. "
                "Math from their {goal} goal + body comp suggests ~{cals} kcal, "
                "{p}g P / {c}g C / {f}g F (BMR {bmr}, TDEE {tdee}, "
                "{pct:+.1f}% from TDEE). If they bring up calories/macros/goals "
                "or it fits the conversation naturally, offer to lock those in. "
                "Call set_macro_targets(calories, protein, carbs, fat) to save. "
                "Or point them to the 'Calculate for me' button on the dashboard "
                "if they prefer to confirm visually. Don't force it on unrelated "
                "messages."
            ).format(
                goal=user.primary_goal or "current",
                cals=rec["calorie_target"],
                p=rec["protein_target"],
                c=rec["carb_target"],
                f=rec["fat_target"],
                bmr=rec["bmr"],
                tdee=rec["tdee"],
                pct=rec["deficit_pct"],
            )
        else:
            # Missing essentials (weight/height/age/sex) — can't compute yet.
            targets_nudge = (
                "[COACH NOTE — targets_unset] User has no calorie/macro targets "
                "AND is missing some of weight/height/age/sex on profile, so "
                "auto-calc won't work yet. If they bring up calories/macros, "
                "ask for the missing field(s) and call update_profile()."
            )

    # Deterministic reply-language anchor — overrides conversational momentum so a
    # user who switches back to English (Latin script) after a non-Latin stretch
    # gets an English reply instead of staying frozen in their stored language.
    # Placed FIRST so it outranks every other block. None for the common case.
    try:
        from core.language import reply_language_directive
        _lang_directive = reply_language_directive(
            getattr(prefs, "preferred_language", None), user_message
        )
    except Exception:
        _lang_directive = None

    sections = [
        (_lang_directive if _lang_directive else ""),
        current_time_line,
        "=== PROFILE ===",
        fmt_profile(user, prefs),
        (goal_wt_nudge if goal_wt_nudge else ""),
        (targets_nudge if targets_nudge else ""),
        (progress if progress else ""),
        # Live learned attributes — placed here so they influence every skill,
        # not buried after 35 days of logs. core tier always; daily if ≤7d old;
        # contextual only when this message's topic matches.
        (attr_block if attr_block else ""),
        f"[CONNECTED DEVICES] {whoop_status} | {apple_status}",
        (f"[LOCATION] {location_status}" if location_status else ""),
        "",
        # Coaching state goes at top so every skill sees it first
        (coaching_state_str if coaching_state_str else ""),
        "",
        (training_program_str if training_program_str else ""),
        "",
        "=== TODAY ===",
        fmt_log(today_log),
        (f"[PACING]\n{pace}" if pace else ""),
        (f"[WEARABLE]\n{health_str}" if health_str else ""),
        ("" if not in_workout else "[WORKOUT MODE: ACTIVE]"),
        (session_state_str if session_state_str else ""),
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
        fmt_recent_day_detail(recent_logs, days=3),
        "",
        "=== FOOD HISTORY ===",
        (food_history if food_history else "No food history yet."),
        "",
        "=== EXERCISE HISTORY ===",
        fmt_exercise_history(recent_logs),
        (strength_prs if strength_prs else ""),
        "",
        # === USER PROFILE === section removed — the [AI PROFILE] block at the
        # top of context is now the source of truth for what Arnie knows.
        # The legacy markdown profile (profile.md) and raw_notes (arnie_memory.md)
        # are kept on disk but no longer injected into context. They served as the
        # primary long-term memory before user_attributes existed; old users still
        # have these files but new facts go through store_attribute exclusively.
        # If profile is empty AND no attributes exist, the [AI PROFILE] block is
        # absent and the model relies on === PROFILE === (structured DB) above.
        (f"[LEGACY PROFILE — older user, attribute store still building]\n{profile[:2500]}"
         if (profile and not attr_block) else ""),
        (f"[LEGACY NOTES]\n{raw_notes[:600]}"
         if (raw_notes and not attr_block and not profile) else ""),
        "",
        (pending_clarification_block if pending_clarification_block else ""),
        link_status,
        (food_mode_inj if food_mode_inj else ""),
    ]
    return "\n".join(s for s in sections if s is not None)
