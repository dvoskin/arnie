"""Post-commit work is queued INSIDE the transaction that owes it.

`background_jobs` was already durable, retried, backed off and deduped — an
outbox in all but name. Three things it could not do, and one thing it did
that it should not have:

  * `enqueue_background_job` called `await db.commit()`. A caller holding an
    open transaction had their half-finished domain work committed as a side
    effect of queuing a job — a hidden commit inside a helper, which is the
    ownership rule this codebase already learned with ledger events. It also
    meant the job and the mutation could not be atomic: a crash between them
    lost the work the write owed.
  * claiming was a plain SELECT, so two sweepers took the same rows and did
    the work twice. Survivable while both job kinds were idempotent, not
    survivable once anything user-visible joins the queue — sending a push
    twice is not a no-op.
  * exhausted retries became `failed`, which reads transient. Nothing
    separated "will retry" from "gave up forever".
  * nothing recorded WHICH turn or WHICH build queued the work.

These pin the corrections. They are about the queue's contract, not about any
particular job kind.
"""
import pytest
from sqlalchemy import select

from db.models import BackgroundJob, FoodEntry
from db.queries import (add_food_entry, enqueue_background_job,
                        claim_due_background_jobs, finish_background_job,
                        get_or_create_today_log, outbox_health,
                        requeue_stale_jobs)


# ── the transaction ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_queued_job_and_its_mutation_are_one_transaction(db, make_user):
    """The whole point of an outbox. If the write rolls back, so does the work
    it owed — there is no state where the food vanished but the job survived."""
    user = await make_user(telegram_id="outbox:atomic")
    log = await get_or_create_today_log(db, user.id, "UTC")

    entry = await add_food_entry(
        db, daily_log_id=log.id, user_id=user.id,
        ledger_source="test", parsed_food_name="Soup", calories=150)
    await enqueue_background_job(db, user.id, "reflection",
                                 payload={"entry": entry.id}, commit=False)
    await db.commit()

    jobs = (await db.execute(select(BackgroundJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == "pending"


@pytest.mark.asyncio
async def test_enqueue_does_not_commit_the_callers_work(db, make_user):
    """`commit=False` must leave the caller's transaction open. If the helper
    committed, a mutation could become durable before its caller decided it
    should be — which is how a failed request leaves committed state."""
    user = await make_user(telegram_id="outbox:nocommit")
    log = await get_or_create_today_log(db, user.id, "UTC")

    entry = FoodEntry(daily_log_id=log.id, parsed_food_name="Uncommitted",
                      calories=99)
    db.add(entry)
    await db.flush()
    await enqueue_background_job(db, user.id, "reflection", commit=False)

    await db.rollback()          # the caller changes its mind

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Uncommitted")
    )).scalars().all()
    jobs = (await db.execute(select(BackgroundJob))).scalars().all()
    assert rows == [], "the helper committed the caller's uncommitted write"
    assert jobs == [], "the job outlived the transaction that queued it"


@pytest.mark.asyncio
async def test_the_default_still_commits_for_existing_callers(db, make_user):
    """Backward compatibility: every existing call site passes no `commit`
    and must keep working exactly as before."""
    user = await make_user(telegram_id="outbox:default")
    jid = await enqueue_background_job(db, user.id, "profile_update")
    assert jid is not None
    assert (await db.get(BackgroundJob, jid)).status == "pending"


# ── identity and provenance ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queued_work_names_the_turn_and_build_that_queued_it(db, make_user):
    """A job that fails two days later was previously unattributable."""
    from core.turn_identity import CURRENT_TURN_ID

    user = await make_user(telegram_id="outbox:turn")
    token = CURRENT_TURN_ID.set("ios:OUTBOX-1")
    try:
        jid = await enqueue_background_job(db, user.id, "reflection")
    finally:
        CURRENT_TURN_ID.reset(token)

    job = await db.get(BackgroundJob, jid)
    assert job.turn_id == "ios:OUTBOX-1", (
        "post-commit work does not join the request that caused it"
    )
    assert job.build_sha, "the job cannot say which deploy queued it"


# ── claiming ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claiming_marks_the_row_so_a_second_sweeper_skips_it(db, make_user):
    """Claiming used to be a plain SELECT — two sweepers, same rows, work done
    twice."""
    user = await make_user(telegram_id="outbox:claim")
    await enqueue_background_job(db, user.id, "reflection")

    first = await claim_due_background_jobs(db, limit=10)
    assert len(first) == 1
    assert first[0].status == "processing"
    assert first[0].claimed_at is not None

    second = await claim_due_background_jobs(db, limit=10)
    assert second == [], "a claimed job was handed to a second sweeper"


@pytest.mark.asyncio
async def test_a_retry_returns_the_job_to_pending(db, make_user):
    """A claimed row that fails must become claimable again, or the queue
    drains to a stop on the first failure."""
    user = await make_user(telegram_id="outbox:retry")
    jid = await enqueue_background_job(db, user.id, "reflection")
    await claim_due_background_jobs(db, limit=10)

    await finish_background_job(db, jid, ok=False, error="boom")

    job = await db.get(BackgroundJob, jid)
    assert job.status == "pending"
    assert job.claimed_at is None


@pytest.mark.asyncio
async def test_a_job_abandoned_by_a_dead_worker_is_requeued(db, make_user):
    """A worker that dies between claiming and finishing leaves the row
    `processing` forever. A queue that silently stops draining is worse than
    one that visibly backs up."""
    from datetime import datetime, timedelta

    user = await make_user(telegram_id="outbox:stale")
    jid = await enqueue_background_job(db, user.id, "reflection")
    await claim_due_background_jobs(db, limit=10)

    job = await db.get(BackgroundJob, jid)
    job.claimed_at = datetime.utcnow() - timedelta(hours=2)
    await db.commit()

    assert await requeue_stale_jobs(db, older_than_min=15) == 1
    assert (await db.get(BackgroundJob, jid)).status == "pending"


# ── visibility ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_backlog_is_observable(db, make_user):
    """A queue nobody can see is a queue nobody notices has stopped."""
    user = await make_user(telegram_id="outbox:health")
    await enqueue_background_job(db, user.id, "reflection")

    health = await outbox_health(db)
    assert health["pending"] == 1
    assert health["dead_letter"] == 0
    assert "oldest_pending_age_s" in health
