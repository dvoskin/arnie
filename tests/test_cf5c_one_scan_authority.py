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


def _Plan(ops=(), ambiguities=(), intent="log", **producer):
    """A REAL plan, through the real normaliser. Builds an interpreter-shaped
    dict — the producer's own keys — and lifts it with
    `plan_from_interpretation`, so `food_subjects` is exactly what production
    would carry. Extra producer keys (`deferred_calls`, `questions`,
    `b1_material`, `points`) pass straight through."""
    from core.turns.stages.food import plan_from_interpretation
    out = {"action": intent, "tool_calls": list(ops), "say": ""}
    if intent == "ask":
        # the primary ask origin's shape: no top-level items/ambiguities
        out.setdefault("questions", [])
    for amb in ambiguities:
        # legacy fixture shape ({"items": [...], "ambiguities": [...]},) —
        # kept for tests that still use it; a dict WITHOUT "items" is a typed
        # producer record {"item","field"} and passes straight through
        if isinstance(amb, dict) and "items" in amb:
            out.setdefault("items", []).extend(amb.get("items") or [])
            out.setdefault("ambiguities", []).extend(amb.get("ambiguities") or [])
        elif isinstance(amb, dict):
            out.setdefault("ambiguities", []).append(amb)
    out.update(producer)
    return plan_from_interpretation(out)

class _V:
    """A ValidationResult stand-in for tests that drive execution directly.
    Carries the PLAN, as the real stage does — execution reads the typed
    food subjects off it."""

    def __init__(self, ops=(), clarification=None, disposition="execute",
                 plan=None):
        self.approved_operations = tuple(ops)
        self.clarification = clarification
        self.disposition = disposition
        self.plan = plan


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
    # THE LIVE SHAPE (primary ask origin, partial commit OFF): no ready
    # write, no top-level items/ambiguities — the food rides ONLY the question
    # label and the nested material. This is exactly the shape the first cut
    # of the gate read as "no food" and refused.
    live = dict(
        questions=[{"item": "Barebells Salty Peanut Protein Bar",
                    "text": "How much of the Barebells did you have?",
                    "options": []}],
        ambiguities=[{"item": "Barebells Salty Peanut Protein Bar",
                      "field": "quantity"}],                     # TYPED
        deferred_calls=[],
        b1_material={"staged_items": (), "items": [
            {"food": "Barebells Salty Peanut Protein Bar", "amount": None,
             "unit": ""}]},
        _message="had a barebells")                             # CONSUMED
    plan = _Plan([], intent="ask", **live)
    assert [s.name for s in plan.food_subjects] == ["Barebells Salty Peanut Protein Bar"]
    assert plan.open_fields == ("quantity",)
    req = _Req("barebells", {"db": db, "user": user, "today_log": log,
                             "messages": ()}, turn_id=f"ios:cf5c-ask-{user.id}")

    from core.scan_authority import decide_from_plan
    begin_turn()
    attach(snap.id)
    try:
        decide_from_plan(plan)
        execution = await NativeExecutionStage().run(
            req, validation=_V([], clarification=live, disposition="ask",
                               plan=plan))
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
    # live shape: the question is a FLAVOUR question — not an amount — so
    # quantity is not the only unknown and CF9 does not apply
    live = dict(
        questions=[{"item": "Barebells",
                    "text": "Salty Peanut or Caramel Cashew?", "options": []}],
        ambiguities=[{"item": "Barebells", "field": "flavor"}],   # TYPED, not quantity
        deferred_calls=[],
        b1_material={"staged_items": (), "items": [{"food": "Barebells"}]},
        _message="had a barebells")
    plan = _Plan([], intent="ask", **live)
    assert plan.open_fields == ("food_identity",)
    req = _Req("barebells?", {"db": db, "user": user, "today_log": log,
                              "messages": ()}, turn_id=f"ios:cf5c-ref-{user.id}")
    begin_turn()
    attach(snap.id)
    try:
        decide_from_plan(plan)
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await NativeExecutionStage().run(
                req, validation=_V([], clarification=live, disposition="ask",
                                   plan=plan))
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


# ═════ REVIEW OF da32929 — THE GATE MUST READ THE PRODUCER'S REAL SHAPE ═════
#
# The first CF5c "complete plan" proof handcrafted `{"items": [...],
# "ambiguities": [...]}` — a shape the primary live ask origin does NOT emit.
# `core.food_turn.run` returns an ask as {tool_calls, deferred_calls,
# questions, b1_material, points}: no top-level items, no ambiguities. So the
# gate proved itself against its fixture, not the producer. These drive the
# REAL producer (`FT.run` with only the model mocked, the harness
# `test_leave_no_food_behind.py` uses) under BOTH partial-commit settings.

import json as _json
from types import SimpleNamespace as _NS

import core.food_turn as _FT


def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": _json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


def _u():
    return _NS(preferences=_NS(food_logging_mode="moderate"))


def _it(food, cal=100, **kw):
    d = {"food": food, "amount": 1, "unit": "", "calories": cal,
         "protein": 5, "carbs": 10, "fats": 3}
    d.update(kw)
    return d


async def _live_plan(monkeypatch, message, payload):
    """The producer's ACTUAL ask dict, lifted by the real
    `plan_from_interpretation` — no shape invented anywhere."""
    from core.turns.stages.food import plan_from_interpretation
    monkeypatch.setattr(_FT, "chat", _fake_chat(payload))
    out = await _FT.run(message, _u())
    assert out and out.get("action") == "ask", out
    # the producer's own keys, asserted so a shape change is visible here
    assert "items" not in out or out.get("b1_material") is not None or "points" in out
    return out, plan_from_interpretation({**out, "_message": message})


@pytest.mark.asyncio
@pytest.mark.parametrize("partial_commit", ["false", "true"])
async def test_cf5c_live_producer_one_ready_plus_one_held_is_skipped_multi_item(
        monkeypatch, partial_commit):
    """A two-food ask through the REAL producer: one food ready, one asked
    about. With partial commit OFF both are held (zero approved writes); ON,
    the ready one is approved (ONE approved write). Either way the turn is
    about TWO foods and the scan binds nothing — the case that approved-
    operation counting got wrong in both directions."""
    from skills.nutrition.product_acquisition import (SKIPPED_MULTI_ITEM,
                                                      SCAN_BINDING, attach,
                                                      begin_turn)
    from core.scan_authority import decide_from_plan
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", partial_commit)
    out, plan = await _live_plan(monkeypatch, "had alpha and bravo", {
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "ambiguities": [{"item": "Alpha", "field": "quantity", "impact_cal": 100}],
        "ready": [_it("Bravo")],
        "items": [_it("Alpha"), _it("Bravo")]})

    # the producer's shape, as it really is
    approved = out.get("tool_calls") or []
    held = out.get("deferred_calls") or []
    if partial_commit == "true":
        assert len(approved) == 1 and not held         # ONE ready write exposed
    else:
        assert not approved and len(held) == 1         # ZERO approved writes
    # and the typed subjects see BOTH foods regardless
    names = sorted(s.name.lower() for s in plan.food_subjects)
    assert names == ["alpha", "bravo"], plan.food_subjects

    begin_turn(); attach(7)
    try:
        assert decide_from_plan(plan) == SKIPPED_MULTI_ITEM
        assert SCAN_BINDING.get().kind == SKIPPED_MULTI_ITEM
    finally:
        begin_turn()


@pytest.mark.asyncio
@pytest.mark.parametrize("partial_commit", ["false", "true"])
async def test_cf5c_live_producer_quantity_only_ask_is_bound_and_opens_cf9(
        db, make_user, monkeypatch, partial_commit):
    """A ONE-food quantity ask through the REAL producer: with partial commit
    OFF this has ZERO approved writes and — before this fix — read as "no
    food" and refused. It is one consumed product with quantity the only
    unknown: BOUND, and the zero-op branch opens the CF9 ask holding the
    snapshot."""
    import handlers.tool_executor as te
    from core.scan_authority import decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import PendingOperation
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    from sqlalchemy import select
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", partial_commit)

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked for a scanned turn")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    # the model's schema REQUIRES `ambiguities: [{item, field}]` on an ask —
    # the TYPED field the authority reads. And the message says they ATE it
    # (CF5c-B2): "had a barebells", not "barebells".
    out, plan = await _live_plan(monkeypatch, "had a barebells", {
        "action": "ask",
        "points": [{"label": "Barebells Salty Peanut Protein Bar",
                    "qs": ["how much did you have?"]}],
        "ambiguities": [{"item": "Barebells Salty Peanut Protein Bar",
                         "field": "quantity", "impact_cal": 200}],
        "items": [_it("Barebells Salty Peanut Protein Bar", amount=None)]})
    assert not (out.get("tool_calls") or [])              # nothing ready either way
    assert [s.name for s in plan.food_subjects] == ["Barebells Salty Peanut Protein Bar"]
    assert plan.open_fields == ("quantity",), plan.open_fields

    req = _Req("barebells", {"db": db, "user": user, "today_log": log,
                             "messages": ()},
               turn_id=f"ios:cf5c-live-{partial_commit}-{user.id}")
    begin_turn(); attach(snap.id)
    try:
        assert decide_from_plan(plan) == BOUND
        execution = await NativeExecutionStage().run(
            req, validation=_V([], clarification=out, disposition="ask",
                               plan=plan))
    finally:
        begin_turn()
    assert execution is not None and not execution.calls[0].committed
    assert await _rows(db, log) == []
    op = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().one()
    payload = _json.loads(op.canonical_payload)
    item = (payload.get("interaction") or {}).get("item") or payload.get("item") or {}
    assert int(item.get("product_evidence_id") or 0) == snap.id, payload


@pytest.mark.asyncio
async def test_cf5c_the_reask_origin_is_also_normalised(monkeypatch):
    """The OTHER live ask origin (a re-ask) carries `points` + `questions` and
    no `b1_material`. Its foods must be seen too."""
    from core.turns.stages.food import plan_from_interpretation
    out = {"action": "ask", "text": "how much?",
           "points": [{"label": "Alpha", "qs": ["how much?"]},
                      {"label": "Bravo", "qs": ["how big?"]}],
           "questions": [{"item": "Alpha", "text": "how much?", "options": []},
                         {"item": "Bravo", "text": "how big?", "options": []}]}
    plan = plan_from_interpretation(out)
    assert sorted(s.name for s in plan.food_subjects) == ["Alpha", "Bravo"]
    # no typed ambiguity record on this origin -> the field is INFERRED from
    # the prose and marked as such; the CF9 test does not accept an inferred
    # field, so this shape can never open a quantity-to-log ask by itself
    assert plan.open_fields == ("quantity?",)


def test_cf5c_the_gate_refuses_a_plan_without_the_typed_contract():
    """A plan that arrives WITHOUT `food_subjects` — a stub, an older producer
    — is not counted from some other view; the contract is refused."""
    from core.scan_authority import foods_in_plan
    class _Bare:
        operations = ({"name": "log_food", "input": {"food_name": "x"}},)
        ambiguities = ()
    with pytest.raises(ValueError, match="food_subjects"):
        foods_in_plan(_Bare())


