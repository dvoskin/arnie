"""Directive §1 and §9 — the premise of the multiplication, and who owns
"the user said so".

§9. Scaling is arithmetic, and arithmetic does not notice when its premise is
wrong. Every case here is a correct multiplication against a basis that did not
describe the source, which is why none of them are visible in any single field.

§1. Two implementations answered "did the user state this amount?" and they
disagreed on every fraction. The interpreter's amount reached the strict gate
as 0.75, "0.75" is not in "3/4 cup of rice", 0.75 is not 0.5 and it is not an
integer — so a portion the user stated exactly was classified as our inference
and they were asked to confirm their own words.
"""
import pytest

from skills.nutrition import sanity
from skills.nutrition.models import NormalizedQuantity, NutrientProfile, NutrientValue
from skills.nutrition.scaling import Per100g, PerServing


_UNITS = {"calories": "kcal", "sodium": "mg"}


def _profile(**kw):
    return NutrientProfile(values={
        k: NutrientValue(value=float(v), unit=_UNITS.get(k, "g"), source="t")
        for k, v in kw.items()})


def _fatal(findings):
    return [f.code for f in findings if f.is_fatal]


def _codes(findings):
    return [f.code for f in findings]


# ── §9: the premise ─────────────────────────────────────────────────────────

def test_a_per_100g_row_landing_whole_on_a_tablespoon():
    """One tablespoon of peanut butter logged as 588 calories, and two
    tablespoons as 588 as well — so answering the clarification changed
    nothing. 588 cal in 16 g is 36 cal/g, four times pure fat."""
    findings = sanity.check(
        _profile(calories=588, protein=25, carbs=20, fat=50),
        Per100g(), NormalizedQuantity(amount=1, unit="tbsp", grams=16.0))
    assert "energy_density_impossible" in _fatal(findings)


def test_olive_oil_is_not_refused_for_being_oil():
    """A per-100ml row through a 0.91 g/ml density lands olive oil at 9.7
    cal/g. It is a correct answer, and refusing at the ceiling would throw away
    exactly the foods that sit there."""
    findings = sanity.check(
        _profile(calories=131, fat=14.8), Per100g(),
        NormalizedQuantity(amount=1, unit="tbsp", grams=13.5))
    assert _fatal(findings) == []
    assert "energy_density_extreme" in _codes(findings)


def test_macros_that_cannot_add_up_to_the_calories():
    """Calories are a fixed function of the macros, so a row whose macros do
    not reach its own calorie figure is a row and a portion that do not belong
    together. Every field here is individually plausible; only the relationship
    between them is wrong.

    This is NOT the profile-flip detector. A wrong-row flip (roast turkey
    arriving as 614 cal / 0g protein / 123g carbs) is internally consistent to
    within 17% and Atwater will not see it — that one is caught upstream, by
    comparing the database read against the model's independent one.
    """
    findings = sanity.check(
        _profile(calories=400, protein=5, carbs=10, fat=2),
        Per100g(), NormalizedQuantity(amount=1, unit="serving", grams=120.0))
    assert "macro_energy_disagreement" in _codes(findings)


def test_macros_that_agree_raise_nothing():
    findings = sanity.check(
        _profile(calories=400, protein=30, carbs=40, fat=13),
        Per100g(), NormalizedQuantity(amount=1, unit="serving", grams=300.0))
    assert _codes(findings) == []


def test_a_plate_is_not_one_of_a_43g_labels_servings():
    """"One plate" arriving as one serving of a packaged label, then scaled by
    the plate's own estimated mass, counts the portion twice."""
    findings = sanity.check(
        _profile(calories=520, protein=20, carbs=60, fat=22),
        PerServing(serving_mass_g=43.0),
        NormalizedQuantity(amount=1, unit="plate", grams=400.0, count=1))
    assert "serving_count_mismatch" in _codes(findings)


