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


async def _native(db, user, log, text, snapshot_id, ops, monkeypatch, forbid_legacy=True,
                  turn_id="t:scan"):
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

    req = _Req(text, {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"{turn_id}-{user.id}")
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
    # the label states a serving, so the refusal is now an ASK holding the
    # snapshot (CF9); a label with nothing to ask with keeps the plain refusal
    assert execution.calls[0].correction["refusal"] in ("scan_bound_ask", "scan_bound_unpriceable")
    assert len((await db.execute(select(FoodEntry))).scalars().all()) == n_rows
    assert (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id))).scalars().all() == []
    assert (await db.execute(select(LedgerEvent).where(
        LedgerEvent.user_id == user.id, LedgerEvent.domain == "food"))).scalars().all() == []
    text = " ".join(response.bubbles)
    assert "55 g serving" in text, text


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
    assert "55 g serving" in text and "whether a bar is one serving" in text \
        and "how much did you have" in text, text     # the ask names the unknown, asks the total


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


@pytest.mark.asyncio
async def test_a_bound_scan_is_not_an_answer_to_an_open_question(db, make_user, monkeypatch):
    """LIVE CANARY #2 (2026-08-18): legacy's flavor question stayed open (its
    log_date keeps it live until tomorrow) and every later Barebells message
    was routed as its ANSWER — the interpreter got the prior, passed or
    re-asked, run() refused, no op, legacy. With a scan bound the plan stage
    interprets COLD: the interpreter is handed NO prior. Unbound, the prior
    still travels (an open question is still an open question)."""
    from core.turns.stages.food import FoodPlanStage
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
    user = await make_user()
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    seen = []
    async def spy(text, u, **kw):
        seen.append(kw.get("prior"))
        return {"action": "log", "tool_calls": [{"name": "log_food", "input": {
            "food_name": "Barebells Protein Bar", "quantity": "2 servings"}}]}
    stale_prior = {"kind": "ask", "question": "Salty Peanut or Caramel Cashew?", "log_date": "2026-08-18"}
    req = _Req("2 servings of Barebells bars", {"db": db, "user": user, "today_log": log,
                                               "messages": (), "food_prior": stale_prior,
                                               "food_pending": True})
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    try:
        plan = await FoodPlanStage(interpreter=spy).run(req)
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    assert seen == [None], "a bound scan handed the interpreter the stale prior"
    assert plan.operations and plan.operations[0]["name"] == "log_food"
    # unbound: the prior travels
    await FoodPlanStage(interpreter=spy).run(req)
    assert seen[-1] == stale_prior


@pytest.mark.asyncio
async def test_the_users_stated_serving_outranks_the_interpreters_bar(db, make_user, monkeypatch):
    """LIVE CANARY #3 (19:33): the user typed "2 servings of the Barebells";
    the interpreter's item said unit=bar; the bound predicate saw "2 bar" and
    asked "how many servings?" about a message that had SAID servings. For a
    scan-bound item the user's stated LABEL unit wins over the interpreter's
    rewrite (P17 precedence class 1): the turn settles bound at 2 x 55 g.
    "2 barebells bars" is untouched and still asks."""
    from db.models import FoodEntry
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    # the interpreter's op, verbatim shape: unit rewritten to "bar"
    ops = [{"name": "log_food", "input": {"food_name": "Barebells Protein Bar",
                                          "quantity": "2 bar", "calories": 400.0, "protein": 40.0}}]
    execution, response = await _native(db, user, log, "2 servings of the Barebells", snap.id, ops, monkeypatch)
    assert execution.calls[0].committed, execution.calls[0]
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    assert row.product_evidence_id == snap.id and row.pricing_rung == "product"
    assert row.quantity == "2 serving" and row.resolved_grams == pytest.approx(110.0)
    assert row.calories == pytest.approx(220.0)                     # the label, not 400

    # the same rewrite with the user's OWN word being "bars" stays a refusal
    execution2, response2 = await _native(db, user, log, "2 barebells bars", snap.id,
                                          [{"name": "log_food", "input": {"food_name": "Barebells Protein Bar",
                                                                          "quantity": "2 bar", "calories": 400.0}}],
                                          monkeypatch, turn_id=f"t:scan-bars-{user.id}")
    assert not execution2.calls[0].committed
    assert "55 g serving" in " ".join(response2.bubbles)


