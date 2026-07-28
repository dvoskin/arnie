"""A shipped card read "Kazunori Hand Roll Set (6 piece) — 4404 cal · 0g protein".

Six hand rolls, against a true ~1,200 cal and ~54 g protein. The coaching was
then authored FROM that row — "that sashimi was mostly fat", which is exactly
what 0 g protein means — and the meal totalled 4,504 cal / 14 g protein with
"2,946 cal over · 158g protein short" underneath it.

When the user pushed back, the model answered 1,200 / 54 immediately. The right
number was never in doubt; the write path preferred the wrong one.

Two independent holes let it through, and this pins both.
"""
from core.food_intelligence import analyze

#: A label-grade row for a DIFFERENT food: calorie-dense, no protein.
WRONG_ROW = {"fdc_id": None, "name": "hand roll set", "_match": "likely",
             "basis": "per_100g",
             "per100g": {"calories": 420, "protein": 0.0, "carbs": 45.0,
                         "fat": 26.0}}


def test_a_row_that_zeroes_protein_does_not_overwrite_the_model():
    """The estimate path keeps the model's CALORIES, then "a label may correct,
    not only fill" overwrote its protein with the row's 0 g — unconditionally,
    because a label-grade row is `_trustworthy`.

    The mass path already refuses a match that collapses the dominant macro.
    This path had no such check, so the same wrong row was refused when it
    arrived with a mass and accepted when it arrived without one.
    """
    r = analyze("Kazunori Hand Roll Set", "6 pieces", 1200, 54, 120, 30,
                off_candidate=WRONG_ROW, is_packaged=True)
    assert r.protein == 54.0, "the model's protein must survive"
    assert r.calories == 1200


def test_a_genuine_correction_still_lands():
    """Narrow on purpose. A row that merely DISAGREES keeps its correction —
    only the erasure of a macro the model reported substantially is refused."""
    label = {"fdc_id": 3, "name": "greek yogurt", "_match": "exact",
             "basis": "per_100g",
             "per100g": {"calories": 59, "protein": 10.0, "carbs": 3.6,
                         "fat": 0.4}}
    r = analyze("greek yogurt", "170 g", 100, 15, 4, 1,
                off_candidate=label, is_packaged=True)
    assert r.protein == 17.0, "the label's 10g/100g must reach the card"


def test_a_food_that_really_has_no_protein_is_untouched():
    """0 g is not a flip when the model never claimed otherwise. Oil is the
    case the guard must not break."""
    oil = {"fdc_id": 4, "name": "olive oil", "_match": "exact",
           "basis": "per_100g",
           "per100g": {"calories": 884, "protein": 0.0, "carbs": 0.0,
                       "fat": 100.0}}
    r = analyze("olive oil", "1 tbsp", 120, 0, 0, 14,
                off_candidate=oil, is_packaged=True)
    assert r.protein == 0.0


def test_an_enriched_row_may_not_multiply_the_estimate():
    """The demotion tested ONE DIRECTION. `cal < 0.7 * model` catches a row
    that undercuts; a row that OVERSTATES by 4x was committed in silence.

    The asymmetry was argued for — the model undercounts ~19%, so upward
    correction is usually right — but 2.5x is not a correction of a 19% bias,
    it is a different food.
    """
    huge = {"fdc_id": 1, "description": "x", "_match": "exact",
            "basis": "per_100g",
            "per100g": {"calories": 500, "protein": 40.0, "carbs": 10.0,
                        "fat": 20.0}}
    r = analyze("something", "600 g", 400, 30, 20, 12, usda_candidate=huge)
    assert r.calories == 400, "a 7.5x jump is a wrong row, not a correction"
    assert r.source == "estimate"


def test_ordinary_upward_correction_survives():
    """The whole reason the bound is loose: enrichment correcting the model's
    ~19% undercount is the feature, not the bug."""
    usda = {"fdc_id": 2, "description": "Chicken breast", "_match": "exact",
            "basis": "per_100g",
            "per100g": {"calories": 165, "protein": 31.0, "carbs": 0.0,
                        "fat": 3.6}}
    r = analyze("chicken breast", "200 g", 260, 45, 0, 6, usda_candidate=usda)
    assert r.calories == 330 and r.source == "usda"
