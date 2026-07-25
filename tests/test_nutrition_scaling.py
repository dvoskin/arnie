"""Quantity normalization + the one scaling engine (work order step 6).

Two failure classes these close, both of which have shipped before:

  • forward-scaling mistakes, from adapters each doing their own per-100g
    arithmetic with their own assumptions;
  • confident wrong numbers, from inventing a mass for a portion that does
    not have one ("six thin deli slices").

The rule under all of it: when the bases cannot be reconciled, refuse. A
refusal becomes an unknown the clarification ladder can act on. A guess
becomes a number nobody can question.
"""
import pytest

from skills.nutrition.models import NormalizedQuantity, profile_from_values
from skills.nutrition.normalize import (normalize_quantity, piece_weight,
                                        vessel_volume)
from skills.nutrition.scaling import (Per100g, Per100ml, PerServing, PerUnit,
                                      ScalingRefused, scale_profile,
                                      scaling_uncertainty)


# ── normalization ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,grams", [
    ("100g", 100.0),
    ("6 oz", 170.1),
    ("1 lb", 453.6),
    ("250 grams", 250.0),
    ("0.5 kg", 500.0),
])
def test_mass_units_are_exact_conversions(raw, grams):
    q = normalize_quantity(raw, "chicken breast")
    assert q.grams == pytest.approx(grams, abs=0.2)
    assert q.uncertainty_g is None          # a conversion has no uncertainty


@pytest.mark.parametrize("raw,ml", [
    ("1 cup", 236.6),
    ("2 tbsp", 29.6),
    ("500ml", 500.0),
])
def test_volume_units_are_exact_conversions(raw, ml):
    q = normalize_quantity(raw, "milk")
    assert q.milliliters == pytest.approx(ml, abs=0.2)


def test_piece_counts_carry_an_estimate_and_its_spread():
    """"six thin deli slices" has no mass — it has an estimate and a spread,
    and the spread is what makes the estimate usable."""
    q = normalize_quantity("6 thin slices", "turkey deli slice")
    assert q.count == 6
    assert q.grams is not None and 60 < q.grams < 90     # thinned from 18g each
    assert q.uncertainty_g and q.uncertainty_g > 0
    assert any("estimated" in a for a in q.assumptions)


def test_an_unweighable_piece_says_so_instead_of_guessing():
    """No basis for a mass → no mass. A fabricated gram figure here is exactly
    the confident wrong number this layer exists to prevent."""
    q = normalize_quantity("2 servings", "grandma's mystery casserole")
    assert q.grams is None
    assert q.count == 2
    assert "portion mass unknown" in q.assumptions


def test_word_numbers_and_fractions_parse():
    assert normalize_quantity("two eggs", "egg").count == 2
    assert normalize_quantity("half a bagel", "bagel").count == 0.5
    assert normalize_quantity("a banana", "banana").count == 1


def test_size_modifiers_move_the_estimate():
    thin = normalize_quantity("1 thin slice", "bread slice").grams
    thick = normalize_quantity("1 thick slice", "bread slice").grams
    assert thin < thick


def test_piece_weight_is_none_for_unknown_foods():
    assert piece_weight("shawarma platter") is None


# ── scaling ───────────────────────────────────────────────────────────────────
def test_per_100g_scales_by_mass():
    profile = profile_from_values("usda", basis="per_100g",
                                  calories=165, protein=31, sodium=74)
    scaled = scale_profile(profile, Per100g(),
                           NormalizedQuantity(amount=200, unit="g", grams=200))
    assert scaled.amount("calories") == 330
    assert scaled.amount("protein") == 62.0
    assert scaled.amount("sodium") == 148.0


def test_per_serving_scales_by_serving_mass():
    """The 86 g of a 43 g-serving product is two servings — the case the
    review named."""
    profile = profile_from_values("off", basis="per_serving", calories=80,
                                  protein=8)
    scaled = scale_profile(profile, PerServing(serving_mass_g=43),
                           NormalizedQuantity(amount=86, unit="g", grams=86))
    assert scaled.amount("calories") == 160
    assert scaled.amount("protein") == 16.0


