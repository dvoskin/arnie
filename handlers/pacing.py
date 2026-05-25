"""
Pacing calculations — deterministic, no LLM required.
"""
from typing import Optional
from db.models import DailyLog, UserPreferences


def get_pacing_status(log: Optional[DailyLog],
                      prefs: Optional[UserPreferences]) -> dict:
    """Return a structured pacing snapshot for the current day."""
    if not log or not prefs:
        return {}

    cal_target = prefs.calorie_target or 0
    pro_target = prefs.protein_target or 0

    cal_remaining = cal_target - log.total_calories
    pro_remaining = pro_target - log.total_protein

    # Risk flags
    protein_risk = pro_target > 0 and (log.total_protein / pro_target) < 0.4
    calorie_behind = cal_target > 0 and cal_remaining > cal_target * 0.5
    calorie_over = cal_target > 0 and cal_remaining < -100

    return {
        "calories_remaining": cal_remaining,
        "protein_remaining": pro_remaining,
        "protein_pct": (log.total_protein / pro_target * 100) if pro_target else None,
        "calorie_pct": (log.total_calories / cal_target * 100) if cal_target else None,
        "protein_risk": protein_risk,
        "calorie_behind": calorie_behind,
        "calorie_over": calorie_over,
    }


def pacing_message(log: Optional[DailyLog],
                   prefs: Optional[UserPreferences]) -> Optional[str]:
    """Generate a short pacing nudge, or None if nothing notable."""
    status = get_pacing_status(log, prefs)
    if not status:
        return None

    msgs = []
    if status.get("calorie_over"):
        over = abs(status["calories_remaining"])
        msgs.append(f"You're {over:.0f} cal over target — keep the rest of the day light.")
    elif status.get("protein_risk"):
        msgs.append(
            f"Only {log.total_protein:.0f}g protein so far. "
            f"Still need {status['protein_remaining']:.0f}g — prioritise protein now."
        )
    elif status.get("calorie_behind"):
        msgs.append(
            f"Behind on food ({log.total_calories:.0f}/{prefs.calorie_target} cal). "
            f"Don't skip meals or you'll likely overeat late."
        )

    return " ".join(msgs) if msgs else None
