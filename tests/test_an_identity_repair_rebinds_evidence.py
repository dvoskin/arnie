"""⭐ B-1.8c — AN IDENTITY / PRODUCT-VARIANT REPAIR REBINDS EVIDENCE, THEN PRICES.

    "actually it was the Elite one" / "actually that was chicken thigh"
        -> bind the canonical row (ledger says canonical:*)
        -> keep the row's EXISTING quantity (omitted -> preserved)
        -> assemble() local evidence for the NEW identity  (LOAD, never build)
        -> price() with the ESTIMATE rung WITHHELD — evidence or refuse
        -> receipt rewritten WHOLESALE (new rung, new evidence, new basis)
        -> one transaction, exactly once (the B-1.8b.1 lifecycle)

⛔⛔ THE INTERPRETER'S NUMBERS ARE NEVER ACCEPTED. The correction tool arrives
with re-estimated calories/protein/…; a canonical repair reprices from what
Arnie KNOWS. If nothing local can price the new identity, the answer is a
typed refusal — not the model's guess landing on a canonical row.
"""
from __future__ import annotations

import datetime as dt

import pytest

from core.canonical_correction import (CORRECTION_SOURCE, CorrectionRefused,
                                       NotACanonicalRow, correct_identity)


async def _canonical_row(db, user, *, name, quantity, calories=200.0):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    from sqlalchemy import select

    meal = ResolvedMeal(
        operation_id=f"b18c_{name}_{quantity}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 18), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=calories, protein=10.0, carbs=5.0, fats=8.0,
            quantity_text=quantity,
            attributes={"pricing": {"rung": "estimate", "evidence_id": "",
                                    "basis": "per_portion"}}),))
    await write_canonical_meal(db, operation=DirectOperation(meal),
                               resolved_meal=meal)
    await db.commit()
    return (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == name).order_by(FoodEntry.id.desc())
    )).scalars().first()


async def _remember(db, user, name, per100g, fdc="900001"):
    """A memory row for `name` — the local evidence a rebind can land on."""
    from core.food_intelligence import memory_key   # the same key _memory reads
    from db.models import UserFoodMatch
    row = UserFoodMatch(origin_tier="canonical_settlement", 
        user_id=user.id, name_norm=memory_key(name, ""),
        display_name=name, cal_100=per100g["calories"],
        protein_100=per100g["protein"], carbs_100=per100g["carbs"],
        fat_100=per100g["fat"], fdc_id=fdc, confidence="exact")
    db.add(row); await db.commit()
    return row


@pytest.mark.asyncio
async def test_a_rename_rebinds_to_local_evidence_and_rewrites_the_receipt(db, make_user):
    """"actually that was chicken thigh": the row keeps its 150 g, is repriced
    from the user's OWN memory of chicken thigh, and the receipt is rewritten
    wholesale — new rung, new evidence id, new basis, per-100g factor 1.5."""
    from db.models import FoodEntry, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Chicken breast", quantity="150 g")

    result = await correct_identity(db, user=user, entry_id=row.id,
                                    new_identity="Chicken thigh")
    assert result.rung == "memory"
    assert result.new_identity == "Chicken thigh"

    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.parsed_food_name == "Chicken thigh"
    assert fresh.quantity == "150 g", "the omitted quantity was not preserved"
    assert fresh.calories == pytest.approx(313.5, abs=0.5)  # 209 x 1.5, calories round whole
    assert fresh.protein == pytest.approx(39.0)
    assert fresh.pricing_rung == "memory"
    assert fresh.nutrition_evidence_id == "900001"
    assert fresh.source_basis == "per_100g"
    assert fresh.scaling_factor == pytest.approx(1.5)
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_no_local_evidence_for_the_new_identity_refuses_rather_than_estimates(db, make_user):
    """⛔⛔ THE ESTIMATE RUNG IS WITHHELD. Nothing local knows "dragonfruit
    smoothie"; the repair must REFUSE, and the row must be untouched — a
    correction that lands on the interpreter's guess is not a repair."""
    from db.models import FoodEntry

    user = await make_user()
    row = await _canonical_row(db, user, name="Chicken breast", quantity="150 g")
    with pytest.raises(CorrectionRefused, match="never re-estimate"):
        await correct_identity(db, user=user, entry_id=row.id,
                               new_identity="Dragonfruit smoothie zzq")
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.parsed_food_name == "Chicken breast"
    assert fresh.calories == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_a_variant_repair_rebinds_to_a_product_snapshot(db, make_user):
    """"actually it was the Barebells one" with an exact snapshot: the row is
    rebound to the persisted product evidence and priced from ITS label at the
    row's quantity, and product_evidence_id lands on the receipt."""
    from db.models import FoodEntry
    from skills.nutrition.product_store import append_product_evidence

    user = await make_user()
    snapshot = await append_product_evidence(db, record={
        "code": "70004199", "product_name": "Barebell salty peanut protein bar",
        "brands": "Barebell", "serving_size": "55.0g", "serving_quantity": 55,
        "serving_quantity_unit": "g", "rev": 1, "last_modified_t": 1724712330,
        "nutrition_data_per": "100g",
        "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                       "carbohydrates_100g": 18, "fat_100g": 7.3,
                       "energy-kcal_serving": 110, "proteins_serving": 11,
                       "carbohydrates_serving": 9.9, "fat_serving": 4}},
        serving_unit="bar")
    row = await _canonical_row(db, user, name="Protein bar", quantity="2 bars")

    result = await correct_identity(db, user=user, entry_id=row.id,
                                    new_identity="Barebells salty peanut bar",
                                    product_evidence_id=snapshot.id)
    assert result.rung == "product"
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.calories == pytest.approx(220.0)          # 2 x 110 from the label
    assert fresh.product_evidence_id == snapshot.id
    assert fresh.pricing_rung == "product"
    assert fresh.source_basis == "per_serving"
    assert fresh.quantity == "2 bars"


