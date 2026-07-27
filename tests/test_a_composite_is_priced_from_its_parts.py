"""`component_estimate` names a method that is now implemented.

The rung has been on the restaurant ladder since the ladders were written and
`COMPONENT_BREAKDOWN` has been in the ambiguity enum just as long. Nothing was
ever seated on it. The only way to reach the name was `food_intelligence`
relabelling an estimate the ladder had already REFUSED, so the disclosure
keyed off it — "Estimated from its components" — described work that had not
happened, and composite totals drifted 18-21% across modes (b835700).

These tests pin the four things that had to become true together: the rung is
seatable, what seats it was priced against an external authority, the ladder
still prefers a published row to a sum of our assumptions, and the old lie is
gone.
"""
import pytest

from core.food_intelligence import analyze, is_generic_food_name
from skills.nutrition import authority, composites
from skills.nutrition.authority import FoodClass


# Real USDA per-100g figures for the generics a street taco decomposes into.
# The point of the whole change is that THESE are the external authority and
# the gram assumptions are ours, so the test data has to be the real rows.
TACO_ROWS = {
    "corn tortilla": {
        "fdc_id": 1, "description": "Tortillas, ready-to-bake or -fry, corn",
        "per100g": {"calories": 218, "protein": 5.7, "carbs": 44.6,
                    "fat": 2.9, "fiber": 6.3, "sodium": 45}},
    "pork shoulder cooked": {
        "fdc_id": 2, "description": "Pork, shoulder, cooked",
        "per100g": {"calories": 294, "protein": 24.0, "carbs": 0.0,
                    "fat": 21.4, "sodium": 75}},
    "onion raw": {
        "fdc_id": 3, "description": "Onions, raw",
        "per100g": {"calories": 40, "protein": 1.1, "carbs": 9.3,
                    "fat": 0.1, "fiber": 1.7, "sodium": 4}},
    "salsa": {
        "fdc_id": 4, "description": "Salsa, ready-to-serve",
        "per100g": {"calories": 36, "protein": 1.5, "carbs": 7.0,
                    "fat": 0.2, "fiber": 1.9, "sodium": 430}},
}


def _taco_candidate(rows=None):
    recipe = composites.match_recipe("carnitas tacos")
    return composites.price(recipe, rows if rows is not None else TACO_ROWS)


# ── the rung had nothing on it ────────────────────────────────────────────────
def test_the_rung_was_unreachable_before_a_component_candidate_existed():
    """The defect itself. Every other source seats somewhere; this one could
    not, so the ladder's last restaurant rung was decorative."""
    seated = authority.candidate_map(
        food_class=FoodClass.RESTAURANT,
        usda_candidate={"per100g": {"calories": 200}},
        off_candidate={"per100g": {"calories": 200}, "_match": "exact"},
        web_candidate=None, memory_match=None)
    assert "component_estimate" not in seated


@pytest.mark.parametrize("food_class", [FoodClass.GENERIC,
                                        FoodClass.RESTAURANT])
def test_a_component_candidate_seats_on_the_rung(food_class):
    seated = authority.candidate_map(food_class=food_class,
                                     component_candidate={"id": "c"})
    assert seated["component_estimate"] == {"id": "c"}
    assert authority.select(seated, food_class)[0] == "component_estimate"


def test_a_manufactured_product_is_not_decomposed():
    """It has a label. Answering from generic parts would replace the better
    answer with a worse one."""
    seated = authority.candidate_map(food_class=FoodClass.MANUFACTURED,
                                     component_candidate={"id": "c"})
    assert "component_estimate" not in seated


def test_every_ladder_still_ends_in_a_disclosed_fallback():
    """Inserting a rung must not push a ladder's terminal rung off the end —
    a ladder ending in a non-fallback fails silently, with no symptom."""
    for food_class, rungs in authority.LADDERS.items():
        assert rungs[-1] in authority.FALLBACK_RUNGS, food_class


# ── the dish this is an estimate OF ───────────────────────────────────────────
def test_the_longer_dish_name_wins():
    """"burrito bowl" must not be read as a burrito, or every bowl gets a
    tortilla it never had — 72 g of flour tortilla, about 210 calories."""
    assert composites.match_recipe("burrito bowl").dish == "burrito bowl"
    assert composites.match_recipe("chicken burrito").dish == "burrito"
    assert "base" not in {c.role for c
                          in composites.match_recipe("burrito bowl").components}


