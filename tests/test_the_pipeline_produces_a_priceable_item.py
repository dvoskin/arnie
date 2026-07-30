"""The staged item the REAL pipeline produces, against what the rest assumes.

This is the test class whose absence is how cause A shipped half-inert.

`test_the_ask_carries_the_resolution.py` and
`test_the_answer_applies_the_resolution.py` both pass, and both **build their
own candidates**. A test that constructs its input cannot discover that
production never constructs it — and production never did: in the whole
repository, every assignment to `StagedFoodItem.candidate_products` was in a
test or in the codec's decoder. Live rows carried `candidate_products: null`
and `anchor: None`, so `FOOD_ANSWER_APPLY` declined 100% of the time and the
zero-lookup commit could not have fired even switched on.

So nothing here builds a staged item. Every item under test comes out of
`core.food_pipeline.plan_turn` as the live turn calls it, fed by
`core.food_turn`'s own ask-time collection, with the fakes pushed out to the
network boundary — the Open Food Facts HTTP client and USDA's search. What is
asserted is the contract the two consumers depend on:

    staged_codec        candidates survive the turn boundary, with their
                        anchor and their basis
    answer_application  a portion answer prices from the stored numbers,
                        with no lookup at all

If a future change unhooks the producer again, these fail; the round-trip
tests would not.
"""
import pytest

from skills.nutrition import off

_TURN = "test:turn:1"

#: One Open Food Facts product and its shelf-mate, as the search returns them.
_VARIANTS = [
    {"code": "7340001111111",
     "product_name": "Barebells Salty Peanut Protein Bar",
     "brands": "Barebells", "serving_size": "55 g", "quantity": "55 g",
     "nutriments": {"energy-kcal_100g": 364, "proteins_100g": 36,
                    "carbohydrates_100g": 27, "fat_100g": 15}},
    {"code": "7340002222222",
     "product_name": "Barebells Cookies and Cream Protein Bar",
     "brands": "Barebells", "serving_size": "55 g", "quantity": "55 g",
     "nutriments": {"energy-kcal_100g": 395, "proteins_100g": 29,
                    "carbohydrates_100g": 35, "fat_100g": 16}},
]

_USDA_ROWS = [{
    "description": "Protein bar", "fdcId": 171284, "brandOwner": "",
    "foodNutrients": [
        {"nutrientName": "Energy", "unitName": "KCAL", "value": 380},
        {"nutrientName": "Protein", "unitName": "G", "value": 30},
        {"nutrientName": "Carbohydrate, by difference", "unitName": "G",
         "value": 30},
        {"nutrientName": "Total lipid (fat)", "unitName": "G", "value": 14},
    ]}]


@pytest.fixture
def turn(monkeypatch):
    """A turn whose product lookups answer from fixtures, not the network.

    Faked at the HTTP boundary and at `api.usda.search_food`, so everything
    between — the single-flight registry, the variant fetch, the spread
    calculation, the candidate adapter, staging — is the shipped code.
    """
    import core.food_turn as FT
    from core.turn_identity import CURRENT_TURN_ID

    class _Resp:
        status_code = 200

        def json(self):
            return {"products": _VARIANTS}

    class _Client:
        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(off, "_client", lambda: _Client())
    monkeypatch.setenv("OFF_ENABLED", "true")

    async def _usda(query, page_size=5):
        return list(_USDA_ROWS)
    monkeypatch.setattr("api.usda.search_food", _usda)

    # A clean cache and a clean in-flight registry: these are process-global
    # and a leftover entry from another test would answer for a fetch this one
    # never made — which is the failure mode the test is about.
    FT._SPREAD_CACHE.clear()
    import handlers.tool_executor as TE
    TE._INFLIGHT_FETCHES.clear()

    token = CURRENT_TURN_ID.set(_TURN)
    try:
        yield FT
    finally:
        CURRENT_TURN_ID.reset(token)
        FT._SPREAD_CACHE.clear()
        TE._INFLIGHT_FETCHES.clear()


def _interpreted(amount=None, unit=None):
    """What the interpreter hands the pipeline for one branded bar."""
    item = {"food": "Barebells salty peanut protein bar", "brand": "Barebells",
            "branded": True, "calories": 200, "protein": 20,
            "carbs": 15, "fat": 8}
    if amount is not None:
        item["amount"], item["unit"] = amount, unit
    return {"action": "log", "items": [item]}