def test_per_unit_scales_by_count():
    profile = profile_from_values("user_label", basis="per_unit", calories=80,
                                  protein=8)
    scaled = scale_profile(profile, PerUnit(unit_mass_g=98),
                           NormalizedQuantity(amount=2, unit="bagel", count=2))
    assert scaled.amount("calories") == 160


def test_scaling_refuses_rather_than_guessing_a_missing_basis():
    """A per-serving panel with no serving mass cannot answer "how much in
    86 g". Refusing produces an unknown; guessing produces a wrong number."""
    profile = profile_from_values("off", basis="per_serving", calories=80)
    with pytest.raises(ScalingRefused):
        scale_profile(profile, PerServing(),
                      NormalizedQuantity(amount=86, unit="g", grams=86))


def test_grams_are_never_silently_read_as_millilitres():
    """100 g of oil is not 100 ml. Density is an assumption, not a conversion,
    so the engine refuses instead of applying water density."""
    profile = profile_from_values("off", basis="per_100ml", calories=90)
    with pytest.raises(ScalingRefused):
        scale_profile(profile, Per100ml(),
                      NormalizedQuantity(amount=100, unit="g", grams=100))


def test_every_field_scales_by_the_same_factor():
    """A field scaling differently from its neighbours means the basis was
    wrong — a bug to surface, not to route around."""
    profile = profile_from_values("usda", basis="per_100g", calories=100,
                                  protein=10, carbs=20, fat=5, sodium=200)
    scaled = scale_profile(profile, Per100g(),
                           NormalizedQuantity(amount=250, unit="g", grams=250))
    assert scaled.amount("calories") == 250
    assert scaled.amount("protein") == 25.0
    assert scaled.amount("carbs") == 50.0
    assert scaled.amount("fat") == 12.5
    assert scaled.amount("sodium") == 500.0


def test_unknown_fields_stay_unknown_through_scaling():
    """Scaling multiplies what is known. It never fills a gap — an unknown
    sodium must not become 0 mg because the arithmetic wanted a number."""
    profile = profile_from_values("off", basis="per_100g", calories=100,
                                  protein=10)
    scaled = scale_profile(profile, Per100g(),
                           NormalizedQuantity(amount=200, unit="g", grams=200))
    assert "sodium" in scaled.unknown()
    assert scaled.amount("sodium") is None
    assert "sodium" not in scaled.as_dict()


def test_provenance_survives_scaling():
    profile = profile_from_values("usda", basis="per_100g", confidence=0.9,
                                  source_id="fdc-123", calories=165)
    scaled = scale_profile(profile, Per100g(),
                           NormalizedQuantity(amount=200, unit="g", grams=200))
    v = scaled.get("calories")
    assert v.source == "usda" and v.source_id == "fdc-123"
    assert v.confidence == 0.9
    # Marked as a portion so nothing downstream can scale it a second time.
    assert v.basis == "per_portion"


def test_uncertainty_becomes_a_calorie_span():
    """"six thin deli slices" ±spread → the calories that ride on the guess.
    That span is what the strictness ladder decides on."""
    profile = profile_from_values("usda", basis="per_100g", calories=150)
    q = normalize_quantity("6 thin slices", "turkey deli slice")
    span = scaling_uncertainty(profile, Per100g(), q)
    assert span is not None and span > 0


def test_no_uncertainty_reported_for_an_exact_portion():
    profile = profile_from_values("usda", basis="per_100g", calories=150)
    q = normalize_quantity("200g", "chicken breast")
    assert scaling_uncertainty(profile, Per100g(), q) is None


# ── a count is not automatically a serving ────────────────────────────────────
# "One plate of pasta" arrives as an estimated 400 g AND count=1. Reading the
# count as one of a packaged label's servings threw the estimate away and
# reported a container as a package, at whatever the label's serving happened to
# be. A count may multiply a per-serving source only when it counts that
# source's own unit — see NormalizedQuantity.count_basis and PerServing.as_served.
@pytest.mark.parametrize("raw,food", [
    ("1 plate", "pasta"),
    ("one bowl", "rice"),
    ("1 scoop", "protein powder"),
    ("a handful", "almonds"),
    ("a large glass", "orange juice"),
])
def test_a_vague_helping_is_not_a_measured_serving(raw, food):
    """A measured label (branded, no serving mass) cannot answer "how much is a
    plate". Refusing surfaces an unknown; multiplying by 1 invents a number."""
    q = normalize_quantity(raw, food)
    assert q.count is not None, "the count still carries the user's intent"
    assert not q.count_is_serving_compatible, f"{raw} {food} read as a serving"
    label = profile_from_values("off", basis="per_serving", calories=200)
    with pytest.raises(ScalingRefused):
        scale_profile(label, PerServing(), q)


