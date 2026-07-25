"""REST edits join the ledger (P0.6, architecture review 2026-07-24).

Direct API mutations (the iOS Daily-tab inline editor) used to write straight
through the query helpers — no event, no history, invisible to undo. A
dashboard edit is a ledger mutation like any other: same events, same
restorable payloads, same cross-surface reach.
"""
from datetime import datetime

import pytest

from db.queries import get_ledger_events


async def _seed(db, user, cal=180.0):
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


@pytest.mark.asyncio
async def test_rest_delete_leaves_a_restorable_event(db, make_user, monkeypatch):
    """The deleted event carries the full entry — so 'bring back the taco' in
    chat can restore a row the user removed from the iOS dashboard."""
    import api.food_edit as FE
    user = await make_user()
    log, fe = await _seed(db, user)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(FE, "AsyncSessionLocal", _session)
    async def _resolve(_db, _identity):
        return user
    monkeypatch.setattr(FE, "resolve_user", _resolve)
    async def _noop_log(*a, **k):
        return None
    monkeypatch.setattr(FE, "log_conversation", _noop_log)

    out = await FE.delete_food(fe.id, identity="im:+1555")
    assert out["status"] == "ok"

    events = await get_ledger_events(db, user.id, domain="food")
    deleted = [e for e in events if e.event_type == "deleted"]
    assert deleted, "a REST delete must leave a ledger event"
    import json
    payload = json.loads(deleted[0].payload_json)
    assert payload["food_name"] == "Birria taco"
    assert payload["calories"] == 180
    assert payload["daily_log_id"] == log.id      # restorable into its own day
    assert deleted[0].source == "ios_edit"
    assert deleted[0].turn_id and "ios_edit" in deleted[0].turn_id


@pytest.mark.asyncio
async def test_rest_update_event_is_invertible(db, make_user, monkeypatch):
    """The updated event captures the BEFORE state, so an 'undo' in chat can
    roll back an edit made on the dashboard."""
    import api.food_edit as FE
    user = await make_user()
    log, fe = await _seed(db, user)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(FE, "AsyncSessionLocal", _session)
    async def _resolve(_db, _identity):
        return user
    monkeypatch.setattr(FE, "resolve_user", _resolve)
    async def _noop_log(*a, **k):
        return None
    monkeypatch.setattr(FE, "log_conversation", _noop_log)

    body = FE.FoodUpdateBody(calories=360, protein=30)
    out = await FE.update_food(fe.id, body, identity="im:+1555")
    assert out["status"] == "ok"

    events = await get_ledger_events(db, user.id, domain="food")
    updated = [e for e in events if e.event_type == "updated"]
    assert updated, "a REST update must leave a ledger event"
    import json
    payload = json.loads(updated[0].payload_json)
    assert payload["before"]["calories"] == 180      # invertible
    assert payload["changes"]["calories"] == 360
    assert updated[0].source == "ios_edit"


@pytest.mark.asyncio
async def test_chat_undo_can_invert_a_dashboard_delete(db, make_user, monkeypatch):
    """The cross-surface property this buys: delete on iOS, 'undo' in chat."""
    import api.food_edit as FE
    import core.ledger_undo as LU
    user = await make_user()
    log, fe = await _seed(db, user)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(FE, "AsyncSessionLocal", _session)
    async def _resolve(_db, _identity):
        return user
    monkeypatch.setattr(FE, "resolve_user", _resolve)
    async def _noop_log(*a, **k):
        return None
    monkeypatch.setattr(FE, "log_conversation", _noop_log)

    await FE.delete_food(fe.id, identity="im:+1555")
    plan = await LU.build_plan(db, user, "undo")
    assert plan is not None and plan["kinds"] == ["log"]
    tc = plan["tool_calls"][0]
    assert tc["name"] == "restore_food_entry"
    assert tc["input"]["food_name"] == "Birria taco"
