"""What a clarification reports as pending is what the ENGINE held.

`clarify_plan` derived its hold set from the QUESTION:

    held = {question.staged_item_id}

One question names one staged item, so however many items the engine refused
to commit, the plan reported exactly one pending and handed the rest to the
composer as resolved. Probed at a1c26d3 on the meal below:

    strict: engine held=3   plan pending=1   resolved=['Peanut M&Ms', 'Banana']

Two consequences, both visible in production:

  * strict and moderate rendered BYTE-IDENTICAL replies while doing opposite
    things. Strictness is a statement about how much lands before the meal is
    understood, and the amount that landed never reached the sentence — so the
    setting was wired, working, and invisible.
  * `validate()` checks the text against `plan.pending_items`, and
    `pending_items` was missing most of what was pending. That is the likely
    source of the `reason=pending_as_committed` composer fallbacks in the logs.

The engine itself was never wrong: `test_the_pipeline_behind_the_gate_is_mode_aware`
has always asserted quick 3/0, moderate 2/1, strict 0/3.
"""
import pytest

from core.food_pipeline import plan_turn
from core.food_turn import clarify_plan, clarify_text

MESSAGE = ("I had like 15 peanut m&m, half a banana and a scoop of "
           "peanut butter")
INTERPRETED = {"items": [
    {"food": "Peanut M&Ms", "amount": 15, "unit": "pieces",
     "branded": True, "calories": 135},
    {"food": "Banana", "amount": 0.5, "unit": "banana", "calories": 53},
    {"food": "Peanut Butter", "amount": 1, "unit": "tbsp", "calories": 95},
]}


def _decide(mode):
    decision = plan_turn(INTERPRETED, turn_id="t", message=MESSAGE, mode=mode)
    assert decision is not None, f"{mode}: pipeline bailed to legacy"
    return decision


@pytest.mark.parametrize("mode,expected_held", [("moderate", 1), ("strict", 3)])
def test_pending_items_equals_the_engines_hold_set(mode, expected_held):
    decision = _decide(mode)
    assert decision.asks, f"{mode} was expected to ask"
    engine = set(decision.clarification.held_item_ids or ())
    assert len(engine) == expected_held, "the engine's own decision moved"

    plan = clarify_plan(decision, decision.question, user_message=MESSAGE)
    assert {i.staged_item_id for i in plan.pending_items} == engine
    # ...and the complement, so nothing is counted twice or lost.
    assert not ({i.staged_item_id for i in plan.resolved_items} & engine)
    assert len(plan.resolved_items) + len(plan.pending_items) == 3


def test_the_question_still_names_the_item_it_is_about():
    """`unresolved_item` is the subject of the sentence. With three items held
    it can no longer be "whichever came first"."""
    decision = _decide("strict")
    plan = clarify_plan(decision, decision.question, user_message=MESSAGE)
    assert plan.unresolved_item.staged_item_id == decision.question.staged_item_id


def test_strict_and_moderate_no_longer_read_the_same():
    """The whole point of the setting. A turn holding the entire meal says so;
    a turn boarding two of three does not."""
    texts = {}
    for mode in ("moderate", "strict"):
        decision = _decide(mode)
        texts[mode] = clarify_text(decision, decision.question,
                                   user_message=MESSAGE)
    assert texts["strict"] != texts["moderate"]
    assert "Nothing goes on the board until then." in texts["strict"]
    assert "Nothing goes on the board" not in texts["moderate"]


def test_the_composer_is_told_when_the_whole_meal_is_waiting():
    from core.food_response import build_prompt
    decision = _decide("strict")
    prompt = build_prompt(clarify_plan(decision, decision.question,
                                       user_message=MESSAGE))
    assert "NOTHING FROM THIS MEAL IS GOING ON THE BOARD" in prompt
    for name in ("Peanut M&Ms", "Banana", "Peanut Butter"):
        assert name in prompt.split("NOT LOGGED, still open:")[1]
