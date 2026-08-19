"""⛔⛔ CF5b — SCAN BINDING MUST DOMINATE CORRECTION CLAIMS *(Danny, 2026-08-18)*.

    A scan-bound turn cannot be claimed by implicit correction, ratio
    correction or legacy mutation before the bound predicate runs.

THE PRODUCTION INCIDENT (P1 authority violation, turn ios:D3B7757E, 21:01):

    scan acquired exact snapshot           product_acquired code=70004199 snapshot=1
    -> correction route discarded binding  interpreter: update_food_entry(3030, "4 bar")
    -> heuristic ratio mutation committed  correction_apply route=ratio ratio=2.000 cal=800.0
    -> bound predicate never ran           (no settlement_route line)

Row 3030 was a LEGACY Barebells row (2 bar / 400 kcal) already on the board.
The user scanned 70004199 and typed "2 servings of Barebells bars". Every
scan-binding check downstream keyed on `log_food`; the update op fell through
the native stage to the legacy executor's ratio arm. CF4 (exact product x
heuristic mass) and CF5 (bound turn -> legacy) broken in one turn.

REQUIRED ARCHITECTURE, at the correction-claim boundary:

    if turn carries SCANNED_PRODUCT_EVIDENCE:
        implicit correction eligibility = false
        ratio correction eligibility = false
        preserve snapshot
        continue through fresh bound-item planning

A scan attachment means a NEW exact-product report. It must not mutate an old
row merely because that product already appears on the board. Defence in
depth inside correction execution: a scan-bound turn reaching correction
application is a typed invariant failure — zero mutation, snapshot never
silently discarded. The executor guard is not the primary router; it prevents
another 800-calorie commit if upstream classification regresses.

PREREGISTERED PROOF (verbatim):

    EXISTING  row 3030 = Barebells, 400 calories
    TURN      scan 70004199 -> "2 servings of Barebells"
    REQUIRE   row 3030 byte-identical
              zero correction event
              zero ratio route
              settlement_route = Supported
              new row committed
              product_evidence_id = acquired snapshot
              resolved quantity = 110 g
              calories ~ 220
              pricing_rung = product
              zero MEMORY
              zero legacy

MUTATION TWINS:
    * remove scan exclusion from correction claim         -> RED
    * remove executor invariant -> adversarial misroute    commits nothing
    * same food already on board must not change the result
    * scan + unsupported "2 bars" -> BoundUnpriceable + CF9 ASK, not correction

Do not weaken ratio correction globally: implicit correction cannot outrank
explicit scan binding — that is the whole exclusion.
"""
from __future__ import annotations

import datetime as dt
import logging

import pytest

from tests.test_a_scan_is_binding import (BAREBELLS_PROD, _Req, _log,
                                          _prod_snapshot)


# ── the board: a LEGACY Barebells row, exactly the production shape ──────────

async def _legacy_barebells_row(db, log, *, calories=400.0, quantity="2 bar"):
    """Row 3030 as production had it: a legacy write, no pricing rung, no
    snapshot — the interpreter's own numbers. Its `created` ledger event
    names a LEGACY writer, so `_correction_route` declines it (not
    canonically owned) and the op would fall to the legacy executor."""
    from db.models import FoodEntry, LedgerEvent
    row = FoodEntry(daily_log_id=log.id, raw_input="2 barebells bars",
                    parsed_food_name="Barebells Salty Peanut Protein Bar",
                    quantity=quantity, calories=calories, protein=40.0,
                    carbs=40.0, fats=14.0, estimated_flag=True,
                    confidence_score=0.65, source_type="text")
    db.add(row)
    await db.flush()
    db.add(LedgerEvent(user_id=log.user_id, domain="food", event_type="created",
                       entry_id=row.id, source="structured_food:food_interpreter_v2",
                       turn_id="ios:legacy-3030", payload_json="{}"))
    await db.commit()
    return row.id


async def _row_bytes(db, entry_id):
    from db.models import FoodEntry
    from sqlalchemy import select
    t = FoodEntry.__table__
    r = (await db.execute(select(t).where(t.c.id == entry_id))).mappings().one()
    return dict(r)


def _the_misrouted_plan(entry_id: int,
                        food_hint: str = "Barebells Salty Peanut Protein Bar") -> list:
    """What the interpreter emitted on the production turn: ONE implicit
    correction of the board row, carrying the corrected TOTAL ("4 bar"), the
    row's name as `food_hint`, and the CAS seed — `_update_call`'s exact
    shape."""
    return [{"name": "update_food_entry",
             "input": {"entry_id": entry_id, "quantity": "4 bar",
                       "expected_calories": 400.0,
                       "food_hint": food_hint,
                       "source": "food_interpreter_v2"}}]


