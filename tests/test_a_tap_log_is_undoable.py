"""Audit O-1. "Undo that" must undo the thing that just happened.

`add_food_entry` writes the row; the `created` ledger event is a separate call,
and only the chat lane made it. `api/quick_log.py` (the iOS Today "+ Add"
sheet) and `api/app.py` (the dashboard) wrote food and exercise rows and
recorded nothing.

`ledger_undo.build_plan` takes the last event UNCONDITIONALLY, so:

    tap-log a banana  ->  "undo that"  ->  removes the previous CHAT-logged row

A row the user never mentioned, was not looking at, and got no warning about.
This is the only defect in the nutrition-lane audit that destroys user data,
and it is reachable from the primary iOS surface.
"""
from datetime import datetime

import pytest

from db.queries import (add_exercise_entry, add_food_entry, get_ledger_events,
                        record_created_from_row, record_ledger_event)


async def _day(db, user):
    from db.models import DailyLog
    log = DailyLog(user_id=user.id, date=datetime.utcnow().date(),
                   total_calories=0, total_protein=0)
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


@pytest.mark.asyncio
async def test_undo_after_a_tap_log_targets_the_tapped_row(db, make_user):
    """The sequence from the audit, end to end."""
    from core.ledger_undo import build_plan
    user = await make_user()
    log = await _day(db, user)

    # Yesterday's conversation: a row logged through chat, with its event.
    chat_entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Chicken shawarma",
        quantity="4 oz", calories=320, protein=34, carbs=6, fats=18)
    await record_ledger_event(
        db, user.id, "created", domain="food", entry_id=chat_entry.id,
        daily_log_id=log.id, payload={"food_name": "Chicken shawarma"},
        source="structured_food:v1")

    # ...then a tap on the Today sheet.
    tapped = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Banana", quantity="1",
        calories=105, protein=1, carbs=27, fats=0)
    await record_created_from_row(db, user.id, tapped, "food", log.id,
                                  source="quick_log:ios")

    plan = await build_plan(db, user, "undo that")
    assert plan is not None, "the tap-log left nothing to undo"
    target = plan["tool_calls"][0]["input"]
    assert target["entry_id"] == tapped.id
    assert target["entry_id"] != chat_entry.id, \
        "undo inverted the previous chat-logged row"
    assert "banana" in plan["say"].lower()


@pytest.mark.asyncio
async def test_the_event_is_written_from_the_committed_row(db, make_user):
    """Same reasoning as 2a4c839: the row is what the undo will have to
    invert, so anything the write normalised or defaulted belongs in the
    record of it — not the request body as it arrived."""
    import json
    user = await make_user()
    log = await _day(db, user)
    entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Royo Everything Bagel",
        quantity="1 bagel", calories=210, protein=20, carbs=24, fats=4,
        meal_type="breakfast")
    await record_created_from_row(db, user.id, entry, "food", log.id,
                                  source="quick_log:ios")

    events = await get_ledger_events(db, user.id, domain="food")
    payload = json.loads(events[0].payload_json)
    assert payload["food_name"] == entry.parsed_food_name
    assert payload["calories"] == entry.calories
    assert payload["meal_type"] == "breakfast"
    assert events[0].entry_id == entry.id
    assert events[0].source == "quick_log:ios"


@pytest.mark.asyncio
async def test_a_tap_logged_set_is_undoable_too(db, make_user):
    """`_invert` handles an exercise `created` exactly as it handles a food
    one, and the same two endpoints write exercise rows the same way. Fixing
    only the food half would leave the identical data-loss path open."""
    from core.ledger_undo import build_plan
    user = await make_user()
    log = await _day(db, user)
    await record_ledger_event(
        db, user.id, "created", domain="food", entry_id=4321,
        daily_log_id=log.id, payload={"food_name": "Oatmeal"})
    entry = await add_exercise_entry(
        db, daily_log_id=log.id, exercise_name="Bench press", sets=3,
        reps="5,5,5", weight=100.0)
    await record_created_from_row(db, user.id, entry, "exercise", log.id,
                                  source="quick_log:ios")

    plan = await build_plan(db, user, "undo that")
    assert plan is not None
    call = plan["tool_calls"][0]
    assert call["name"] == "delete_exercise_entry"
    assert call["input"]["entry_id"] == entry.id


@pytest.mark.asyncio
async def test_a_failed_event_never_breaks_the_write(db, make_user, monkeypatch):
    """Every other ledger call site is best-effort for the same reason: the
    history describes the write and must not be able to undo it."""
    import db.queries as Q
    user = await make_user()
    log = await _day(db, user)
    entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Toast", calories=90,
        protein=3, carbs=17, fats=1)

    async def _broken(*a, **k):
        raise RuntimeError("ledger table locked")

    monkeypatch.setattr(Q, "record_ledger_event", _broken)
    assert await Q.record_created_from_row(
        db, user.id, entry, "food", log.id, source="quick_log:ios") is None


def test_both_tap_log_surfaces_record_their_writes():
    """The helper is worth nothing if a call site is missed — and being missed
    is exactly what happened to these four.

    Updated for the one-writer consolidation (master audit 2026-07-30):
    exercise creations are recorded by `add_exercise_entry` itself — the
    tap-log endpoints pass `ledger_source` instead of writing a second event
    (which is what they had been doing: every tap-logged set produced a
    duplicate operation). FOOD still records at the call site, because
    `add_food_entry` has no internal recorder.

    A source count is a weak assertion (the B.0 lesson); the behaviour —
    exactly one invertible event per creation — is owned by
    `test_one_write_one_ledger_event.py`. This survives only as a cheap
    call-site census so a NEW endpoint that forgets both mechanisms still
    trips something.
    """
    import inspect
    import api.app as APP
    import api.quick_log as QL
    for module in (QL, APP):
        source = inspect.getsource(module)
        assert source.count("record_created_from_row(db, user.id, entry") == 1, \
            f"{module.__name__}: food tap-log must record exactly once"
        assert source.count("ledger_source=") == 1, \
            f"{module.__name__}: exercise tap-log must pass its provenance " \
            f"through add_exercise_entry, not record a second event"
