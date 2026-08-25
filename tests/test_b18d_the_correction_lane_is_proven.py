"""⭐ B-1.8d — THE CORRECTION LANE, PROVEN. Semantics FROZEN at c2.3; this file
is adversarial proof only *(Danny)*:

    1. APPLY       quantity · identity · product variant · preparation ·
                   identity+quantity — deterministic, one write each
    2. REPLAY      same turn twice -> ONE effective mutation, ONE correction
                   event, ONE completed claim — every kind
    3. UNDO        exact pre-correction row: panel + receipt + metadata,
                   explicit NULLs — the product-variant kind (others pinned
                   in their own files)
    4. STALE UNDO  tests/test_a_stale_undo_cannot_erase_newer_work.py
    5. CRASH       Postgres-only, three windows, identity+quantity AND restore
                   -> no partial row/event/claim; retry succeeds exactly once
    6. CONCURRENCY tests/test_a_correction_survives_its_own_history.py
                   (FOR UPDATE chain, Postgres)
    7. E2E         real stage routing; a canonical refusal NEVER reaches the
                   legacy executor (instrumented to fail if invoked)
    8. ROLLBACK    the route decides by OWNERSHIP, not by flag: a legacy row
                   on the same turn shape goes to legacy untouched, so
                   "rollback" of the lane = the legacy path it never left.
                   Production canary is gated on the manual deploy +
                   /health schema.in_sync (see board).

Every "N == 1" below is asserted from the DATABASE — rows, ledger events,
idempotency records — never from a return value.
"""
from __future__ import annotations

import datetime as dt
import os

import pytest
from sqlalchemy import select

from core.canonical_correction import (CORRECTION_SOURCE, CorrectionRefused,
                                       StaleUndo, correct_preparation,
                                       restore_recorded_state,
                                       select_product_variant)
from tests.trusted_memory_fixture import trusted  # noqa: E402

_COLS = ("parsed_food_name", "quantity", "calories", "protein", "carbs",
         "fats", "fiber", "sugar", "sodium", "micronutrients_json",
         "pricing_rung", "nutrition_evidence_id", "source_basis",
         "basis_evidence_id", "conversion_evidence_ids_json", "source_amount",
         "source_unit", "scaling_factor", "resolved_grams",
         "product_evidence_id", "estimated_flag", "micros_estimated",
         "alcohol_units", "processing_level")


# ── harness (the same shapes the B-1.8b twins use) ──────────────────────────

class _Req:
    def __init__(self, text, turn_id):
        self.text, self.turn_id = text, turn_id
        self.metadata = {}


class _Validation:
    def __init__(self, ops):
        self.approved_operations = ops


async def _run(db, user, ops, text, turn_id):
    from core.turns.stages.execute_native import NativeExecutionStage
    req = _Req(text, turn_id)
    req.metadata = {"db": db, "user": user, "today_log": None}
    return await NativeExecutionStage().run(req, validation=_Validation(ops))


async def _canonical_row(db, user, *, name, quantity="150 g", calories=200.0,
                         **panel):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    meal = ResolvedMeal(
        operation_id=f"b18d_{user.id}_{name}_{quantity}", revision=0,
        user_id=user.id, logging_day=dt.date(2026, 8, 18),
        user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=calories, protein=10.0, carbs=5.0, fats=8.0,
            quantity_text=quantity,
            attributes={"pricing": {"rung": "estimate", "evidence_id": "",
                                    "basis": "per_portion"}}, **panel),))
    await write_canonical_meal(db, operation=DirectOperation(meal),
                               resolved_meal=meal)
    await db.commit()
    return (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == name,
    ).order_by(FoodEntry.id.desc()))).scalars().first()


async def _legacy_row(db, user, *, name="Legacy toast", quantity="2 slices"):
    """A row LEGACY created (created event names a legacy source)."""
    from db.queries import add_food_entry, get_or_create_log_for_date
    log = await get_or_create_log_for_date(db, user.id, dt.date(2026, 8, 18))
    entry = await add_food_entry(
        db, log.id, ledger_source="legacy:test", user_id=user.id,
        parsed_food_name=name, quantity=quantity, calories=160.0,
        protein=5.0, carbs=30.0, fats=2.0)
    await db.commit()
    return entry


async def _remember(db, user, name, per100g, fdc):
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    db.add(trusted(db, UserFoodMatch(
        user_id=user.id, name_norm=memory_key(name, ""), display_name=name,
        cal_100=per100g["calories"], protein_100=per100g["protein"],
        carbs_100=per100g["carbs"], fat_100=per100g["fat"], fdc_id=fdc,
        confidence="exact")))
    await db.commit()


