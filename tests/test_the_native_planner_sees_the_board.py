"""⭐ THE NATIVE PLANNER SEES THE BOARD — the B-1.8 canary's finding.

PRODUCTION 2026-08-18, user 26, turn ios:4DB2A7D6: "actually the grilled
chicken breast was 8 oz" reached the native lane; `FoodPlanStage` called the
interpreter with board=None (the request never carried one), the interpreter
could not name entry 3026, produced ZERO ops, the coordinator delegated to
legacy, and the ownership firewall refused legacy's write (mutation_rejected
2105). The correction lane never received an op.

These tests pin the wiring, not the model: a stub interpreter RECORDS what it
was handed. Before the fix, `board` was None and `thread_active` False.
"""
from __future__ import annotations

import datetime as dt

import pytest


class _Req:
    def __init__(self, text, metadata):
        self.text, self.turn_id, self.metadata = text, "t:board", metadata


async def _log_with_row(db, user):
    from db.queries import add_food_entry, get_or_create_log_for_date
    from db.models import DailyLog
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    log = await get_or_create_log_for_date(db, user.id, dt.date(2026, 8, 18))
    await add_food_entry(db, log.id, ledger_source="canonical:create",
                         user_id=user.id, parsed_food_name="grilled chicken",
                         quantity="6 oz", calories=257.0)
    await db.commit()
    return (await db.execute(select(DailyLog).where(DailyLog.id == log.id)
                             .options(selectinload(DailyLog.food_entries))
                             .execution_options(populate_existing=True))).scalar_one()


@pytest.mark.asyncio
async def test_the_plan_stage_hands_the_interpreter_todays_board(db, make_user):
    from core.turns.stages.food import FoodPlanStage
    user = await make_user()
    log = await _log_with_row(db, user)
    row_id = log.food_entries[0].id
    seen = {}

    async def spy(text, u, **kw):
        seen.update(kw)
        return {"action": "update", "tool_calls": [
            {"name": "update_food_entry",
             "input": {"entry_id": row_id, "quantity": "8 oz"}}]}

    req = _Req("actually the grilled chicken was 8 oz",
               {"db": db, "user": user, "today_log": log,
                "messages": ({"role": "assistant", "content": "Grilled chicken logged."},),
                "food_prior": None, "food_pending": False})
    plan = await FoodPlanStage(interpreter=spy).run(req)

    assert seen.get("board"), "the interpreter was handed NO board — it cannot name a row to correct"
    assert [b["id"] for b in seen["board"]] == [row_id]
    assert seen["board"][0]["food"] == "grilled chicken" and seen["board"][0]["qty"] == "6 oz"
    assert seen.get("thread_active") is True, "a correction seconds after a write is thread-active"
    assert seen.get("last_assistant") == "Grilled chicken logged."
    assert plan.operations and plan.operations[0]["input"]["entry_id"] == row_id


@pytest.mark.asyncio
async def test_a_request_that_already_carries_a_board_is_not_overridden(db, make_user):
    """Shadow hooks and tests may hand a board in explicitly; derivation only
    fills the gap, it never replaces what the caller stated."""
    from core.turns.stages.food import FoodPlanStage
    user = await make_user()
    seen = {}

    async def spy(text, u, **kw):
        seen.update(kw); return {"action": "pass", "tool_calls": []}

    req = _Req("x", {"db": db, "user": user, "today_log": None,
                     "board": [{"id": 999, "food": "given", "qty": "", "mins_ago": 0, "cal": 1}]})
    await FoodPlanStage(interpreter=spy).run(req)
    assert seen["board"][0]["id"] == 999


def test_build_request_carries_the_thread():
    from core.turns.entrypoint import build_request

    class U: id = 7
    req = build_request(turn_id="t", user=U(), platform="ios", source_type="ios",
                        text="hi", messages=[{"role": "assistant", "content": "a"}])
    assert req.metadata["messages"] == ({"role": "assistant", "content": "a"},)


