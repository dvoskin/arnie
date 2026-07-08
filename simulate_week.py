"""
END-TO-END WEEK REGRESSION SIM — a persona's 5-day arc through the REAL pipeline.

Drives run_chat_turn with the LIVE LLM and the production system prompt over a
frozen-time week, exercising every facet we've built and asserting regression
invariants at each step:

  Day 1  logging (multi-item food, correction, weigh-in) + the weight-misroute
         regression (a food number after weight-talk must NOT re-log weight)
  Day 2  relational memory (capture wife/daughter + the deeper why → core tier)
  Day 3  open-loop capture (trip → user_threads row, next_touch scheduled) +
         deep-research routing
  Day 4  workout program builder (no degenerate days) + proactive follow-through
         (the trip's day-before nudge fires and marks the thread touched)
  Day 5  late-night read (no "breakfast"/"lunch" at 1am) + entry MOVE (no false
         failure) + relational RECALL (knows the daughter's name)

Hard checks read DB state; soft checks read the reply (tolerant of LLM
non-determinism — pattern/skills, not exact wording). Coaching hygiene (non-empty,
no em dash) is checked on every turn.

Run from repo root:
    .venv/bin/python simulate_week.py

Needs ANTHROPIC_API_KEY in .env. Sets SEARCH_ENABLED so deep_research is live;
Tavily may be absent locally (deep_research then returns an honest fallback — we
assert ROUTING here, plan quality is covered by simulate_deep_research.py).
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, date

os.environ.setdefault("SEARCH_ENABLED", "true")
os.environ.setdefault("DEEP_RESEARCH_TIME_BUDGET", "8")
os.environ.setdefault("DEEP_RESEARCH_MAX_ROUNDS", "1")

from dotenv import load_dotenv
load_dotenv(override=True)
os.environ["SEARCH_ENABLED"] = "true"

from freezegun import freeze_time

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"
_pass = 0; _fail = 0


def check(label, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"    {G}ok{X} {label}")
    else:
        _fail += 1
        print(f"    {R}XX{X} {label}  {D}{detail}{X}")


EMDASH = ("—", "–")


async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import select, func
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import (User, UserPreferences, FoodEntry, DailyLog, UserThread,
                           UserAttribute, BodyMetric, GeneratedWorkoutProgram,
                           GeneratedWorkoutSession, ConversationLog)
    from db.queries import reload_user
    from core.chat_service import run_chat_turn

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    TZ = "America/New_York"
    async with Maker() as db:
        u = User(telegram_id="ios:week", name="Jordan", age=34, sex="male",
                 height_cm=180.0, current_weight_kg=86.0, goal_weight_kg=79.0,
                 primary_goal="cut", training_experience="beginner",
                 timezone=TZ, onboarding_completed=True)
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2200, protein_target=185,
                               coaching_style="balanced", accountability_level="high",
                               wake_time="06:30", sleep_time="23:00",
                               reminder_frequency="moderate",
                               food_logging_mode="moderate",
                               proactive_messaging_enabled=True))
        await db.commit()
        uid = u.id

    async def turn(msg, when: datetime):
        """One live turn at a frozen wall-clock. Returns (bubbles, skills, joined)."""
        with freeze_time(when):
            async with Maker() as db:
                user = await reload_user(db, uid)
                t = await run_chat_turn(db, user, msg, platform="ios",
                                        source_type="ios", schedule_background=False)
        bubbles = t.response.bubbles if t and t.response else []
        joined = "|||".join(bubbles)
        # latest persisted skills_fired
        async with Maker() as db:
            row = (await db.execute(
                select(ConversationLog).where(ConversationLog.user_id == uid)
                .order_by(ConversationLog.id.desc()).limit(1))).scalar_one_or_none()
            skills = (row.skills_fired or "") if row else ""
        print(f"  {C}» {msg[:66]}{X}")
        print(f"    {D}fired: {skills or '(none)'} | {joined[:96]}{X}")
        # coaching hygiene on every turn
        check("reply non-empty", bool(joined.strip()))
        check("no em/en dash", not any(e in joined for e in EMDASH), joined[:80])
        return bubbles, skills, joined

    async def snap():
        async with Maker() as db:
            foods = (await db.execute(select(FoodEntry).join(DailyLog)
                     .where(DailyLog.user_id == uid))).scalars().all()
            threads = (await db.execute(select(UserThread)
                       .where(UserThread.user_id == uid))).scalars().all()
            attrs = (await db.execute(select(UserAttribute)
                     .where(UserAttribute.user_id == uid))).scalars().all()
            weights = (await db.execute(select(BodyMetric)
                       .where(BodyMetric.user_id == uid))).scalars().all()
            progs = (await db.execute(select(GeneratedWorkoutProgram)
                     .where(GeneratedWorkoutProgram.user_id == uid,
                            GeneratedWorkoutProgram.active == True))).scalars().all()  # noqa
        return foods, threads, attrs, weights, progs

    base = datetime(2026, 7, 13, 8, 0)  # a Monday, 8am local-ish

    # ── DAY 1 — logging + weight-misroute regression ─────────────────────────
    print(f"\n{B}Day 1 (Mon) — logging + weigh-in{X}")
    await turn("morning. had 3 scrambled eggs and a bowl of oatmeal", base)
    foods, *_ = await snap()
    check("food logged (>=1 entry)", len(foods) >= 1, f"{len(foods)} entries")
    await turn("weighed in at 190 this morning", base + timedelta(minutes=5))
    _, _, _, weights, _ = await snap()
    check("weigh-in stored", len(weights) == 1, f"{len(weights)} body metrics")
    # THE regression: a food number right after weight-talk must route to food
    _, skills, _ = await turn("just had a protein bar, like 200 cal", base + timedelta(minutes=8))
    _, _, _, weights2, _ = await snap()
    check("food-after-weight did NOT re-log weight", len(weights2) == 1,
          f"weights went {len(weights)}->{len(weights2)}")
    # The regression is the MISROUTE — a food number after weight-talk must not
    # hit log_body_weight. Logging vs. clarifying the brand are both fine.
    check("protein bar not routed to log_body_weight",
          "log_body_weight" not in skills, skills)

    # ── DAY 2 — relational memory capture ────────────────────────────────────
    print(f"\n{B}Day 2 (Tue) — relational memory{X}")
    d2 = base + timedelta(days=1)
    await turn("my wife Sarah started keto and honestly it's motivating me", d2)
    await turn("real talk, I want to get in shape to keep up with my daughter Mia, she's 4", d2 + timedelta(minutes=3))
    _, _, attrs, _, _ = await snap()
    relational = [a for a in attrs if a.relevance_tier == "core" and
                  any(m in a.attribute_key.lower() for m in ("person", "wife", "daughter", "why", "motiv", "family", "child"))]
    check("captured a relational fact at core tier", len(relational) >= 1,
          f"attrs={[a.attribute_key for a in attrs]}")
    joined_vals = " ".join((a.value or "").lower() for a in attrs)
    check("remembers a name (Sarah or Mia)", ("sarah" in joined_vals or "mia" in joined_vals),
          joined_vals[:120])

    # ── DAY 3 — open-loop capture + deep-research routing ────────────────────
    print(f"\n{B}Day 3 (Wed) — trip: thread capture + deep research{X}")
    d3 = base + timedelta(days=2)
    _, skills_trip, jn_trip = await turn(
        "heads up, I'm flying to Austin this Friday for work, hotel gym only", d3)
    _, threads, _, _, _ = await snap()
    print(f"    {D}threads now: {[(t.kind, t.summary) for t in threads]}{X}")
    trip = [t for t in threads if any(w in (t.summary or "").lower()
            for w in ("austin", "trip", "travel", "flying", "hotel", "work"))]
    # Capture succeeds if a trip thread exists OR remember_thread fired this turn.
    check("trip captured as an open thread",
          len(trip) >= 1 or "remember_thread" in skills_trip,
          f"skills={skills_trip} threads={[t.summary for t in threads]}")
    if trip:
        check("trip thread has a proactive next_touch", trip[0].next_touch_at is not None)
    _, skills, jn_plan = await turn("plan my eating strategy for the Austin trip", d3 + timedelta(minutes=2))
    print(f"    {D}plan reply: {jn_plan[:140]}{X}")
    check("plan ask routed to deep_research", "deep_research" in skills, skills)

    # ── DAY 4 — workout program + proactive follow-through ───────────────────
    print(f"\n{B}Day 4 (Thu) — program builder + proactive nudge{X}")
    d4 = base + timedelta(days=3)
    _, skills, _ = await turn("build me a workout program, 4 days a week, dumbbells and bands at home", d4)
    # propose_workout_program is instructed to ask up to 2 clarifiers first — if it
    # did, answer them, then it should build. (Both paths are correct.)
    if "propose_workout_program" not in skills:
        _, skills, _ = await turn("losing weight, I'm a beginner, full body's good", d4 + timedelta(minutes=1))
    check("program build routed to propose_workout_program",
          "propose_workout_program" in skills, skills)
    async with Maker() as db:
        progs = (await db.execute(select(GeneratedWorkoutProgram)
                 .where(GeneratedWorkoutProgram.user_id == uid,
                        GeneratedWorkoutProgram.active == True))).scalars().all()  # noqa
        deg = None
        if progs:
            sess = (await db.execute(select(GeneratedWorkoutSession)
                    .where(GeneratedWorkoutSession.program_id == progs[0].id))).scalars().all()
            import json as _j
            deg = min((len(_j.loads(s.exercises_json or "[]")) for s in sess), default=0)
    check("a program was persisted", bool(progs), f"{len(progs)} active")
    if progs:
        check("no degenerate session (>=3 exercises each)", (deg or 0) >= 3, f"min={deg}")

    # Proactive: it's Thursday ~9:30am, the Austin (Fri) thread's next_touch is due.
    print(f"  {D}— proactive scan (Thu 9:30am){X}")
    import scheduler.proactive_scheduler as P
    sent = []
    _osend = P._send_logged_with_voice
    async def _cap(db_, uid_, sid, text, slot, **kw): sent.append((slot, text))
    P._send_logged_with_voice = _cap
    try:
        with freeze_time(d4.replace(hour=9, minute=30)):
            async with Maker() as db:
                user = await reload_user(db, uid)
                fired = await P._maybe_send_thread_nudge(db, user, "ios:week", "Jordan")
        check("proactive thread nudge fired for the trip", fired is True)
        check("nudge references the trip",
              bool(sent) and any(w in sent[0][1].lower()
                                 for w in ("austin", "trip", "travel", "hotel", "gym", "pack")),
              sent[:1])
        # and it can't re-fire (marked touched)
        with freeze_time(d4.replace(hour=9, minute=45)):
            async with Maker() as db:
                user = await reload_user(db, uid)
                again = await P._maybe_send_thread_nudge(db, user, "ios:week", "Jordan")
        check("nudge does not re-fire (one touch per loop)", again is False)
    finally:
        P._send_logged_with_voice = _osend

    # ── DAY 5 — late-night read + move + relational recall ───────────────────
    print(f"\n{B}Day 5 (Sat 1am) — late-night + move + recall{X}")
    late = datetime(2026, 7, 18, 1, 0)  # 1am
    _, skills, joined = await turn("having a late snack, handful of almonds", late)
    check("late-night: not called 'breakfast'/'lunch'",
          not any(w in joined.lower() for w in ("breakfast", "lunch")), joined[:100])
    await turn("actually move the almonds to yesterday", late + timedelta(minutes=2))
    # move regression: reply must not claim a failure
    _, _, jn = (None, None, joined)
    _, skills_m, joined_m = await turn("did that move go through?", late + timedelta(minutes=3))
    check("move not falsely reported as failed",
          not any(w in joined_m.lower() for w in ("snag", "didn't go through", "couldn't")),
          joined_m[:110])
    _, _, joined_r = await turn("what's my daughter's name again?", late + timedelta(minutes=5))
    check("relational recall — knows the daughter's name",
          "mia" in joined_r.lower(), joined_r[:110])

    print(f"\n{B}{'='*60}{X}")
    color = G if _fail == 0 else R
    print(f"{color}{B}{_pass} passed, {_fail} failed{X}\n")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