@pytest.mark.asyncio
async def test_a_legacy_row_is_not_this_slice(db, make_user):
    from db.queries import add_food_entry, get_or_create_log_for_date

    user = await make_user()
    log = await get_or_create_log_for_date(db, user.id, dt.date(2026, 8, 18))
    legacy = await add_food_entry(db, log.id, ledger_source="legacy:ios",
                                  user_id=user.id, parsed_food_name="Toast",
                                  quantity="2 slices", calories=160.0)
    with pytest.raises(NotACanonicalRow):
        await correct_identity(db, user=user, entry_id=legacy.id,
                               new_identity="Bagel")


@pytest.mark.asyncio
async def test_a_repair_never_touches_a_provider(db, make_user, monkeypatch):
    """assemble() is LOAD-NEVER-BUILD; USDA, OFF and the artifact loader are
    poisoned throughout and the rebind still prices from memory."""
    import api.usda as usda
    import skills.nutrition.off as off_mod

    async def _boom(*a, **kw):                            # pragma: no cover
        raise AssertionError("an identity repair reached a provider")
    monkeypatch.setattr(usda, "search_food", _boom)
    monkeypatch.setattr(off_mod, "_get_json", _boom)
    monkeypatch.setattr(off_mod, "fetch_product", _boom)

    user = await make_user()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Chicken breast", quantity="100 g")
    result = await correct_identity(db, user=user, entry_id=row.id,
                                    new_identity="Chicken thigh")
    assert result.changes["calories"] == pytest.approx(209.0)


# ── THE ROUTE: the interpreter's numbers are IGNORED, not routed away ───────

def test_the_route_ignores_the_interpreters_numbers_and_dispatches_by_kind():
    """A correction op arrives with re-estimated calories/protein. B-1.8b
    routed such turns to LEGACY (which would have accepted them). Now they
    are canonical: identity -> rebind repair, quantity -> ratio repair, and
    the numbers are simply never read."""
    from core.turns.stages.execute_native import _correction_input

    identity_op = [{"name": "update_food_entry",
                    "input": {"entry_id": 7, "food_name": "Chicken thigh",
                              "calories": 999, "protein": 99}}]
    inp = _correction_input(identity_op)
    assert inp["food_name"] == "Chicken thigh"
    # nothing downstream reads calories/protein — asserted structurally:
    import inspect
    from core import canonical_correction as cc
    src = inspect.getsource(cc.correct_identity) + inspect.getsource(cc.correct_quantity)
    assert 'inp.get("calories")' not in src and 'fields.get("calories")' not in src


# ── THE THREE P1s, PINNED *(review of 40fcee5)* ─────────────────────────────

