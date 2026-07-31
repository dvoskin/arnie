"""Durable post-turn work (P0.7, architecture review 2026-07-24).

Two defects this closes:
  • memory reflection fired on a 25% coin flip, so two users revealing the
    same durable fact got different outcomes by luck;
  • the work ran as a detached asyncio task, so a deploy or crash dropped it
    with no retry.

Now: deterministic signal gating, plus a queued row that survives the
process and is swept by the scheduler.
"""
import json

import pytest

import core.background_jobs as BJ
from db.queries import (enqueue_background_job, claim_due_background_jobs,
                        finish_background_job)


# ── deterministic gating ──────────────────────────────────────────────────────
def test_memory_signal_is_deterministic_not_sampled():
    """Same input, same answer — every time. (The old path was random.)"""
    text = "I always take my coffee with oat milk now, switched last month"
    assert all(BJ.turn_has_memory_signal(text) for _ in range(20))


@pytest.mark.parametrize("text", [
    "remember that I train at 6am on weekdays",
    "I'm allergic to shellfish",
    "my usual breakfast is eggs and toast",
    "from now on log my shakes as 2 scoops",
    "actually, I stopped drinking coffee entirely",
    "that's wrong, I never eat dairy",
])
def test_real_signals_are_captured(text):
    assert BJ.turn_has_memory_signal(text)


@pytest.mark.parametrize("text", [
    "had a banana",
    "ok cool thanks",
    "how many calories in a bagel?",
    "",
    "yes",
])
def test_ordinary_turns_are_skipped(text):
    assert not BJ.turn_has_memory_signal(text)


# ── durability ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_job_survives_and_dedups(db, make_user):
    user = await make_user()
    jid = await enqueue_background_job(db, user.id, "profile_update",
                                       dedup_key=f"profile:{user.id}")
    assert jid is not None
    # Same key inside the window → collapsed, not queued twice.
    again = await enqueue_background_job(db, user.id, "profile_update",
                                         dedup_key=f"profile:{user.id}")
    assert again is None
    due = await claim_due_background_jobs(db)
    assert [j.id for j in due] == [jid]


@pytest.mark.asyncio
async def test_failure_retries_then_gives_up(db, make_user):
    user = await make_user()
    jid = await enqueue_background_job(db, user.id, "reflection",
                                       payload={"user_text": "x"})
    # Two failures keep it pending (with backoff); the third gives up.
    await finish_background_job(db, jid, ok=False, error="boom")
    from db.models import BackgroundJob
    job = await db.get(BackgroundJob, jid)
    assert job.status == "pending" and job.attempts == 1
    assert job.next_attempt_at is not None      # backoff scheduled
    await finish_background_job(db, jid, ok=False, error="boom")
    await finish_background_job(db, jid, ok=False, error="boom")
    job = await db.get(BackgroundJob, jid)
    # DEAD LETTER, not "failed". The old status read like a transient outcome,
    # so nothing distinguished "will retry" from "gave up forever" and
    # exhausted work was invisible in the queue. This state exists to be
    # alerted on, which is why the rename is worth breaking an assertion for.
    assert job.status == "dead_letter" and job.attempts == 3
    assert job.last_error == "boom"


@pytest.mark.asyncio
async def test_sweep_runs_pending_work_and_marks_it_done(db, make_user, monkeypatch):
    """The safety net: a job the in-process task never finished still runs."""
    user = await make_user()
    jid = await enqueue_background_job(
        db, user.id, "reflection",
        payload={"user_text": "I always train fasted", "response_text": "noted"})

    ran = {"n": 0, "text": ""}
    async def _fake_reflection(user_id, user_text, response_text):
        ran["n"] += 1
        ran["text"] = user_text
    monkeypatch.setattr(BJ, "run_reflection", _fake_reflection)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(BJ, "AsyncSessionLocal", _session)

    n = await BJ.sweep_background_jobs()
    assert n == 1 and ran["n"] == 1
    assert ran["text"] == "I always train fasted"
    from db.models import BackgroundJob
    job = await db.get(BackgroundJob, jid)
    assert job.status == "done" and job.completed_at is not None
    # Nothing left due — a second sweep is a no-op.
    assert await BJ.sweep_background_jobs() == 0


@pytest.mark.asyncio
async def test_sweep_marks_a_failing_job_for_retry(db, make_user, monkeypatch):
    user = await make_user()
    jid = await enqueue_background_job(db, user.id, "profile_update")

    async def _boom(user_id):
        raise RuntimeError("model down")
    monkeypatch.setattr(BJ, "run_profile_update", _boom)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(BJ, "AsyncSessionLocal", _session)

    assert await BJ.sweep_background_jobs() == 1
    from db.models import BackgroundJob
    job = await db.get(BackgroundJob, jid)
    assert job.status == "pending"          # retried, not lost
    assert "model down" in (job.last_error or "")
