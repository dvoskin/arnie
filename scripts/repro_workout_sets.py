"""Live repro: multi-movement / multi-set workout logging on opus-4-8.

Replays Danny's 2026-07-23 session (prod) turn by turn through the REAL run_turn,
and after each turn prints what actually landed in exercise_entries. Shows where
sets/movements drop despite a "🏋️ ... logged" reply (opus narrates without firing
log_exercise deeper into the session).

Usage: SCRIBE_SHADOW_ENABLED=false .venv/bin/python scripts/repro_workout_sets.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (user message, what it SHOULD add) — mirrors the real session.
TURNS = [
    ("Just started my workout", "—"),
    ("205x13 incline chest press first set so far", "Incline set1 205x13"),
    ("Hit 12 on the second set", "Incline set2 205x12"),
    ("Got 11 on that one", "Incline set3 205x11"),
    ("Just did a set of cable chest fly seated at 65", "(asks reps or logs)"),
    ("11", "Seated Cable Fly 65x11"),
    ("Moving on doing some high to low fly", "—"),
    ("I did 2 sets of 120 for 12 each", "High-to-Low 120x12 x2"),
    ("I'm doing low to high now", "—"),
    ("I did 80x12 first set gonna drop to 60 on others", "Low-to-High set1 80x12"),
    ("60x13", "Low-to-High set2 60x13"),
    ("13 again", "Low-to-High set3 60x13"),
    ("8 dips to wrap it", "Dips 1x8 bodyweight"),
]


async def main():
    from dotenv import load_dotenv
    load_dotenv(override=False)
    os.environ["DEFAULT_MODEL"] = os.environ.get("J7_MODEL") or "claude-opus-4-8"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); sys.exit(2)
    print(f"model = {os.environ['DEFAULT_MODEL']}\n")

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import User, UserPreferences, DailyLog, ExerciseEntry
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
        u = User(telegram_id="WK_001", name="Danny", age=35, sex="male",
                 height_cm=180.0, current_weight_kg=88.0, goal_weight_kg=82.0,
                 primary_goal="recomp", training_experience="advanced",
                 timezone="America/New_York", onboarding_completed=True)
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2165, protein_target=180,
                               food_logging_mode="moderate"))
        await db.flush()
        await get_or_create_webhook_token(db, u.id)
        uid = u.id
        await db.commit()

    async def entries(db, today_id):
        rows = (await db.execute(
            select(ExerciseEntry).where(ExerciseEntry.daily_log_id == today_id)
            .order_by(ExerciseEntry.id))).scalars().all()
        return rows

    messages = []
    async with Maker() as db:
        user = await reload_user(db, uid)
        today = await get_or_create_today_log(db, uid, user.timezone)
        today_id = today.id
        for msg, expect in TURNS:
            messages.append({"role": "user", "content": msg})
            today = (await db.execute(select(DailyLog).where(DailyLog.id == today_id)
                     .options(selectinload(DailyLog.exercise_entries)))).scalar_one()
            before = len(today.exercise_entries)
            ctx = await build_context(user, today, db, platform="telegram", user_message=msg)
            turn = await run_turn(user, db, list(messages), f"{system_base}\n\n{ctx}",
                                  platform="telegram", in_onboarding=False,
                                  was_onboarding=False, today_log=today, source_type="text")
            bubbles = turn.response.bubbles if turn.response else []
            messages.append({"role": "assistant", "content": "|||".join(bubbles)})
            fired = [tc.get("name") for tc in turn.tool_calls if "exercise" in tc.get("name", "")]
            rows = await entries(db, today_id)
            print(f"» {msg[:46]:46s} | expect: {expect}")
            print(f"    tools={fired or '—'}  reply: {' '.join(bubbles)[:80]}")
            print(f"    DB now: " + (" ; ".join(
                f"{r.exercise_name} {r.sets}x[{r.reps}]@{round(r.weight*2.20462) if r.weight else '?'}"
                for r in rows) or "(empty)"))

        print("\n=== FINAL exercise_entries ===")
        for r in await entries(db, today_id):
            wt = f"{round(r.weight*2.20462)}lb" if r.weight else "no-wt"
            print(f"  {r.exercise_name:28s} sets={r.sets} reps={r.reps!r} {wt}")

asyncio.run(main())