# ═════ CF9 / P17-UA slice C — THE ASK HOLDS THE SNAPSHOT (the natural journey) ═

@pytest.mark.asyncio
async def test_two_bars_opens_an_ask_that_holds_the_snapshot_and_the_answer_settles_bound(
        db, make_user, monkeypatch):
    """scan -> "2 bars" -> BoundUnpriceable -> an ASK in the label's terms is
    PERSISTED with the snapshot on its stored item -> the answer "2 servings"
    (a later turn, NO scan) settles the SAME snapshot canonically: no
    reacquisition (spy = 0), no MEMORY read (spy = 0), no legacy (forbidden),
    row.product_evidence_id == the snapshot, 110 g from the label's serving."""
    import handlers.tool_executor as te
    from core import b1_answer_turn, canonical_pricing_inputs as inputs
    from core.clarification_answer import Outcome
    from core.turns.stages.execute_native import NativeExecutionStage
    from core.turns.stages.render_native import NativeRenderStage
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    from db.models import FoodEntry, PendingOperation
    from skills.nutrition import product_acquisition as acq
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
    from sqlalchemy import select

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)                       # 70004199 as it really is
    # a memory row for the same name — must never be read on the bound path
    await _remember(db, user, "Barebells Salty Peanut Protein Bar",
                    {"calories": 9000, "protein": 1, "carbs": 1, "fat": 1}, fdc=f"60{user.id}")

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    acquisitions, memory_reads = [], []
    real_acquire = acq.acquire_product_evidence
    async def spy_acquire(*a, **k):
        acquisitions.append(a); return await real_acquire(*a, **k)
    monkeypatch.setattr(acq, "acquire_product_evidence", spy_acquire)
    real_mem = inputs._memory
    async def spy_mem(*a, **k):
        import traceback
        memory_reads.append([f.name for f in traceback.extract_stack()[:-1]][-4:])
        return await real_mem(*a, **k)
    monkeypatch.setattr(inputs, "_memory", spy_mem)

    # ── TURN 1: scan + "2 bars" -> the interpreter's op shape (unit=bar) ──
    ops = [{"name": "log_food", "input": {"food_name": "Barebells Salty Peanut Protein Bar",
                                          "quantity": "2 bar", "calories": 400.0, "protein": 40.0}}]
    class _V:
        disposition = "execute"; approved_operations = ops; clarification = None
    req = _Req("2 barebells bars", {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:cf9-{user.id}")
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    try:
        execution = await NativeExecutionStage().run(req, validation=_V())
        snapshot = await CommittedSnapshotStage().run(req, execution=execution)
        response = await NativeRenderStage().run(req, plan=None, validation=_V(), snapshot=snapshot)
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    assert not execution.calls[0].committed
    assert execution.calls[0].correction["refusal"] == "scan_bound_ask"
    text = " ".join(response.bubbles)
    assert "55 g serving" in text and "whether a bar is one serving" in text, text
    assert "is each bar" not in text, "the per-bar yes/no is the trap: an affirmative matched the 1-serving chip"
    assert getattr(response, "interaction", None), "the ask must reach the client as an interaction"
    # nothing written; the OPERATION is persisted with the snapshot on its item
    assert (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id))).scalars().all() == []
    op = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().one()
    import json
    stored = json.loads(op.canonical_payload)
    assert stored["item"]["product_evidence_id"] == snap.id
    assert op.status == "awaiting_answer"

    # ── TURN 2: the answer, a LATER turn with NO scan attached ──
    turn = await b1_answer_turn.handle(db, user=user, source_turn_id=f"ios:cf9-ans-{user.id}",
                                       message="2 servings")
    assert turn is not None and turn.outcome is Outcome.APPLIED, turn
    await db.commit()
    row = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id))).scalars().one()
    assert row.product_evidence_id == snap.id, "the answer did not settle the held snapshot"
    assert row.pricing_rung == "product"
    assert row.calories == pytest.approx(220.0)            # the label, not the 400 guess, not 9000
    # "2 servings" chosen = a user-stated mass of 110 g (class 1): scaled 1.1x
    # from per-100 g; no conversion was needed, so resolved_grams is unset
    assert row.scaling_factor == pytest.approx(1.1)
    assert acquisitions == [], "the answer re-acquired the product"
    assert memory_reads == [], "the bound answer READ memory"


