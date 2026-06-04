"""
Behavioral regression check — drives the REAL conversation pipeline (run_turn)
with the LIVE LLM and the production system prompt, to confirm the profile-system
changes did NOT change how Arnie talks over messaging.

Guards the core invariants the system prompt promises:
  • multi-bubble texting (|||), short, sentence-case
  • never self-references as AI
  • NEVER narrates passive memory/extraction ("added to your profile", "I've
    recorded", "in your database") — extraction must stay invisible
  • no em dashes
  • logs food/workouts when mentioned; doesn't log when just chatting
  • explicit "remember X" → natural confirm (silent storage, no clinical DB-speak)
  • "what do you know about me" → surfaces real profile facts, doesn't refuse

Run from arnie/:
    .venv/bin/python simulate_conversation.py
"""
import asyncio
import re
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv(override=True)

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

_pass = 0
_fail = 0
_warn = 0


def check(label, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"    {G}✓{X} {label}" + (f" {D}{detail}{X}" if detail else ""))
    else:
        _fail += 1
        print(f"    {R}✗ {label}{X}" + (f" {R}{detail}{X}" if detail else ""))
    return cond


def warn(label, detail=""):
    global _warn
    _warn += 1
    print(f"    {Y}⚠ {label}{X}" + (f" {D}{detail}{X}" if detail else ""))


# ── Banned-phrase sets ───────────────────────────────────────────────────────
AI_SELFREF = [
    "as an ai", "i'm an ai", "i am an ai", "ai coach", "language model",
    "artificial intelligence", "my model", "i'm a system", "as a language model",
    "i'm a chatbot", "i am a chatbot",
]
# Passive-extraction / clinical memory narration — Arnie must NOT say these.
# (A natural "got it" after an explicit "remember X" is fine; THESE are not.)
MEMORY_NARRATION = [
    "added to your profile", "added that to your profile", "saved to your profile",
    "i've recorded", "i have recorded", "in your database", "to your database",
    "updating your profile", "updated your profile", "in my notes", "to my notes",
    "i've stored", "i have stored", "saving that to", "logging that to your profile",
    "added to your file", "noted in your profile", "in your profile matrix",
    "i'll add that to your profile", "recorded in your profile",
]


def analyze(bubbles, tool_calls, *, allow_long=False, expect_tools=None,
            forbid_tools=None, label=""):
    text = " ||| ".join(bubbles)
    low = text.lower()
    names = [t["name"] for t in tool_calls]

    # 1. bubbles present + non-empty
    check(f"[{label}] produced a real reply", bool(bubbles) and any(b.strip() for b in bubbles),
          f"{len(bubbles)} bubble(s)")

    # 2. no AI self-reference
    hit = next((p for p in AI_SELFREF if p in low), None)
    check(f"[{label}] no AI self-reference", hit is None, f"hit: {hit!r}" if hit else "")

    # 3. no passive memory/extraction narration (THE key anti-regression)
    mhit = next((p for p in MEMORY_NARRATION if p in low), None)
    check(f"[{label}] no memory/extraction narration", mhit is None,
          f"said: {mhit!r}" if mhit else "extraction stays invisible")

    # 4. no em dashes
    check(f"[{label}] no em dashes", "—" not in text and "–" not in text)

    # 5. bubble discipline — multi-bubble OR a single short line, not a wall
    total = sum(len(b) for b in bubbles)
    if not allow_long:
        check(f"[{label}] not essay-length", total < 900, f"{total} chars")
    else:
        if total > 1400:
            warn(f"[{label}] long reply (expected for this prompt)", f"{total} chars")

    # 6. tool expectations
    if expect_tools:
        for t in expect_tools:
            check(f"[{label}] called {t}", t in names, f"tools={names}")
    if forbid_tools:
        for t in forbid_tools:
            check(f"[{label}] did NOT call {t}", t not in names, f"tools={names}")

    return text, names