async def _plan(FT, data, message="had a barebells bar", mode="moderate"):
    """The live sequence: fetch the spread, collect the candidates, decide."""
    from core.food_pipeline import plan_turn
    spreads = await FT._variant_spreads(data, mode=mode, targets=None)
    return spreads, plan_turn(data, turn_id=_TURN, message=message, mode=mode,
                              variant_spreads=spreads,
                              item_candidates=FT._ask_candidates(data))


# ── the producer exists ───────────────────────────────────────────────────────
async def test_a_staged_item_carries_the_products_the_turn_looked_up(turn):
    """The finding itself: `candidate_products` had no producer."""
    _, decision = await _plan(turn, _interpreted())
    assert decision is not None
    item = decision.staged_items[0]
    assert item.candidate_products, \
        "the ask staged an item with no products — §8.1 is not closed"


async def test_every_stored_candidate_carries_an_anchor_and_a_basis(turn):
    """What `answer_application` reads before it will price anything, and what
    makes the resolution a claim about a PRODUCT rather than about a word."""
    _, decision = await _plan(turn, _interpreted())
    for candidate in decision.staged_items[0].candidate_products:
        assert candidate.serving_basis, f"{candidate.source} has no basis"
        assert candidate.source_id, f"{candidate.source} has no anchor"


async def test_the_shelf_the_spread_measured_is_the_shelf_that_is_stored(turn):
    """The variant fetch measured a disagreement between real products, and
    those products were reduced to a per-nutrient span and dropped. One fetch,
    both readers — so the ask can say WHAT it is unsure between."""
    spreads, decision = await _plan(turn, _interpreted())
    assert spreads, "the fixture shelf produced no spread"
    names = {c.canonical_name
             for c in decision.staged_items[0].candidate_products}
    assert any("Salty Peanut" in n for n in names)
    assert any("Cookies and Cream" in n for n in names)


async def test_the_interpreters_own_guess_is_not_seated_as_a_product(turn):
    """It is not something the shelf says, it is already on the raw item, and
    as a candidate it would outrank every real source on name overlap — the
    stored resolution would be the model quoting itself back."""
    _, decision = await _plan(turn, _interpreted())
    sources = {c.source
               for c in decision.staged_items[0].candidate_products}
    assert "provisional" not in sources and "user_label" not in sources


# ── the two consumers ─────────────────────────────────────────────────────────
async def test_the_resolution_survives_the_turn_boundary(turn):
    """Through the codec the ask return actually uses. A candidate that does
    not decode is a candidate the answering turn does not have."""
    from skills.nutrition.staged_codec import decode_items, encode_items

    _, decision = await _plan(turn, _interpreted())
    restored = decode_items(encode_items(decision.staged_items))
    assert restored
    before = decision.staged_items[0].candidate_products
    after = restored[0].candidate_products
    assert len(after) == len(before)
    assert [c.source_id for c in after] == [c.source_id for c in before]
    assert [c.serving_basis for c in after] == [c.serving_basis for c in before]
    assert after[0].nutrient_profile is not None


async def test_a_portion_answer_prices_from_the_stored_numbers(turn):
    """The end of cause A: answering "about 55 g" costs no lookup.

    Priced from the per-100g row the ask stored, so the answer cannot disagree
    with the question — the production failure was an ask that said 10 g of
    protein and an answer that re-priced from scratch and logged 8 g.
    """
    from skills.nutrition.answer_application import commit_from_answer
    from skills.nutrition.staged_codec import encode_items

    _, decision = await _plan(turn, _interpreted())
    item = decision.staged_items[0]
    priced = commit_from_answer(encode_items([item]), item.staged_item_id,
                                {"estimated_mass_g": 55.0})
    assert priced is not None, \
        "the stored resolution could not be priced — the join is inert"
    # 364 cal/100 g over 55 g. The number comes from the shelf, not the model:
    # the interpreter's own guess for this row was 200.
    assert priced["calories"] == pytest.approx(200.2, abs=1.0)
    assert priced["protein"] == pytest.approx(19.8, abs=0.5)


