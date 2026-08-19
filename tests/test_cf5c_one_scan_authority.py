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
        # legacy fixture shape {"items": [...], "ambiguities": [...]} — kept
        # readable for tests that still use it, but the SUBJECTS come from the
        # dict's own keys via the normaliser, never from a max() over views
        if isinstance(amb, dict):
            out.setdefault("items", []).extend(amb.get("items") or [])
            out.setdefault("ambiguities", []).extend(amb.get("ambiguities") or [])
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
        deferred_calls=[],
        b1_material={"staged_items": (), "items": [
            {"food": "Barebells Salty Peanut Protein Bar", "amount": None,
             "unit": ""}]})
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
        deferred_calls=[],
        b1_material={"staged_items": (), "items": [{"food": "Barebells"}]})
    plan = _Plan([], intent="ask", **live)
    assert plan.open_fields == ("unknown",)
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
    out, plan = await _live_plan(monkeypatch, "alpha and bravo", {
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
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

    out, plan = await _live_plan(monkeypatch, "barebells", {
        "action": "ask",
        "points": [{"label": "Barebells Salty Peanut Protein Bar",
                    "qs": ["how much did you have?"]}],
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
    assert plan.open_fields == ("quantity",)


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
        "ambiguities": [{"field": "quantity"}]})                  # 7 amb
    assert len(plan.food_subjects) == 1, plan.food_subjects
    sub = plan.food_subjects[0]
    assert sub.key == "op:ready:0"                 # anchored on the occurrence
    assert sub.open_fields == ("quantity",)


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
    # not to a third subject
    assert all("quantity" in s.open_fields for s in plan.food_subjects)
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
    assert plan.open_fields == ("quantity",)
