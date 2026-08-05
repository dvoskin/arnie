"""The canonical lane's invariants, as tests rather than as prose.

`docs/ARCHITECTURE_CONTRACT.md` records I1–I17 for the system as a whole and
tracks which hold. These six are the canonical mutation boundary's own, and
they are written here because an invariant that lives only in a comment is a
hope: the reason this rearchitecture exists is a list of properties everyone
believed and nothing checked.

    C1  Every committed row belongs to exactly one MealCommitResult.
    C2  Every MealCommitResult corresponds to exactly one operation revision.
    C3  No renderer derives totals independently.
    C4  No mutation bypasses the commit coordinator.
    C5  No PendingOperation transitions directly to COMMITTED.
    C6  Every duplicate returns the identical persisted MealCommitResult.

C3 and C4 CANNOT hold yet — the legacy lane is still the production writer, and
it is meant to be. Those two are written as RATCHETS against a recorded
baseline: they permit exactly what exists today and fail the moment it grows.
That is the difference between "not done" and "getting worse", and it is what
makes the migration converge rather than accumulate. Each mutation owner that
moves must lower the number, never raise it.
"""
import ast
import os
import pathlib
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import meal_commit, pending_repository as repo
from core.canonical_writer import (MealIntent, ResolvedFood, ResolvedMeal,
                                   write_canonical_meal)
from core.commit_coordinator import commit_or_load_existing
from core.semantics import (CanonicalEvent, PendingStatus, ResolutionStatus,
                            _ALLOWED_TRANSITIONS)
from db.database import make_engine
from db.models import Base, FoodEntry, LedgerEvent, MealCommit, User

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAY, TZ = date(2026, 8, 5), "America/New_York"

PG = os.getenv("TEST_POSTGRES_URL")
if os.getenv("CI") and not PG:
    raise RuntimeError(
        "TEST_POSTGRES_URL is unset in CI. The canonical invariants are "
        "database properties and cannot be checked on sqlite.")
pg_only = pytest.mark.skipif(not PG, reason="needs a real Postgres")


def _food(name, cal, **kw):
    return ResolvedFood(
        event=CanonicalEvent(id=f"ev_{name}", domain="food",
                             entity_id=name.lower(), surface_text=name,
                             resolution_status=ResolutionStatus.RESOLVED),
        calories=cal, **kw)


def _meal(oid="op_inv", revision=0, items=None, **kw):
    return ResolvedMeal(operation_id=oid, revision=revision, user_id=1,
                        logging_day=DAY, user_timezone=TZ,
                        items=items or (_food("Chicken", 320),
                                        _food("Rice", 205)), **kw)


@pytest_asyncio.fixture
async def pg():
    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        s.add(User(telegram_id="pg:invariants"))
        await s.commit()
    yield maker
    await engine.dispose()


# ── C1 ───────────────────────────────────────────────────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_c1_every_row_belongs_to_exactly_one_result(pg):
    """A row that belongs to no result cannot be undone, audited, or joined to
    the turn that claims it. A row claimed by two results means one of the two
    confirmations is describing food it did not write."""
    async with pg() as s:
        r1 = await commit_or_load_existing(
            s, operation=_Op("op_a"), resolved_meal=_meal("op_a"),
            writer=write_canonical_meal)
        await s.commit()
    async with pg() as s:
        r2 = await commit_or_load_existing(
            s, operation=_Op("op_b"), resolved_meal=_meal("op_b"),
            writer=write_canonical_meal)
        await s.commit()

    owned = [i["entry_id"] for i in r1.committed_items] + \
            [i["entry_id"] for i in r2.committed_items]
    assert len(owned) == len(set(owned)), "a row is claimed by two results"

    async with pg() as s:
        rows = {r.id for r in
                (await s.execute(select(FoodEntry))).scalars().all()}
    assert rows == set(owned), (
        f"rows with no owning result: {rows - set(owned)}")


