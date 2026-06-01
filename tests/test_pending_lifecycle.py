"""
PendingQuestion lifecycle — the conversation-path bridge that records open
follow-up loops and resolves them when answered (reminders.lifecycle).
"""
import pytest

from reminders.lifecycle import sync_pending_questions
from db.queries import get_open_pending_question, get_open_pending_questions


# A fully-onboarded user is missing age/sex/height unless we pass them.
_COMPLETE_STATS = dict(age=30, sex="male", height_cm=180.0)


async def test_records_profile_loop_when_stats_missing(make_user, db):
    u = await make_user(telegram_id="400")  # no age/sex/height
    await sync_pending_questions(db, u)
    pq = await get_open_pending_question(db, u.id, "profile_stats")
    assert pq is not None
    assert pq.tier == "goal_critical"
    assert pq.answered_at is None


async def test_record_is_idempotent(make_user, db):
    u = await make_user(telegram_id="401")
    await sync_pending_questions(db, u)
    await sync_pending_questions(db, u)
    await sync_pending_questions(db, u)
    assert len(await get_open_pending_questions(db, u.id)) == 1


async def test_resolves_when_stats_complete(make_user, db):
    u = await make_user(telegram_id="402")
    await sync_pending_questions(db, u)
    assert await get_open_pending_question(db, u.id, "profile_stats") is not None

    # user fills in their stats → next sync closes the loop
    u.age, u.sex, u.height_cm = 30, "male", 180.0
    await db.commit()
    await sync_pending_questions(db, u)
    assert await get_open_pending_question(db, u.id, "profile_stats") is None


async def test_no_loop_when_stats_already_complete(make_user, db):
    u = await make_user(telegram_id="403", **_COMPLETE_STATS)
    await sync_pending_questions(db, u)
    assert await get_open_pending_questions(db, u.id) == []


async def test_noop_during_onboarding(make_user, db):
    u = await make_user(telegram_id="404", onboarded=False)
    await sync_pending_questions(db, u)
    # nothing recorded while still onboarding (even though stats are missing)
    assert await get_open_pending_questions(db, u.id) == []