def test_cf5c_an_unnamed_correction_is_still_one_food_subject():
    """`_update_call` emits {entry_id, quantity} with NO food_name when the
    interpreter does not rename ("make it 4"). That is still a turn about ONE
    food — the row it targets — not a turn about none."""
    from core.turns.stages.food import plan_from_interpretation
    plan = plan_from_interpretation({"action": "update", "tool_calls": [
        {"name": "update_food_entry", "input": {"entry_id": 3030, "quantity": "4 bar"}}]})
    assert len(plan.food_subjects) == 1
    assert plan.food_subjects[0].key == "entry:3030"


# ═════ OCCURRENCE IS THE UNIT; NAME IS ONLY THE CROSS-CARRIER LINK ═════════
#
# Danny, pre-ship: normalised-name deduplication must collapse ONE subject
# repeated across carriers, never TWO distinct occurrences. A one-ready-plus-
# one-held turn about the SAME product collapsed to one subject -> BOUND ->
# the ready write went through on a turn with two food intents.

def test_cf5c_one_subject_mirrored_through_every_carrier_is_one():
    """The same Barebells seen through ALL SEVEN carriers — a ready write, its
    staged row, its interpretation row, top-level items, a question, a point,
    and (with partial commit off, the same op) a held write — is ONE subject
    with the roles merged."""
    from types import SimpleNamespace as NS
    from core.turns.stages.food import plan_from_interpretation
    call = {"name": "log_food", "input": {"food_name": "Barebells Bar",
                                          "quantity": "1 bar"}}
    plan = plan_from_interpretation({
        "action": "ask",
        "tool_calls": [call],                                     # 1 ready
        "deferred_calls": [],
        "questions": [{"item": "barebells bar", "text": "how many?",
                       "options": []}],                           # 2 question
        "points": [{"label": "Barebells bar", "qs": ["how many?"]}],  # 3 point
        "b1_material": {
            "staged_items": (NS(food="Barebells Bar", staged_item_id="s1",
                                ambiguities=(NS(field="quantity"),)),),  # 4 staged
            "items": [{"food": "Barebells Bar"}]},                # 5 interpreted
        "items": [{"food": "Barebells Bar"}],                     # 6 top-level
        "ambiguities": [{"item": "Barebells Bar",
                         "field": "quantity"}]})                  # 7 amb (typed)
    assert len(plan.food_subjects) == 1, plan.food_subjects
    sub = plan.food_subjects[0]
    assert sub.key == "op:ready:0"                 # anchored on the occurrence
    assert sub.open_fields == ("quantity",)        # typed, via `ambiguities`
    assert sub.consumed is True                    # a write asserts consumption


def test_cf5c_an_ambiguity_record_without_an_item_does_not_type_the_field():
    """The model's schema requires `{"item", "field"}`. A record naming no
    item cannot be attributed to a subject, so the field stays INFERRED and
    marked — conservative: it will not open a quantity-to-log ask."""
    from core.turns.stages.food import plan_from_interpretation
    plan = plan_from_interpretation({
        "action": "ask", "tool_calls": [],
        "questions": [{"item": "Barebells", "text": "how many?", "options": []}],
        "ambiguities": [{"field": "quantity"}],           # no item
        "b1_material": {"staged_items": (), "items": [{"food": "Barebells"}]}})
    assert plan.open_fields == ("quantity?",), plan.open_fields


def test_cf5c_two_independently_represented_same_name_subjects_are_two():
    """Two SEPARATE Barebells operations — one ready, one held — are two
    subjects even though their names normalise identically, and the turn is
    SKIPPED_MULTI_ITEM: the scan binds nothing, the ready write does not go
    through as if this were one food."""
    from core.scan_authority import decide_from_plan
    from core.turns.stages.food import plan_from_interpretation
    from skills.nutrition.product_acquisition import (SKIPPED_MULTI_ITEM,
                                                      attach, begin_turn)
    a = {"name": "log_food", "input": {"food_name": "Barebells Bar",
                                       "quantity": "1 bar"}}
    b = {"name": "log_food", "input": {"food_name": "barebells bar",
                                       "quantity": "2 bar"}}
    plan = plan_from_interpretation({
        "action": "ask", "tool_calls": [a], "deferred_calls": [b],
        "questions": [{"item": "Barebells bar", "text": "how many?",
                       "options": []}],
        "b1_material": {"staged_items": (),
                        "items": [{"food": "Barebells Bar"},
                                  {"food": "Barebells Bar"}]}})
    keys = sorted(s.key for s in plan.food_subjects)
    assert keys == ["op:held:0", "op:ready:0"], plan.food_subjects
    # the label attached to BOTH occurrences (a question about that food),
    # not to a third subject — inferred from prose here (no typed record)
    assert all("quantity?" in s.open_fields for s in plan.food_subjects)
    begin_turn(); attach(7)
    try:
        assert decide_from_plan(plan) == SKIPPED_MULTI_ITEM
    finally:
        begin_turn()


def test_cf5c_two_same_name_ready_writes_are_two_and_refuse_under_bound():
    """Two ready `log_food` for the same product: two subjects, and if the
    disposition were somehow BOUND the executor would refuse the shape —
    BOUND is exactly ONE log_food."""
    from core.scan_authority import ScanAuthorityRefusal, require_shape
    from core.turns.stages.food import plan_from_interpretation
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    a = {"name": "log_food", "input": {"food_name": "Barebells Bar", "quantity": "1 bar"}}
    plan = plan_from_interpretation({"action": "log", "tool_calls": [a, dict(a)]})
    assert len(plan.food_subjects) == 2
    begin_turn(); attach(7)
    SCAN_BINDING.set(ScanBinding("bound", 7))          # adversarially
    try:
        with pytest.raises(ScanAuthorityRefusal) as ei:
            require_shape([a, dict(a)])
        assert ei.value.reason == "impossible_shape"
    finally:
        begin_turn()


# ═════ CLEANUP — stale API gated · CONSUMED lifecycle · backstop fails closed ═

def test_cf5c_no_production_module_calls_the_stale_decision_api():
    """`decide_binding` is gone; `scan_is_bound` is a mechanical delegate.
    No production module may call either — the authority is the only
    decision and the only reader."""
    import ast
    import pathlib
    import skills.nutrition.product_acquisition as pa
    assert not hasattr(pa, "decide_binding"), "the stale second decision API survives"
    offenders = []
    for root in ("core", "handlers", "skills", "api", "db"):
        for path in pathlib.Path(root).rglob("*.py"):
            if path.name == "product_acquisition.py":
                continue
            tree = ast.parse(path.read_text())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    f = n.func
                    nm = getattr(f, "id", None) or getattr(f, "attr", None)
                    if nm in ("decide_binding", "scan_is_bound"):
                        offenders.append(f"{path}:{n.lineno}")
    assert not offenders, offenders


