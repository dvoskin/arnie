"""claim -> write -> record -> finalise, in the CALLER's transaction.

The coordinator owns the PROTOCOL, not the session. Giving it its own session
would split atomicity the wrong way — food rows committing while the rest of
the turn fails, or the reverse — so everything rides the caller's outer
transaction and nothing here calls `commit()` or `rollback()`.

Real `FoodEntry` rows are written, because "the food rows roll back with the
result" is not a claim a mock can support.
"""
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from core import meal_commit, pending_repository as repo
from core.commit_coordinator import CommitInProgress, commit_or_load_existing
from core.meal_commit import MealCommitResult
from db.models import Base, DailyLog, FoodEntry


class _Op:
    def __init__(self, oid="op_1", revision=0, user_id=26):
        self.id, self.revision, self.user_id = oid, revision, user_id


LOG_ID = 1


@pytest_asyncio.fixture
async def sessions(tmp_path):
    """TWO SESSIONS ON TWO CONNECTIONS.

    Deliberately a file database in WAL mode, not `:memory:` with a
    `StaticPool`. That pool hands every session the SAME connection, so an
    uncommitted write is instantly visible to the "other" session and
    "the caller still owns the commit" passes whether or not it is true.
    A test that cannot fail proves nothing.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    async with engine.connect() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    setup = maker()
    setup.add(DailyLog(id=LOG_ID, user_id=26, date=date(2026, 8, 4)))
    await setup.commit()
    await setup.close()

    a, b = maker(), maker()
    try:
        yield a, b
    finally:
        await a.close(); await b.close(); await engine.dispose()


async def _food_rows(db) -> int:
    res = await db.execute(select(func.count()).select_from(FoodEntry))
    return int(res.scalar() or 0)


async def _writer(db, *, operation, resolved_meal):
    """A REAL ledger write, on the real `food_entries` shape: rows that must
    vanish if anything after them fails."""
    ids = []
    for item in resolved_meal:
        row = FoodEntry(daily_log_id=LOG_ID,
                        parsed_food_name=item["name"],
                        calories=item["calories"])
        db.add(row)
        await db.flush()
        ids.append(row.id)
    return MealCommitResult(
        committed_items=[{"entry_id": i} for i in ids],
        meal_totals={"calories": sum(i["calories"] for i in resolved_meal)})


MEAL = [{"name": "Chicken", "calories": 320},
        {"name": "Rice", "calories": 200}]


# ── the happy path, and who commits ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_caller_still_owns_the_commit(sessions):
    """The coordinator flushes; it does not commit. Until the caller commits,
    another session sees nothing."""
    a, b = sessions
    result = await commit_or_load_existing(a, operation=_Op(),
                                           resolved_meal=MEAL, writer=_writer)
    assert len(result.committed_items) == 2
    assert await _food_rows(b) == 0, "an uncommitted turn must not be visible"

    await a.commit()
    assert await _food_rows(b) == 2


@pytest.mark.asyncio
async def test_pre_staged_turn_work_survives_a_duplicate(sessions):
    """A duplicate is routine, and must not discard what the turn already
    staged — the savepoint is what makes that true."""
    a, b = sessions
    await commit_or_load_existing(a, operation=_Op("op_dup"),
                                  resolved_meal=MEAL, writer=_writer)
    await a.commit()

    b.add(FoodEntry(daily_log_id=LOG_ID,
                    parsed_food_name="staged earlier", calories=10))
    await b.flush()
    again = await commit_or_load_existing(b, operation=_Op("op_dup"),
                                          resolved_meal=MEAL, writer=_writer)
    await b.commit()

    assert again.meal_totals == {"calories": 520}
    names = (await b.execute(
        select(FoodEntry.parsed_food_name))).scalars().all()
    assert "staged earlier" in names
    assert names.count("Chicken") == 1, "the duplicate must not write again"


@pytest.mark.asyncio
async def test_a_duplicate_returns_an_identical_result(sessions):
    a, b = sessions
    first = await commit_or_load_existing(a, operation=_Op("op_same"),
                                          resolved_meal=MEAL, writer=_writer)
    await a.commit()
    second = await commit_or_load_existing(b, operation=_Op("op_same"),
                                           resolved_meal=MEAL, writer=_writer)
    assert second == first
    assert isinstance(second, MealCommitResult)


# ── every failure unwinds the ledger write with it ───────────────────────────

@pytest.mark.asyncio
async def test_a_failing_result_record_rolls_back_the_food(sessions, monkeypatch):
    """FOOD WITHOUT AN AUTHORITATIVE RESULT is the invariant. The rows are
    written before the result is recorded, so the recording failing has to take
    them with it — which it does only because they share one transaction."""
    a, b = sessions

    async def _boom(*args, **kw):
        raise meal_commit.MissingCommitClaim("op_r", 0, "forced")

    monkeypatch.setattr("core.commit_coordinator.record_result", _boom)
    with pytest.raises(meal_commit.MissingCommitClaim):
        await commit_or_load_existing(a, operation=_Op("op_r"),
                                      resolved_meal=MEAL, writer=_writer)
    await a.rollback()          # the CALLER decides, as it would in run_turn
    assert await _food_rows(b) == 0


@pytest.mark.asyncio
async def test_a_failing_finalisation_rolls_back_food_and_result(sessions):
    """The last step failing must not leave rows and a result behind."""
    a, b = sessions

    async def _boom(db, **kw):
        raise RuntimeError("finalisation failed")

    with pytest.raises(RuntimeError):
        await commit_or_load_existing(a, operation=_Op("op_f"),
                                      resolved_meal=MEAL, writer=_writer,
                                      finaliser=_boom)
    await a.rollback()
    assert await _food_rows(b) == 0
    assert await meal_commit.existing_result(b, operation_id="op_f") is None


@pytest.mark.asyncio
async def test_a_failing_writer_leaves_no_claim(sessions):
    a, b = sessions

    async def _boom(db, **kw):
        raise RuntimeError("ledger unavailable")

    with pytest.raises(RuntimeError):
        await commit_or_load_existing(a, operation=_Op("op_w"),
                                      resolved_meal=MEAL, writer=_boom)
    await a.rollback()
    assert await meal_commit.existing_result(b, operation_id="op_w") is None


# ── the abnormal duplicate ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_claim_without_a_result_is_not_a_success(sessions):
    """NOT ROUTINE. If claim, write and result share one transaction, a crash
    before commit unwinds all three — so a DURABLE claim with no result means
    another writer is in flight or something left a partial state. Returning
    success there would report a commit that may never have written a row."""
    a, b = sessions
    assert (await meal_commit.claim_commit(
        a, operation_id="op_p", user_id=26)).won
    await a.commit()            # a claim, deliberately with no result

    with pytest.raises(CommitInProgress):
        await commit_or_load_existing(b, operation=_Op("op_p"),
                                      resolved_meal=MEAL, writer=_writer)


@pytest.mark.asyncio
async def test_it_never_returns_none(sessions):
    """Every path returns a result or raises. A caller receiving None cannot
    tell "already done" from "nothing happened"."""
    a, _ = sessions
    out = await commit_or_load_existing(a, operation=_Op("op_n"),
                                        resolved_meal=MEAL, writer=_writer)
    assert out is not None and isinstance(out, MealCommitResult)


@pytest.mark.asyncio
async def test_the_writer_must_return_the_canonical_type(sessions):
    """Otherwise the winner and a later duplicate answer with different
    types — the asymmetry the result type exists to remove."""
    a, _ = sessions

    async def _wrong(db, **kw):
        return {"entry_ids": [1]}

    with pytest.raises(TypeError, match="MealCommitResult"):
        await commit_or_load_existing(a, operation=_Op("op_t"),
                                      resolved_meal=MEAL, writer=_wrong)


# ── revision ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_new_revision_writes_again(sessions):
    """A corrected meal is a NEW mutation of the same operation."""
    a, b = sessions
    await commit_or_load_existing(a, operation=_Op("op_rev", revision=0),
                                  resolved_meal=MEAL, writer=_writer)
    await a.commit()
    await commit_or_load_existing(a, operation=_Op("op_rev", revision=1),
                                  resolved_meal=MEAL, writer=_writer)
    await a.commit()
    assert await _food_rows(b) == 4

    # ...and each revision remains committable only once.
    dup = await commit_or_load_existing(b, operation=_Op("op_rev", revision=1),
                                        resolved_meal=MEAL, writer=_writer)
    assert dup.meal_totals == {"calories": 520}
    assert await _food_rows(b) == 4


@pytest.mark.asyncio
async def test_the_operation_is_marked_committed(sessions):
    """The finaliser runs inside the same transaction, so the operation's
    transition cannot outlive a failed write."""
    a, b = sessions
    await repo.create_operation(a, operation_id="op_m", user_id=26,
                                status="ready_to_commit",
                                storage_status="active")
    await a.commit()

    await commit_or_load_existing(a, operation=_Op("op_m"),
                                  resolved_meal=MEAL, writer=_writer,
                                  finaliser=repo.mark_committed)
    await a.commit()

    row = await repo.load_operation(b, "op_m")
    assert row.status == "committed" and row.storage_status == "consumed"
    assert row.commit_key == "op_m:0"