async def _run(db, user, log, text, snapshot_id, plan, monkeypatch, *,
               forbid_legacy=True, turn_id="t:cf5b"):
    """The native chain with the interpreter stubbed to the MISROUTED plan
    (action="update"), the scan bound through the SAME contextvar
    api/chat.py sets, the legacy executor instrumented to fail if invoked.
    Returns (plan, execution, response) — the plan too, so the lift is
    observable."""
    import handlers.tool_executor as te
    from core.turns.stages.execute_native import NativeExecutionStage
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from core.turns.stages.render_native import NativeRenderStage
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE

    if forbid_legacy:
        async def forbidden(*a, **k):
            raise AssertionError("legacy executor invoked for a scan-bound turn")
        monkeypatch.setattr(te, "execute_tool_calls", forbidden)

    async def stub(text, u, **kw):
        return {"action": "update", "say": "", "tool_calls": plan}

    req = _Req(text, {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"{turn_id}-{user.id}")
    token = SCANNED_PRODUCT_EVIDENCE.set(snapshot_id)
    try:
        typed = await FoodPlanStage(interpreter=stub).run(req)
        validation = await FoodValidationStage().run(req, plan=typed)
        assert validation.disposition == "execute", validation
        execution = await NativeExecutionStage().run(req, validation=validation)
        snapshot = await CommittedSnapshotStage().run(req, execution=execution)
        response = await NativeRenderStage().run(req, plan=typed, validation=validation,
                                                 snapshot=snapshot)
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    return typed, execution, response


async def _events(db, user_id):
    from db.models import LedgerEvent
    from sqlalchemy import select
    return (await db.execute(select(LedgerEvent).where(
        LedgerEvent.user_id == user_id, LedgerEvent.domain == "food")
        .order_by(LedgerEvent.id))).scalars().all()


# ═════ THE PREREGISTERED PROOF ═══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cf5b_a_scan_bound_implicit_correction_becomes_a_fresh_bound_row(
        db, make_user, monkeypatch, caplog):
    """The production turn, replayed against the fix, every REQUIRE line."""
    from db.models import FoodEntry
    from sqlalchemy import select
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)                       # 70004199 as prod acquired it
    existing = await _legacy_barebells_row(db, log)      # row "3030"
    before = await _row_bytes(db, existing)
    events_before = len(await _events(db, user.id))

    typed, execution, response = await _run(
        db, user, log, "2 servings of Barebells bars", snap.id,
        _the_misrouted_plan(existing), monkeypatch)

    # the LIFT: the plan the executor saw is a log of the scanned product in
    # the USER'S words — never the planner's "4 bar" total
    assert len(typed.operations) == 1
    op = typed.operations[0]
    assert op["name"] == "log_food", op
    assert op["input"]["quantity"] == "2 serving", op       # from the message
    assert "entry_id" not in op["input"], "the existing row target was not discarded"
    assert "scan_rejects_correction_shape" in caplog.text

    # row 3030 byte-identical
    assert await _row_bytes(db, existing) == before
    # zero correction event, zero ratio route
    after = await _events(db, user.id)
    assert [e for e in after if e.event_type == "updated"] == []
    assert "route=ratio" not in caplog.text and "correction_apply" not in caplog.text
    # settlement_route = Supported
    assert "settlement_route" in caplog.text and "decision=Supported" in caplog.text
    # new row committed, bound to the acquired snapshot, from the label
    assert execution is not None and execution.calls[0].committed
    rows = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id)
                             .order_by(FoodEntry.id))).scalars().all()
    assert [r.id for r in rows][0] == existing and len(rows) == 2
    new = rows[-1]
    assert new.product_evidence_id == snap.id
    assert new.resolved_grams == pytest.approx(110.0)
    assert new.calories == pytest.approx(220.0)
    assert new.pricing_rung == "product"
    # identity from the exact scanned SNAPSHOT — its own product_name, not
    # the board row's "Barebells Salty Peanut Protein Bar" the interpreter
    # had picked to mutate. Asserted EXACTLY: a startswith("barebell") here
    # was satisfied by the placeholder and hid a copy that dropped the name.
    assert "scan_lift_named_from_snapshot" in caplog.text
    assert new.parsed_food_name == BAREBELLS_PROD["product_name"], new.parsed_food_name
    assert new.parsed_food_name != "Barebells Salty Peanut Protein Bar"
    # zero MEMORY, zero legacy
    assert "pricing.memory" not in caplog.text and "rung=memory" not in caplog.text
    assert [e for e in after if e.event_type == "created" and
            str(e.source or "").startswith("canonical")], "the new row is a canonical write"
    assert len(after) == events_before + 1
    # and the user is told
    assert response is not None and "".join(response.bubbles).strip()


# ═════ MUTATION TWINS ════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_twin_removing_the_scan_exclusion_from_the_correction_claim_is_red(
        db, make_user, monkeypatch, caplog):
    """MUTATION 1: with the lift disabled, the SAME turn is a correction
    again — and the executor backstop must catch it (nothing written) or
    the proof above is vacuous. Two things asserted: (a) the lift is what
    makes the plan a log (mutating it away changes the plan), (b) the
    backstop is what stops the mutation (nothing committed, legacy never
    reached). Both RED without their code."""
    from core.turns.stages import food as food_mod
    from core.turns.stages.execute_native import ScanBoundNotLegacy
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    existing = await _legacy_barebells_row(db, log)
    before = await _row_bytes(db, existing)

    # (a) remove the scan exclusion at the claim boundary
    monkeypatch.setattr(food_mod, "_lift_bound_correction_to_log",
                        lambda ops, message: None)
    with pytest.raises(ScanBoundNotLegacy):
        await _run(db, user, log, "2 servings of Barebells bars", snap.id,
                   _the_misrouted_plan(existing), monkeypatch)
    # (b) and NOTHING moved: no ratio, no legacy, row untouched
    assert await _row_bytes(db, existing) == before
    assert "route=ratio" not in caplog.text
    assert [e for e in await _events(db, user.id) if e.event_type == "updated"] == []


