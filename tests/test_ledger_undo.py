"""Deterministic undo/restore on the event ledger (FOOD_LEDGER_V2 Phase 2):
"undo" / "bring back the fries" invert the last event with zero model calls.

Covers: shape detection, created→delete inversion, deleted→restore inversion
(executed through the real restore executor branch: row recreated, totals
recomputed, restore event appended), updated→before rollback, restore-by-name
matching, the freshness bound, and the refuse-on-uninvertible rule."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import core.ledger_undo as LU
from db.queries import record_ledger_event, get_ledger_events


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


# ── detection ─────────────────────────────────────────────────────────────────
def test_detect_shapes():
    assert LU.detect("undo") == {"kind": "undo"}
    assert LU.detect("Undo that") == {"kind": "undo"}
    assert LU.detect("undo the last one") == {"kind": "undo"}
    assert LU.detect("bring back the fries") == {"kind": "restore",
                                                 "name": "fries"}
    assert LU.detect("restore the caesar salad")["name"] == "caesar salad"
    assert LU.detect("put it back") == {"kind": "restore", "name": None}
    # not undo shapes
    assert LU.detect("undo my whole life") is None
    assert LU.detect("had a taco") is None
    assert LU.detect("remove the fries") is None
    assert LU.detect("") is None


# ── inversions ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_undo_after_create_deletes(db, make_user):
    user = await make_user()
    log, fe = await _seed_day(db, user)
    await record_ledger_event(db, user.id, "created", domain="food",
                              entry_id=fe.id, daily_log_id=log.id,
                              payload={"food_name": "Birria taco",
                                       "calories": 180})
    plan = await LU.build_plan(db, user, "undo")
    assert plan is not None and plan["kinds"] == ["delete"]
    tc = plan["tool_calls"][0]
    assert tc["name"] == "delete_food_entry"
    assert tc["input"]["entry_id"] == fe.id
    assert "Birria taco" in plan["say"]


@pytest.mark.asyncio
async def test_undo_after_delete_restores_via_executor(db, make_user):
    """Full loop: delete through the real branch (event captured), 'undo'
    builds a restore plan, the restore branch recreates the row and appends
    its own created event."""
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)
    out = await TE._dispatch("delete_food_entry", {"entry_id": fe.id},
                             user, log, db, "text")
    assert "Removed" in out
    plan = await LU.build_plan(db, user, "undo")
    assert plan is not None and plan["kinds"] == ["log"]
    tc = plan["tool_calls"][0]
    assert tc["name"] == "restore_food_entry"
    out2 = await TE._dispatch(tc["name"], tc["input"], user, log, db, "text")
    assert "Restored Birria taco" in out2
    from db.models import FoodEntry
    from sqlalchemy import select
    rows = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all()
    assert len(rows) == 1 and rows[0].parsed_food_name == "Birria taco"
    assert rows[0].calories == 180.0
    events = await get_ledger_events(db, user.id, domain="food")
    assert [e.event_type for e in events[:2]] == ["created", "deleted"]
    assert events[0].source == LU.UNDO_SOURCE


@pytest.mark.asyncio
async def test_undo_after_update_rolls_back(db, make_user):
    """The updated event's captured `before` becomes the rollback write —
    through the real update branch so the capture itself is exercised."""
    import handlers.tool_executor as TE
    user = await make_user()
    log, fe = await _seed_day(db, user)
    out = await TE._dispatch(
        "update_food_entry",
        {"entry_id": fe.id, "quantity": "2 tacos", "calories": 360},
        user, log, db, "text")
    assert "Updated" in out
    plan = await LU.build_plan(db, user, "undo that")
    assert plan is not None and plan["kinds"] == ["update"]
    inp = plan["tool_calls"][0]["input"]
    assert inp["entry_id"] == fe.id
    assert inp["quantity"] == "1 taco" and inp["calories"] == 180.0


@pytest.mark.asyncio
async def test_restore_by_name_matches(db, make_user):
    user = await make_user()
    await record_ledger_event(db, user.id, "deleted", domain="food",
                              entry_id=11, payload={"food_name": "Truffle fries",
                                                    "calories": 190})
    await record_ledger_event(db, user.id, "deleted", domain="food",
                              entry_id=12, payload={"food_name": "Caesar salad",
                                                    "calories": 300})
    plan = await LU.build_plan(db, user, "bring back the fries")
    assert plan is not None
    assert plan["tool_calls"][0]["input"]["food_name"] == "Truffle fries"


# ── bounds and refusals ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stale_events_are_not_undone(db, make_user):
    user = await make_user()
    await record_ledger_event(db, user.id, "created", domain="food",
                              entry_id=5, payload={"food_name": "Old thing"})
    from db.models import LedgerEvent
    from sqlalchemy import select
    row = (await db.execute(select(LedgerEvent))).scalars().first()
    row.created_at = datetime.utcnow() - timedelta(hours=20)
    await db.commit()
    assert await LU.build_plan(db, user, "undo") is None


@pytest.mark.asyncio
async def test_uninvertible_last_event_refuses_not_skips(db, make_user):
    """Water created has no delete branch yet — 'undo' right after it must
    refuse (legacy brain handles), never skip past it to undo the wrong
    thing."""
    user = await make_user()
    await record_ledger_event(db, user.id, "created", domain="food",
                              entry_id=7, payload={"food_name": "Eggs"})
    await record_ledger_event(db, user.id, "created", domain="water",
                              payload={"amount_ml": 500})
    assert await LU.build_plan(db, user, "undo") is None


@pytest.mark.asyncio
async def test_no_events_no_plan(db, make_user):
    user = await make_user()
    assert await LU.build_plan(db, user, "undo") is None
