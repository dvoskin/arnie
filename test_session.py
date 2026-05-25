"""
Full-day simulation test.
Drives the core pipeline (LLM + DB + memory) directly — no Telegram required.
Run from the arnie/ directory:
    .venv/bin/python test_session.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
load_dotenv(override=True)

# ── pretty output ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def user_msg(text): print(f"\n{CYAN}{BOLD}[YOU ]{RESET} {text}")
def arnie_msg(text): print(f"{GREEN}{BOLD}[ARNIE]{RESET} {text}")
def info(text):  print(f"{YELLOW}[INFO ]{RESET} {text}")
def err(text):   print(f"{RED}{BOLD}[ERROR]{RESET} {text}")
def sep():       print(f"\n{'─'*60}")

# ── minimal Telegram Update mock ───────────────────────────────────────────────
class _FakeUser:
    id = 99999999  # test user — won't clash with real users
    first_name = "TestUser"

class _FakeMessage:
    def __init__(self, text):
        self.text = text
        self.voice = None
        self.photo = None
        self.caption = None

    async def reply_text(self, text, **kwargs):
        arnie_msg(text)

class _FakeUpdate:
    def __init__(self, text):
        self.effective_user = _FakeUser()
        self.message = _FakeMessage(text)


# ── pipeline shim ──────────────────────────────────────────────────────────────
async def send(text: str):
    """Send one message through the full pipeline and return the response."""
    user_msg(text)
    from db.database import AsyncSessionLocal
    from db.queries import (
        get_or_create_user, get_or_create_today_log, reload_user,
        get_recent_conversations, log_conversation,
    )
    from core.llm import chat, chat_follow_up
    from core.context_builder import build_context
    from handlers.onboarding import build_onboarding_system
    from handlers.tool_executor import execute_tool_calls
    from memory.reflection import maybe_update_memory

    update = _FakeUpdate(text)
    tg_id = str(update.effective_user.id)

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, tg_id)
        in_onboarding = not user.onboarding_completed

        from bot.telegram_handler import _ARNIE_SYSTEM
        if in_onboarding:
            system_base = build_onboarding_system(user)
            today_log = None
        else:
            today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
            ctx = await build_context(user, today_log, db)
            system_base = f"{_ARNIE_SYSTEM}\n\n{ctx}"

        # conversation history
        recent = await get_recent_conversations(db, user.id, limit=6)
        messages = []
        for c in reversed(recent):
            messages.append({"role": "user", "content": c.raw_message or ""})
            messages.append({"role": "assistant", "content": c.response or ""})
        messages.append({"role": "user", "content": text})

        result = await chat(messages, system_base, tools=True, max_tokens=1024)
        response_text = result["text"]
        tool_calls = result["tool_calls"]
        raw_content = result["raw_content"]

        if tool_calls:
            info(f"Tools called: {[t['name'] for t in tool_calls]}")
            if today_log is None and not in_onboarding:
                today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")

            class _FakeLog:
                id = None; total_calories = 0; total_protein = 0
                total_carbs = 0; total_fats = 0; total_water_ml = 0
                workout_completed = False; cardio_completed = False
                food_entries = []; exercise_entries = []

            tool_results = await execute_tool_calls(
                tool_calls, user,
                today_log if today_log else _FakeLog(),
                db, source_type="text"
            )
            info(f"Tool results: {tool_results}")
            user = await reload_user(db, user.id)
            if today_log and hasattr(today_log, "id") and today_log.id:
                await db.refresh(today_log)
            # Rebuild system with updated profile state
            in_onboarding = not user.onboarding_completed
            if in_onboarding:
                system_base = build_onboarding_system(user)

        need_followup = tool_calls and raw_content and (in_onboarding or not response_text)
        if need_followup:
            response_text = await chat_follow_up(
                messages, raw_content, tool_calls, tool_results, system_base, max_tokens=400
            )

        if not response_text:
            response_text = "Got it."

        arnie_msg(response_text)
        await log_conversation(db, user.id, text, response_text, source_type="text")
        return response_text


# ── test scenarios ─────────────────────────────────────────────────────────────
ONBOARDING_MSGS = [
    "hey",
    "Danny",
    "31 male",
    "5ft11, 191 lbs",
    "goal weight 178, I'm cutting",
    "intermediate lifter, been training 4 years",
    "no dietary restrictions",
    "no injuries",
    "balanced coaching style, high accountability",
    "America/New_York, wake 6:30am sleep 11pm",
]

DAY_MSGS = [
    # morning
    "weight 191.2 this morning",
    "had 3 eggs and 2 pieces of whole wheat toast for breakfast",
    "also had a black coffee",

    # mid morning
    "protein shake - 1 scoop whey with water",

    # check in
    "how am I doing on protein so far?",

    # workout
    "just finished my push day. bench press 185lbs 4x5, incline db press 70lbs 3x10, ohp 115lbs 3x8, lateral raises 20lbs 4x15, tricep pushdowns 3x12",

    # lunch
    "lunch was a chicken burrito bowl from chipotle - chicken, rice, black beans, salsa, guac",

    # afternoon
    "had an apple and a handful of almonds around 3pm",

    # pacing check
    "what do I still need to eat today to hit my goals?",

    # dinner
    "dinner: 8oz salmon fillet, roasted sweet potato, and broccoli",

    # evening
    "had a greek yogurt with some berries after dinner",

    # summary request
    "/summary",

    # day close
    "close the day",
]

EDGE_CASES = [
    "what are some high protein breakfast ideas?",
    "I think I'm going to skip the gym tomorrow, feeling worn out",
    "can you build me a pull day workout?",
    "I ate like shit today honestly, had pizza and beer with friends",
    "update my calorie target to 2400 and protein to 185g",
]


async def run_onboarding():
    sep()
    print(f"{BOLD}PHASE 1 — ONBOARDING{RESET}")
    sep()
    for msg in ONBOARDING_MSGS:
        await send(msg)
        await asyncio.sleep(0.5)


async def run_full_day():
    sep()
    print(f"{BOLD}PHASE 2 — FULL DAY LOGGING{RESET}")
    sep()
    for msg in DAY_MSGS:
        await send(msg)
        await asyncio.sleep(0.5)


async def run_edge_cases():
    sep()
    print(f"{BOLD}PHASE 3 — EDGE CASES{RESET}")
    sep()
    for msg in EDGE_CASES:
        await send(msg)
        await asyncio.sleep(0.5)


async def print_final_state():
    sep()
    print(f"{BOLD}FINAL DB STATE{RESET}")
    sep()
    from db.database import AsyncSessionLocal
    from db.queries import get_or_create_user, get_today_log, get_recent_weights
    from memory.memory_manager import read_memory

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, "99999999")
        info(f"User: {user.name}, age={user.age}, sex={user.sex}")
        info(f"  Height: {user.height_cm}cm  Weight: {user.current_weight_kg}kg  Goal: {user.goal_weight_kg}kg")
        info(f"  Goal: {user.primary_goal}  Experience: {user.training_experience}")
        info(f"  Timezone: {user.timezone}  Onboarding: {user.onboarding_completed}")
        if user.preferences:
            p = user.preferences
            info(f"  Coaching: {p.coaching_style}  Accountability: {p.accountability_level}")
            info(f"  Cal target: {p.calorie_target}  Protein target: {p.protein_target}g")

        log = await get_today_log(db, user.id, user.timezone or "UTC")
        if log:
            info(f"\nToday's log [{log.status}]:")
            info(f"  Calories: {log.total_calories:.0f}  Protein: {log.total_protein:.0f}g  "
                 f"Carbs: {log.total_carbs:.0f}g  Fats: {log.total_fats:.0f}g")
            info(f"  Workout: {log.workout_completed}  Cardio: {log.cardio_completed}")
            info(f"  Food entries: {len(log.food_entries)}  Exercise entries: {len(log.exercise_entries)}")

        weights = await get_recent_weights(db, user.id, days=7)
        info(f"\nWeight entries today: {[f'{w.weight_kg:.1f}kg' for w in weights]}")

        memory = await read_memory("99999999")
        info(f"\nMemory file ({len(memory)} chars):")
        print(memory[:800])


async def cleanup():
    """Remove the test user from DB and memory files."""
    import shutil
    from pathlib import Path
    from db.database import AsyncSessionLocal
    from db.models import User
    from db.queries import get_or_create_user
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .where(User.telegram_id == "99999999")
            .options(selectinload(User.preferences))
        )
        user = result.scalar_one_or_none()
        if user:
            await db.delete(user)
            await db.commit()

    mem_dir = Path("users/99999999")
    if mem_dir.exists():
        shutil.rmtree(mem_dir)
    info("Test user cleaned up.")


async def main():
    from db.database import init_db
    await init_db()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ARNIE FULL-DAY TEST SESSION{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    try:
        await run_onboarding()
        await run_full_day()
        await run_edge_cases()
        await print_final_state()
    except Exception as e:
        err(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await cleanup()

    sep()
    print(f"{GREEN}{BOLD}All tests complete.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
