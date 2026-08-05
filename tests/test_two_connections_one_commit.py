"""Two real connections, one operation revision — the directive's actual gate.

    "one operation revision commits at most once and every duplicate receives
     the original authoritative result"

`test_commit_coordinator_0804.py` and `test_meal_commit_boundary_0804.py` assert
that on sqlite. Sqlite cannot express it. Two things are missing there and both
are the whole point:

  1. A SECOND CONNECTION. Even the WAL file database those tests use races
     nothing — the calls are sequential and merely isolated.
  2. POSTGRES'S ABORT SEMANTICS. A constraint violation aborts the entire
     transaction; every later statement fails with "current transaction is
     aborted" until it is rolled back. Sqlite does not do that. So on sqlite,
     `claim_commit`'s SAVEPOINT looks like defensive tidiness, and on the
     database that actually runs it is the only reason a duplicate does not
     destroy the turn holding it.

There is also a guarantee that only a real race can demonstrate. Postgres
BLOCKS a conflicting unique insert until the first transaction resolves, so a
loser does not merely discover a duplicate — it discovers a duplicate whose
result is already durable. `CommitInProgress` should therefore be unreachable
in a plain race, and a duplicate should always come back with the winner's
result rather than an in-progress error.

SKIPS without `TEST_POSTGRES_URL`, and FAILS if CI lacks one, following
`test_two_connections_one_meal.py` — a green tick standing in for an unrun
check is worse than a red one.
"""
import asyncio
import os
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.database import make_engine

from core import meal_commit
from core.commit_coordinator import commit_or_load_existing
from core.meal_commit import MealCommitResult, claim_commit
from db.models import Base, DailyLog, FoodEntry, MealCommit, User

PG = os.getenv("TEST_POSTGRES_URL")

if os.getenv("CI") and not PG:
    raise RuntimeError(
        "TEST_POSTGRES_URL is unset in CI. The commit boundary's guarantee is "
        "a database guarantee; sqlite shares one connection and does not abort "
        "a transaction on constraint violation, so it cannot test either half.")

pytestmark = pytest.mark.skipif(
    not PG, reason="needs a real Postgres (TEST_POSTGRES_URL); sqlite cannot "
                   "express a cross-connection race or an aborted transaction")

MEAL = [{"name": "Chicken", "calories": 320}, {"name": "Rice", "calories": 200}]


class _Op:
    def __init__(self, oid, revision=0, user_id=1):
        self.id, self.revision, self.user_id = oid, revision, user_id


@pytest.fixture
async def pg():
    # via the factory: an unpinned Postgres engine is refused outright,
    # which is what keeps the UTC guarantee from being opt-in.
    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _seed(maker) -> tuple:
    async with maker() as s:
        user = User(telegram_id="pg:commit")
        s.add(user)
        await s.flush()
        log = DailyLog(user_id=user.id, date=date(2026, 8, 4))
        s.add(log)
        await s.commit()
        return user.id, log.id


def _writer_for(log_id):
    async def _writer(db, *, operation, resolved_meal):
        ids = []
        for item in resolved_meal:
            row = FoodEntry(daily_log_id=log_id,
                            parsed_food_name=item["name"],
                            calories=item["calories"])
            db.add(row)
            await db.flush()
            ids.append(row.id)
        return MealCommitResult(
            committed_items=tuple({"entry_id": i} for i in ids),
            meal_totals={"calories": sum(i["calories"] for i in resolved_meal)})
    return _writer


@pytest.mark.asyncio
async def test_three_connections_one_revision_write_one_meal(pg):
    """THE gate, both halves at once, on the database that runs in production.

    Exactly one caller writes food. The other two receive that caller's result
    — not None, not an error, and not a second copy of the meal.
    """
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    _, log_id = await _seed(maker)
    writer = _writer_for(log_id)

    async def attempt():
        async with maker() as s:
            try:
                result = await commit_or_load_existing(
                    s, operation=_Op("op_race"), resolved_meal=MEAL,
                    writer=writer)
                await s.commit()
                return result
            except Exception as exc:            # noqa: BLE001 — reported below
                await s.rollback()
                return exc

    outcomes = await asyncio.gather(attempt(), attempt(), attempt())

    results = [o for o in outcomes if isinstance(o, MealCommitResult)]
    assert len(results) == 3, (
        f"every caller must receive the authoritative result; got {outcomes}")
    assert all(r == results[0] for r in results), (
        f"the duplicates did not receive the ORIGINAL result: {results}")

    async with maker() as s:
        rows = (await s.execute(select(func.count()).select_from(FoodEntry))
                ).scalar()
        claims = (await s.execute(select(func.count()).select_from(MealCommit))
                  ).scalar()
    assert rows == len(MEAL), f"the meal was written {rows / len(MEAL)}×"
    assert claims == 1