@pytest.mark.asyncio
async def test_cf5c_a_settled_bound_meal_is_CONSUMED_and_so_is_the_ordinary_ask(
        db, make_user, monkeypatch):
    """The lifecycle: BOUND -> CONSUMED once the bound meal SETTLES, and once
    the ordinary BoundUnpriceable ask holds the snapshot — not only on the
    zero-op ask."""
    from skills.nutrition.product_acquisition import CONSUMED, SCAN_BINDING
    from core.scan_authority import decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    # (a) settles bound
    ops = [{"name": "log_food", "input": {"food_name": BAREBELLS_PROD["product_name"],
                                          "quantity": "2 servings", "calories": 999.0}}]
    plan = _Plan(ops)
    req = _Req("2 servings", {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:cf5c-consumed-a-{user.id}")
    begin_turn(); attach(snap.id); decide_from_plan(plan)
    ex = await NativeExecutionStage().run(req, validation=_V(ops, plan=plan))
    assert ex.calls[0].committed
    assert SCAN_BINDING.get().kind == CONSUMED, SCAN_BINDING.get()

    # (b) the ordinary bound ask (BoundUnpriceable: "2 bars" has no label unit)
    ops2 = [{"name": "log_food", "input": {"food_name": BAREBELLS_PROD["product_name"],
                                           "quantity": "2 bar", "calories": 999.0}}]
    plan2 = _Plan(ops2)
    req2 = _Req("2 bars", {"db": db, "user": user, "today_log": log, "messages": ()},
                turn_id=f"ios:cf5c-consumed-b-{user.id}")
    begin_turn(); attach(snap.id); decide_from_plan(plan2)
    ex2 = await NativeExecutionStage().run(req2, validation=_V(ops2, plan=plan2))
    assert not ex2.calls[0].committed
    assert ex2.calls[0].correction["refusal"] == "scan_bound_ask"
    assert SCAN_BINDING.get().kind == CONSUMED, SCAN_BINDING.get()
    begin_turn()


def test_cf5c_the_correction_backstop_fails_closed_when_the_authority_is_unreadable(
        monkeypatch):
    """A backstop advertised as fail-closed must not `return` when it cannot
    read the authority: an unreadable authority is an UNKNOWN about binding,
    and arithmetic under an unknown binding is the write it exists to stop."""
    import core.scan_authority as sa
    from skills.nutrition import correction_application as ca

    def _boom():
        raise RuntimeError("authority unreadable")
    monkeypatch.setattr(sa, "is_bound", _boom)
    with pytest.raises(ca.ScanBoundCorrectionRefused):
        ca._refuse_if_scan_bound("Sun Chips")


# ═════ EACH PRODUCER SOURCE, AS THE SOLE CARRIER OF A FOOD ═════════════════
#
# The mutation sweep found that dropping `deferred_calls` or `b1_material`
# from the normaliser left every proof green — each was redundant with the
# question labels on those fixtures. A source that is only ever proven
# alongside another source is unproven. So each source carries a food that
# appears NOWHERE else, and the count must still see it.

def test_cf5c_a_food_carried_only_by_a_deferred_write_is_counted():
    """Partial commit OFF: a co-item the interpreter marked READY but did not
    ask about rides ONLY `deferred_calls` — no question names it, no material
    row stages it (the ready list bypasses staging). Dropping it reads a
    two-food turn as one and BINDS a scan to it."""
    from core.turns.stages.food import plan_from_interpretation
    plan = plan_from_interpretation({
        "action": "ask", "tool_calls": [],
        "deferred_calls": [{"name": "log_food",
                            "input": {"food_name": "Bravo", "quantity": "1"}}],
        "questions": [{"item": "Alpha", "text": "how much?", "options": []}],
        "b1_material": {"staged_items": (), "items": [{"food": "Alpha"}]}})
    assert sorted(s.name for s in plan.food_subjects) == ["Alpha", "Bravo"]
    assert next(s for s in plan.food_subjects if s.name == "Bravo").role == "held"


def test_cf5c_a_food_carried_only_by_the_material_is_counted():
    """The interpretation lists a food the points/questions never label — the
    corn shape from `test_leave_no_food_behind` (parsed, neither asked nor
    ready). Only `b1_material.items` knows it exists."""
    from core.turns.stages.food import plan_from_interpretation
    plan = plan_from_interpretation({
        "action": "ask", "tool_calls": [], "deferred_calls": [],
        "questions": [{"item": "Turkey", "text": "how much?", "options": []}],
        "b1_material": {"staged_items": (),
                        "items": [{"food": "Turkey"}, {"food": "Corn"}]}})
    assert sorted(s.name for s in plan.food_subjects) == ["Corn", "Turkey"]


def test_cf5c_a_food_carried_only_by_a_staged_item_is_counted():
    """Typed staging can carry a row the raw list did not (a split, a
    normalised alias). `b1_material.staged_items` is walked too, and its own
    ambiguity list yields the open fields."""
    from types import SimpleNamespace as NS
    from core.turns.stages.food import plan_from_interpretation
    staged = NS(food="Egg whites", ambiguities=(NS(field="quantity"),))
    plan = plan_from_interpretation({
        "action": "ask", "tool_calls": [], "deferred_calls": [],
        "questions": [], "points": [],
        "b1_material": {"staged_items": (staged,), "items": []}})
    assert [s.name for s in plan.food_subjects] == ["Egg whites"]
    assert plan.food_subjects[0].open_fields == ("quantity",)


def test_cf5c_a_food_carried_only_by_a_point_label_is_counted():
    """The re-ask origin ships `points` with no `questions` on some paths."""
    from core.turns.stages.food import plan_from_interpretation
    plan = plan_from_interpretation({
        "action": "ask", "points": [{"label": "Kotletka", "qs": ["how big?"]}]})
    assert [s.name for s in plan.food_subjects] == ["Kotletka"]
    assert plan.open_fields == ("quantity?",)          # inferred, not typed


# ═════ REVIEW OF fc38825 — FOUR BLOCKERS, FIVE REQUIRED PROOFS ═══════════════
#
#   1. Existing B-1 ask + new scan cannot settle the old item.
#   2. No consumption assertion means no quantity-to-log operation.
#   3. Same-turn retry returns the same ask; concurrent scans leave at most
#      one active ask.
#   4. A hidden second subject prevents every scan-specific plan transform.
#   5. Binding for snapshot A cannot settle using attachment B.


# ── 1. THE B-1 CLAIM UPSTREAM OF THE COORDINATOR ────────────────────────────

@pytest.mark.asyncio
async def test_b1_an_open_ask_cannot_claim_a_scanned_text_message(
        db, make_user, monkeypatch, caplog):
    """`b1_answer_turn.handle` runs from `core.conversation` BEFORE the
    coordinator. An open CHICKEN quantity ask must not consume a NEW Barebells
    scan + "2 servings" as its answer: the chicken must not settle, and the
    scanned message must fall through (None = "not ours") to the coordinator
    where CF5c owns it."""
    from core import b1_answer_turn
    from core.b1_quantity_operation import owning
    from db.models import FoodEntry
    from skills.nutrition.product_acquisition import attach, begin_turn
    from sqlalchemy import select
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    # an OPEN chicken ask, opened by the ordinary bound-ask path on a scan of
    # some other product is overkill — open a plain B-1 ask instead
    from tests.test_a_scan_is_binding import _open_bound_ask
    chicken_snap = await _prod_snapshot(db)         # any snapshot; the ask is what matters
    await _open_bound_ask(db, user, log, chicken_snap, monkeypatch,
                          turn_id=f"ios:b1-open-{user.id}", qty="2 bar")
    open_op = await owning(db, user)
    assert open_op is not None and open_op.awaiting
    rows_before = len((await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all())

    # a NEW scan rides the next free-text message
    begin_turn(); attach(snap.id)
    try:
        out = await b1_answer_turn.handle(db, user=user,
                                          source_turn_id=f"ios:b1-scan-{user.id}",
                                          message="2 servings")
    finally:
        begin_turn()
    assert out is None, f"the open ask claimed a scanned message: {out}"
    assert "b1_answer_declines_scanned_text" in caplog.text
    # the old operation did NOT settle
    still = await owning(db, user)
    assert still is not None and still.awaiting
    rows_after = len((await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all())
    assert rows_after == rows_before


@pytest.mark.asyncio
async def test_b1_a_chip_tap_with_a_scan_attached_is_still_an_answer(
        db, make_user, monkeypatch):
    """The twin: a TAP (`option_id`) names its operation and IS an answer —
    the CF9 tap on the bound ask carries the scan too. Only free text is
    declined."""
    from core import b1_answer_turn
    from core.clarification_answer import Outcome
    from skills.nutrition.product_acquisition import attach, begin_turn
    from tests.test_a_scan_is_binding import _open_bound_ask
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    ex = await _open_bound_ask(db, user, log, snap, monkeypatch,
                               turn_id=f"ios:b1-tap-{user.id}")
    field = ex.calls[0].correction["interaction"]["groups"][0]["fields"][0]
    two = next(o for o in field["options"] if o["option_id"] == "opt_label_serving_2")
    begin_turn(); attach(snap.id)                    # the tap rides the scan too
    try:
        turn = await b1_answer_turn.handle(
            db, user=user, source_turn_id=f"ios:b1-tapans-{user.id}",
            field_id=field["field_id"], option_id=two["option_id"], revision=0)
    finally:
        begin_turn()
    assert turn is not None and turn.outcome is Outcome.APPLIED, turn


# ── 2. NO CONSUMPTION, NO QUANTITY-TO-LOG OPERATION ─────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["barebells", "scanned a barebells",
                                     "got some barebells", "barebells for later"])
async def test_b2_a_named_or_scanned_product_with_no_consumption_does_not_open_an_ask(
        db, make_user, monkeypatch, message):
    """The user scanned or named the product and did NOT say they ate it. The
    subject carries no consumption assertion, so CF9 does not apply: typed
    refusal, no operation, no row."""
    import handlers.tool_executor as te
    from core.scan_authority import ScanAuthorityRefusal, decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import PendingOperation
    from skills.nutrition.product_acquisition import attach, begin_turn
    from sqlalchemy import select

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked for a scanned turn")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    live = dict(
        questions=[{"item": "Barebells Salty Peanut Protein Bar",
                    "text": "How much?", "options": []}],
        ambiguities=[{"item": "Barebells Salty Peanut Protein Bar",
                      "field": "quantity"}],
        deferred_calls=[],
        b1_material={"staged_items": (), "items": [
            {"food": "Barebells Salty Peanut Protein Bar"}]},
        _message=message)
    plan = _Plan([], intent="ask", **live)
    assert len(plan.food_subjects) == 1
    assert plan.food_subjects[0].consumed is False, plan.food_subjects
    req = _Req(message, {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:b2-{abs(hash(message)) % 10**6}-{user.id}")
    begin_turn(); attach(snap.id)
    try:
        decide_from_plan(plan)
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await NativeExecutionStage().run(
                req, validation=_V([], clarification=live, disposition="ask",
                                   plan=plan))
    finally:
        begin_turn()
    assert ei.value.reason == "no_consumption"
    assert await _rows(db, log) == []
    assert (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_leak_a_an_inferred_quantity_field_does_not_open_the_ask(
        db, make_user, monkeypatch):
    """The question's PROSE says "how much" but the interpreter typed no
    field for the item. The field is INFERRED and marked; CF9 accepts typed
    ids only, so this refuses rather than opening an ask whose answer logs
    food. (Consumption IS asserted here, so the refusal is about the field.)"""
    import handlers.tool_executor as te
    from core.scan_authority import ScanAuthorityRefusal, decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    live = dict(
        questions=[{"item": "Barebells Salty Peanut Protein Bar",
                    "text": "How much did you have?", "options": []}],
        # NO typed ambiguity record
        deferred_calls=[],
        b1_material={"staged_items": (), "items": [
            {"food": "Barebells Salty Peanut Protein Bar"}]},
        _message="had a barebells")
    plan = _Plan([], intent="ask", **live)
    assert plan.food_subjects[0].consumed is True
    assert plan.open_fields == ("quantity?",)          # inferred, marked
    req = _Req("had a barebells", {"db": db, "user": user, "today_log": log,
                                   "messages": ()}, turn_id=f"ios:leak-a-{user.id}")
    begin_turn(); attach(snap.id)
    try:
        decide_from_plan(plan)
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await NativeExecutionStage().run(
                req, validation=_V([], clarification=live, disposition="ask",
                                   plan=plan))
    finally:
        begin_turn()
    assert ei.value.reason == "no_quantity_ask"
    assert await _rows(db, log) == []


def test_leak_c_two_same_name_questions_with_no_anchor_are_two_subjects():
    """Two questions about "Barebells" and nothing else naming it: two
    intents until something says otherwise -> two subjects. Whereas the SAME
    label once in `questions` and once in `points` is one reference."""
    from core.turns.stages.food import plan_from_interpretation
    two_q = plan_from_interpretation({"action": "ask", "questions": [
        {"item": "Barebells", "text": "how many?", "options": []},
        {"item": "barebells", "text": "which flavour?", "options": []}]})
    assert len(two_q.food_subjects) == 2, two_q.food_subjects
    q_and_p = plan_from_interpretation({"action": "ask",
        "questions": [{"item": "Barebells", "text": "how many?", "options": []}],
        "points": [{"label": "Barebells", "qs": ["how many?"]}]})
    assert len(q_and_p.food_subjects) == 1, q_and_p.food_subjects


def test_b2_a_write_asserts_consumption_and_a_bare_label_does_not():
    from core.turns.stages.food import plan_from_interpretation
    write = plan_from_interpretation({"action": "log", "tool_calls": [
        {"name": "log_food", "input": {"food_name": "Barebells", "quantity": "1"}}],
        "_message": "barebells"})
    assert write.food_subjects[0].consumed is True
    label = plan_from_interpretation({"action": "ask", "questions": [
        {"item": "Barebells", "text": "how many?", "options": []}],
        "_message": "barebells"})
    assert label.food_subjects[0].consumed is False
    said = plan_from_interpretation({"action": "ask", "questions": [
        {"item": "Barebells", "text": "how many?", "options": []}],
        "_message": "had a barebells"})
    assert said.food_subjects[0].consumed is True


# ── 3. IDEMPOTENT, SINGLE-OWNER ASK CREATION ────────────────────────────────

@pytest.mark.asyncio
async def test_b3_a_same_turn_retry_returns_the_same_ask(db, make_user, monkeypatch,
                                                         caplog):
    """The retry does not cancel its own ask and collide: it finds its own
    operation open and returns THAT ask, same operation id, same option ids."""
    from core.b1_quantity_operation import owning
    from db.models import PendingOperation
    from sqlalchemy import select
    from tests.test_a_scan_is_binding import _open_bound_ask
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    tid = f"ios:b3-retry-{user.id}"
    ex1 = await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=tid)
    op1 = ex1.calls[0].correction["interaction"]["operation_id"]
    ex2 = await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=tid)
    op2 = ex2.calls[0].correction["interaction"]["operation_id"]
    assert op1 == op2
    # reuse is decided at the SEAM now (fingerprint-checked) and surfaced by
    # the wrapper as `bound_ask_reused`; nothing was superseded or released
    assert "b1_open_reused" in caplog.text and "bound_ask_reused" in caplog.text
    assert "b1_prior_released" not in caplog.text
    ops = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().all()
    assert len(ops) == 1 and ops[0].status == "awaiting_answer"
    f1 = ex1.calls[0].correction["interaction"]["groups"][0]["fields"][0]
    f2 = ex2.calls[0].correction["interaction"]["groups"][0]["fields"][0]
    assert [o["option_id"] for o in f1["options"]] == [o["option_id"] for o in f2["options"]]


@pytest.mark.asyncio
async def test_b3_a_failed_supersede_refuses_rather_than_opening_beside(
        db, make_user, monkeypatch):
    """A prior ask exists and cancelling it FAILS: refuse (typed), never open
    a second awaiting operation beside an unknown."""
    import core.b1_quantity_operation as b1q
    from core.product_bound_ask import BoundAskNotSingular
    from core.scan_authority import decide_from_plan
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import PendingOperation
    from skills.nutrition.product_acquisition import attach, begin_turn
    from sqlalchemy import select
    from tests.test_a_scan_is_binding import _open_bound_ask
    user = await make_user()
    uid = user.id                                    # captured: rollback expires `user`
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(uid))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:b3-p-{uid}")

    # the release lives in `open_operation` (`_release_prior_awaiting`); make
    # the repository's revision write fail so the prior CANNOT be released
    from core import pending_repository as repo
    async def _boom(*a, **k):
        raise RuntimeError("release failed")
    monkeypatch.setattr(repo, "save_revision", _boom)
    monkeypatch.setattr(repo, "mark_expired", _boom)
    ops = [{"name": "log_food", "input": {"food_name": BAREBELLS_PROD["product_name"],
                                          "quantity": "2 bar", "calories": 400.0}}]
    plan = _Plan(ops)
    req = _Req("2 bars", {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:b3-second-{user.id}")
    import logging as _lg
    caplog = None
    begin_turn(); attach(snap.id); decide_from_plan(plan)
    try:
        with pytest.raises(BoundAskNotSingular) as ei:
            await NativeExecutionStage().run(req, validation=_V(ops, plan=plan))
    finally:
        begin_turn()
    # the refusal came from the SUPERSEDE step, not from losing an insert
    # race to the DB constraint (defence in depth that would ALSO stop it,
    # and would mask a supersede handler that swallowed the failure)
    assert "could not supersede" in str(ei.value), ei.value
    await db.rollback()
    open_ops = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == uid,
        PendingOperation.status == "awaiting_answer"))).scalars().all()
    assert len(open_ops) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not __import__("os").getenv("TEST_POSTGRES_URL"),
                    reason="the one-awaiting constraint is a PARTIAL UNIQUE "
                           "INDEX enforced by the database under real "
                           "concurrent connections; the shared sqlite fixture "
                           "has one connection")
