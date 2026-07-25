"""Typed execution results (P0.3a): one per-call view of what a tool batch
actually did — published by the real executor, scraped as a fallback for
mocked ones. Downstream (narration filters, cards) consumes this instead of
reading executor-stashed underscore keys off tool inputs."""
from datetime import datetime
from types import SimpleNamespace

import pytest

import core.execution_result as ER


async def _seed_day(db, user, cal=180.0):
    from db.models import DailyLog, FoodEntry
    log = DailyLog(user_id=user.id, date=datetime.utcnow().date(),
                   total_calories=cal, total_protein=12)
    db.add(log)
    await db.flush()
    fe = FoodEntry(daily_log_id=log.id, parsed_food_name="Birria taco",
                   quantity="1 taco", calories=cal, protein=12.0,
                   carbs=14.0, fats=9.0, meal_type="lunch")
    db.add(fe)
    await db.commit()
    await db.refresh(fe)
    # execute_tool_calls snapshots the log's relationships up front — load
    # them eagerly here so the async lazy-load never fires outside a greenlet.
    await db.refresh(log, attribute_names=["food_entries", "exercise_entries"])
    return log, fe


# ── the scraper fallback ──────────────────────────────────────────────────────
def test_from_tool_calls_reads_status_and_stashes():
    calls = [
        {"name": "log_food",
         "input": {"food_name": "Coke", "calories": 140, "_entry_id": 9,
                   "_event_id": 900, "_result": "Logged Coke: 140 cal."}},
        {"name": "update_food_entry",
         "input": {"entry_id": 1, "calories": 360, "food_hint": "Birria taco",
                   "_result": "STALE BOARD: entry #1 is now 500 cal."}},
    ]
    ex = ER.from_tool_calls(calls, {"log_food": "Logged Coke: 140 cal."})
    assert [c.status for c in ex.calls] == ["committed", "blocked"]
    assert ex.calls[0].entry_id == 9 and ex.calls[0].event_id == 900
    assert ex.ok_tool_calls() == [{"name": "log_food",
                                   "input": calls[0]["input"]}]
    assert ex.failed_names() == ["Birria taco"]


def test_unstamped_calls_count_committed():
    """Mocked executors don't stamp _result — the view fails open, matching
    the narration filters' existing semantics."""
    ex = ER.from_tool_calls([{"name": "log_food",
                              "input": {"food_name": "Banana"}}])
    assert ex.calls[0].committed
    assert ex.failed_names() == []


# ── the real executor publishes it ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_executor_publishes_typed_view(db, make_user):
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)
    calls = [{"name": "delete_food_entry",
              "input": {"entry_id": fe.id, "food_hint": "Birria taco",
                        "source": "structured_food:test"}}]
    results = await TE.execute_tool_calls(calls, user, log, db,
                                          source_type="text")
    ex = ER.LAST_EXECUTION.get()
    assert ex is not None and len(ex.calls) == 1
    cr = ex.calls[0]
    assert cr.name == "delete_food_entry" and cr.committed
    assert cr.result_text.startswith("Removed")
    assert results["delete_food_entry"].startswith("Removed")


@pytest.mark.asyncio
async def test_executor_view_marks_stale_update_blocked(db, make_user):
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)          # row is 180 cal
    calls = [{"name": "update_food_entry",
              "input": {"entry_id": fe.id, "quantity": "2 tacos",
                        "calories": 360, "expected_calories": 500.0,
                        "food_hint": "Birria taco"}}]
    await TE.execute_tool_calls(calls, user, log, db, source_type="text")
    ex = ER.LAST_EXECUTION.get()
    assert ex is not None
    assert ex.calls[0].status == "blocked"
    assert ex.failed_names() == ["Birria taco"]
    assert ex.ok_tool_calls() == []


# ── cards render from the typed view (P0.3b) ──────────────────────────────────
def test_card_prefers_typed_call_over_stashed_keys():
    """The card mirrors what the executor COMMITTED: ids come from the typed
    CallResult, not from whatever was stashed on the model's input."""
    from core.conversation import _logged_entry_card
    inp = {"food_name": "Banana", "quantity": "1 banana", "calories": 105,
           "_entry_id": 11, "_event_id": 800}     # stale/legacy stash
    cr = ER.CallResult(name="log_food", raw_input=inp, status="committed",
                       entry_id=42, event_id=900,
                       receipt={"day_calories": 1200})
    card = _logged_entry_card("log_food", inp, call=cr)
    assert card["payload"]["entry_id"] == 42     # typed wins
    assert card["payload"]["event_id"] == 900
    assert card["payload"]["day_calories"] == 1200   # receipt from the call
    # Legacy path (no typed call) still reads the stash — unit tests and any
    # caller that hasn't converted yet keep working.
    legacy = _logged_entry_card("log_food", inp)
    assert legacy["payload"]["entry_id"] == 11


def test_uncommitted_call_still_produces_no_card():
    """No committed row → no card, whichever path built it."""
    from core.conversation import _logged_entry_card
    inp = {"food_name": "Banana", "calories": 105}
    cr = ER.CallResult(name="log_food", raw_input=inp, status="blocked")
    assert _logged_entry_card("log_food", inp, call=cr) is None