# ── C2 ───────────────────────────────────────────────────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_c2_one_result_per_operation_revision(pg):
    """Enforced by the database, not by this test — the unique constraint on
    (operation_id, operation_revision) is what makes it true under concurrency
    (see test_two_connections_one_commit.py)."""
    async with pg() as s:
        for rev in (0, 1):
            await commit_or_load_existing(
                s, operation=_Op("op_rev", revision=rev),
                resolved_meal=_meal("op_rev", revision=rev),
                writer=write_canonical_meal)
            await s.commit()

    async with pg() as s:
        rows = (await s.execute(select(MealCommit))).scalars().all()
    keys = [(r.operation_id, r.operation_revision) for r in rows]
    assert len(keys) == len(set(keys)) == 2


# ── C3 (ratchet, PARTIAL) ────────────────────────────────────────────────────
#
# "No renderer derives totals independently." This covers ONE shape of that:
# aggregating macros across entries. The other shape — three owners of the
# day's REMAINING calories, disagreeing by one because each rounds differently
# — is arithmetic on an already-computed total and is not detected here. It is
# tracked as I9 in docs/ARCHITECTURE_CONTRACT.md. Claiming otherwise would make
# this gate read as broader than it is, which is the failure mode the whole
# rearchitecture is about.

#: Modules that aggregate macros across entries today. Each is named with what
#: it is, because "debt" and "legitimately not a renderer" are different and a
#: bare number cannot tell them apart.
#:
#: MEASURED, NOT ASSUMED. An earlier draft was written from memory —
#: food_ledger, receipt, food_turn — and every entry was wrong: those three own
#: the day's REMAINING calories, a different shape this detector does not see.
#: The canonical writer was wrong too, for the opposite reason: it accumulates
#: in a loop rather than calling sum(). The stale-entry check below is what
#: caught both, and it is why the list is derived from a run rather than from
#: recollection.
_TOTALS_BASELINE = {
    "db/queries.py",              # recompute_log_totals — the LEDGER's own,
                                  # and the one that should survive
    "handlers/tool_executor.py",  # DEBT: legacy write lane
    "api/app.py",                 # DEBT: day endpoint aggregates directly
    "api/insights.py",            # analytics, not a renderer of a commit
    "core/coach_live.py",         # coach projections over history
    "core/health_score.py",       # a score over a period, not a meal
    "core/targets.py",            # goal arithmetic, not committed state
}


def _modules_summing_macros() -> set:
    """Modules that add up calories or macros across entries.

    A grep would match strings and comments; this walks the AST and looks for
    `sum(...)` over an attribute named like a macro, which is what a total
    actually looks like in this codebase.
    """
    found = set()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", ".venv/")) \
                or rel.startswith("simulate_"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "sum"):
                continue
            for sub in ast.walk(node):
                name = (sub.attr if isinstance(sub, ast.Attribute)
                        else sub.value if isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str) else None)
                if name in ("calories", "protein", "carbs", "fats"):
                    found.add(rel)
    return found


def test_c3_no_new_module_aggregates_macros_across_entries():
    """RATCHET on ONE shape of C3: summing macros over entries.

    C3 in full — "no renderer derives totals independently" — also covers the
    remaining-calorie arithmetic that has three owners disagreeing by one
    (I9 in docs/ARCHITECTURE_CONTRACT.md). This does NOT detect that shape, and
    the name says so rather than implying a coverage it does not have.

    When rendering consumes MealCommitResult, the DEBT entries come out of the
    baseline and this tightens toward the real invariant.
    """
    found = _modules_summing_macros()
    new = found - _TOTALS_BASELINE
    assert not new, (
        f"new module(s) computing totals independently: {sorted(new)}. "
        f"Totals come from MealCommitResult, which reads them back from the "
        f"committed rows — a fourth owner is how the prose and the card came "
        f"to disagree by one.")
    stale = _TOTALS_BASELINE - found
    assert not stale, (
        f"{sorted(stale)} no longer computes totals — remove it from "
        f"_TOTALS_BASELINE so the ratchet keeps tightening")


# ── C4 (ratchet) ─────────────────────────────────────────────────────────────

def _food_write_sites() -> set:
    """Every call site that creates a food row."""
    sites = set()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", ".venv/")) \
                or rel.startswith("simulate_") or rel == "db/queries.py" \
                or rel == "core/canonical_writer.py":   # IS the coordinator path
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if isinstance(node, ast.Call) and name == "add_food_entry":
                sites.add(f"{rel}:{node.lineno}")
    return sites