@pytest.mark.asyncio
async def test_the_bound_ask_chip_settles_the_same_snapshot(db, make_user, monkeypatch):
    """The tap path: the option '2 servings (110 g)' by id -> settles bound."""
    import handlers.tool_executor as te
    from core import b1_answer_turn
    from core.clarification_answer import Outcome
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import FoodEntry, PendingOperation
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
    from sqlalchemy import select
    import json

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    ops = [{"name": "log_food", "input": {"food_name": "Barebells bar", "quantity": "2 bar",
                                          "calories": 400.0}}]
    class _V:
        disposition = "execute"; approved_operations = ops; clarification = None
    req = _Req("2 barebells bars", {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:cf9tap-{user.id}")
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    try:
        execution = await NativeExecutionStage().run(req, validation=_V())
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    receipt = execution.calls[0].correction
    wire = receipt["interaction"]
    field = wire["groups"][0]["fields"][0]
    two = next(o for o in field["options"] if o["option_id"] == "opt_label_serving_2")
    op_row = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().one()
    turn = await b1_answer_turn.handle(
        db, user=user, source_turn_id=f"ios:cf9tap-ans-{user.id}",
        field_id=field["field_id"], option_id=two["option_id"], revision=0)
    assert turn is not None and turn.outcome is Outcome.APPLIED, turn
    await db.commit()
    row = (await db.execute(select(FoodEntry).where(FoodEntry.daily_log_id == log.id))).scalars().one()
    assert row.product_evidence_id == snap.id and row.calories == pytest.approx(220.0)


# ═════ CF9 REPLAY / SAFETY (Danny's closure list) ═══════════════════════════

async def _open_bound_ask(db, user, log, snap, monkeypatch, *, turn_id, qty="2 bar"):
    """Turn 1 helper: scan + '2 bars' -> the ask; returns the execution."""
    from core.turns.stages.execute_native import NativeExecutionStage
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
    ops = [{"name": "log_food", "input": {"food_name": "Barebells Salty Peanut Protein Bar",
                                          "quantity": qty, "calories": 400.0}}]
    class _V:
        disposition = "execute"; approved_operations = ops; clarification = None
    req = _Req("2 barebells bars", {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=turn_id)
    token = SCANNED_PRODUCT_EVIDENCE.set(snap.id)
    try:
        execution = await NativeExecutionStage().run(req, validation=_V())
    finally:
        SCANNED_PRODUCT_EVIDENCE.reset(token)
    await db.commit()
    return execution


async def _rows(db, log):
    """Core-table read by log id captured up front — safe after a rollback."""
    from db.models import FoodEntry
    from sqlalchemy import select
    log_id = log if isinstance(log, int) else int(log.__dict__.get("id") or log.id)
    t = FoodEntry.__table__
    return (await db.execute(select(t).where(t.c.daily_log_id == log_id))).mappings().all()


@pytest.mark.asyncio
async def test_turn_one_takes_no_claim_and_a_duplicate_answer_makes_one_row(db, make_user, monkeypatch):
    import handlers.tool_executor as te
    from core import b1_answer_turn
    from core.clarification_answer import Outcome
    from db.models import IdempotencyRecord
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    async def forbidden(*a, **k): raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    log = await _log(db, user); snap = await _prod_snapshot(db)
    ex = await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:cf9s1-{user.id}")
    assert ex.calls[0].correction["refusal"] == "scan_bound_ask"
    # zero food write, ZERO settlement claim on turn 1
    assert await _rows(db, log) == []
    assert (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id))).scalars().all() == []
    # answer, then the SAME answer again under a new turn id
    t1 = await b1_answer_turn.handle(db, user=user, source_turn_id=f"a1-{user.id}", message="2 servings")
    assert t1.outcome is Outcome.APPLIED
    await db.commit()
    t2 = await b1_answer_turn.handle(db, user=user, source_turn_id=f"a2-{user.id}", message="2 servings")
    assert t2 is not None and t2.outcome is Outcome.REPLAY, t2
    await db.commit()
    rows = await _rows(db, log)
    assert len(rows) == 1 and rows[0]["product_evidence_id"] == snap.id


@pytest.mark.asyncio
async def test_another_user_cannot_answer_the_ask(db, make_user, monkeypatch):
    import handlers.tool_executor as te
    from core import b1_answer_turn
    owner, other = await make_user("cf9-owner"), await make_user("cf9-other")
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(owner.id))
    async def forbidden(*a, **k): raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    log = await _log(db, owner); snap = await _prod_snapshot(db)
    await _open_bound_ask(db, owner, log, snap, monkeypatch, turn_id=f"ios:cf9u-{owner.id}")
    assert await b1_answer_turn.handle(db, user=other, source_turn_id="x", message="2 servings") is None
    assert await _rows(db, log) == []


