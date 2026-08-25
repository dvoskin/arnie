"""⭐ B-1.8d #4 — A STALE UNDO CANNOT CLOBBER NEWER WORK *(preregistered, Danny)*.

    correction A   (identity:  chicken breast -> chicken thigh)
    correction B   (quantity:  150 g -> 300 g)
    undo A         (the card for A still on screen; plan_for_event(A))
        -> MUST NOT erase B

FOR UPDATE serialises simultaneous writers. It does not prove that an OLD
historical inverse is still valid against a NEWER row state — A's inverse is
"put back the whole before-A state", which is a state B has since moved on
from. Applying it silently would restore the breast at 150 g and throw B
away, while the user thinks they only undid the identity.

The guard is a CURRENT-TIP check: the inverse of event A may only be applied
while A is the row's newest ledger event. Otherwise: StaleUndo, non-mutating,
and the user is told to undo the newer correction first (a real chain).

Reachable through a SHIPPED path: `plan_for_event` is the tap-to-undo backend
and targets the event the user pointed at, not the newest one.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from core.canonical_correction import (CORRECTION_SOURCE, StaleUndo,
                                       correct_identity, correct_quantity,
                                       restore_recorded_state)
from tests.trusted_memory_fixture import trusted  # noqa: E402

_COLS = ("parsed_food_name", "quantity", "calories", "protein", "carbs",
         "fats", "fiber", "sugar", "sodium", "micronutrients_json",
         "pricing_rung", "nutrition_evidence_id", "source_basis",
         "basis_evidence_id", "conversion_evidence_ids_json", "source_amount",
         "source_unit", "scaling_factor", "resolved_grams",
         "product_evidence_id", "estimated_flag", "micros_estimated",
         "alcohol_units", "processing_level")


async def _canonical_row(db, user, *, name, quantity="150 g", calories=200.0):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    meal = ResolvedMeal(
        operation_id=f"stale_{user.id}_{name}", revision=0, user_id=user.id,
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
        FoodEntry.parsed_food_name == name,
    ).order_by(FoodEntry.id.desc()))).scalars().first()


async def _remember(db, user, name, per100g, fdc):
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    db.add(trusted(db, UserFoodMatch(
        user_id=user.id, name_norm=memory_key(name, ""), display_name=name,
        cal_100=per100g["calories"], protein_100=per100g["protein"],
        carbs_100=per100g["carbs"], fat_100=per100g["fat"], fdc_id=fdc,
        confidence="exact")))
    await db.commit()


async def _row_state(db, row_id):
    from db.models import FoodEntry
    t = FoodEntry.__table__
    r = (await db.execute(select(t).where(t.c.id == row_id))).mappings().one()
    return {k: r[k] for k in _COLS}


async def _correction_event(db, row_id, *, nth: int):
    from db.models import LedgerEvent
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE).order_by(LedgerEvent.id)
    )).scalars().all()
    return events[nth]


def _before_from(plan):
    inp = plan["tool_calls"][0]["input"]
    return {k: v for k, v in inp.items() if k not in ("entry_id", "source", "food_hint")}


@pytest.mark.asyncio
async def test_undo_of_a_after_b_is_refused_and_b_survives(db, make_user):
    """A: identity. B: quantity. Undo A via the SHIPPED tap-to-undo backend
    (plan_for_event(A)) -> StaleUndo; the row is byte-identical to the
    post-B state; no restore event was written."""
    from core.ledger_undo import plan_for_event
    from db.models import LedgerEvent

    user = await make_user()
    row = await _canonical_row(db, user, name=f"Chicken breast u{user.id}")
    await _remember(db, user, f"Chicken thigh u{user.id}",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc=f"97{user.id}")
    row_id = int(row.id)

    # A — identity
    a = await correct_identity(db, user=user, entry_id=row_id,
                               new_identity=f"Chicken thigh u{user.id}",
                               idempotency=("t_A", "actually thigh"))
    assert a is not None
    event_a = await _correction_event(db, row_id, nth=0)
    # B — quantity, AFTER A
    b = await correct_quantity(db, user=user, entry_id=row_id,
                               new_quantity_text="300 g",
                               idempotency=("t_B", "make it 300 g"))
    assert b is not None
    after_b = await _row_state(db, row_id)
    assert after_b["quantity"] == "300 g"
    assert after_b["parsed_food_name"] == f"Chicken thigh u{user.id}"

    # the user taps Undo on A's card
    plan = await plan_for_event(db, user, event_a.id)
    assert plan is not None and plan["tool_calls"][0]["name"] == "update_food_entry"
    with pytest.raises(StaleUndo):
        await restore_recorded_state(db, user=user, entry_id=row_id,
                                     before=_before_from(plan),
                                     idempotency=("t_undo_A", "undo"))
    await db.rollback()

    assert await _row_state(db, row_id) == after_b, \
        "the stale undo of A erased B (breast at 150 g would be a hybrid of two rollbacks)"
    restores = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id,
        LedgerEvent.source == "ledger_undo:canonical"))).scalars().all()
    assert restores == []


@pytest.mark.asyncio
async def test_the_chain_undoes_in_order_b_then_a(db, make_user):
    """The honest path: only the NEWEST event's inverse applies. Undo B (the
    tip) restores EXACTLY the post-A state; a redelivered undo-B under the
    same turn is a replay, not a second write."""
    from core.ledger_undo import plan_for_event

    user = await make_user()
    row = await _canonical_row(db, user, name=f"Chicken breast u{user.id}")
    await _remember(db, user, f"Chicken thigh u{user.id}",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc=f"98{user.id}")
    row_id = int(row.id)

    await correct_identity(db, user=user, entry_id=row_id,
                           new_identity=f"Chicken thigh u{user.id}",
                           idempotency=("t_A2", "thigh"))
    after_a = await _row_state(db, row_id)
    await correct_quantity(db, user=user, entry_id=row_id,
                           new_quantity_text="300 g", idempotency=("t_B2", "300"))
    event_b = await _correction_event(db, row_id, nth=1)

    # undo B — the tip — is valid and restores EXACTLY post-A
    plan_b = await plan_for_event(db, user, event_b.id)
    restored = await restore_recorded_state(db, user=user, entry_id=row_id,
                                            before=_before_from(plan_b),
                                            idempotency=("t_undo_B", "undo"))
    assert restored
    assert await _row_state(db, row_id) == after_a

    # and a SECOND delivery of the same undo-B tap is a replay, not a second write
    again = await restore_recorded_state(db, user=user, entry_id=row_id,
                                         before=_before_from(plan_b),
                                         idempotency=("t_undo_B", "undo"))
    assert again is None
    assert await _row_state(db, row_id) == after_a


@pytest.mark.asyncio
async def test_a_redelivered_undo_under_a_new_turn_id_is_stale_not_double(
        db, make_user):
    """Undo A (valid, A is the tip). The client retries the tap with a NEW
    turn id (so the claim cannot catch it). The tip is now A's RESTORE event,
    so A's inverse is stale -> refused. Without the tip guard this would
    re-apply the same before-state — harmless-looking here, but it is the
    same door B walks through above."""
    from core.ledger_undo import plan_for_event

    user = await make_user()
    row = await _canonical_row(db, user, name=f"Chicken breast u{user.id}")
    await _remember(db, user, f"Chicken thigh u{user.id}",
                    {"calories": 209.0, "protein": 26.0, "carbs": 0.0, "fat": 11.0},
                    fdc=f"99{user.id}")
    row_id = int(row.id)
    before = await _row_state(db, row_id)
    await correct_identity(db, user=user, entry_id=row_id,
                           new_identity=f"Chicken thigh u{user.id}",
                           idempotency=("t_A3", "thigh"))
    event_a = await _correction_event(db, row_id, nth=0)
    plan = await plan_for_event(db, user, event_a.id)
    assert await restore_recorded_state(db, user=user, entry_id=row_id,
                                        before=_before_from(plan),
                                        idempotency=("t_undo_A3", "undo"))
    assert await _row_state(db, row_id) == before
    with pytest.raises(StaleUndo):
        await restore_recorded_state(db, user=user, entry_id=row_id,
                                     before=_before_from(plan),
                                     idempotency=("t_undo_A3_retry", "undo"))
    await db.rollback()
    assert await _row_state(db, row_id) == before


@pytest.mark.asyncio
async def test_an_undo_that_names_no_event_is_refused(db, make_user):
    """A before-state with no `undoes_event_id` cannot prove it is current.
    Refused — the unguarded restore is exactly the stale-undo door."""
    user = await make_user()
    row = await _canonical_row(db, user, name=f"Chicken breast u{user.id}")
    with pytest.raises(StaleUndo):
        await restore_recorded_state(db, user=user, entry_id=int(row.id),
                                     before={"quantity": "1 g"})
