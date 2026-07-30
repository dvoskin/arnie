""""It's the same one" logs the meal as it was read — no model, no escape.

Production, 2026-07-29 (`legacy_reason=interpreter_none`): a clarification asked
"the Harvest Cheddar ones like last time, or a different flavor?" and the answer
"It's the same one" fell out of the structured lane entirely. The pending stored
no `response_schema`, so the per-schema parsers never ran; the interpreter read
the message as contentless and returned pass; and the turn escaped to legacy
with the question — and the stashed interpretation — lost.

A premise confirmation is a COMMAND ("log it as you read it"), and commands need
no schema. These tests run the real `food_turn.run` with no model configured:
the deterministic path must settle the turn before any model call, which is the
point — an affirmation is not material for a model to interpret.
"""
import asyncio
from types import SimpleNamespace

import pytest

from core import food_turn as FT
from skills.nutrition.answer_parsers import ClarificationCommand, parse_command


def _user(mode="quick"):
    return SimpleNamespace(
        id=999, first_name="Test",
        weight_kg=84.0, height_cm=180.0, age=34, sex="male",
        preferences=SimpleNamespace(food_logging_mode=mode,
                                    calorie_target=2165, protein_target=180))


PRIOR = {
    "original": "Having the sun chips again",
    "question": "The Harvest Cheddar ones like last time, or a different flavor?",
    "kind": "clarify", "ask_count": 1,
    "items": [{"food": "Sun Chips Harvest Cheddar", "amount": 1,
               "unit": "bag", "calories": 210, "protein": 3}],
}


# ── the command is recognised, wrapped or bare ────────────────────────────────
@pytest.mark.parametrize("text", [
    "It's the same one",           # the production message, verbatim
    "the same one",
    "same one",
    "it was the same one",
    "Yeah, the same one",
    "yes same",
    "same as last time",
    "Same as always.",
])
def test_a_premise_confirmation_parses_as_keep_as_read(text):
    assert parse_command(text) is ClarificationCommand.KEEP_AS_READ, text


@pytest.mark.parametrize("text", [
    "same again but with rice",     # a NEW report that mentions sameness
    "the same but only half",       # modifies the premise — not a confirmation
    "not the same one",             # negation
    "it wasn't the same one",
    "make it the same as yesterday's dinner entry",
    "skip it",                      # other commands keep their own meaning
    # "usual" is NOT a premise confirmation: it points at the user's history,
    # which the stash does not carry. It stays with the regulars machinery —
    # `test_the_normal_one_stays_pending` owns that boundary.
    "the usual",
    "It's the usual one",
])
def test_a_message_that_adds_or_negates_is_not_keep_as_read(text):
    assert parse_command(text) is not ClarificationCommand.KEEP_AS_READ, text


# ── the handler settles the turn from the stash, deterministically ────────────
def test_the_answer_logs_the_stashed_items_without_a_model():
    """The full entry point, no model configured: the deterministic command
    path must return the write before any model call is attempted."""
    result = asyncio.run(FT.run("It's the same one", _user(), prior=PRIOR,
                                thread_active=True))
    assert result is not None, "the turn escaped the lane"
    assert result["action"] == "log"
    calls = result["tool_calls"]
    assert [c["name"] for c in calls] == ["log_food"]
    assert calls[0]["input"]["food_name"] == "Sun Chips Harvest Cheddar"
    assert calls[0]["input"]["calories"] == 210
    # The commit is voiced by the composer/floor like every other log turn —
    # the handler must not carry its own English literal (cause E).
    assert result["say"] == ""


def test_every_stashed_item_commits_not_just_the_first():
    prior = dict(PRIOR)
    prior["items"] = [
        {"food": "Sun Chips Harvest Cheddar", "amount": 1, "unit": "bag",
         "calories": 210},
        {"food": "Turkey sandwich", "amount": 1, "unit": "", "calories": 380},
    ]
    result = asyncio.run(FT.run("same one", _user(), prior=prior,
                                thread_active=True))
    assert result is not None and result["action"] == "log"
    names = [c["input"]["food_name"] for c in result["tool_calls"]]
    assert names == ["Sun Chips Harvest Cheddar", "Turkey sandwich"]


def test_no_stash_means_the_interpreter_still_owns_the_turn():
    """A confirmation with nothing stashed has nothing to commit. The handler
    must decline (None) so the interpreter runs with the answer in context —
    NOT invent a write."""
    from core.food_turn import _handle_clarification_command
    prior = {k: v for k, v in PRIOR.items() if k != "items"}
    out = _handle_clarification_command(ClarificationCommand.KEEP_AS_READ,
                                        prior, "same one")
    assert out is None


def test_an_unloggable_stash_declines_rather_than_half_committing():
    from core.food_turn import _handle_clarification_command
    prior = dict(PRIOR)
    prior["items"] = [{"food": ""}]         # nothing _log_call can write
    out = _handle_clarification_command(ClarificationCommand.KEEP_AS_READ,
                                        prior, "same one")
    assert out is None


# ── the selection parser tolerates the same lead-ins ──────────────────────────
def test_vague_selection_matches_the_wrapped_form():
    from skills.nutrition.answer_parsers import _VAGUE_SELECTIONS
    for t in ("It's the same one", "the usual", "it was the regular one",
              "yeah the normal kind"):
        assert _VAGUE_SELECTIONS.match(t), t
    for t in ("same again but with rice", "a regular coke and fries"):
        assert not _VAGUE_SELECTIONS.match(t), t
