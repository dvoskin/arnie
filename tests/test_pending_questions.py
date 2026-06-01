"""
PendingQuestion store — the backing state for context-aware follow-ups.

Exercises the query layer (record / get-open / followed-up / resolve) against the
real schema. These are the foundational invariants the reminders module relies on:
one open row per kind, answered rows drop out of the open set, resolution is
idempotent and kind-scoped.
"""
import pytest

from db.queries import (
    record_pending_question, get_open_pending_question,
    get_open_pending_questions, mark_pending_question_followed_up,
    resolve_pending_questions,
)


async def test_record_creates_open_row(make_user, db):
    u = await make_user(telegram_id="200")
    pq = await record_pending_question(
        db, u.id, kind="profile_stats", question="what's your height?",
        tier="goal_critical",
    )
    assert pq.id is not None
    assert pq.answered_at is None
    assert pq.tier == "goal_critical"
    assert pq.follow_up_count == 0
    assert pq.asked_at is not None

    open_q = await get_open_pending_question(db, u.id, "profile_stats")
    assert open_q is not None and open_q.id == pq.id


async def test_record_same_kind_updates_in_place(make_user, db):
    """A second ask of the same kind should not stack a duplicate open row."""
    u = await make_user(telegram_id="201")
    first = await record_pending_question(db, u.id, "profile_stats", "height?")
    second = await record_pending_question(
        db, u.id, "profile_stats", "height and weight?", tier="goal_critical"
    )
    assert first.id == second.id           # same row, updated
    assert second.question == "height and weight?"
    assert second.tier == "goal_critical"

    all_open = await get_open_pending_questions(db, u.id)
    assert len(all_open) == 1


async def test_different_kinds_coexist(make_user, db):
    u = await make_user(telegram_id="202")
    await record_pending_question(db, u.id, "profile_stats", "height?")
    await record_pending_question(db, u.id, "goal_check", "still cutting?")
    open_all = await get_open_pending_questions(db, u.id)
    assert {q.kind for q in open_all} == {"profile_stats", "goal_check"}


async def test_mark_followed_up_bumps_count(make_user, db):
    u = await make_user(telegram_id="203")
    pq = await record_pending_question(db, u.id, "goal_check", "still cutting?")
    await mark_pending_question_followed_up(db, pq.id)
    await mark_pending_question_followed_up(db, pq.id)
    refreshed = await get_open_pending_question(db, u.id, "goal_check")
    assert refreshed.follow_up_count == 2
    assert refreshed.last_asked_at is not None


async def test_resolve_by_kind_only_closes_that_kind(make_user, db):
    u = await make_user(telegram_id="204")
    await record_pending_question(db, u.id, "profile_stats", "height?")
    await record_pending_question(db, u.id, "goal_check", "still cutting?")

    closed = await resolve_pending_questions(db, u.id, kinds=["profile_stats"])
    assert closed == 1
    assert await get_open_pending_question(db, u.id, "profile_stats") is None
    assert await get_open_pending_question(db, u.id, "goal_check") is not None


async def test_resolve_all_and_idempotent(make_user, db):
    u = await make_user(telegram_id="205")
    await record_pending_question(db, u.id, "profile_stats", "height?")
    await record_pending_question(db, u.id, "goal_check", "still cutting?")

    closed = await resolve_pending_questions(db, u.id)
    assert closed == 2
    assert await get_open_pending_questions(db, u.id) == []
    # second call closes nothing (already answered)
    assert await resolve_pending_questions(db, u.id) == 0


async def test_resolved_row_lets_new_one_open(make_user, db):
    """After a question is answered, a fresh ask of the same kind opens a new row."""
    u = await make_user(telegram_id="206")
    first = await record_pending_question(db, u.id, "weight_checkin", "weigh in today?")
    await resolve_pending_questions(db, u.id, kinds=["weight_checkin"])

    second = await record_pending_question(db, u.id, "weight_checkin", "weigh in today?")
    assert second.id != first.id
    assert second.answered_at is None
