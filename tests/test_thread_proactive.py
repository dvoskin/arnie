"""Memory-graph Stage 2 — thread-driven proactive follow-through.

Pins the mechanism + every discipline guard that keeps it from becoming spam:
  • get_due_threads: only OPEN, salient-enough, next_touch due, not expired,
    right user; ranked salience x overdue.
  • next_touch scheduling: dated events nudge the day before; undated actionable
    loops get a follow-up cadence; non-actionable kinds get NO auto-nudge.
  • mark_thread_touched CLEARS next_touch (one touch per loop — the dedup).
  • _maybe_send_thread_nudge fires once, marks touched, and then finds nothing
    (can't re-fire); no-due → no send; failure paths degrade to False.
  • the frequency gate class (followup_thread → followup_pending).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from db.thread_queries import (
    upsert_thread, get_due_threads, mark_thread_touched, resolve_thread,
)


async def _thread(db, uid, kind, summary, *, salience=4, next_touch=None,
                  expires_at=None):
    t, _ = await upsert_thread(db, uid, kind, summary, salience=salience,
                               next_touch_at=next_touch, expires_at=expires_at)
    return t


async def _puser(db, make_user, **kw):
    """A user with preferences eager-loaded, like the real scheduler loop sees —
    so accessing user.preferences doesn't trigger an async lazy-load."""
    u = await make_user(**kw)
    from db.queries import reload_user
    return await reload_user(db, u.id)


# ── get_due_threads ───────────────────────────────────────────────────────────

async def test_due_thread_fires(db, make_user):
    u = await make_user()
    past = datetime.utcnow() - timedelta(hours=1)
    await _thread(db, u.id, "event", "Hamptons trip", salience=4, next_touch=past)
    due = await get_due_threads(db, u.id, datetime.utcnow())
    assert [t.summary for t in due] == ["Hamptons trip"]


async def test_future_touch_not_due(db, make_user):
    u = await make_user()
    await _thread(db, u.id, "event", "trip next month", salience=5,
                  next_touch=datetime.utcnow() + timedelta(days=20))
    assert await get_due_threads(db, u.id, datetime.utcnow()) == []


async def test_low_salience_excluded(db, make_user):
    u = await make_user()
    await _thread(db, u.id, "intention", "might try something", salience=2,
                  next_touch=datetime.utcnow() - timedelta(hours=1))
    assert await get_due_threads(db, u.id, datetime.utcnow(), min_salience=3) == []


async def test_no_next_touch_never_due(db, make_user):
    u = await make_user()
    await _thread(db, u.id, "watch_item", "protein low", salience=5, next_touch=None)
    assert await get_due_threads(db, u.id, datetime.utcnow()) == []


async def test_resolved_thread_not_due(db, make_user):
    u = await make_user()
    t = await _thread(db, u.id, "event", "old trip", salience=5,
                      next_touch=datetime.utcnow() - timedelta(days=1))
    await resolve_thread(db, t.id, u.id, status="done")
    assert await get_due_threads(db, u.id, datetime.utcnow()) == []


async def test_expired_thread_not_due(db, make_user):
    u = await make_user()
    await _thread(db, u.id, "event", "lapsed", salience=5,
                  next_touch=datetime.utcnow() - timedelta(days=2),
                  expires_at=datetime.utcnow() - timedelta(hours=1))
    assert await get_due_threads(db, u.id, datetime.utcnow()) == []


async def test_ranks_salience_then_overdue(db, make_user):
    u = await make_user()
    now = datetime.utcnow()
    await _thread(db, u.id, "habit", "low but overdue", salience=3,
                  next_touch=now - timedelta(days=3))
    await _thread(db, u.id, "event", "high salience", salience=5,
                  next_touch=now - timedelta(hours=1))
    due = await get_due_threads(db, u.id, now, limit=2)
    assert due[0].summary == "high salience"


# ── mark_thread_touched = the one-touch dedup ─────────────────────────────────

async def test_mark_touched_clears_next_touch(db, make_user):
    u = await make_user()
    t = await _thread(db, u.id, "event", "trip", salience=5,
                      next_touch=datetime.utcnow() - timedelta(hours=1))
    await mark_thread_touched(db, t.id)
    assert await get_due_threads(db, u.id, datetime.utcnow()) == []


# ── next_touch scheduling at capture ──────────────────────────────────────────