@pytest.mark.asyncio
async def test_twin_removing_the_executor_invariant_an_adversarial_misroute_commits_nothing(
        db, make_user, monkeypatch, caplog):
    """MUTATION 2: the lift is bypassed AND the native backstop is removed.
    The last line of defence is `correction_application` itself: a
    scan-bound turn reaching it is a typed invariant failure with zero
    mutation. Driven straight at the module — the shape the legacy
    executor's portion arm calls."""
    from skills.nutrition import correction_application as ca
    from skills.nutrition.product_acquisition import (SCAN_BINDING,
                                                      SCANNED_PRODUCT_EVIDENCE,
                                                      ScanBinding)
    caplog.set_level(logging.INFO)
    snap = await _prod_snapshot(db)
    committed = {"calories": 400.0, "protein": 40.0, "carbs": 40.0, "fats": 14.0}
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    binding = SCAN_BINDING.set(ScanBinding("bound", snap.id))
    try:
        for arm, kw in (
            (ca.apply_portion, {}),
            (ca.apply_count_correction, {}),
            (ca.apply_serving_count_correction, {"serving_text": "1 bar (55 g)"}),
        ):
            with pytest.raises(ca.ScanBoundCorrectionRefused) as ei:
                arm(food_name="Barebells Salty Peanut Protein Bar",
                    old_quantity="2 bar", new_quantity="4 bar",
                    committed=committed, **kw)
            assert ei.value.snapshot_id == snap.id       # the snapshot is NAMED, never silently dropped
        assert "route=ratio" not in caplog.text
        assert "reason=scan_bound" in caplog.text
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
        SCAN_BINDING.reset(binding)
    # UNBOUND, the same arithmetic still applies — ratio correction is not
    # weakened globally
    scaled = ca.apply_portion(food_name="Barebells Salty Peanut Protein Bar",
                              old_quantity="110 g", new_quantity="220 g",
                              committed=committed)
    assert scaled and scaled["calories"] == pytest.approx(800.0)


@pytest.mark.asyncio
async def test_twin_the_same_food_already_on_the_board_does_not_change_the_result(
        db, make_user, monkeypatch, caplog):
    """MUTATION 3: the board is the variable. With NO prior Barebells row the
    interpreter emits a log; with one it emitted a correction. Both must
    settle to the SAME bound row — the board must not change what a scan
    means."""
    from db.models import FoodEntry
    from sqlalchemy import select
    from tests.test_a_scan_is_binding import _native
    caplog.set_level(logging.INFO)

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    snap = await _prod_snapshot(db)

    log = await _log(db, user)

    # empty board: the ordinary bound log
    ops = [{"name": "log_food", "input": {"food_name": "Barebells Salty Peanut Protein Bar",
                                          "quantity": "2 serving", "calories": 400.0}}]
    await _native(db, user, log, "2 servings of Barebells bars", snap.id, ops,
                  monkeypatch, turn_id="t:cf5b-empty")
    r1 = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id)
                           .order_by(FoodEntry.id.desc()))).scalars().first()
    assert r1 is not None and r1.pricing_rung == "product"

    # occupied board (r1 AND a legacy Barebells row): the misrouted correction,
    # lifted. A DIFFERENT message on purpose — A12 dedupes an identical one
    # inside the hour as the same meal (general_duplicate), which is not the
    # question here; the question is whether the BOARD changes the answer.
    existing = await _legacy_barebells_row(db, log)
    _, ex2, _ = await _run(db, user, log, "had 2 servings of the Barebells", snap.id,
                           _the_misrouted_plan(existing), monkeypatch, turn_id="t:cf5b-busy")
    r2 = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id)
                           .order_by(FoodEntry.id.desc()))).scalars().first()
    assert r2.id not in (existing, r1.id)

    for a, b in ((r1.product_evidence_id, r2.product_evidence_id),
                 (r1.pricing_rung, r2.pricing_rung),
                 (r1.resolved_grams, r2.resolved_grams),
                 (r1.calories, r2.calories),
                 (r1.quantity, r2.quantity)):
        assert a == b, (a, b)
    assert r2.pricing_rung == "product" and r2.calories == pytest.approx(220.0)


@pytest.mark.asyncio
async def test_twin_scan_plus_unsupported_two_bars_reaches_the_cf9_ask_not_a_correction(
        db, make_user, monkeypatch, caplog):
    """MUTATION 4: the two-turn shape under a busy board. "2 Barebells bars"
    (no label unit) with a Barebells row already on the board: the
    interpreter's implicit correction is lifted, the bound predicate says
    BoundUnpriceable, and the CF9 ask opens HOLDING the snapshot — no
    correction, no ratio, nothing written, row untouched."""
    from db.models import FoodEntry, PendingOperation
    from sqlalchemy import select
    import json
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    existing = await _legacy_barebells_row(db, log)
    before = await _row_bytes(db, existing)

    typed, execution, response = await _run(
        db, user, log, "2 Barebells bars", snap.id,
        _the_misrouted_plan(existing), monkeypatch, turn_id="t:cf5b-ask")

    assert typed.operations[0]["name"] == "log_food"
    assert typed.operations[0]["input"]["quantity"] == "2 bar"      # the user's noun, unpriced
    assert not execution.calls[0].committed
    assert execution.calls[0].correction["refusal"] == "scan_bound_ask"
    assert "decision=BoundUnpriceable" in caplog.text
    assert "route=ratio" not in caplog.text and "correction_apply" not in caplog.text
    assert await _row_bytes(db, existing) == before
    rows = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id))).scalars().all()
    assert [r.id for r in rows] == [existing]
    op = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().one()
    payload = json.loads(op.canonical_payload)
    item = (payload.get("interaction") or {}).get("item") or payload.get("item") or {}
    assert int(item.get("product_evidence_id") or 0) == snap.id, payload
    text = " ".join(response.bubbles)
    assert "55 g serving" in text and "how much did you have" in text, text


# ═════ REVIEW P1 — SNAPSHOT IDENTITY IS AUTHORITATIVE FOR A LIFTED ITEM ═════
#
# The lifted item's placeholder name is the BOARD ROW'S — another product's
# identity. If the snapshot's name were "enrichment", an unreadable snapshot
# would commit one product's NAME over another snapshot's NUTRITION. It is
# authoritative: load + usable name, or a typed refusal with zero write.

