"""
Open coaching loops — one active daily "mission" per user.

A mission is the day's single highest-leverage action, chosen deterministically
from the user's data so it's always auto-evaluable against the log (no fragile
LLM parsing). Humans return to unfinished challenges — Arnie sets one each
morning, tracks live progress, and closes it in the evening.

State lives on the User row (active_mission, mission_metric, mission_target,
mission_date). Pure logic here; persistence handled by callers.
"""
from datetime import date
from statistics import mean
from typing import Optional


def pick_mission(today_log, recent_logs, prefs, user) -> Optional[dict]:
    """
    Choose today's highest-leverage mission. Returns
      {text, metric, target}  or None if nothing stands out.
    Priority: protein (the goal metric) > training cadence > steps > calorie discipline.
    """
    pro_t = prefs.protein_target if prefs else None
    cal_t = prefs.calorie_target if prefs else None
    closed = [l for l in recent_logs if (l.total_calories or 0) > 0]

    # 1) Protein — if they routinely miss it, that's the lever
    if pro_t:
        recent_pro = [min((l.total_protein or 0), pro_t * 1.5) for l in closed[:7]]
        avg_pro = mean(recent_pro) if recent_pro else 0
        if avg_pro < pro_t * 0.85:
            # front-load it: target most of protein before mid-afternoon
            early = round(pro_t * 0.6 / 5) * 5
            return {"text": f"{early}g protein before 3pm", "metric": "protein", "target": float(early)}

    # 2) Training cadence — no session in the last 2 days
    last2 = recent_logs[:2]
    if last2 and not any(l.workout_completed or l.cardio_completed for l in last2):
        return {"text": "get a session in today", "metric": "workouts", "target": 1.0}

    # 3) Steps — if step data exists and runs low
    stepped = [l for l in closed[:7] if getattr(l, "total_steps", None)]
    if len(stepped) >= 3:
        avg_steps = mean((l.total_steps or 0) for l in stepped)
        if avg_steps < 8000:
            return {"text": "10k steps today", "metric": "steps", "target": 10000.0}

    # 4) Calorie discipline — finish under target
    if cal_t:
        return {"text": f"finish under {cal_t} cal tonight", "metric": "calories", "target": float(cal_t)}

    return None


def set_mission_on_user(user, mission: dict) -> None:
    user.active_mission = mission["text"]
    user.mission_metric = mission["metric"]
    user.mission_target = mission["target"]
    user.mission_date = str(date.today())


def mission_progress(user, today_log) -> Optional[str]:
    """
    Live progress line against the active mission, evaluated from today's log.
    Returns None if no active mission for today.
    """
    if not user.active_mission or user.mission_date != str(date.today()):
        return None
    metric, target = user.mission_metric, (user.mission_target or 0)
    log = today_log
    if metric == "protein":
        cur = (log.total_protein or 0) if log else 0
        done = cur >= target
        return f"[ACTIVE MISSION] {user.active_mission} — at {cur:.0f}g{' ✓ done' if done else f', {max(0,target-cur):.0f}g to go'}"
    if metric == "calories":
        cur = (log.total_calories or 0) if log else 0
        return f"[ACTIVE MISSION] {user.active_mission} — at {cur:.0f} cal so far"
    if metric == "workouts":
        done = bool(log and (log.workout_completed or log.cardio_completed))
        return f"[ACTIVE MISSION] {user.active_mission}{' — ✓ done' if done else ' — not yet'}"
    if metric == "steps":
        cur = (getattr(log, "total_steps", 0) or 0) if log else 0
        done = cur >= target
        return f"[ACTIVE MISSION] {user.active_mission} — at {cur:,} steps{' ✓' if done else ''}"
    return f"[ACTIVE MISSION] {user.active_mission}"


def mission_completed(user, today_log) -> Optional[bool]:
    """True/False if there's an active mission today; None if no mission."""
    if not user.active_mission or user.mission_date != str(date.today()):
        return None
    metric, target = user.mission_metric, (user.mission_target or 0)
    log = today_log
    if metric == "protein":
        return (log.total_protein or 0) >= target if log else False
    if metric == "calories":
        return (log.total_calories or 0) <= target if log else False
    if metric == "workouts":
        return bool(log and (log.workout_completed or log.cardio_completed))
    if metric == "steps":
        return (getattr(log, "total_steps", 0) or 0) >= target if log else False
    return None
