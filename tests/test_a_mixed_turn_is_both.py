"""A message that mentions food and something else is both, not either.

`FoodResponsePlan.intent` is singular, so GENERAL_CONVERSATION is mutually
exclusive with COMMIT and CLARIFY rather than sitting alongside them. The food
half arrived as approved facts and a narrow brief; everything else arrived as
`user_message` — unstructured background — and the specific task won.

    "I had chicken and rice after a brutal meeting. I think I'm going to quit."

The plan understood chicken, rice and a disposition. It had no representation
of the meeting, the distress, or the fact that food was one part of the turn.
COMMIT's brief said "return an empty string if there is nothing useful" and its
policy allowed none, so **silence was the compliant answer**.

`user_emotional_context` has been on the plan since it was written and is
populated by nothing anywhere — which is the shape of the whole problem: the
capability was declared, never made an obligation.

And it is not only emotional. "I ate this before my workout", "we were
celebrating our anniversary", "the restaurant messed up my order", "I made this
for my son too" carry obligations with no feeling attached.
"""
import pytest

from core.food_response import (ConversationalContext, FoodItemSummary,
                                FoodResponseIntent, FoodResponsePlan, Reason,
                                apply_policy, build_prompt, contextual_preface,
                                fallback, validate)

ITEMS = (FoodItemSummary(name="chicken and rice", portion="1 plate"),)


def _ctx(**kw):
    base = dict(topic="quitting their job",
                user_statement="I think I'm going to quit",
                emotional_signal="distressed",
                response_obligation="offer support before discussing food",
                priority="important",
                approved_acknowledgement="That sounds like a lot to sit with.")
    base.update(kw)
    return ConversationalContext(**base)


def _plan(ctx=None, intent=FoodResponseIntent.COMMIT):
    return apply_policy(FoodResponsePlan(
        intent=intent, committed_items=ITEMS,
        conversational_context=ctx, card_will_render=True))


# ── the policy reserves room, and withdraws permission to say nothing ─────────

def test_a_mixed_turn_may_not_be_answered_with_silence():
    """COMMIT's budget was written for a turn where the card says everything.
    The card cannot acknowledge a person."""
    assert _plan(_ctx()).allow_no_text is False
    assert _plan(None).allow_no_text is True


def test_a_mixed_turn_gets_room_to_answer_in():
    mixed, food_only = _plan(_ctx()), _plan(None)
    assert mixed.max_sentences > food_only.max_sentences
    assert mixed.max_words > food_only.max_words


# ── validation names the real failure ─────────────────────────────────────────

def test_an_empty_reply_is_refused_for_ignoring_them_not_for_being_empty():
    """The reason code matters: "empty_not_allowed" sends the next reader to
    the length rules, which are not what went wrong."""
    result = validate("", _plan(_ctx()))
    assert result.ok is False
    assert result.reason == Reason.MISSED_CONVERSATIONAL_CONTEXT


@pytest.mark.parametrize("priority", ["important", "urgent"])
def test_material_context_cannot_be_answered_with_silence(priority):
    assert validate("", _plan(_ctx(priority=priority))).ok is False


def test_ordinary_context_does_not_force_a_reply():
    """"I ate this before my workout" is worth knowing and not worth forcing a
    sentence about. Only important/urgent is an obligation."""
    plan = _plan(_ctx(priority="normal", topic="pre-workout timing"))
    assert validate("", plan).reason != Reason.MISSED_CONVERSATIONAL_CONTEXT


# ── the prompt carries it as an obligation ────────────────────────────────────

def test_the_prompt_states_the_obligation_not_just_the_words():
    prompt = build_prompt(_plan(_ctx()))
    assert "NON-FOOD CONTEXT THAT MUST NOT BE IGNORED" in prompt
    assert "quitting their job" in prompt
    assert "offer support before discussing food" in prompt


def test_an_urgent_context_says_the_food_half_may_wait():
    assert "urgent" in build_prompt(_plan(_ctx(priority="urgent"))).lower()


def test_a_food_only_turn_is_unchanged():
    assert "NON-FOOD CONTEXT" not in build_prompt(_plan(None))


# ── the fallback answers both halves, and never improvises ────────────────────

def test_the_fallback_leads_with_the_approved_acknowledgement():
    text = fallback(_plan(_ctx(response_obligation="briefly acknowledge")))
    assert text.startswith("That sounds like a lot to sit with.")
    assert len(text) > len("That sounds like a lot to sit with."), \
        "the food half still has to be there"


def test_the_fallback_never_invents_a_reply_to_distress():
    """`fallback()` runs when the composer has already failed twice. A
    deterministic renderer improvising a response to "I'm going to quit" is a
    worse failure than saying nothing about it — so with no approved wording it
    says nothing, and the food half stands alone.
    """
    bare = _ctx(approved_acknowledgement="", approved_fallback_response="")
    assert contextual_preface(_plan(bare)) == ""
    assert "quit" not in fallback(_plan(bare)).lower()


def test_a_food_only_fallback_is_untouched():
    assert contextual_preface(_plan(None)) == ""