async def _snap(db, code="70004199", kcal_serving=110):
    from skills.nutrition.product_store import append_product_evidence
    return await append_product_evidence(db, record={
        "code": code, "product_name": "Barebell", "serving_size": "55.0g",
        "serving_quantity": 55, "serving_quantity_unit": "g", "rev": 1,
        "last_modified_t": 1, "nutrition_data_per": "100g",
        "nutriments": {"energy-kcal_100g": round(kcal_serving / 0.55, 1),
                       "proteins_100g": 20, "carbohydrates_100g": 18,
                       "fat_100g": 7.3, "energy-kcal_serving": kcal_serving,
                       "proteins_serving": 11, "carbohydrates_serving": 9.9,
                       "fat_serving": 4}}, serving_unit="bar")


async def _product_universe(db, user, snapshot, *, label):
    from core import candidate_repository as repo
    from core.semantics import (CandidateSet, EvidenceContext,
                                ExactProductCandidate)
    from skills.nutrition.product_variant_clarification import (options_for,
                                                                reopen)
    op = f"op:b18d:{user.id}"
    cand = ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                                 product_evidence_id=snapshot.id, label=label)
    set_id = await repo.ensure_candidate_set(db, CandidateSet(
        candidate_set_id=f"cs:b18d:{user.id}", operation_id=op, user_id=user.id,
        context=EvidenceContext(user_id=user.id, canonical_entity_id="",
                                product_variant_id=None),
        interaction_revision=0, field_id="product_variant",
        generator_version="product_variant_reopen_v1",
        generation_input_fingerprint="fp", candidates=(cand,),
        candidate_kind="product"))
    await db.commit()
    universe = await reopen(db, operation_id=op, user_id=user.id,
                            candidate_set_id=set_id)
    option = options_for(universe, event_id="ev1",
                         field_id=f"{op}:ev1:product_variant:0")[0]
    return op, set_id, option.patch


async def _state(db, row_id):
    from db.models import FoodEntry
    t = FoodEntry.__table__
    r = (await db.execute(select(t).where(t.c.id == row_id))).mappings().one()
    return {k: r[k] for k in _COLS}


async def _counts(db, row_id, user_id, *, command="correction",
                  source=CORRECTION_SOURCE):
    """(correction events on the row, completed claims for the user/command)."""
    from db.models import IdempotencyRecord, LedgerEvent
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == source))).scalars().all()
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.command == command))).scalars().all()
    return len(events), sum(1 for c in claims if c.status == "completed")


@pytest.fixture
def no_legacy(monkeypatch):
    """The legacy executor MUST NOT run for a canonically owned row. If the
    stage ever falls through, this fixture turns the fall-through into a
    named failure instead of a silent second authority."""
    import handlers.tool_executor as te
    calls = []

    async def _forbidden(*a, **k):
        calls.append(a)
        raise AssertionError("legacy execute_tool_calls was invoked for a "
                             "canonically owned row — refusal fell through")
    monkeypatch.setattr(te, "execute_tool_calls", _forbidden)
    return calls


# ═════ 1. APPLY + 2. REPLAY — every kind, through the stage where routed ════

@pytest.mark.asyncio
async def test_apply_and_replay_quantity(db, make_user, no_legacy):
    from core.turns.stages.execute_native import ExactlyOnceRefusal
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Egg u{user.id}", quantity="2 eggs",
                               calories=180.0)
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": row.id, "quantity": "3 eggs"}}]
    r = await _run(db, user, ops, "actually 3 eggs", f"t:q:{user.id}")
    assert r.calls[0].committed
    with pytest.raises(ExactlyOnceRefusal):
        await _run(db, user, ops, "actually 3 eggs", f"t:q:{user.id}")
    s = await _state(db, row.id)
    assert s["quantity"] == "3 eggs" and s["calories"] == pytest.approx(270.0)
    assert await _counts(db, row.id, user.id) == (1, 1)