@pytest.mark.asyncio
async def test_identity_plus_quantity_is_one_write_one_event_one_claim(db, make_user):
    """P1: "actually chicken thigh, and make it 200 g" — ONE call, priced once
    at 200 g on the rebound evidence. One row mutation, ONE updated event, one
    completed claim. The first cut chained two committing functions."""
    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Chicken breast", quantity="150 g")

    result = await correct_identity(db, user=user, entry_id=row.id,
                                    new_identity="Chicken thigh",
                                    new_quantity_text="200 g",
                                    idempotency=("ios:both-1", "actually chicken thigh, 200 g"))
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.parsed_food_name == "Chicken thigh"
    assert fresh.quantity == "200 g"
    assert fresh.calories == pytest.approx(418.0, abs=0.5)      # 209 x 2.0, once
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated"
    ))).scalars().all()
    assert len(events) == 1, "identity+quantity produced more than one event"
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id))).scalars().all()
    assert len(claims) == 1 and claims[0].status == "completed"


@pytest.mark.asyncio
async def test_a_rebind_replaces_the_whole_receipt_and_panel_including_absence(db, make_user):
    """P1: a rebind is WHOLESALE. The old row carries fiber, sodium, micros,
    resolved_grams, basis evidence, conversion ids and a product snapshot; the
    new evidence supplies NONE of them. Every one must be CLEARED, not left
    over — a row must never describe two foods at once."""
    from db.models import FoodEntry
    from skills.nutrition.product_store import append_product_evidence

    user = await make_user()
    snapshot = await append_product_evidence(db, record={
        "code": "70004199", "product_name": "Barebell", "serving_size": "55.0g",
        "serving_quantity": 55, "serving_quantity_unit": "g", "rev": 1,
        "last_modified_t": 1, "nutrition_data_per": "100g",
        "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                       "carbohydrates_100g": 18, "fat_100g": 7.3,
                       "energy-kcal_serving": 110, "proteins_serving": 11,
                       "carbohydrates_serving": 9.9, "fat_serving": 4}},
        serving_unit="bar")
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Barebells bar", quantity="100 g")
    # Dress the old row with everything a product row would carry.
    from db.queries import MutationAuthority, update_food_entry
    await update_food_entry(
        db, row.id, user.id, authority=MutationAuthority.CANONICAL_OWNER,
        fiber=4.0, sodium=300.0, micronutrients_json='{"iron": 2.0}',
        resolved_grams=92.0, basis_evidence_id="usda:panel:1",
        conversion_evidence_ids_json='["usda:173423"]',
        product_evidence_id=snapshot.id, scaling_factor=1.8)

    await correct_identity(db, user=user, entry_id=row.id,
                           new_identity="Chicken thigh")   # generic; memory row
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.parsed_food_name == "Chicken thigh"
    assert fresh.pricing_rung == "memory"
    for cleared in ("product_evidence_id", "basis_evidence_id",
                    "conversion_evidence_ids_json", "resolved_grams",
                    "micronutrients_json"):
        assert getattr(fresh, cleared) is None, (
            f"{cleared} survived the rebind — the row describes two foods")
    # panel fields the new evidence lacks are cleared too, not inherited
    assert fresh.fiber is None and fresh.sodium is None


@pytest.mark.asyncio
async def test_the_ledger_records_an_explicit_clear_so_replay_reproduces_it(db, make_user):
    """P1: product -> generic clears product_evidence_id 42 -> NULL. The
    `updated` event MUST carry that clear, or the M1.1 replay (created events
    replayed through updated events) reconstructs a row that still points at
    the snapshot. omitted = preserve; null = explicitly clear — in the ledger
    exactly as in the merge contract."""
    import json

    from db.models import FoodEntry, LedgerEvent
    from sqlalchemy import select
    from skills.nutrition.product_store import append_product_evidence

    user = await make_user()
    snapshot = await append_product_evidence(db, record={
        "code": "70004199", "product_name": "Barebell", "serving_size": "55.0g",
        "serving_quantity": 55, "serving_quantity_unit": "g", "rev": 1,
        "last_modified_t": 1, "nutrition_data_per": "100g",
        "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                       "carbohydrates_100g": 18, "fat_100g": 7.3,
                       "energy-kcal_serving": 110, "proteins_serving": 11,
                       "carbohydrates_serving": 9.9, "fat_serving": 4}},
        serving_unit="bar")
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Barebells bar", quantity="100 g")
    from db.queries import MutationAuthority, update_food_entry
    await update_food_entry(db, row.id, user.id,
                            authority=MutationAuthority.CANONICAL_OWNER,
                            product_evidence_id=snapshot.id)

    await correct_identity(db, user=user, entry_id=row.id,
                           new_identity="Chicken thigh")

    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().one()
    changes = json.loads(event.payload_json)["changes"]
    assert "product_evidence_id" in changes and changes["product_evidence_id"] is None, (
        "the ledger dropped the explicit clear — replay cannot reproduce it")

    # And REPLAY the events, the M1.1 way: created -> updated, None = clear.
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id).order_by(LedgerEvent.created_at,
                                                  LedgerEvent.id))).scalars().all()
    state = {}
    for ev in events:
        p = json.loads(ev.payload_json or "{}")
        if ev.event_type == "created":
            state.update({k: v for k, v in p.items()})
        elif ev.event_type == "updated":
            state.update(p.get("changes") or {})       # None APPLIES as a clear
    assert state.get("product_evidence_id") is None
    assert state.get("parsed_food_name") == "Chicken thigh"
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.product_evidence_id is None


