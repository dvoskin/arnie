#!/usr/bin/env python3
"""Reproduce + verify the Royo-bagel accuracy bug: user's LOGGED history must beat a
generic USDA close-match (and a poisoned cache).

Danny logged "Royo Everything Bagel" at 80 cal. Logging "everything Royo bagel" later
enriched to a GENERIC everything bagel (~290) because (a) the cache was poisoned with
536 cal/100g under that key and (b) word order fragmented the match. The user's own
recent log is ground truth — it must win.

Mocks USDA to return the generic bagel (deterministic). Run:
  python scripts/repro_history_accuracy.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
import handlers.tool_executor as TE
from core.chat_service import run_chat_turn
from db.queries import reload_user, get_today_log


# Generic everything bagel, per-100g — what USDA returns for the un-branded name.
async def _fake_usda(name, page_size=8):
    return [{"description": "Bagel, everything", "fdc_id": 9999,
             "per100g": {"calories": 271, "protein": 10, "carbs": 53, "fat": 2,
                         "fiber": 2, "sugar": 5, "sodium": 500}}]


async def _seed_prior_log(H, uid, name, cal, protein, carbs, when_days_ago=1):
    """Insert a prior food_entry so it lands in [FOOD HISTORY] + the match path."""
    from datetime import date, timedelta
    from db.models import FoodEntry, DailyLog
    from db.queries import get_or_create_today_log
    async with await H.session() as db:
        u = await reload_user(db, uid)
        # a prior-day log
        d = date.today() - timedelta(days=when_days_ago)
        from sqlalchemy import select
        dl = (await db.execute(select(DailyLog).where(
            DailyLog.user_id == uid, DailyLog.date == d))).scalar_one_or_none()
        if dl is None:
            dl = DailyLog(user_id=uid, date=d)
            db.add(dl); await db.flush()
        db.add(FoodEntry(daily_log_id=dl.id, parsed_food_name=name, quantity="1 bagel",
                         calories=cal, protein=protein, carbs=carbs, fats=1,
                         estimated_flag=False, source_type="text", meal_type="snack"))
        await db.commit()


async def main():
    # Mock USDA to the GENERIC everything bagel (deterministic; no network).
    import api.usda as USDA
    USDA.search_food = _fake_usda

    H = S.Harness(); await H.setup(); uid = await H.new_user()
    # Prod conditions: (1) the REAL Royo bagel logged at 80 (word order "Royo Everything
    # Bagel"), (2) a POISONED cache (536/100g generic) under the other word order.
    await _seed_prior_log(H, uid, "Royo Everything Bagel", 80, 10, 6, when_days_ago=1)
    from db.queries import upsert_user_food_match
    async with await H.session() as db:
        await upsert_user_food_match(
            db, uid, "everything royo bagel", "Everything Royo Bagel", 9999,
            {"calories": 536, "protein": 20, "carbs": 106, "fat": 4}, "likely")
        await db.commit()

    # The model provides the BAD generic estimate (290) — exactly what happened in prod.
    # The enrichment must override it with the user's own logged 80, not the cache/USDA.
    async with await H.session() as db:
        u = await reload_user(db, uid)
        result = await TE._analyze_food(
            db, u, "everything Royo bagel",
            {"calories": 290, "protein": 11, "carbs": 54, "fats": 1,
             "quantity": "1 bagel", "confidence": 0.6})
    cal = round(float(getattr(result, "calories", 0) or 0))
    src = getattr(result, "source", "?")
    print("=" * 68)
    print("Prod conditions: history 'Royo Everything Bagel'=80 | cache poisoned=536/100g")
    print("Model provided the generic estimate: 290 cal")
    print(f"  → _analyze_food returned {cal} cal (source={src})")
    ok = cal <= 130   # the user's logged 80 must win, not the 290/536 generic
    print(f"  VERDICT: {'✅ PASS — your logged history won' if ok else f'❌ FAIL — generic/cache overrode history ({cal} cal)'}")
    print("=" * 68)


if __name__ == "__main__":
    asyncio.run(main())
