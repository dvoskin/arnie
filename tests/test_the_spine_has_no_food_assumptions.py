"""A fake second domain, run through the real spine (directive §27).

Workout logging must later adopt the operation claim, the coordinator, the
duplicate replay, rollback and result persistence WITHOUT another foundational
rewrite. "Workout-ready" is not a claim anyone gets to make in prose — it is
this test: a payload that is not a meal, a writer that writes no food rows,
through the same `commit_or_load_existing` production food uses.

The spine's job is: claim under (operation, revision) → invoke the injected
writer with the payload it was handed, UNREAD → persist the result → replay
duplicates from storage. If any stage peeks inside the payload, requires a
`FoodEntry`, or touches a daily log, this fails.

WHAT IS PINNED AS SHARED today: the coordinator, the claim, the persisted
result mechanics. WHAT IS KNOWN FOOD-NAMED: the result container is
`MealCommitResult` — generically shaped (items, totals, assumptions, warnings,
render_actions) but food-named; §5's `OperationResult` envelope carrying a
`DomainCommitResult` is the Phase-C rename, extracted when the second real
domain demonstrates it (rule of two, §24). This test uses the container as the
protocol it already is.
"""
import os
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import meal_commit
from core.commit_coordinator import commit_or_load_existing
from core.meal_commit import MealCommitResult, OutboxEvent
from db.database import make_engine
from db.models import Base, BackgroundJob, DailyLog, FoodEntry, LedgerEvent, User

PG = os.getenv("TEST_POSTGRES_URL")
if os.getenv("CI") and not PG:
    raise RuntimeError("TEST_POSTGRES_URL is unset in CI.")
pytestmark = pytest.mark.skipif(not PG, reason="needs a real Postgres")


# ── the fake domain: deliberately nothing like food ──────────────────────────

@dataclass(frozen=True)
class FakeResolvedSet:
    reps: int
    load_kg: float


@dataclass(frozen=True)
class FakeResolvedActivity:
    """A workout-shaped payload with NO food fields at all."""
    operation_id: str
    revision: int
    user_id: int
    exercise: str
    sets: tuple


class _Op:
    def __init__(self, payload):
        self.id = payload.operation_id
        self.revision = payload.revision
        self.user_id = payload.user_id


async def fake_activity_writer(db, *, operation, resolved_meal):
    """Writes NOTHING food-shaped. The rows a real WorkoutWriter would write
    live in its own tables; here the result alone carries the facts, which is
    enough to prove the coordinator neither requires food rows nor inspects
    the payload."""
    activity = resolved_meal
    assert isinstance(activity, FakeResolvedActivity), (
        "the coordinator re-shaped the payload on its way to the writer")
    total_reps = sum(s.reps for s in activity.sets)
    return MealCommitResult(
        committed_items=tuple(
            {"entry_id": i + 1, "set": f"{s.reps}x{s.load_kg}kg"}
            for i, s in enumerate(activity.sets)),
        meal_totals={"total_reps": total_reps,
                     "top_load_kg": max(s.load_kg for s in activity.sets)},
        assumptions=("assumed barbell, as last session",),
        render_actions=({"action": "refresh_training_view",
                         "user_id": activity.user_id},),
        # DURABLE POST-COMMIT WORK, from a domain with no food rows. The
        # coordinator hard-requires `OutboxEvent` — a type that lives in
        # core.meal_commit — so the newest shared-spine requirement was
        # unproven for any other domain until this writer emitted one.
        outbox_events=(OutboxEvent(
            kind="training_analysis",
            payload={"exercise": activity.exercise,
                     "total_reps": total_reps},
            dedup_key=f"u{activity.user_id}:analysis:{activity.operation_id}"),))


BENCH = FakeResolvedActivity(
    operation_id="fake:1:wk_1", revision=0, user_id=1,
    exercise="barbell_bench_press",
    sets=(FakeResolvedSet(8, 60.0), FakeResolvedSet(8, 60.0),
          FakeResolvedSet(6, 62.5)))


@pytest_asyncio.fixture
async def pg():
    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        s.add(User(telegram_id="pg:fake-domain"))
        await s.commit()
    yield maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_non_food_domain_commits_through_the_same_spine(pg):
    async with pg() as s:
        result = await commit_or_load_existing(
            s, operation=_Op(BENCH), resolved_meal=BENCH,
            writer=fake_activity_writer)
        await s.commit()

    assert result.meal_totals == {"total_reps": 22, "top_load_kg": 62.5}
    assert len(result.committed_items) == 3

    # ...and the spine wrote NO food artefacts on the fake domain's behalf.
    async with pg() as s:
        for model in (FoodEntry, DailyLog, LedgerEvent):
            n = (await s.execute(
                select(func.count()).select_from(model))).scalar()
            assert n == 0, (
                f"the coordinator created {model.__name__} rows for a domain "
                f"that has none — the spine is food-coupled")

        # ...while the durable post-commit work DID land, in the same
        # transaction as the (absent) rows. Enqueue is the newest shared-spine
        # requirement and the one the fake domain never exercised.
        jobs = (await s.execute(select(BackgroundJob))).scalars().all()
        assert [j.kind for j in jobs] == ["training_analysis"], \
            f"expected one non-food outbox job, got {[j.kind for j in jobs]}"


@pytest.mark.asyncio
async def test_a_duplicate_fake_domain_delivery_replays_from_storage(pg):
    """The duplicate is answered from the PERSISTED result — including the
    disclosure — with the writer never invoked again. Same guarantee food
    gets, proven domain-neutral."""
    calls = {"n": 0}

    async def counting_writer(db, **kw):
        calls["n"] += 1
        return await fake_activity_writer(db, **kw)

    async with pg() as s:
        first = await commit_or_load_existing(
            s, operation=_Op(BENCH), resolved_meal=BENCH,
            writer=counting_writer)
        await s.commit()
    async with pg() as s:
        second = await commit_or_load_existing(
            s, operation=_Op(BENCH), resolved_meal=BENCH,
            writer=counting_writer)
        await s.commit()

    assert calls["n"] == 1, "the duplicate re-ran the writer"
    assert second == first
    assert second.assumptions == ("assumed barbell, as last session",)


@pytest.mark.asyncio
async def test_a_fake_domain_failure_unwinds_like_a_food_one(pg):
    async def failing_writer(db, **kw):
        raise RuntimeError("rack unavailable")

    async with pg() as s:
        with pytest.raises(RuntimeError):
            await commit_or_load_existing(
                s, operation=_Op(BENCH), resolved_meal=BENCH,
                writer=failing_writer)
        await s.rollback()
    async with pg() as s:
        assert await meal_commit.existing_result(
            s, operation_id=BENCH.operation_id) is None, (
            "a failed fake-domain write left a claim or result behind")

    # ...and the retry succeeds cleanly, exactly as food's does.
    async with pg() as s:
        retry = await commit_or_load_existing(
            s, operation=_Op(BENCH), resolved_meal=BENCH,
            writer=fake_activity_writer)
        await s.commit()
    assert retry.meal_totals["total_reps"] == 22
