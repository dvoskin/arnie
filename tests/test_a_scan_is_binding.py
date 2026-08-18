"""⭐ P17 SCAN/BINDING — A SCAN IS BINDING, LIKE A TAP. Takes CF4 + CF5, obeys CF6.

    verified barcode -> persisted exact ProductEvidence snapshot
      -> SCAN-BOUND item (product_evidence_id on the item)
      -> predicate: judged by the SNAPSHOT (Supported("product") /
         BoundUnpriceable), never by memory or artifact
      -> assemble(bound=True): MEMORY / ARTIFACT / ESTIMATE never READ
      -> price(bound=True): that snapshot only, AUTHORITATIVE scaling only
      -> settle  |  ASK / REFUSE (canonical, in the label's units)

    NEVER  scan -> MEMORY -> PRODUCT
    NEVER  exact product x heuristic mass -> authoritative settlement
    NEVER  scan-bound -> legacy

nutrition authority != quantity authority: a barcode proves WHAT was eaten,
not HOW MUCH.
"""
from __future__ import annotations

import datetime as dt

import pytest


BAREBELLS = {
    "code": "70004199", "product_name": "Barebells Salty Peanut", "brands": "Barebells",
    "serving_size": "55.0g", "serving_quantity": 55, "serving_quantity_unit": "g",
    "rev": 1, "last_modified_t": 1, "nutrition_data_per": "100g",
    "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                   "carbohydrates_100g": 18, "fat_100g": 7.3,
                   "energy-kcal_serving": 110, "proteins_serving": 11,
                   "carbohydrates_serving": 9.9, "fat_serving": 4}}


async def _snapshot(db):
    from skills.nutrition.product_store import append_product_evidence
    return await append_product_evidence(db, record=dict(BAREBELLS), serving_unit="bar")


async def _remember(db, user, name, per100g, fdc):
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    db.add(UserFoodMatch(user_id=user.id, name_norm=memory_key(name, ""),
                         display_name=name, cal_100=per100g["calories"],
                         protein_100=per100g["protein"], carbs_100=per100g["carbs"],
                         fat_100=per100g["fat"], fdc_id=fdc, confidence="exact"))
    await db.commit()


def _item(qty, name="Barebells bar", pid=None):
    it = {"food_name": name, "quantity": qty, "calories": 999.0, "protein": 1.0}
    if pid:
        it["product_evidence_id"] = pid
    return it


# ── THE PREDICATE JUDGES A BOUND ITEM BY ITS SNAPSHOT ───────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("qty,expect", [
    ("2 bars", "product"),          # the label's own unit -> direct basis
    ("110 g", "product"),           # user-stated exact mass
    ("2 cups", "bound_unpriceable"),  # vessel heuristic mass -> CF4
    ("2 handfuls", "bound_unpriceable"),
    ("", "bound_unpriceable"),      # no quantity at all
])
async def test_the_predicate_decides_a_bound_item_from_the_label(
        db, make_user, qty, expect):
    from core.general_settlement import BoundUnpriceable, Supported, coverage_for
    user = await make_user()
    snap = await _snapshot(db)
    verdict = await coverage_for(db, user_id=user.id, items=[_item(qty, pid=snap.id)])
    if expect == "product":
        assert isinstance(verdict, Supported) and verdict.expected_source == "product", verdict
    else:
        assert isinstance(verdict, BoundUnpriceable), verdict
        assert verdict.unit == "bar"


@pytest.mark.asyncio
async def test_a_bound_item_is_not_judged_by_memory_or_artifact(db, make_user):
    """The SAME item, unbound, is Unsupported (no identity/evidence for a
    made-up name); bound, it is Supported("product"). And a bound item with a
    memory row that could price "2 cups" is STILL BoundUnpriceable — memory
    is not consulted for a bound item, not even by the predicate."""
    from core.general_settlement import (BoundUnpriceable, Supported,
                                         Unsupported, coverage_for)
    user = await make_user()
    snap = await _snapshot(db)
    name = f"Barebells bar u{user.id}"
    unbound = await coverage_for(db, user_id=user.id, items=[_item("2 bars", name)])
    assert isinstance(unbound, Unsupported) and not isinstance(unbound, BoundUnpriceable)
    bound = await coverage_for(db, user_id=user.id, items=[_item("2 bars", name, snap.id)])
    assert isinstance(bound, Supported) and bound.expected_source == "product"
    await _remember(db, user, name, {"calories": 400, "protein": 30, "carbs": 30, "fat": 15},
                    fdc=f"77{user.id}")
    cups = await coverage_for(db, user_id=user.id, items=[_item("2 cups", name, snap.id)])
    assert isinstance(cups, BoundUnpriceable), "memory priced a bound item's heuristic mass"


