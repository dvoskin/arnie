"""A PORTION question offers the bracket it already computed.

Measured on prod 2026-08-03: of the last 40 `food_structured_ask` rows, one
carried any options at all. The producers explain it — the pipeline branch
builds options from `FoodAmbiguity.top_options`, so it fires only where a
scored ambiguity with real alternatives exists, and the interpreter branch
looks up a brand shelf and nothing else. So the commonest ask of all, "about
how much?", ships no chips and the user types.

The portion bracket was never missing. `_portion_stakes` already reaches the
calibrated ontology to RANK a portion question — `_vague_measure_in` for the
user's own word, `distribution_for` for what that word spans — and then throws
the distribution away. `derive_vague_quantities` turns the identical
distribution into "one tablespoon" / "two tablespoons" on the other branch.
The same numbers, offered instead of discarded.

WHAT MUST NOT HAPPEN. Options have to derive from something real. A count ask
offering "8 / 10 / 12" when nothing computed those states a precision the user
never gave, and a question whose bracket is not derivable ships no chips —
that is the correct outcome, not a gap to paper over.
"""
from core.food_turn import _portion_options


# ── the bracket is real, and it is the ontology's ────────────────────────────

def test_a_vague_portion_offers_the_ontologys_own_endpoints():
    """"I'm having some chicken and rice" — prod #2090 and #2075, both shipped
    with `options: []`.

    "some" is the user's own word; the ontology prices it at 30-200g for an
    uncategorised food. Those endpoints are what `_measure_options` already
    renders on the pipeline branch, and they are what the composer is already
    told to voice ("both ends have to be things they could plausibly have
    eaten"). They reach the wire here.
    """
    opts = _portion_options("Chicken", "I'm having some chicken and rice",
                            items=[{"food": "Chicken", "amount": 6,
                                    "unit": "oz", "calories": 280}])
    assert opts == ["30g", "200g"]


def test_the_category_row_wins_over_the_fallback():
    """Rice has its own ontology row, so its bracket is 80-260g where the
    uncategorised chicken gets the broad 30-200g default. Two foods, two
    different real answers — which is the whole reason for deriving them
    rather than writing a table of numbers here."""
    opts = _portion_options("rice", "just some rice",
                            items=[{"food": "rice", "amount": 1,
                                    "unit": "cup", "calories": 200}])
    assert opts == ["80g", "260g"]


def test_spoon_measures_stay_in_spoons():
    """PQ#2029's precedent: `ClarificationOption(label='one tablespoon')`. A
    question answerable from memory beats one that needs a conversion first,
    and `_measure_options` already owns that judgement — this must not grow a
    second phrasing rule."""
    opts = _portion_options("peanut butter", "a scoop of peanut butter",
                            items=[{"food": "peanut butter", "amount": 2,
                                    "unit": "tbsp", "calories": 190}])
    assert opts == ["one tablespoon", "two tablespoons"]


# ── and it stays silent whenever it is not ───────────────────────────────────

def test_a_stated_amount_is_never_re_asked():
    """"I also had a special roll ... just 1 piece tho" — prod 2026-08-03.

    "piece" is in VAGUE_MEASURES, so the measure lookup matches when it lands
    in the food's own clause. But the interpreter recorded the amount in THE
    USER'S OWN unit — 1 piece — which is the pipeline branch's rule ("only
    when our unit DIFFERS from the user's word"). The vagueness is inherent to
    the measure, not a silent conversion, and offering "30g or 200g" against a
    portion they counted is the truffle-fries incident arriving from the other
    side.
    """
    opts = _portion_options(
        "special roll", "I had a piece of the special roll",
        items=[{"food": "special roll", "amount": 1, "unit": "piece",
                "calories": 460}])
    assert opts == []
    # Same food, same message, but recorded in a unit of OURS — the conversion
    # this exists to surface. Now the bracket is worth offering.
    assert _portion_options(
        "special roll", "I had a piece of the special roll",
        items=[{"food": "special roll", "amount": 130, "unit": "g"}]) \
        == ["30g", "200g"]


def test_the_clause_rule_already_excludes_a_trailing_count():
    """Prod 2026-08-03, verbatim: "I also had a special roll ... just 1 piece
    tho". The count sits in its own clause, which shares no tokens with the
    food, so no measure attaches and no chips are offered — the stated amount
    is protected before the unit gate is even reached."""
    assert _portion_options(
        "special roll", "I also had a special roll, just 1 piece tho",
        items=[{"food": "special roll", "amount": 1, "unit": "piece"}]) == []


def test_a_hedge_in_a_neighbours_clause_does_not_reach_this_food():
    """The measured gap, recorded rather than papered over.

    In "I'm having some chicken and rice" the rice gets NO chips. The clause
    rule in `_vague_measure_in` attaches a measure only inside the clause that
    names the food, and "some" sits in the chicken's — deliberately, because
    position is what wrongly attaches "a scoop of peanut butter" to "200g of
    chicken". So the chicken is covered by this change and the rice is not.

    Reading "some" as distributing over the conjunction may well be right, but
    it is a change to a function BOTH ask branches share and it needs its own
    evidence. Inventing a bracket for the rice here, where the user's own word
    never reached it, is exactly the precision this module refuses to state.
    """
    assert _portion_options("Rice", "I'm having some chicken and rice",
                            items=[{"food": "Rice", "amount": 1,
                                    "unit": "cup"}]) == []