@pytest.mark.asyncio
async def test_apply_and_replay_identity_plus_quantity_is_one_write(
        db, make_user, no_legacy):
    """identity + quantity in ONE op -> ONE row write, ONE event, ONE claim,
    priced once at the NEW quantity on the rebound evidence."""
    from core.turns.stages.execute_native import ExactlyOnceRefusal
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Chicken breast u{user.id}")
    await _remember(db, user, f"Chicken thigh u{user.id}",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc=f"81{user.id}")
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": row.id, "food_name": f"Chicken thigh u{user.id}",
                      "quantity": "200 g",
                      # the interpreter's re-guessed numbers: IGNORED, never routed away
                      "calories": 999.0, "protein": 1.0}}]
    r = await _run(db, user, ops, "actually chicken thigh, 200 g", f"t:iq:{user.id}")
    assert r.calls[0].committed
    with pytest.raises(ExactlyOnceRefusal):
        await _run(db, user, ops, "actually chicken thigh, 200 g", f"t:iq:{user.id}")
    s = await _state(db, row.id)
    assert s["parsed_food_name"] == f"Chicken thigh u{user.id}"
    assert s["quantity"] == "200 g"
    assert s["calories"] == pytest.approx(418.0)          # 209/100 g x 200 g, not 999
    assert s["pricing_rung"] == "memory"
    assert await _counts(db, row.id, user.id) == (1, 1)


@pytest.mark.asyncio
async def test_apply_and_replay_product_variant(db, make_user):
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Protein bar u{user.id}",
                               quantity="2 bars")
    snap = await _snap(db)
    op, set_id, patch = await _product_universe(db, user, snap,
                                                label=f"Barebell u{user.id}")
    idem = (f"t:pv:{user.id}", "the Barebell one")
    first = await select_product_variant(db, user=user, entry_id=row.id, patch=patch,
                                         operation_id=op, candidate_set_id=set_id,
                                         idempotency=idem)
    assert first is not None
    again = await select_product_variant(db, user=user, entry_id=row.id, patch=patch,
                                         operation_id=op, candidate_set_id=set_id,
                                         idempotency=idem)
    assert again is None
    s = await _state(db, row.id)
    assert s["product_evidence_id"] == snap.id and s["calories"] == pytest.approx(220.0)
    assert await _counts(db, row.id, user.id) == (1, 1)


@pytest.mark.asyncio
async def test_apply_and_replay_preparation(db, make_user):
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}")
    await _remember(db, user, f"chicken u{user.id}, fried",
                    {"calories": 246.0, "protein": 27.0, "carbs": 8.0, "fat": 12.0},
                    fdc=f"82{user.id}")
    idem = (f"t:prep:{user.id}", "actually fried")
    assert await correct_preparation(db, user=user, entry_id=row.id,
                                     preparation_id="fried", idempotency=idem)
    assert await correct_preparation(db, user=user, entry_id=row.id,
                                     preparation_id="fried", idempotency=idem) is None
    s = await _state(db, row.id)
    assert s["parsed_food_name"] == f"chicken u{user.id}, fried"
    assert await _counts(db, row.id, user.id) == (1, 1)


# ═════ 3. UNDO EXACT — the product-variant kind (receipt incl. snapshot id) ══

@pytest.mark.asyncio
async def test_undo_of_a_product_variant_selection_restores_the_exact_row(
        db, make_user):
    from core.ledger_undo import plan_for_event
    from db.models import LedgerEvent
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Protein bar u{user.id}",
                               quantity="2 bars", fiber=2.0)
    row_id = int(row.id)
    before = await _state(db, row_id)
    snap = await _snap(db)
    op, set_id, patch = await _product_universe(db, user, snap,
                                                label=f"Barebell u{user.id}")
    await select_product_variant(db, user=user, entry_id=row_id, patch=patch,
                                 operation_id=op, candidate_set_id=set_id)
    mid = await _state(db, row_id)
    assert mid["product_evidence_id"] == snap.id and mid["fiber"] != 2.0
    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.source == CORRECTION_SOURCE
    ))).scalars().one()
    plan = await plan_for_event(db, user, event.id)
    inp = plan["tool_calls"][0]["input"]
    assert "product_evidence_id" in inp and inp["product_evidence_id"] is None, \
        "the snapshot binding the selection ADDED must be cleared by undo"
    await restore_recorded_state(
        db, user=user, entry_id=row_id,
        before={k: v for k, v in inp.items() if k not in ("entry_id", "source", "food_hint")},
        idempotency=(f"t:undo:pv:{user.id}", "undo"))
    after = await _state(db, row_id)
    for k, v in before.items():
        assert after[k] == v, f"{k}: before={v!r} after-undo={after[k]!r}"


# ═════ 7. E2E — refusal stays canonical; legacy is never the fallback ═══════