async def test_an_identity_answer_still_declines(turn):
    """Unchanged, and it has to be: an answer that replaces the food means the
    stored basis describes something else, so re-resolution is correct."""
    from skills.nutrition.answer_application import commit_from_answer
    from skills.nutrition.staged_codec import encode_items

    _, decision = await _plan(turn, _interpreted())
    item = decision.staged_items[0]
    assert commit_from_answer(encode_items([item]), item.staged_item_id,
                              {"variant": "cookies and cream"}) is None


# ── what it may never cost ────────────────────────────────────────────────────
async def test_the_ask_does_not_fetch(turn, monkeypatch):
    """No new lookups on the critical path. The collection reads what the turn
    already fetched; a lookup still in flight is treated as absent rather than
    awaited, because the decision is synchronous and a product database may
    never hold up a question."""
    import handlers.tool_executor as TE

    data = _interpreted()
    spreads = await turn._variant_spreads(data, mode="moderate", targets=None)
    assert spreads

    async def _boom(*a, **k):
        raise AssertionError("the ask fetched again")
    monkeypatch.setattr(TE, "_fetch_usda_off", _boom)
    monkeypatch.setattr(TE, "_fetch_usda_off_uncached", _boom)
    monkeypatch.setattr(off, "search_variants", _boom)

    found = turn._ask_candidates(data)
    assert found, "the already-fetched shelf produced nothing"


async def test_a_dead_lookup_costs_the_turn_nothing(turn, monkeypatch):
    """A turn never loses its decision because a product database failed."""
    import skills.nutrition.ask_candidates as AC

    def _boom(*a, **k):
        raise RuntimeError("product database on fire")
    monkeypatch.setattr(AC, "candidates_for", _boom)

    data = _interpreted()
    await turn._variant_spreads(data, mode="moderate", targets=None)
    _, decision = await _plan(turn, data)
    assert decision is not None
    assert decision.staged_items
    assert not decision.staged_items[0].candidate_products


async def test_an_item_with_nothing_fetched_is_left_alone(turn):
    """A generic food nobody looked up stages exactly as it does today."""
    from core.food_pipeline import plan_turn

    data = {"action": "log", "items": [{"food": "leftover soup",
                                        "calories": 180}]}
    decision = plan_turn(data, turn_id=_TURN, message="had leftover soup",
                         mode="moderate",
                         item_candidates=turn._ask_candidates(data))
    assert decision is not None
    assert decision.staged_items[0].candidate_products == ()


# ── a prior shortens the question; it never removes it ────────────────────────
_HAPPY_WOLF = {"action": "log", "items": [{
    "food": "Happy Wolf chocolate chip bar", "brand": "Happy Wolf",
    "branded": True, "amount": 1, "unit": "bar", "calories": 110,
    "protein": 6, "carbs": 10.9, "fat": 4.7}]}

_SHELF = {"happy wolf chocolate chip bar": [
    {"name": "Happy Wolf Chocolate Chip Bar"},
    {"name": "Happy Wolf Strawberry Bar"},
    {"name": "Happy Wolf Apple Cinnamon Bar"},
    {"name": "Happy Wolf Choco-Banana Bar"}]}


@pytest.fixture(autouse=True)
def _identity_ask_on(monkeypatch):
    """These cover the flagged behaviour, so they switch it on explicitly.
    Everything else in the suite runs with it off, which is how it ships."""
    monkeypatch.setenv("FOOD_IDENTITY_ASK", "true")


def _plan_identity(message, rows, regulars=None):
    from core.food_pipeline import plan_turn
    return plan_turn(_HAPPY_WOLF, turn_id="t", message=message,
                     mode="moderate", variant_rows=rows, regulars=regulars)


def test_a_flavour_we_invented_is_asked_about_when_the_shelf_is_wide():
    """Production, turn #8338: "I just had a happy wolf bar" logged as "Happy
    Wolf chocolate chip bar" — a flavour nobody stated, from their most-logged
    prior, asserted as fact. Happy Wolf carries four."""
    decision = _plan_identity("I just had a happy wolf bar", _SHELF)
    assert decision.asks, "the invented flavour was not questioned"
    prompt = decision.question.prompt
    # Offered in the shelf's own words, trimmed to what distinguishes them.
    assert "Strawberry" in prompt and "Apple Cinnamon" in prompt


