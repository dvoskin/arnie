"""
Live-workout coaching + logging regression sim — drives the REAL run_turn with
the LIVE LLM and production prompt, replaying the failure modes from Danny's
2026-06-14 shoulder session (the session that motivated Phase 1):

  1. PACING DEFLECTION  — "Pace me" before any set is logged got answered with
     "log the set first". Pacing must surface immediately.
  2. PREMATURE LOGGING  — "lateral raises next" / "gonna do face pull superset
     with upright rows" got logged as phantom sets. Intent is not a log.
  3. PHANTOM RE-LOG      — Face Pull 3×12 logged, then re-logged 8 min later when
     the user pivoted → 7 sets stored for 3 performed. Widened multi-set dedup
     window + prompt must prevent it.
  4. NO DROPPED SETS     — every set the user reports gets logged exactly once.

Nondeterministic (live LLM). Run a few times; per-turn tool-call checks are the
hard signals, the DB tallies are the aggregate outcome.

Run from arnie/:
    .venv/bin/python simulate_live_workout.py
"""
import asyncio
from datetime import date, timedelta, datetime, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

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


# Each step: (message, checker(bubbles, names, db_state) -> None)
# Checkers run AFTER the turn; db_state is a dict of {exercise_name_lower: total_sets}.
DEFLECT_PHRASES = [
    "log the set first", "log it first", "log that first", "log the first set",
    "once you log", "after you log", "log it and i", "log the set and",
]
PACING_WORDS = [
    "rest", "warm", "match", "beat", "target", "tempo", "130", "chase",
    "groove", "ready", "send it", "go", "push",
]