async def test_b3_concurrent_scans_leave_at_most_one_active_ask(monkeypatch):
    """Two workers, two connections, the SAME user, each opening a bound ask
    for a different turn at once. The partial unique index
    `uq_pending_operations_one_awaiting` lets exactly one insert land; the
    loser reads the winner and returns it. Never two awaiting rows."""
    import asyncio
    import os
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from db.database import make_engine
    from db.models import Base, PendingOperation, User
    from skills.nutrition.product_store import append_product_evidence

    engine = make_engine(os.environ["TEST_POSTGRES_URL"], pool_size=5, max_overflow=5)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            u = User(telegram_id="cf5c-race", onboarding_completed=True)
            s.add(u); await s.flush()
            from db.models import UserPreferences
            s.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
            snap = await append_product_evidence(s, record=dict(BAREBELLS_PROD))
            await s.commit()
            uid, sid = u.id, snap.id
        monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(uid))

        async def one(turn):
            from core.general_settlement import coverage_for
            from core.product_bound_ask import open_bound_quantity_ask
            from skills.nutrition.product_acquisition import (SCAN_BINDING,
                                                              ScanBinding, attach,
                                                              begin_turn)
            async with factory() as s:
                user = await s.get(User, uid)
                begin_turn(); attach(sid); SCAN_BINDING.set(ScanBinding("bound", sid))
                item = {"food_name": BAREBELLS_PROD["product_name"], "quantity": "2 bar",
                        "product_evidence_id": sid}
                cov = await coverage_for(s, user_id=uid, items=[item])
                ask = await open_bound_quantity_ask(
                    s, user=user, item=item, coverage=cov, turn_id=turn,
                    channel="ios", locale="en")
                await s.commit()
                begin_turn()
                return getattr(ask, "operation_id", None)

        # (a) two DIFFERENT turns at once: the newer may legitimately SUPERSEDE
        # the older (cancel + insert). The invariant is not "same ask" — it is
        # AT MOST ONE ACTIVE, and every returned id names a row that exists.
        results = await asyncio.gather(one("ios:race-A"), one("ios:race-B"),
                                       return_exceptions=True)
        async with factory() as s:
            rows = (await s.execute(select(PendingOperation).where(
                PendingOperation.user_id == uid))).scalars().all()
            awaiting = [o for o in rows if o.status == "awaiting_answer"
                        and o.storage_status == "active"]
        assert len(awaiting) <= 1, [(o.operation_id, o.status) for o in awaiting]
        known = {o.operation_id for o in rows}
        for r in results:
            assert not isinstance(r, Exception) or "NotSingular" in type(r).__name__, r
            if isinstance(r, str):
                assert r in known, (r, known)

        # (b) the SAME turn at once — the true collision: identical operation
        # id, no supersede possible. Exactly one row, and both workers return
        # THAT id (one inserted, one lost the race and read the winner).
        async with factory() as s:
            for o in (await s.execute(select(PendingOperation).where(
                    PendingOperation.user_id == uid))).scalars().all():
                await s.delete(o)
            await s.commit()
        results = await asyncio.gather(one("ios:race-SAME"), one("ios:race-SAME"),
                                       return_exceptions=True)
        async with factory() as s:
            rows = (await s.execute(select(PendingOperation).where(
                PendingOperation.user_id == uid))).scalars().all()
        assert len(rows) == 1, [(o.operation_id, o.status) for o in rows]
        assert rows[0].status == "awaiting_answer"
        for r in results:
            if isinstance(r, Exception):
                assert "NotSingular" in type(r).__name__, r
            else:
                assert r == rows[0].operation_id, (r, rows[0].operation_id)
    finally:
        await engine.dispose()


def test_b3_the_model_declares_the_one_awaiting_index_for_both_dialects():
    """The constraint exists in the ORM (so the shared harness sees it) AND a
    migration ships it (so production does) — the drift class the
    'never amend a pushed migration' rule records."""
    import pathlib
    from db.models import PendingOperation
    idx = {i.name: i for i in PendingOperation.__table__.indexes}
    assert "uq_pending_operations_one_awaiting" in idx
    i = idx["uq_pending_operations_one_awaiting"]
    assert i.unique
    assert i.dialect_options["postgresql"]["where"] is not None
    assert i.dialect_options["sqlite"]["where"] is not None
    mig = pathlib.Path("alembic/versions/oneask001_one_awaiting_operation_per_user.py")
    assert mig.exists() and "uq_pending_operations_one_awaiting" in mig.read_text()


# ── 4. A HIDDEN SECOND SUBJECT PREVENTS EVERY SCAN TRANSFORM ────────────────

