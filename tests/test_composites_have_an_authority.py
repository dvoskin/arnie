"""`component_estimate` finally has something behind it.

The rung has been the bottom of the RESTAURANT ladder since `authority.py` was
written and `candidate_map` has never seated anything on it, so every composite
dish fell to the model's estimate with a provenance line — "Estimated from its
components" — describing an arithmetic nobody performed.

These tests hold the two halves that make it real: that USDA can be made to
answer for a dish it has no row for, and that it is not asked to answer for one
it does.
"""
import asyncio

import pytest

from core.food_intelligence import analyze
from skills.nutrition import composites as C
from skills.nutrition.authority import (FoodClass, candidate_map,
                                        display_detail, select)
from tests.gold.usda_component_rows import ROWS, search


# ── the table addresses the database, and has to actually reach it ────────────
def test_every_component_query_in_the_table_finds_its_row():
    """The whole feature is dark if the queries miss, and a miss is silent —
    an unpriced dish is indistinguishable from a dish with no recipe.

    This is the test that would have caught phrasing the queries the way a
    person speaks: "corn tortilla" scores 0.5 coverage against USDA's
    "Tortillas, ready-to-bake or -fry, corn" and would have priced nothing.
    """
    unreachable = []
    for recipe in C._RECIPES:
        for component in recipe.components:
            for modifier in ("", "carnitas", "chicken", "turkey", "tuna"):
                query = C.resolve_component(
                    component, f"{modifier} {recipe.key}")
                rows = ROWS.get(query)
                assert rows, f"no fixture for {query!r} ({recipe.key})"
                if C.match_component_row(query, rows) is None:
                    unreachable.append((recipe.key, component.role, query))
    assert not unreachable


def test_a_corn_tortilla_is_not_a_bag_of_corn_chips():
    """"Snacks, tortilla chips, plain, white corn" answers every word of
    "Tortillas, corn" and is 508 cal/100 g against a tortilla's 218. It scored
    HIGHER than the real row — its description is one word shorter — and put 75
    calories of chips in every taco.

    Token coverage cannot see this: "tortilla" there is a modifier on "chips".
    """
    row = C.match_component_row("Tortillas, corn", ROWS["Tortillas, corn"])
    assert row["description"] == "Tortillas, ready-to-bake or -fry, corn"


@pytest.mark.parametrize("query,expected", [
    # USDA's CATEGORY for the right food is not a wrong form. Blocking "sauce"
    # and "salad" outright rejected two of the table's own components, and a
    # dish that cannot price a part is not seated — so the bug looked exactly
    # like a dish with no recipe.
    ("Salsa", "Sauce, salsa, ready-to-serve"),
    ("Mayonnaise", "Salad dressing, mayonnaise, regular"),
    # ...while a genuinely different food or preparation still loses.
    ("Rice, white, cooked", "Rice, white, long-grain, regular, enriched, cooked"),
    ("Beans, black, cooked",
     "Beans, black, mature seeds, cooked, boiled, without salt"),
    ("Chicken, breast, meat only, cooked, roasted",
     "Chicken, broilers or fryers, breast, meat only, cooked, roasted"),
    ("Egg, whole, raw, fresh", "Egg, whole, raw, fresh"),
])
def test_the_matcher_picks_the_row_the_query_meant(query, expected):
    row = C.match_component_row(query, ROWS[query])
    assert row is not None and row["description"] == expected


def test_a_query_with_no_answer_matches_nothing():
    """Fail closed. The alternative is pricing a taco's protein off whatever
    row shared a word with it."""
    assert C.match_component_row("Pork, shoulder, cooked", []) is None
    assert C.match_component_row(
        "Pork, shoulder, cooked", ROWS["Rice, white, cooked"]) is None


# ── which dish, if any ────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,dish", [
    ("two carnitas tacos", "taco"),          # plural
    ("a taco", "taco"),
    ("a burger", "burger"),
    ("cheeseburger", "cheeseburger"),        # longer key wins over "burger"
    ("burrito bowl", "burrito bowl"),        # longer key wins over "burrito"
    ("chicken burrito", "burrito"),
    ("Chipotle burrito bowl", "burrito bowl"),
    ("omelet", "omelette"),                  # alias
    ("hamburger", "burger"),                 # alias
    ("turkey sandwich", "sandwich"),
])
def test_the_dish_a_name_names(name, dish):
    recipe = C.recipe_for(name)
    assert recipe is not None and recipe.key == dish


