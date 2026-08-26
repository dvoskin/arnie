"""The per-user food memory caches the micronutrient panel so repeat-logged
foods keep their micros (memory hits used to drop them, leaving every entry
after the first with an empty micronutrients_json)."""
import json

import pytest

from db.queries import (
    _extract_micros_100, upsert_user_food_match, get_user_food_match,
)

PER100_WITH_MICROS = {
    "calories": 100, "protein": 5, "carbs": 10, "fat": 3,
    "fiber": 2, "sugar": 1, "sodium": 50,
    "calcium": 120, "iron": 2.0, "potassium": 300, "vitamin_c": 9,
}


def test_extract_micros_100_picks_only_micros():
    m = _extract_micros_100(PER100_WITH_MICROS)
    assert m == {"calcium": 120, "iron": 2.0, "potassium": 300, "vitamin_c": 9}
    # macros stay out; None-valued keys are dropped
    assert "calories" not in m and "protein" not in m
    assert _extract_micros_100({}) == {}
    assert _extract_micros_100({"calcium": None}) == {}


async def _settle(db, uid, key, name, per100, fdc="X"):
    """⛔⛔ CF26 — A MICRO PANEL IS NUTRITION. The public writer runs before the
    meal is priced and stores none of it, so micros are cached by the one
    writer that may: the settlement projection."""
    from db.models import MealCommit
    from db.queries import remember_canonical_settlement
    operation_id = f"op:micros:{key}"
    if not (await db.execute(
            __import__("sqlalchemy").select(MealCommit.commit_id).where(
                MealCommit.operation_id == operation_id))).first():
        db.add(MealCommit(operation_id=operation_id, operation_revision=0,
                          user_id=uid, status="committed"))
        await db.flush()
    return await remember_canonical_settlement(
        db, user_id=uid, name_norm=key, display_name=name,
        operation_id=operation_id, per100=per100, evidence_id=fdc,
        basis="per_100g", fdc_id=fdc)


@pytest.mark.asyncio
async def test_cache_stores_micros_on_new_row(db, make_user):
    user = await make_user(telegram_id="ios:micros-new")
    await _settle(db, user.id, "spinach", "spinach", PER100_WITH_MICROS)
    row = await get_user_food_match(db, user.id, "spinach")
    assert row.micros_100_json is not None
    assert json.loads(row.micros_100_json)["calcium"] == 120


@pytest.mark.asyncio
async def test_cache_self_heals_macro_only_row(db, make_user):
    """A row created before micros existed (micros_100_json NULL) gets backfilled
    the first time a richer profile flows through."""
    user = await make_user(telegram_id="ios:micros-heal")
    # First write: macros only (simulates a pre-micros cache entry)
    macros_only = {k: PER100_WITH_MICROS[k] for k in
                   ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium")}
    await _settle(db, user.id, "oats", "oats", macros_only, fdc="Y")
    row = await get_user_food_match(db, user.id, "oats")
    assert row.micros_100_json is None

    # A LATER SETTLEMENT carrying the full panel replaces the row wholesale —
    # ⛔ CF26/CF24 — never a patch. A row holding new micros over old macros
    # would be a profile no single meal produced.
    await _settle(db, user.id, "oats", "oats", PER100_WITH_MICROS, fdc="Y")
    row = await get_user_food_match(db, user.id, "oats")
    assert row.micros_100_json is not None
    assert json.loads(row.micros_100_json)["iron"] == 2.0