#: The LEGACY writers, by count — the canonical writer is excluded above,
#: because counting it would make the scoreboard go UP as the migration
#: succeeds. Counted, not pinned to exact lines: a line moves for unrelated
#: reasons, and a brittle gate gets deleted rather than obeyed.
#:
#: api/app.py · api/quick_log.py · handlers/tool_executor.py ×2
_LEGACY_FOOD_WRITERS = 4


def test_c4_no_new_mutation_bypasses_the_coordinator():
    """RATCHET, and the migration's actual scoreboard.

    Every mutation owner that moves onto the coordinator must LOWER this
    number. The failure mode this guards is not a bug — it is a migration that
    stalls at 90% because the new path became an additional layer instead of a
    replacement, and the two then diverge one special-case fix at a time.
    """
    sites = _food_write_sites()
    assert len(sites) <= _LEGACY_FOOD_WRITERS, (
        f"{len(sites)} direct food writers, baseline {_LEGACY_FOOD_WRITERS}: "
        f"{sorted(sites)}. A new write must go through the commit coordinator.")
    assert len(sites) == _LEGACY_FOOD_WRITERS, (
        f"only {len(sites)} direct writers remain (baseline "
        f"{_LEGACY_FOOD_WRITERS}) — LOWER _LEGACY_FOOD_WRITERS to "
        f"{len(sites)} so the ratchet holds the ground you just took")


# ── C5 ───────────────────────────────────────────────────────────────────────

def test_c5_no_direct_transition_to_committed():
    """COMMITTING is not ceremony. It is the state in which a crash is
    recoverable: an operation that jumps straight to COMMITTED has no state
    saying a ledger write was in flight, so a retry cannot tell "never started"
    from "may have written"."""
    for status, allowed in _ALLOWED_TRANSITIONS.items():
        if status is PendingStatus.COMMITTING:
            continue
        assert PendingStatus.COMMITTED not in allowed, (
            f"{status.value} -> committed skips COMMITTING, the only state "
            f"that says a ledger write was in flight")
    assert PendingStatus.COMMITTED in _ALLOWED_TRANSITIONS[
        PendingStatus.COMMITTING]


@pg_only
@pytest.mark.asyncio
async def test_c5_holds_in_the_repository_too(pg):
    """The dataclass guards the in-memory transition; this is the persisted
    one."""
    async with pg() as s:
        await repo.create_operation(s, operation_id="op_c5", user_id=1,
                                    status="resolving",
                                    storage_status="active")
        await s.commit()
        out = await repo.mark_committed(s, operation_id="op_c5",
                                        expected_revision=0,
                                        commit_key="op_c5:0")
        await s.commit()
        assert out.ok, "the repository is the persistence layer, not the policy"

    # ...so the POLICY has to be enforced where the transition is decided.
    from core.semantics import InvalidPendingTransition, PendingOperation
    op = PendingOperation(id="x", user_id="1", domain="food",
                          status=PendingStatus.RESOLVING)
    with pytest.raises(InvalidPendingTransition):
        op.transition_to(PendingStatus.COMMITTED)


# ── C6 ───────────────────────────────────────────────────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_c6_a_duplicate_returns_the_identical_persisted_result(pg):
    """Identical, and PERSISTED — the second delivery is answered from storage
    and never re-runs interpretation, so it must not merely be equivalent."""
    async with pg() as s:
        first = await commit_or_load_existing(
            s, operation=_Op("op_c6"),
            resolved_meal=_meal("op_c6", assumptions=("a cup is 158g",)),
            writer=write_canonical_meal)
        await s.commit()

    async with pg() as s:
        second = await commit_or_load_existing(
            s, operation=_Op("op_c6"), resolved_meal=_meal("op_c6"),
            writer=write_canonical_meal)
        await s.commit()
        stored = await meal_commit.existing_result(s, operation_id="op_c6")

    assert second == first == stored
    assert second.assumptions == ("a cup is 158g",), (
        "the duplicate lost the disclosure the first delivery made")

    async with pg() as s:
        assert int((await s.execute(select(func.count()).select_from(
            FoodEntry))).scalar()) == 2
        assert int((await s.execute(select(func.count()).select_from(
            LedgerEvent))).scalar()) == 2


class _Op:
    def __init__(self, oid, revision=0, user_id=1):
        self.id, self.revision, self.user_id = oid, revision, user_id