# ── THE PRICER: NEVER scan -> MEMORY; NEVER exact x heuristic ────────────────

def test_price_bound_refuses_a_heuristic_mass_and_unbound_accepts_it():
    """CF4 at the pricer: the same PRODUCT evidence and the same "2 cups":
    unbound prices (heuristic, as today); bound REFUSES."""
    from core.canonical_pricing import PricingRefused, ProductEvidence, price
    from skills.nutrition.normalize import normalize_quantity
    ev = ProductEvidence(identifier="off:70004199",
                         per100g={"calories": 200, "protein": 20, "carbs": 18, "fat": 7.3},
                         per_serving={"calories": 110, "protein": 11, "carbs": 9.9, "fat": 4},
                         serving_grams=55.0, serving_unit="bar")
    cups = normalize_quantity("2 cups", "Barebells salty peanut")
    assert cups.grams and cups.normalization_source == "vessel"
    assert price(entity="Barebells bar", consumed=cups, product=ev).rung.value == "product"
    with pytest.raises(PricingRefused, match="heuristic"):
        price(entity="Barebells bar", consumed=cups, product=ev, bound=True)
    # and the label's own units / an exact mass DO price bound
    for q in ("2 bars", "110 g"):
        priced = price(entity="Barebells bar",
                       consumed=normalize_quantity(q, "Barebells salty peanut"),
                       product=ev, bound=True)
        assert priced.rung.value == "product" and priced.calories == pytest.approx(220.0)


@pytest.mark.asyncio
async def test_settlement_prices_a_scanned_item_bound_and_never_reads_memory(
        db, make_user, monkeypatch):
    """The settle path itself: `_price` on a bound item calls assemble(bound)
    — `_memory` is spied and must NOT be called — and prices from the
    snapshot even though a memory row for the same name says 9000 kcal."""
    from core import canonical_pricing_inputs as inputs
    from core.general_settlement import GeneralSettlementOwner
    user = await make_user()
    snap = await _snapshot(db)
    name = f"Barebells bar u{user.id}"
    await _remember(db, user, name, {"calories": 9000, "protein": 1, "carbs": 1, "fat": 1},
                    fdc=f"78{user.id}")
    calls = []
    real = inputs._memory
    async def spy(*a, **k):
        calls.append(a); return await real(*a, **k)
    monkeypatch.setattr(inputs, "_memory", spy)

    priced = await GeneralSettlementOwner()._price(db, user=user, item=_item("2 bars", name, snap.id))
    assert priced.analysis.rung.value == "product"
    assert priced.analysis.calories == pytest.approx(220.0)
    assert calls == [], "a scan-bound settle READ memory"


# ── THE LIVE PATH (CF6): plan -> validate -> native stage -> render ──────────

class _Req:
    def __init__(self, text, metadata, turn_id="t:scan"):
        self.text, self.turn_id, self.metadata = text, turn_id, metadata
        self.source_type, self.platform = "ios", "ios"


async def _log(db, user):
    from db.models import DailyLog
    from db.queries import get_or_create_log_for_date
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    log = await get_or_create_log_for_date(db, user.id, dt.date(2026, 8, 18))
    await db.commit()
    return (await db.execute(select(DailyLog).where(DailyLog.id == log.id)
                             .options(selectinload(DailyLog.food_entries))
                             .execution_options(populate_existing=True))).scalar_one()


async def _native(db, user, log, text, snapshot_id, ops, monkeypatch, forbid_legacy=True):
    """The native chain with the interpreter stubbed to return `ops`, the
    scan bound through the SAME contextvar api/chat.py sets, and the legacy
    executor instrumented to fail if invoked."""
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
        return {"action": "log", "say": "", "tool_calls": ops}

    req = _Req(text, {"db": db, "user": user, "today_log": log, "messages": ()})
    token = SCANNED_PRODUCT_EVIDENCE.set(snapshot_id)
    try:
        plan = await FoodPlanStage(interpreter=stub).run(req)
        validation = await FoodValidationStage().run(req, plan=plan)
        assert validation.disposition == "execute"
        execution = await NativeExecutionStage().run(req, validation=validation)
        snapshot = await CommittedSnapshotStage().run(req, execution=execution)
        response = await NativeRenderStage().run(req, plan=plan, validation=validation,
                                                 snapshot=snapshot)
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    return execution, response


