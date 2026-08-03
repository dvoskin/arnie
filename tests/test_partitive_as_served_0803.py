"""A part of a dish is not one serving of it.

Prod 2026-08-03, fe#2719: "I also had a special roll ... just 1 piece tho".
The interpreter estimated 130-190 cal for one piece — correct. A restaurant web
lookup returned the WHOLE roll (per100 200 cal/g-basis, empty serving panel),
`web_label_candidate` marked it `as_served=True`, and `_factor` turned that into
`return float(count)` = 1.0. Committed: 460 cal for one piece.

The plausibility backstop cannot catch this class — 460 against ~160 is 2.9x,
under the 5x cap, and the cap cannot be lowered because 2-5x is where the real
corrections live. The checkable signal is not magnitude, it is that the unit the
user said names a PART of the object the lookup priced.
"""
import dataclasses

import pytest

from skills.nutrition.candidates import web_label_candidate
from skills.nutrition.models import FoodResolutionRequest
from skills.nutrition.normalize import is_partitive_unit
from skills.nutrition.scaling import PerServing, ScalingRefused, _factor


ROLL_HIT = {"name": "Special Roll (tuna, mango, cucumber, avocado, spicy mayo)",
            "calories": 460, "protein": 19.0, "carbs": 43.0, "fat": 23.0,
            "confidence": 0.6}


def _request(unit: str) -> FoodResolutionRequest:
    return FoodResolutionRequest(
        food_name="Special Roll (tuna, mango, cucumber, avocado, spicy mayo)",
        amount=1.0, unit=unit, raw_quantity=f"1 {unit}")


@pytest.mark.parametrize("unit", ["piece", "pieces", "slice", "bite", "wedge"])
def test_partitive_units_are_recognised(unit):
    assert is_partitive_unit(unit)


@pytest.mark.parametrize("unit", ["plate", "bowl", "order", "serving", "roll",
                                  "burrito", "g", ""])
def test_whole_units_are_not_partitive(unit):
    """`serving` is the load-bearing one: `count_units_compatible` holds it
    interchangeable with `piece`, so this cannot be derived from that."""
    assert not is_partitive_unit(unit)


def test_a_piece_does_not_claim_the_dish_as_served():
    cand = web_label_candidate(ROLL_HIT, _request("piece"))
    assert cand is not None
    assert cand.basis.as_served is False, (
        "one piece of a roll is not one serving of the roll")


def test_a_helping_still_claims_the_dish_as_served():
    """The behaviour as-served exists for must survive: 'a plate of pad thai'
    IS one helping of the dish however loosely it was described."""
    cand = web_label_candidate(ROLL_HIT, _request("plate"))
    assert cand.basis.as_served is True


ROLL = "Special Roll (tuna, mango, cucumber, avocado, spicy mayo)"


def test_the_piece_refuses_to_scale_rather_than_pricing_the_whole_roll():
    """The fix's real outcome, through the REAL normalization path — building a
    NormalizedQuantity by hand would silently default `unit_is_fraction` and
    test nothing. A refusal here leaves the interpreter's own 130-190 standing
    instead of overriding it with 460."""
    from skills.nutrition.normalize import normalize_quantity

    consumed = normalize_quantity("1 piece", ROLL)
    assert consumed.unit_is_fraction, "one piece of a roll is a fraction of it"
    cand = web_label_candidate(ROLL_HIT, _request("piece"))
    with pytest.raises(ScalingRefused):
        _factor(cand.basis, consumed)


def test_a_helping_still_scales_to_one_serving():
    from skills.nutrition.normalize import normalize_quantity

    consumed = normalize_quantity("1 plate", "pad thai")
    assert not consumed.unit_is_fraction
    cand = web_label_candidate(ROLL_HIT, _request("plate"))
    assert _factor(cand.basis, consumed) == 1.0


def test_the_unit_that_IS_the_product_still_counts_units():
    """The case that killed the first two attempts at this fix: a TURKEY DELI
    SLICE is the product, so counting slices of it counts units."""
    from skills.nutrition.normalize import normalize_quantity

    consumed = normalize_quantity("6 slices", "turkey deli slice")
    assert not consumed.unit_is_fraction
    assert _factor(PerServing(), consumed) == 6.0


def test_an_enumerated_panel_still_prices_a_fraction():
    """And the case that killed the third: "15 pieces" IS a fraction of peanut
    m&ms, but a panel reading "35 g (12 pieces)" knows what one piece weighs,
    so a mass resolves and the count never becomes the multiplier. The refusal
    must stay scoped to sources that state no panel at all."""
    from skills.nutrition.normalize import normalize_quantity

    consumed = normalize_quantity("15 pieces", "peanut m&ms")
    assert consumed.unit_is_fraction
    priced = dataclasses.replace(consumed, grams=43.75)
    assert _factor(PerServing(serving_mass_g=35.0),
                   priced) == pytest.approx(43.75 / 35.0)


def test_a_branded_label_is_unaffected():
    """Branded servings are MEASURED — the gate is only about a restaurant
    lookup asserting its dish is whatever helping the user described."""
    req = FoodResolutionRequest(food_name="Barebells bar", amount=1.0,
                                unit="piece", brand="Barebells",
                                is_packaged=True, raw_quantity="1 piece")
    cand = web_label_candidate(ROLL_HIT, req)
    assert cand.basis.as_served is False