@pytest.mark.asyncio
async def test_p1_a_different_board_row_product_commits_exactly_the_snapshot_name(
        db, make_user, monkeypatch, caplog):
    """ADVERSARIAL: the interpreter misreads a Barebells scan as a correction
    of a QUEST row. The committed row must be named EXACTLY the Barebells
    snapshot's product — never "Quest" over Barebells nutrition."""
    from db.models import FoodEntry
    from sqlalchemy import select
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)                                  # Barebells
    quest = await _legacy_barebells_row(db, log)                     # a row...
    from db.models import FoodEntry as _FE
    r = await db.get(_FE, quest); r.parsed_food_name = "Quest Protein Bar"; await db.commit()
    before = await _row_bytes(db, quest)

    _, execution, _ = await _run(db, user, log, "2 servings of the bar", snap.id,
                                 _the_misrouted_plan(quest, food_hint="Quest Protein Bar"),
                                 monkeypatch, turn_id="t:p1-quest")
    assert execution.calls[0].committed
    rows = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id)
                             .order_by(FoodEntry.id))).scalars().all()
    new = rows[-1]
    assert new.id != quest and await _row_bytes(db, quest) == before
    assert new.parsed_food_name == BAREBELLS_PROD["product_name"], new.parsed_food_name
    assert "quest" not in new.parsed_food_name.lower()
    assert new.product_evidence_id == snap.id and new.calories == pytest.approx(220.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "nameless", "unreadable"])
async def test_p1_an_unavailable_snapshot_identity_refuses_with_zero_write_and_no_legacy(
        db, make_user, monkeypatch, caplog, failure):
    """Snapshot missing / nameless / unreadable -> ScanBoundIdentityUnavailable,
    raised before the predicate: zero rows, zero events, legacy never invoked,
    the board row byte-identical."""
    from db.models import FoodEntry, ProductEvidenceRecord
    from sqlalchemy import select
    from core.turns.stages import execute_native as stage_mod
    from core.turns.stages.execute_native import ScanBoundIdentityUnavailable
    caplog.set_level(logging.INFO)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    existing = await _legacy_barebells_row(db, log)
    before = await _row_bytes(db, existing)
    events_before = len(await _events(db, user.id))
    snapshot_id = snap.id
    if failure == "missing":
        snapshot_id = 999_999
    elif failure == "nameless":
        row = await db.get(ProductEvidenceRecord, snap.id)
        row.product_name = ""; await db.commit()
    elif failure == "unreadable":
        # `_name_from_snapshot` is the only reader of the record on this path;
        # break the read the way a dead connection would — the helper's own
        # try/except turns it into the typed refusal, never a swallowed None
        real_get = db.get
        async def broken_get(model, ident, *a, **k):
            if model is ProductEvidenceRecord:
                raise RuntimeError("connection reset")
            return await real_get(model, ident, *a, **k)
        monkeypatch.setattr(db, "get", broken_get)

    with pytest.raises(ScanBoundIdentityUnavailable) as ei:
        await _run(db, user, log, "2 servings of Barebells bars", snapshot_id,
                   _the_misrouted_plan(existing), monkeypatch, turn_id=f"t:p1-{failure}")
    if failure == "unreadable":
        monkeypatch.undo()
    assert ei.value.placeholder == "Barebells Salty Peanut Protein Bar"
    assert "settlement_route" not in caplog.text          # refused BEFORE the predicate
    assert "route=ratio" not in caplog.text
    assert await _row_bytes(db, existing) == before
    rows = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id))).scalars().all()
    assert [r.id for r in rows] == [existing]
    assert len(await _events(db, user.id)) == events_before


def test_p1_the_identity_refusal_is_answered_in_words():
    from core.turns.entrypoint import _refusal_copy
    from core.turns.stages.execute_native import ScanBoundIdentityUnavailable
    copy = _refusal_copy(ScanBoundIdentityUnavailable(1, "Quest", "snapshot missing"))
    assert "didn't log anything" in copy and "Scan it again" in copy
    assert "unavailable" not in copy.lower()


def test_p1_the_helper_fails_closed_by_construction():
    """The AST says it: `_name_from_snapshot` contains no bare `return`
    that would let a lifted item continue unnamed, and raises the typed
    refusal on every branch that cannot name."""
    import ast
    import inspect
    from core.turns.stages import execute_native as m
    tree = ast.parse(inspect.getsource(m._name_from_snapshot).lstrip())
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)
              and isinstance(getattr(n.exc, "func", None), ast.Name)
              and n.exc.func.id == "ScanBoundIdentityUnavailable"]
    assert len(raises) >= 4, "missing / nameless / unreadable / unbound must each refuse"
    # the only early exits are `continue` for NON-lifted items — never a
    # `return` that leaves a lifted item under its placeholder
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert not returns, "a bare return here fails OPEN"


# ═════ REVIEW P2 — BINDING DISPOSITION COUNTS EVERY FOOD-AFFECTING OP ═══════

def test_p2_a_mixed_update_plus_log_plan_is_two_foods_and_binds_nothing():
    from core.turns.stages.execute_native import _scan_declined_to_bind
    upd = {"name": "update_food_entry", "input": {"entry_id": 1, "quantity": "2 bar"}}
    logf = {"name": "log_food", "input": {"food_name": "soup", "quantity": "1 bowl"}}
    dele = {"name": "delete_food_entry", "input": {"entry_id": 1}}
    assert _scan_declined_to_bind([upd, logf]) is True        # two foods -> unbound by design
    assert _scan_declined_to_bind([dele, logf]) is True
    assert _scan_declined_to_bind([upd]) is False              # one food (a correction): the scan's turn
    assert _scan_declined_to_bind([logf]) is False


# ── the real executor, because a stub cannot see this ───────────────────────
#
# The first version of this twin replaced `execute_tool_calls` with a
# recording stub and its own docstring admitted "the correction guard is not
# consulted" — so it asserted the claim it was supposed to test. Driven
# through the REAL executor the claim was FALSE: the guard read the
# ATTACHMENT, raised inside `_apply_portion_correction`, the bare except
# swallowed it, and the row was written "9 chips" beside the whole bag's
# 210 kcal (unbound: 90.1). Nothing is stubbed here but the enrichment
# network, and the assertions are on the row.

