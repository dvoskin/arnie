"""A clarification opens with the range, not with a point estimate.

The shipped sentence this exists to stop:

    "You've got the hand roll down at 230 calories and 10g protein, that's
     your reading so far. The catch is which one you grabbed: was it the egg
     roll, or a salmon, tuna, or spicy tuna hand roll? That's what moves the
     number."

The first sentence states a figure as settled for the ONE item whose identity
is the open question, and the next sentence contradicts it. The user reads a
decision that has been made, then a question about the decision.

The range was already computed. `FoodAmbiguity` carries `calorie_span`,
`protein_span`, `carb_span`, `fat_span` and `candidate_values` — labelled
options with confidences — and `unknowns_from_decision` summed the first into
one scalar named `stakes` and dropped the rest, one layer before the composer
needed it. A scalar ranks a question; it cannot phrase one.
"""
import pytest

from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, apply_policy, build_prompt)
from core.food_turn import unknowns_from_decision
from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        build_ambiguity)


def _ambiguity(*, span=150, calories=305, options=()):
    return build_ambiguity(
        staged_item_id="s1", ambiguity_type=AmbiguityType.PRODUCT_VARIANT,
        field_name="variant", mode="moderate", calorie_span=span,
        item_calories=calories, options=options)


def _decision(*ambiguities, name="hand roll"):
    item = type("Item", (), {"original_text": name,
                             "ambiguities": tuple(ambiguities)})()
    return type("Decision", (), {"staged_items": (item,)})()


def _plan(unknowns, *, open_calories=305):
    held = FoodItemSummary(name="hand roll", calories=open_calories, protein=10)
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY, card_will_render=False,
        resolved_items=(FoodItemSummary(name="miso soup", calories=75),),
        pending_items=(held,), unresolved_item=held,
        clarification_question="Which hand roll was it?",
        clarification_unknowns=unknowns, requires_answer=True))


# ── the endpoints exist, and survive the trip ────────────────────────────────
def test_the_span_becomes_endpoints_around_the_reading():
    """A span is a WIDTH. The reading is where it was measured from, so the
    endpoints are the reading either side of half of it."""
    assert _ambiguity(span=150, calories=305).calorie_range == (230, 380)


def test_an_unpriced_doubt_has_no_range_rather_than_a_made_up_one():
    assert _ambiguity(span=150, calories=None).calorie_range is None
    assert _ambiguity(span=None, calories=305).calorie_range is None


def test_a_range_never_runs_below_zero():
    low, high = _ambiguity(span=400, calories=100).calorie_range
    assert low == 0 and high == 300


def test_unknowns_from_decision_keeps_the_endpoints_and_the_options():
    """It kept `stakes` and threw the rest away. `stakes` still has a job —
    the mode thresholds are compared against it — so this is an addition, not
    a swap."""
    unknowns = unknowns_from_decision(_decision(_ambiguity(options=(
        AmbiguityOption("egg roll", 0.4),
        AmbiguityOption("spicy tuna hand roll", 0.35)))))
    assert len(unknowns) == 1
    assert unknowns[0]["stakes"] == 150.0
    assert unknowns[0]["ranges"] == {"hand roll": (230, 380)}
    assert unknowns[0]["options"] == ("egg roll", "spicy tuna hand roll")


def test_two_open_questions_about_one_food_widen_its_range():
    """Which product AND how much of it are two separate reasons the number
    could move. A range covering one and not the other claims more than we
    know."""
    wide = build_ambiguity(
        staged_item_id="s1", ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="consumed_fraction", mode="moderate",
        calorie_span=300, item_calories=305)
    unknowns = unknowns_from_decision(_decision(_ambiguity(), wide))
    spans = [u["ranges"]["hand roll"] for u in unknowns if u["ranges"]]
    assert (155, 455) in spans


# ── and reach the sentence ───────────────────────────────────────────────────
def test_the_open_line_is_written_as_a_range_not_a_figure():
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity()))))
    assert "hand roll — between 230 and 380 cal" in prompt
    # The settled item keeps its figure; only the open one loses it.
    assert "miso soup — 75 cal" in prompt
    assert "hand roll — 305 cal" not in prompt


def test_an_open_line_nobody_could_price_is_still_not_asserted():
    """Most identity questions have no span until the candidates themselves
    are costed. Failing to price the doubt is not a licence to state the
    number as settled."""
    prompt = build_prompt(_plan(unknowns_from_decision(
        _decision(_ambiguity(span=None)))))
    assert "hand roll — 305 cal" not in prompt
    assert "do not state it as settled" in prompt


def test_the_roll_up_is_a_range_when_any_line_is_open():
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity()))))
    assert "the meal total is a range too" in prompt


def test_a_meal_with_nothing_open_is_unchanged():
    """The reading block still states figures for a meal whose lines are all
    settled — this is a rule about the line being ASKED about, not a ban on
    numbers."""
    prompt = build_prompt(_plan(()))
    assert "hand roll — 305 cal" in prompt
    assert "the meal total is a range too" not in prompt


def test_the_brief_offers_the_range_and_the_choice():
    """`stakes` stays fenced off as reasoning material — it is a materiality
    score and nobody says "worth ~150 cal" out loud. The endpoints are the
    opposite: they are exactly how a person describes not knowing."""
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity(
        options=(AmbiguityOption("egg roll", 0.4),
                 AmbiguityOption("spicy tuna hand roll", 0.35)))))))
    assert "somewhere between 230 and 380 cal" in prompt
    assert "they are choosing between: egg roll / spicy tuna hand roll" in prompt
    assert "never say this number" in prompt