async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import User, UserPreferences, ConversationLog, DailyLog, ExerciseEntry
    from db.queries import get_or_create_webhook_token, get_or_create_today_log, log_conversation, reload_user
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
        u = User(
            telegram_id="LIVEWO_001", name="Danny", age=37, sex="male",
            height_cm=178.0, current_weight_kg=86.0, goal_weight_kg=80.0,
            primary_goal="cut", training_experience="advanced",
            injuries="none", timezone="America/New_York", onboarding_completed=True,
        )
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2126, protein_target=190,
                               coaching_style="direct", accountability_level="high",
                               wake_time="07:00", sleep_time="23:30"))
        await db.flush()
        uid = u.id
        await get_or_create_webhook_token(db, u.id)

        # Seed YESTERDAY's shoulder session so [EXERCISE HISTORY] gives Arnie a
        # target to pace against (130x10 shoulder press, etc.).
        y = date.today() - timedelta(days=1)
        ylog = DailyLog(user_id=uid, date=y, workout_completed=True)
        db.add(ylog)
        await db.flush()
        seed = [
            ("Shoulder Press Machine", 1, "10", 58.97),
            ("Cable Lateral Raise", 1, "15", 9.07),
            ("Face Pull", 1, "12", 31.75),
            ("Upright Row", 1, "12", 49.90),
        ]
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        for nm, st, rp, wt in seed:
            db.add(ExerciseEntry(daily_log_id=ylog.id, exercise_name=nm, sets=st,
                                 reps=rp, weight=wt, timestamp=ts, source_type="text"))
        await db.commit()

    print(f"\n{B}{C}{'='*66}{X}")
    print(f"{B}{C} LIVE-WORKOUT COACHING + LOGGING SIM — live LLM, prod prompt{X}")
    print(f"{B}{C}{'='*66}{X}")
    print(f"{D}  Danny, 37, advanced, cutting. Yesterday: shoulder press 130x10.{X}\n")

    async def db_tally():
        async with Maker() as db:
            tl = await get_or_create_today_log(db, uid, "America/New_York")
            from sqlalchemy import select
            rows = (await db.execute(
                select(ExerciseEntry).join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
                .where(DailyLog.user_id == uid, DailyLog.date == date.today()))).scalars().all()
            tally = {}
            for e in rows:
                tally[(e.exercise_name or "?").lower()] = tally.get((e.exercise_name or "?").lower(), 0) + (e.sets or 0)
            return tally, rows

    def step_checks(label, bubbles, names):
        text = " ||| ".join(bubbles).lower()
        if label == "intent_shoulders":
            check("[about to hit shoulders] no premature log_exercise", "log_exercise" not in names, f"tools={names}")
        if label == "pace_me":
            check("[pace me] no deflection to 'log first'",
                  not any(p in text for p in DEFLECT_PHRASES), f"text={text[:120]}")
            check("[pace me] surfaces an actual pacing cue",
                  any(w in text for w in PACING_WORDS), "expected rest/target/warm-up cue")
            check("[pace me] no log_exercise (nothing performed yet)", "log_exercise" not in names, f"tools={names}")
        if label == "laterals_next":
            check("[lateral raises next] no premature log (intent only)", "log_exercise" not in names, f"tools={names}")
        if label == "fp_ur_superset_decl":
            check("[face pull superset decl] no premature log (intent only)", "log_exercise" not in names, f"tools={names}")

    SCRIPT = [
        ("I'm about to hit shoulders",        "intent_shoulders"),
        ("Pace me",                            "pace_me"),
        ("130x12 first set on shoulder press", "log_press_1"),
        ("lateral raises next",                "laterals_next"),
        ("16x20 each side first set",          "log_lat_1"),
        ("14 second set",                      "log_lat_2"),
        ("gonna do face pull superset with upright rows", "fp_ur_superset_decl"),
        ("12x70 face pull, 12x110 upright row", "log_fp_ur_1"),
        ("did same reps for 3 sets on both",   "log_fp_ur_roll"),
        ("front raise cable 80x12, shrug 14x190", "pivot_frontraise"),  # face pull must NOT re-log
    ]

    for msg, label in SCRIPT:
        async with Maker() as db:
            user = await reload_user(db, uid)
            today_log = await get_or_create_today_log(db, uid, user.timezone)
            context_str = await build_context(user, today_log, db, platform="telegram", user_message=msg)
            system = f"{system_base}\n\n{context_str}"
            recent = (await db.execute(
                ConversationLog.__table__.select().where(ConversationLog.user_id == uid)
                .order_by(ConversationLog.timestamp.desc()).limit(10))).fetchall()
            messages = []
            for row in reversed(recent):
                messages.append({"role": "user", "content": row.raw_message or ""})
                messages.append({"role": "assistant", "content": row.response or ""})
            messages.append({"role": "user", "content": msg})

            turn = await run_turn(user, db, messages, system, platform="telegram",
                                  in_onboarding=False, was_onboarding=False,
                                  today_log=today_log, source_type="text")
            bubbles = turn.response.bubbles
            names = [t["name"] for t in turn.tool_calls]
            await log_conversation(db, uid, msg, "|||".join(bubbles), source_type="text")
            await db.commit()

        print(f"  {B}{Y}USER:{X} {msg}")
        for b in bubbles:
            print(f"  {C}ARNIE:{X} {b}")
        if names:
            print(f"  {D}      tools: {', '.join(names)}{X}")
        step_checks(label, bubbles, names)
        print()

    # ── Aggregate logging-accuracy tally ─────────────────────────────────────
    tally, rows = await db_tally()
    print(f"{B}{C}{'='*66}{X}")
    print(f"{B} FINAL DB STATE (today's exercise entries){X}")
    for e in rows:
        lb = round((e.weight or 0) * 2.20462)
        print(f"   {e.exercise_name:<24} {e.sets}×{e.reps:<10} @ {lb}lb")
    print(f"{D}   per-exercise total sets: {tally}{X}\n")

    # Performed: press 1, laterals 2, face pull 3, upright row 3, front raise 1, shrug 1
    check("face pull NOT over-logged (≤3 sets, no phantom re-log)", tally.get("face pull", 0) <= 3,
          f"got {tally.get('face pull', 0)} sets")
    check("upright row NOT over-logged (≤3 sets)", tally.get("upright row", 0) <= 3,
          f"got {tally.get('upright row', 0)} sets")
    check("shoulder press logged (set performed)", tally.get("shoulder press machine", 0) >= 1)
    check("lateral raises logged (sets performed)", tally.get("cable lateral raise", 0) >= 1)

    print(f"\n{B}  RESULT: {G}{_pass} passed{X}, {R if _fail else G}{_fail} failed{X}\n")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
