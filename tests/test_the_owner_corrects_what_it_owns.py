"""⭐ B-1.8b — THE CANONICAL OWNER CORRECTS WHAT IT OWNS.

The first path ever to exercise `MutationAuthority.CANONICAL_OWNER` — permitted
by the ownership firewall since the salmon-overwrote-chicken incident, and
never called until now. The firewall is UNTOUCHED: legacy's
INFERRED_INTERPRETATION is still refused on the same row, in the same test.

    "actually 3 eggs" on a canonical 2-egg row
        -> bind (ledger names canonical:create) -> repair (ratio 1.5)
        -> merge (omitted size PRESERVED) -> write (one transaction:
           row + totals + `updated` event with the before-state)
        -> never legacy; refusals PROPAGATE.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from core.canonical_correction import (CORRECTION_SOURCE, CorrectionRefused,
                                       NotACanonicalRow, correct_quantity)


async def _canonical_meal(db, user, *, name="Egg", quantity="2 large eggs",
                          calories=180.0, protein=12.6, receipt=None):
    """A canonically owned row, written the way settlement writes it — through
    the writer, so its `created` event names canonical:create."""
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    from sqlalchemy import select

    attributes = {"pricing": receipt} if receipt else {}
    meal = ResolvedMeal(
        operation_id=f"b18b_{name}_{quantity}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 17), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=calories, protein=protein, carbs=1.6, fats=13.2,
            fiber=0.0, sugar=0.4, sodium=190.0,
            quantity_text=quantity, attributes=attributes),))
    await write_canonical_meal(db, operation=DirectOperation(meal),
                               resolved_meal=meal)
    await db.commit()
    return (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == name).order_by(FoodEntry.id.desc())
    )).scalars().first()


@pytest.mark.asyncio
async def test_the_owner_corrects_and_the_receipt_moves(db, make_user):
    """The headline: 2 large eggs -> "actually 3 eggs". Macros × 1.5, size
    PRESERVED in the stored quantity, receipt factor and mass move, totals
    recomputed, `updated` event written under canonical:correction with the
    full before-state — one transaction."""
    from db.models import DailyLog, FoodEntry, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    row = await _canonical_meal(db, user, receipt={
        "rung": "artifact", "evidence_id": "usda:173423",
        "basis": "per_100g", "scaling_factor": 0.92,
        "resolved_grams": 92.0, "source_amount": 100.0, "source_unit": "g"})
    assert row.scaling_factor == pytest.approx(0.92)

    result = await correct_quantity(db, user=user, entry_id=row.id,
                                    new_quantity_text="3 eggs")
    assert result.ratio == pytest.approx(1.5)
    assert result.method == "count_ratio"

    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.calories == pytest.approx(270.0)
    assert fresh.protein == pytest.approx(18.9)
    assert fresh.sodium == pytest.approx(285.0)
    # ⛔⛔ THE FIELD-MERGE CONTRACT: omitted size is PRESERVED.
    assert fresh.quantity == "3 large eggs", fresh.quantity
    # The receipt moved WITH the correction; the evidence did not change.
    assert fresh.scaling_factor == pytest.approx(1.38)
    assert fresh.resolved_grams == pytest.approx(138.0)
    assert fresh.nutrition_evidence_id == "usda:173423"
    assert fresh.pricing_rung == "artifact"

    # Totals recomputed on the day.
    log = await db.get(DailyLog, fresh.daily_log_id)
    await db.refresh(log)
    assert log.total_calories == pytest.approx(270.0)

    # The `updated` event, under the correction lane, carrying the before.
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id,
        LedgerEvent.event_type == "updated"))).scalars().all()
    assert len(events) == 1
    assert events[0].source == CORRECTION_SOURCE
    payload = json.loads(events[0].payload_json)
    assert payload["before"]["calories"] == pytest.approx(180.0)
    assert payload["changes"]["quantity"] == "3 large eggs"


@pytest.mark.asyncio
async def test_a_stated_size_replaces_and_a_conflict_refuses(db, make_user):
    """stated -> replace: 2 large -> "3 large eggs" keeps large. conflicting
    -> refuse: 2 large -> "3 medium eggs" is semantic repair, and it PROPAGATES
    as CorrectionRefused rather than writing anything."""
    from db.models import FoodEntry

    user = await make_user()
    row = await _canonical_meal(db, user)
    before = row.calories

    with pytest.raises(CorrectionRefused, match="semantic repair"):
        await correct_quantity(db, user=user, entry_id=row.id,
                               new_quantity_text="3 medium eggs")
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.calories == pytest.approx(before), (
        "a refused correction wrote something")
    assert fresh.quantity == "2 large eggs"


@pytest.mark.asyncio
async def test_a_legacy_row_is_not_this_slice(db, make_user):
    """A row legacy created keeps its legacy correction path, untouched —
    NotACanonicalRow is ROUTING, not a refusal."""
    from db.queries import add_food_entry, get_or_create_log_for_date

    user = await make_user()
    log = await get_or_create_log_for_date(db, user.id, dt.date(2026, 8, 17))
    legacy = await add_food_entry(db, log.id, ledger_source="legacy:ios",
                                  user_id=user.id, parsed_food_name="Toast",
                                  quantity="2 slices", calories=160.0)
    with pytest.raises(NotACanonicalRow):
        await correct_quantity(db, user=user, entry_id=legacy.id,
                               new_quantity_text="3 slices")


@pytest.mark.asyncio
async def test_the_firewall_still_refuses_legacy_on_the_same_row(db, make_user):
    """⛔⛔ THE FIREWALL IS UNTOUCHED. The very row the owner just corrected
    still refuses INFERRED_INTERPRETATION — the salmon authority — with a
    mutation_rejected event. B-1.8b exercised the reserved authority; it did
    not widen who may write."""
    from db.models import LedgerEvent
    from db.queries import (CrossOwnerMutation, MutationAuthority,
                            update_food_entry)
    from sqlalchemy import select

    user = await make_user()
    row = await _canonical_meal(db, user)
    await correct_quantity(db, user=user, entry_id=row.id,
                           new_quantity_text="3 eggs")

    with pytest.raises(CrossOwnerMutation):
        await update_food_entry(
            db, row.id, user.id, ledger_source="structured_food:v2",
            authority=MutationAuthority.INFERRED_INTERPRETATION,
            calories=999.0)
    rejected = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id,
        LedgerEvent.event_type == "mutation_rejected"))).scalars().all()
    assert len(rejected) == 1


@pytest.mark.asyncio
async def test_a_correction_never_touches_a_provider(db, make_user, monkeypatch):
    """The crucial proof, per the GO ruling: "2 eggs -> 3 eggs" reprices from
    the row — USDA, OFF and the artifact are poisoned throughout."""
    import api.usda as usda
    import skills.nutrition.off as off_mod

    async def _boom(*a, **kw):                            # pragma: no cover
        raise AssertionError("a correction reached a provider")
    monkeypatch.setattr(usda, "search_food", _boom)
    monkeypatch.setattr(usda, "food_portions", _boom)
    monkeypatch.setattr(off_mod, "_get_json", _boom)
    monkeypatch.setattr("skills.nutrition.pricing_artifact.evidence_for",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("a correction reached the artifact")))

    user = await make_user()
    row = await _canonical_meal(db, user, quantity="2 eggs")
    result = await correct_quantity(db, user=user, entry_id=row.id,
                                    new_quantity_text="3 eggs")
    assert result.changes["calories"] == pytest.approx(270.0)


@pytest.mark.asyncio
async def test_two_corrections_chain_from_the_rows_own_history(db, make_user):
    """2 -> 3 -> 4 eggs: the second correction reads the FIRST's written
    state (quantity "3 large eggs", moved receipt), and lands within storage
    rounding of 2 -> 4 direct."""
    from db.models import FoodEntry

    user = await make_user()
    row = await _canonical_meal(db, user, receipt={
        "rung": "artifact", "evidence_id": "usda:173423",
        "basis": "per_100g", "scaling_factor": 0.92, "resolved_grams": 92.0})
    await correct_quantity(db, user=user, entry_id=row.id,
                           new_quantity_text="3 eggs")
    await correct_quantity(db, user=user, entry_id=row.id,
                           new_quantity_text="4 eggs")
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.quantity == "4 large eggs"
    assert fresh.calories == pytest.approx(360.0, abs=0.05)
    assert fresh.scaling_factor == pytest.approx(1.84, abs=1e-5)


# ── THE ROUTE: the native stage sends a canonical correction to the owner ───

def test_the_correction_route_is_narrow():
    """Exactly ONE update_food_entry with a quantity, nothing else. Mixed
    turns, multi-row corrections, renames and day-moves are not this slice."""
    from core.turns.stages.execute_native import _correction_input

    one = [{"name": "update_food_entry",
            "input": {"entry_id": 7, "quantity": "3 eggs"}}]
    assert _correction_input(one) == {"entry_id": 7, "quantity": "3 eggs"}
    assert _correction_input([]) is None
    assert _correction_input(one + [{"name": "log_food", "input": {}}]) is None
    assert _correction_input([{"name": "log_food",
                               "input": {"entry_id": 7}}]) is None
    assert _correction_input([{"name": "update_food_entry",
                               "input": {"quantity": "3"}}]) is None


def test_the_stage_still_holds_no_except_handler():
    """A8, re-asserted for the branch this slice added: the correction path
    RAISES through `run` — a handler here is how a canonical refusal reaches
    the legacy executor."""
    import ast
    import inspect

    from core.turns.stages.execute_native import NativeExecutionStage

    tree = ast.parse(inspect.getsource(NativeExecutionStage.run).lstrip())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert not handlers, "an except handler entered NativeExecutionStage.run"