@pytest.mark.asyncio
async def test_b4_a_hidden_second_subject_prevents_every_scan_transform(
        db, make_user, monkeypatch, caplog):
    """The plan names TWO foods but exposes ONE ready write — a shape the
    old planner would have scan-transformed (identity answered, unit
    restored, correction lifted) and the authority then classified
    SKIPPED_MULTI_ITEM. Now the planner is attachment-blind and `bind_plan`
    runs only for BOUND, so NONE of the three transforms fires."""
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from skills.nutrition.product_acquisition import (SKIPPED_MULTI_ITEM,
                                                      SCAN_BINDING, attach,
                                                      begin_turn)
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)

    # an ask: ONE ready write (Barebells) + a HELD soup + a flavour question
    # about the bar. Every transform's trigger is present: identity-class
    # ambiguity on a single interpreter item, a scan, "2 servings" in the
    # message. But the soup is a second subject.
    ready = {"name": "log_food",
             "input": {"food_name": "Barebells bar", "quantity": "2 bar"}}
    held = {"name": "log_food",
            "input": {"food_name": "Mystery soup", "quantity": "1 bowl"}}
    interpreter_out = {
        "action": "ask", "text": "Salty Peanut or Caramel Cashew?",
        "tool_calls": [ready], "deferred_calls": [held],
        "items": [{"food": "Barebells bar", "amount": 2, "unit": "bar"}],
        "ambiguities": [{"item": "Barebells bar", "field": "flavor"}],
        "questions": [{"item": "Barebells bar",
                       "text": "Salty Peanut or Caramel Cashew?", "options": []}],
        "b1_material": {"staged_items": (), "items": [
            {"food": "Barebells bar"}, {"food": "Mystery soup"}]},
        "say": ""}

    async def stub(text, u, **kw):
        return interpreter_out
    req = _Req("2 servings of barebells and some soup",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    begin_turn(); attach(snap.id)
    try:
        raw = await FoodPlanStage(interpreter=stub).run(req)
        # the PLANNER did nothing scan-specific
        assert [op["name"] for op in raw.operations] == ["log_food"]
        assert raw.operations[0]["input"]["quantity"] == "2 bar"      # not restored
        assert raw.response_intent == "ask"                             # not answered
        v = await FoodValidationStage().run(req, plan=raw)
        assert SCAN_BINDING.get().kind == SKIPPED_MULTI_ITEM
        # and the post-decision bind step ALSO left it alone
        assert v.plan.response_intent == "ask"
        assert v.plan.operations[0]["input"]["quantity"] == "2 bar"
    finally:
        begin_turn()
    for marker in ("scan_answers_identity", "scan_rejects_correction_shape",
                   "scan_user_unit_restored"):
        assert marker not in caplog.text, marker


@pytest.mark.asyncio
async def test_b4_the_same_plan_with_one_subject_is_transformed_after_the_decision(
        db, make_user, monkeypatch, caplog):
    """The twin: remove the hidden soup and the SAME plan is BOUND, and the
    transforms fire — AFTER the decision, in the validation stage."""
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from skills.nutrition.product_acquisition import BOUND, SCAN_BINDING, attach, begin_turn
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    interpreter_out = {
        "action": "ask", "text": "Salty Peanut or Caramel Cashew?",
        "tool_calls": [],
        "items": [{"food": "Barebells bar", "amount": 2, "unit": "bar"}],
        "ambiguities": [{"item": "Barebells bar", "field": "flavor"}],
        "questions": [{"item": "Barebells bar",
                       "text": "Salty Peanut or Caramel Cashew?", "options": []}],
        "b1_material": {"staged_items": (), "items": [{"food": "Barebells bar"}]},
        "say": ""}

    async def stub(text, u, **kw):
        return interpreter_out
    req = _Req("2 servings of barebells",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    begin_turn(); attach(snap.id)
    try:
        raw = await FoodPlanStage(interpreter=stub).run(req)
        assert raw.response_intent == "ask" and not raw.operations      # untouched
        v = await FoodValidationStage().run(req, plan=raw)
        assert SCAN_BINDING.get().kind == BOUND
        assert v.disposition == "execute"
        assert v.plan.operations[0]["name"] == "log_food"
        assert v.plan.operations[0]["input"]["quantity"] == "2 serving"  # restored
    finally:
        begin_turn()
    assert "scan_answers_identity" in caplog.text


def test_b4_the_planner_module_holds_no_attachment_read():
    """AST: `core.turns.stages.food` reads the attachment ONLY through the
    pre-plan hook `suppresses_replay_and_prior`; no other function in the
    module touches SCANNED_PRODUCT_EVIDENCE or the authority's is_bound —
    the transforms live in `bind_plan`, which reads the DECISION."""
    import ast
    import inspect
    from core.turns.stages import food as m
    tree = ast.parse(inspect.getsource(m))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            if "SCANNED_PRODUCT_EVIDENCE" in names | attrs:
                assert False, f"{node.name} reads the attachment directly"
            if node.name in ("_plan_from_interpretation", "food_subjects_of",
                             "_lift_bound_correction_to_log",
                             "_restore_user_stated_unit",
                             "_scan_answers_the_identity"):
                assert "is_bound" not in names and "scan_attached" not in names, (
                    f"{node.name} consults the scan — the planner is attachment-blind")


# ── 5. BINDING FOR SNAPSHOT A CANNOT SETTLE USING ATTACHMENT B ──────────────

@pytest.mark.asyncio
async def test_b5_binding_for_snapshot_a_cannot_settle_using_attachment_b(
        db, make_user, monkeypatch, caplog):
    """The authority decided BOUND for snapshot A; the attachment variable
    is then swapped to B (a stale contextvar, a mid-turn re-set). Every
    downstream reader follows the DECISION — and the mismatch itself is
    refused before any write."""
    from core.scan_authority import ScanAuthorityRefusal, decide_from_plan, snapshot_id
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import (SCAN_BINDING,
                                                      SCANNED_PRODUCT_EVIDENCE,
                                                      attach, begin_turn)
    from skills.nutrition.product_store import append_product_evidence
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap_a = await _prod_snapshot(db)
    other = dict(BAREBELLS_PROD, code="70004200", product_name="Quest Protein Bar",
                 brands="Quest", rev=2)
    snap_b = await append_product_evidence(db, record=other)
    assert snap_a.id != snap_b.id

    ops = [{"name": "log_food", "input": {"food_name": BAREBELLS_PROD["product_name"],
                                          "quantity": "2 servings", "calories": 999.0}}]
    plan = _Plan(ops)
    req = _Req("2 servings", {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:b5-{user.id}")
    begin_turn(); attach(snap_a.id); decide_from_plan(plan)
    assert SCAN_BINDING.get().snapshot_id == snap_a.id
    # the attachment is swapped UNDER the decision
    SCANNED_PRODUCT_EVIDENCE.set(snap_b.id)
    try:
        assert snapshot_id() == snap_a.id, "a reader followed the attachment, not the decision"
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await NativeExecutionStage().run(req, validation=_V(ops, plan=plan))
        assert ei.value.reason == "snapshot_mismatch"
    finally:
        begin_turn()
    assert await _rows(db, log) == []


def test_b5_the_authority_reads_the_decided_snapshot_and_no_module_reads_the_raw_one():
    """AST: outside `scan_authority` and `product_acquisition`, no production
    module reads SCANNED_PRODUCT_EVIDENCE — every consumer goes through
    `snapshot_id()`, which follows the decision."""
    import ast
    import pathlib
    offenders = []
    for root in ("core", "handlers", "skills", "api"):
        for path in pathlib.Path(root).rglob("*.py"):
            if path.name in ("scan_authority.py", "product_acquisition.py"):
                continue
            tree = ast.parse(path.read_text())
            for n in ast.walk(tree):
                if (isinstance(n, ast.Attribute) and n.attr == "get"
                        and isinstance(n.value, ast.Name)
                        and n.value.id == "SCANNED_PRODUCT_EVIDENCE"):
                    offenders.append(f"{path}:{n.lineno}")
    assert not offenders, offenders


# ═════ REVIEW OF 22b9e7a — B3's two identity-impacting defects + proof gaps ═

@pytest.mark.asyncio
async def test_b3_a_release_that_reports_not_ok_refuses_by_value(
        db, make_user, monkeypatch):
    """⛔ THE REPOSITORY REPORTS, IT DOES NOT RAISE. `save_revision` and
    `mark_expired` return SaveOutcome(ok=False, conflict=True) when another
    writer moved the row first. The first cut checked only exceptions, logged
    "released", and proceeded to INSERT beside a row it had not released. The
    mock here is the REAL contract value, not an exception."""
    from core import pending_repository as repo
    from core.b1_quantity_operation import PriorAskNotReleased, open_operation
    from core.pending_repository import SaveOutcome
    from db.models import PendingOperation
    from sqlalchemy import select
    from tests.test_a_scan_is_binding import _open_bound_ask
    user = await make_user()
    uid = user.id
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(uid))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:b3v-p-{uid}")

    async def _conflict(*a, **k):
        return SaveOutcome(ok=False, revision=7, conflict=True)
    monkeypatch.setattr(repo, "save_revision", _conflict)
    monkeypatch.setattr(repo, "mark_expired", _conflict)

    from core.semantics import ClarificationInteraction
    from skills.nutrition import quantity_clarification as qc
    from core.food_pipeline import stage_items
    staged = stage_items({"items": [{"food": "Oatmeal", "amount": 1, "unit": "cup",
                                     "calories": 150}]}, turn_id="t", message="oatmeal",
                         mode="strict")[0]
    op_id_probe = "x"
    field = qc.quantity_field(operation_id=op_id_probe, revision=0, item=staged)
    interaction = qc.build_interaction(operation_id=op_id_probe, revision=0,
                                       item=staged, options=field.options,
                                       introduction="How much?", ask_preparation=False)
    with pytest.raises(PriorAskNotReleased) as ei:
        await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                             interaction=interaction,
                             turn_id=f"ios:b3v-second-{uid}", locale="en")
    assert "revision conflict" in str(ei.value)
    await db.rollback()
    awaiting = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == uid,
        PendingOperation.status == "awaiting_answer"))).scalars().all()
    assert len(awaiting) == 1                         # the prior, untouched; no second


@pytest.mark.asyncio
async def test_b3_open_operation_returns_a_typed_result_and_reuse_renders_the_stored_one(
        db, make_user, monkeypatch, caplog):
    """The seam returns OpenResult. A second call for the SAME turn with the
    SAME semantics is `reused`, its interaction is the STORED one (decoded
    from the row), its fingerprint matches — and no second row exists. The
    interaction here is built with the row's COMPUTED operation id, not a
    placeholder (the earlier version built it with "x", so it never proved
    the wire's operation_id equalled the row's)."""
    from core.b1_quantity_operation import (OpenResult, _operation_id_for,
                                            open_operation, semantic_fingerprint)
    from core.food_pipeline import stage_items
    from db.models import PendingOperation
    from skills.nutrition import quantity_clarification as qc
    from sqlalchemy import select
    caplog.set_level(logging.INFO)
    user = await make_user()
    tid = f"ios:b3-seam-{user.id}"
    op_id = _operation_id_for(user, tid)
    staged = stage_items({"items": [{"food": "Oatmeal", "amount": 1, "unit": "cup",
                                     "calories": 150}]}, turn_id=tid, message="oatmeal",
                         mode="strict")[0]
    field = qc.quantity_field(operation_id=op_id, revision=0, item=staged)
    interaction = qc.build_interaction(operation_id=op_id, revision=0, item=staged,
                                       options=field.options,
                                       introduction="How much?", ask_preparation=False)
    item = {"food": "Oatmeal", "amount": 1, "unit": "cup"}
    first = await open_operation(db, user=user, interpreter_item=item,
                                 interaction=interaction, turn_id=tid, locale="en")
    await db.commit()
    assert isinstance(first, OpenResult) and first.created
    assert first.operation_id == op_id
    second = await open_operation(db, user=user, interpreter_item=item,
                                  interaction=interaction, turn_id=tid, locale="en")
    assert second.reused and second.operation_id == op_id
    assert second.fingerprint == first.fingerprint == semantic_fingerprint(interaction, item)
    assert "b1_open_reused" in caplog.text
    assert "b1_prior_released" not in caplog.text
    rows = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().all()
    assert len(rows) == 1
    import json as _json
    stored = _json.loads(rows[0].canonical_payload)["interaction"]
    assert second.interaction.to_payload()["operation_id"] == stored["operation_id"] == op_id
    assert ([o["option_id"] for g in second.interaction.to_payload()["groups"]
             for f in g["fields"] for o in f["options"]]
            == [o["option_id"] for g in stored["groups"]
                for f in g["fields"] for o in f["options"]])


@pytest.mark.asyncio
async def test_b3_same_turn_different_semantics_is_not_a_reuse(db, make_user):
    """Same operation id (same turn), DIFFERENT snapshot / question: the
    persisted payload's fingerprint differs -> OpenedElsewhere, not a reuse.
    Concurrent retries with snapshots A and B cannot persist A and render B."""
    from core.b1_quantity_operation import (OpenedElsewhere, _operation_id_for,
                                            open_operation)
    from core.food_pipeline import stage_items
    from skills.nutrition import quantity_clarification as qc
    user = await make_user()
    tid = f"ios:b3-sem-{user.id}"
    op_id = _operation_id_for(user, tid)
    def _build(food, pid):
        staged = stage_items({"items": [{"food": food, "amount": 2, "unit": "bar",
                                         "calories": 200}]}, turn_id=tid, message=food,
                             mode="strict")[0]
        field = qc.quantity_field(operation_id=op_id, revision=0, item=staged)
        inter = qc.build_interaction(operation_id=op_id, revision=0, item=staged,
                                     options=field.options, introduction="How much?",
                                     ask_preparation=False)
        return inter, {"food": food, "amount": 2, "unit": "bar",
                       "product_evidence_id": pid}
    ia, item_a = _build("Barebells bar", 1)
    ib, item_b = _build("Quest bar", 2)
    first = await open_operation(db, user=user, interpreter_item=item_a,
                                 interaction=ia, turn_id=tid, locale="en")
    await db.commit()
    assert first.created
    with pytest.raises(OpenedElsewhere, match="DIFFERENT semantic payload"):
        await open_operation(db, user=user, interpreter_item=item_b,
                             interaction=ib, turn_id=tid, locale="en")


