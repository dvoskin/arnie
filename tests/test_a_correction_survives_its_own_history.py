"""⭐ B-1.8d — APPLY -> REPLAY -> UNDO -> CRASH -> CONCURRENT. Not happy paths.

The write semantics were made solid in c.1 (one transaction, wholesale
rebind, explicit clears in the ledger); the second adversarial pass found the
rest: undo restored four macros and produced a HYBRID row; the generic
calorie-ratio rescale ran BEFORE the owner write and rescaled the OLD food's
micros into the NEW food; no row lock let two corrections compute from one
ancestor; an undo through the repair path would RE-PRICE the restored food.
This file proves each is closed, on the real engine where it matters.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from core.canonical_correction import (CORRECTION_SOURCE, correct_identity,
                                       correct_quantity,
                                       restore_recorded_state)
from tests.trusted_memory_fixture import trusted  # noqa: E402


async def _canonical_row(db, user, *, name, quantity, calories=200.0,
                         **extra):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    from sqlalchemy import select

    meal = ResolvedMeal(
        operation_id=f"b18d_{name}_{quantity}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 18), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=calories, protein=10.0, carbs=5.0, fats=8.0,
            fiber=extra.get("fiber"), sugar=extra.get("sugar"),
            sodium=extra.get("sodium"), micros=extra.get("micros"),
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
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    # ⛔ CF23/CF24 — an identity repair must rebind to EVIDENCE, and memory is
    # only evidence when it LINKS to the settlement that produced it. The tier
    # alone stopped meaning anything; `trusted` writes that settlement too.
    row = trusted(db, UserFoodMatch(
        user_id=user.id, name_norm=memory_key(name, ""),
        display_name=name, cal_100=per100g["calories"],
        protein_100=per100g["protein"],
        carbs_100=per100g["carbs"], fat_100=per100g["fat"],
        fdc_id=fdc, confidence="exact"))
    db.add(row); await db.commit()
    return row


def _snapshot(entry) -> dict:
    return {k: getattr(entry, k) for k in (
        "parsed_food_name", "quantity", "calories", "protein", "carbs",
        "fats", "fiber", "sugar", "sodium", "micronutrients_json",
        "pricing_rung", "nutrition_evidence_id", "source_basis",
        "basis_evidence_id", "conversion_evidence_ids_json", "source_amount",
        "source_unit", "scaling_factor", "resolved_grams",
        "product_evidence_id", "estimated_flag", "micros_estimated",
        "alcohol_units", "processing_level")}


# ── #2b: THE OLD FOOD'S MICROS MUST NOT BE RESCALED INTO THE NEW FOOD ───────

@pytest.mark.asyncio
async def test_a_rebind_does_not_rescale_the_old_foods_panel_into_the_new_one(db, make_user):
    """The generic calorie-ratio rescale ran BEFORE the owner write. Old row:
    wine-ish micros {iron: 2, "vitamin_c": 40}, sodium 300. Rebind to chicken
    thigh (memory, no micros). Under the bug: micros = old × (new_kcal/old_kcal),
    sodium likewise — the WINE's iron, rescaled into the CHICKEN. Now: cleared."""
    from db.models import FoodEntry

    user = await make_user()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Red wine", quantity="150 g",
                               calories=125.0, sodium=300.0,
                               micros={"iron": 2.0, "vitamin_c": 40.0})
    # dress the metadata a wine row would carry
    from db.queries import MutationAuthority, update_food_entry
    await update_food_entry(db, row.id, user.id,
                            authority=MutationAuthority.CANONICAL_OWNER,
                            alcohol_units=1.5, processing_level="ultra",
                            estimated_flag=True)

    await correct_identity(db, user=user, entry_id=row.id,
                           new_identity="Chicken thigh")
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.micronutrients_json is None, (
        f"the old food's micros were rescaled into the new food: "
        f"{fresh.micronutrients_json}")
    assert fresh.sodium is None
    # the stale-metadata audit
    assert fresh.alcohol_units is None, "chicken kept the wine's alcohol"
    assert fresh.processing_level is None
    assert fresh.estimated_flag is False, "an evidence rebind stayed estimated"


