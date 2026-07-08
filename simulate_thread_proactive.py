"""
Behavioral sim for memory-graph Stage 2 — thread-driven proactive follow-through.

Three layers, run against the REAL code:
  A. DUE-SCAN MATRIX (deterministic, no LLM) — build a spread of threads
     (due/future/low-salience/no-touch/resolved/expired/wrong-user) in an
     in-memory DB and assert get_due_threads picks exactly the right ones.
  B. FIRE PATH (deterministic) — _maybe_send_thread_nudge with a captured send:
     fires once, marks touched, cannot re-fire.
  C. LIVE NUDGE QUALITY (real LLM) — generate the actual proactive nudge for
     several thread kinds and check it references the loop, stays 1-2 bubbles,
     sounds like a coach who remembers (not a reminder bot), and has no em dash.

Run from the repo root:
    .venv/bin/python simulate_thread_proactive.py

Layers A+B need no API key. Layer C needs ANTHROPIC_API_KEY in .env; it's
skipped with a notice if absent.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv(override=True)

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"
_pass = 0
_fail = 0


def check(label, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  {G}PASS{X} {label}")
    else:
        _fail += 1
        print(f"  {R}FAIL{X} {label}  {D}{detail}{X}")


async def _fresh_db():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from db.database import Base
    from db import models  # noqa: register
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return Session


async def _mk_user(db, tz="America/New_York"):
    from db.models import User, UserPreferences
    u = User(telegram_id="ios:sim", name="Danny", onboarding_completed=True, timezone=tz)
    db.add(u); await db.flush()
    db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=True,
                           reminder_frequency="moderate"))
    await db.commit()
    from db.queries import reload_user
    return await reload_user(db, u.id)


# ── Layer A: due-scan matrix ──────────────────────────────────────────────────

async def layer_a():
    print(f"\n{B}A. Due-scan matrix{X}")
    from db.thread_queries import upsert_thread, get_due_threads, resolve_thread
    Session = await _fresh_db()
    async with Session() as db:
        u = await _mk_user(db)
        now = datetime.utcnow()
        async def T(kind, summ, sal, touch, exp=None):
            t, _ = await upsert_thread(db, u.id, kind, summ, salience=sal,
                                       next_touch_at=touch, expires_at=exp)
            return t
        due_trip = await T("event", "Hamptons trip", 5, now - timedelta(hours=1))
        await T("event", "trip next month", 5, now + timedelta(days=20))       # future
        await T("intention", "maybe try mornings", 2, now - timedelta(hours=1))  # low sal
        await T("watch_item", "protein low", 5, None)                           # no touch
        done = await T("event", "past trip", 5, now - timedelta(days=1))
        await resolve_thread(db, done.id, u.id, status="done")                  # resolved
        await T("event", "lapsed", 5, now - timedelta(days=2),
                exp=now - timedelta(hours=1))                                    # expired
        due_habit = await T("habit", "fix breakfast", 3, now - timedelta(days=1))

        due = await get_due_threads(db, u.id, now, limit=10)
        names = {t.summary for t in due}
        check("exactly the two eligible threads are due",
              names == {"Hamptons trip", "fix breakfast"},
              f"got {sorted(names)}")
        top = (await get_due_threads(db, u.id, now, limit=1))[0]
        check("highest-salience fires first", top.summary == "Hamptons trip", top.summary)

        # another user's due thread must not leak
        from db.models import User
        v = User(telegram_id="ios:other", name="Other", onboarding_completed=True, timezone="UTC")
        db.add(v); await db.flush(); await db.commit()
        await upsert_thread(db, v.id, "event", "someone else trip", salience=5,
                            next_touch_at=now - timedelta(hours=1))
        mine = await get_due_threads(db, u.id, now, limit=10)
        check("per-user isolation", all("someone else" not in t.summary for t in mine))


# ── Layer B: fire path ────────────────────────────────────────────────────────

async def layer_b():
    print(f"\n{B}B. Fire path (fire once, mark, no re-fire){X}")
    import scheduler.proactive_scheduler as P
    from db.thread_queries import upsert_thread, get_due_threads
    Session = await _fresh_db()
    async with Session() as db:
        u = await _mk_user(db)
        await upsert_thread(db, u.id, "event", "Hamptons trip tomorrow", salience=5,
                            next_touch_at=datetime.utcnow() - timedelta(hours=1))
        sent = []
        _orig_nudge = P._llm_thread_nudge
        _orig_send = P._send_logged_with_voice
        async def fake_nudge(user, thread, name):
            return "hamptons tomorrow, want me to prep your travel eating plan?"
        async def fake_send(db_, uid, send_id, text, slot, **kw):
            sent.append((slot, text))
        P._llm_thread_nudge = fake_nudge
        P._send_logged_with_voice = fake_send
        try:
            fired = await P._maybe_send_thread_nudge(db, u, "ios:sim", "Danny")
            check("nudge fired for the due trip", fired is True)
            check("sent on the followup_thread slot", sent and sent[0][0] == "followup_thread")
            again = await P._maybe_send_thread_nudge(db, u, "ios:sim", "Danny")
            check("cannot re-fire (marked touched)", again is False)
            check("no second send", len(sent) == 1)
        finally:
            P._llm_thread_nudge = _orig_nudge
            P._send_logged_with_voice = _orig_send


# ── Layer C: live nudge quality ───────────────────────────────────────────────

async def layer_c():
    print(f"\n{B}C. Live nudge quality (real LLM){X}")
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(f"  {Y}SKIP{X} — no ANTHROPIC_API_KEY in .env")
        return
    import scheduler.proactive_scheduler as P
    from types import SimpleNamespace as NS

    tomorrow = datetime.utcnow() + timedelta(days=1)
    cases = [
        ("event", "Hamptons trip with wife and baby, wants high-end restaurants", tomorrow,
         ("hampton", "trip", "dinner", "eat", "restaurant", "pack", "protein")),
        ("habit", "trying to add protein at breakfast", None,
         ("breakfast", "protein", "morning")),
        ("promise", "said I'd check on tonight's workout", None,
         ("workout", "train", "lift", "session", "gym")),
        ("state", "felt burned out this week", None,
         ("feel", "recover", "energy", "rest", "burn")),
    ]
    user = NS(id=1, name="Danny", timezone="America/New_York",
              preferences=NS(preferred_language="English"))
    for kind, summary, start, keywords in cases:
        thread = NS(kind=kind, summary=summary, start_at=start)
        msg = await P._llm_thread_nudge(user, thread, "Danny")
        print(f"  {C}[{kind}]{X} {D}{msg[:150]}{X}")
        check(f"[{kind}] non-empty", bool(msg))
        check(f"[{kind}] <= 2 bubbles", (msg.count('|||') <= 1))
        check(f"[{kind}] no em dash", ("—" not in msg and "–" not in msg))
        check(f"[{kind}] not a reminder bot",
              all(w not in msg.lower() for w in ("reminder", "i have a note", "flagged")))
        check(f"[{kind}] references the loop",
              any(k in msg.lower() for k in keywords),
              f"none of {keywords} in nudge")


async def main():
    print(f"\n{B}Stage-2 proactive follow-through sim{X}")
    await layer_a()
    await layer_b()
    await layer_c()
    print(f"\n{B}{'='*56}{X}")
    color = G if _fail == 0 else R
    print(f"{color}{B}{_pass} passed, {_fail} failed{X}\n")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