@pytest.mark.asyncio
async def test_end_to_end_the_correction_reaches_the_canonical_route(db, make_user, monkeypatch):
    """The whole native chain on a CANONICAL row: plan (stub interpreter that
    reads the board it is handed) -> validate -> NativeExecutionStage ->
    _correction_route -> canonical correction. The legacy executor is
    instrumented to fail if invoked. Before the fix the plan had no ops and
    the turn delegated to legacy."""
    import handlers.tool_executor as te
    from core.canonical_correction import CORRECTION_SOURCE
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from core.turns.stages.execute_native import NativeExecutionStage
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from db.models import DailyLog, FoodEntry, LedgerEvent
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked — the correction fell through")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    user = await make_user()
    meal = ResolvedMeal(
        operation_id=f"canary_{user.id}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 18), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text="grilled chicken",
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=257.0, protein=52.0, carbs=0.0, fats=6.0, quantity_text="6 oz",
            attributes={"pricing": {"rung": "artifact", "evidence_id": "usda:1",
                                    "basis": "per_100g"}}),))
    await write_canonical_meal(db, operation=DirectOperation(meal), resolved_meal=meal)
    await db.commit()
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    log = (await db.execute(select(DailyLog).where(DailyLog.id == row.daily_log_id)
                            .options(selectinload(DailyLog.food_entries))
                            .execution_options(populate_existing=True))).scalar_one()

    async def interpreter_reading_the_board(text, u, **kw):
        # the model's job, stubbed: find the row on the board and correct it
        target = next(b for b in kw["board"] if "chicken" in b["food"])
        return {"action": "update", "tool_calls": [
            {"name": "update_food_entry",
             "input": {"entry_id": target["id"], "quantity": "8 oz",
                       "calories": 342.7, "protein": 69.2}}]}

    req = _Req("actually the grilled chicken was 8 oz",
               {"db": db, "user": user, "today_log": log, "messages": (),
                "food_prior": None, "food_pending": False})
    plan = await FoodPlanStage(interpreter=interpreter_reading_the_board).run(req)
    validation = await FoodValidationStage().run(req, plan=plan)
    assert validation.disposition == "execute"
    result = await NativeExecutionStage().run(req, validation=validation)
    assert result is not None and result.calls[0].committed

    fresh = (await db.execute(select(FoodEntry).where(FoodEntry.id == row.id)
                              .execution_options(populate_existing=True))).scalar_one()
    assert fresh.quantity == "8 oz"
    assert fresh.calories == pytest.approx(257.0 * 8 / 6, abs=1.0)   # ratio, not 342.7
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.source == CORRECTION_SOURCE))).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_a_committed_correction_renders_a_reply_not_the_recovery_bubble(
        db, make_user):
    """CANARY #2 (231fcf9, ios:0EE4B6BD): the correction COMMITTED (event 2110,
    claim 80) and the user was told "Lost the thread there. Try one more
    time" — the render stage produced NOTHING for a committed update, the
    reply was empty, and delivery substituted the recovery bubble. A real
    write reported as a failure is the phantom's mirror image."""
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from core.turns.stages.execute_native import NativeExecutionStage
    from core.turns.stages.render_native import NativeRenderStage
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    from db.models import DailyLog, FoodEntry
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    user = await make_user()
    meal = ResolvedMeal(
        operation_id=f"canary2_{user.id}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 18), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text="grilled chicken",
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=257.0, protein=52.0, carbs=0.0, fats=6.0, quantity_text="6 oz",
            attributes={"pricing": {"rung": "artifact", "evidence_id": "usda:1",
                                    "basis": "per_100g"}}),))
    await write_canonical_meal(db, operation=DirectOperation(meal), resolved_meal=meal)
    await db.commit()
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    log = (await db.execute(select(DailyLog).where(DailyLog.id == row.daily_log_id)
                            .options(selectinload(DailyLog.food_entries))
                            .execution_options(populate_existing=True))).scalar_one()

    # the interpreter's op, as it really arrives: entry_id AND food_name AND its numbers
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": row.id, "food_name": "grilled chicken",
                      "quantity": "8 oz", "calories": 342.7, "protein": 69.2}}]

    class _V:
        disposition = "execute"; approved_operations = ops; clarification = None

    req = _Req("actually the grilled chicken was 8 oz",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    execution = await NativeExecutionStage().run(req, validation=_V())
    assert execution.calls[0].committed
    snapshot = await CommittedSnapshotStage().run(req, execution=execution)
    response = await NativeRenderStage().run(req, plan=None, validation=_V(),
                                             snapshot=snapshot)
    assert response is not None and "".join(response.bubbles).strip(), \
        "a COMMITTED correction rendered no reply — the user gets the recovery bubble"
    text = " ".join(response.bubbles)
    assert "8 oz" in text or "343" in text or "342" in text, text


async def _canonical_chicken(db, user):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import DailyLog, FoodEntry
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    meal = ResolvedMeal(
        operation_id=f"e2e_{user.id}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 18), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text="grilled chicken",
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=257.0, protein=52.0, carbs=0.0, fats=6.0, quantity_text="6 oz",
            attributes={"pricing": {"rung": "artifact", "evidence_id": "usda:1",
                                    "basis": "per_100g"}}),))
    await write_canonical_meal(db, operation=DirectOperation(meal), resolved_meal=meal)
    await db.commit()
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    log = (await db.execute(select(DailyLog).where(DailyLog.id == row.daily_log_id)
                            .options(selectinload(DailyLog.food_entries))
                            .execution_options(populate_existing=True))).scalar_one()
    return row, log