@pytest.mark.asyncio
async def test_live_shape_two_bars_settles_bound_and_replies(db, make_user, monkeypatch):
    from db.models import FoodEntry
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))   # fail-closed: name the user
    log = await _log(db, user)
    snap = await _snapshot(db)
    ops = [{"name": "log_food", "input": {"food_name": "Barebells bar", "quantity": "2 bars",
                                          "calories": 999.0, "protein": 1.0}}]
    execution, response = await _native(db, user, log, "2 barebells bars", snap.id, ops, monkeypatch)
    assert execution is not None and execution.calls[0].committed
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    assert row.pricing_rung == "product" and row.product_evidence_id == snap.id
    assert row.calories == pytest.approx(220.0)                 # the label, not 999
    assert response is not None and "".join(response.bubbles).strip()


@pytest.mark.asyncio
async def test_live_shape_two_cups_is_refused_in_the_labels_units_never_legacy(
        db, make_user, monkeypatch):
    """The ASK/REFUSE arm on the live shape: nothing written, nothing claimed,
    the legacy executor never invoked, and the reply names the label's unit."""
    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _snapshot(db)
    n_rows = len((await db.execute(select(FoodEntry))).scalars().all())
    ops = [{"name": "log_food", "input": {"food_name": "Barebells bar", "quantity": "2 cups",
                                          "calories": 999.0}}]
    execution, response = await _native(db, user, log, "2 cups of barebells", snap.id, ops, monkeypatch)
    assert execution is not None and not execution.calls[0].committed
    assert execution.calls[0].correction["refusal"] == "scan_bound_unpriceable"
    assert len((await db.execute(select(FoodEntry))).scalars().all()) == n_rows
    assert (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id))).scalars().all() == []
    assert (await db.execute(select(LedgerEvent).where(
        LedgerEvent.user_id == user.id, LedgerEvent.domain == "food"))).scalars().all() == []
    text = " ".join(response.bubbles)
    assert "bar" in text and "2 cups" in text, text


@pytest.mark.asyncio
async def test_a_multi_item_scan_turn_binds_nothing_and_takes_the_general_path(
        db, make_user, monkeypatch):
    """A scan names ONE product; two foods in one turn bind nothing — the
    verdict is the ordinary predicate's (here Unsupported -> the stage's
    legacy branch, which for this test is a recording stub, not forbidden)."""
    import handlers.tool_executor as te
    from core.execution_result import ExecutionResult
    seen = []
    async def legacy(ops, *a, **k):
        seen.append(ops); return ExecutionResult(calls=())
    monkeypatch.setattr(te, "execute_tool_calls", legacy)
    from core.turns.stages import execute_native as stage_mod
    async def claim_ok(self, *a, **k): return True
    monkeypatch.setattr(stage_mod.NativeExecutionStage, "_claim", claim_ok)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _snapshot(db)
    ops = [{"name": "log_food", "input": {"food_name": f"Barebells bar u{user.id}", "quantity": "1 bar"}},
           {"name": "log_food", "input": {"food_name": f"Mystery soup u{user.id}", "quantity": "1 bowl"}}]
    await _native(db, user, log, "a bar and some soup", snap.id, ops, monkeypatch, forbid_legacy=False)
    assert seen and all("product_evidence_id" not in op["input"] for op in seen[0])


# ═════ LIVE CANARY #1 (2026-08-18) — the two production shapes, verbatim ═════

