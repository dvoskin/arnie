"""
Scheduler ↔ reminders integration: the context-aware follow-up dispatch.

Drives the real _maybe_followup_pending against an in-memory DB with the network
send + LLM generation stubbed, so it asserts the wiring: a due unanswered question
is re-asked once and its follow_up_count bumps; nothing due → no send.
"""
from datetime import datetime, timedelta

import pytest

import scheduler.proactive_scheduler as sched
from db.models import PendingQuestion
from db.queries import get_open_pending_question


@pytest.fixture
def capture_send(monkeypatch):
    sent = []

    async def _fake_send(send_id, text, effect=None):
        sent.append((send_id, text))

    async def _fake_llm_followup(user, pq, name):
        return "hey, still curious — what's your height?"

    monkeypatch.setattr(sched, "_send", _fake_send)
    monkeypatch.setattr(sched, "_llm_followup", _fake_llm_followup)
    return sent


async def _add_question(db, user_id, *, kind="profile_stats", tier="goal_critical",
                        asked_h_ago=30.0, count=0):
    asked = datetime.utcnow() - timedelta(hours=asked_h_ago)
    pq = PendingQuestion(
        user_id=user_id, kind=kind, question="what's your height?",
        tier=tier, asked_at=asked, last_asked_at=asked, follow_up_count=count,
    )
    db.add(pq)
    await db.commit()
    await db.refresh(pq)
    return pq


async def test_due_question_is_reasked_and_counted(make_user, db, capture_send):
    u = await make_user(telegram_id="300")
    await _add_question(db, u.id, asked_h_ago=30)  # goal_critical, due after 8h

    sent_now = await sched._maybe_followup_pending(db, u, send_id="300",
                                                   name="Danny", mins_since=None)
    assert sent_now is True
    assert len(capture_send) == 1
    # follow_up_count bumped, last_asked_at advanced — but still open (not answered)
    pq = await get_open_pending_question(db, u.id, "profile_stats")
    assert pq is not None and pq.follow_up_count == 1


async def test_no_open_questions_no_send(make_user, db, capture_send):
    u = await make_user(telegram_id="301")
    sent_now = await sched._maybe_followup_pending(db, u, send_id="301",
                                                   name="Danny", mins_since=None)
    assert sent_now is False
    assert capture_send == []


async def test_not_yet_due_question_skipped(make_user, db, capture_send):
    u = await make_user(telegram_id="302")
    # casual question asked 2h ago — first re-ask not due until 24h
    await _add_question(db, u.id, tier="casual", asked_h_ago=2)
    sent_now = await sched._maybe_followup_pending(db, u, send_id="302",
                                                   name="Danny", mins_since=None)
    assert sent_now is False
    assert capture_send == []


async def test_live_conversation_blocks_followup(make_user, db, capture_send):
    u = await make_user(telegram_id="303")
    await _add_question(db, u.id, asked_h_ago=30)  # would otherwise be due
    # user messaged 5 min ago → mid-thread, don't interrupt
    sent_now = await sched._maybe_followup_pending(db, u, send_id="303",
                                                   name="Danny", mins_since=5)
    assert sent_now is False
    assert capture_send == []