@pytest.mark.asyncio
async def test_b3_a_lost_race_to_a_different_turn_is_refused_not_rendered(
        db, make_user, monkeypatch):
    """The insert loses to a winner from a DIFFERENT turn. The first cut
    returned "whichever ask currently owns the user" — product B's question
    rendered in product A's reply. Now: OpenedElsewhere at the seam,
    BoundAskNotSingular at the wrapper; the other ask is never presented as
    this one."""
    from sqlalchemy.exc import IntegrityError
    from core import pending_repository as repo
    from core.b1_quantity_operation import OpenedElsewhere, open_operation
    from skills.nutrition import quantity_clarification as qc
    from core.food_pipeline import stage_items
    from tests.test_a_scan_is_binding import _open_bound_ask
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    # a winner from turn A already awaiting (the "other product's question")
    await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:raceA-{user.id}")

    # turn B: make the release a no-op (simulating the window where the
    # winner landed AFTER our release read) and the insert collide
    async def _no_rows(*a, **k):
        return []
    monkeypatch.setattr(repo, "locked_awaiting_for_user", _no_rows)
    real_create = repo.create_operation
    async def _collide(*a, **k):
        raise IntegrityError("insert", {}, Exception("uq_pending_operations_one_awaiting"))
    monkeypatch.setattr(repo, "create_operation", _collide)

    staged = stage_items({"items": [{"food": "Quest bar", "amount": 1, "unit": "bar",
                                     "calories": 200}]}, turn_id="t", message="quest",
                         mode="strict")[0]
    field = qc.quantity_field(operation_id="x", revision=0, item=staged)
    interaction = qc.build_interaction(operation_id="x", revision=0, item=staged,
                                       options=field.options,
                                       introduction="How much?", ask_preparation=False)
    with pytest.raises(OpenedElsewhere):
        await open_operation(db, user=user, interpreter_item={"food": "Quest bar"},
                             interaction=interaction,
                             turn_id=f"ios:raceB-{user.id}", locale="en")
    monkeypatch.setattr(repo, "create_operation", real_create)


@pytest.mark.asyncio
async def test_b3_the_bound_wrapper_refuses_a_same_id_ask_bound_to_another_snapshot(
        db, make_user, monkeypatch):
    """Same operation id, awaiting — but the persisted item is bound to a
    DIFFERENT snapshot. Not rendered as this scan's question."""
    from core.product_bound_ask import BoundAskNotSingular, open_bound_quantity_ask
    from core.general_settlement import coverage_for
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    from skills.nutrition.product_store import append_product_evidence
    from tests.test_a_scan_is_binding import _open_bound_ask
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap_a = await _prod_snapshot(db)
    snap_b = await append_product_evidence(db, record=dict(
        BAREBELLS_PROD, code="70004200", product_name="Quest Protein Bar",
        brands="Quest", rev=2))
    tid = f"ios:b3-swap-{user.id}"
    await _open_bound_ask(db, user, log, snap_a, monkeypatch, turn_id=tid)   # bound to A
    # the SAME turn id, now with snapshot B attached
    begin_turn(); attach(snap_b.id); SCAN_BINDING.set(ScanBinding("bound", snap_b.id))
    try:
        item = {"food_name": "Quest Protein Bar", "quantity": "2 bar",
                "product_evidence_id": snap_b.id}
        cov = await coverage_for(db, user_id=user.id, items=[item])
        with pytest.raises(BoundAskNotSingular):
            await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                          turn_id=tid, channel="ios", locale="en")
    finally:
        begin_turn()


# ── F2/F3/F4: what the wrapper and try_take_ownership RENDER on reuse ──────

@pytest.mark.asyncio
async def test_b3_the_bound_wrapper_renders_the_stored_interaction_on_reuse(
        db, make_user, monkeypatch):
    """Same turn, same snapshot, retried through the WRAPPER: the CanonicalAsk
    it returns carries the STORED interaction (decoded from the row), not the
    one it just built. Proven by making the rebuilt one DIFFER (a different
    introduction) and asserting the returned wire equals the row, not the
    rebuild."""
    import json as _json
    from core import product_bound_ask as pba
    from core.general_settlement import coverage_for
    from core.product_bound_ask import open_bound_quantity_ask
    from db.models import PendingOperation
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    snap = await _prod_snapshot(db)
    tid = f"ios:b3-wrap-{user.id}"
    item = {"food_name": BAREBELLS_PROD["product_name"], "quantity": "2 bar",
            "product_evidence_id": snap.id}
    begin_turn(); attach(snap.id); SCAN_BINDING.set(ScanBinding("bound", snap.id))
    try:
        cov = await coverage_for(db, user_id=user.id, items=[item])
        first = await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                              turn_id=tid, channel="ios", locale="en")
        await db.commit()
        row = (await db.execute(select(PendingOperation).where(
            PendingOperation.user_id == user.id))).scalars().one()
        stored = _json.loads(row.canonical_payload)["interaction"]
        # now make the wrapper BUILD something different on the retry: a
        # different question text. The fingerprint covers the interaction, so
        # a differing rebuild must NOT be silently reused either — it refuses.
        real_q = pba._question
        monkeypatch.setattr(pba, "_question", lambda **k: "A DIFFERENT QUESTION?")
        from core.product_bound_ask import BoundAskNotSingular
        with pytest.raises(BoundAskNotSingular):
            await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                          turn_id=tid, channel="ios", locale="en")
        monkeypatch.setattr(pba, "_question", real_q)
        # and an IDENTICAL rebuild reuses — returning the STORED wire
        second = await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                               turn_id=tid, channel="ios", locale="en")
    finally:
        begin_turn()
    assert second.operation_id == first.operation_id == row.operation_id
    # the STORED interaction, whole: the semantic payload the row holds is
    # what the retry returned (to_payload is the full shape; wire_payload is
    # the label-only client view)
    assert second.interaction.to_payload() == stored


@pytest.mark.asyncio
async def test_b3_an_absent_stored_snapshot_is_not_a_match(db, make_user, monkeypatch):
    """The persisted item carries NO product_evidence_id (an ordinary B-1 ask
    opened for this turn). A bound retry on the same turn id must REFUSE —
    absence is not a match — both at the pre-read guard and at the post-open
    check."""
    from core.b1_quantity_operation import _operation_id_for, open_operation
    from core.food_pipeline import stage_items
    from core.general_settlement import coverage_for
    from core.product_bound_ask import BoundAskNotSingular, open_bound_quantity_ask
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    snap = await _prod_snapshot(db)
    tid = f"ios:b3-absent-{user.id}"
    op_id = _operation_id_for(user, tid)
    # an ORDINARY ask on this turn — its item has no snapshot
    staged = stage_items({"items": [{"food": "Barebells bar", "amount": 2, "unit": "bar",
                                     "calories": 200}]}, turn_id=tid, message="bar",
                         mode="strict")[0]
    field = qc.quantity_field(operation_id=op_id, revision=0, item=staged)
    inter = qc.build_interaction(operation_id=op_id, revision=0, item=staged,
                                 options=field.options, introduction="How much?",
                                 ask_preparation=False)
    await open_operation(db, user=user, interpreter_item={"food": "Barebells bar",
                                                           "amount": 2, "unit": "bar"},
                         interaction=inter, turn_id=tid, locale="en")
    await db.commit()
    # the bound wrapper on the SAME turn id
    item = {"food_name": BAREBELLS_PROD["product_name"], "quantity": "2 bar",
            "product_evidence_id": snap.id}
    begin_turn(); attach(snap.id); SCAN_BINDING.set(ScanBinding("bound", snap.id))
    try:
        cov = await coverage_for(db, user_id=user.id, items=[item])
        with pytest.raises(BoundAskNotSingular):
            await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                          turn_id=tid, channel="ios", locale="en")
    finally:
        begin_turn()


# ── F2/F3/F4 AT THE BOUNDARY THEY GUARD ─────────────────────────────────────
#
# Under the seam's fingerprint check a reuse is semantically identical to the
# row by construction, so "render stored vs render rebuilt" cannot be told
# apart at any call site, and an absent stored snapshot is refused upstream
# (bound pid != no pid -> different fingerprint). Those guards are defence in
# depth for a seam that returns something other than what it checked; they
# are proven HERE by handing each consumer an OpenResult that differs from the
# local build — the only way to reach them — because a guard that cannot be
# reached must be proven directly or removed, never trusted.

@pytest.mark.asyncio
async def test_f2_try_take_ownership_renders_the_openresult_interaction_not_its_own(
        db, make_user, monkeypatch):
    """Hand `try_take_ownership` a seam that returns an OpenResult carrying a
    DIFFERENT stored interaction. The CanonicalAsk must carry the STORED one
    — the seam's answer — not the interaction it built locally."""
    from core import b1_quantity_operation as b1q
    from core.food_pipeline import derive_semantics, stage_items
    from skills.nutrition import quantity_clarification as qc
    from types import SimpleNamespace as NS
    user = await make_user()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(user.id))
    monkeypatch.setenv("B1_QUANTITY_MODE", "allowlist")
    # a VAGUE quantity, so B-1 has something to ask ("a cup" is stated and
    # declines with quantity_already_stated — correctly)
    data = {"items": [{"food": "Oatmeal", "amount": 1, "unit": "bowl", "calories": 150}]}
    staged, _group = stage_items(data, turn_id="t", message="had some oatmeal",
                                 mode="moderate")
    staged = derive_semantics(staged, data, message="had some oatmeal", mode="moderate")
    material = {"staged_items": tuple(staged), "items": data["items"],
                "message": "had some oatmeal", "identity_evidence": False}
    # the seam returns a STORED interaction that is visibly different
    captured = {}
    async def fake_open(db_, *, user, interpreter_item, interaction, **k):
        captured["built"] = interaction
        # re-serialise the SAME interaction with a different introduction
        # (revision unchanged: field ids derive from it)
        from core.semantics import ClarificationInteraction
        payload = interaction.to_payload()
        payload["introduction"] = "THE STORED QUESTION"
        stored = ClarificationInteraction.from_payload(payload)
        return b1q.OpenResult(operation_id=interaction.operation_id, created=False,
                              interaction=stored, item=dict(interpreter_item),
                              revision=0, fingerprint="stored")
    monkeypatch.setattr(b1q, "open_operation", fake_open)
    ask = await b1q.try_take_ownership(db, user=user, material=material,
                                       turn_id=f"ios:f2-{user.id}", channel="telegram",
                                       locale="en")
    assert ask is not None, "B-1 declined an eligible vague-quantity ask — the render path was not reached"
    assert ask.interaction.introduction == "THE STORED QUESTION"
    assert captured["built"].introduction != "THE STORED QUESTION"


