"""
Behavioral regression sim for the 7 iOS-fix bugs reviewed 2026-06-18.

Drives the REAL run_turn pipeline with the LIVE LLM and the production system
prompt — set up to look like the iOS test users in prod (uid 25, 26): strict
food-logging mode, location on file, [TODAY] log pre-seeded with the Barebells
entries so the dedup-pushback scenario can be triggered in a single turn.

Scenarios verified (one ≈ one bug from the review):
  S1  /reset all confirm        → intercepted (no LLM), explicit confirm message
  S2  /reset                    → intercepted, help message lists today + all
  S3  cappuccino + croissant    → strict mode MUST ask milk/size, NOT log_food
  S4  dedup pushback            → must reference existing entry, NOT "logged ✅"
  S5  pasted health metrics     → must fire track_metric (>=2 calls)
  S6  "share my location"       → must NOT deny when Location: ON FILE
  S7  every iOS reply           → first bubble starts with a capital letter

Run from arnie/:
    .venv/bin/python simulate_ios_fixes.py

Requires: ANTHROPIC_API_KEY (and/or OPENAI_API_KEY) in .env. Sets
LOCATION_ENABLED=true for this process so the LOCATION_RULES block loads.
"""
import asyncio
import os
import sys

# Must set BEFORE any module reads it.
os.environ["LOCATION_ENABLED"] = "true"

from datetime import date, datetime, timedelta
from dotenv import load_dotenv
load_dotenv(override=True)
os.environ["LOCATION_ENABLED"] = "true"  # reassert — load_dotenv may overwrite

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

_pass = 0
_fail = 0


def check(label, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"    {G}✓{X} {label}" + (f" {D}{detail}{X}" if detail else ""))
    else:
        _fail += 1
        print(f"    {R}✗ {label}{X}" + (f" {R}{detail}{X}" if detail else ""))
    return cond


def first_letter(s):
    for ch in s.lstrip():
        if ch.isalpha():
            return ch
    return ""


