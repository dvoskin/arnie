"""A turn carrying something to answer is not routine, whatever else it wrote.

"Chicken and rice after a brutal meeting. I think I'm going to quit." commits
food, so its intent is COMMIT, so it drew the micro acknowledgement brief. That
brief says:

    No coaching, no next move, no question: they did not ask one and the turn
    did not raise one.

while `build_prompt` adds, for the non-food half:

    Answer or acknowledge this in the SAME reply ... Do not write as though
    they had submitted a food record.

One prompt, two instructions, and the model picks. That is the same defect
that suppressed `points` and turned clarifications into silent logs — a prompt
arguing with itself resolves somewhere, and the losing side is invisible. So
the profile is chosen from the PLAN, not the intent alone.

The rest of this file is the end-to-end path the mixed-turn work depends on,
pinned because every hop of it is a place the obligation can be dropped
silently: the interpreter reports it, `_context_from` sanitises it, the plan
carries it, and `build_prompt` states it. A break anywhere reads as Arnie
ignoring what someone said, which is the failure the whole feature exists to
prevent.
"""
import pytest

import core.food_turn as FT
from core.conversation import _conversational_context as build_ctx
from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, arnie_voice, build_prompt,
                                voice_profile_for)

MIXED = {"action": "log",
         "items": [{"food": "Chicken and rice"}],
         "context": {"topic": "quitting their job",
                     "said": "I think I'm going to quit",
                     "signal": "stressed", "priority": "important"}}
FOOD_ONLY = {"action": "log", "items": [{"food": "Chicken and rice"}]}


def _plan(data) -> FoodResponsePlan:
    """Built the way production builds it: the interpreter's dict through the
    sanitiser, then the typed obligation."""
    return FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        user_message="chicken and rice after a brutal meeting",
        committed_items=(FoodItemSummary(name="Chicken and rice"),),
        conversational_context=build_ctx(FT._context_from(data)))


def _flat(plan) -> str:
    return " ".join(build_prompt(plan).split())


# ── the contradiction ────────────────────────────────────────────────────────
def test_a_mixed_turn_does_not_get_the_routine_brief():
    assert voice_profile_for(FoodResponseIntent.COMMIT,
                             _plan(MIXED)) == "coaching"


def test_a_food_only_turn_stays_routine():
    """The upgrade must be earned, or every log pays the coaching brief."""
    assert voice_profile_for(FoodResponseIntent.COMMIT,
                             _plan(FOOD_ONLY)) == "micro_acknowledgement"


def test_the_prompt_never_both_demands_and_forbids_an_acknowledgement():
    """The property, stated directly. Whichever profile is chosen, the prompt
    must not contain both instructions."""
    for data in (MIXED, FOOD_ONLY):
        flat = _flat(_plan(data))
        demands = "Answer or acknowledge this in the SAME reply" in flat
        forbids = "no next move, no question" in flat
        assert not (demands and forbids), (
            "the prompt asks for an acknowledgement and forbids one at once")


def test_the_mixed_turn_is_asked_to_answer():
    assert "Answer or acknowledge this in the SAME reply" in _flat(_plan(MIXED))


def test_the_food_only_turn_is_told_to_stop():
    assert "no next move, no question" in _flat(_plan(FOOD_ONLY))


def test_the_intent_alone_still_answers_when_there_is_no_plan():
    """Callers that pass no plan — the trace, older call sites — keep working
    and get the intent's default."""
    assert voice_profile_for(
        FoodResponseIntent.COMMIT) == "micro_acknowledgement"


# ── the obligation survives every hop ────────────────────────────────────────
def test_the_interpreter_reports_it():
    raw = FT._context_from(MIXED)
    assert raw and raw["topic"] == "quitting their job"


def test_a_food_only_message_carries_no_obligation():
    """Absent is the common case and the right default — inventing one would
    make every meal log sound like it was consoling someone."""
    assert FT._context_from(FOOD_ONLY) is None


def test_the_plan_carries_it_as_a_typed_obligation():
    ctx = _plan(MIXED).conversational_context
    assert ctx is not None
    assert ctx.user_statement == "I think I'm going to quit"
    assert ctx.emotional_signal == "stressed"
    assert ctx.is_material, "important/urgent means ignoring it is wrong"


def test_the_prompt_states_what_the_reply_owes_them():
    flat = _flat(_plan(MIXED))
    assert "quitting their job" in flat
    assert "I think I'm going to quit" in flat


def test_the_coaching_brief_is_the_one_that_mentions_non_food_context():
    """The brief and the plan have to agree about this being part of the job.
    The micro brief never mentions it, which is why a mixed turn must not
    use it."""
    assert "not about food" in " ".join(
        arnie_voice(FoodResponseIntent.COMMIT, _plan(MIXED)).split())


# ── the sanitiser is the gate, and it holds either way round ────────────────
@pytest.mark.parametrize("raw", [{}, {"topic": "", "said": ""}, None,
                                 "not a dict", {"signal": "stressed"}])
def test_nothing_to_acknowledge_produces_no_obligation(raw):
    """`{"signal": "stressed"}` with no topic and no statement included: a
    feeling with nothing attached to it is not something a reply can answer."""
    assert FT._context_from({"context": raw}) is None


def test_an_over_long_statement_is_capped_not_dropped():
    raw = FT._context_from({"context": {"topic": "x" * 400,
                                        "said": "y" * 900}})
    assert len(raw["topic"]) <= 120 and len(raw["said"]) <= 300


def test_an_unknown_priority_falls_back_to_normal():
    """Priority decides whether ignoring this is wrong. An unrecognised value
    must not silently read as urgent."""
    raw = FT._context_from({"context": {"topic": "x", "priority": "CRITICAL!"}})
    assert raw["priority"] == "normal"
