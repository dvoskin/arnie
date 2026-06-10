"""Mifflin-St Jeor target calculation + dependent-macro sync."""
from types import SimpleNamespace
from core.targets import (
    calc_targets,
    compute_macros_for_calorie_target,
    compute_macro_split,
    sync_macros_after_change,
)


def _user(**kw):
    base = dict(current_weight_kg=80, height_cm=180, age=30, sex="male",
                primary_goal="maintain", training_experience="intermediate",
                goal_weight_kg=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_returns_none_when_stats_missing():
    assert calc_targets(_user(height_cm=None)) is None
    assert calc_targets(_user(age=None)) is None
    assert calc_targets(_user(sex=None)) is None


def test_maintain_targets_reasonable():
    t = calc_targets(_user(primary_goal="maintain"))
    assert t is not None
    # BMR ~1780, x1.4 TDEE ~2492 -> maintain calories in a sane band
    assert 2200 <= t["calories"] <= 3100
    assert t["protein"] > 100
    assert t["goal"] == "maintain"


def test_cut_is_below_maintain_and_bulk_above():
    maint = calc_targets(_user(primary_goal="maintain"))["calories"]
    cut = calc_targets(_user(primary_goal="cut"))["calories"]
    bulk = calc_targets(_user(primary_goal="bulk"))["calories"]
    assert cut < maint < bulk
    # cut applies ~17.5% deficit on TDEE ~2492 (~436); bulk +10% (~249)
    assert 300 <= maint - cut <= 550
    assert 150 <= bulk - maint <= 350


def test_sex_changes_bmr():
    m = calc_targets(_user(sex="male"))["calories"]
    f = calc_targets(_user(sex="female"))["calories"]
    assert m > f  # male BMR constant is +5 vs -161


# ── Dependent-macro sync (dashboard PATCH path) ──────────────────────────────

def _prefs(**kw):
    base = dict(calorie_target=None, protein_target=None,
                carb_target=None, fat_target=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_calorie_target_re_derives_all_three_macros():
    """User sets calories alone → protein/carbs/fat all derived from goal+weight."""
    u = _user(primary_goal="maintain", current_weight_kg=80)
    m = compute_macros_for_calorie_target(u, 2500)
    # protein 0.9 * 176lb = 159, fat 0.35 * 176lb = 62, carbs = remainder
    assert m == {"protein_target": 159, "carb_target": 326, "fat_target": 62}


def test_compute_macros_returns_none_without_weight():
    assert compute_macros_for_calorie_target(_user(current_weight_kg=None), 2500) is None
    assert compute_macros_for_calorie_target(_user(), None) is None


def test_protein_change_splits_remainder_by_goal_ratio():
    """Protein change → carbs/fat split using goal-specific ratio."""
    # maintain: 55/45 carb/fat split of the calories after protein
    assert compute_macro_split(2500, 200, "maintain") == (234, 85)
    # cut: 45/55 — fat-leaning
    c, f = compute_macro_split(2500, 200, "cut")
    assert c < 234 and f > 85
    # bulk: 65/35 — carb-leaning
    c, f = compute_macro_split(2500, 200, "bulk")
    assert c > 234 and f < 85


def test_compute_macro_split_bails_when_protein_overshoots():
    assert compute_macro_split(2500, 700, "maintain") == (None, None)  # remaining < 50
    assert compute_macro_split(None, 200, "maintain") == (None, None)
    assert compute_macro_split(2500, None, "maintain") == (None, None)


def test_sync_calorie_field_writes_all_three():
    u = _user(primary_goal="maintain")
    p = _prefs(calorie_target=2500)
    assert sync_macros_after_change(u, p, "calorie_target") is True
    assert p.protein_target == 159 and p.carb_target == 326 and p.fat_target == 62


def test_sync_protein_field_preserves_calories():
    u = _user(primary_goal="maintain")
    p = _prefs(calorie_target=2500, protein_target=220)
    assert sync_macros_after_change(u, p, "protein_target") is True
    # calories untouched, carbs+fat sum back to ~remaining (within rounding)
    assert p.calorie_target == 2500 and p.protein_target == 220
    assert abs(2500 - (220 * 4 + p.carb_target * 4 + p.fat_target * 9)) <= 10


def test_sync_carb_field_absorbs_into_fat():
    u = _user(primary_goal="maintain")
    p = _prefs(calorie_target=2500, protein_target=200, carb_target=100, fat_target=80)
    assert sync_macros_after_change(u, p, "carb_target") is True
    # remaining = 2500 - 800 - 400 = 1300 → fat = 144
    assert p.fat_target == round((2500 - 800 - 400) / 9)
    assert p.carb_target == 100  # untouched
    assert p.protein_target == 200  # untouched


def test_sync_fat_field_absorbs_into_carbs():
    u = _user(primary_goal="maintain")
    p = _prefs(calorie_target=2500, protein_target=200, carb_target=300, fat_target=100)
    assert sync_macros_after_change(u, p, "fat_target") is True
    # remaining = 2500 - 800 - 900 = 800 → carbs = 200
    assert p.carb_target == round((2500 - 800 - 900) / 4)
    assert p.fat_target == 100  # untouched
    assert p.protein_target == 200  # untouched


def test_sync_no_op_when_calorie_unset():
    """Without a calorie anchor, none of the dependent rules can fire."""
    u = _user()
    p = _prefs(protein_target=200, carb_target=300, fat_target=80)
    assert sync_macros_after_change(u, p, "protein_target") is False
    assert p.carb_target == 300 and p.fat_target == 80  # untouched


def test_sync_no_op_when_protein_overshoots_calories():
    u = _user()
    p = _prefs(calorie_target=900, protein_target=300)
    # protein alone = 1200 cals > 900 → remainder negative → bail
    assert sync_macros_after_change(u, p, "protein_target") is False


def test_low_calorie_scales_protein_and_fat_to_fit():
    """When goal-rule protein+fat exceeds the calorie budget (aggressive
    cut at heavy body weight), scale BOTH down proportionally so the
    macro sum lands at the calorie target. Previously this returned
    incoherent values: target=800 with macros summing to 1194."""
    u = _user(primary_goal="maintain", current_weight_kg=80)
    m = compute_macros_for_calorie_target(u, 800)
    sum_kcal = m["protein_target"] * 4 + m["carb_target"] * 4 + m["fat_target"] * 9
    # rounding may push 1-2 kcal over; the macro sum must NOT wildly
    # exceed the budget the way pre-fix did (1194 vs 800).
    assert sum_kcal <= 810, f"low-cal incoherence: {m} sums to {sum_kcal}"
    # carbs collapse to near-zero (rounding may leave 1-2g of residual remainder)
    assert m["carb_target"] <= 2
    # Protein and fat scaled in fixed proportion: maintain has p=0.9*lb
    # and f=0.35*lb → ratio p_cal/f_cal = (159*4)/(62*9) ≈ 1.14, preserved
    # after scaling (within rounding).
    ratio = (m["protein_target"] * 4) / (m["fat_target"] * 9)
    assert 1.05 <= ratio <= 1.25
