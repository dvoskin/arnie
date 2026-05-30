"""
Memory Moments — periodically surface meaningful, ACCURATE historical context
that builds emotional attachment ("3 months ago you were 212 saying you wanted
under 190; today you're 191.4").

Strict integrity: every number is pulled from real stored data (BodyMetric,
DailyLog). Returns a moment ONLY when there's a genuinely notable comparison —
never fabricated, never trivial. Used in the weekly recap and occasional
proactive surfacing, not every message (so it stays special).
"""
from datetime import date, timedelta
from statistics import mean
from typing import Optional


def find_memory_moment(weights, recent_logs, user) -> Optional[str]:
    """
    Return one meaningful, real historical moment — or None if nothing notable.
    Priority: a milestone crossed > a big weight journey > a real habit improvement.
    """
    # ── Weight journey (needs a span of history) ──────────────────────────────
    if weights and len(weights) >= 4:
        sw = sorted(weights, key=lambda w: w.timestamp)
        first, last = sw[0], sw[-1]
        span_days = (last.timestamp - first.timestamp).days
        if span_days >= 21:
            delta_lbs = (last.weight_kg - first.weight_kg) * 2.20462
            start_lbs = first.weight_kg * 2.20462
            now_lbs = last.weight_kg * 2.20462
            weeks = span_days // 7
            goal = getattr(user, "goal_weight_kg", None)

            # Milestone: just crossed the goal
            if goal:
                goal_lbs = goal * 2.20462
                want_down = goal < first.weight_kg
                crossed = (want_down and now_lbs <= goal_lbs + 0.5) or \
                          (not want_down and now_lbs >= goal_lbs - 0.5)
                if crossed and abs(start_lbs - goal_lbs) >= 3:
                    return (f"{weeks} weeks ago you were {start_lbs:.0f} lbs with a goal of {goal_lbs:.0f}. "
                            f"this morning: {now_lbs:.0f}. you got there. 🔥")

            # Big journey worth naming (≥4 lbs over ≥3 weeks, in the right direction)
            if abs(delta_lbs) >= 4 and weeks >= 3:
                direction = "down" if delta_lbs < 0 else "up"
                return (f"{weeks} weeks ago you were {start_lbs:.0f} lbs. today you're {now_lbs:.0f} — "
                        f"that's {abs(delta_lbs):.0f} lbs {direction}. real progress, not noise.")

    # ── Habit improvement: protein adherence then vs now ─────────────────────
    prefs = getattr(user, "preferences", None)
    pro_t = prefs.protein_target if prefs else None
    closed = sorted([l for l in recent_logs if (l.total_calories or 0) > 0], key=lambda l: l.date)
    if pro_t and len(closed) >= 14:
        first_half = closed[: len(closed) // 2]
        recent_half = closed[len(closed) // 2:]
        early_avg = mean((l.total_protein or 0) for l in first_half)
        recent_avg = mean((l.total_protein or 0) for l in recent_half)
        if recent_avg - early_avg >= 25:
            return (f"when you started you were averaging {early_avg:.0f}g protein a day. "
                    f"lately you're at {recent_avg:.0f}. that habit's locked in now.")

    # ── Consistency milestone ────────────────────────────────────────────────
    if len(closed) >= 20:
        return (f"you've logged {len(closed)} days now. that consistency is the whole game — "
                f"most people quit way before this.")

    return None
