"""A clarification never states a figure for the line it is asking about.

The shipped sentence this exists to stop:

    "You've got the hand roll down at 230 calories and 10g protein, that's
     your reading so far. The catch is which one you grabbed: was it the egg
     roll, or a salmon, tuna, or spicy tuna hand roll?"

The first sentence settles the one item whose identity is the open question,
and the next contradicts it.

The first fix computed endpoints — the reading ± half the span, floored at zero
— and shipped this instead:

    "Cheez Doodles, somewhere between 0 and 500 cal, 2g protein. That puts the
     snack somewhere in the 0 to 500 range depending on how much you had."

Which is worse, and wrong in a way worth naming: nobody eats zero calories of a
thing they just said they ate. Pack-size endpoints fail the same way from the
other end — a 24 oz share bag is a real product and a ridiculous thing to offer
as an equal option for one sitting. Both compute plausibility out of data that
does not encode it, and whether a food is eaten whole or eaten FROM is world
knowledge that varies by product, size and occasion.

So there is no formula here any more. What this file pins is the part that IS a
rule: the open line is never asserted, the settled lines keep their figures,
the evidence reaches the writer, and the range — if one is offered — is left to
the sentence, which is the only place that can weigh whether an end is
plausible. The commit path is untouched either way: a clarification writes
nothing, so its numbers are framing, and `validate()` guards the other half.
"""
from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, apply_policy, build_prompt)
from core.food_turn import unknowns_from_decision
from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        build_ambiguity)


def _ambiguity(*, span=150, calories=305, options=()):
    return build_ambiguity(
        staged_item_id="s1", ambiguity_type=AmbiguityType.PRODUCT_VARIANT,
        field_name="variant", mode="moderate", calorie_span=span,
        impact_basis_cal=calories, options=options)


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


# ── no formula survives ───────────────────────────────────────────────────────
def test_there_is_no_computed_endpoint_pair():
    """`calorie_range` is gone and nothing replaced it. The WIDTH stays: it
    ranks questions honestly and `stakes` is built from it."""
    amb = _ambiguity(span=400, calories=100)
    assert not hasattr(amb, "calorie_range")
    assert amb.calorie_span == 400


def test_unknowns_carry_the_swing_and_the_choice_but_no_endpoints():
    unknowns = unknowns_from_decision(_decision(_ambiguity(options=(
        AmbiguityOption("egg roll", 0.4),
        AmbiguityOption("spicy tuna hand roll", 0.35)))))
    assert len(unknowns) == 1
    assert unknowns[0]["stakes"] == 150.0
    assert unknowns[0]["options"] == ("egg roll", "spicy tuna hand roll")
    assert "ranges" not in unknowns[0], (
        "an endpoint pair here is the formula coming back")


# ── the open line is never asserted ───────────────────────────────────────────
def test_the_open_line_is_not_given_a_figure():
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity()))))
    assert "hand roll — 305 cal" not in prompt
    assert "do not state it as settled" in prompt
    # The settled line keeps its number — this is a rule about the line being
    # asked about, not a ban on numbers.
    assert "miso soup — 75 cal" in prompt


def test_an_unpriced_doubt_is_still_marked_open():
    """Most identity questions have no span until the candidates are costed.
    Failing to price a doubt is not a licence to state the number."""
    prompt = build_prompt(_plan(unknowns_from_decision(
        _decision(_ambiguity(span=None)))))
    assert "hand roll — 305 cal" not in prompt
    assert "do not state it as settled" in prompt


def test_a_meal_with_nothing_open_is_unchanged():
    prompt = build_prompt(_plan(()))
    assert "hand roll — 305 cal" in prompt
    assert "the meal total is a range too" not in prompt


# ── what the writer is told about ranges ──────────────────────────────────────
def test_the_brief_demands_plausible_ends_and_names_both_failures():
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity()))))
    assert "A PERSON WOULD ACTUALLY OFFER" in prompt
    assert "bottom end of zero is never right" in prompt
    assert "nobody finishes in one go" in prompt


def test_the_roll_up_inherits_the_doubt():
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity()))))
    assert "the meal total is a range too" in prompt


def test_the_choice_is_offered_once_and_the_score_stays_hidden():
    """One owner for the range. The brief used to print endpoints here AND in
    the reading block, which is why the shipped text said it twice."""
    prompt = build_prompt(_plan(unknowns_from_decision(_decision(_ambiguity(
        options=(AmbiguityOption("egg roll", 0.4),
                 AmbiguityOption("spicy tuna hand roll", 0.35)))))))
    assert "they are choosing between: egg roll / spicy tuna hand roll" in prompt
    assert "SAY THIS RANGE" not in prompt
    # `stakes` is a materiality score; nobody says "worth ~150 cal" out loud.
    assert "never say this number" in prompt