_PER100 = {"calories": 536, "protein": 7.1, "carbs": 64.3, "fat": 26.8,
           "sodium": 571}


class _Analysis:
    calories = 210.0; protein = 3.0; carbs = 25.0; fat = 10.0
    fiber = 2.0; sugar = 2.0; sodium = 224.0
    fdc_id = "167625"; confidence = "likely"; source = "usda"
    protein_density = None; satiety = None; quality = None
    per100 = dict(_PER100); serving_text = "28 g (about 15 chips)"
    micros: dict = {}; micros_estimated = False; coach_note = ""
    enrichment_source = "usda"; provenance = None


@pytest.fixture
def priced(monkeypatch):
    async def _analyze(db, user, food_name, inp, *a, **k):
        return _Analysis()
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _analyze)
    return _Analysis


async def _loaded(db, user_id):
    from db.models import User
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    return (await db.execute(select(User).where(User.id == user_id)
                             .options(selectinload(User.preferences)))).scalars().one()


async def _today(db, user):
    from db.queries import get_or_create_today_log
    return await get_or_create_today_log(db, user.id)


async def _mixed_turn_through_the_real_executor(db, user, snapshot_id):
    """log "1 bag"; then a MIXED turn [update(bag -> "9 chips"), log(soup)]
    with the scan attached exactly as ingress attaches it. Returns the
    corrected row's columns."""
    from db.models import FoodEntry
    from handlers.tool_executor import execute_tool_calls
    from skills.nutrition.product_acquisition import attach, begin_turn
    from sqlalchemy import select

    begin_turn()
    await execute_tool_calls(
        [{"name": "log_food", "input": {"food_name": "Sun Chips Harvest Cheddar",
                                        "quantity": "1 bag", "calories": 210,
                                        "protein": 3, "carbs": 25, "fats": 10}}],
        user, await _today(db, user), db)
    log = await _today(db, user)
    row = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().first()

    begin_turn()
    attach(snapshot_id)                       # ATTACHED — the decision is the stage's
    await execute_tool_calls(
        [{"name": "update_food_entry",
          "input": {"entry_id": row.id, "quantity": "9 chips"}},
         {"name": "log_food", "input": {"food_name": "Mystery soup",
                                        "quantity": "1 bowl"}}],
        user, await _today(db, user), db)
    await db.refresh(row)
    return {"calories": row.calories, "protein": row.protein,
            "carbs": row.carbs, "fats": row.fats, "quantity": row.quantity,
            "product_evidence_id": row.product_evidence_id}


@pytest.mark.asyncio
async def test_p2_a_mixed_multi_food_scan_turn_is_byte_identical_to_its_unbound_twin(
        db, make_user, monkeypatch, caplog, priced):
    """Danny's required proof: existing bar row + scan attachment +
    update(bar) + log(soup) -> binding SKIPPED -> the real legacy executor
    runs -> the correction result is byte-identical to the same unbound twin,
    the soup is byte-identical, neither carries a product_evidence_id, no
    ScanBoundCorrectionRefused, and no "portion correction not applied"
    warning."""
    from db.models import FoodEntry
    from sqlalchemy import select
    caplog.set_level(logging.WARNING)
    snap = await _prod_snapshot(db)

    unbound_user = await _loaded(db, (await make_user(telegram_id="cf5b-u")).id)
    unbound = await _mixed_turn_through_the_real_executor(db, unbound_user, None)

    attached_user = await _loaded(db, (await make_user(telegram_id="cf5b-a")).id)
    attached = await _mixed_turn_through_the_real_executor(db, attached_user, snap.id)

    assert unbound == attached, (
        f"a scan that bound NOTHING changed the correction: {unbound} != {attached}")
    assert unbound["calories"] == pytest.approx(90.1)     # the deterministic rescale
    assert attached["product_evidence_id"] is None

    soups = {}
    for label, u in (("unbound", unbound_user), ("attached", attached_user)):
        log = await _today(db, u)
        rows = (await db.execute(select(FoodEntry).where(
            FoodEntry.daily_log_id == log.id).order_by(FoodEntry.id))).scalars().all()
        soup = [r for r in rows if "soup" in (r.parsed_food_name or "").lower()][0]
        soups[label] = {"quantity": soup.quantity, "calories": soup.calories,
                        "product_evidence_id": soup.product_evidence_id}
    assert soups["unbound"] == soups["attached"], soups
    assert soups["attached"]["product_evidence_id"] is None

    warnings = [str(r.message) for r in caplog.records]
    assert not [w for w in warnings if "portion correction not applied" in w], warnings
    assert not [w for w in warnings if "scan-bound turn" in w], warnings


@pytest.mark.asyncio
async def test_p2_the_typed_invariant_propagates_and_is_never_swallowed(
        db, make_user, monkeypatch, priced):
    """Requirement 1: if a genuinely BOUND turn ever reaches correction
    application, the refusal must reach the caller — not become a warning
    while the row takes the model's macros beside a new portion."""
    from db.models import FoodEntry
    from handlers.tool_executor import execute_tool_calls
    from skills.nutrition.correction_application import ScanBoundCorrectionRefused
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      attach, begin_turn)
    from sqlalchemy import select
    user = await _loaded(db, (await make_user(telegram_id="cf5b-p")).id)
    snap = await _prod_snapshot(db)
    begin_turn()
    await execute_tool_calls(
        [{"name": "log_food", "input": {"food_name": "Sun Chips Harvest Cheddar",
                                        "quantity": "1 bag", "calories": 210,
                                        "protein": 3, "carbs": 25, "fats": 10}}],
        user, await _today(db, user), db)
    log = await _today(db, user)
    row = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().first()
    before = {"calories": row.calories, "quantity": row.quantity}

    begin_turn()
    attach(snap.id)
    SCAN_BINDING.set(ScanBinding("bound", snap.id))       # the misroute, adversarially
    with pytest.raises(ScanBoundCorrectionRefused):
        await execute_tool_calls(
            [{"name": "update_food_entry",
              "input": {"entry_id": row.id, "quantity": "9 chips"}}],
            user, await _today(db, user), db)
    await db.refresh(row)
    assert {"calories": row.calories, "quantity": row.quantity} == before, (
        "the refusal was swallowed and the row moved anyway")


