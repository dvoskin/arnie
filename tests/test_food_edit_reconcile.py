"""Dashboard-edit macro/calorie coherence — api.food_edit._reconcile_macros.

The iOS editor can ship a quantity rescale and a direct calorie edit in one
PATCH (Danny's truffle fries: 80 cal with P5/C25/F27 ≈ 363 implied). Stored
rows must stay internally consistent; calories are the user's intent anchor.
"""
from api.food_edit import _reconcile_macros


BEFORE = {"name": "Fries", "quantity": "5.5 fries",
          "calories": 375, "protein": 4, "carbs": 30, "fats": 26}


def test_calorie_edit_scales_macros_onto_the_anchor():
    fixed = _reconcile_macros(BEFORE, {"calories": 80, "protein": 5,
                                       "carbs": 25, "fats": 27,
                                       "quantity": "5.5 fries"})
    implied = 4 * fixed["protein"] + 4 * fixed["carbs"] + 9 * fixed["fats"]
    assert fixed["calories"] == 80
    assert 0.7 <= 80 / implied <= 1.3


def test_macro_edit_without_calories_recomputes_calories():
    fixed = _reconcile_macros(BEFORE, {"protein": 40, "carbs": 5, "fats": 2})
    assert fixed["calories"] == round(4 * 40 + 4 * 5 + 9 * 2)


def test_coherent_edits_pass_through_untouched():
    changes = {"calories": 200, "protein": 20, "carbs": 20, "fats": 4}
    assert _reconcile_macros(BEFORE, changes) == changes


def test_cosmetic_edits_never_touch_numbers():
    changes = {"parsed_food_name": "Truffle Fries"}
    assert _reconcile_macros(BEFORE, changes) == changes