async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import User, UserPreferences, DailyLog, FoodEntry
    from db.queries import (
        get_or_create_today_log, log_conversation, save_user_location,
    )
    from core.chat_service import run_chat_turn

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── Seed strict-mode iOS user with location ON FILE + Barebells already
    # logged today, so the dedup-pushback scenario triggers in a single turn ──
    async with Maker() as db:
        u = User(
            telegram_id="ios:test_danny",
            name="Danny", age=33, sex="male",
            height_cm=178.0, current_weight_kg=78.0, goal_weight_kg=74.0,
            primary_goal="cut", training_experience="intermediate",
            dietary_preferences="high-protein",
            injuries="none", timezone="America/New_York",
            onboarding_completed=True,
        )
        db.add(u)
        db.add(UserPreferences(
            user=u, calorie_target=2047, protein_target=182,
            coaching_style="balanced", accountability_level="high",
            wake_time="06:30", sleep_time="22:30",
            food_logging_mode="strict",  # the bug class
        ))
        await db.flush()
        uid = u.id

        # location on file — both lat/lng + city
        await save_user_location(
            db, user_id=uid,
            lat=40.7747, lng=-73.9906,
            city="New York",
        )

        # Pre-seed TODAY's log with 2 Barebells so dedup-pushback (S4) is real
        today_log = await get_or_create_today_log(db, uid, "America/New_York")
        db.add(FoodEntry(
            daily_log_id=today_log.id,
            timestamp=datetime.utcnow() - timedelta(minutes=90),
            raw_input="2 barebell bars",
            parsed_food_name="Barebells Protein Bar",
            quantity="2 bars",
            calories=360.0, protein=42.0, carbs=24.0, fats=14.0,
            source_type="ios",
        ))
        await db.commit()

    # ── Turn helper ─────────────────────────────────────────────────────────
    async def run(msg):
        async with Maker() as db:
            from db.queries import reload_user
            user = await reload_user(db, uid)
            turn = await run_chat_turn(
                db, user, msg,
                platform="ios", source_type="ios",
                schedule_background=False,
            )
        return turn

    print(f"\n{B}{C}{'═'*66}{X}")
    print(f"{B}{C} iOS FIX REGRESSION — live LLM, production prompt{X}")
    print(f"{B}{C}{'═'*66}{X}")
    print(f"{D}  User: Danny, 33, cutting, strict mode, location on file (NYC),{X}")
    print(f"{D}  [TODAY] already has 2 Barebells from 90 min ago{X}\n")

    sentence_case_failures = []

    # ── S2: /reset — help message (non-destructive, runs first) ─────────────
    print(f"{B}S2  /reset — must intercept and show help{X}")
    turn = await run("/reset")
    blob = " ".join(turn.response.bubbles).lower()
    check("S2 lists today option", "/reset today" in blob)
    check("S2 lists all option", "/reset all confirm" in blob)
    sentence_case_failures.append(("S2", turn.response.bubbles))

    # ── S3: strict mode beverage — MUST ask, NOT log ─────────────────────────
    print(f"\n{B}S3  strict mode — 'cappuccino and croissant' must clarify, NOT log{X}")
    turn = await run("I had a cappuccino and a croissant")
    names = [tc["name"] for tc in turn.tool_calls]
    blob = " ".join(turn.response.bubbles).lower()
    check("S3 did NOT call log_food", "log_food" not in names,
          detail=f"tools fired: {names}")
    check("S3 asked a clarifying question", "?" in " ".join(turn.response.bubbles))
    check("S3 mentions milk OR size",
          any(w in blob for w in ("milk", "size", "small", "medium", "large",
                                    "whole", "oat", "skim", "almond")))
    sentence_case_failures.append(("S3", turn.response.bubbles))

    # ── S4: dedup-pushback — must reference existing entry, NOT relog ────────
    # Replay the EXACT prod sequence (conv ids 2195-2197) on a clean user
    # to avoid prior-turn referent confusion from S3's cappuccino.
    print(f"\n{B}S4  dedup pushback — replay prod sequence on fresh user{X}")
    async with Maker() as db:
        u4 = User(
            telegram_id="ios:test_danny_s4",
            name="Danny", age=33, sex="male",
            height_cm=178.0, current_weight_kg=78.0, goal_weight_kg=74.0,
            primary_goal="cut", training_experience="intermediate",
            dietary_preferences="high-protein", injuries="none",
            timezone="America/New_York", onboarding_completed=True,
        )
        db.add(u4)
        db.add(UserPreferences(
            user=u4, calorie_target=2047, protein_target=182,
            coaching_style="balanced", accountability_level="high",
            wake_time="06:30", sleep_time="22:30",
            food_logging_mode="strict",
        ))
        await db.flush()
        uid4 = u4.id
        today_log4 = await get_or_create_today_log(db, uid4, "America/New_York")
        db.add(FoodEntry(
            daily_log_id=today_log4.id,
            timestamp=datetime.utcnow() - timedelta(minutes=90),
            raw_input="2 barebell bars",
            parsed_food_name="Barebells Protein Bar",
            quantity="2 bars",
            calories=360.0, protein=42.0, carbs=24.0, fats=14.0,
            source_type="ios",
        ))
        # Seed the two prior turns so the dedup-pushback context is clean
        await log_conversation(
            db, uid4, "I had 2 barebell bars today",
            "2 Barebells bars logged ✅|||roughly 360 calories, 42g protein combined.",
            source_type="ios", platform="ios",
        )
        await log_conversation(
            db, uid4, "I had 2 barebell bars today",
            "Looks like those are already in your log, Danny.|||Want me to add 2 more, or were you just referencing what you had earlier?",
            source_type="ios", platform="ios",
        )
        await db.commit()

    async def run4(msg):
        async with Maker() as db:
            from db.queries import reload_user
            user = await reload_user(db, uid4)
            return await run_chat_turn(
                db, user, msg,
                platform="ios", source_type="ios",
                schedule_background=False,
            )
    turn = await run4("I don't see them in my logs")
    names = [tc["name"] for tc in turn.tool_calls]
    blob = " ".join(turn.response.bubbles).lower()
    check("S4 did NOT call log_food (no fake double-log)",
          "log_food" not in names, detail=f"tools: {names}")
    check("S4 references existing entry (mentions barebells/bar)",
          "barebell" in blob or "bar" in blob,
          detail=f"reply: {turn.response.bubbles}")
    check("S4 does NOT use 'logged ✅' template",
          "logged ✅" not in " ".join(turn.response.bubbles))
    sentence_case_failures.append(("S4", turn.response.bubbles))

    # ── S5: pasted health text — must fire track_metric ──────────────────────
    print(f"\n{B}S5  pasted health metrics — must fire track_metric{X}")
    payload = (
        "Resting heart rate: 78 bpm. "
        "HRV: 44 ms. "
        "Steps today: 6500. "
        "Sleep last night: 5.5 hours. "
    )
    turn = await run(payload)
    names = [tc["name"] for tc in turn.tool_calls]
    n_track = sum(1 for n in names if n == "track_metric")
    check("S5 fired track_metric at least once",
          n_track >= 1, detail=f"track_metric × {n_track}, all tools: {names}")
    check("S5 fired track_metric for >=2 metrics (was 4 in the user paste)",
          n_track >= 2, detail=f"got {n_track}")
    check("S5 did NOT say 'all logged' without firing",
          n_track > 0 or "all logged" not in " ".join(turn.response.bubbles).lower())
    sentence_case_failures.append(("S5", turn.response.bubbles))

    # ── S6: 'do you see my location?' — must NOT deny when on file (prod #2191) ─
    print(f"\n{B}S6  'do you see my location?' — location ON FILE; must not deny{X}")
    turn = await run("Do you see my location?")
    blob = " ".join(turn.response.bubbles).lower()
    bad = [
        "i can't access your location",
        "i can not access your location",
        "i have no access to your",
        "no live location",
        "no connection to your phone",
        "no access to your phone",
        "i don't have your location",
        "i do not have your location",
        "i don't have any location",
        "i don't have access to your location",
    ]
    hit = next((p for p in bad if p in blob), None)
    check("S6 does NOT flatly deny having location",
          hit is None, detail=f"said: {hit!r}" if hit else "")
    check("S6 acknowledges the location it has on file",
          "new york" in blob or "on file" in blob or "ny" in blob.split()
          or "city" in blob or "yes" in blob or "got" in blob,
          detail=f"reply: {turn.response.bubbles}")
    sentence_case_failures.append(("S6", turn.response.bubbles))

    # ── S1: /reset all confirm — DESTRUCTIVE, runs last so it doesn't
    #         wipe onboarding state ahead of S3-S6 ────────────────────────────
    print(f"\n{B}S1  /reset all confirm — must intercept BEFORE the LLM{X}")
    turn = await run("/reset all confirm")
    blob = " ".join(turn.response.bubbles).lower()
    check("S1 bubbles produced", bool(turn.response.bubbles))
    check("S1 mentions wipe", "wipe" in blob or "wiped" in blob or "fresh start" in blob,
          detail=f"got: {turn.response.bubbles}")
    check("S1 no LLM tool calls", turn.tool_calls == [])
    sentence_case_failures.append(("S1", turn.response.bubbles))

    # ── S7: sentence case on iOS — every first bubble starts with a capital ──
    print(f"\n{B}S7  sentence case on iOS — first letter must be uppercase{X}")
    for label, bubbles in sentence_case_failures:
        if not bubbles or not bubbles[0].strip():
            continue
        fc = first_letter(bubbles[0])
        check(f"S7 {label} first bubble starts with capital",
              fc == "" or fc.isupper(),
              detail=f"first char: {fc!r}  bubble: {bubbles[0][:80]!r}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{B}{C}{'═'*66}{X}")
    print(f"{B}  RESULTS: {G}{_pass} passed{X}  {R}{_fail} failed{X}")
    print(f"{B}{C}{'═'*66}{X}\n")
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
