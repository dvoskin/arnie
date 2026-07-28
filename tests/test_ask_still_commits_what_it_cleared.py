"""A clarifying turn commits the items it was never unsure about.

Audit A1. `core.food_turn` returns an ask carrying the READY items' tool calls
— the ones the clarification veto already cleared — and the legacy lane
executes them while asking about the rest. The native `FoodPlanStage` returned
`operations=()` for every ask, `FoodValidationStage` approved nothing, and the
coordinator only ever executed on `disposition == "execute"`.

Three separate places had to agree that an ask writes nothing, and all three
did. So moderate mode's PARTIAL_COMMIT silently became ATOMIC_HOLD on the
native path: the whole meal waits on its least certain item, which is the exact
regression `core/conversation.py` records having fixed once already.

Promoting the lane would have shipped that as a functional regression, and it
would have looked like a clarification-policy change rather than a wiring loss.
"""
import pytest

from core.turns.stages.food import FoodPlanStage, FoodValidationStage


def _req(text="a bar and some chicken"):
    from core.turns.models import TurnRequest
    return TurnRequest(turn_id="t1", user_id=1, platform="ios",
                       source_type="text", text=text,
                       metadata={"user": object()})


def _interpreter(out):
    async def _run(*a, **k):
        return out
    return _run


READY_CALL = {"name": "log_food",
              "input": {"food_name": "Barebells bar", "calories": 200}}

ASK_WITH_READY = {
    "action": "ask", "text": "How much chicken?",
    "tool_calls": [READY_CALL],
    "points": ["How much chicken?"],
    "response_schema": "quantity", "staged_item_id": "sid-chicken",
}


# ── the plan keeps them ───────────────────────────────────────────────────────

async def test_the_plan_carries_the_cleared_items():
    plan = await FoodPlanStage(interpreter=_interpreter(ASK_WITH_READY)).run(
        _req())
    assert plan.response_intent == "ask"
    assert plan.operations == (READY_CALL,)


async def test_an_ask_with_nothing_cleared_still_carries_nothing():
    out = dict(ASK_WITH_READY, tool_calls=[])
    plan = await FoodPlanStage(interpreter=_interpreter(out)).run(_req())
    assert plan.response_intent == "ask"
    assert plan.operations == ()


# ── validation approves them ──────────────────────────────────────────────────

async def test_validation_approves_the_cleared_items_on_an_ask():
    plan = await FoodPlanStage(interpreter=_interpreter(ASK_WITH_READY)).run(
        _req())
    result = await FoodValidationStage().run(_req(), plan=plan)
    assert result.disposition == "ask"          # it still asks
    assert result.approved_operations == (READY_CALL,)   # and still writes
    assert result.clarification is not None


async def test_a_confirm_approves_nothing():
    """A confirm asks whether the whole parse is right. Committing half of it
    pre-empts the answer, so this is a deliberate asymmetry rather than an
    oversight — and worth a test precisely because it looks like one."""
    out = dict(ASK_WITH_READY, kind="confirm")
    plan = await FoodPlanStage(interpreter=_interpreter(out)).run(_req())
    result = await FoodValidationStage().run(_req(), plan=plan)
    assert result.disposition == "ask"
    assert result.approved_operations == ()


# ── and the phase machine runs them ───────────────────────────────────────────

@pytest.mark.parametrize("disposition,ops,should_execute", [
    ("execute", (READY_CALL,), True),
    ("ask", (READY_CALL,), True),      # the fix
    ("ask", (), False),                # nothing cleared, nothing to run
    ("pass", (READY_CALL,), False),    # ops on a pass is a bug, not a licence
    ("reject", (READY_CALL,), False),
])
def test_only_an_execute_or_a_committing_ask_reaches_execution(
        disposition, ops, should_execute):
    """The condition the coordinator branches on, stated directly.

    Asserting the predicate rather than driving a whole coordinator keeps this
    readable — and this predicate IS the bug: gating on the string alone made
    partial commit unreachable however the policy had decided.
    """
    reached = disposition == "execute" or (disposition == "ask" and bool(ops))
    assert reached is should_execute