@pytest.mark.parametrize("raw,food", [
    ("1 bottle", "Fairlife core power"),
    ("1 bar", "Barebells caramel cashew"),
    ("2 bagels", "bagel"),
    ("1 can", "Diet Coke"),
    ("6 slices", "turkey deli slice"),
])
def test_a_real_unit_count_still_scales_by_count(raw, food):
    """The other half of the fix. A sealed container and a discrete piece ARE
    the label's unit, and dropping their counts would turn every packaged food
    with a per-serving label into an unscalable portion."""
    q = normalize_quantity(raw, food)
    assert q.count_is_serving_compatible, f"{raw} {food} lost its unit count"
    label = profile_from_values("off", basis="per_serving", calories=200)
    scaled = scale_profile(label, PerServing(), q)
    assert scaled.amount("calories") == pytest.approx(200 * q.count)


def test_the_food_can_be_its_own_vague_measure():
    """"1 bowl" of a burrito bowl counts the product, not a helping of it. The
    deny-list yields to the food name, or every Chipotle order became unscalable."""
    q = normalize_quantity("1 bowl", "Chipotle burrito bowl")
    assert q.count_is_serving_compatible
    label = profile_from_values("web_label", basis="per_serving", calories=630)
    assert scale_profile(label, PerServing(), q).amount("calories") == 630


def test_a_dish_as_served_accepts_a_vague_helping():
    """A restaurant estimate, a provisional guess or the user's own regular
    describes the dish AS SERVED, so one plate of it genuinely is one serving.
    Only a measured branded/USDA serving refuses."""
    q = normalize_quantity("1 plate", "restaurant carbonara")
    assert not q.count_is_serving_compatible
    label = profile_from_values("web_label", basis="per_serving", calories=800)
    assert scale_profile(label, PerServing(as_served=True),
                         q).amount("calories") == 800


def test_an_estimated_helping_prefers_the_mass_it_estimated():
    """When the label DOES state a serving mass, the plate's estimated grams are
    the scaling currency — 400 g against a 100 g serving is four servings, not
    one."""
    q = normalize_quantity("1 plate", "pasta")
    assert q.grams == pytest.approx(400.0)
    label = profile_from_values("off", basis="per_serving", calories=100)
    scaled = scale_profile(label, PerServing(serving_mass_g=100), q)
    assert scaled.amount("calories") == pytest.approx(400)


def test_per_unit_refuses_an_estimated_helping_without_a_unit_mass():
    q = normalize_quantity("1 bowl", "rice")
    with pytest.raises(ScalingRefused):
        scale_profile(profile_from_values("off", basis="per_unit", calories=90),
                      PerUnit(), q)


# ── the vessel is the vessel, not the adjective ───────────────────────────────
def test_a_size_word_belongs_to_the_vessel_not_its_name():
    """"large glass" recorded the vessel as "large" and estimated it at a plain
    glass's 250 ml, so the size word the user bothered to say changed nothing."""
    name, ml, spread = vessel_volume("large glass")
    assert name == "glass"
    plain_name, plain_ml, plain_spread = vessel_volume("glass")
    assert plain_name == "glass"
    assert ml > plain_ml and spread > plain_spread

    q = normalize_quantity("a large glass", "orange juice")
    assert q.milliliters == pytest.approx(337.5)
    assert any("glass estimated at" in a for a in q.assumptions)


def test_the_disclosure_keeps_the_users_own_wording():
    """The basis uses the canonical vessel; the sentence shown to the user keeps
    the plural they typed."""
    q = normalize_quantity("2 bottles", "sparkling water")
    assert any("bottles estimated at 500ml" in a for a in q.assumptions)
