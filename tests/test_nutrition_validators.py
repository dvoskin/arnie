"""Pre-commit validation (work order step 8).

Every nutrient incident this system has had shares a shape: a candidate that
was plausible on the axis someone checked and wrong on an axis nobody did.
These tests are written from those incidents, not from the happy path.
"""
import pytest

from skills.nutrition.models import NormalizedQuantity, profile_from_values
from skills.nutrition.validators import (DOWNGRADE, PASS, REJECT,
                                         category_for, sources_disagree,
                                         strip_out_of_bounds,
                                         validate_bounds, validate_energy,
                                         validate_identity, validate_serving)


# ── identity ──────────────────────────────────────────────────────────────────
def test_a_concentrated_cousin_is_rejected():
    """The sodium-bomb failure class: "garlic" matched to garlic POWDER. The
    identity reads right and the numbers are 20×."""
    v = validate_identity("garlic", "garlic powder")
    assert v.outcome == REJECT and v.reason == "concentrated_form"


def test_asking_for_the_concentrate_is_not_a_mismatch():
    assert validate_identity("garlic powder", "garlic powder, dried").ok


def test_a_brand_conflict_is_rejected():
    v = validate_identity("bagel", "Everything Bagel",
                          requested_brand="Royo", candidate_brand="Thomas")
    assert v.outcome == REJECT and v.reason == "brand_conflict"


def test_a_flavour_conflict_is_rejected():
    v = validate_identity("Royo bagel", "Royo bagel",
                          requested_variant="plain", candidate_variant="everything")
    assert v.outcome == REJECT and v.reason == "variant_conflict"


def test_a_preparation_mismatch_downgrades_rather_than_rejects():
    """Raw vs roasted is a real difference, but the candidate is still about
    the right food — worth keeping at lower confidence."""
    v = validate_identity("chicken breast, roasted", "chicken breast, raw")
    assert v.outcome == DOWNGRADE and v.reason == "preparation_mismatch"


def test_unrelated_foods_are_rejected():
    assert validate_identity("Royo bagel", "beef stew").outcome == REJECT


# ── energy consistency ────────────────────────────────────────────────────────
def test_macros_that_do_not_add_up_are_caught():
    profile = profile_from_values("off", calories=100, protein=30, carbs=40,
                                  fat=20)          # implies 460 kcal
    assert validate_energy(profile).outcome == REJECT


def test_small_drift_passes_because_fibre_and_rounding_are_real():
    profile = profile_from_values("off", calories=200, protein=10, carbs=20,
                                  fat=8)           # implies 192 kcal
    assert validate_energy(profile).ok


def test_energy_is_not_checked_when_a_macro_is_unknown():
    """Treating unknown as zero would flag every partially-known profile,
    which teaches everyone to ignore the check."""
    profile = profile_from_values("off", calories=200, protein=10, carbs=20)
    assert validate_energy(profile).ok        # fat unknown → no verdict


# ── serving basis ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mass", [0, -5, 0.2, 4000])
def test_impossible_serving_masses_are_rejected(mass):
    assert validate_serving(mass).outcome == REJECT


def test_a_normal_serving_passes():
    assert validate_serving(43.0, servings_per_package=6).ok


def test_an_absurd_portion_downgrades():
    q = NormalizedQuantity(amount=6000, unit="g", grams=6000)
    assert validate_serving(43.0, quantity=q).outcome == DOWNGRADE


# ── nutrient bounds ───────────────────────────────────────────────────────────
def test_the_sodium_incident_is_caught():
    """20,378 mg per 100 g — the actual number from the seasoning match."""
    profile = profile_from_values("usda", basis="per_100g", calories=330,
                                  sodium=20378)
    verdict, fields = validate_bounds(profile, "chicken breast",
                                      basis="per_100g")
    assert verdict.outcome == DOWNGRADE and "sodium" in fields


def test_a_condiment_is_allowed_to_be_salty():
    """Soy sauce really does carry ~6,000 mg per 100 g. A category-blind
    ceiling would reject the correct answer."""
    profile = profile_from_values("usda", basis="per_100g", calories=60,
                                  sodium=5500)
    verdict, fields = validate_bounds(profile, "soy sauce", basis="per_100g")
    assert verdict.ok and fields == ()
    assert category_for("soy sauce") == "condiment"


def test_impossible_calories_condemn_the_whole_candidate():
    profile = profile_from_values("usda", basis="per_100g", calories=4000)
    verdict, _ = validate_bounds(profile, "rice", basis="per_100g")
    assert verdict.outcome == REJECT


def test_one_wild_micro_does_not_condemn_good_macros():
    profile = profile_from_values("usda", basis="per_100g", calories=200,
                                  protein=20, sodium=20378)
    verdict, fields = validate_bounds(profile, "chicken", basis="per_100g")
    assert verdict.outcome == DOWNGRADE
    cleaned = strip_out_of_bounds(profile, fields)
    assert cleaned.amount("calories") == 200      # macros survive
    assert cleaned.amount("sodium") is None       # the bad field is unknown…
    assert "sodium" not in cleaned.as_dict()      # …not zero


def test_bounds_are_only_meaningful_per_100g():
    """A portion legitimately carries any amount if it is large enough.
    Checking a portion against per-100g ceilings is the wrong yardstick."""
    profile = profile_from_values("usda", basis="per_portion", sodium=20378)
    verdict, fields = validate_bounds(profile, "chicken", basis="per_portion")
    assert verdict.ok and fields == ()


def test_unknown_is_never_out_of_bounds():
    profile = profile_from_values("usda", basis="per_100g", calories=200)
    verdict, fields = validate_bounds(profile, "chicken", basis="per_100g")
    assert verdict.ok and fields == ()


# ── cross-source agreement ────────────────────────────────────────────────────
def test_material_disagreement_is_reported():
    a = profile_from_values("off", calories=80, protein=8)
    b = profile_from_values("usda", calories=260, protein=10)
    gap = sources_disagree(a, b)
    assert gap["calorie_span"] == 180.0
    assert gap["options"] == (80.0, 260.0)


def test_close_enough_is_not_a_disagreement():
    """Below the threshold the choice is free, and asking would be friction
    for nothing."""
    a = profile_from_values("off", calories=250)
    b = profile_from_values("usda", calories=265)
    assert sources_disagree(a, b) is None


def test_a_missing_calorie_value_is_not_a_disagreement():
    a = profile_from_values("off", protein=8)
    b = profile_from_values("usda", calories=260)
    assert sources_disagree(a, b) is None