# ── Conversation script ──────────────────────────────────────────────────────
# (message, kwargs for analyze)
SCRIPT = [
    # food-log: a seeded CONTEXTUAL health attr (zinc) must NOT appear in context
    # here — no health topic in this message.
    ("morning! had greek yogurt with berries and honey for breakfast",
     dict(label="food-log", expect_tools=["log_food"], ctx_lacks=["zinc: 50"])),
    ("just smashed push day — bench 4x8 at 185, then incline db and some flies",
     dict(label="workout-log", expect_tools=["log_exercise"])),
    ("ngl work was brutal today, barely slept and my boss was on me all day",
     dict(label="vent", forbid_tools=["log_food", "log_exercise"])),
    ("what should i have for dinner to hit my protein",
     dict(label="coaching-q", forbid_tools=["log_food"])),
    # supps-topic: health topic → the seeded contextual zinc attr SHOULD surface
    # in context (Step-1 live-injection under test). Pre-dates the user "telling"
    # Arnie about zinc, so it can only come from the learned attribute.
    ("are there any supplements worth taking for recovery and sleep?",
     dict(label="supps-topic", allow_long=True, forbid_tools=["log_food", "log_exercise"],
          ctx_has=["zinc: 50", "[known attributes]"])),
    ("oh also remember i take zinc and creatine every morning",
     dict(label="remember-supps")),  # the silent-storage test
    ("had a barebells caramel bar as a snack",
     dict(label="food-after-remember", expect_tools=["log_food"])),  # must NOT narrate zinc
    ("what do you actually know about me at this point?",
     dict(label="profile-recall", allow_long=True, forbid_tools=["log_food", "log_exercise"])),
]


