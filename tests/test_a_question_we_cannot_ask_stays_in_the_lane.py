"""An `ask` the lane cannot phrase must not become a turn the lane never sees.

`clarify_plan_from_points` returns None when `points` is empty, the empty text
that follows returned None from `_run_untraced`, and None is not a no-op — the
caller reads it as `_to_legacy("interpreter_none")` and hands the whole turn to
the legacy conversational path.

That path is the one this lane was built to replace. It has the full thread and
a free-form `log_food` with no resolver behind it, no portion ontology, no
materiality gate and no exactly-once executor. So the failure did not look like
a failure. It looked like Arnie answering from somewhere else — reaching into
the conversation for an unrelated order — because a different, older Arnie
answered that turn.

An empty `points` list takes one of two exits, and they look nothing alike:

  * IMMATERIAL — a cucumber, a tomato. `_proposed_ask_is_material` declines the
    question first, and the turn converts to a log INSIDE the lane. The row
    written is whatever the interpreter put in `items`, which for a model that
    expected to ask is a placeholder: "0.5 cup" for a food nobody measures in
    cups. Wrong-looking, but ours, and correctable on the card.
  * MATERIAL — a real meal. Nothing declines it, no question can be built, and
    the turn leaves the lane entirely.

The shipped trigger was a prompt edit (f3aa3be, reverted in 99f330a) that told
the interpreter "your entire output is the decision and the rows" while twelve
lines above the same prompt made `points` and `ambiguities` mandatory. The
trigger is not the defect. Any turn where the model omits `points` — a bad
sample, a truncation, a future prompt edit — reaches the same exit, and nothing
in the reply tells you it happened.

So the rule pinned here: a question we cannot phrase degrades to a log we can
stand behind, inside the lane, with the assumption carried onto the card. It
never degrades to a turn that leaves the lane.
"""
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT


def _interpreter(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


#: A question worth asking, with nothing to ask it with. The swing has to clear
#: materiality or `_proposed_ask_is_material` declines it one branch earlier and
#: this path is never reached — which is exactly how the first version of this
#: file passed against the unfixed code.
MATERIAL_ASK_NO_POINTS = {
    "action": "ask",
    "items": [{"food": "Chicken burrito", "amount": 1, "unit": "burrito",
               "calories": 900, "protein": 45, "carbs": 90, "fats": 38}],
    "ambiguities": [{"item": "Chicken burrito", "field": "size",
                     "impact_cal": 400, "impact_protein": 15,
                     "assumed": "a regular one, not the big one"}],
}


@pytest.mark.asyncio
async def test_it_does_not_hand_the_turn_to_legacy(monkeypatch):
    """The regression in one assertion. None here means the food lane is off
    for this turn and the user cannot tell."""
    monkeypatch.setattr(FT, "chat", _interpreter(MATERIAL_ASK_NO_POINTS))
    out = await FT.run("a chicken burrito", SimpleNamespace())
    assert out is not None, (
        "an unphrasable question fell through to the legacy lane, which logs "
        "with no resolver and no portion ontology behind it")


@pytest.mark.asyncio
async def test_the_food_is_written_by_this_lane(monkeypatch):
    monkeypatch.setattr(FT, "chat", _interpreter(MATERIAL_ASK_NO_POINTS))
    out = await FT.run("a chicken burrito", SimpleNamespace())
    assert out["action"] == "log"
    assert [c["input"]["food_name"] for c in out["tool_calls"]] == [
        "Chicken burrito"]
    assert out["tool_calls"][0]["input"]["quantity"] == "1 burrito"


@pytest.mark.asyncio
async def test_the_guess_is_carried_not_hidden(monkeypatch):
    """We did not learn the answer, we picked one — so the pick rides to the
    card where a tap corrects it. A silent guess is the failure mode this lane
    exists to prevent."""
    monkeypatch.setattr(FT, "chat", _interpreter(MATERIAL_ASK_NO_POINTS))
    out = await FT.run("a chicken burrito", SimpleNamespace())
    assumed = out["tool_calls"][0]["input"].get("assumptions") or []
    assert any("regular one" in str(a) for a in assumed), assumed


@pytest.mark.asyncio
async def test_a_real_question_still_reaches_the_user(monkeypatch):
    """The degrade must not swallow asks that CAN be phrased — that would trade
    this bug for the opposite one."""
    monkeypatch.setattr(FT, "chat", _interpreter({
        "action": "ask",
        "items": [{"food": "Chicken", "amount": 6, "unit": "oz",
                   "calories": 280, "protein": 52, "carbs": 0, "fats": 7}],
        "ambiguities": [{"item": "Chicken", "field": "prep",
                         "impact_cal": 180, "impact_protein": 6}],
        "points": [{"label": "Chicken", "qs": ["grilled, baked, or fried?"]}],
    }))
    out = await FT.run("some chicken", SimpleNamespace())
    assert out is not None and out["action"] == "ask"
    assert out["text"].strip()


@pytest.mark.asyncio
async def test_nothing_parsed_is_still_not_our_turn(monkeypatch):
    """The one case where None remains right: no question AND no food. There is
    nothing to keep in the lane, so the conversation belongs elsewhere."""
    monkeypatch.setattr(FT, "chat", _interpreter({"action": "ask"}))
    assert await FT.run("hey", SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_the_immaterial_exit_was_already_in_lane(monkeypatch):
    """The cucumber's path, for the record. `_proposed_ask_is_material` folds a
    trivial question into a log one branch earlier, so this half never left the
    lane even while the other half did — which is why the same broken prompt
    produced two symptoms that looked unrelated."""
    monkeypatch.setattr(FT, "chat", _interpreter({
        "action": "ask",
        "items": [{"food": "Cucumber", "amount": 0.5, "unit": "cup",
                   "calories": 8, "protein": 0, "carbs": 2, "fats": 0}],
        "ambiguities": [{"item": "Cucumber", "field": "amount",
                         "impact_cal": 12, "assumed": "about half a cup"}]}))
    out = await FT.run("a cucumber", SimpleNamespace())
    assert out is not None and out["action"] == "log"


# ── the conversion itself ────────────────────────────────────────────────────
def test_a_food_in_both_items_and_ready_is_written_once():
    """`ready` and `items` overlap whenever the model lists everything it
    parsed and then repeats the settled ones. Dict equality missed the
    duplicate when one key differed, which wrote six rows for four foods."""
    out = FT._ask_becomes_log({
        "action": "ask",
        "items": [{"food": "Cucumber", "amount": 1, "unit": "cucumber",
                   "calories": 30, "basis": "estimate"}],
        "ready": [{"food": "Cucumber", "amount": 1, "unit": "cucumber",
                   "calories": 30},
                  {"food": "Tomato", "amount": 1, "unit": "tomato",
                   "calories": 22}],
    })
    assert [i["food"] for i in out["items"]] == ["Cucumber", "Tomato"]


def test_the_stale_question_does_not_ride_along():
    out = FT._ask_becomes_log({"action": "ask", "points": [{"label": "x"}],
                               "items": [{"food": "Tomato", "calories": 22}]})
    assert out["action"] == "log"
    assert "points" not in out


def test_only_the_questioned_row_carries_the_assumption():
    out = FT._ask_becomes_log({
        "action": "ask",
        "items": [{"food": "Cucumber", "calories": 30},
                  {"food": "Tomato", "calories": 22}],
        "ambiguities": [{"item": "Cucumber", "field": "amount",
                         "assumed": "a whole one"}]})
    by_name = {i["food"]: i.get("_assumed") for i in out["items"]}
    assert by_name["Cucumber"] == [{"field": "amount", "text": "a whole one"}]
    assert by_name["Tomato"] is None