@pytest.mark.parametrize("name", [
    "banana", "greek yogurt", "chicken breast", "olive oil", "cottage cheese",
    "Royo everything bagel", "oatmeal", "a scoop of peanut butter",
])
def test_a_food_that_is_not_a_dish_has_no_recipe(name):
    """A single food is not a composite, and giving it one would replace a
    measured USDA row with a sum over our guesses."""
    assert C.recipe_for(name) is None


@pytest.mark.parametrize("name,expected", [
    ("two carnitas tacos", "Pork, shoulder, cooked"),
    ("al pastor tacos", "Pork, shoulder, cooked"),
    ("chicken burrito", "Chicken, breast, meat only, cooked, roasted"),
    ("barbacoa burrito bowl", "Beef, chuck, cooked"),
    ("tuna poke bowl", "Fish, tuna, yellowfin, raw"),
    ("turkey sandwich", "Turkey, breast, meat only, cooked, roasted"),
    ("veggie burrito", "Beans, black, cooked"),
    ("a taco", "Beef, ground, cooked"),          # the stated default
])
def test_the_protein_follows_the_dish_name(name, expected):
    """Without this every taco in the table is a beef taco, and the whole
    exercise is a more elaborate way of being wrong."""
    recipe = C.recipe_for(name)
    protein = next(c for c in recipe.components if c.follows_name)
    assert C.resolve_component(protein, name) == expected


# ── the sum ───────────────────────────────────────────────────────────────────
@pytest.fixture
def taco():
    return asyncio.run(C.price_from_usda("two carnitas tacos", search=search))


def test_a_dish_is_priced_from_parts_usda_measured(taco):
    """USDA has no taco. It has a corn tortilla, cooked pork shoulder, queso
    fresco and salsa, and that is the external authority."""
    assert taco is not None
    matched = {c.role: c.matched for c in taco["components"]}
    assert matched["corn tortilla"] == "Tortillas, ready-to-bake or -fry, corn"
    assert matched["protein"].startswith("Pork, fresh, shoulder")
    assert taco["per_serving"]["calories"] == pytest.approx(236, abs=6)


def test_the_answer_is_a_range_not_a_number(taco):
    """Summing four typical masses produces one number carrying the confidence
    of a measurement, which a dish does not have. The light and heavy builds of
    the SAME recipe are the two numbers that are true."""
    low, high, point = (taco["calorie_low"], taco["calorie_high"],
                        taco["per_serving"]["calories"])
    assert low < point < high
    assert high - low > 0.3 * point       # a real span, not decoration


def test_naming_the_protein_narrows_the_range():
    """"chicken quesadilla" and "quesadilla" came back with an identical range
    while their point estimates differed by 124 calories — the named part still
    read as possibly-absent."""
    plain = asyncio.run(C.price_from_usda("quesadilla", search=search))
    named = asyncio.run(C.price_from_usda("chicken quesadilla", search=search))
    assert named["per_serving"]["calories"] > plain["per_serving"]["calories"]
    assert named["calorie_low"] > plain["calorie_low"]


def test_a_composite_never_reports_sodium():
    """A dish's sodium lives in the seasoning, the brine and the sauce — none
    of which this table models. Summing the parts we DO know would be a
    confident undercount of the one nutrient people restrict on medical
    advice."""
    for name in ("a burger", "chicken burrito", "two carnitas tacos"):
        priced = asyncio.run(C.price_from_usda(name, search=search))
        assert "sodium" not in priced["per_serving"]
        assert "sodium" not in priced["per100g"]


def test_a_missing_required_part_seats_nothing():
    """Fail closed. A partial sum is not a cheaper answer — it is a systematic
    UNDERCOUNT wearing a provenance line that says four sources agreed."""
    rows = {q: r for q, r in ROWS.items() if q != "Tortillas, corn"}
    assert C.price(C.recipe_for("a taco"), "a taco", rows) is None


def test_may_be_absent_and_absent_from_the_default_build_are_different():
    """A taco's salsa may be absent — its light end is zero — and is still part
    of the typical taco, so failing to price it fails the dish. A plain
    quesadilla's chicken has no mass in the default build at all, so failing to
    price THAT costs only the heavy end of the range.

    Conflating the two is what made the skip condition read
    `optional and grams <= 0`, where the first half never decided anything.
    """
    salsa = next(c for c in C.recipe_for("a taco").components
                 if c.role == "salsa")
    assert salsa.may_be_absent and salsa.grams > 0
    assert C.price(C.recipe_for("a taco"), "a taco",
                   {q: r for q, r in ROWS.items() if q != "Salsa"}) is None

    quesadilla = C.recipe_for("quesadilla")
    protein = next(c for c in quesadilla.components if c.follows_name)
    assert protein.may_be_absent and protein.grams == 0
    assert C.price(quesadilla, "quesadilla",
                   {q: r for q, r in ROWS.items()
                    if not q.startswith("Chicken")}) is not None