async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import User, UserPreferences, ConversationLog
    from db.queries import get_or_create_webhook_token, get_or_create_today_log, log_conversation
    from core.context_builder import build_context
    from core.prompts import build_arnie_system
    from core.conversation import run_turn
    from memory.profile_manager import write_profile

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    system_base = build_arnie_system(platform="telegram")

    # ── Seed a realistic onboarded user ─────────────────────────────────────
    async with Maker() as db:
        u = User(
            telegram_id="CONVSIM_001", name="Marcus", age=29, sex="male",
            height_cm=180.0, current_weight_kg=84.0, goal_weight_kg=78.0,
            primary_goal="cut", training_experience="advanced",
            dietary_preferences="high-protein, flexible dieting",
            injuries="none", timezone="America/New_York", onboarding_completed=True,
        )
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2100, protein_target=200,
                               coaching_style="direct", accountability_level="high",
                               wake_time="06:30", sleep_time="22:30"))
        await db.flush()
        await get_or_create_webhook_token(db, u.id)
        uid = u.id
        await db.commit()

        # Seed a profile.md so "what do you know about me" has real material
        await write_profile("CONVSIM_001", _SEED_PROFILE)

        # Seed a CONTEXTUAL learned attribute (health tier=contextual). Step 1
        # should surface it in Arnie's context ONLY when the topic matches.
        from memory.attribute_store import upsert_attribute
        await upsert_attribute(db, uid, attribute_key="health_supplement_zinc_mg",
                               value="50", unit="mg", display_name="Zinc",
                               category="health", relevance_tier="contextual",
                               confidence="confirmed", source="user_stated")

    print(f"\n{B}{C}{'═'*66}{X}")
    print(f"{B}{C} CONVERSATION BEHAVIORAL CHECK — live LLM, production prompt{X}")
    print(f"{B}{C}{'═'*66}{X}")
    print(f"{D}  User: Marcus, 29, advanced, cutting 84→78kg, 2100cal/200g{X}\n")

    for msg, kw in SCRIPT:
        async with Maker() as db:
            from db.queries import reload_user
            user = await reload_user(db, uid)
            today_log = await get_or_create_today_log(db, uid, user.timezone)
            context_str = await build_context(user, today_log, db, platform="telegram",
                                               user_message=msg)
            system = f"{system_base}\n\n{context_str}"

            # history + current
            recent = (await db.execute(
                ConversationLog.__table__.select()
                .where(ConversationLog.user_id == uid)
                .order_by(ConversationLog.timestamp.desc()).limit(8)
            )).fetchall()
            messages = []
            for row in reversed(recent):
                messages.append({"role": "user", "content": row.raw_message or ""})
                messages.append({"role": "assistant", "content": row.response or ""})
            messages.append({"role": "user", "content": msg})

            turn = await run_turn(
                user, db, messages, system, platform="telegram",
                in_onboarding=False, was_onboarding=False, today_log=today_log,
                source_type="text",
            )
            bubbles = turn.response.bubbles
            tool_calls = turn.tool_calls

            # persist so history accrues
            await log_conversation(db, uid, msg, "|||".join(bubbles), source_type="text")
            await db.commit()

        # ── print exchange ──
        print(f"  {B}{Y}USER:{X} {msg}")
        names = [t['name'] for t in tool_calls]
        for b in bubbles:
            print(f"  {C}ARNIE:{X} {b}")
        if names:
            print(f"  {D}      tools: {', '.join(names)}{X}")

        # Step-1 context-injection assertions (tier-filtered, topic-gated).
        ctx_low = context_str.lower()
        for s in kw.pop("ctx_has", []):
            check(f"[{kw.get('label')}] context SHOWS '{s}' (topic match)", s.lower() in ctx_low)
        for s in kw.pop("ctx_lacks", []):
            check(f"[{kw.get('label')}] context HIDES '{s}' (no topic match)", s.lower() not in ctx_low)

        analyze(bubbles, tool_calls, **kw)

        # Targeted extra checks
        if kw.get("label") == "remember-supps":
            low = " ".join(bubbles).lower()
            check("[remember-supps] acknowledges the supplements",
                  "zinc" in low or "creatine" in low or "got it" in low or "covered" in low,
                  "natural confirm")
        if kw.get("label") == "food-after-remember":
            low = " ".join(bubbles).lower()
            # The whole point: logging a snack should NOT resurface zinc/creatine
            # or narrate that anything was remembered.
            check("[food-after-remember] doesn't resurface stored supps unprompted",
                  "zinc" not in low and "creatine" not in low,
                  "extraction stays invisible")
        if kw.get("label") == "profile-recall":
            low = " ".join(bubbles).lower()
            # Should surface at least some real, known facts about Marcus
            facts = sum(x in low for x in ["cut", "protein", "78", "advanced",
                                           "push", "bench", "high-protein", "200"])
            check("[profile-recall] surfaces real known facts", facts >= 1,
                  f"{facts} known facts referenced")
        print()

    # ── summary ──
    print(f"{B}{'═'*66}{X}")
    color = G if _fail == 0 else R
    print(f"{B}{color} RESULT: {_pass} passed, {_fail} failed, {_warn} warnings{X}")
    print(f"{B}{'═'*66}{X}\n")
    return _fail == 0


_SEED_PROFILE = """<!-- last_synced: 2026-06-01T00:00:00+00:00 -->
# User Profile Matrix — Marcus

## Goals & Aspirations
_Last updated: 2026-06-01_
- Primary goal: cut to 78kg  `[confirmed]`
- Deeper why: wants visible abs and to feel athletic again  `[inferred]`

## Nutrition Preferences
_Last updated: 2026-06-01_
- Diet style: high-protein, flexible dieting  `[confirmed]`
- Commonly eaten: greek yogurt, chicken, rice, barebells bars  `[inferred]`
- Protein habits: targets 200g/day, usually hits it  `[confirmed]`

## Fitness Profile
_Last updated: 2026-06-01_
- Training experience: advanced  `[confirmed]`
- Workout split: push/pull/legs  `[inferred]`
- Preferred training time: mornings before work  `[inferred]`

## Behavior & Motivation
_Last updated: 2026-06-01_
- Coaching tone preference: direct, no sugar-coating  `[confirmed]`
- Responds to: straight accountability  `[inferred]`
"""


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