def test_default_next_touch_actionable_vs_not():
    from handlers.tool_executor import _default_next_touch
    assert _default_next_touch("promise", "UTC") is not None
    assert _default_next_touch("habit", "UTC") is not None
    assert _default_next_touch("state", "UTC") is not None
    # non-actionable / surfaced-only kinds get no auto-nudge
    assert _default_next_touch("watch_item", "UTC") is None
    assert _default_next_touch("milestone", "UTC") is None
    assert _default_next_touch("other", "UTC") is None


async def test_dated_event_schedules_day_before(db, make_user):
    from handlers.tool_executor import _dispatch
    from db.thread_queries import get_open_threads
    u = await make_user(timezone="America/New_York")
    tomorrow = (datetime.utcnow() + timedelta(days=3)).date().isoformat()
    await _dispatch("remember_thread",
                    {"kind": "event", "summary": "flight to Miami", "when": tomorrow,
                     "salience": 5}, u, None, db, "ios")
    t = (await get_open_threads(db, u.id))[0]
    assert t.next_touch_at is not None
    # nudge lands ~1 day before the start
    assert t.next_touch_at < t.start_at


async def test_undated_habit_gets_followup_touch(db, make_user):
    from handlers.tool_executor import _dispatch
    from db.thread_queries import get_open_threads
    u = await make_user(timezone="UTC")
    await _dispatch("remember_thread",
                    {"kind": "habit", "summary": "add protein at breakfast",
                     "salience": 4}, u, None, db, "ios")
    t = (await get_open_threads(db, u.id))[0]
    assert t.next_touch_at is not None      # will get a proactive check-in
    assert t.next_touch_at > datetime.utcnow()


# ── _maybe_send_thread_nudge: fire-once, mark, no re-fire ─────────────────────

async def test_send_thread_nudge_fires_once_and_marks(db, make_user, monkeypatch):
    import scheduler.proactive_scheduler as P
    u = await _puser(db, make_user)
    await _thread(db, u.id, "event", "Hamptons trip tomorrow", salience=5,
                  next_touch=datetime.utcnow() - timedelta(hours=1))

    sent = []
    async def fake_nudge(user, thread, name):
        return "Hamptons tomorrow, want me to prep your travel-eating plan?"
    async def fake_send(db_, uid, send_id, text, slot, **kw):
        sent.append((slot, text))
    monkeypatch.setattr(P, "_llm_thread_nudge", fake_nudge)
    monkeypatch.setattr(P, "_send_logged_with_voice", fake_send)

    fired = await P._maybe_send_thread_nudge(db, u, "ios:x", "Danny")
    assert fired is True
    assert sent and sent[0][0] == "followup_thread"
    # marked touched → a second scan finds nothing (can't re-fire)
    fired2 = await P._maybe_send_thread_nudge(db, u, "ios:x", "Danny")
    assert fired2 is False


async def test_send_thread_nudge_noop_when_nothing_due(db, make_user, monkeypatch):
    import scheduler.proactive_scheduler as P
    u = await _puser(db, make_user)
    await _thread(db, u.id, "event", "far trip", salience=5,
                  next_touch=datetime.utcnow() + timedelta(days=10))
    async def fake_send(*a, **k):
        raise AssertionError("must not send when nothing is due")
    monkeypatch.setattr(P, "_send_logged_with_voice", fake_send)
    assert await P._maybe_send_thread_nudge(db, u, "ios:x", "Danny") is False


async def test_empty_nudge_does_not_send_or_burn(db, make_user, monkeypatch):
    import scheduler.proactive_scheduler as P
    u = await _puser(db, make_user)
    t = await _thread(db, u.id, "event", "trip", salience=5,
                      next_touch=datetime.utcnow() - timedelta(hours=1))
    async def empty_nudge(*a, **k):
        return ""
    async def fake_send(*a, **k):
        raise AssertionError("must not send an empty nudge")
    monkeypatch.setattr(P, "_llm_thread_nudge", empty_nudge)
    monkeypatch.setattr(P, "_send_logged_with_voice", fake_send)
    assert await P._maybe_send_thread_nudge(db, u, "ios:x", "Danny") is False
    # LLM produced nothing → thread NOT burned, still due for the next tick
    assert len(await get_due_threads(db, u.id, datetime.utcnow())) == 1


# ── frequency gate ────────────────────────────────────────────────────────────

def test_followup_thread_rides_followup_gate():
    from reminders.eligibility import frequency_allows
    from types import SimpleNamespace as NS
    mod = NS(reminder_frequency="moderate")
    assert frequency_allows(mod, "followup_thread") == frequency_allows(mod, "followup_pending")
    none = NS(reminder_frequency="none")
    # "none" users (minimal contact) don't get thread nudges
    assert frequency_allows(none, "followup_thread") is False
