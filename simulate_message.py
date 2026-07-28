"""Send Arnie a message and see everything the turn did — without writing
anything, anywhere.

The point is testing food changes against the REAL path: the live gate, the
live interpreter, the live USDA/Open Food Facts lookups and the live composer,
with the same prompts production uses. What it does not have is your account.

WHY THIS EXISTS. Testing on a live account is not reversible. Every confident
lookup writes `user_food_matches`, a correction writes it again through the
backfill, and `delete_food_entry` is `db.delete(entry)` — it never touches that
table. So a test log permanently teaches the memory cache, and deleting the
entry afterwards does not undo it: the next real log of that food primes from
whatever the test produced.

The database here is `sqlite+aiosqlite://` — in memory, created per run,
discarded on exit. It cannot reach arnie.db, your Postgres, or your history.

    .venv/bin/python simulate_message.py "had a Barebells salty peanut bar"
    .venv/bin/python simulate_message.py "had a bar and some chicken" "about a cup of rice"

Several arguments are consecutive TURNS in one conversation, which is what the
clarification tests need — the second message is answering the first's question.

Costs real model calls and real API quota. It is a simulator, not a mock.
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

# The turn logs heavily and the point here is the EXCHANGE. Set
# SIMULATE_VERBOSE=1 to get the full trace back, including the
# `event=macro_reconcile` and `event=resolution` lines.
logging.basicConfig(
    level=(logging.INFO if os.getenv("SIMULATE_VERBOSE") else logging.ERROR),
    format="  %(message)s")

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"
B = "\033[1m"; X = "\033[0m"; D = "\033[90m"


async def main(messages):
    from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                        create_async_engine)
    from sqlalchemy.pool import StaticPool

    from core.conversation import run_turn
    from core.prompts import build_arnie_system
    from db.database import Base, _migrate
    from db import models  # noqa: F401
    from db.models import ConversationLog, FoodEntry, User, UserPreferences
    from db.queries import (get_or_create_today_log,
                            get_or_create_webhook_token, log_conversation)

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    system = build_arnie_system(platform="telegram")

    async with Maker() as db:
        user = User(telegram_id="MSGSIM_001", name="Test", age=30, sex="male",
                    height_cm=180.0, current_weight_kg=82.0,
                    goal_weight_kg=78.0, primary_goal="cut",
                    training_experience="advanced",
                    timezone="America/New_York", onboarding_completed=True)
        db.add(user)
        db.add(UserPreferences(user=user, calorie_target=2200,
                               protein_target=180, coaching_style="direct",
                               # The mode the clarification policy reads. Moderate
                               # is the default and the one partial commit is
                               # written for, so it is what a test should see.
                               food_logging_mode="moderate"))
        await db.flush()
        await get_or_create_webhook_token(db, user.id)
        uid = user.id
        await db.commit()

    for turn_no, message in enumerate(messages, 1):
        async with Maker() as db:
            user = await db.get(User, uid)
            today_log = await get_or_create_today_log(db, uid, user.timezone)

            history = (await db.execute(
                ConversationLog.__table__.select()
                .where(ConversationLog.user_id == uid)
                .order_by(ConversationLog.timestamp.desc()).limit(8)
            )).fetchall()
            convo = []
            for row in reversed(history):
                convo.append({"role": "user", "content": row.raw_message or ""})
                convo.append({"role": "assistant", "content": row.response or ""})
            convo.append({"role": "user", "content": message})

            turn = await run_turn(user, db, convo, system, platform="telegram",
                                  in_onboarding=False, was_onboarding=False,
                                  today_log=today_log, source_type="text")
            await log_conversation(db, uid, message,
                                   "|||".join(turn.response.bubbles),
                                   source_type="text")
            await db.commit()

            print(f"\n{B}{Y}[{turn_no}] YOU:{X} {message}")
            for bubble in turn.response.bubbles:
                print(f"    {C}ARNIE:{X} {bubble}")

            calls = [t["name"] for t in (turn.tool_calls or [])]
            print(f"    {D}tools: {', '.join(calls) or 'none'}{X}")

            # THE RECEIPT, which is where the provenance fixes show up.
            for call in (turn.tool_calls or []):
                inp = call.get("input") or {}
                lanes = inp.get("lanes")
                if lanes:
                    print(f"    {D}lanes: "
                          f"{', '.join(f'{k}:{v}' for k, v in lanes)}{X}")
                sourcing = inp.get("_sourcing")
                if isinstance(sourcing, dict):
                    print(f"    {D}source: {sourcing.get('source')} — "
                          f"{sourcing.get('detail') or '-'}{X}")
                receipt = inp.get("_receipt")
                if isinstance(receipt, dict):
                    print(f"    {D}receipt: {receipt}{X}")

            rows = (await db.execute(
                FoodEntry.__table__.select()
                .where(FoodEntry.daily_log_id == today_log.id))).fetchall()
            if rows:
                print(f"    {G}committed:{X}")
                for r in rows:
                    print(f"      {r.parsed_food_name} ({r.quantity}) — "
                          f"{round(r.calories or 0)} cal, "
                          f"{round(r.protein or 0)}P "
                          f"{round(r.carbs or 0)}C {round(r.fats or 0)}F")
            else:
                print(f"    {D}committed: nothing{X}")

    print(f"\n{D}in-memory database discarded — nothing was written{X}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1:]))