def test_a_count_that_really_does_count_servings_is_quiet():
    findings = sanity.check(
        _profile(calories=200, protein=10, carbs=25, fat=7),
        PerServing(serving_mass_g=43.0),
        NormalizedQuantity(amount=2, unit="serving", grams=86.0, count=2))
    assert "serving_count_mismatch" not in _codes(findings)


def test_an_as_served_basis_is_exempt():
    """A restaurant estimate or the user's own saved regular defines the dish
    AS SERVED, so one helping genuinely is one serving however loosely it was
    described."""
    findings = sanity.check(
        _profile(calories=520), PerServing(serving_mass_g=43.0, as_served=True),
        NormalizedQuantity(amount=1, unit="plate", grams=400.0, count=1))
    assert "serving_count_mismatch" not in _codes(findings)


def test_absurd_totals_for_one_line_item():
    assert "item_calories_impossible" in _fatal(sanity.check(
        _profile(calories=8800), Per100g(),
        NormalizedQuantity(amount=1, unit="serving", grams=2000.0)))
    assert "item_mass_impossible" in _fatal(sanity.check(
        _profile(calories=1200), Per100g(),
        NormalizedQuantity(amount=1, unit="serving", grams=9000.0)))


def test_unknown_calories_check_nothing():
    """Unknown is not zero, and it is not a violation either."""
    assert sanity.check(_profile(protein=10), Per100g(),
                        NormalizedQuantity(amount=1, unit="g", grams=100.0)) == ()


def test_an_impossible_result_is_not_persisted_behind_a_warning():
    """Keeping it "with a warning" is what put 588 calories of peanut butter in
    a day's totals behind a warning nobody read."""
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import FoodResolutionRequest
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve

    request = FoodResolutionRequest(food_name="peanut butter", amount=1.0,
                                    unit="tbsp", raw_quantity="1 tbsp")
    # A per-SERVING row carrying the whole per-100g numbers — the shipped shape.
    candidate = Candidate(
        source="usda", tier=SourceTier.GENERIC_EXACT, name="Peanut butter",
        profile=_profile(calories=588, protein=25, carbs=20, fat=50),
        basis=PerServing(serving_mass_g=16.0, as_served=True),
        reported_grade=MatchGrade.EXACT)
    out = resolve(request, [candidate])
    assert out.nutrients.amount("calories") is None
    assert any("energy_density_impossible" in w for w in out.warnings)


# ── §1: one owner for "the user said so" ────────────────────────────────────

@pytest.mark.parametrize("message,amount,unit", [
    ("I had 3/4 cup of rice", 0.75, "cup"),
    ("two thirds of a cup of rice", 2 / 3, "cup"),
    ("I ate 1 1/2 cups of rice", 1.5, "cup"),
    ("one and a half bagels", 1.5, "bagel"),
    ("half a bagel", 0.5, "bagel"),
    ("6 oz chicken", 6.0, "oz"),
])
def test_a_stated_fraction_is_stated(message, amount, unit):
    """The friction was the disagreement between two parsers, not the
    strictness. Strict mode asked the user to confirm their own words."""
    from core.food_turn import _item_is_stated
    item = {"food": unit, "amount": amount, "unit": unit}
    assert _item_is_stated(item, message) is True


def test_a_converted_measure_is_still_ours():
    """"A scoop of peanut butter" arriving as 1 tbsp matches on the amount
    alone. Treating that as stated is the shipped failure — a 190-calorie
    assumption presented back as the user's own words."""
    from core.food_turn import _item_is_stated
    assert _item_is_stated(
        {"food": "peanut butter", "amount": 1, "unit": "tbsp"},
        "a scoop of peanut butter") is False


def test_the_clause_scan_does_not_reach_the_next_food():
    from core.food_turn import _item_is_stated
    assert _item_is_stated(
        {"food": "banana", "amount": 0.5, "unit": "banana"},
        "like 15 peanut m&m, half a banana and a scoop of peanut butter"
    ) is True