def test_the_protein_slot_is_filled_from_what_was_actually_said():
    """Otherwise the dish name is decorative and all three tacos price the
    same."""
    def protein(name):
        return next(c.query for c in composites.match_recipe(name).components
                    if c.role == composites.PROTEIN_ROLE)

    assert protein("carnitas taco") == "pork shoulder cooked"
    assert protein("chicken taco") == "chicken breast roasted"
    assert protein("carne asada taco") == "beef steak cooked"
    # "ground beef" must be matched before "beef" can claim it.
    assert protein("ground beef burrito") == "ground beef cooked"


def test_substituting_the_filling_does_not_resize_the_dish():
    """A taco holds about as much chicken as it holds pork. The grams belong
    to the dish, not to the meat."""
    pork = composites.match_recipe("carnitas taco")
    chicken = composites.match_recipe("chicken taco")
    assert pork.assumed_mass_g == chicken.assumed_mass_g


def test_an_unknown_dish_gets_no_estimate():
    """None is the common and correct answer. A table of seven builds must not
    imply an opinion about everything else."""
    for name in ("oatmeal", "chicken breast", "a protein shake", ""):
        assert composites.match_recipe(name) is None


def test_a_dish_name_is_matched_on_whole_words():
    assert composites.match_recipe("tacoma") is None
    assert composites.match_recipe("two tacos") is not None


# ── priced against an external authority ──────────────────────────────────────
def test_the_calories_are_the_sum_of_usda_rows_times_our_grams():
    """Nothing in the number is invented: every calorie traces to a row, and
    the only thing we contributed is the mass it was priced at."""
    cand = _taco_candidate()
    expected = round(sum(
        TACO_ROWS[c.query]["per100g"]["calories"] * c.grams / 100.0
        for c in composites.match_recipe("carnitas tacos").components))
    assert cand["per_serving"]["calories"] == expected
    assert cand["serving_mass_g"] == 104.0
    assert [b["fdc_id"] for b in cand["component_breakdown"]] == [1, 2, 3, 4]


def test_the_estimate_carries_a_range_that_brackets_it():
    """The rung's own definition is "component estimate WITH a range". The
    grams are assumptions and a point value would hide that."""
    cand = _taco_candidate()
    assert cand["calorie_low"] < cand["per_serving"]["calories"] < cand["calorie_high"]


def test_too_little_of_the_dish_priced_is_refused_outright():
    """A short-weight sum would be confidently low, seated above the estimate,
    and carrying USDA's name on the shortfall. Better to have no answer."""
    without_filling = {k: v for k, v in TACO_ROWS.items()
                       if k != "pork shoulder cooked"}
    assert _taco_candidate(without_filling) is None


def test_what_did_not_price_widens_the_answer_rather_than_shrinking_it():
    """The missing food is real. Dropping it silently is how a component sum
    comes out low and confident."""
    full = _taco_candidate()
    without_onion = _taco_candidate(
        {k: v for k, v in TACO_ROWS.items() if k != "onion raw"})
    assert without_onion is not None
    assert without_onion["component_unpriced"] == ("onion raw",)
    assert without_onion["calorie_high"] > full["calorie_high"]


def test_a_component_row_with_no_calories_counts_as_unpriced():
    rows = dict(TACO_ROWS)
    rows["salsa"] = {"fdc_id": 4, "description": "Salsa", "per100g": {}}
    priced = _taco_candidate(rows)
    assert priced is not None
    assert priced["component_unpriced"] == ("salsa",)


# ── through analyze(), which is what commits ──────────────────────────────────
def test_a_count_of_the_dish_scales_the_priced_serving():
    """"2 tacos" is two of the thing we priced. This is the reason the
    candidate publishes a serving panel — the existing count path does the
    multiplication and no new scaling code exists."""
    cand = _taco_candidate()
    one = analyze("carnitas tacos", "1 taco", 0, 0, 0, 0,
                  component_candidate=cand)
    two = analyze("carnitas tacos", "2 tacos", 0, 0, 0, 0,
                  component_candidate=cand)
    assert two.calories == 2 * one.calories
    assert two.protein == pytest.approx(2 * one.protein, rel=1e-6)


