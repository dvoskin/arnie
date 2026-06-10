"""
Target calculation — Mifflin-St Jeor BMR → calorie + macro targets.

Shared by the bot handlers, tool_executor, and dashboard so targets can be
auto-computed identically everywhere. Use compute_macro_targets() for full
4-macro output (calories + protein + carbs + fat). The legacy calc_targets()
shim is kept for backward compatibility but now wraps the unified math.
"""
import logging

logger = logging.getLogger(__name__)


def compute_macro_targets(user) -> dict | None:
    """Canonical calorie + 4-macro calculator. Used by:
      · dashboard POST /api/profile/{token}/auto-targets
      · bot post-onboarding auto-set (handlers/tool_executor.py)
      · bot set_macro_targets tool (handlers/tool_executor.py)

    Returns {calorie_target, protein_target, carb_target, fat_target, bmr,
    tdee, deficit_pct, goal} or None if essentials are missing (weight,
    height, age, sex).

    Logic (per macro-rules spec):
      Calories
        cut          : TDEE × 0.825  (mid of 10-25% deficit)
        bulk (lean)  : TDEE × 1.10   (mid of 5-15% surplus)
        performance  : TDEE × 1.05
        maintain     : TDEE
        health       : TDEE
      Macros
        cut          : 1.0 g/lb of GOAL weight protein,
                       0.3 g/lb of current weight fat,
                       carbs = remainder.
        bulk         : 0.9 g/lb current protein,
                       0.35 g/lb current fat, carbs = remainder.
        maintain     : 0.9 g/lb · 0.35 g/lb · carbs remainder.
        performance  : 0.9 g/lb protein, 25% kcal from fat, carbs remainder.
        health       : 30% kcal protein, 30% kcal fat, 40% carbs.
    """
    if not all([user.current_weight_kg, user.height_cm, user.age, user.sex]):
        return None

    w_kg = user.current_weight_kg
    h_cm = user.height_cm
    age = user.age
    sex = (user.sex or "").lower()

    if sex in ("m", "male", "man"):
        bmr = 10 * w_kg + 6.25 * h_cm - 5 * age + 5
    else:
        bmr = 10 * w_kg + 6.25 * h_cm - 5 * age - 161

    # Activity factor — DECOUPLED from training_experience.
    #
    # Earlier versions of this function used training_experience (years
    # lifting) to pick an activity multiplier. That was a category error:
    # "advanced" describes EXPERIENCE, not daily energy burn. A 5-year
    # lifter with a desk job burns roughly the same per day as a 2-year
    # lifter with the same routine. Conflating the two systematically
    # over-projected TDEE for the most common case (4-year lifter +
    # desk job) and produced cut targets that were too generous.
    #
    # Until we add an explicit `non_training_activity` field (sedentary /
    # lightly active / moderately active / very active — what the textbook
    # multipliers actually measure), we use a SINGLE conservative default
    # of 1.4 — slightly above textbook "lightly active" (1.375) to account
    # for the gym sessions themselves, but well below "moderate" (1.55)
    # which assumes a non-sedentary occupation.
    #
    # Per Helms (Muscle & Strength Pyramid) and Lyle McDonald: start LOW
    # and let real-world weight change tell you where TDEE actually is.
    # The user can edit the calorie target directly after the calc runs
    # if they know they're truly more (or less) active than the default.
    factor = 1.4

    tdee = bmr * factor
    goal = (user.primary_goal or "maintain").lower()
    w_lb = w_kg * 2.20462
    goal_lb = (user.goal_weight_kg * 2.20462) if user.goal_weight_kg else w_lb

    if goal == "cut":
        cals, deficit_pct = round(tdee * 0.825), -17.5
    elif goal == "bulk":
        cals, deficit_pct = round(tdee * 1.10), 10.0
    elif goal == "performance":
        cals, deficit_pct = round(tdee * 1.05), 5.0
    else:  # maintain, health
        cals, deficit_pct = round(tdee), 0.0

    if goal == "cut":
        protein = round(1.0 * goal_lb)
        fat = round(0.3 * w_lb)
    elif goal == "bulk":
        protein = round(0.9 * w_lb)
        fat = round(0.35 * w_lb)
    elif goal == "performance":
        protein = round(0.9 * w_lb)
        fat = round((cals * 0.25) / 9)
    elif goal == "health":
        protein = round((cals * 0.30) / 4)
        fat = round((cals * 0.30) / 9)
    else:  # maintain
        protein = round(0.9 * w_lb)
        fat = round(0.35 * w_lb)

    protein_cals = protein * 4
    fat_cals = fat * 9
    carb_cals = max(0, cals - protein_cals - fat_cals)
    carbs = round(carb_cals / 4)

    return {
        "calorie_target": cals,
        "protein_target": protein,
        "carb_target":    carbs,
        "fat_target":     fat,
        "bmr":            round(bmr),
        "tdee":           round(tdee),
        "deficit_pct":    deficit_pct,
        "goal":           goal,
    }


def calc_targets(user) -> dict | None:
    """Legacy shim — wraps compute_macro_targets() with the older return
    shape ({tdee, calories, protein, goal}). Existing callers keep working;
    the post-onboarding auto-set should migrate to compute_macro_targets()
    so carbs + fat get populated too."""
    t = compute_macro_targets(user)
    if not t:
        return None
    return {
        "tdee":     t["tdee"],
        "calories": max(t["calorie_target"], 1200),
        "protein":  max(t["protein_target"], 100),
        "goal":     t["goal"],
    }


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