def test_a_shelf_with_no_real_alternative_says_nothing():
    """When every sibling carries the same flavour words, there was never a
    choice — so there is nothing to ask and nothing to disclose.

    This replaces an assertion that the assumption is stated here. That was
    written before the shelf gate, and the gate makes it unreachable by
    construction: the words are subtracted as product-line boilerplate, so
    nothing reads as invented. Stating "went with the chocolate chip" when the
    shelf offers only chocolate chip would be disclosing a decision nobody
    made.
    """
    shelf = {"happy wolf chocolate chip bar": [
        {"name": "Happy Wolf Chocolate Chip Bar"},
        {"name": "Happy Wolf Bar Chocolate Chip"}]}   # one product, two labels
    decision = _plan_identity("I just had a happy wolf bar", shelf)
    assert not decision.asks
    assert not [a for a in decision.staged_items[0].assumptions
                if a.field_name == "variant"]


def test_no_shelf_means_no_guess_about_what_was_chosen():
    """Deliberately narrow. Without siblings there is no way to tell a flavour
    from product-line boilerplate — "caramel cashew Barebells bar" logged as
    "...Protein Bar" adds the word "protein", and asking which protein it was
    is an interrogation about the product line. No stopword list can decide it
    either: "protein" is boilerplate on a bar and the whole point on a shake.

    The cost is a silent turn when Open Food Facts has nothing; the fetch gate
    (`_identity_was_invented`) exists so that is rare, because a turn that
    invented a specifier now earns the lookup.
    """
    decision = _plan_identity("I just had a happy wolf bar", None)
    assert not decision.asks
    assert not [a for a in decision.staged_items[0].assumptions
                if a.field_name == "variant"]


def test_naming_the_flavour_yourself_invents_nothing():
    """No question, no assumption — they said it, so nothing was chosen."""
    decision = _plan_identity("had a happy wolf chocolate chip bar", _SHELF)
    assert not decision.asks
    assert not (decision.clarification.assumptions or ())


def test_a_generic_food_gaining_a_word_is_not_an_invented_product():
    """"chicken" -> "chicken breast" is normalisation. Treating it as an
    invented PRODUCT would interrogate people about groceries.

    The turn may still ask about the AMOUNT — "some chicken" is a vague
    measure and that question predates this and is correct. What must not
    appear is an identity doubt or a chosen-product assumption.
    """
    from core.food_pipeline import plan_turn
    data = {"action": "log", "items": [{"food": "chicken breast",
                                        "calories": 180}]}
    decision = plan_turn(data, turn_id="t", message="had some chicken",
                         mode="moderate", variant_rows=None)
    item = decision.staged_items[0]
    assert not [a for a in item.ambiguities if a.field_name == "variant"]
    assert not [a for a in item.assumptions if a.field_name == "variant"]


def test_the_rule_holds_in_a_language_it_was_never_written_for():
    """The rule is "words they did not write", so it needs no vocabulary — and
    the proof of that is a script the code has never seen.

    Asserted by RUNNING it, not by grepping the source for English words. A
    grep for "chocolate" passes on a file whose docstring quotes the incident,
    and this session already had to convert two source greps that broke on a
    comment while covering nothing.
    """
    from core.food_pipeline import plan_turn

    data = {"action": "log", "items": [{
        "food": "Барни шоколадный", "brand": "Барни", "branded": True,
        "amount": 1, "unit": "шт", "calories": 140}]}
    shelf = {"барни шоколадный": [{"name": "Барни шоколадный"},
                                  {"name": "Барни молочный"},
                                  {"name": "Барни клубничный"}]}
    # They named the brand only; the flavour is ours.
    decision = plan_turn(data, turn_id="t", message="съел барни",
                         mode="moderate", variant_rows=shelf)
    assert decision.asks, "the invented flavour was not questioned in Russian"
    assert [a for a in decision.staged_items[0].assumptions
            if a.field_name == "variant"]

    # ...and naming it themselves invents nothing, in the same language.
    settled = plan_turn(data, turn_id="t2", message="съел барни шоколадный",
                        mode="moderate", variant_rows=shelf)
    assert not [a for a in settled.staged_items[0].assumptions
                if a.field_name == "variant"]
