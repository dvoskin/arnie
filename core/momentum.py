"""
Momentum Score — a resilient, 0-100 measure of how a user's performance system
is trending. Replaces fragile day-streaks: one bad day barely moves it, because
it's a rolling 7-day blend. Momentum rewards consistency and resilience, not
perfection.

Pure computation over data we already store (DailyLog, BodyMetric). No new tables.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class Momentum:
    score: int                  # 0-100
    tier: str                   # rebuilding | building | strong | peak
    direction: str              # rising | steady | cooling
    drivers: list               # short phrases: what's lifting/dragging it
    logged_days: int            # days logged in window


def _tier(score: int) -> str:
    if score >= 80: return "peak"
    if score >= 60: return "strong"
    if score >= 35: return "building"
    return "rebuilding"


def compute_momentum(recent_logs, prefs, weights=None, user=None) -> Optional[Momentum]:
    """
    7-day momentum from logging consistency, protein + calorie adherence,
    training frequency, and trend direction toward goal. Returns None if there's
    not enough data yet (brand-new users).
    """
    today = date.today()
    window = [today - timedelta(days=i) for i in range(7)]
    by_date = {l.date: l for l in recent_logs}
    logs = [by_date[d] for d in window if d in by_date]
    logged_days = len(logs)
    if logged_days == 0:
        return None

    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None

    # 1) Logging consistency (0-1) — the foundation
    consistency = logged_days / 7.0

    # 2) Protein adherence (0-1) over logged days — the goal metric
    if pro_t:
        protein = sum(min((l.total_protein or 0) / pro_t, 1.0) for l in logs) / logged_days
    else:
        protein = 0.6  # neutral when no target

    # 3) Calorie adherence (0-1) — within 12% of target counts as on-point
    if cal_t:
        cal = sum(1 for l in logs if abs((l.total_calories or 0) - cal_t) <= cal_t * 0.12) / logged_days
    else:
        cal = 0.6

    # 4) Training (0-1) — 4+ sessions in the week = full marks
    workouts = sum(1 for l in logs if l.workout_completed or l.cardio_completed)
    training = min(workouts / 4.0, 1.0)

    # 5) Trend direction toward goal (0-1)
    trend = 0.5
    if weights and len(weights) >= 2 and user and getattr(user, "goal_weight_kg", None):
        sw = sorted(weights, key=lambda w: w.timestamp)
        delta = sw[-1].weight_kg - sw[0].weight_kg
        goal = user.goal_weight_kg
        cur = sw[-1].weight_kg
        want_down = goal < cur
        moving_right = (delta < -0.1 and want_down) or (delta > 0.1 and not want_down)
        if abs(cur - goal) <= 0.5:
            trend = 1.0       # essentially at goal
        elif moving_right:
            trend = 0.85
        elif abs(delta) < 0.1:
            trend = 0.5       # holding
        else:
            trend = 0.3       # drifting wrong way

    # Weighted blend → 0-100. Consistency + protein carry the most weight.
    score01 = (
        0.30 * consistency +
        0.25 * protein +
        0.18 * cal +
        0.15 * training +
        0.12 * trend
    )
    score = round(score01 * 100)

    # Direction: compare this week's consistency+training to the prior week.
    prior_window = [today - timedelta(days=i) for i in range(7, 14)]
    prior = [by_date[d] for d in prior_window if d in by_date]
    direction = "steady"
    if prior:
        prior_active = sum(1 for l in prior if (l.total_calories or 0) > 0) + \
                       sum(1 for l in prior if l.workout_completed)
        now_active = logged_days + workouts
        if now_active > prior_active + 1:
            direction = "rising"
        elif now_active < prior_active - 1:
            direction = "cooling"

    # Drivers — what's helping / hurting (top 2)
    drivers = []
    if consistency >= 0.85: drivers.append("logging like clockwork")
    elif consistency < 0.5: drivers.append("logging's been spotty")
    if pro_t and protein >= 0.9: drivers.append("protein on point")
    elif pro_t and protein < 0.6: drivers.append("protein running low")
    if training >= 1.0: drivers.append(f"{workouts} sessions this week")
    elif workouts == 0: drivers.append("no training logged this week")
    if trend >= 0.85: drivers.append("weight trending your way")
    elif trend <= 0.3: drivers.append("weight drifting off-target")

    return Momentum(
        score=score, tier=_tier(score), direction=direction,
        drivers=drivers[:3], logged_days=logged_days,
    )


def fmt_momentum(m: Optional[Momentum]) -> str:
    """Render for context injection."""
    if not m:
        return ""
    arrow = {"rising": "↑", "cooling": "↓", "steady": "→"}.get(m.direction, "")
    line = f"[MOMENTUM] {m.score}/100 ({m.tier}, {m.direction} {arrow})"
    if m.drivers:
        line += "\n  drivers: " + " · ".join(m.drivers)
    line += ("\n  note: this is a rolling 7-day score — one off day barely moves it. "
             "frame setbacks as resilience, not failure.")
    return line
