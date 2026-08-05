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


# ── the result is recorded exactly once, or the caller is told ───────────────

@pytest.mark.asyncio
async def test_recording_against_a_missing_claim_raises(sessions):
    """FOOD ROWS WITHOUT AN AUTHORITATIVE RESULT is the outcome this module
    exists to prevent, and it was reachable: the UPDATE matched zero rows,
    raised nothing, and the transaction committed. A wrong operation id or
    revision was enough."""
    a, _ = sessions
    with pytest.raises(meal_commit.MissingCommitClaim) as exc:
        await meal_commit.record_result(a, operation_id="never_claimed",
                                        result={"x": 1})
    assert "no claim exists" in exc.value.why


@pytest.mark.asyncio
async def test_recording_against_the_wrong_revision_raises(sessions):
    a, _ = sessions
    assert (await meal_commit.claim_commit(
        a, operation_id="op_rev", revision=0, user_id=26)).won
    with pytest.raises(meal_commit.MissingCommitClaim):
        await meal_commit.record_result(a, operation_id="op_rev", revision=1,
                                        result={"x": 1})


@pytest.mark.asyncio
async def test_the_original_result_cannot_be_overwritten(sessions):
    """A second write would redefine "the original result" as "the most recent
    one", which breaks the duplicate contract from the inside."""
    a, b = sessions
    assert (await meal_commit.claim_commit(
        a, operation_id="op_imm", user_id=26)).won
    await meal_commit.record_result(a, operation_id="op_imm",
                                    result={"calories": 520})
    await a.commit()

    with pytest.raises(meal_commit.MissingCommitClaim) as exc:
        await meal_commit.record_result(a, operation_id="op_imm",
                                        result={"calories": 999})
    assert "already has a result" in exc.value.why

    dup = await meal_commit.claim_commit(b, operation_id="op_imm", user_id=26)
    assert dup.result == {"calories": 520}, "the FIRST result must survive"


@pytest.mark.asyncio
async def test_a_duplicate_claim_does_not_discard_the_callers_work(sessions):
    """A duplicate is a NORMAL outcome. `db.rollback()` on it would throw away
    everything the caller had already staged in the same transaction — a defect
    waiting for the first composite caller."""
    from db.models import PendingOperation

    a, b = sessions
    assert (await meal_commit.claim_commit(
        a, operation_id="op_sp", user_id=26)).won
    await a.commit()

    # Stage unrelated work, then hit a duplicate claim.
    b.add(PendingOperation(operation_id="staged_before_the_claim", user_id=26,
                           domain="food", status="resolving",
                           storage_status="active", revision=0))
    await b.flush()
    dup = await meal_commit.claim_commit(b, operation_id="op_sp", user_id=26)
    assert dup.is_duplicate
    await b.commit()

    from core import pending_repository as repo
    assert await repo.load_operation(a, "staged_before_the_claim") is not None


# ── the stored result is lossless or refused ─────────────────────────────────

def test_a_lossy_value_is_refused_rather_than_stringified():
    """`default=str` turned any unsupported object into a string, so a
    duplicate received something structurally different from what the original
    caller got — and nothing failed when it happened."""
    class Domain:
        pass

    with pytest.raises(meal_commit.UnserializableResult) as exc:
        meal_commit.encode_result({"items": [{"entry": Domain()}]})
    assert "items[0].entry" in str(exc.value), "the path must name the value"


def test_decimals_and_datetimes_round_trip_losslessly():
    """Both appear in real totals and both have an exact text form."""
    from datetime import datetime as dt
    from decimal import Decimal

    raw = meal_commit.encode_result(
        {"calories": Decimal("520.5"), "at": dt(2026, 8, 4, 12, 30)})
    out = meal_commit.decode_result(raw)
    assert out["calories"] == "520.5"        # exact, not 520.50000000000001
    assert out["at"] == "2026-08-04T12:30:00"


def test_the_stored_result_is_versioned():
    import json as _json

    data = _json.loads(meal_commit.encode_result({"a": 1}))
    assert data["schema_version"] == meal_commit.RESULT_SCHEMA_VERSION
    assert data["result"] == {"a": 1}


@pytest.mark.parametrize("raw", [
    "{not json", "[]", '{"result": {}}',
    '{"schema_version": 999, "result": {}}',
])
def test_an_uninterpretable_result_reads_as_none(raw):
    """Answering a duplicate with a partially-understood payload would hand it
    something the original caller never saw."""
    assert meal_commit.decode_result(raw) is None
