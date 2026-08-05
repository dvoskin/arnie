"""One ledger mutation per (operation, revision), proven against a database.

`pending_store.claim()` proves one consumer of the clarification ANSWER. This
proves one WRITE of the meal that follows — a different promise, and the gap
between them is a real sequence: claim, commit food, crash before marking
consumed, retry, commit again.

The uniqueness is a CONSTRAINT rather than a check because an application-level
`if not already_committed(key)` cannot arbitrate concurrent workers: both read
"not committed", both proceed, both write. These tests use TWO SESSIONS to
exercise that, since a single session cannot demonstrate what a constraint is
for.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.pool import StaticPool

from core import meal_commit
from db.models import Base


@pytest_asyncio.fixture
async def sessions():
    """Two sessions on one in-memory database — two workers, one row store."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    a, b = maker(), maker()
    try:
        yield a, b
    finally:
        await a.close()
        await b.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_constraint_exists_in_the_schema():
    """If the table ships without it, every test below passes for the wrong
    reason — the writes simply never collide."""
    from db.models import MealCommit

    names = {c.name for c in MealCommit.__table__.constraints if c.name}
    assert "uq_meal_commits_operation_revision" in names


@pytest.mark.asyncio
async def test_exactly_one_caller_wins(sessions):
    a, b = sessions
    first = await meal_commit.claim_commit(a, operation_id="op_1", user_id=26)
    await a.commit()
    second = await meal_commit.claim_commit(b, operation_id="op_1", user_id=26)

    assert first.won is True
    assert second.won is False and second.is_duplicate


@pytest.mark.asyncio
async def test_the_loser_gets_the_winners_result(sessions):
    """A duplicate must return what the FIRST attempt produced. Returning
    nothing leaves the caller unable to tell "already done" from "nothing
    happened" — and it will either re-report the meal or report a commit that
    did not occur on this turn."""
    a, b = sessions
    claim = await meal_commit.claim_commit(a, operation_id="op_2", user_id=26)
    assert claim.won
    await meal_commit.record_result(
        a, operation_id="op_2",
        result={"entry_ids": [11, 12], "calories": 520})
    await a.commit()

    dup = await meal_commit.claim_commit(b, operation_id="op_2", user_id=26)
    assert dup.is_duplicate
    assert dup.result == {"entry_ids": [11, 12], "calories": 520}


@pytest.mark.asyncio
async def test_a_new_revision_is_a_new_mutation(sessions):
    """A corrected meal is a NEW write of the SAME operation. Revision is what
    lets that through while still refusing a duplicate of either."""
    a, b = sessions
    assert (await meal_commit.claim_commit(
        a, operation_id="op_3", revision=0, user_id=26)).won
    await a.commit()
    assert (await meal_commit.claim_commit(
        a, operation_id="op_3", revision=1, user_id=26)).won
    await a.commit()
    # ...and each revision is still claimable only once.
    assert (await meal_commit.claim_commit(
        b, operation_id="op_3", revision=1, user_id=26)).is_duplicate


@pytest.mark.asyncio
async def test_different_operations_do_not_collide(sessions):
    a, _ = sessions
    for op in ("op_a", "op_b", "op_c"):
        assert (await meal_commit.claim_commit(
            a, operation_id=op, user_id=26)).won
        await a.commit()


@pytest.mark.asyncio
async def test_the_crash_window_is_visible_not_silent(sessions):
    """A claim with no result is the crash sequence: the winner inserted, then
    died before recording. The retry must be able to SEE that, rather than
    receiving an empty result it cannot distinguish from a successful
    no-op."""
    a, b = sessions
    assert (await meal_commit.claim_commit(
        a, operation_id="op_4", user_id=26)).won
    await a.commit()          # claimed, but record_result never ran

    dup = await meal_commit.claim_commit(b, operation_id="op_4", user_id=26)
    assert dup.is_duplicate
    assert dup.result is None, (
        "a claim with no recorded result must report None, so the caller "
        "knows the first attempt did not finish")


@pytest.mark.asyncio
async def test_a_missing_operation_id_is_refused(sessions):
    a, _ = sessions
    with pytest.raises(ValueError):
        await meal_commit.claim_commit(a, operation_id="", user_id=26)


@pytest.mark.asyncio
async def test_an_unreadable_result_does_not_raise(sessions):
    """Corrupt JSON in one row may not break the turn reading it."""
    from sqlalchemy import update

    from db.models import MealCommit

    a, b = sessions
    await meal_commit.claim_commit(a, operation_id="op_5", user_id=26)
    await a.execute(update(MealCommit)
                    .where(MealCommit.operation_id == "op_5")
                    .values(result_payload="{not json"))
    await a.commit()
    dup = await meal_commit.claim_commit(b, operation_id="op_5", user_id=26)
    assert dup.is_duplicate and dup.result is None


@pytest.mark.asyncio
async def test_it_is_not_wired_into_the_food_path_yet():
    """Deliberate ordering. Routing the mutation sites through this before the
    constraint is proven would relocate the double-commit rather than close it,
    so this asserts the sequencing is still what the plan says."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    callers = []
    for name in ("core/conversation.py", "handlers/tool_executor.py",
                 "core/food_turn.py"):
        if "meal_commit" in (root / name).read_text():
            callers.append(name)
    assert not callers, (
        f"meal_commit is now wired into {callers} — if that is intentional, "
        "this test should be deleted along with the claim that it is not")


@pytest.mark.asyncio
async def test_the_migration_matches_the_model():
    """DRIFT BETWEEN THEM IS THE REAL RISK, and this test caught it: the model
    was renamed to the directive's column names and the migration briefly was
    not, which SQLite reported as "no column named revision". The tests above build the table
    from `Base.metadata`, so they would all pass against a migration that ships
    a different shape — or none at all.

    The full chain cannot be exercised here: an OLDER migration
    (`c1d2e3f4a5b6`) ALTERs a constraint, which SQLite does not support.
    Production is Postgres, so that is not a defect, but it does mean this
    migration is verified in ISOLATION and the chain is verified only on
    deploy.
    """
    import importlib.util
    import os
    import sqlite3
    import tempfile

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    from db.models import MealCommit

    path = os.path.join(tempfile.mkdtemp(), "m.db")
    engine = create_engine(f"sqlite:///{path}")
    spec = importlib.util.spec_from_file_location(
        "mc_mig", "alembic/versions/mealcommit001_add_meal_commits.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()

    con = sqlite3.connect(path)
    try:
        migrated = {r[1] for r in con.execute(
            "PRAGMA table_info(meal_commits)")}
        assert migrated == {c.name for c in MealCommit.__table__.columns}, (
            "the migration and the model disagree about the table")

        # And the constraint is enforced by the DATABASE, not by the ORM.
        con.execute("INSERT INTO meal_commits "
                    "(operation_id,operation_revision,user_id) "
                    "VALUES ('op',0,1)")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO meal_commits "
                        "(operation_id,operation_revision,user_id) "
                        "VALUES ('op',0,1)")
    finally:
        con.close()

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
    engine.dispose()
