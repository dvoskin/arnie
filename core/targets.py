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


def compute_macros_for_calorie_target(user, calorie_target: int) -> dict | None:
    """Given a manually-set calorie target, derive goal-aligned protein,
    carb, and fat grams. Same macro rules as compute_macro_targets(), but
    anchored on the user's chosen calorie level instead of TDEE-derived
    calories. Needs current_weight_kg + primary_goal at minimum.

    Returns {protein_target, carb_target, fat_target} or None if essentials
    are missing.
    """
    if not (user.current_weight_kg and calorie_target):
        return None
    cals = int(calorie_target)
    w_lb = user.current_weight_kg * 2.20462
    goal_lb = (user.goal_weight_kg * 2.20462) if user.goal_weight_kg else w_lb
    goal = (user.primary_goal or "maintain").lower()

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

    carb_cals = max(0, cals - protein * 4 - fat * 9)
    carbs = round(carb_cals / 4)
    return {"protein_target": protein, "carb_target": carbs, "fat_target": fat}


def compute_macro_split(calorie_target: int, protein_target: int, goal: str):
    """Derive carb + fat grams from calorie + protein targets using
    goal-specific ratios for the calories remaining after protein.

      bulk: 65/35 carb/fat   cut: 45/55   performance: 70/30
      maintain/health: 55/45 (balanced)

    Returns (carb_g, fat_g) or (None, None) when data is insufficient or
    protein alone fills almost all calories.
    """
    if not calorie_target or not protein_target:
        return None, None
    remaining = calorie_target - protein_target * 4
    if remaining <= 50:
        return None, None
    carb_frac = {"bulk": 0.65, "cut": 0.45, "performance": 0.70}.get(goal, 0.55)
    carb_g = round(remaining * carb_frac / 4)
    fat_g = round(remaining * (1 - carb_frac) / 9)
    return carb_g, fat_g


def sync_macros_after_change(user, prefs, changed_field: str) -> bool:
    """After a single macro target is edited, re-derive the others so that
    calories = protein*4 + carbs*4 + fat*9 stays self-consistent.

    Calories are the total energy budget; protein anchors first; carbs and
    fat absorb what's left. Behavior by field:
      calorie_target → re-derive all three macros from goal+weight rules
      protein_target → keep calories, split remainder into carbs/fat
                       using the goal-based carb/fat ratio
      carb_target    → keep calories+protein, fat = remainder / 9
      fat_target     → keep calories+protein, carbs = remainder / 4

    Mutates prefs in place. Returns True if dependent targets were written,
    False if there wasn't enough data to derive (e.g. calories not set, or
    protein alone already overshoots the calorie budget).
    """
    cal  = prefs.calorie_target
    pro  = prefs.protein_target
    carb = prefs.carb_target
    fat  = prefs.fat_target
    goal = (user.primary_goal or "maintain").lower()

    if changed_field == "calorie_target":
        if not cal:
            return False
        m = compute_macros_for_calorie_target(user, cal)
        if not m:
            return False
        prefs.protein_target = m["protein_target"]
        prefs.carb_target    = m["carb_target"]
        prefs.fat_target     = m["fat_target"]
        return True

    if changed_field == "protein_target":
        if not (cal and pro):
            return False
        c, f = compute_macro_split(cal, pro, goal)
        if c is None:
            return False
        prefs.carb_target = c
        prefs.fat_target  = f
        return True

    if changed_field == "carb_target":
        if not (cal and pro and carb is not None):
            return False
        remaining = cal - pro * 4 - carb * 4
        if remaining <= 0:
            return False
        prefs.fat_target = round(remaining / 9)
        return True

    if changed_field == "fat_target":
        if not (cal and pro and fat is not None):
            return False
        remaining = cal - pro * 4 - fat * 9
        if remaining <= 0:
            return False
        prefs.carb_target = round(remaining / 4)
        return True

    return False


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