def test_p2_the_executor_reraises_the_typed_invariant_by_construction():
    """AST: `_apply_portion_correction` holds an except that RE-RAISES
    ScanBoundCorrectionRefused, ahead of the broad handler."""
    import ast
    import inspect
    from handlers import tool_executor as te
    fn = ast.parse(inspect.getsource(te._apply_portion_correction).lstrip()).body[0]
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    typed = [h for h in handlers
             if isinstance(h.type, ast.Name) and h.type.id == "ScanBoundCorrectionRefused"]
    assert typed, "the typed invariant is not re-raised — it can be swallowed"
    assert any(isinstance(n, ast.Raise) and n.exc is None
               for h in typed for n in ast.walk(h)), "caught but not re-raised"
    broad = [h for h in handlers if h.type is None
             or (isinstance(h.type, ast.Name) and h.type.id == "Exception")]
    assert broad and typed[0].lineno < broad[0].lineno, (
        "the broad handler precedes the typed one and would swallow it")


# ═════ REQUIREMENT 2 — THE BINDING STATE DOES NOT LEAK ACROSS TURNS ═════════

@pytest.mark.asyncio
@pytest.mark.parametrize("how_turn_a_ends", ["settles", "refuses", "crashes"])
async def test_p2_binding_state_does_not_leak_into_the_next_turn(
        db, make_user, monkeypatch, priced, how_turn_a_ends):
    """Turn A: scanned, binding active — settling, refusing, or crashing.
    Turn B: an ordinary UNSCANNED correction. B must behave exactly like the
    baseline, with no snapshot and no binding left over."""
    from db.models import FoodEntry
    from handlers.tool_executor import execute_tool_calls
    from skills.nutrition.product_acquisition import (SCAN_BINDING,
                                                      SCANNED_PRODUCT_EVIDENCE,
                                                      ScanBinding, attach,
                                                      begin_turn, scan_is_bound)
    from sqlalchemy import select
    user = await _loaded(db, (await make_user(telegram_id=f"cf5b-l{how_turn_a_ends[0]}")).id)
    snap = await _prod_snapshot(db)

    begin_turn()
    await execute_tool_calls(
        [{"name": "log_food", "input": {"food_name": "Sun Chips Harvest Cheddar",
                                        "quantity": "1 bag", "calories": 210,
                                        "protein": 3, "carbs": 25, "fats": 10}}],
        user, await _today(db, user), db)
    log = await _today(db, user)
    row = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().first()

    # ── TURN A: scanned, bound, ending three different ways ──
    begin_turn()
    attach(snap.id)
    SCAN_BINDING.set(ScanBinding("bound", snap.id))
    assert scan_is_bound()
    if how_turn_a_ends == "refuses":
        from skills.nutrition.correction_application import ScanBoundCorrectionRefused
        with pytest.raises(ScanBoundCorrectionRefused):
            await execute_tool_calls(
                [{"name": "update_food_entry",
                  "input": {"entry_id": row.id, "quantity": "9 chips"}}],
                user, log, db)
    elif how_turn_a_ends == "crashes":
        try:
            raise RuntimeError("turn A died mid-flight")
        except RuntimeError:
            pass

    # ── TURN B: ingress runs, as it does unconditionally, every turn ──
    begin_turn()
    assert SCANNED_PRODUCT_EVIDENCE.get() is None
    assert SCAN_BINDING.get() is None
    assert not scan_is_bound()
    await execute_tool_calls(
        [{"name": "update_food_entry",
          "input": {"entry_id": row.id, "quantity": "9 chips"}}],
        user, await _today(db, user), db)
    await db.refresh(row)
    assert row.quantity == "9 chips"
    assert row.calories == pytest.approx(90.1), (
        "turn B did not behave like the unscanned baseline — binding leaked")
    assert row.product_evidence_id is None


def test_p2_the_ingress_clears_both_the_attachment_and_the_decision():
    """`begin_turn` is the ONE reset, and ingress calls it — an ingress that
    cleared only the id would leave a stale "bound" to be read as this
    turn's."""
    import ast
    import inspect
    from pathlib import Path
    from skills.nutrition import product_acquisition as pa
    src = inspect.getsource(pa.begin_turn)
    assert "SCANNED_PRODUCT_EVIDENCE.set(None)" in src and "SCAN_BINDING.set(None)" in src
    chat = Path("api/chat.py").read_text()
    tree = ast.parse(chat)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_begin_scan_turn" in called, "ingress does not clear the binding state"
    assert "SCANNED_PRODUCT_EVIDENCE.set" not in chat, (
        "ingress sets the attachment directly — the reset must be the one door")


# ═════ REQUIREMENT 3 — THE STATE IS THE FINAL AUTHORITY ════════════════════