def test_no_vague_measure_means_no_options():
    """The user said nothing hedged, so there is no bracket of theirs to
    offer. An unpriceable question ships no chips."""
    assert _portion_options("Chicken", "I had 6oz of chicken",
                            items=[{"food": "Chicken", "amount": 6,
                                    "unit": "oz"}]) == []


def test_a_tight_spread_is_not_a_choice():
    """Below VAGUE_SPREAD_RATIO the wording is vague and the fact is precise
    enough — the same bar `derive_vague_quantities` applies before it raises
    the ambiguity at all. Two chips 20% apart are theatre."""
    from unittest.mock import patch

    from skills.nutrition.portions import QuantityDistribution
    tight = QuantityDistribution(median_g=100.0, lower_g=95.0, upper_g=105.0)
    with patch("skills.nutrition.portions.distribution_for",
               return_value=tight):
        assert _portion_options("Chicken", "some chicken",
                                items=[{"food": "Chicken", "unit": "oz"}]) == []


def test_an_unrecognised_hedge_offers_nothing():
    """"a smidge" is not a measure this system has ever priced. Nothing real
    exists for it, so nothing is offered."""
    assert _portion_options("Chicken", "I had a smidge of chicken",
                            items=[{"food": "Chicken", "unit": "oz"}]) == []


def test_options_never_raise():
    """A chip row is a convenience. Losing the QUESTION to build one is not a
    trade worth making, so every failure mode degrades to no chips."""
    assert _portion_options("", "", items=None) == []
    assert _portion_options(None, None, items=None) == []
    # A malformed `items` costs the unit gate its input, never the turn.
    assert isinstance(
        _portion_options("Chicken", "some chicken", items="not a list"), list)


# ── the return site attaches them without displacing a shelf ─────────────────

def test_a_branded_shelf_still_wins_its_own_question():
    """"just had some quest chips" is a portion word over a branded product.
    The shelf is the better answer to "which one" and it is already looked up;
    portion options must not overwrite it.
    """
    from core.food_turn import _question_options

    out = _question_options(
        label="Quest chips", qs=["which flavor?"],
        found_by_label=[("Quest chips", ["Nacho Cheese", "BBQ"])],
        message="just had some quest chips",
        items=[{"food": "Quest chips", "amount": 1, "unit": "bag"}])
    assert out == ["Nacho Cheese", "BBQ"]


def test_a_portion_question_with_no_shelf_gets_the_bracket():
    from core.food_turn import _question_options

    out = _question_options(
        label="Chicken", qs=["rough amount - oz or a piece?"],
        found_by_label=[],
        message="I'm having some chicken and rice",
        items=[{"food": "Chicken", "amount": 6, "unit": "oz"}])
    assert out == ["30g", "200g"]


def test_points_become_questions_with_their_own_options():
    """The parse every interpreter-side ask now shares. Each question keeps
    its own options, so a tap is unambiguous about which question it answers —
    the shelf never bleeds onto the portion question beside it."""
    from core.food_turn import _questions_from_points

    out = _questions_from_points(
        [{"label": "Quest chips", "qs": ["which flavor?"]},
         {"label": "Chicken", "qs": ["rough amount - oz or a piece?"]},
         {"label": "", "q": "any sauce on it?"}],
        message="some quest chips and some chicken",
        items=[{"food": "Chicken", "amount": 6, "unit": "oz"},
               {"food": "Quest chips", "amount": 1, "unit": "bag"}],
        found_by_label=[("Quest chips", ["Nacho Cheese", "BBQ"])])

    assert out == [
        {"item": "Quest chips", "text": "which flavor?",
         "options": ["Nacho Cheese", "BBQ"]},
        {"item": "Chicken", "text": "rough amount - oz or a piece?",
         "options": ["30g", "200g"]},
        {"item": None, "text": "any sauce on it?", "options": []},
    ]


def test_the_fallbacks_point_shape_is_read_too():
    """`food_ledger.ambiguity_points` emits {label, q} rather than {label,
    qs} — the calorie-only fallback's shape. It must parse, or the path taken
    when the staged pipeline is off is also the path with no chips."""
    from core.food_turn import _questions_from_points

    out = _questions_from_points(
        [{"label": "Chicken", "q": "roughly how much?"}],
        message="just some chicken",
        items=[{"food": "Chicken", "amount": 6, "unit": "oz"}])
    assert out == [{"item": "Chicken", "text": "roughly how much?",
                    "options": ["30g", "200g"]}]


def test_a_question_with_no_real_options_still_ships():
    """A question that cannot be priced keeps its place in the list with an
    empty options row. Dropping it would renumber the groups the chips bind
    to."""
    from core.food_turn import _questions_from_points

    out = _questions_from_points([{"label": "Chicken", "qs": ["how much?"]}],
                                 message="I had 6oz of chicken", items=[])
    assert out == [{"item": "Chicken", "text": "how much?", "options": []}]


def test_a_non_portion_question_gets_nothing_from_the_ontology():
    """"how's it cooked, grilled or baked?" is a preparation question. The
    portion bracket answers a different question and would read as an answer
    to this one."""
    from core.food_turn import _question_options

    out = _question_options(
        label="Chicken", qs=["grilled or baked, and any sauce?"],
        found_by_label=[],
        message="I'm having some chicken",
        items=[{"food": "Chicken", "amount": 6, "unit": "oz"}])
    assert out == []
