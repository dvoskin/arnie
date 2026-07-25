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


# ── the reasoning receipt reads the typed view (P0.3c) ────────────────────────
def test_receipt_reports_per_call_truth_from_typed_view():
    """The name-keyed results dict collapses a multi-item batch to the LAST
    result — a blocked item would read as 'Logged'. The typed view carries
    per-call truth, so the receipt reports what each call actually did."""
    from core.reasoning import build_reasoning
    inp_ok = {"food_name": "Coke", "calories": 140}
    inp_dup = {"food_name": "Banana", "calories": 105}
    calls = [{"name": "log_food", "input": inp_ok},
             {"name": "log_food", "input": inp_dup}]
    execution = ER.ExecutionResult(calls=(
        ER.CallResult(name="log_food", raw_input=inp_ok, status="committed",
                      result_text="Logged Coke: 140 cal."),
        ER.CallResult(name="log_food", raw_input=inp_dup, status="blocked",
                      result_text="Already on the board: Banana"),
    ))
    # The shared dict says everything logged (last write wins) — the typed
    # view must override that for the blocked item.
    rec = build_reasoning(calls, {"log_food": "Logged Coke: 140 cal."},
                          execution=execution)
    blob = str(rec)
    assert "Duplicate check" in blob and "Banana" in blob
    # Without the typed view, the collapsed dict misreports it as logged.
    rec_legacy = build_reasoning(calls, {"log_food": "Logged Coke: 140 cal."})
    assert "Duplicate check" not in str(rec_legacy)


def test_receipt_sourcing_rides_the_typed_call():
    from core.reasoning import build_reasoning
    inp = {"food_name": "Fage 0% yogurt", "calories": 120}
    execution = ER.ExecutionResult(calls=(
        ER.CallResult(name="log_food", raw_input=inp, status="committed",
                      result_text="Logged Fage: 120 cal.",
                      sourcing={"source": "usda", "calories": 120}),
    ))
    rec = build_reasoning([{"name": "log_food", "input": inp}], {},
                          execution=execution)
    assert "USDA" in str(rec)
    # And the input itself was never mutated by the receipt build.
    assert "_sourcing" not in inp


# ── native construction: the command is never the carrier (P0.3d) ─────────────
@pytest.mark.asyncio
async def test_execution_state_rides_the_side_channel_not_the_command(db, make_user):
    """The executor records what HAPPENED in a per-call context; the typed view
    is built from THAT, never by scraping the command."""
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)
    # log_food reads user.preferences for the receipt — load it eagerly so the
    # async lazy-load never fires outside a greenlet in this harness.
    await db.refresh(user, attribute_names=["preferences"])
    calls = [{"name": "log_food",
              "input": {"food_name": "Banana", "quantity": "1 banana",
                        "calories": 105}}]
    await TE.execute_tool_calls(calls, user, log, db, source_type="text")
    cr = ER.LAST_EXECUTION.get().calls[0]
    assert cr.committed
    assert cr.entry_id is not None          # committed row id, from the context
    assert cr.event_id is not None          # ledger event id (undo token)
    assert isinstance(cr.receipt, dict)     # decision receipt


def test_native_view_needs_no_stash_keys_on_the_command():
    """Proof the command is no longer the carrier: with every underscore key
    stripped from the input, the context alone still yields the full view."""
    from core.execution_result import from_call_contexts
    clean_input = {"food_name": "Banana", "quantity": "1 banana", "calories": 105}
    ctx = {"entry_id": 42, "event_id": 900, "receipt": {"day_calories": 1200},
           "sourcing": {"source": "usda"}, "result": "Logged Banana: 105 cal."}
    ex = from_call_contexts([{"name": "log_food", "input": clean_input}], [ctx])
    cr = ex.calls[0]
    assert cr.committed and cr.entry_id == 42 and cr.event_id == 900
    assert cr.receipt["day_calories"] == 1200 and cr.sourcing["source"] == "usda"
    assert not any(k.startswith("_") for k in clean_input)


@pytest.mark.asyncio
async def test_batch_contexts_stay_per_call(db, make_user):
    """Two calls in one batch get independent contexts — the second can never
    inherit the first's committed ids."""
    import handlers.tool_executor as TE
    from core.execution_result import LAST_EXECUTION
    user = await make_user()
    log, fe = await _seed_day(db, user)
    await db.refresh(user, attribute_names=["preferences"])
    calls = [
        {"name": "log_food", "input": {"food_name": "Coke", "quantity": "12 oz",
                                       "calories": 140}},
        {"name": "log_food", "input": {"food_name": "Chips", "quantity": "1 bag",
                                       "calories": 150}},
    ]
    await TE.execute_tool_calls(calls, user, log, db, source_type="text")
    ex = LAST_EXECUTION.get()
    assert ex is not None and len(ex.calls) == 2
    ids = [c.entry_id for c in ex.calls]
    assert all(i is not None for i in ids), ids
    assert ids[0] != ids[1], "each call must carry its OWN committed row id"