# ── #3: UNDO RESTORES THE WHOLE ROW, IDENTITY INCLUDED ──────────────────────

@pytest.mark.asyncio
async def test_undo_of_an_identity_repair_restores_the_whole_before_state(db, make_user):
    """chicken breast -> chicken thigh -> undo. Under the bug: the THIGH's
    name and receipt over the BREAST's macros — a hybrid. Now: the row is
    byte-for-byte the pre-correction snapshot, and fields the correction ADDED
    (a resolved_grams, a receipt) are CLEARED by the undo, not preserved."""
    from core.ledger_undo import _invert
    from db.models import FoodEntry, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Chicken breast", quantity="150 g",
                               fiber=1.0, sodium=70.0)
    before = _snapshot(row)

    await correct_identity(db, user=user, entry_id=row.id,
                           new_identity="Chicken thigh")
    mid = await db.get(FoodEntry, row.id); await db.refresh(mid)
    assert mid.parsed_food_name == "Chicken thigh" and mid.pricing_rung == "memory"

    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().one()
    plan = _invert(event)
    assert plan and plan["tool_calls"][0]["name"] == "update_food_entry"
    inp = plan["tool_calls"][0]["input"]
    assert inp["food_name"] == "Chicken breast", "undo did not restore identity"
    assert inp["fiber"] == 1.0 and inp["sodium"] == 70.0
    # fields the correction ADDED must be cleared by the undo:
    assert "nutrition_evidence_id" in inp and inp["nutrition_evidence_id"] is None
    assert "scaling_factor" in inp and inp["scaling_factor"] is None

    restored = await restore_recorded_state(
        db, user=user, entry_id=row.id,
        before={k: v for k, v in inp.items() if k not in ("entry_id", "source")})
    after = await db.get(FoodEntry, row.id); await db.refresh(after)
    got = _snapshot(after)
    for k, v in before.items():
        assert got[k] == v, f"{k}: before={v!r} after-undo={got[k]!r} — hybrid row"


@pytest.mark.asyncio
async def test_undo_of_a_quantity_repair_restores_the_receipt_too(db, make_user):
    """B-1.8b's quantity corrections undid the macros but left the moved
    scaling_factor / resolved_grams behind. Now they roll back with the rest."""
    from core.ledger_undo import _invert
    from db.models import FoodEntry, LedgerEvent
    from sqlalchemy import select
    from db.queries import MutationAuthority, update_food_entry

    user = await make_user()
    row = await _canonical_row(db, user, name="Egg", quantity="2 eggs",
                               calories=180.0)
    await update_food_entry(db, row.id, user.id,
                            authority=MutationAuthority.CANONICAL_OWNER,
                            scaling_factor=0.92, resolved_grams=92.0)
    fresh = await db.get(FoodEntry, row.id); await db.refresh(fresh)
    before = _snapshot(fresh)

    await correct_quantity(db, user=user, entry_id=row.id, new_quantity_text="3 eggs")
    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().one()
    inp = _invert(event)["tool_calls"][0]["input"]
    assert inp["scaling_factor"] == pytest.approx(0.92)
    assert inp["resolved_grams"] == pytest.approx(92.0)
    await restore_recorded_state(
        db, user=user, entry_id=row.id,
        before={k: v for k, v in inp.items() if k not in ("entry_id", "source")})
    after = await db.get(FoodEntry, row.id); await db.refresh(after)
    assert _snapshot(after) == before


# ── UNDO IS A RESTORE, NEVER A REPAIR ───────────────────────────────────────

def test_the_route_sends_a_recorded_replay_to_restore_not_repair():
    """A ledger_undo op naming a canonical row must not reach correct_identity
    (which would RE-PRICE the restored food). The route flags it as a replay."""
    from core.turns.stages.execute_native import _correction_input

    undo_op = [{"name": "update_food_entry",
                "input": {"entry_id": 7, "source": "ledger_undo:v1",
                          "food_name": "Chicken breast", "quantity": "150 g",
                          "calories": 200.0, "nutrition_evidence_id": None}}]
    inp = _correction_input(undo_op)
    assert inp["source"].startswith("ledger_undo:")
    # and the executor's own generic 'drop None' does not apply on this path:
    # restore_recorded_state receives the None and CLEARS. (Behavioural proof
    # is test_undo_of_an_identity_repair_restores_the_whole_before_state.)


