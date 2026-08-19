"""⛔⛔ CF5c — ONE SCAN AUTHORITY *(Danny, 2026-08-19)*.

Four production-shaped routes were found around the CF5 guards, and each fix
added another local guard at the point where the damage surfaced:

    ios:D3B7757E   implicit ratio correction of a board row      CF5b
    mixed turn     attachment read as binding                    review 2
    undecidable    the decision itself failed open               review 3
    zero-op        early return before any decision ran          review 4

The pattern was the finding: every guard re-derived "is this bound?" from
whatever it had to hand. CF5c makes it ONE semantic decision with three
physical touch points — pre-plan hook, post-plan gate, execution enforcement
— and strips the other guards to backstops that read the disposition and fail
closed on a shape that cannot be.

THE PROOF MATRIX (Danny, verbatim):

    scan + "yes"                     -> no replay of an older confirmed food
    multi-food ask, one ready item   -> SKIPPED_MULTI_ITEM, not BOUND
    zero approved operations         -> CF9 ask or typed refusal, never legacy
    bound canonical update           -> refused before the correction route
    mismatched text/snapshot name    -> the snapshot's identity wins

Plus the ordinary-path twin: a correctly named direct scan settles
IDENTICALLY after identity was widened to every bound log. A widening that
only proves the negative has not proved it is safe.
"""
from __future__ import annotations

import logging

import pytest

from tests.test_a_scan_is_binding import (BAREBELLS_PROD, _Req, _log,
                                          _prod_snapshot)


class _Plan:
    def __init__(self, ops=(), ambiguities=(), intent="log"):
        self.operations = tuple(ops)
        self.ambiguities = tuple(ambiguities)
        self.response_intent = intent


class _V:
    """A ValidationResult stand-in for tests that drive execution directly."""

    def __init__(self, ops=(), clarification=None, disposition="execute"):
        self.approved_operations = tuple(ops)
        self.clarification = clarification
        self.disposition = disposition


async def _rows(db, log):
    from db.models import FoodEntry
    from sqlalchemy import select
    t = FoodEntry.__table__
    return (await db.execute(select(t).where(
        t.c.daily_log_id == log.id).order_by(t.c.id))).mappings().all()


# ═════ 1 — SCAN + "yes" MUST NOT REPLAY AN OLDER CONFIRMED FOOD ════════════

@pytest.mark.asyncio
async def test_cf5c_a_scan_suppresses_confirm_replay(db, make_user, monkeypatch,
                                                     caplog):
    """⛔ THE UPSTREAM HOLE. `ConfirmReplayPlanStage` runs BEFORE the
    interpreter, before the plan, before any binding decision — so scan +
    "yes" would log an EARLIER confirmed food verbatim and then attach THIS
    scan's snapshot to it: one product's nutrition under another product's
    name. Every identity guard lives downstream of this stage and none of
    them would have seen it."""
    from core.turns.stages.food import FoodPlanStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    # an open confirm holding a DIFFERENT food, and the user says "yes"
    prior = {"kind": "confirm",
             "items": [{"food": "Chicken thighs", "amount": 2, "unit": "piece",
                        "calories": 500}]}
    req = _Req("yes", {"db": db, "user": user, "today_log": log,
                       "messages": (), "food_prior": prior,
                       "board": [], "day_line": "", "regulars": None})

    async def interpreter_must_run(text, u, **kw):
        return {"action": "log", "say": "", "tool_calls": [
            {"name": "log_food",
             "input": {"food_name": "Barebells", "quantity": "1 bar"}}]}

    begin_turn()
    attach(snap.id)
    try:
        plan = await FoodPlanStage(interpreter=interpreter_must_run).run(req)
    finally:
        begin_turn()

    assert "scan_suppresses_confirm_replay" in caplog.text
    names = [op["input"].get("food_name", "") for op in plan.operations]
    assert not any("chicken" in n.lower() for n in names), (
        f"the scan was absorbed by a replay of an older confirmed meal: {names}")
    assert any("barebells" in n.lower() for n in names), names