@pytest.mark.asyncio
async def test_f3_the_bound_wrapper_renders_the_openresult_interaction_and_f4_refuses_absence(
        db, make_user, monkeypatch):
    """Same at the wrapper: (F3) a seam returning a different stored
    interaction -> the wrapper renders THAT; (F4) a seam returning an item
    with NO product_evidence_id -> refused, absence is not a match."""
    from core import b1_quantity_operation as b1q
    from core import product_bound_ask as pba
    from core.general_settlement import coverage_for
    from core.product_bound_ask import BoundAskNotSingular, open_bound_quantity_ask
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    snap = await _prod_snapshot(db)
    item = {"food_name": BAREBELLS_PROD["product_name"], "quantity": "2 bar",
            "product_evidence_id": snap.id}

    def _fake(stored_pid):
        async def fake_open(db_, *, user, interpreter_item, interaction, **k):
            # the STORED interaction: the same interaction the wrapper built,
            # re-serialised with a different introduction and revision — so
            # every field/option id stays consistent (the semantics layer
            # refuses an option sitting on a field it does not answer)
            from core.semantics import ClarificationInteraction
            payload = interaction.to_payload()
            payload["introduction"] = "THE STORED BOUND QUESTION"
            # revision stays 0: the semantics layer derives field ids from it
            # and refuses an interaction whose revision disagrees with its
            # fields' — correctly
            stored = ClarificationInteraction.from_payload(payload)
            it = dict(interpreter_item)
            if stored_pid is None:
                it.pop("product_evidence_id", None)
            else:
                it["product_evidence_id"] = stored_pid
            return b1q.OpenResult(operation_id=interaction.operation_id, created=False,
                                  interaction=stored, item=it, revision=0,
                                  fingerprint="stored")
        return fake_open


    begin_turn(); attach(snap.id); SCAN_BINDING.set(ScanBinding("bound", snap.id))
    try:
        cov = await coverage_for(db, user_id=user.id, items=[item])
        # F3: stored interaction wins
        monkeypatch.setattr(b1q, "open_operation", _fake(snap.id))
        ask = await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                            turn_id=f"ios:f3-{user.id}", channel="ios",
                                            locale="en")
        assert ask is not None
        assert ask.interaction.introduction == "THE STORED BOUND QUESTION"
        # F4: absence refuses
        monkeypatch.setattr(b1q, "open_operation", _fake(None))
        with pytest.raises(BoundAskNotSingular):
            await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                          turn_id=f"ios:f4-{user.id}", channel="ios",
                                          locale="en")
        # and a DIFFERENT snapshot refuses too
        monkeypatch.setattr(b1q, "open_operation", _fake(snap.id + 999))
        with pytest.raises(BoundAskNotSingular):
            await open_bound_quantity_ask(db, user=user, item=item, coverage=cov,
                                          turn_id=f"ios:f4b-{user.id}", channel="ios",
                                          locale="en")
    finally:
        begin_turn()


# ── the two proof gaps ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b4_a_hidden_second_subject_also_prevents_the_correction_lift(
        db, make_user, monkeypatch, caplog):
    """The earlier B4 proof never supplied an `update_food_entry`, so it did
    not exercise the CORRECTION lift. Here the plan is the CF5b shape — ONE
    implicit update of a board row — PLUS a hidden held soup. Two subjects:
    the lift must not fire; the update is left exactly as the interpreter
    emitted it (and the executor then refuses the impossible shape or routes
    it unbound, per the authority)."""
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from skills.nutrition.product_acquisition import (SKIPPED_MULTI_ITEM,
                                                      SCAN_BINDING, attach,
                                                      begin_turn)
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    upd = {"name": "update_food_entry",
           "input": {"entry_id": 3030, "quantity": "4 bar",
                     "food_hint": "Barebells Salty Peanut Protein Bar"}}
    held = {"name": "log_food",
            "input": {"food_name": "Mystery soup", "quantity": "1 bowl"}}
    interpreter_out = {"action": "update", "tool_calls": [upd],
                       "deferred_calls": [held], "say": ""}

    async def stub(text, u, **kw):
        return interpreter_out
    req = _Req("2 servings of Barebells bars and some soup",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    begin_turn(); attach(snap.id)
    try:
        raw = await FoodPlanStage(interpreter=stub).run(req)
        assert raw.operations[0]["name"] == "update_food_entry"      # planner blind
        v = await FoodValidationStage().run(req, plan=raw)
        assert SCAN_BINDING.get().kind == SKIPPED_MULTI_ITEM
        assert v.plan.operations[0]["name"] == "update_food_entry"   # NOT lifted
        assert v.plan.operations[0]["input"]["quantity"] == "4 bar"
    finally:
        begin_turn()
    assert "scan_rejects_correction_shape" not in caplog.text

    # and the twin: drop the soup -> BOUND -> the lift fires, post-decision
    interpreter_out["deferred_calls"] = []
    begin_turn(); attach(snap.id)
    try:
        raw = await FoodPlanStage(interpreter=stub).run(req)
        v = await FoodValidationStage().run(req, plan=raw)
        assert v.plan.operations[0]["name"] == "log_food"
        assert v.plan.operations[0]["input"]["quantity"] == "2 serving"
    finally:
        begin_turn()
    assert "scan_rejects_correction_shape" in caplog.text


def test_subject_sources_is_a_gate_not_a_claim():
    """`SUBJECT_SOURCES` says every listed producer key is READ by the
    normaliser. The docstring claimed a gate existed; this is that gate: each
    key must appear as a subscript of `out` (or a `.get(...)` on it) inside
    `food_subjects_of`, so a key added to the tuple without a reader fails
    here."""
    import ast
    import inspect
    from core.turns.stages import food as m
    tree = ast.parse(inspect.getsource(m.food_subjects_of).lstrip())
    # ⚠ ONLY reads whose RECEIVER is `out` — the producer dict. The first
    # version counted every `.get(...)` regardless of receiver (so `it.get(
    # "food")` on an item satisfied it) and hardcoded the same seven names
    # for its converse, so a newly read undeclared producer key passed.
    read = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and n.args
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "out"
                and isinstance(n.args[0], ast.Constant)):
            read.add(n.args[0].value)
        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and isinstance(n.value, ast.Name) and n.value.id == "out"):
            read.add(n.slice.value)
    missing = [k for k in m.SUBJECT_SOURCES if k not in read]
    assert not missing, f"SUBJECT_SOURCES names keys the normaliser never reads: {missing}"
    # the converse, DERIVED from the code: every producer key read off `out`
    # must be declared, except the turn-context keys that are not food
    # sources. A new `out.get("<x>")` in the normaliser fails here until it
    # is declared — which is the contract change being made explicit.
    context_keys = {"_message", "_thread_active", "action", "say", "kind"}
    undeclared = sorted(k for k in read
                        if isinstance(k, str) and not k.startswith("_")
                        and k not in set(m.SUBJECT_SOURCES) and k not in context_keys)
    assert not undeclared, (
        f"the normaliser reads producer keys not declared in SUBJECT_SOURCES: "
        f"{undeclared}")


# ═════ REQUIRED RACE PROOF — same op id, snapshots A and B, concurrently ════

@pytest.mark.asyncio
@pytest.mark.skipif(not __import__("os").getenv("TEST_POSTGRES_URL"),
                    reason="the post-read race needs two real connections")
async def test_race_same_operation_id_with_snapshots_a_and_b_one_owns_the_row(monkeypatch):
    """Two workers, the SAME turn id (so the same operation id), one bound to
    snapshot A and one to snapshot B, submitted at once. Exactly ONE snapshot
    owns the row; its returned wire equals the stored wire BYTE FOR BYTE; the
    other request REFUSES (OpenedElsewhere -> BoundAskNotSingular) — it does
    not get the winner's ask rendered as its own, and it does not get its own
    rendered over the winner's row. This is the post-read race that the
    operation-id check alone cannot catch; the fingerprint can."""
    import asyncio
    import json as _json
    import os
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from db.database import make_engine
    from db.models import Base, PendingOperation, User, UserPreferences
    from skills.nutrition.product_store import append_product_evidence

    engine = make_engine(os.environ["TEST_POSTGRES_URL"], pool_size=5, max_overflow=5)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            u = User(telegram_id="cf5c-ab", onboarding_completed=True)
            s.add(u); await s.flush()
            s.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
            snap_a = await append_product_evidence(s, record=dict(BAREBELLS_PROD))
            snap_b = await append_product_evidence(s, record=dict(
                BAREBELLS_PROD, code="70004200", product_name="Quest Protein Bar",
                brands="Quest", rev=2))
            await s.commit()
            uid, a_id, b_id = u.id, snap_a.id, snap_b.id
        monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(uid))
        TURN = "ios:race-AB"

        async def one(snapshot_id, food):
            from core.general_settlement import coverage_for
            from core.product_bound_ask import BoundAskNotSingular, open_bound_quantity_ask
            from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                              attach, begin_turn)
            async with factory() as s:
                user = await s.get(User, uid)
                begin_turn(); attach(snapshot_id)
                SCAN_BINDING.set(ScanBinding("bound", snapshot_id))
                item = {"food_name": food, "quantity": "2 bar",
                        "product_evidence_id": snapshot_id}
                cov = await coverage_for(s, user_id=uid, items=[item])
                try:
                    ask = await open_bound_quantity_ask(
                        s, user=user, item=item, coverage=cov, turn_id=TURN,
                        channel="ios", locale="en")
                    await s.commit()
                    return ("ask", snapshot_id, ask)
                except BoundAskNotSingular as exc:
                    await s.rollback()
                    return ("refused", snapshot_id, str(exc))
                finally:
                    begin_turn()

        results = await asyncio.gather(
            one(a_id, BAREBELLS_PROD["product_name"]), one(b_id, "Quest Protein Bar"),
            return_exceptions=True)
        for r in results:
            assert not isinstance(r, Exception), r

        async with factory() as s:
            rows = (await s.execute(select(PendingOperation).where(
                PendingOperation.user_id == uid))).scalars().all()
        assert len(rows) == 1, [(r.operation_id, r.status) for r in rows]
        row = rows[0]
        stored = _json.loads(row.canonical_payload)
        stored_pid = int(stored["item"]["product_evidence_id"])
        stored_wire_bytes = _json.dumps(stored["interaction"], sort_keys=True,
                                        separators=(",", ":")).encode()

        asks = [r for r in results if r[0] == "ask"]
        refusals = [r for r in results if r[0] == "refused"]
        # the post-read race can resolve two ways, both correct:
        #   (i) one wins, one refuses; or (ii) both "win" in sequence — the
        #   second SUPERSEDED the first (different turn? no — same turn id,
        #   so it cannot: same id means reuse-or-refuse, never supersede).
        # So: exactly one ask, exactly one refusal.
        assert len(asks) == 1 and len(refusals) == 1, results
        kind, winner_pid, ask = asks[0]
        assert winner_pid == stored_pid, (winner_pid, stored_pid)
        returned_wire_bytes = _json.dumps(ask.interaction.to_payload(), sort_keys=True,
                                          separators=(",", ":")).encode()
        assert returned_wire_bytes == stored_wire_bytes      # byte for byte
        assert ask.operation_id == row.operation_id
        _, loser_pid, reason = refusals[0]
        assert loser_pid != stored_pid
        assert "DIFFERENT semantic payload" in reason or "another ask owns" in reason, reason
    finally:
        await engine.dispose()


# ═════ Danny's three pre-deploy details, as gates ═══════════════════════════

