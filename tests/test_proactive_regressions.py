"""Regressions from the 2026-07-17 transcript audit.

1. Quote-wrapped bubbles: Haiku returned the 4:30 nudge as quoted lines and the
   user received messages wrapped in literal quote marks.
2. Stale thread nudge: "Hamptons trip kicks off today, right?" sent an hour
   AFTER the user said "back from my trip" — thread nudges must defer while the
   user is actively talking (the live turn is the chance to resolve the loop).
"""
from datetime import datetime, timedelta

import pytest

from scheduler.proactive_scheduler import _clean_proactive_text, _throttle_decision

pytestmark = pytest.mark.asyncio


# ── 1. Quote-wrapped bubble sanitizer ────────────────────────────────────────

async def test_quoted_bubbles_are_unwrapped():
    raw = '"It\'s 4:30 and nothing\'s logged yet."|||"Workout still happening today?"'
    assert _clean_proactive_text(raw) == \
        "It's 4:30 and nothing's logged yet.|||Workout still happening today?"


async def test_smart_quotes_and_nesting_unwrap():
    assert _clean_proactive_text("“Scale check?”") == "Scale check?"
    assert _clean_proactive_text('"“double wrapped”"') == "double wrapped"


async def test_internal_quotes_survive():
    # Only WRAPPING pairs strip — a quote inside a sentence is content.
    s = 'You said "no carbs" yesterday, still the plan?'
    assert _clean_proactive_text(s) == s


async def test_blank_bubbles_dropped():
    assert _clean_proactive_text('Hey|||   |||""|||there') == "Hey|||there"
    assert _clean_proactive_text('" "') == ""


async def test_plain_text_untouched():
    s = "End of day check, Danny.|||1000/2148 cal, 1148 under."
    assert _clean_proactive_text(s) == s


# ── 2. Thread-nudge staleness guard ──────────────────────────────────────────

async def test_recent_user_activity_defers_thread_nudge(db, make_user):
    from scheduler.proactive_scheduler import _user_spoke_recently
    from db.models import ConversationLog

    u = await make_user()
    # No conversation at all → not recent.
    assert await _user_spoke_recently(db, u.id) is False

    # A real user turn 30 minutes ago → recent.
    db.add(ConversationLog(user_id=u.id, raw_message="back from my trip",
                           response="welcome back", source_type="ios",
                           timestamp=datetime.utcnow() - timedelta(minutes=30)))
    await db.commit()
    assert await _user_spoke_recently(db, u.id, minutes=180) is True

    # Outside the window → not recent.
    assert await _user_spoke_recently(db, u.id, minutes=20) is False


async def test_proactive_rows_dont_count_as_user_activity(db, make_user):
    from scheduler.proactive_scheduler import _user_spoke_recently
    from db.models import ConversationLog

    u = await make_user()
    db.add(ConversationLog(user_id=u.id, raw_message="",
                           response="nudge|||text", source_type="proactive",
                           timestamp=datetime.utcnow() - timedelta(minutes=5)))
    await db.commit()
    assert await _user_spoke_recently(db, u.id) is False


async def test_defer_thread_touch_pushes_forward(db, make_user):
    from db.thread_queries import defer_thread_touch
    from db.models import UserThread

    u = await make_user()
    t = UserThread(user_id=u.id, kind="event", summary="Hamptons trip",
                   next_touch_at=datetime.utcnow() - timedelta(hours=1))
    db.add(t)
    await db.commit()
    await defer_thread_touch(db, t.id, hours=4)
    await db.refresh(t)
    assert t.next_touch_at > datetime.utcnow() + timedelta(hours=3)


# ── Budget sanity (the gate that finally shipped today) ──────────────────────

async def test_throttle_decision_matrix():
    assert _throttle_decision(0, None, 4, 90) == "send"
    assert _throttle_decision(4, 200, 4, 90) == "cap"      # daily cap
    assert _throttle_decision(1, 15, 4, 90) == "gap"       # Marina's 13:15→13:30
    assert _throttle_decision(3, 91, 4, 90) == "send"