@pytest.mark.asyncio
async def test_cf5c_an_unscanned_yes_still_replays(db, make_user, monkeypatch):
    """The twin: with NO scan the replay is untouched — CF5c suppresses it for
    scanned turns only, and a confirm answered "yes" must still cost no
    re-parse."""
    from core.turns.stages.food import FoodPlanStage
    from skills.nutrition.product_acquisition import begin_turn
    user = await make_user()
    log = await _log(db, user)
    prior = {"kind": "confirm",
             "items": [{"food": "Chicken thighs", "amount": 2, "unit": "piece",
                        "calories": 500}]}
    req = _Req("yes", {"db": db, "user": user, "today_log": log,
                       "messages": (), "food_prior": prior,
                       "board": [], "day_line": "", "regulars": None})

    async def interpreter_must_not_run(text, u, **kw):
        raise AssertionError("the replay did not fire — this cost a re-parse")

    begin_turn()
    plan = await FoodPlanStage(interpreter=interpreter_must_not_run).run(req)
    names = [op["input"].get("food_name", "") for op in plan.operations]
    assert any("chicken" in n.lower() for n in names), names


# ═════ 2 — A MULTI-FOOD ASK EXPOSING ONE READY ITEM BINDS NOTHING ══════════

@pytest.mark.asyncio
async def test_cf5c_a_two_food_ask_with_one_ready_item_does_not_bind(
        db, make_user, monkeypatch, caplog):
    """⛔ WHY THE GATE READS THE COMPLETE PLAN. `FoodValidationStage` approves
    only the READY items of an ask, so a turn naming TWO foods can expose
    exactly ONE approved operation. A decision taken from the approved writes
    counts one food and binds the scan; the clarification's own item list is
    the other half of the truth."""
    from core.turns.stages.food import FoodValidationStage
    from skills.nutrition.product_acquisition import (SKIPPED_MULTI_ITEM,
                                                      SCAN_BINDING, attach,
                                                      begin_turn)
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    ready = {"name": "log_food",
             "input": {"food_name": "Barebells", "quantity": "1 bar"}}
    ask = {"items": [{"food": "Barebells"}, {"food": "Mystery soup"}],
           "ambiguities": [{"field": "quantity"}],
           "tool_calls": [ready]}
    plan = _Plan([ready], (ask,), intent="ask")
    req = _Req("a barebells and some soup",
               {"db": db, "user": user, "today_log": log, "messages": ()})

    begin_turn()
    attach(snap.id)
    try:
        validation = await FoodValidationStage().run(req, plan=plan)
        assert len(validation.approved_operations) == 1     # the trap
        assert SCAN_BINDING.get().kind == SKIPPED_MULTI_ITEM, (
            "a two-food turn bound the scan because only one write was approved")
    finally:
        begin_turn()


# ═════ 3 — ZERO APPROVED OPERATIONS: CF9 ASK OR REFUSAL, NEVER LEGACY ══════

@pytest.mark.asyncio
async def test_cf5c_zero_ops_with_quantity_the_only_unknown_opens_the_cf9_ask(
        db, make_user, monkeypatch, caplog):
    """One consumed product, the amount unknown: the DURABLE ask holding the
    snapshot, so the answer settles bound — not a refusal, and not legacy."""
    import handlers.tool_executor as te
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import PendingOperation
    from skills.nutrition.product_acquisition import attach, begin_turn
    from sqlalchemy import select
    import json
    caplog.set_level(logging.INFO)

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked for a scanned turn")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    ask = {"items": [{"food": "Barebells Salty Peanut Protein Bar"}],
           "ambiguities": [{"field": "quantity"}], "tool_calls": []}
    req = _Req("barebells", {"db": db, "user": user, "today_log": log,
                             "messages": ()}, turn_id=f"ios:cf5c-ask-{user.id}")

    from core.scan_authority import decide_from_plan
    begin_turn()
    attach(snap.id)
    try:
        decide_from_plan(_Plan([], (ask,), intent="ask"))
        execution = await NativeExecutionStage().run(
            req, validation=_V([], clarification=ask, disposition="ask"))
    finally:
        begin_turn()

    assert execution is not None and not execution.calls[0].committed
    assert "scan_zero_op_bound_ask" in caplog.text
    assert await _rows(db, log) == []
    op = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().one()
    payload = json.loads(op.canonical_payload)
    item = (payload.get("interaction") or {}).get("item") or payload.get("item") or {}
    assert int(item.get("product_evidence_id") or 0) == snap.id, payload