def test_fp_is_canonical_versioned_and_fails_closed():
    """(1) canonical: key order and whitespace do not change it; versioned:
    the prefix names the rule; fail-closed: a non-serialisable payload raises
    FingerprintUnreadable rather than str()-ing into a match."""
    from core.b1_quantity_operation import (FINGERPRINT_VERSION, FingerprintUnreadable,
                                            semantic_fingerprint)
    from core.semantics import ClarificationInteraction
    from skills.nutrition import quantity_clarification as qc
    from core.food_pipeline import stage_items
    items, _g = stage_items({"items": [{"food": "Oatmeal", "amount": 1, "unit": "bowl",
                                        "calories": 150}]}, turn_id="t", message="x",
                            mode="strict")
    field = qc.quantity_field(operation_id="chat_quantity:1:t", revision=0, item=items[0])
    inter = qc.build_interaction(operation_id="chat_quantity:1:t", revision=0,
                                 item=items[0], options=field.options,
                                 introduction="How much?", ask_preparation=False)
    a = semantic_fingerprint(inter, {"food": "Oatmeal", "amount": 1, "unit": "bowl"})
    b = semantic_fingerprint(inter, {"unit": "bowl", "amount": 1, "food": "Oatmeal"})
    assert a == b and a.startswith(FINGERPRINT_VERSION + ":")
    # round-trip through JSON (what the row holds) is identical
    again = ClarificationInteraction.from_payload(inter.to_payload())
    assert semantic_fingerprint(again, {"food": "Oatmeal", "amount": 1, "unit": "bowl"}) == a
    # a different snapshot is a different fingerprint
    assert (semantic_fingerprint(inter, {"food": "Oatmeal", "product_evidence_id": 1})
            != semantic_fingerprint(inter, {"food": "Oatmeal", "product_evidence_id": 2}))
    # fail closed
    with pytest.raises(FingerprintUnreadable):
        semantic_fingerprint(inter, {"food": "Oatmeal", "nan": float("nan")})
    with pytest.raises(FingerprintUnreadable):
        semantic_fingerprint(inter, {"food": "Oatmeal", "obj": object()})


@pytest.mark.asyncio
async def test_reuse_verifies_row_ownership_user_domain_turn(db, make_user):
    """(1b) a row reached by operation id is still checked against the
    request's user, domain and turn before anything in it is rendered."""
    from core.b1_quantity_operation import (OpenedElsewhere, _operation_id_for,
                                            _stored_open_result, open_operation)
    from core.food_pipeline import stage_items
    from db.models import PendingOperation
    from skills.nutrition import quantity_clarification as qc
    from sqlalchemy import select
    user = await make_user()
    tid = f"ios:own-{user.id}"
    op_id = _operation_id_for(user, tid)
    items, _g = stage_items({"items": [{"food": "Oatmeal", "amount": 1, "unit": "bowl",
                                        "calories": 150}]}, turn_id=tid, message="x",
                            mode="strict")
    field = qc.quantity_field(operation_id=op_id, revision=0, item=items[0])
    inter = qc.build_interaction(operation_id=op_id, revision=0, item=items[0],
                                 options=field.options, introduction="How much?",
                                 ask_preparation=False)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, locale="en", cohort="allowlist")
    await db.commit()
    row = (await db.execute(select(PendingOperation).where(
        PendingOperation.operation_id == op_id))).scalars().one()
    ok = _stored_open_result(row, created=False, expect_user_id=user.id, expect_turn_id=tid)
    assert ok.locale == "en" and ok.cohort == "allowlist"        # (2) rendering facts
    with pytest.raises(OpenedElsewhere, match="belongs to user"):
        _stored_open_result(row, created=False, expect_user_id=user.id + 99, expect_turn_id=tid)
    with pytest.raises(OpenedElsewhere, match="opened on turn"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id="ios:someone-elses-turn")


@pytest.mark.asyncio
async def test_an_unreadable_stored_payload_refuses_not_reuses(db, make_user, monkeypatch):
    """(1c) the stored payload cannot be decoded -> FingerprintUnreadable, a
    refusal at both consumers, never a partial reuse."""
    from core.b1_quantity_operation import (FingerprintUnreadable, _operation_id_for,
                                            open_operation)
    from core.food_pipeline import stage_items
    from db.models import PendingOperation
    from skills.nutrition import quantity_clarification as qc
    from sqlalchemy import select, update
    user = await make_user()
    tid = f"ios:unread-{user.id}"
    op_id = _operation_id_for(user, tid)
    items, _g = stage_items({"items": [{"food": "Oatmeal", "amount": 1, "unit": "bowl",
                                        "calories": 150}]}, turn_id=tid, message="x",
                            mode="strict")
    field = qc.quantity_field(operation_id=op_id, revision=0, item=items[0])
    inter = qc.build_interaction(operation_id=op_id, revision=0, item=items[0],
                                 options=field.options, introduction="How much?",
                                 ask_preparation=False)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, locale="en")
    await db.commit()
    await db.execute(update(PendingOperation).where(
        PendingOperation.operation_id == op_id).values(canonical_payload="{not json"))
    await db.commit()
    with pytest.raises(FingerprintUnreadable):
        await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                             interaction=inter, turn_id=tid, locale="en")


@pytest.mark.asyncio
async def test_a_reused_ask_renders_entirely_from_persisted_state(db, make_user, monkeypatch):
    """(2) locale and cohort on a reuse come from the ROW, not the retry: open
    with locale=ru cohort=allowlist, retry with locale=en cohort=scan_bound ->
    the CanonicalAsk carries ru / allowlist."""
    from core import b1_quantity_operation as b1q
    from core.food_pipeline import stage_items
    from skills.nutrition import quantity_clarification as qc
    user = await make_user()
    tid = f"ios:persist-{user.id}"
    op_id = b1q._operation_id_for(user, tid)
    items, _g = stage_items({"items": [{"food": "Oatmeal", "amount": 1, "unit": "bowl",
                                        "calories": 150}]}, turn_id=tid, message="x",
                            mode="strict")
    field = qc.quantity_field(operation_id=op_id, revision=0, item=items[0])
    inter = qc.build_interaction(operation_id=op_id, revision=0, item=items[0],
                                 options=field.options, introduction="How much?",
                                 ask_preparation=False)
    first = await b1q.open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                                     interaction=inter, turn_id=tid, locale="ru",
                                     cohort="allowlist")
    await db.commit()
    assert first.created and first.locale == "ru" and first.cohort == "allowlist"
    again = await b1q.open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                                     interaction=inter, turn_id=tid, locale="en",
                                     cohort="scan_bound")
    assert again.reused
    assert again.locale == "ru" and again.cohort == "allowlist", (again.locale, again.cohort)


# ═════ PRODUCTION 2026-08-19 13:40 — a scanned empty-plan turn must NOT delegate ═
#
# The direct P17g canary's first send: product_acquired snapshot=1, the
# interpreter raised RateLimitError, NO plan, the authority ruled UNDECIDABLE
# (foods=0) — and `run_turn`'s `native_no_plan` block handed the SCANNED turn
# to legacy, because `require_shape` lives in NativeExecutionStage.run which
# a disposition="pass" never reaches. Legacy also rate-limited so nothing was
# written; had it not, the scanned product would have been re-interpreted as
# prose without its snapshot. The same escape one layer up.

def _tail_state(error=None, execution=None, response=None, request=None):
    import types
    return types.SimpleNamespace(
        error=error, execution=execution, response=response,
        request=request, health_flags=(), snapshot=None, phase=None,
        route=None, plan=None, validation=None, context=None)


def _tail_request(turn_id="ios:RL-1"):
    from core.turns.models import TurnRequest
    return TurnRequest(turn_id=turn_id, user_id=26, platform="ios",
                       source_type="ios", text="2 servings of Barebells", metadata={})


async def _run_tail(monkeypatch, state, legacy_spy):
    import types
    import core.turns.factory as F
    from core.turns.stages import execute as E

    class _Coordinator:
        route_stage = types.SimpleNamespace(decision=None)
        async def run(self, request):
            return state
    async def _build(request, **kwargs):
        return _Coordinator()
    monkeypatch.setattr(F, "build_coordinator", _build)
    monkeypatch.setattr(E, "LegacyExecutionStage", legacy_spy)
    from core.turns.entrypoint import run_turn
    return await run_turn(request=state.request)


class _LegacySpy:
    calls = []
    def __init__(self, **kwargs):
        _LegacySpy.calls.append(kwargs)
    async def run(self, request):
        return None


@pytest.mark.asyncio
async def test_prod_0819_a_scanned_turn_with_no_plan_refuses_in_words_and_never_delegates(
        monkeypatch, caplog):
    """scan attached + UNDECIDABLE (no plan, the model failed) -> a typed
    refusal answered in words; LegacyExecutionStage is NEVER constructed."""
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    caplog.set_level(logging.INFO)
    _LegacySpy.calls.clear()
    req = _tail_request()
    begin_turn(); attach(1)
    SCAN_BINDING.set(ScanBinding("undecidable", 1))      # what the gate recorded
    try:
        result = await _run_tail(monkeypatch, _tail_state(request=req), _LegacySpy)
    finally:
        begin_turn()
    bubbles = list(getattr(result.response, "bubbles", None) or [])
    assert bubbles and any(b.strip() for b in bubbles), result
    text = " ".join(bubbles).lower()
    assert "scanned product" in text, text
    assert "wires crossed" not in text and "lost the thread" not in text
    assert _LegacySpy.calls == [], "a scanned turn was delegated to legacy"
    assert "scan_refuses_delegation" in caplog.text
    assert "native_no_plan" not in caplog.text


@pytest.mark.asyncio
async def test_prod_0819_a_scanned_BOUND_turn_with_no_plan_also_refuses(monkeypatch, caplog):
    """Even if the gate had said BOUND, an empty plan at this seam refuses —
    the zero-op CF9 branch lives in the execution stage, which never ran."""
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    caplog.set_level(logging.INFO)
    _LegacySpy.calls.clear()
    req = _tail_request("ios:RL-2")
    begin_turn(); attach(1)
    SCAN_BINDING.set(ScanBinding("bound", 1))
    try:
        result = await _run_tail(monkeypatch, _tail_state(request=req), _LegacySpy)
    finally:
        begin_turn()
    assert list(getattr(result.response, "bubbles", None) or [])
    assert _LegacySpy.calls == []
    assert "scan_refuses_delegation" in caplog.text


@pytest.mark.asyncio
async def test_prod_0819_an_unscanned_empty_turn_still_delegates(monkeypatch, caplog):
    """The twin: no scan -> `native_no_plan` delegation exactly as before."""
    from skills.nutrition.product_acquisition import begin_turn
    caplog.set_level(logging.INFO)
    _LegacySpy.calls.clear()
    begin_turn()
    req = _tail_request("ios:RL-3")
    await _run_tail(monkeypatch, _tail_state(request=req), _LegacySpy)
    assert len(_LegacySpy.calls) == 1
    assert "native_no_plan" in caplog.text
    assert "scan_refuses_delegation" not in caplog.text


def test_prod_0819_the_entrypoint_consults_the_authority_before_delegating():
    """AST: in run_turn, `scan_attached` / `require_shape` are called BEFORE
    the LegacyExecutionStage import in the no-plan block."""
    import ast
    import inspect
    from core.turns import entrypoint as ep
    tree = ast.parse(inspect.getsource(ep.run_turn).lstrip())
    consult = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "id", None) in ("scan_attached", "require_shape")]
    legacy = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
              and any(a.name == "LegacyExecutionStage" for a in n.names)]
    assert consult and legacy and min(consult) < min(legacy), (
        "the no-plan block can delegate a scanned turn before asking the authority")