# ── #5: CONCURRENT CORRECTIONS FORM A CHAIN, NOT SIBLINGS ───────────────────
#
# Postgres-only: FOR UPDATE is the mechanism and sqlite has none (single-writer
# by construction). SQLite is not an authoritative instrument here.
_PG = __import__("os").getenv("TEST_POSTGRES_URL")
_needs_pg = pytest.mark.skipif(
    not _PG, reason="row-lock proof needs a real Postgres (TEST_POSTGRES_URL); "
                    "sqlite has no FOR UPDATE — do not un-skip")


@_needs_pg
@pytest.mark.asyncio
async def test_two_concurrent_corrections_serialise_into_a_chain():
    """Two sessions each read "2 eggs" and each say "actually 3 eggs". Without
    the lock: both compute 3-from-2, last-writer-wins, and BOTH before-states
    say "2 eggs" — two siblings of one ancestor. With the lock the second waits
    and computes 3-from-3 → 4.5?  No — it reads the committed "3 eggs" and its
    count ratio is 3/3 = 1.0: the SECOND correction is a no-op on an already-
    corrected row, and its before-state says "3 eggs". A chain."""
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from db.database import Base, make_engine
    from db.models import FoodEntry, LedgerEvent, User

    engine = make_engine(_PG.replace("+asyncpg", "+psycopg"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with S() as db:
            user = User(telegram_id="pg-conc", name="pg"); db.add(user); await db.commit()
            row = await _canonical_row(db, user, name="Egg", quantity="2 eggs", calories=180.0)
            row_id, uid = int(row.id), int(user.id)

        async def one(tag):
            async with S() as s:
                u = await s.get(User, uid)
                return await correct_quantity(s, user=u, entry_id=row_id,
                                              new_quantity_text="3 eggs")
        results = await asyncio.gather(one("a"), one("b"))

        async with S() as db:
            fresh = (await db.execute(select(FoodEntry).where(FoodEntry.id == row_id))).scalar_one()
            assert fresh.calories == pytest.approx(270.0), (
                f"concurrent corrections compounded or raced: {fresh.calories}")
            befores = [json.loads(e.payload_json)["before"]["quantity"] for e in
                       (await db.execute(select(LedgerEvent).where(
                           LedgerEvent.entry_id == row_id,
                           LedgerEvent.event_type == "updated")
                           .order_by(LedgerEvent.id))).scalars().all()]
            assert befores == ["2 eggs", "3 eggs"], (
                f"before-states are siblings, not a chain: {befores}")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_redelivered_undo_restores_exactly_once(db, make_user):
    """⛔ P1 *(review of ef796ac)*: the restore branch passed no claim, so the
    same undo turn redelivered produced a SECOND restore mutation and event.
    Now the B-1.8b.1 lifecycle: one restore, one event, one completed claim;
    the replay is refused closed."""
    from core.ledger_undo import _invert
    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    await _remember(db, user, "Chicken thigh",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0})
    row = await _canonical_row(db, user, name="Chicken breast", quantity="150 g")
    await correct_identity(db, user=user, entry_id=row.id, new_identity="Chicken thigh")
    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().one()
    inp = _invert(event)["tool_calls"][0]["input"]
    before = {k: v for k, v in inp.items() if k not in ("entry_id", "source")}

    idem = ("ios:undo-1", "undo")
    first = await restore_recorded_state(db, user=user, entry_id=row.id,
                                         before=before, idempotency=idem)
    again = await restore_recorded_state(db, user=user, entry_id=row.id,
                                         before=before, idempotency=idem)
    assert first is not None and again is None, "the redelivered undo was not refused"

    restores = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == "ledger_undo:canonical"))).scalars().all()
    assert len(restores) == 1
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id,
        IdempotencyRecord.command == "restore"))).scalars().all()
    assert len(claims) == 1 and claims[0].status == "completed"