def test_p2_the_final_proof_matrix_of_binding_states():
    """single scanned log -> BOUND · scan-bound correction shape -> lifted or
    refused · multi-food scan -> SKIPPED_MULTI_ITEM · next unscanned turn ->
    no binding state · typed invariant -> propagates, never swallowed."""
    from skills.nutrition.product_acquisition import (ATTACHED, BOUND,
                                                      SKIPPED_MULTI_ITEM,
                                                      SCAN_BINDING, attach,
                                                      begin_turn, decide_binding,
                                                      scan_is_bound)
    logf = {"name": "log_food", "input": {"food_name": "x", "quantity": "1 bar"}}
    upd = {"name": "update_food_entry", "input": {"entry_id": 1, "quantity": "2 bar"}}
    soup = {"name": "log_food", "input": {"food_name": "soup", "quantity": "1 bowl"}}
    from core.turns.stages.execute_native import _scan_declined_to_bind

    def _decide(ops):
        begin_turn(); attach(7)
        assert SCAN_BINDING.get().kind == ATTACHED
        decide_binding(bound=not _scan_declined_to_bind(ops))
        return SCAN_BINDING.get().kind

    assert _decide([logf]) == BOUND                       # single scanned log
    assert _decide([upd]) == BOUND                        # correction shape: the scan's turn
    assert _decide([upd, soup]) == SKIPPED_MULTI_ITEM     # multi-food
    assert _decide([logf, soup]) == SKIPPED_MULTI_ITEM
    begin_turn()                                          # the next, unscanned turn
    assert SCAN_BINDING.get() is None and not scan_is_bound()


def test_p2_the_binder_stamps_only_what_the_decision_says_is_bound():
    """`_bind_scanned_product` receives `_food_inputs`' output, which filters
    to log_food — so a MIXED [update, log] turn arrives here as ONE item and
    the old "len(items) == 1" rule would stamp a binding this turn does not
    have. The decision is the authority. (Redundant today because
    `_canonical_route` rejects the length mismatch first; proven because an
    unproven guard is indistinguishable from a dead one.)"""
    from core.turns.stages.execute_native import _bind_scanned_product
    from skills.nutrition.product_acquisition import (SCAN_BINDING, ScanBinding,
                                                      SCANNED_PRODUCT_EVIDENCE,
                                                      attach, begin_turn)
    begin_turn()
    attach(7)
    SCAN_BINDING.set(ScanBinding("skipped_multi_item", 7))
    items = [{"food_name": "soup", "quantity": "1 bowl"}]
    assert "product_evidence_id" not in _bind_scanned_product(items)[0], (
        "the binder stamped a snapshot the decision said binds nothing")
    SCAN_BINDING.set(ScanBinding("bound", 7))
    assert _bind_scanned_product(
        [{"food_name": "bar", "quantity": "1 bar"}])[0]["product_evidence_id"] == 7
    begin_turn()
    assert SCANNED_PRODUCT_EVIDENCE.get() is None


def test_p2_no_guard_re_derives_binding_from_operation_shape():
    """`_FOOD_OPS` counting is the DECISION's input and appears once, at the
    decision. Guards read the state."""
    import ast
    import inspect
    from core.turns.stages import execute_native as m
    src = inspect.getsource(m)
    tree = ast.parse(src)
    callers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_scan_declined_to_bind"]
    assert len(callers) == 1, (
        "operation counting is consulted more than once — a second definition "
        "of whether binding occurred")
    run_src = inspect.getsource(m.NativeExecutionStage.run)
    assert "_scan_bound()" in run_src and "_scan_declined_to_bind" not in run_src


# ═════ SCOPE: UNBOUND IS BYTE-IDENTICAL; MULTI-FOOD SCAN IS UNTOUCHED ═══════

@pytest.mark.asyncio
async def test_an_unbound_implicit_correction_is_byte_identical_in_behaviour(
        db, make_user, monkeypatch):
    """No scan: the same plan is a correction, exactly as before — the lift
    is never consulted (unbound updates remain byte-identical)."""
    from core.turns.stages.food import FoodPlanStage
    from tests.test_a_scan_is_binding import _Req
    user = await make_user()
    log = await _log(db, user)
    existing = await _legacy_barebells_row(db, log)
    plan = _the_misrouted_plan(existing)

    async def stub(text, u, **kw):
        return {"action": "update", "say": "", "tool_calls": plan}
    req = _Req("2 servings of Barebells bars", {"db": db, "user": user, "today_log": log,
                                                 "messages": ()})
    typed = await FoodPlanStage(interpreter=stub).run(req)
    assert len(typed.operations) == 1
    assert typed.operations[0]["name"] == "update_food_entry"
    assert typed.operations[0]["input"]["entry_id"] == existing
    assert typed.operations[0]["input"]["quantity"] == "4 bar"


def test_the_lift_is_scoped_to_exactly_one_implicit_food_update():
    """The narrow scope, as a table: one implicit update lifts; a mixed plan,
    two updates, a move-to-date, a delete, or a log do not."""
    from core.turns.stages.food import _lift_bound_correction_to_log as lift
    upd = {"name": "update_food_entry",
           "input": {"entry_id": 1, "quantity": "4 bar", "food_hint": "Barebells bar"}}
    logf = {"name": "log_food", "input": {"food_name": "x", "quantity": "1 bar"}}
    dele = {"name": "delete_food_entry", "input": {"entry_id": 1}}
    dated = {"name": "update_food_entry",
             "input": {"entry_id": 1, "quantity": "4 bar", "food_hint": "Barebells bar",
                       "date": "2026-08-17"}}
    assert lift((upd,), "2 servings of barebells")["name"] == "log_food"
    assert lift((upd, logf), "2 servings") is None            # mixed plan
    assert lift((upd, upd), "2 servings") is None             # two updates
    assert lift((dated,), "2 servings") is None               # move-to-date is explicit
    assert lift((dele,), "2 servings") is None                # a delete is not a correction
    assert lift((logf,), "2 servings") is None                # a log is already a log
    assert lift((), "2 servings") is None


