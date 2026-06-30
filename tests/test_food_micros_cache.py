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


@pytest.mark.asyncio
async def test_cache_stores_micros_on_new_row(db, make_user):
    user = await make_user(telegram_id="ios:micros-new")
    await upsert_user_food_match(
        db, user.id, "spinach", "spinach", "X", PER100_WITH_MICROS, "likely",
    )
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
    await upsert_user_food_match(db, user.id, "oats", "oats", "Y", macros_only, "likely")
    row = await get_user_food_match(db, user.id, "oats")
    assert row.micros_100_json is None

    # Second write with the full panel → self-heals the existing row in place.
    await upsert_user_food_match(db, user.id, "oats", "oats", "Y", PER100_WITH_MICROS, "likely")
    row = await get_user_food_match(db, user.id, "oats")
    assert row.micros_100_json is not None
    assert json.loads(row.micros_100_json)["iron"] == 2.0
    assert row.times_used == 2  # still the same row, usage bumped
