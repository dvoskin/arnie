"""⭐ B-1.8c2.3 — SetPreparation: PRESERVE THE ENTITY, REPLACE THE PREPARATION.

    SetPreparation(event, fried) on "Grilled chicken"
        -> lock the canonical row
        -> entity "chicken" preserved STRUCTURALLY (split, not string edit)
        -> preparation replaced: chicken|fried
        -> local evidence for entity+fried, evidence-backed price or refuse
        -> wholesale receipt replacement, one claim / one event / one commit

The twins *(Danny)*:
    grilled chicken + SetPreparation(fried)         -> fried chicken
    grilled chicken + correction "chicken thigh"    -> chicken thigh,
                                                       NOT grilled chicken thigh
    SetPreparation(fried) with no evidence          -> refuse; row byte-identical
    duplicate preparation correction                -> exactly once
    undo preparation correction                     -> exact old snapshot restored
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from core.canonical_correction import (CORRECTION_SOURCE, CorrectionRefused,
                                       correct_identity, correct_preparation,
                                       restore_recorded_state)

_COLS = ("parsed_food_name", "quantity", "calories", "protein", "carbs",
         "fats", "fiber", "sugar", "sodium", "micronutrients_json",
         "pricing_rung", "nutrition_evidence_id", "source_basis",
         "basis_evidence_id", "conversion_evidence_ids_json", "source_amount",
         "source_unit", "scaling_factor", "resolved_grams",
         "product_evidence_id", "estimated_flag", "micros_estimated",
         "alcohol_units", "processing_level")


async def _canonical_row(db, user, *, name, quantity="150 g", calories=200.0,
                         **panel):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    meal = ResolvedMeal(
        operation_id=f"c23_{user.id}_{name}_{quantity}", revision=0,
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


async def _remember(db, user, name, per100g, fdc):
    """A memory row for `name` — the local evidence a rebind can land on.
    Per-user fdc + label: the memory rung quarantines a surface key bound to
    disagreeing records fleet-wide, and these tests share one session."""
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    db.add(UserFoodMatch(origin_tier="canonical_settlement", 
        user_id=user.id, name_norm=memory_key(name, ""), display_name=name,
        cal_100=per100g["calories"], protein_100=per100g["protein"],
        carbs_100=per100g["carbs"], fat_100=per100g["fat"], fdc_id=fdc,
        confidence="exact"))
    await db.commit()


async def _row_state(db, row_id):
    from db.models import FoodEntry
    t = FoodEntry.__table__
    r = (await db.execute(select(t).where(t.c.id == row_id))).mappings().one()
    return {k: r[k] for k in _COLS}


async def _events(db, row_id):
    from db.models import LedgerEvent
    return (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id,
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().all()


# ── TWIN 1: grilled chicken + SetPreparation(fried) -> fried chicken ─────────

@pytest.mark.asyncio
async def test_set_preparation_preserves_the_entity_and_replaces_the_prep(
        db, make_user):
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}")
    # evidence for chicken|fried, THIS user's memory (the composed key)
    await _remember(db, user, f"chicken u{user.id}, fried",
                    {"calories": 246.0, "protein": 27.0, "carbs": 8.0, "fat": 12.0},
                    fdc=f"91{user.id}")

    result = await correct_preparation(db, user=user, entry_id=row.id,
                                       preparation_id="fried",
                                       idempotency=("t_c23_1", "actually fried"))
    assert result is not None and result.rung == "memory"
    after = await _row_state(db, row.id)
    assert after["parsed_food_name"] == f"chicken u{user.id}, fried"
    assert "grilled" not in after["parsed_food_name"].lower(), \
        "the old preparation survived — 'grilled chicken, fried' is two preps on one food"
    assert after["quantity"] == "150 g"                       # omitted -> preserved
    assert after["calories"] == pytest.approx(246.0 * 1.5)
    assert after["pricing_rung"] == "memory"
    assert after["estimated_flag"] is False
    assert len(await _events(db, row.id)) == 1


# ── TWIN 2: grilled chicken + "chicken thigh" -> chicken thigh, NOT grilled ──

@pytest.mark.asyncio
async def test_an_identity_correction_does_not_carry_the_old_preparation(
        db, make_user):
    """"actually it was chicken thigh" on a grilled chicken row: the NEW
    identity replaces WHOLESALE. There is no grilled chicken thigh."""
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}")
    await _remember(db, user, f"Chicken thigh u{user.id}",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc=f"92{user.id}")
    # a grilled-thigh memory row exists too — it must NOT be what gets priced
    await _remember(db, user, f"chicken thigh u{user.id}, grilled",
                    {"calories": 999.0, "protein": 1.0, "carbs": 1.0, "fat": 1.0},
                    fdc=f"93{user.id}")

    result = await correct_identity(db, user=user, entry_id=row.id,
                                    new_identity=f"Chicken thigh u{user.id}")
    assert result.rung == "memory"
    after = await _row_state(db, row.id)
    assert after["parsed_food_name"] == f"Chicken thigh u{user.id}"
    assert "grilled" not in after["parsed_food_name"].lower()
    assert after["calories"] == pytest.approx(209.0 * 1.5, abs=1.0)   # thigh, not grilled thigh (999)


# ── TWIN 3: no evidence -> refuse; row byte-identical ────────────────────────

@pytest.mark.asyncio
async def test_set_preparation_with_no_evidence_refuses_and_leaves_the_row(
        db, make_user):
    """No memory for chicken|fried, no artifact hit for a per-user-suffixed
    entity, ESTIMATE withheld -> CorrectionRefused, and the row is
    byte-identical with zero correction events. Not repriced from the old
    'grilled' evidence, not estimated."""
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}",
                               fiber=1.0, sodium=70.0)
    # the OLD identity has evidence; the NEW one does not
    await _remember(db, user, f"chicken u{user.id}, grilled",
                    {"calories": 165.0, "protein": 31.0, "carbs": 0.0, "fat": 3.6},
                    fdc=f"94{user.id}")
    row_id = int(row.id)                 # captured before the rollback expires the ORM row
    before = await _row_state(db, row_id)
    with pytest.raises(CorrectionRefused):
        await correct_preparation(db, user=user, entry_id=row_id,
                                  preparation_id="fried")
    await db.rollback()
    assert await _row_state(db, row_id) == before, "a refusal mutated the row"
    assert await _events(db, row_id) == []


@pytest.mark.asyncio
async def test_an_unregistered_preparation_is_refused_not_composed_away(
        db, make_user):
    """name_with silently drops an UNKNOWN preparation, which would make
    SetPreparation('sous-vide') a no-op that still wrote a row + event.
    Refused before the lock."""
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}")
    row_id = int(row.id)
    before = await _row_state(db, row_id)
    with pytest.raises(CorrectionRefused, match="not in the registered"):
        await correct_preparation(db, user=user, entry_id=row_id,
                                  preparation_id="sous-vide")
    await db.rollback()
    assert await _row_state(db, row_id) == before
    assert await _events(db, row_id) == []


# ── TWIN 4: duplicate -> exactly once ────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_duplicate_preparation_correction_applies_exactly_once(
        db, make_user):
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}")
    await _remember(db, user, f"chicken u{user.id}, fried",
                    {"calories": 246.0, "protein": 27.0, "carbs": 8.0, "fat": 12.0},
                    fdc=f"95{user.id}")
    idem = ("t_c23_dup", "actually fried")
    first = await correct_preparation(db, user=user, entry_id=row.id,
                                      preparation_id="fried", idempotency=idem)
    assert first is not None
    state = await _row_state(db, row.id)
    again = await correct_preparation(db, user=user, entry_id=row.id,
                                      preparation_id="fried", idempotency=idem)
    assert again is None, "the redelivered turn was applied a second time"
    assert await _row_state(db, row.id) == state
    assert len(await _events(db, row.id)) == 1


# ── TWIN 5: undo -> the exact old snapshot ───────────────────────────────────

@pytest.mark.asyncio
async def test_undo_of_a_preparation_correction_restores_the_old_snapshot(
        db, make_user):
    from core.ledger_undo import _invert
    from db.models import LedgerEvent

    user = await make_user()
    row = await _canonical_row(db, user, name=f"Grilled chicken u{user.id}",
                               fiber=1.0, sodium=70.0)
    await _remember(db, user, f"chicken u{user.id}, fried",
                    {"calories": 246.0, "protein": 27.0, "carbs": 8.0, "fat": 12.0},
                    fdc=f"96{user.id}")
    before = await _row_state(db, row.id)

    await correct_preparation(db, user=user, entry_id=row.id,
                              preparation_id="fried")
    mid = await _row_state(db, row.id)
    assert mid["parsed_food_name"] != before["parsed_food_name"]

    event = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().one()
    plan = _invert(event)
    inp = plan["tool_calls"][0]["input"]
    assert inp["food_name"] == before["parsed_food_name"]
    restored = await restore_recorded_state(
        db, user=user, entry_id=row.id,
        before={k: v for k, v in inp.items() if k not in ("entry_id", "source")})
    assert restored
    after = await _row_state(db, row.id)
    for k, v in before.items():
        assert after[k] == v, f"{k}: before={v!r} after-undo={after[k]!r} — hybrid row"