def test_the_rung_and_the_disclosure_agree_with_what_was_done():
    cand = _taco_candidate()
    result = analyze("carnitas tacos", "2 tacos", 0, 0, 0, 0,
                     component_candidate=cand)
    assert result.provenance.rung == "component_estimate"
    assert result.provenance.primary_macro_source == "component_estimate"
    assert authority.display_detail(
        result.provenance) == "Estimated from its components"
    assert result.source == "components"


def test_the_note_does_not_tell_the_model_this_was_a_database_match():
    """Both existing branches assumed a published row; "USDA likely match" was
    the default for anything that was not the web lane."""
    result = analyze("carnitas tacos", "2 tacos", 0, 0, 0, 0,
                     component_candidate=_taco_candidate())
    assert "estimated from its components" in result.coach_note
    assert "USDA" not in result.coach_note


def test_a_published_usda_row_still_outranks_a_sum_of_our_assumptions():
    """The ladder order is the whole claim: external authority beats our
    decomposition when it exists."""
    usda = {"fdc_id": 9, "description": "Tacos, beef", "_match": "exact",
            "per100g": {"calories": 217, "protein": 12.0, "carbs": 20.0,
                        "fat": 10.0}}
    result = analyze("carnitas tacos", "2 tacos", 300, 20, 20, 10,
                     usda_candidate=usda,
                     component_candidate=_taco_candidate())
    assert result.provenance.rung == "usda_exact"


# ── the lie that is gone ──────────────────────────────────────────────────────
def test_an_unseated_restaurant_estimate_no_longer_claims_the_rung():
    """The relabel this replaces. Reaching that branch means `select` seated
    NOTHING — no decomposition happened and no component was priced — yet the
    rung read `component_estimate` purely because the food was a restaurant
    food, and the disclosure said so."""
    usda = {"fdc_id": 7, "description": "Sandwich, turkey", "_match": "likely",
            "per100g": {"calories": 250, "protein": 15.0}}
    result = analyze("half a Starbucks turkey bacon sandwich", "1 sandwich",
                     180, 12, 15, 7, usda_candidate=usda)
    assert result.provenance.food_class == FoodClass.RESTAURANT.value
    assert result.provenance.rung == "estimate"
    assert authority.display_detail(
        result.provenance) != "Estimated from its components"


# ── the gate that decides whether to pay for the lookups ──────────────────────
@pytest.mark.parametrize("rung,expected", [
    ("", True),                  # nothing held — the lane is the only answer
    ("portion_ontology", True),  # a weaker guess than priced parts
    ("estimate", True),
    ("usda_exact", False),       # a published row already won
    ("user_correction", False),
])
def test_the_cost_gate_asks_the_ladder(rung, expected):
    assert authority.components_could_win(FoodClass.GENERIC, rung) is expected


def test_a_manufactured_food_never_pays_for_a_decomposition():
    assert authority.components_could_win(FoodClass.MANUFACTURED, "") is False


# ── the structural claim: this lane serves the traffic the old gate excluded ──
def test_the_dishes_that_skip_every_lookup_are_the_ones_this_lane_answers():
    """`_analyze_food`'s enrichment block is gated on `not generic`, so a name
    whose every token is a category word skips USDA, OFF and web entirely.
    That is right for a text match — there is no particular row "burger" means
    — and it is exactly why the component lane sits OUTSIDE that gate. A lane
    placed inside it would have been dark for precisely the traffic it was
    built for, which is how the food gate shipped switched off (8997d92)."""
    for name in ("burger", "taco"):
        assert is_generic_food_name(name) is True
        assert composites.match_recipe(name) is not None


# ── both paths are shown the same evidence ────────────────────────────────────
def test_the_typed_resolver_sees_the_component_candidate():
    """In `live` mode promotion REPLACES the committed answer with the
    resolution's, so a candidate the ladder seated but the resolver's adapter
    never heard of would be discarded in production while every ladder test
    still passed."""
    from skills.nutrition.shadow import candidates_from_live

    built = candidates_from_live("carnitas tacos", {},
                                 component=_taco_candidate())
    comp = [c for c in built if c.source == "components"]
    assert len(comp) == 1
    assert comp[0].serving_mass_g == 104.0
    # `as_served`, because "2 tacos" is a count with no mass and per-100g
    # values would refuse to scale it.
    assert comp[0].basis.as_served is True


def test_the_resolver_adapter_ignores_an_absent_component():
    from skills.nutrition.shadow import candidates_from_live

    built = candidates_from_live("banana", {}, component=None)
    assert not [c for c in built if c.source == "components"]