def test_the_module_cannot_produce_a_calorie_without_usda():
    """THE LOAD-BEARING INVARIANT, stated as the thing it forbids.

    What is ours is WHAT IS IN THE DISH and roughly how much; what is USDA's is
    what those things weigh per calorie. The moment one calorie figure is
    hardcoded here, "estimated from its components" stops being an external
    authority and becomes our own guess wearing USDA's name — and nothing
    downstream could tell the difference.

    So: starve the module of rows and it must produce nothing at all. Every
    recipe, no exceptions, no partial answer, no default.
    """
    for recipe in C._RECIPES:
        assert C.price(recipe, recipe.key, {}) is None
        assert asyncio.run(C.price_from_usda(
            recipe.key, search=lambda q, page_size=8: _nothing())) is None


async def _nothing():
    return []


# ── the ladder ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("food_class", [FoodClass.GENERIC, FoodClass.RESTAURANT])
def test_the_rung_is_seated_at_last(food_class):
    """`candidate_map` never put anything here. That is the defect."""
    rung, seated = select(
        candidate_map(food_class=food_class, component_candidate={"id": "c"}),
        food_class)
    assert (rung, seated["id"]) == ("component_estimate", "c")


def test_an_exact_usda_row_for_the_whole_dish_still_wins():
    """USDA does carry some composites outright, and a measured row for the
    dish beats a sum over our guess at its parts every time."""
    rung, _ = select(candidate_map(
        food_class=FoodClass.GENERIC,
        usda_candidate={"_match": "exact"},
        component_candidate={"id": "c"}), FoodClass.GENERIC)
    assert rung == "usda_exact"


def test_a_likely_usda_row_for_a_dish_loses_to_its_parts():
    """`score_match` hands out "likely" at 0.6 token overlap — the documented
    way a bare query matches a full meal. Holding the top rung on that evidence
    kept the composite from ever answering, for exactly the dishes it exists
    for."""
    rung, _ = select(candidate_map(
        food_class=FoodClass.GENERIC,
        usda_candidate={"_match": "likely"},
        component_candidate={"id": "c"}), FoodClass.GENERIC)
    assert rung == "component_estimate"


def test_a_food_with_no_recipe_keeps_its_likely_usda_row():
    """The grade gate above must not tighten USDA's seating for every generic
    food in the system — only for the dishes a composite can answer."""
    rung, _ = select(candidate_map(
        food_class=FoodClass.GENERIC,
        usda_candidate={"_match": "likely"}), FoodClass.GENERIC)
    assert rung == "usda_exact"


def test_memory_and_a_correction_still_outrank_a_composite():
    for memory, expected in (
            ({"user_confirmed": True}, "user_correction"),
            ({"origin_tier": "branded_exact"}, "usda_exact")):
        rung, _ = select(candidate_map(
            food_class=FoodClass.GENERIC, memory_match=memory,
            component_candidate={"id": "c"}), FoodClass.GENERIC)
        assert rung == expected


# ── through analyze(), which is what actually writes the row ──────────────────
def test_the_card_says_where_the_number_came_from():
    priced = asyncio.run(C.price_from_usda("a burger", search=search))
    result = analyze("a burger", "1 burger", 600, 30, 40, 35,
                     component_candidate=priced)
    assert result.source == "components"
    assert result.provenance.rung == "component_estimate"
    assert display_detail(result.provenance) == "Estimated from its components"
    assert result.calories == pytest.approx(514, abs=8)


def test_a_composite_is_not_reported_as_a_web_label():
    """Before this branch existed a composite fell through `analyze`'s identity
    chain to the `else` and named itself `web_label` — a source it never
    consulted, on a row assembled from four USDA generics."""
    priced = asyncio.run(C.price_from_usda("omelette", search=search))
    result = analyze("omelette", "1 omelette", 350, 24, 3, 27,
                     component_candidate=priced)
    assert result.source not in ("web_label", "usda", "off", "memory")


def test_two_of_them_is_twice_one_of_them():
    """The candidate publishes a serving — "1 taco (133 g)" — so the count path
    that already exists for a labelled product answers a dish too."""
    priced = asyncio.run(C.price_from_usda("carnitas tacos", search=search))
    one = analyze("carnitas tacos", "1 taco", 200, 10, 15, 10,
                  component_candidate=priced)
    two = analyze("carnitas tacos", "2 tacos", 400, 20, 30, 20,
                  component_candidate=priced)
    assert two.calories == pytest.approx(2 * one.calories, abs=2)


