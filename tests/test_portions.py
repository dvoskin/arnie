"""Category-aware portion ontology and conversion honesty (build order 16, 17).

"A handful" is not a number. A handful of blueberries is ~45 g, of almonds
~30 g, of popcorn ~8 g — mapping all three to one constant is confidently wrong
in two cases out of three.

The range is the useful part: it is what the materiality score reads to decide
whether the vagueness earns a question. Collapsing to the median throws away
the only signal that says "ask about this one".
"""
import pytest

from skills.nutrition.portions import (FOOD_CATEGORIES, FORM_ALIASES,
                                       PORTION_ONTOLOGY, UnitKind, convert,
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
    # Source now carries the specificity tier that answered.
    assert out.conversion_source == "ontology:category:berries_handful"


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


# ── form-specific distributions above the broad fallbacks ─────────────────────
# The directive: retain the broad vague-quantity ranges, but progressively
# replace them with category-AND-form-specific distributions. So the fallbacks
# must stay, the form rows must sit above them, and which tier answered must be
# visible — otherwise "progressively" has no way to measure itself.
from skills.nutrition.portions import (FORM_DISTRIBUTIONS, Specificity,
                                       detect_form, ontology_coverage)


def test_the_broad_fallbacks_are_still_there():
    """They are the safety net for every combination not yet written down.
    Adding form rows must never delete them."""
    for measure, rows in PORTION_ONTOLOGY.items():
        assert "default" in rows, measure


def test_the_fallbacks_are_still_wide():
    """A narrow fallback would silence the clarification that fixes it — the
    original calibration argument still applies at this tier."""
    for measure, rows in PORTION_ONTOLOGY.items():
        median, lower, upper, conf = rows["default"]
        assert upper > lower
        assert (upper - lower) / median > 0.5, measure


def test_form_beats_category_beats_fallback():
    """The whole lookup chain, in one assertion."""
    form = distribution_for("handful", "cooked spinach")
    category = distribution_for("handful", "spinach")
    fallback = distribution_for("handful", "grandma's mystery goo")
    assert form.specificity is Specificity.FORM
    assert category.specificity is Specificity.CATEGORY
    assert fallback.specificity is Specificity.FALLBACK
    assert fallback.specificity.is_fallback


def test_an_unrecognised_food_reports_fallback_not_category():
    """food_category() returns the literal "default" for an unknown food, which
    matches the fallback row. Reporting that as category-specific would corrupt
    the one metric this tier exists to produce."""
    d = distribution_for("handful", "grandma's mystery goo")
    assert d.specificity is Specificity.FALLBACK
    assert d.form == ""


def test_cooked_greens_weigh_far_more_than_raw():
    """Spinach wilts to roughly a third of its volume — the clearest case for
    why form has to be its own dimension."""
    raw = distribution_for("handful", "raw spinach")
    cooked = distribution_for("handful", "cooked spinach")
    assert cooked.median_g > raw.median_g * 2


def test_dry_and_cooked_oats_differ_by_five_times():
    dry = distribution_for("bowl", "dry oatmeal")
    cooked = distribution_for("bowl", "cooked oatmeal")
    assert cooked.median_g > dry.median_g * 4
    assert dry.specificity is Specificity.FORM
    assert cooked.specificity is Specificity.FORM


def test_shredded_and_cubed_cheese_are_distinguished():
    shredded = distribution_for("handful", "shredded cheddar")
    cubed = distribution_for("handful", "cubed cheddar")
    assert cubed.median_g > shredded.median_g


def test_a_form_row_is_only_worth_having_if_it_moves_the_number():
    """Keeps the table honest. A form row that duplicates its category
    fallback makes the ontology look more informed than it is, so every row
    must either shift the median materially or be meaningfully more
    confident."""
    for measure, rows in FORM_DISTRIBUTIONS.items():
        base = PORTION_ONTOLOGY.get(measure, {})
        for (category, form), (median, lower, upper, conf) in rows.items():
            fallback = base.get(category) or base["default"]
            base_median, _, _, base_conf = fallback
            moved = abs(median - base_median) / max(base_median, 1.0) > 0.10
            # 0.03, not 0.02: 0.02 sat exactly on a float knife-edge —
            # `0.64 > 0.62 + 0.02` is False while `0.64 - 0.62 > 0.02` is True,
            # so the check passed or failed depending on how it was written.
            sharper = conf - base_conf >= 0.03
            assert moved or sharper, f"{measure}/{category}/{form} adds nothing"


def test_every_form_row_is_internally_coherent():
    for measure, rows in FORM_DISTRIBUTIONS.items():
        for key, (median, lower, upper, conf) in rows.items():
            assert lower < median < upper, f"{measure}/{key}"
            assert 0.0 < conf <= 1.0, f"{measure}/{key}"


def test_every_form_row_is_reachable():
    """A row keyed on a category no food maps to, or a form no alias produces,
    is dead weight that silently never fires."""
    reachable_categories = set(FOOD_CATEGORIES.values()) | {"default"}
    reachable_forms = set(FORM_ALIASES.values())
    for measure, rows in FORM_DISTRIBUTIONS.items():
        assert measure in PORTION_ONTOLOGY, measure
        for category, form in rows:
            assert category in reachable_categories, f"{measure}/{category}"
            assert form in reachable_forms, f"{measure}/{form}"


@pytest.mark.parametrize("text,form", [
    ("cooked spinach", "cooked"),
    ("steamed broccoli", "cooked"),
    ("raw kale", "raw"),
    ("dry oats", "dry"),
    ("dried cranberries", "dried"),
    ("shredded cheese", "shredded"),
    ("grated parmesan", "shredded"),
    ("diced cheddar", "cubed"),
    ("chopped almonds", "chopped"),
    ("packed brown sugar", "packed"),
    ("melted peanut butter", "melted"),
    ("greek yogurt", "greek"),
    ("shaved turkey", "shaved"),
    ("plain rice", ""),
])
def test_forms_are_detected(text, form):
    assert detect_form(text) == form


def test_the_form_can_come_from_the_portion_phrase_not_only_the_food_name():
    """"a handful of cooked spinach" names the form in the phrase; the food may
    arrive as bare "spinach"."""
    out = convert("a handful of cooked spinach", "spinach")
    assert out.distribution.specificity is Specificity.FORM
    assert out.distribution.form == "cooked"


def test_the_specificity_is_greppable_in_the_conversion_source():
    """Counting `ontology:fallback:` in production is how the next rows get
    chosen — that is what makes replacement progressive rather than
    aspirational."""
    assert convert("a handful", "mystery goo").conversion_source == \
        "ontology:fallback:default_handful"
    assert convert("a handful", "blueberries").conversion_source == \
        "ontology:category:berries_handful"
    assert convert("a handful", "cooked spinach").conversion_source == \
        "ontology:form:greens_handful:cooked"


def test_form_and_specificity_survive_scaling():
    one = distribution_for("slice", "shaved turkey deli slice")
    six = one.scaled(6)
    assert six.specificity is one.specificity
    assert six.form == one.form


def test_a_form_row_still_respects_size_modifiers():
    small = distribution_for("handful", "cooked spinach", "small")
    large = distribution_for("handful", "cooked spinach", "large")
    assert small.median_g < large.median_g
    assert small.specificity is Specificity.FORM


def test_an_explicit_form_overrides_detection():
    """Callers that already know the form — from a candidate's product data,
    say — should not have to encode it back into a string."""
    assert distribution_for("bowl", "oatmeal", form="dry").median_g < \
        distribution_for("bowl", "oatmeal", form="cooked").median_g


def test_an_unknown_form_falls_through_to_category():
    """A form with no row must not break the lookup — it degrades one tier."""
    d = distribution_for("handful", "blueberries", form="julienned")
    assert d.specificity is Specificity.CATEGORY
    assert d.median_g == 45.0


def test_coverage_is_reportable():
    """Progress on replacing the fallbacks is a number, not a feeling."""
    cov = ontology_coverage()
    assert cov["measures"] == len(PORTION_ONTOLOGY)
    assert cov["form_rows"] > 0
    assert cov["measures_with_forms"] <= cov["measures"]