@pytest.mark.asyncio
async def test_cf5c_zero_ops_with_another_ambiguity_refuses_without_legacy(
        db, make_user, monkeypatch, caplog):
    """No trustworthy amount question — an identity ambiguity beside it — is
    the refusal arm. Non-mutating, no legacy, and the user is told."""
    import handlers.tool_executor as te
    from core.scan_authority import ScanAuthorityRefusal, decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    caplog.set_level(logging.INFO)

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked for a scanned turn")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    ask = {"items": [{"food": "Barebells"}],
           "ambiguities": [{"field": "quantity"}, {"field": "identity"}],
           "tool_calls": []}
    req = _Req("barebells?", {"db": db, "user": user, "today_log": log,
                              "messages": ()}, turn_id=f"ios:cf5c-ref-{user.id}")
    begin_turn()
    attach(snap.id)
    try:
        decide_from_plan(_Plan([], (ask,), intent="ask"))
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await NativeExecutionStage().run(
                req, validation=_V([], clarification=ask, disposition="ask"))
    finally:
        begin_turn()
    assert ei.value.reason == "no_quantity_ask"
    assert await _rows(db, log) == []


@pytest.mark.asyncio
async def test_cf5c_an_unscanned_zero_op_turn_still_reaches_legacy(
        db, make_user, monkeypatch):
    """⚠ THE BRANCH THAT MUST SURVIVE. `native_no_plan` delegation is
    legitimate for an UNSCANNED turn and stays exactly as it was: the stage
    returns None so the entrypoint can hand it to legacy."""
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import begin_turn
    user = await make_user()
    log = await _log(db, user)
    req = _Req("I had a corn on the cob",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    begin_turn()
    assert await NativeExecutionStage().run(req, validation=_V([])) is None


@pytest.mark.asyncio
async def test_cf5c_the_zero_op_path_clears_the_ambient_execution(
        db, make_user, monkeypatch):
    """The zero-op return used to happen BEFORE `LAST_EXECUTION.set(None)`, so
    a previous turn's execution stayed ambient for the renderer to narrate."""
    from core.execution_result import LAST_EXECUTION
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import begin_turn
    user = await make_user()
    log = await _log(db, user)
    LAST_EXECUTION.set("a previous turn's execution")
    req = _Req("nothing to log",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    begin_turn()
    await NativeExecutionStage().run(req, validation=_V([]))
    assert LAST_EXECUTION.get() is None


# ═════ 4 — A BOUND CANONICAL UPDATE IS REFUSED BEFORE THE CORRECTION ROUTE ══

@pytest.mark.asyncio
async def test_cf5c_a_bound_update_never_reaches_the_correction_route(
        db, make_user, monkeypatch, caplog):
    """Even if the planner lift misses it, BOUND + `update_food_entry` is an
    impossible shape and the gate refuses it BEFORE `_correction_route` runs
    — so a canonically owned row cannot be corrected under a scan either."""
    from core.scan_authority import ScanAuthorityRefusal, decide_from_plan
    from core.turns.stages import execute_native as en
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    reached = []
    real_route = NativeExecutionStage._correction_route
    async def spy(self, db_, user_, ops):
        reached.append(ops)
        return await real_route(self, db_, user_, ops)
    monkeypatch.setattr(NativeExecutionStage, "_correction_route", spy)

    upd = [{"name": "update_food_entry",
            "input": {"entry_id": 1, "quantity": "4 bar"}}]
    req = _Req("make it 4", {"db": db, "user": user, "today_log": log,
                             "messages": ()}, turn_id=f"ios:cf5c-upd-{user.id}")
    begin_turn()
    attach(snap.id)
    try:
        decide_from_plan(_Plan(upd))
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await NativeExecutionStage().run(req, validation=_V(upd))
    finally:
        begin_turn()
    assert ei.value.reason == "impossible_shape"
    assert not reached, "the correction route ran on a bound turn"


# ═════ 5 — IDENTITY: THE SNAPSHOT WINS, AND THE ORDINARY PATH IS UNCHANGED ══

async def _settle_one_log(db, user, log, snap, monkeypatch, *, food_name,
                          quantity="2 servings", turn_id="ios:cf5c-id"):
    from core.scan_authority import decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    ops = [{"name": "log_food",
            "input": {"food_name": food_name, "quantity": quantity,
                      "calories": 999.0}}]
    req = _Req(f"{quantity} of {food_name}",
               {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"{turn_id}-{user.id}")
    begin_turn()
    attach(snap.id)
    try:
        decide_from_plan(_Plan(ops))
        return await NativeExecutionStage().run(req, validation=_V(ops))
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_cf5c_a_mismatched_name_loses_to_the_snapshot(
        db, make_user, monkeypatch, caplog):
    """The interpreter's prose names a DIFFERENT product beside a correct
    snapshot. Identity is now authoritative for EVERY bound log, so the row
    is named by the snapshot — never one product's name over another's
    nutrition."""
    from db.models import FoodEntry
    from sqlalchemy import select
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    execution = await _settle_one_log(db, user, log, snap, monkeypatch,
                                      food_name="Quest Protein Bar",
                                      turn_id="ios:cf5c-mismatch")
    assert execution.calls[0].committed
    row = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().one()
    assert row.parsed_food_name == BAREBELLS_PROD["product_name"], row.parsed_food_name
    assert "quest" not in row.parsed_food_name.lower()
    assert row.product_evidence_id == snap.id
    assert row.calories == pytest.approx(220.0)


@pytest.mark.asyncio
async def test_cf5c_the_ordinary_correctly_named_scan_settles_identically(
        db, make_user, monkeypatch):
    """⚠ THE TWIN THAT MAKES THE WIDENING SAFE. Identity used to be repaired
    only for LIFTED items; it now applies to every bound log. A widening
    proved only by its negative has not been proved safe — so the ORDINARY
    path, where the interpreter already named the product correctly, must
    settle byte-identically to the mismatched one."""
    from db.models import FoodEntry
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    await _settle_one_log(db, user, log, snap, monkeypatch,
                          food_name=BAREBELLS_PROD["product_name"],
                          turn_id="ios:cf5c-ordinary")
    rows = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.parsed_food_name == BAREBELLS_PROD["product_name"]
    assert row.product_evidence_id == snap.id
    assert row.pricing_rung == "product"
    assert row.calories == pytest.approx(220.0)
    assert row.resolved_grams == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_cf5c_an_unbound_log_keeps_the_interpreters_name(
        db, make_user, monkeypatch):
    """And with no scan the interpreter's name stands, exactly as before —
    the widening must not reach unscanned turns."""
    from core.scan_authority import decide_from_plan
    from core.turns.stages.execute_native import _name_from_snapshot
    from skills.nutrition.product_acquisition import begin_turn
    await _prod_snapshot(db)
    begin_turn()
    decide_from_plan(_Plan([]))
    ops = [{"name": "log_food", "input": {"food_name": "Home made soup"}}]
    await _name_from_snapshot(db, ops)
    assert ops[0]["input"]["food_name"] == "Home made soup"


# ═════ THE AUTHORITY IS SINGULAR ═══════════════════════════════════════════

def test_cf5c_the_decision_has_exactly_one_home():
    """`decide_from_plan` is called from ONE place — the validation stage.
    Two callers would be two decisions, which is the whole defect."""
    import ast
    import pathlib
    callers = []
    roots = ("core", "handlers", "skills", "api", "db")
    for root in roots:
        for path in pathlib.Path(root).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "decide_from_plan"):
                    callers.append(str(path))
    assert callers == ["core/turns/stages/food.py"], callers


def test_cf5c_enforcement_precedes_every_exit_in_run():
    """AST: `require_shape` is called before the first `return` in
    `NativeExecutionStage.run`, and before the legacy import."""
    import ast
    import inspect
    from core.turns.stages.execute_native import NativeExecutionStage
    tree = ast.parse(inspect.getsource(NativeExecutionStage.run).lstrip())
    enforce = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and getattr(n.func, "id", None) == "require_shape"]
    returns = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Return)]
    legacy = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.ImportFrom)
              and any(a.name == "execute_tool_calls" for a in n.names)]
    assert enforce, "the gate is not enforced in run()"
    assert min(enforce) < min(returns), (
        "a turn can return before the scan authority is consumed")
    assert not legacy or min(enforce) < min(legacy)
