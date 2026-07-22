"""Live repro: does STRICT-mode food logging ask-before-log (July-7) or log-first?

Drives the REAL run_turn with the live LLM (pin DEFAULT_MODEL=claude-opus-4-8 to
match prod). For each strict-mode ambiguous item it reports:
  • ASKED?  — model asked a clarifying '?' with NO log_food this turn (July-7 want)
  • LOGGED  — items + calories + meal_type each log_food fired (log-first = current)
  • PHANTOM?— a 'you're at N cal' running total in the reply with nothing written

Baseline it BEFORE the July-7 revert, then re-run after each switch flip.
Usage:  DEFAULT_MODEL=claude-opus-4-8 .venv/bin/python scripts/repro_july7_behavior.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Strict-mode cases from Danny's 2026-07-22 screenshots. 3rd field = the answer
# to send if it asks first, to prove the ANSWER turn actually logs (ask→log).
CASES = [
    ("I also had half a chicken cutlet and a piece of white bread",
     "cooking method (pan-fried vs baked) swings fat — strict should ask first",
     "it was fried, and the bread was plain with no butter"),
    ("2 slices toast with butter",
     "butter amount swings cal — strict should ask how much butter first",
     "just a thin spread of butter, maybe a teaspoon"),
    ("chicken shawarma with hummus, fries, pita, garlic sauce, yellow rice, "
     "chopped salad and pickled turnips",
     "multi-item dinner — all items should share ONE meal slot",
     "grilled chicken, normal amount of toum, everything a regular portion"),
]


def _phantom_total(bubbles) -> bool:
    from core.turn_health import claimed_day_total
    return claimed_day_total("\n".join(bubbles or [])) is not None


async def main():
    from dotenv import load_dotenv
    load_dotenv(override=False)          # fill MISSING vars (API key) but don't clobber our pin
    # Force the prod model — the screenshot behavior is model-sensitive; .env may
    # pin a stale DEFAULT_MODEL, so set it explicitly (override with J7_MODEL).
    os.environ["DEFAULT_MODEL"] = os.environ.get("J7_MODEL") or "claude-opus-4-8"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); sys.exit(2)
    print(f"model = {os.environ['DEFAULT_MODEL']}   followup = "
          f"{os.environ.get('FOLLOWUP_MODEL', '(default)')}\n")

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import delete
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import User, UserPreferences, FoodEntry
    from db.queries import (get_or_create_webhook_token, get_or_create_today_log,
                            reload_user)
    from core.context_builder import build_context
    from core.prompts import build_arnie_system
    from core.conversation import run_turn

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    system_base = build_arnie_system(platform="telegram")

    async with Maker() as db:
        u = User(telegram_id="J7_001", name="Danny", age=35, sex="male",
                 height_cm=180.0, current_weight_kg=88.0, goal_weight_kg=82.0,
                 primary_goal="cut", training_experience="advanced",
                 timezone="America/New_York", onboarding_completed=True)
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2165, protein_target=180,
                               food_logging_mode="strict"))
        await db.flush()
        await get_or_create_webhook_token(db, u.id)
        uid = u.id
        await db.commit()

    from sqlalchemy import select as _select
    from sqlalchemy.orm import selectinload as _sil
    from db.models import DailyLog as _DL, PendingQuestion as _PQ

    async def _fresh_today(db, user):
        today = await get_or_create_today_log(db, uid, user.timezone)
        return (await db.execute(
            _select(_DL).where(_DL.id == today.id).options(_sil(_DL.food_entries))
        )).scalar_one()

    async def _run(db, user, messages):
        today = await _fresh_today(db, user)
        ctx = await build_context(user, today, db, platform="telegram",
                                  user_message=messages[-1]["content"])
        turn = await run_turn(user, db, messages, f"{system_base}\n\n{ctx}",
                              platform="telegram", in_onboarding=False,
                              was_onboarding=False, today_log=today, source_type="text")
        logs = [tc for tc in turn.tool_calls if tc.get("name") == "log_food"]
        return turn, logs

    for desc, why, answer in CASES:
        async with Maker() as db:
            user = await reload_user(db, uid)
            turn, logs = await _run(db, user, [{"role": "user", "content": desc}])
            bubbles = turn.response.bubbles if turn.response else []
            asked = (not logs) and any("?" in b for b in bubbles)
            phantom = _phantom_total(bubbles) and not logs
            print(f"── {desc[:60]}…")
            print(f"   why: {why}")
            print(f"   TURN 1  ASKED-before-log: {'YES ✅' if asked else 'no'}   "
                  f"logged {len(logs)}   phantom: {'YES ⚠️' if phantom else 'no'}")
            print(f"     reply: {' '.join(bubbles)[:140]}")
            # ── ANSWER TURN — the held meal must LOG now ──
            if asked:
                msgs = [{"role": "user", "content": desc},
                        {"role": "assistant", "content": "|||".join(bubbles)},
                        {"role": "user", "content": answer}]
                turn2, logs2 = await _run(db, user, msgs)
                b2 = turn2.response.bubbles if turn2.response else []
                print(f"   turn2 ALL tools: {[tc.get('name') for tc in turn2.tool_calls]}  "
                      f"reply: {' '.join(b2)[:90]}")
                slots = {(tc.get("input", {}).get("meal_type") or "(def)") for tc in logs2}
                print(f"   TURN 2 (answer '{answer[:28]}…')  LOGGED {len(logs2)} item(s)  "
                      f"slots={slots or '—'}  {'✅' if logs2 else '❌ NOTHING LOGGED'}")
                for tc in logs2:
                    i = tc.get("input", {})
                    print(f"      • {i.get('food_name'):<30} {i.get('calories')} cal  "
                          f"{i.get('meal_type') or '(def)'}")
            print()
            # isolate next case: clear food + pending questions + reset totals
            await db.execute(delete(FoodEntry))
            await db.execute(delete(_PQ).where(_PQ.user_id == uid))
            t = await get_or_create_today_log(db, uid, user.timezone)
            t.total_calories = t.total_protein = t.total_carbs = t.total_fats = 0
            await db.commit()

asyncio.run(main())