@pytest.mark.asyncio
async def test_a_failed_settlement_does_not_consume_the_ask(db, make_user, monkeypatch):
    """"2 cups" is a heuristic mass -> the bound settle REFUSES -> no row, the
    ask is still awaiting -> "2 servings" then settles it."""
    import handlers.tool_executor as te
    from core import b1_answer_turn
    from core.clarification_answer import Outcome
    from core.b1_quantity_operation import owning
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    async def forbidden(*a, **k): raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    log = await _log(db, user); snap = await _prod_snapshot(db)
    await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:cf9f-{user.id}")
    user_id = int(user.id); log_id = int(log.id)
    bad = await b1_answer_turn.handle(db, user=user, source_turn_id=f"b-{user_id}", message="2 cups")
    assert bad is not None and bad.outcome is Outcome.REFUSED, bad
    await db.rollback()
    await db.refresh(user)               # the rollback expired the ORM user
    assert await _rows(db, log_id) == []
    owned = await owning(db, user)
    assert owned is not None and owned.awaiting, "a failed settle consumed the ask"
    good = await b1_answer_turn.handle(db, user=user, source_turn_id=f"g-{user.id}", message="2 servings")
    assert good.outcome is Outcome.APPLIED
    await db.commit()
    rows = await _rows(db, log)
    assert len(rows) == 1 and rows[0]["product_evidence_id"] == snap.id


@pytest.mark.asyncio
async def test_a_new_scan_supersedes_the_open_ask(db, make_user, monkeypatch):
    import handlers.tool_executor as te
    from core.b1_quantity_operation import owning
    from db.models import PendingOperation
    from sqlalchemy import select
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    async def forbidden(*a, **k): raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    log = await _log(db, user); snap = await _prod_snapshot(db)
    await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:cf9n1-{user.id}")
    await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:cf9n2-{user.id}")
    ops = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id).order_by(PendingOperation.id))).scalars().all()
    assert len(ops) == 2
    assert ops[0].status != "awaiting_answer", "the old ask was not superseded"
    owned = await owning(db, user)
    assert owned is not None and owned.operation_id == ops[1].operation_id


@pytest.mark.asyncio
async def test_an_expired_ask_ignores_free_text_but_a_tap_still_lands(db, make_user, monkeypatch):
    """B-1's contract, applied to the bound ask: after expiry, unaddressed
    prose is a NEW report (left alone, no write); an addressed tap is still an
    answer to the question it names."""
    import handlers.tool_executor as te
    from datetime import timedelta
    from core import b1_answer_turn
    from core.clarification_answer import Outcome
    from core.clock import now as _now
    from db.models import PendingOperation
    from sqlalchemy import select, update
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    async def forbidden(*a, **k): raise AssertionError("legacy executor invoked")
    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    log = await _log(db, user); snap = await _prod_snapshot(db)
    ex = await _open_bound_ask(db, user, log, snap, monkeypatch, turn_id=f"ios:cf9e-{user.id}")
    await db.execute(update(PendingOperation).where(PendingOperation.user_id == user.id)
                     .values(expires_at=_now() - timedelta(hours=1)))
    await db.commit()
    assert await b1_answer_turn.handle(db, user=user, source_turn_id=f"e1-{user.id}",
                                       message="had some rice") is None
    assert await _rows(db, log) == []
    wire = ex.calls[0].correction["interaction"]; field = wire["groups"][0]["fields"][0]
    two = next(o for o in field["options"] if o["option_id"] == "opt_label_serving_2")
    t = await b1_answer_turn.handle(db, user=user, source_turn_id=f"e2-{user.id}",
                                    field_id=field["field_id"], option_id=two["option_id"], revision=0)
    assert t is not None and t.outcome is Outcome.APPLIED, t
    await db.commit()
    rows = await _rows(db, log)
    assert len(rows) == 1 and rows[0]["product_evidence_id"] == snap.id
