"""
Target calculation — Mifflin-St Jeor BMR → calorie + protein targets.

Shared by the bot handlers and tool_executor so targets can be auto-computed
the moment the required stats (weight, height, age, sex, goal) are all present —
including when height/age/sex are collected post-onboarding via proactive nudges.
"""
import logging

logger = logging.getLogger(__name__)


def calc_targets(user) -> dict | None:
    """
    Returns {tdee, calories, protein, goal} or None if required fields missing.
    Requires: current_weight_kg, height_cm, age, sex (male/female), primary_goal.
    """
    try:
        w = user.current_weight_kg
        h = user.height_cm
        a = user.age
        s = (user.sex or "").lower()
        g = user.primary_goal
        if not all([w, h, a, s in ("male", "female"), g]):
            return None

        bmr = 10 * w + 6.25 * h - 5 * a + (5 if s == "male" else -161)
        tdee = round(bmr * 1.55)  # moderately active lifter

        if g == "cut":
            cal = round((tdee - 450) / 50) * 50
        elif g == "bulk":
            cal = round((tdee + 300) / 50) * 50
        else:
            cal = round(tdee / 50) * 50

        w_lbs = w * 2.20462
        protein = round(w_lbs * (0.9 if g in ("cut", "maintain") else 0.8) / 5) * 5

        return {"tdee": tdee, "calories": max(cal, 1200),
                "protein": max(protein, 100), "goal": g}
    except Exception as e:
        logger.warning(f"calc_targets failed: {e}")
        return None


def missing_profile_stats(user) -> list[str]:
    """Which target-calc stats are still missing. Used by proactive collection."""
    missing = []
    if not user.age:
        missing.append("age")
    if not user.sex:
        missing.append("sex")
    if not user.height_cm:
        missing.append("height")
    return missing