def test_the_model_is_left_alone_when_there_is_no_recipe():
    """Every food that is not in the table behaves exactly as it did."""
    before = analyze("banana", "1 banana", 105, 1.3, 27, 0.4)
    after = analyze("banana", "1 banana", 105, 1.3, 27, 0.4,
                    component_candidate=None)
    assert (before.calories, before.source) == (after.calories, after.source)
    assert after.calories == 105


class _FakeUsda:
    """Counts what was actually asked of the network."""

    def __init__(self, rows=None):
        self.rows, self.calls = rows if rows is not None else ROWS, []

    async def __call__(self, query, page_size=8):
        self.calls.append(query)
        return self.rows.get(query, [])


@pytest.fixture
def usda(monkeypatch):
    import api.usda
    from handlers.tool_executor import _COMPONENT_ROWS
    _COMPONENT_ROWS.clear()
    fake = _FakeUsda()
    monkeypatch.setattr(api.usda, "search_food", fake)
    yield fake
    _COMPONENT_ROWS.clear()


def test_a_food_with_no_recipe_costs_no_round_trips(usda):
    """What makes it safe to ask this of EVERY food. One dict lookup, and the
    network is never touched."""
    from handlers.tool_executor import _price_composite
    assert asyncio.run(_price_composite("banana")) is None
    assert usda.calls == []


def test_shared_ingredients_are_fetched_once(usda):
    """Every dish in the table shares rice, cheese, tortillas or salsa with
    another, and a burrito alone is seven components. The memo is what keeps
    that from being seven round-trips per burrito, forever."""
    from handlers.tool_executor import _price_composite
    assert asyncio.run(_price_composite("two carnitas tacos")) is not None
    first = len(usda.calls)
    assert first == 4

    # Same dish, different protein: only the part that differs is fetched.
    assert asyncio.run(_price_composite("a taco")) is not None
    assert len(usda.calls) - first == 1

    # Same dish again: nothing at all.
    before = len(usda.calls)
    assert asyncio.run(_price_composite("two carnitas tacos")) is not None
    assert len(usda.calls) == before


def test_a_usda_outage_is_not_remembered_as_an_answer(usda, monkeypatch):
    """An empty result is USDA being unreachable far more often than it is USDA
    having no such food. Memoizing it would take every composite down for six
    hours after the API came back."""
    import api.usda
    from handlers.tool_executor import _COMPONENT_ROWS, _price_composite
    monkeypatch.setattr(api.usda, "search_food", _FakeUsda(rows={}))
    assert asyncio.run(_price_composite("a taco")) is None
    assert len(_COMPONENT_ROWS) == 0

    monkeypatch.setattr(api.usda, "search_food", _FakeUsda())
    assert asyncio.run(_price_composite("a taco")) is not None


def test_a_slow_usda_costs_the_budget_and_not_the_turn(usda, monkeypatch):
    """A composite that runs out of time is a MISS, not an error: the estimate
    commits with its provenance intact, which is the degradation every other
    remote source in this pipeline already promises."""
    import api.usda
    from core import deadline
    from handlers.tool_executor import _price_composite

    async def never(query, page_size=8):
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(api.usda, "search_food", never)

    async def run():
        with deadline.budget(0.2):
            return await _price_composite("two carnitas tacos")

    assert asyncio.run(asyncio.wait_for(run(), timeout=5)) is None


def test_the_receipt_still_shows_the_lanes_that_ran_before_it():
    """The composite lane runs after both branches that write `lanes`, and
    `stash` replaces a key rather than merging it — so writing the list again
    would erase whichever of usda/off/web had just been recorded, and the
    receipt would show a dish priced from its parts with no sign that anything
    else was consulted."""
    from core.execution_result import CALL_CTX
    from handlers.tool_executor import _append_lane

    token = CALL_CTX.set({"lanes": [("usda", "miss"), ("off", "miss")]})
    try:
        _append_lane({}, "components", "priced 4 parts from USDA")
        assert CALL_CTX.get()["lanes"] == [
            ("usda", "miss"), ("off", "miss"),
            ("components", "priced 4 parts from USDA")]
    finally:
        CALL_CTX.reset(token)


def test_a_dish_is_never_written_to_food_memory():
    """Memory re-enters the ladder ABOVE `component_estimate`, so caching a
    dish would shadow the composite from the second log onwards — the feature
    would work once per food per user and then quietly stop.

    And there is nothing to cache. A dish's calories are a property of the
    instance, not of the name; two burritos are not the same burrito.
    """
    from handlers.tool_executor import _has_recipe
    assert _has_recipe("chicken burrito") is True
    assert _has_recipe("two carnitas tacos") is True
    assert _has_recipe("banana") is False
    assert _has_recipe("Royo everything bagel") is False