# ── THE CRASH TWIN *(Danny)*: identity + quantity, crash before the commit ──
#
# Postgres-only for the reason pinned in test_the_owner_corrects_what_it_owns:
# pysqlite commits the outer transaction on savepoint release, so sqlite is
# not an authoritative instrument for this boundary. Do not un-skip.
_PG = __import__("os").getenv("TEST_POSTGRES_URL")
_needs_pg = pytest.mark.skipif(
    not _PG, reason="transaction-boundary proof: needs a real Postgres "
                    "(TEST_POSTGRES_URL). SQLite is NOT an authoritative "
                    "instrument here — do not un-skip.")


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


@_needs_pg
@pytest.mark.asyncio
async def test_identity_plus_quantity_crash_before_commit_leaves_both_old_and_retry_applies_both(
        pg_db, monkeypatch):
    """identity + quantity, crash after the rebind is computed / before the
    final commit -> OLD identity, OLD quantity, NO correction event, NO
    completed claim. Retry applies BOTH. This is the twin that would have
    caught the two-commit chain: there, the crash left identity NEW, quantity
    OLD, and a completed claim that refused the retry."""
    import json

    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent, User
    from sqlalchemy import select
    import db.queries as queries

    db = pg_db
    user = User(telegram_id="pg-both", name="pg"); db.add(user); await db.commit()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Chicken breast", quantity="150 g")
    row_id, user_id = int(row.id), int(user.id)

    real_complete = queries._complete_claim_in_txn
    async def _crash_at_commit(db_, claim_id, entry_id, daily_log_id):
        await real_complete(db_, claim_id, entry_id, daily_log_id)
        await db_.rollback()
        raise RuntimeError("simulated crash before commit")
    monkeypatch.setattr(queries, "_complete_claim_in_txn", _crash_at_commit)

    with pytest.raises(RuntimeError, match="simulated crash"):
        await correct_identity(db, user=user, entry_id=row_id,
                               new_identity="Chicken thigh",
                               new_quantity_text="200 g",
                               idempotency=("ios:both-crash", "chicken thigh 200 g"))
    monkeypatch.setattr(queries, "_complete_claim_in_txn", real_complete)
    await db.rollback(); await db.refresh(user)

    fresh = (await db.execute(select(FoodEntry).where(FoodEntry.id == row_id)
                              .execution_options(populate_existing=True))).scalar_one()
    assert fresh.parsed_food_name == "Chicken breast", "identity changed despite the crash"
    assert fresh.quantity == "150 g", "quantity changed despite the crash"
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.event_type == "updated"))).scalars().all()
    assert events == []
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id))).scalars().all()
    assert not any(c.status == "completed" for c in claims)

    # The retry — same turn — applies BOTH.
    result = await correct_identity(db, user=user, entry_id=row_id,
                                    new_identity="Chicken thigh",
                                    new_quantity_text="200 g",
                                    idempotency=("ios:both-crash", "chicken thigh 200 g"))
    assert result is not None
    fresh = (await db.execute(select(FoodEntry).where(FoodEntry.id == row_id)
                              .execution_options(populate_existing=True))).scalar_one()
    assert fresh.parsed_food_name == "Chicken thigh" and fresh.quantity == "200 g"
    assert fresh.calories == pytest.approx(418.0, abs=0.5)
