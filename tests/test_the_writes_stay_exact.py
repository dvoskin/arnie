"""Three guarantees the write path owes, now that the writer is free-writing.

**The model does not choose the writes.** Legacy felt intelligent and dropped
tool calls because one model did both jobs — read the message and pick the
tools. The structured lane took the second job away, and this sprint gave the
first one's VOICE back. The line between them is that the interpreter's plan is
the write, and nothing the composer does can add to it, drop from it or reorder
it.

**A dashboard mutation is a ledger event.** `ledger_undo.build_plan` takes the
last event unconditionally, so a mutation that records none leaves "undo that"
pointing at whatever came before — a row the user never touched.

**A correction that cannot be priced says so.** The executor renames the row,
finds nothing that can cost the new identity, declines to write a zero, and
records that. Nothing read it, so "Fixed it to a double cheeseburger" shipped
over the single cheeseburger's 324 cal against a real 450, and the user had to
notice and supply the number.
"""
import inspect

import pytest

from core.food_response import (CARD_FACTS, FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, Reason, apply_policy,
                                build_prompt, fallback, validate)


# ── the plan is the write ─────────────────────────────────────────────────────
def test_execution_runs_the_interpreters_calls_and_only_those():
    """`result["tool_calls"]` on a structured turn is `_sft["tool_calls"]` —
    the interpreter's plan — and the composer runs after execution, on a
    snapshot. There is no path from composed text back to a tool call."""
    import core.conversation as C
    body = inspect.getsource(C._run_turn)
    assert '"tool_calls": _sft["tool_calls"]' in body, (
        "the executed batch must be the interpreter's plan verbatim")
    # And the composer is reached only after the executor has published.
    assert body.index("execute_tool_calls(") < body.index("compose_async(")


def test_the_composer_cannot_reach_a_tool():
    """It is called with tools disabled. A free-writing model that could call
    a tool is legacy again."""
    import core.food_response as FR
    assert "tools=False" in inspect.getsource(FR.compose_async)


# ── a dashboard mutation is a ledger event ────────────────────────────────────
def test_the_webhook_edit_and_delete_record_events():
    """`api/food_edit.py` recorded these for the iOS path and `api/app.py` did
    not, so the same row had two edit surfaces and only one was invertible.

    Asserted on the WRITE rather than on the handler's source. Both of these
    used to grep for `_record_food_event` / `_food_row_state` inside the
    handler; under B2 the event moved INTO `delete_food_entry` so it commits
    in the row's own transaction, and the greps went red for a change that
    made the property stronger. A source grep cannot tell those two apart —
    behaviour can, and the behavioural version below also covers the iOS and
    chat surfaces the grep never looked at.
    """
    import inspect as _i

    import api.app as A
    for fn in (A.api_edit_food, A.api_delete_food):
        src = _i.getsource(fn)
        assert "ledger_source=" in src, (
            f"{fn.__name__} does not ask its write to record history")


@pytest.mark.asyncio
async def test_a_delete_captures_the_row_before_it_dies(db, make_user):
    """A delete event without a body cannot be restored, and "bring it back"
    is the half of undo that needs one.

    The row is read inside `delete_food_entry`, while it still exists, and the
    event commits with the delete.
    """
    import json
    from datetime import date

    from sqlalchemy import select

    from db.models import DailyLog, FoodEntry, LedgerEvent
    from db.queries import delete_food_entry

    user = await make_user(telegram_id="del:capture")
    log = DailyLog(user_id=user.id, date=date.today())
    db.add(log)
    await db.flush()
    entry = FoodEntry(daily_log_id=log.id, parsed_food_name="Birria taco",
                      calories=180, protein=9, carbs=12, fats=10)
    db.add(entry)
    await db.commit()

    assert await delete_food_entry(db, entry.id, user.id,
                                   ledger_source="dashboard_edit")

    ev = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id,
                                  LedgerEvent.event_type == "deleted")
    )).scalars().first()
    assert ev is not None, "the delete left no event to restore from"
    payload = json.loads(ev.payload_json)
    assert payload["food_name"] == "Birria taco"
    assert payload["calories"] == 180
    assert payload["daily_log_id"] == log.id, (
        "without the day, a restore puts the food back on the wrong date")


# ── an unpriced correction discloses ──────────────────────────────────────────
def _unpriced_plan(**kw):
    base = dict(intent=FoodResponseIntent.CORRECT,
                committed_items=(FoodItemSummary(name="Double Cheeseburger"),),
                unpriced_corrections=("Double Cheeseburger",),
                card_will_render=True, facts_visible_in_card=CARD_FACTS)
    base.update(kw)
    return apply_policy(FoodResponsePlan(**base))


def test_an_unpriced_correction_may_ask_although_a_correction_normally_cannot():
    plain = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.CORRECT))
    assert not plain.allow_question
    assert _unpriced_plan().allow_question, (
        "the only source left for the number is the person who ate it")


def test_it_may_not_be_silent():
    assert validate("", _unpriced_plan()).reason == Reason.EMPTY_NOT_ALLOWED


def test_the_deterministic_floor_says_the_numbers_did_not_move():
    text = fallback(_unpriced_plan())
    assert "old calories" in text
    assert "?" in text, "it has to ask — nothing else can supply the number"


def test_the_brief_forbids_implying_an_update_or_guessing():
    prompt = build_prompt(_unpriced_plan())
    assert "THE NUMBERS COULD NOT FOLLOW" in prompt
    assert "do not guess one yourself" in prompt


def test_a_priced_correction_is_untouched():
    """The ordinary correction still carries the day exactly as it did."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CORRECT,
        committed_items=(FoodItemSummary(name="Birria Tacos"),),
        corrections=("1 taco is now 2 tacos",)))
    assert not plan.allow_question
    assert "old calories" not in fallback(plan)