def test_the_lift_takes_the_users_words_never_the_planners_total():
    """"2 servings" from the message; "2 bar" when only a noun was said; the
    planner's "4 bar" total never survives."""
    from core.turns.stages.food import _lift_bound_correction_to_log as lift
    upd = {"name": "update_food_entry",
           "input": {"entry_id": 1, "quantity": "4 bar", "food_hint": "Barebells bar"}}
    assert lift((upd,), "2 servings of Barebells bars")["input"]["quantity"] == "2 serving"
    assert lift((upd,), "110 g of barebells")["input"]["quantity"] == "110 g"
    assert lift((upd,), "2 Barebells bars")["input"]["quantity"] == "2 bar"
    assert lift((upd,), "two barebells bars")["input"]["quantity"] == "2 bar"
    for msg in ("2 servings of Barebells bars", "2 Barebells bars"):
        assert "4 bar" not in lift((upd,), msg)["input"]["quantity"]
    assert lift((upd,), "2 servings")["input"]["_scan_lifted"] is True


def test_the_backstop_is_keyed_on_the_binding_not_the_attachment():
    """A scan names ONE product. A multi-food turn binds nothing by design and
    legitimately takes the general path; every other shape under a scan is
    the scanned product's turn."""
    from core.turns.stages.execute_native import _scan_declined_to_bind
    logf = {"name": "log_food", "input": {"food_name": "x", "quantity": "1"}}
    upd = {"name": "update_food_entry", "input": {"entry_id": 1, "quantity": "4 bar"}}
    assert _scan_declined_to_bind([logf, logf]) is True        # two foods: unbound by design
    assert _scan_declined_to_bind([upd, logf]) is True         # a food updated + a food logged: two foods
    assert _scan_declined_to_bind([logf]) is False             # one food: bound
    assert _scan_declined_to_bind([upd]) is False              # a correction: the scanned product's turn
    assert _scan_declined_to_bind([]) is False


def test_the_native_stage_still_holds_no_except_handler():
    """A8, restated for the backstop: `ScanBoundNotLegacy` PROPAGATES."""
    import ast
    import inspect
    from core.turns.stages.execute_native import NativeExecutionStage
    run = ast.parse(inspect.getsource(NativeExecutionStage.run).lstrip()).body[0]
    assert not [n for n in ast.walk(run) if isinstance(n, ast.ExceptHandler)]
    raises = [n for n in ast.walk(run) if isinstance(n, ast.Raise)
              and isinstance(getattr(n.exc, "func", None), ast.Name)
              and n.exc.func.id == "ScanBoundNotLegacy"]
    assert raises, "the CF5b backstop is not in NativeExecutionStage.run"


def test_the_refusal_is_answered_in_words_not_the_failure_floor():
    from core.turns.entrypoint import _refusal_copy
    from core.turns.stages.execute_native import ScanBoundNotLegacy
    copy = _refusal_copy(ScanBoundNotLegacy("t:1", ["update_food_entry"]))
    assert "scanned product" in copy and "didn't touch anything" in copy
    assert "unavailable" not in copy.lower() and "lost the thread" not in copy.lower()


# ═════ THE ASK'S COPY: NAME THE UNKNOWN, CHIPS LEAD WITH THE LABEL'S UNIT ════

def test_the_bound_ask_names_the_unknown_and_asks_for_the_total():
    """The first two-turn canary: "is each bar one 55 g serving?" invited
    "yes", and "yes" read as the ONE-serving chip — half the food, looking
    confirmed. The question now names what the label doesn't say and asks
    for the total the chips offer."""
    from core.product_bound_ask import _question
    q = _question(food="Barebells Salty Peanut Protein Bar", unit_word="bar",
                  serving_grams=55.0, stated_quantity="2 bar")
    assert "doesn't say whether a bar is one serving" in q
    assert "how much did you have" in q
    assert "is each bar" not in q
    ml = _question(food="Fairlife", unit_word="bottle", serving_grams=240.0,
                   stated_quantity="1 bottle", base_unit="ml")
    assert "per 240 ml serving" in ml


def test_the_chips_lead_with_mass_and_keep_the_labels_words_as_the_value():
    """[110 g — 2 servings] [55 g — 1 serving]; value "2 servings" / "1
    serving" so `send_value` (what a text channel types back) is the label's
    own words and `_option_for_label` still matches; the PATCH is the
    semantic object (2 x serving), unchanged."""
    from core.product_bound_ask import _label_options
    from core.semantics import Dimension

    class _F:
        field_id = "f"; event_id = "e"
    opts = _label_options(field=_F(), serving_grams=55.0, unit="bar", stated_count=2.0)
    assert [o.label for o in opts] == ["110 g — 2 servings", "55 g — 1 serving"]
    assert [o.value for o in opts] == ["2 servings", "1 serving"]
    assert [o.send_value for o in opts] == ["2 servings", "1 serving"]
    assert [o.option_id for o in opts] == ["opt_label_serving_2", "opt_label_serving_1"]
    two = opts[0].patch.quantity
    assert two.unit_id == "serving" and two.dimension is Dimension.COUNT
    assert float(two.count) == 2.0 and float(two.grams) == 110.0
    liquid = _label_options(field=_F(), serving_grams=240.0, unit="bottle",
                            stated_count=None, base_unit="ml")
    assert [o.label for o in liquid] == ["240 ml — 1 serving"]


def test_a_typed_answer_in_the_labels_words_still_matches_the_chip():
    """The reason the value carries the words: "2 servings" typed on a text
    channel resolves to the same option as the tap."""
    from core.b1_answer_turn import _option_for_label
    from core.product_bound_ask import _label_options

    class _F:
        field_id = "f"; event_id = "e"
    opts = _label_options(field=_F(), serving_grams=55.0, unit="bar", stated_count=2.0)

    class _Field:
        options = opts
    assert _option_for_label(_Field(), "2 servings").option_id == "opt_label_serving_2"
    assert _option_for_label(_Field(), "1 SERVING").option_id == "opt_label_serving_1"
    # and the display text typed back verbatim resolves too — `_option_for_
    # label` matches label OR send_value; the wire still carries no patch
    assert _option_for_label(_Field(), "110 g — 2 servings").option_id == "opt_label_serving_2"
    assert _option_for_label(_Field(), "yes") is None       # the trap is gone: no chip is "yes"
