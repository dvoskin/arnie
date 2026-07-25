"""Category-aware portion ontology and conversion honesty (build order 16, 17).

"A handful" is not a number. A handful of blueberries is ~45 g, of almonds
~30 g, of popcorn ~8 g — mapping all three to one constant is confidently wrong
in two cases out of three.

The range is the useful part: it is what the materiality score reads to decide
whether the vagueness earns a question. Collapsing to the median throws away
the only signal that says "ask about this one".
"""
import pytest

from skills.nutrition.portions import (PORTION_ONTOLOGY, UnitKind, convert,
                                       detect_measure, detect_modifier,
                                       distribution_for, food_category)


# ── the same measure means different things ───────────────────────────────────
def test_a_handful_depends_entirely_on_the_food():
    berries = distribution_for("handful", "blueberries")
    almonds = distribution_for("handful", "almonds")
    popcorn = distribution_for("handful", "popcorn")
    assert berries.median_g > almonds.median_g > popcorn.median_g
    assert popcorn.median_g < 15      # a handful of popcorn is almost nothing


def test_a_slice_of_turkey_is_not_a_slice_of_pizza():
    turkey = distribution_for("slice", "turkey deli slice")
    pizza = distribution_for("slice", "pizza")
    assert pizza.median_g > turkey.median_g * 4


def test_a_spoonful_of_peanut_butter_is_not_a_spoonful_of_rice():
    pb = distribution_for("spoonful", "peanut butter")
    rice = distribution_for("spoonful", "rice")
    assert pb.median_g < rice.median_g


def test_peanut_butter_categorizes_as_nut_butter_not_nuts():
    """Longest fragment wins — otherwise "peanut butter" resolves as "nuts"
    and gets a 30 g handful estimate."""
    assert food_category("peanut butter") == "nut_butter"
    assert food_category("almonds") == "nuts"
    assert food_category("crunchy almond butter") == "nut_butter"


def test_an_unknown_food_gets_the_default_row_not_a_failure():
    dist = distribution_for("handful", "grandma's mystery mix")
    assert dist is not None
    assert dist.category.endswith("_handful")


# ── the range is the signal ───────────────────────────────────────────────────
def test_vague_measures_carry_wide_ranges_on_purpose():
    """"Some" carries almost no information. A confident narrow range here is
    the fake precision this module exists to refuse."""
    some = distribution_for("some", "rice")
    assert some.confidence < 0.4
    assert some.spread_g > 100


def test_a_well_understood_measure_is_narrower_and_more_confident():
    scoop = distribution_for("scoop", "whey protein powder")
    assert scoop.confidence > 0.75
    assert scoop.spread_g < 15


def test_wrong_but_narrow_would_suppress_the_question():
    """Sanity check on the calibration: every row's range must be non-trivial,
    because a narrow range silences the clarification that would fix it."""
    for measure, rows in PORTION_ONTOLOGY.items():
        for category, (median, lower, upper, conf) in rows.items():
            assert lower < median < upper, f"{measure}/{category}"
            assert upper - lower > 0, f"{measure}/{category}"
            assert 0.0 < conf <= 1.0, f"{measure}/{category}"


def test_uncertainty_scales_with_count():
    """Six uncertain slices are six times as uncertain as one — which is why
    "6 thin slices" earns a question that "1 thin slice" does not."""
    one = distribution_for("slice", "turkey deli slice")
    six = one.scaled(6)
    assert six.median_g == pytest.approx(one.median_g * 6)
    assert six.spread_g == pytest.approx(one.spread_g * 6, abs=0.5)


def test_size_modifiers_move_the_whole_distribution():
    small = distribution_for("handful", "blueberries", "small")
    big = distribution_for("handful", "blueberries", "large")
    assert small.median_g < big.median_g
    assert small.lower_g < big.lower_g       # bounds move too, proportionally
    assert small.upper_g < big.upper_g


# ── detection ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,measure", [
    ("a small handful", "handful"),
    ("a couple spoonfuls", "spoonful"),
    ("1 scoop", "scoop"),
    ("a drizzle of olive oil", "drizzle"),
    ("two slices", "slice"),
    ("a few bites", "bite"),
    ("a medium bowl", "bowl"),
    ("a plate of", "plate"),
    ("a little", "little"),
    ("some", "some"),
])
def test_measures_are_detected(text, measure):
    assert detect_measure(text) == measure


def test_a_precise_amount_has_no_vague_measure():
    assert detect_measure("200g") is None
    assert detect_measure("6 oz") is None


def test_modifiers_are_detected():
    assert detect_modifier("a small handful") == "small"
    assert detect_modifier("2 thick slices") == "thick"
    assert detect_modifier("a handful") == ""


# ── conversion honesty ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,grams", [
    ("200g", 200.0), ("6 oz", 170.1), ("1 lb", 453.6), ("0.5 kg", 500.0),
])
def test_mass_units_convert_exactly(text, grams):
    out = convert(text, "chicken")
    assert out.unit_kind is UnitKind.MASS
    assert out.mass_equivalent_g == pytest.approx(grams, abs=0.2)
    assert out.is_exact and out.conversion_source == "exact_mass"


def test_volume_is_exact_as_volume_but_is_not_a_mass():
    """Density is an assumption, not a conversion. 100 ml of oil is not 100 g,
    and the scaler refuses that step by design."""
    out = convert("1 cup", "milk")
    assert out.unit_kind is UnitKind.VOLUME
    assert out.amount == pytest.approx(236.6, abs=0.2)
    assert out.mass_equivalent_g is None
    assert out.is_exact


def test_a_vague_measure_carries_its_distribution():
    out = convert("a small handful", "blueberries")
    assert out.unit_kind is UnitKind.DESCRIPTIVE
    assert out.distribution is not None
    assert out.mass_equivalent_g == out.distribution.median_g
    assert out.conversion_confidence < 0.8       # never claimed as exact
    assert out.conversion_source.startswith("ontology:berries")


def test_six_deli_slices_records_count_mass_and_confidence():
    """The directive's case: not a bare 54 g that reads like a measurement."""
    out = convert("6 slices", "turkey deli slice")
    assert out.count == 6
    assert out.mass_equivalent_g is not None
    assert 0.5 < out.conversion_confidence < 0.9
    assert out.distribution.spread_g > 0


def test_a_count_with_a_known_product_unit_weight_converts_confidently():
    out = convert("2 bottles", "Core Power", unit_mass_g=414.0)
    assert out.unit_kind is UnitKind.COUNT
    assert out.mass_equivalent_g == 828.0
    assert out.conversion_confidence > 0.9
    assert out.conversion_source == "product_unit_weight"


def test_a_count_with_no_basis_reports_no_mass_at_all():
    """Inventing grams here is the fake precision the directive forbids. No
    mass, zero confidence, and a source that says why."""
    out = convert("2 servings", "grandma's mystery casserole")
    assert out.mass_equivalent_g is None
    assert out.conversion_confidence == 0.0
    assert out.conversion_source == "unknown_unit_weight"
    assert out.count == 2


def test_word_numbers_and_fractions_parse():
    assert convert("two slices", "bread").count == 2
    assert convert("half a bowl", "soup").amount == 0.5
    assert convert("a handful", "almonds").count == 1


def test_a_multi_unit_vague_portion_scales_the_distribution():
    one = convert("1 handful", "almonds")
    three = convert("3 handfuls", "almonds")
    assert three.mass_equivalent_g == pytest.approx(
        one.mass_equivalent_g * 3, abs=0.5)
    assert three.distribution.spread_g > one.distribution.spread_g
