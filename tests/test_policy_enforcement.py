"""Only approved commands execute — asserted on the LIVE path (review item 2).

The staged-ambiguity architecture's central promise was that the policy engine
decides what may be written. In the live turn it did not.

`plan_turn` ran, and if it wanted to ASK the turn returned early with the
question. Everything else it decided was dropped: the tool calls below that
branch were built from the complete normalized operation list, and
`decision.approved_operations` was never consulted in selecting them. The
promise held only because a hold almost always arrives WITH a question, and the
question returns early. A no-question hold, an unsupported edge case, or any
future change to the clarification policy would have executed everything the
interpreter proposed.

`approved_operations` could not have closed it either: it filters
`data["_calls"]`, and the interpreter's JSON has no `_calls`. Only fixtures put
them there — which is exactly how the existing tests passed over the seam.

**So every test in this file drives `food_turn.run()` with a fake interpreter
and nothing else.** No `_calls` are injected anywhere. If the enforcement is
removed, these fail.
"""
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT


def _interpreter(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


def _names(out):
    return [c["input"]["food_name"] for c in (out or {}).get("tool_calls", [])]


def _hold(*held_texts):
    """A clarification decision that holds items WITHOUT asking about them.

    The shape the live path could not survive. It is rare rather than
    impossible — which is the point: a promise that holds by luck is not a
    promise, and this is the cheapest possible way to find out.
    """
    class _Item:
        def __init__(self, text, sid):
            self.original_text = text
            self.staged_item_id = sid

    class _Clarification:
        questions = ()
        assumptions = ()

        def __init__(self, held_ids):
            self.held_item_ids = tuple(held_ids)
            self.ready_item_ids = ()

    class _Decision:
        def __init__(self, texts):
            self.staged_items = tuple(
                _Item(t, f"s{i}") for i, t in enumerate(texts))
            self.clarification = _Clarification(
                [f"s{i}" for i, t in enumerate(texts) if t in held_texts])
            self.approved_operations = ()
            self.meal_group_id = "m1"

        @property
        def asks(self):
            return False

    return _Decision


@pytest.fixture
def _live(monkeypatch):
    """The pipeline decision, injected where `plan_turn` returns it."""
    def install(decision):
        import core.food_pipeline as FP
        monkeypatch.setattr(FP, "plan_turn", lambda *a, **k: decision)
        monkeypatch.setattr(FP, "pipeline_enabled", lambda: True)
    return install


LOG_PAYLOAD = {
    "action": "log",
    "items": [
        {"food": "grilled chicken", "amount": 6, "unit": "oz",
         "calories": 280, "protein": 52, "carbs": 0, "fats": 6},
        {"food": "white rice", "amount": 1, "unit": "cup",
         "calories": 205, "protein": 4, "carbs": 45, "fats": 0},
    ],
}


@pytest.mark.asyncio
async def test_a_held_item_does_not_execute(monkeypatch, _live):
    """The whole promise, on the live path, with no `_calls` injected."""
    monkeypatch.setattr(FT, "chat", _interpreter(LOG_PAYLOAD))
    _live(_hold("white rice")(["grilled chicken", "white rice"]))
    out = await FT.run("6 oz chicken and a cup of rice", SimpleNamespace())
    assert _names(out) == ["grilled chicken"]


@pytest.mark.asyncio
async def test_the_items_the_policy_cleared_still_execute(monkeypatch, _live):
    """A veto that holds everything is not enforcement, it is an outage."""
    monkeypatch.setattr(FT, "chat", _interpreter(LOG_PAYLOAD))
    _live(_hold()(["grilled chicken", "white rice"]))
    out = await FT.run("6 oz chicken and a cup of rice", SimpleNamespace())
    assert _names(out) == ["grilled chicken", "white rice"]


@pytest.mark.asyncio
async def test_holding_every_item_produces_no_turn_rather_than_a_partial_one(
        monkeypatch, _live):
    monkeypatch.setattr(FT, "chat", _interpreter(LOG_PAYLOAD))
    _live(_hold("grilled chicken", "white rice")(
        ["grilled chicken", "white rice"]))
    out = await FT.run("6 oz chicken and a cup of rice", SimpleNamespace())
    assert out is None


@pytest.mark.asyncio
async def test_a_delete_is_not_vetoed_by_a_set_it_was_never_in(
        monkeypatch, _live):
    """Updates and deletes are the user's own explicit corrections to rows
    already on the board. They were never staged and the policy never reasoned
    about them, so vetoing them for being absent from `ready_item_ids` would
    silently swallow "remove the fries"."""
    monkeypatch.setattr(FT, "chat", _interpreter({
        "action": "delete",
        "deletes": [{"entry_id": 7, "food": "fries"}]}))
    _live(_hold("fries")(["fries"]))
    out = await FT.run("remove the fries", SimpleNamespace(),
                       board=[{"id": 7, "food": "fries", "qty": "1 serving",
                               "cal": 300}])
    assert out is not None and out["action"] == "delete"


@pytest.mark.asyncio
async def test_no_decision_at_all_leaves_the_turn_untouched(monkeypatch):
    """The pipeline is fail-safe: an exception or a disabled switch returns
    None, and the turn must proceed exactly as it did before."""
    import core.food_pipeline as FP
    monkeypatch.setattr(FT, "chat", _interpreter(LOG_PAYLOAD))
    monkeypatch.setattr(FP, "pipeline_enabled", lambda: False)
    out = await FT.run("6 oz chicken and a cup of rice", SimpleNamespace())
    assert _names(out) == ["grilled chicken", "white rice"]