@pytest.mark.asyncio
async def test_the_index_rejects_the_second_claim_not_the_application(pg):
    """Proves the guard is the UNIQUE INDEX, not a select-then-insert window.
    If this passes with the constraint gone, everything else here is
    decoration."""
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)

    def row():
        return MealCommit(operation_id="op_idx", operation_revision=0,
                          user_id=1, status="claimed")

    async with maker() as a:
        a.add(row())
        await a.commit()

    async with maker() as b:                    # a genuinely separate connection
        b.add(row())
        with pytest.raises(IntegrityError):
            await b.commit()


@pytest.mark.asyncio
async def test_a_duplicate_does_not_abort_the_turn_holding_it(pg):
    """THE test sqlite cannot write.

    On Postgres a unique violation aborts the transaction — every subsequent
    statement raises until rollback. A duplicate commit is a NORMAL outcome, so
    without `claim_commit`'s SAVEPOINT the ordinary case of a user tapping twice
    would take the entire turn's staged work down with it, and the commit below
    would fail outright.
    """
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    _, log_id = await _seed(maker)
    writer = _writer_for(log_id)

    async with maker() as a:
        await commit_or_load_existing(a, operation=_Op("op_abort"),
                                      resolved_meal=MEAL, writer=writer)
        await a.commit()

    async with maker() as b:
        b.add(FoodEntry(daily_log_id=log_id, parsed_food_name="staged earlier",
                        calories=10))
        await b.flush()

        again = await commit_or_load_existing(b, operation=_Op("op_abort"),
                                              resolved_meal=MEAL, writer=writer)
        assert again.meal_totals == {"calories": 520}

        # The transaction is still USABLE — the savepoint contained the abort.
        await b.commit()

    async with maker() as s:
        names = (await s.execute(select(FoodEntry.parsed_food_name))
                 ).scalars().all()
    assert "staged earlier" in names, "the duplicate aborted the caller's turn"
    assert names.count("Chicken") == 1


@pytest.mark.asyncio
async def test_a_losing_writer_leaves_no_food_and_no_claim(pg):
    """A failure anywhere after the claim unwinds the claim with it, so a retry
    is not permanently locked out by a row that describes a write that never
    happened."""
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    _, log_id = await _seed(maker)

    async def _boom(db, *, operation, resolved_meal):
        db.add(FoodEntry(daily_log_id=log_id, parsed_food_name="Doomed",
                         calories=1))
        await db.flush()
        raise RuntimeError("the ledger failed after writing")

    async with maker() as a:
        with pytest.raises(RuntimeError):
            await commit_or_load_existing(a, operation=_Op("op_undo"),
                                          resolved_meal=MEAL, writer=_boom)
        await a.rollback()

    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(FoodEntry))
                ).scalar() == 0
        assert await meal_commit.existing_result(s, operation_id="op_undo") \
            is None

    # ...and the retry succeeds, rather than seeing a phantom claim.
    async with maker() as b:
        retry = await commit_or_load_existing(b, operation=_Op("op_undo"),
                                              resolved_meal=MEAL,
                                              writer=_writer_for(log_id))
        await b.commit()
    assert retry.meal_totals == {"calories": 520}


@pytest.mark.asyncio
async def test_an_unresolved_claim_blocks_rather_than_double_writing(pg):
    """The one path to `CommitInProgress`: a claim that is durable while no
    result is.

    A plain race cannot reach it — Postgres blocks the second insert until the
    first transaction resolves, so by the time a duplicate is detected the
    winner's result is already committed. Reaching it takes a claim committed on
    its own, which is what a crash between two separate transactions would
    leave. The correct answer is to refuse, not to write the meal again.
    """
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    _, log_id = await _seed(maker)

    async with maker() as a:
        assert (await claim_commit(a, operation_id="op_stuck", user_id=1)).won
        await a.commit()

    async with maker() as b:
        from core.commit_coordinator import CommitInProgress
        with pytest.raises(CommitInProgress):
            await commit_or_load_existing(b, operation=_Op("op_stuck"),
                                          resolved_meal=MEAL,
                                          writer=_writer_for(log_id))
        await b.rollback()

    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(FoodEntry))
                ).scalar() == 0, "an unresolved claim must not write the meal"