@pytest.mark.asyncio
async def test_a_canonical_refusal_propagates_and_never_reaches_legacy(
        db, make_user, no_legacy):
    """Identity repair with NO local evidence -> CorrectionRefused PROPAGATES
    out of the stage (A8: no handler), the row is byte-identical, no event, no
    claim — and the legacy executor was never invoked (fixture would raise a
    different, named AssertionError if it had been)."""
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Mystery stew u{user.id}")
    row_id = int(row.id)
    before = await _state(db, row_id)
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": row_id, "food_name": f"Unknowable dish u{user.id}",
                      "calories": 500.0}}]
    with pytest.raises(CorrectionRefused):
        await _run(db, user, ops, "actually the unknowable dish", f"t:ref:{user.id}")
    await db.rollback()
    await db.refresh(user)
    assert await _state(db, row_id) == before
    assert await _counts(db, row_id, user.id) == (0, 0)
    assert no_legacy == []


@pytest.mark.asyncio
async def test_a_stale_undo_through_the_stage_is_refused_and_never_legacy(
        db, make_user, no_legacy):
    """The stale-event twin, END TO END: correction A (identity), correction B
    (quantity), then the undo plan for A arrives as a real turn (source
    ledger_undo:*) -> StaleUndo propagates; B survives; legacy untouched."""
    from core.ledger_undo import plan_for_event
    from db.models import LedgerEvent
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Chicken breast u{user.id}")
    row_id = int(row.id)
    await _remember(db, user, f"Chicken thigh u{user.id}",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc=f"83{user.id}")
    a = await _run(db, user, [{"name": "update_food_entry", "input": {
        "entry_id": row_id, "food_name": f"Chicken thigh u{user.id}"}}],
        "actually thigh", f"t:A:{user.id}")
    assert a.calls[0].committed
    event_a = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.source == CORRECTION_SOURCE)
        .order_by(LedgerEvent.id))).scalars().first()
    b = await _run(db, user, [{"name": "update_food_entry", "input": {
        "entry_id": row_id, "quantity": "300 g"}}], "make it 300", f"t:B:{user.id}")
    assert b.calls[0].committed
    after_b = await _state(db, row_id)

    plan = await plan_for_event(db, user, event_a.id)
    with pytest.raises(StaleUndo):
        await _run(db, user, plan["tool_calls"], "undo", f"t:undoA:{user.id}")
    await db.rollback()
    await db.refresh(user)
    assert await _state(db, row_id) == after_b
    assert no_legacy == []


# ═════ 8. ROLLBACK — ownership decides; a legacy row is legacy's, untouched ═

@pytest.mark.asyncio
async def test_a_legacy_row_on_the_same_turn_shape_is_not_routed_canonical(
        db, make_user):
    """The lane has no flag to roll back: it owns rows whose created event
    names canonical:*, and nothing else. `_correction_route` — the PURE
    ownership decision the stage makes before any claim — returns None for a
    legacy row on the SAME op shape, which is the untouched legacy path. The
    canonical row beside it routes. Rollback of the lane is therefore not a
    switch to flip: it is the ownership predicate, and every legacy row is
    already on the other side of it."""
    from core.turns.stages.execute_native import NativeExecutionStage
    stage = NativeExecutionStage()
    user = await make_user()
    legacy = await _legacy_row(db, user)
    canonical = await _canonical_row(db, user, name=f"Toast u{user.id}",
                                     quantity="2 slices")
    shape = lambda eid: [{"name": "update_food_entry",
                          "input": {"entry_id": eid, "quantity": "3 slices"}}]
    assert await stage._correction_route(db, user, shape(legacy.id)) is None
    routed = await stage._correction_route(db, user, shape(canonical.id))
    assert routed is not None and routed[0] == canonical.id
    assert await _counts(db, legacy.id, user.id) == (0, 0)


# ═════ 5. CRASH TWINS — POSTGRES ONLY (sqlite is not an instrument here) ════

_PG = os.getenv("TEST_POSTGRES_URL")
_needs_pg = pytest.mark.skipif(
    not _PG, reason="transaction-boundary proof needs a real Postgres "
                    "(TEST_POSTGRES_URL); pysqlite commits the outer txn on "
                    "savepoint release. Do not un-skip on sqlite.")


@pytest.fixture
async def pg_db():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from db.database import Base, make_engine
    engine = make_engine(_PG.replace("+asyncpg", "+psycopg"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _pg_user(pg_db, tag):
    from db.models import User
    u = User(telegram_id=f"pg-b18d-{tag}", name="pg")
    pg_db.add(u); await pg_db.commit()
    return u


async def _nothing_durable(db, row_id, user_id, before, *, source,
                           command="correction"):
    from db.models import IdempotencyRecord, LedgerEvent
    assert await _state(db, row_id) == before, "a partial row change survived"
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == source))).scalars().all()
    assert events == [], "a ledger event survived the crash"
    # scoped to THIS command: the restore twin's earlier correction claim is
    # legitimately completed and must not be mistaken for a leaked one
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.command == command))).scalars().all()
    assert not any(c.status == "completed" for c in claims), \
        "a completed claim survived a crash whose work did not"


