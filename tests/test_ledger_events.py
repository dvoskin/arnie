"""Ledger durability (FOOD_LEDGER_V2 Phase 2): append-only event history for
every logging domain (food / exercise / weight / water) and the durable
exactly-once claim behind structured commits.

Covers: event recording + retrieval across domains, delete events capturing
the full restorable payload through the real executor branch, update events
through the real executor branch, and claim_processed_turn's first/duplicate/
expired-reclaim semantics."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from db.queries import (record_ledger_event, get_ledger_events,
                        claim_processed_turn)


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
    return log, fe


# ── event history ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_events_roundtrip_across_domains(db, make_user):
    user = await make_user()
    await record_ledger_event(db, user.id, "created", domain="food",
                              entry_id=1, payload={"food_name": "Eggs"},
                              source="structured_food:test")
    await record_ledger_event(db, user.id, "created", domain="exercise",
                              entry_id=9, payload={"exercise_name": "Bench"})
    await record_ledger_event(db, user.id, "created", domain="weight",
                              payload={"weight_kg": 86.2})
    await record_ledger_event(db, user.id, "created", domain="water",
                              payload={"amount_ml": 500})
    all_events = await get_ledger_events(db, user.id)
    assert {e.domain for e in all_events} == {"food", "exercise", "weight", "water"}
    food_only = await get_ledger_events(db, user.id, domain="food")
    assert len(food_only) == 1
    assert json.loads(food_only[0].payload_json)["food_name"] == "Eggs"
    assert food_only[0].source == "structured_food:test"


@pytest.mark.asyncio
async def test_delete_records_restorable_payload(db, make_user):
    """The real executor delete branch: the deleted event carries the full
    entry state, and it survives the row's deletion — that is what makes
    'bring it back' possible."""
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)
    out = await TE._dispatch(
        "delete_food_entry",
        {"entry_id": fe.id, "source": "structured_food:test"},
        user, log, db, "text")
    assert "Removed" in out
    events = await get_ledger_events(db, user.id, domain="food",
                                     entry_id=fe.id)
    deleted = [e for e in events if e.event_type == "deleted"]
    assert deleted, "delete must append a deleted event"
    payload = json.loads(deleted[0].payload_json)
    assert payload["food_name"] == "Birria taco"
    assert payload["calories"] == 180.0
    assert deleted[0].source == "structured_food:test"
    # And the entry itself is gone while its history remains.
    from db.models import FoodEntry
    assert await db.get(FoodEntry, fe.id) is None


@pytest.mark.asyncio
async def test_update_records_changes_event(db, make_user):
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)
    out = await TE._dispatch(
        "update_food_entry",
        {"entry_id": fe.id, "quantity": "2 tacos", "calories": 360,
         "expected_calories": 180.0, "food_hint": "Birria taco",
         "source": "structured_food:test"},
        user, log, db, "text")
    assert "Updated" in out
    events = await get_ledger_events(db, user.id, domain="food",
                                     entry_id=fe.id)
    updated = [e for e in events if e.event_type == "updated"]
    assert updated
    changes = json.loads(updated[0].payload_json)["changes"]
    assert changes["calories"] == 360
    assert "expected_calories" not in changes, "carrier fields never persist as changes"


# ── durable exactly-once ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_claim_is_exactly_once_within_window(db, make_user):
    user = await make_user()
    assert await claim_processed_turn(db, user.id, "k1", "Banana") is True
    assert await claim_processed_turn(db, user.id, "k1", "Banana") is False
    # A different key is a different turn.
    assert await claim_processed_turn(db, user.id, "k2", "Coke") is True


@pytest.mark.asyncio
async def test_claim_reopens_after_window(db, make_user):
    """The same 'had a banana' a day later is a genuinely new turn — the
    claim is time-scoped, not forever."""
    user = await make_user()
    assert await claim_processed_turn(db, user.id, "k1", "Banana") is True
    from db.models import ProcessedTurn
    from sqlalchemy import select
    row = (await db.execute(select(ProcessedTurn).where(
        ProcessedTurn.user_id == user.id))).scalars().first()
    row.created_at = datetime.utcnow() - timedelta(hours=25)
    await db.commit()
    assert await claim_processed_turn(db, user.id, "k1", "Banana") is True


def test_card_carries_event_id_undo_token():
    """P0 card/ledger unification (2026-07-24): the macro_card surfaces the
    ledger event id behind the write — the backend contract for one-tap Undo.
    Optional on the wire; a write with no event stays cardable."""
    from core.conversation import _logged_entry_card
    with_ev = _logged_entry_card("log_food", {
        "_entry_id": 42, "_event_id": 900, "food_name": "Banana",
        "quantity": "1 banana", "calories": 105})
    assert with_ev["payload"]["event_id"] == 900
    without = _logged_entry_card("log_food", {
        "_entry_id": 42, "food_name": "Banana", "calories": 105})
    assert "event_id" not in without["payload"]


def test_restored_entry_gets_a_card():
    from core.conversation import _logged_entry_card
    card = _logged_entry_card("restore_food_entry", {
        "_entry_id": 43, "_event_id": 901, "food_name": "Truffle fries",
        "quantity": "6 fries", "calories": 190})
    assert card["type"] == "macro_card"
    assert card["payload"]["name"] == "Truffle fries"
    assert card["payload"]["event_id"] == 901
    # no committed row → no card, same as log_food
    assert _logged_entry_card("restore_food_entry", {"food_name": "X"}) is None
