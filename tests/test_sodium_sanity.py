"""Sodium plausibility clamp — every path that writes entry sodium respects
SODIUM_IMPLAUSIBLE_MG (4000mg; a very salty restaurant meal is 2-3.5g).

The three write paths under test:
  1. analyze() enrichment (ground-truth AND estimate paths) — bad USDA matches
     (salt-like records) and blown-up multipliers (LLM calories ÷ a tiny
     cal/100g) both produce garbage; the value is DROPPED (NULL reads as
     no-coverage to the health score — honest, no false "high sodium" flag).
  2. The Haiku micro-estimator fallback — hallucinated sodium is dropped in
     _parse_estimate before it ever reaches the entry.
  3. update_food_entry's serving rescale — a portion upscale of an already-
     vetted value is CAPPED (not dropped: the food is genuinely salty).
"""
from datetime import date

from core.food_intelligence import SODIUM_IMPLAUSIBLE_MG, analyze
from core.micro_estimator import _parse_estimate


# ── 1a. Ground-truth path: mass-stated quantity × a salt-like USDA record ────

def test_mass_stated_salt_record_drops_sodium():
    """The corn incident shape (Danny 2026-06-23): USDA matched a seasoning-like
    record carrying 20,378mg sodium per 100g. '200g' of it computes forward to
    ~40g sodium — dropped, while the rest of the profile stays."""
    cand = {
        "fdc_id": "SALT", "_match": "likely",
        "per100g": {"calories": 50, "protein": 2, "carbs": 10, "fat": 0.5,
                    "sodium": 20378},
    }
    a = analyze("corn", "200g", 90, 3, 19, 1, usda_candidate=cand)
    assert a.sodium is None
    assert a.calories == 100          # forward path still applied (50 × 2)


# ── 1b. Estimate path: garbage multiplier lands in the 4-5g band ─────────────

def test_estimate_path_garbage_multiplier_drops_sodium():
    """Low cal/100g salty foods (broth, pickles) + a normal LLM calorie guess
    imply an absurd portion: 150 kcal ÷ 10 kcal/100g = 1.5kg, so 300mg/100g
    becomes 4500mg. That passed the old 5000 clamp and stored garbage — it
    must drop under the 4000 bound."""
    cand = {
        "fdc_id": "BROTH", "_match": "likely",
        "per100g": {"calories": 10, "protein": 1, "carbs": 1, "fat": 0,
                    "sodium": 300},
    }
    a = analyze("chicken broth", "1 bowl", 150, 5, 10, 2, usda_candidate=cand)
    assert a.sodium is None


def test_plausible_salty_meal_survives():
    """A genuinely salty composite meal (ramen at 2000mg) clears the bound —
    the clamp only kills implausible values, never real salt."""
    cand = {
        "fdc_id": "RAMEN", "_match": "likely",
        "per100g": {"calories": 120, "protein": 4, "carbs": 15, "fat": 5,
                    "fiber": 1, "sugar": 2, "sodium": 400},
    }
    a = analyze("ramen", "1 bowl", 600, 20, 75, 25, usda_candidate=cand)
    assert a.sodium == 2000           # 400 × (600/120) — kept
    assert "sodium" in a.coach_note   # and still flagged high for coaching


def test_clamp_boundary_is_exclusive():
    """Exactly 4000mg is the edge of plausible — kept, not dropped."""
    cand = {
        "fdc_id": "EDGE", "_match": "likely",
        "per100g": {"calories": 100, "protein": 5, "carbs": 10, "fat": 4,
                    "sodium": 400},
    }
    a = analyze("salty platter", "1 plate", 1000, 50, 100, 20,
                usda_candidate=cand)
    assert a.sodium == SODIUM_IMPLAUSIBLE_MG


# ── 2. Haiku micro-estimator fallback ─────────────────────────────────────────

def test_micro_estimator_drops_implausible_sodium():
    assert _parse_estimate('{"sodium": 4500}') is None
    out = _parse_estimate('{"sodium": 3800}')
    assert out == {"sodium": 3800.0}


# ── 3. Serving-edit rescale (db.queries.update_food_entry) ───────────────────

async def test_serving_edit_caps_scaled_sodium(db, make_user):
    """Tripling a 3000mg entry would write 9000mg — the rescale caps at the
    shared bound instead, while fiber/sugar scale freely."""
    from db.models import DailyLog, FoodEntry
    from db.queries import update_food_entry

    u = await make_user()
    log = DailyLog(user_id=u.id, date=date(2026, 7, 17), total_calories=500)
    db.add(log)
    await db.flush()
    e = FoodEntry(daily_log_id=log.id, parsed_food_name="pho", calories=500,
                  protein=25, carbs=60, fats=12, fiber=2.0, sugar=4.0,
                  sodium=3000)
    db.add(e)
    await db.commit()

    updated = await update_food_entry(db, e.id, u.id, calories=1500.0,
                                      protein=75.0, carbs=180.0, fats=36.0)
    assert updated is not None
    assert updated.fiber == 6.0 and updated.sugar == 12.0
    assert updated.sodium == float(SODIUM_IMPLAUSIBLE_MG)


async def test_serving_edit_under_bound_scales_normally(db, make_user):
    """A rescale that stays plausible is untouched by the cap."""
    from db.models import DailyLog, FoodEntry
    from db.queries import update_food_entry

    u = await make_user()
    log = DailyLog(user_id=u.id, date=date(2026, 7, 16), total_calories=400)
    db.add(log)
    await db.flush()
    e = FoodEntry(daily_log_id=log.id, parsed_food_name="soup", calories=400,
                  protein=15, carbs=40, fats=10, sodium=1200)
    db.add(e)
    await db.commit()

    updated = await update_food_entry(db, e.id, u.id, calories=800.0,
                                      protein=30.0, carbs=80.0, fats=20.0)
    assert updated is not None
    assert updated.sodium == 2400