@_needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["reservation", "staged", "before_commit"])
async def test_identity_plus_quantity_crash_windows_leave_nothing_then_retry_once(
        pg_db, monkeypatch, window):
    """identity+quantity through the stage; crash injected at (a) right after
    the claim reservation, (b) after the row+event are staged, (c) at the
    commit itself. Each: no partial row / event / completed claim; the retry
    of the SAME turn succeeds exactly once."""
    db = pg_db
    import db.queries as queries

    user = await _pg_user(db, f"iq-{window}")
    row = await _canonical_row(db, user, name="Chicken breast")
    row_id, user_id = int(row.id), int(user.id)
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc="8400")
    before = await _state(db, row_id)
    ops = [{"name": "update_food_entry", "input": {
        "entry_id": row_id, "food_name": "Chicken thigh", "quantity": "200 g"}}]

    if window == "reservation":
        import core.canonical_pricing_inputs as inputs
        async def _crash(*a, **k):
            raise RuntimeError("simulated crash after reservation")
        monkeypatch.setattr(inputs, "assemble", _crash)
    elif window == "staged":
        real_complete = queries._complete_claim_in_txn
        async def _crash(db_, *a, **k):
            # row + event staged; the claim completion never happens
            raise RuntimeError("simulated crash after staging")
        monkeypatch.setattr(queries, "_complete_claim_in_txn", _crash)
    else:
        real_complete = queries._complete_claim_in_txn
        async def _crash(db_, *a, **k):
            await real_complete(db_, *a, **k)
            await db_.rollback()
            raise RuntimeError("simulated crash before commit")
        monkeypatch.setattr(queries, "_complete_claim_in_txn", _crash)

    with pytest.raises(RuntimeError, match="simulated crash"):
        await _run(db, user, ops, "actually thigh 200 g", f"pg:iq:{window}")
    monkeypatch.undo()
    await db.rollback()
    await db.refresh(user)
    await _nothing_durable(db, row_id, user_id, before, source=CORRECTION_SOURCE)

    r = await _run(db, user, ops, "actually thigh 200 g", f"pg:iq:{window}")
    assert r.calls[0].committed
    s = await _state(db, row_id)
    assert s["parsed_food_name"] == "Chicken thigh" and s["quantity"] == "200 g"
    assert s["calories"] == pytest.approx(418.0)
    assert await _counts(db, row_id, user_id) == (1, 1)


@_needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["staged", "before_commit"])
async def test_restore_crash_windows_leave_nothing_then_retry_once(
        pg_db, monkeypatch, window):
    """UNDO (restore) through the stage: crash after staging / at commit ->
    the corrected row stands (undo did NOT half-apply), no restore event, no
    completed restore claim; the retried undo turn applies exactly once."""
    db = pg_db
    import db.queries as queries
    from core.ledger_undo import plan_for_event
    from db.models import LedgerEvent

    user = await _pg_user(db, f"undo-{window}")
    row = await _canonical_row(db, user, name="Chicken breast", fiber=1.0)
    row_id, user_id = int(row.id), int(user.id)
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc="8500")
    original = await _state(db, row_id)
    a = await _run(db, user, [{"name": "update_food_entry", "input": {
        "entry_id": row_id, "food_name": "Chicken thigh"}}], "thigh", "pg:A")
    assert a.calls[0].committed
    corrected = await _state(db, row_id)
    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.source == CORRECTION_SOURCE
    ))).scalars().one()
    plan = await plan_for_event(db, user, event.id)

    real_complete = queries._complete_claim_in_txn
    if window == "staged":
        async def _crash(db_, *a, **k):
            raise RuntimeError("simulated crash after staging")
    else:
        async def _crash(db_, *a, **k):
            await real_complete(db_, *a, **k)
            await db_.rollback()
            raise RuntimeError("simulated crash before commit")
    monkeypatch.setattr(queries, "_complete_claim_in_txn", _crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await _run(db, user, plan["tool_calls"], "undo", f"pg:undo:{window}")
    monkeypatch.undo()
    await db.rollback()
    await db.refresh(user)
    await _nothing_durable(db, row_id, user_id, corrected,
                           source="ledger_undo:canonical", command="restore")

    r = await _run(db, user, plan["tool_calls"], "undo", f"pg:undo:{window}")
    assert r.calls[0].committed
    assert await _state(db, row_id) == original
    assert await _counts(db, row_id, user_id, command="restore",
                         source="ledger_undo:canonical") == (1, 1)