#: OFF 70004199 as production acquired it: per-100 g, a 55 g serving, NO unit
#: noun, NO product quantity (the P17d probe's exact shape).
BAREBELLS_PROD = {
    "code": "70004199", "product_name": "Barebell salty peanut protein bar",
    "brands": "Barebell", "serving_size": "55.0g", "serving_quantity": "55",
    "serving_quantity_unit": "g", "rev": 1, "last_modified_t": 1724712330,
    "nutrition_data_per": "100g",
    "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                   "carbohydrates_100g": 18, "fat_100g": 8, "fiber_100g": 3}}


async def _prod_snapshot(db):
    from skills.nutrition.product_store import append_product_evidence
    return await append_product_evidence(db, record=dict(BAREBELLS_PROD))  # no serving_unit


@pytest.mark.asyncio
@pytest.mark.parametrize("qty,expect", [
    ("2 servings", "product"),      # the LABEL'S own serving — sourced conversion
    ("1 serving", "product"),
    ("half a serving", "product"),
    ("110 g", "product"),
    ("2 bars", "bound_unpriceable"),   # nothing on the record says a bar is a serving
    ("2 cups", "bound_unpriceable"),
])
async def test_the_labels_own_serving_is_a_sourced_conversion(db, make_user, qty, expect):
    """LIVE CANARY #1: '2 barebell bars' was refused — correctly, the record
    has no unit noun — but the label DOES state a 55 g serving and the pricer
    offered no way to count it. Now the label's serving is a sourced
    conversion under the noun 'serving' (provenance = our immutable
    snapshot); bars/cups still refuse, honestly."""
    from core.general_settlement import BoundUnpriceable, Supported, coverage_for
    user = await make_user()
    snap = await _prod_snapshot(db)
    verdict = await coverage_for(db, user_id=user.id,
                                 items=[_item(qty, "Barebell salty peanut protein bar", snap.id)])
    if expect == "product":
        assert isinstance(verdict, Supported) and verdict.expected_source == "product", verdict
    else:
        assert isinstance(verdict, BoundUnpriceable), verdict
        assert verdict.serving_grams == 55.0 and verdict.unit == ""


@pytest.mark.asyncio
async def test_two_servings_settle_bound_with_the_snapshot_and_conversion_on_the_row(
        db, make_user, monkeypatch):
    from db.models import FoodEntry
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    ops = [{"name": "log_food", "input": {"food_name": "Barebell salty peanut protein bar",
                                          "quantity": "2 servings", "calories": 999.0}}]
    execution, response = await _native(db, user, log, "2 servings of the barebells", snap.id, ops, monkeypatch)
    assert execution.calls[0].committed
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    assert row.product_evidence_id == snap.id and row.pricing_rung == "product"
    assert row.calories == pytest.approx(220.0)
    assert row.resolved_grams == pytest.approx(110.0)          # 2 x the label's 55 g
    assert row.conversion_evidence_ids_json and "off:70004199" in row.conversion_evidence_ids_json
    assert "".join(response.bubbles).strip()


@pytest.mark.asyncio
async def test_two_bars_are_refused_in_the_labels_own_terms(db, make_user, monkeypatch):
    """The refusal copy offers what the label KNOWS: 'the label lists a 55 g
    serving — how many servings, or how many grams?' — not 'what was the
    weight'."""
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    ops = [{"name": "log_food", "input": {"food_name": "Barebells Protein Bar",
                                          "quantity": "2 bar", "calories": 400.0}}]
    execution, response = await _native(db, user, log, "2 barebell bars", snap.id, ops, monkeypatch)
    assert not execution.calls[0].committed
    text = " ".join(response.bubbles)
    assert "55 g serving" in text and "servings" in text and "grams" in text, text


@pytest.mark.asyncio
async def test_a_scan_answers_the_interpreters_flavor_question(db, make_user, monkeypatch):
    """LIVE CANARY #1, turn 2: the interpreter returned action=ask about
    FLAVOR ('Salty Peanut or Caramel Cashew?') for a scan-bound bar — an
    identity question the snapshot has answered — so the native lane had no
    op and delegated to legacy. Now the plan stage approves the single item
    and the bound predicate decides the quantity. Payload verbatim from the
    production log."""
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    interpreter_ask = {
        "action": "ask",
        "items": [{"food": "Barebells Protein Bar", "amount": 2, "unit": "serving",
                   "calories": 400, "protein": 40, "carbs": 38, "fats": 15,
                   "branded": True, "basis": "regular"}],
        "ambiguities": [{"item": "Barebells Protein Bar", "field": "identity",
                         "impact_cal": 0, "impact_protein": 0,
                         "assumed": "need flavor to pick between Salty Peanut and Caramel Cashew"}],
        "points": [{"label": "Barebells Protein Bar", "qs": ["Salty Peanut or Caramel Cashew?"]}],
        "ready": [], "tool_calls": []}

    async def stub(text, u, **kw):
        return interpreter_ask
    req = _Req("2 servings of barebells", {"db": db, "user": user, "today_log": log, "messages": ()})
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    try:
        plan = await FoodPlanStage(interpreter=stub).run(req)
        validation = await FoodValidationStage().run(req, plan=plan)
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    assert validation.disposition == "execute", validation
    assert validation.approved_operations[0]["name"] == "log_food"
    assert validation.approved_operations[0]["input"]["quantity"] == "2 serving"

    # UNBOUND, the same ask stays an ask — a scan is the only thing that
    # answers identity here
    plan_unbound = await FoodPlanStage(interpreter=stub).run(req)
    v2 = await FoodValidationStage().run(req, plan=plan_unbound)
    assert v2.disposition == "ask"

    # and a QUANTITY ambiguity is NOT answered by a scan
    qty_ask = dict(interpreter_ask, ambiguities=[{"item": "Barebells Protein Bar",
                                                  "field": "quantity", "impact_cal": 200}])
    async def stub_q(text, u, **kw):
        return qty_ask
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    try:
        v3 = await FoodValidationStage().run(req, plan=await FoodPlanStage(interpreter=stub_q).run(req))
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    assert v3.disposition == "ask"