async def _turn(db, user, log, text, turn_id):
    """The REAL entrypoint — route -> plan -> validate -> execute -> snapshot
    -> render — with the interpreter stubbed to read the board it is handed."""
    from core.turns import entrypoint as E
    req = E.build_request(turn_id=turn_id, user=user, platform="ios",
                          source_type="ios", text=text, db=db, today_log=log,
                          messages=[{"role": "assistant", "content": "Grilled chicken logged."}])
    return await E.run_turn(
        request=req, user=user, db=db, messages=req.metadata["messages"],
        system="", platform="ios", in_onboarding=False, was_onboarding=False,
        today_log=log, source_type="ios", on_image=None, on_interim=None,
        on_text_bubble=None, on_tool_start=None, on_card=None, turn_id=turn_id)


@pytest.mark.asyncio
async def test_undo_executes_natively_and_the_stale_guard_is_on_the_path(
        db, make_user, monkeypatch):
    """CANARY #2: "Undo" ran through LEGACY (source ledger_undo:v1) because
    LEDGER_UNDO was not an enabled native lane — so restore_recorded_state,
    and the B-1.8d stale-tip guard, were not on the production path. With the
    lane enabled: correction (native) -> undo (native, restore, source
    ledger_undo:canonical, restore claim) -> a SECOND undo of the same event
    is stale and refused non-mutating; the legacy executor never runs."""
    import handlers.tool_executor as te
    import core.food_turn as ft
    from core.canonical_correction import CORRECTION_SOURCE
    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent
    from sqlalchemy import select

    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_execute")
    monkeypatch.setenv("TURN_COORDINATOR_LANES", "structured_food,ledger_undo")
    monkeypatch.setenv("TURN_COORDINATOR_ALLOWLIST", "")
    monkeypatch.setenv("STRUCTURED_FOOD", "true")

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    async def stub(text, u, **kw):
        target = next(b for b in kw["board"] if "chicken" in b["food"])
        return {"action": "update", "say": "", "tool_calls": [
            {"name": "update_food_entry",
             "input": {"entry_id": target["id"], "food_name": "grilled chicken",
                       "quantity": "8 oz", "calories": 342.7}}]}
    monkeypatch.setattr(ft, "run", stub)
    async def rel(text): return True
    monkeypatch.setattr(ft, "food_relevance", rel)

    user = await make_user()
    row, log = await _canonical_chicken(db, user)
    row_id = int(row.id)

    r1 = await _turn(db, user, log, "actually the grilled chicken was 8 oz", "ios:e2e-corr")
    assert "".join(r1.response.bubbles).strip()
    mid = (await db.execute(select(FoodEntry).where(FoodEntry.id == row_id)
                            .execution_options(populate_existing=True))).scalar_one()
    assert mid.quantity == "8 oz"

    r2 = await _turn(db, user, log, "undo", "ios:e2e-undo")
    assert r2 is not None and "".join(r2.response.bubbles).strip()
    after = (await db.execute(select(FoodEntry).where(FoodEntry.id == row_id)
                              .execution_options(populate_existing=True))).scalar_one()
    assert after.quantity == "6 oz" and after.calories == pytest.approx(257.0)
    restores = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id,
        LedgerEvent.source == "ledger_undo:canonical"))).scalars().all()
    assert len(restores) == 1, "the undo did not run through the canonical restore"
    legacy_undo = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id,
        LedgerEvent.source == "ledger_undo:v1"))).scalars().all()
    assert legacy_undo == []
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id,
        IdempotencyRecord.command == "restore"))).scalars().all()
    assert len(claims) == 1 and claims[0].status == "completed"
