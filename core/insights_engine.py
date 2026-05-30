"""
Insights Engine — turns stored data into discovery, projection, and records.

Three jobs, all computed from existing DailyLog / BodyMetric data (no new tables):
  1. Future projection — where current behavior leads (4-week weight forecast).
  2. Pattern discovery — correlations the user hasn't noticed ("you overeat most
     after skipping breakfast", "weight drops fastest above 10k steps").
  3. Personal records beyond lifting — best protein week, most workouts, lowest
     weekly avg weight, best step average, longest logging run.

These feed the daily briefing and (rotated) the conversation context, so Arnie
surfaces "I never noticed that" moments instead of just reporting.
"""
from datetime import date, timedelta
from statistics import mean
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Future projection
# ─────────────────────────────────────────────────────────────────────────────

def weight_projection(weights, user, weeks: int = 4) -> Optional[str]:
    """Forecast bodyweight `weeks` out from the recent trend. lbs-facing."""
    if not weights or len(weights) < 3 or not user:
        return None
    sw = sorted(weights, key=lambda w: w.timestamp)
    days = max((sw[-1].timestamp - sw[0].timestamp).days, 1)
    if days < 7:
        return None
    rate_per_day = (sw[-1].weight_kg - sw[0].weight_kg) / days
    if abs(rate_per_day) < 0.005:  # essentially flat
        return f"you're holding steady around {sw[-1].weight_kg * 2.20462:.0f} lbs."
    projected_kg = sw[-1].weight_kg + rate_per_day * 7 * weeks
    proj_lbs = projected_kg * 2.20462
    cur_lbs = sw[-1].weight_kg * 2.20462
    goal = getattr(user, "goal_weight_kg", None)
    base = f"if this trend holds, you're on pace for ~{proj_lbs:.0f} lbs in {weeks} weeks (now {cur_lbs:.0f})."
    if goal:
        goal_lbs = goal * 2.20462
        # weeks to goal at current rate
        remaining_kg = goal - sw[-1].weight_kg
        if rate_per_day != 0 and (remaining_kg / rate_per_day) > 0:
            wks = remaining_kg / rate_per_day / 7
            if 0 < wks <= 52:
                base += f" at this rate you'd hit {goal_lbs:.0f} in about {wks:.0f} weeks."
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Pattern discovery
# ─────────────────────────────────────────────────────────────────────────────

def discover_pattern(logs, prefs) -> Optional[str]:
    """
    Mine recent logs for ONE non-obvious correlation worth surfacing.
    Returns a single insight string or None. Heuristic, evidence-gated.
    """
    closed = [l for l in logs if (l.total_calories or 0) > 0]
    if len(closed) < 8:
        return None

    cal_t = prefs.calorie_target if prefs else None

    # Pattern A: steps vs calorie control (needs step data)
    stepped = [l for l in closed if getattr(l, "total_steps", None)]
    if cal_t and len(stepped) >= 8:
        hi = [l for l in stepped if (l.total_steps or 0) >= 10000]
        lo = [l for l in stepped if (l.total_steps or 0) < 10000]
        if len(hi) >= 3 and len(lo) >= 3:
            hi_over = mean(1 if (l.total_calories or 0) > cal_t else 0 for l in hi)
            lo_over = mean(1 if (l.total_calories or 0) > cal_t else 0 for l in lo)
            if lo_over - hi_over >= 0.3:
                return ("you stay under your calorie target far more often on 10k+ step days. "
                        "movement seems to anchor your eating.")

    # Pattern B: weekend vs weekday calorie overruns
    if cal_t:
        wknd = [l for l in closed if l.date.weekday() >= 5]
        wkdy = [l for l in closed if l.date.weekday() < 5]
        if len(wknd) >= 3 and len(wkdy) >= 4:
            wknd_over = mean(max((l.total_calories or 0) - cal_t, 0) for l in wknd)
            wkdy_over = mean(max((l.total_calories or 0) - cal_t, 0) for l in wkdy)
            if wknd_over > wkdy_over + 250:
                return (f"your weekends run about {wknd_over - wkdy_over:.0f} cal higher than weekdays. "
                        "that's where most of your overage lives.")

    # Pattern C: training days vs protein adherence
    pro_t = prefs.protein_target if prefs else None
    if pro_t:
        train = [l for l in closed if l.workout_completed]
        rest = [l for l in closed if not l.workout_completed]
        if len(train) >= 3 and len(rest) >= 3:
            train_p = mean((l.total_protein or 0) for l in train)
            rest_p = mean((l.total_protein or 0) for l in rest)
            if train_p - rest_p >= 25:
                return (f"you hit ~{train_p - rest_p:.0f}g more protein on training days than rest days. "
                        "rest days are where protein slips.")

    # Pattern D: low-protein days cluster under a calorie floor (under-eating)
    if cal_t and pro_t:
        low_cal = [l for l in closed if (l.total_calories or 0) < cal_t * 0.7]
        if len(low_cal) >= 3 and len(low_cal) / len(closed) >= 0.3:
            return (f"{len(low_cal)} of your last {len(closed)} logged days came in well under target. "
                    "under-eating this often can stall progress as much as overeating.")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Personal records beyond lifting
# ─────────────────────────────────────────────────────────────────────────────

def _iso_week(d: date):
    return d.isocalendar()[:2]


def personal_records(logs, weights) -> dict:
    """
    Compute non-lifting PRs from history. Returns a dict of record→value.
    Used both to celebrate new records and to show what to beat.
    """
    recs = {}
    closed = [l for l in logs if (l.total_calories or 0) > 0]

    if closed:
        best_protein_day = max((l.total_protein or 0) for l in closed)
        recs["best_protein_day"] = round(best_protein_day)

        # weekly aggregates
        weeks = {}
        for l in closed:
            wk = _iso_week(l.date)
            weeks.setdefault(wk, []).append(l)
        if weeks:
            recs["most_workouts_week"] = max(
                sum(1 for l in ls if l.workout_completed) for ls in weeks.values()
            )
            recs["best_protein_week_avg"] = round(max(
                mean((l.total_protein or 0) for l in ls) for ls in weeks.values()
            ))
            stepped_weeks = [
                mean((l.total_steps or 0) for l in ls if getattr(l, "total_steps", None))
                for ls in weeks.values()
                if any(getattr(l, "total_steps", None) for l in ls)
            ]
            if stepped_weeks:
                recs["best_step_week_avg"] = round(max(stepped_weeks))

    if weights and len(weights) >= 3:
        recs["lowest_weight_kg"] = round(min(w.weight_kg for w in weights), 1)

    return recs


def fmt_records(recs: dict) -> str:
    """Render PRs for context — what they've achieved / can beat."""
    if not recs:
        return ""
    bits = []
    if "best_protein_day" in recs: bits.append(f"best protein day {recs['best_protein_day']}g")
    if "best_protein_week_avg" in recs: bits.append(f"best protein week avg {recs['best_protein_week_avg']}g")
    if "most_workouts_week" in recs: bits.append(f"most workouts in a week {recs['most_workouts_week']}")
    if "best_step_week_avg" in recs: bits.append(f"best weekly step avg {recs['best_step_week_avg']:,}")
    if "lowest_weight_kg" in recs: bits.append(f"lowest weight {recs['lowest_weight_kg'] * 2.20462:.0f} lbs")
    if not bits:
        return ""
    return "[PERSONAL RECORDS] " + " · ".join(bits)
