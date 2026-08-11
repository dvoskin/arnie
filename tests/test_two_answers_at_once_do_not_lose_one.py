"""⛔ A B-1.5 LIVE CORRECTNESS DEFECT, found while building B-1.6.

`hold_answer` rewrote the whole `answered` map from an `OwnedOperation`
hydrated by an UNLOCKED read:

    held = dict(owned.answered or {})            # read, unlocked
    held[patch.field_id] = patch
    owned.row.canonical_payload = json.dumps(...)  # blind write

Two answers arriving together each read the map, each add their own patch,
each write everything. Last write wins, one answer is silently lost, and the
reply confirms it. Not B-1.6 debt — this is reachable on B-1.5 today with two
chips on screen and a fast pair of taps, or one tap plus a retried delivery.

`save_revision` is a genuine compare-and-swap and CANNOT fix this: holding an
answer deliberately does not move the revision, so both writers satisfy
`WHERE revision = N` and both succeed. The read-modify-write itself has to be
serialized.

THESE GATES RUN ON REAL POSTGRES AND SKIP WITHOUT ONE. `FOR UPDATE` is the
mechanism under test; SQLite is single-writer and would prove the lock is
unnecessary rather than that it works — a green run on the wrong engine is
exactly the "instrument that reports success without testing anything" this
codebase keeps paying for.
"""
from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import pending_repository as repo
from core.semantics import (CanonicalQuantity, ClarificationAttribute,
                            Dimension, SetAddedFatPresent, SetPreparation,
                            SetQuantity)

PG = os.getenv("TEST_POSTGRES_URL")
pg_only = pytest.mark.skipif(
    not PG, reason="the row lock is the thing under test; SQLite is "
                   "single-writer and would pass without it")

OPERATION = "concurrency_probe:26:ios:overlap"


def _quantity(field="op:food_item_1:quantity:0"):
    return SetQuantity(event_id="food_item_1", field_id=field,
                       quantity=CanonicalQuantity(amount=Decimal("120"),
                                                  unit_id="g",
                                                  dimension=Dimension.MASS))


def _preparation(field="op:food_item_1:preparation:0"):
    return SetPreparation(event_id="food_item_1", field_id=field,
                          preparation_id="grilled")


def _fat(present: bool):
    return SetAddedFatPresent(
        event_id="food_item_1",
        field_id=f"op:food_item_1:{ClarificationAttribute.ADDED_FAT_PRESENT.value}:0",
        present=present)


@pytest_asyncio.fixture
async def sessions():
    """TWO INDEPENDENT SESSIONS on real Postgres — one connection each, so the
    lock has something to serialize. A shared connection would make the test
    pass by construction and prove nothing."""
    from db.database import Base, make_engine
    from db import models  # noqa: F401

    # `make_engine`, never `create_async_engine` — the one-clock guard refuses
    # an unpinned Postgres engine, and it is right to: a hand-built one would
    # run on the server's timezone. See docs/ONE_CLOCK_MIGRATION.md.
    engine = make_engine(PG)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    yield maker
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _seed(maker, payload: dict):
    from db.models import PendingOperation

    async with maker() as db:
        await db.execute(
            __import__("sqlalchemy").delete(PendingOperation).where(
                PendingOperation.operation_id == OPERATION))
        db.add(PendingOperation(
            operation_id=OPERATION, user_id=26, domain="food",
            status="awaiting_answer", storage_status="active", revision=0,
            canonical_payload=json.dumps(payload)))
        await db.commit()


async def _hold_under_lock(maker, patch, *, hold_open: float = 0.0):
    """One writer's whole critical section: lock, re-read, merge, write."""
    async with maker() as db:
        async with db.begin():
            locked = await repo.locked_operation(db, OPERATION)
            held = dict((locked.payload.get("answered") or {}))
            if hold_open:
                await asyncio.sleep(hold_open)     # force the overlap
            held[str(patch.field_id)] = patch.to_payload()
            payload = dict(locked.payload)
            payload["answered"] = held
            locked.write(payload)
            db.add(locked.row)
        return locked.lock_wait_ms


async def _answered(maker) -> dict:
    async with maker() as db:
        row = await repo.load_operation(db, OPERATION)
        return json.loads(row.canonical_payload or "{}").get("answered") or {}


# ── GATE 1: two holds at the same revision, different fields ───────────────

@pg_only
@pytest.mark.asyncio
async def test_two_simultaneous_answers_both_survive(sessions):
    """THE LOST UPDATE, as a rule.

    Writer A holds the lock open long enough that B must genuinely wait. Both
    answered DIFFERENT fields, so the durable map must contain BOTH — the
    pre-fix code returned whichever flushed last.
    """
    await _seed(sessions, {"item": {"food": "Chicken"}, "answered": {}})

    waits = await asyncio.gather(
        _hold_under_lock(sessions, _quantity(), hold_open=0.4),
        _hold_under_lock(sessions, _preparation()))

    answered = await _answered(sessions)
    assert set(answered) == {_quantity().field_id, _preparation().field_id}, (
        f"one answer was lost: {sorted(answered)}. Both writers merged into "
        f"the map they read, and the second write erased the first")
    assert max(waits) > 0, (
        "neither writer waited, so the two critical sections never overlapped "
        "and this run proved nothing about the lock")


# ── GATE 2: a shape-changing answer against a concurrent one ───────────────

@pg_only
@pytest.mark.asyncio
async def test_a_shape_changing_answer_serializes_against_another(sessions):
    """One transition serializes first; the second re-reads UNDER THE LOCK.

    `added_fat_present=yes` activates the amount field — an active-set shape
    change — while another request answers a field from the old interaction.
    Neither may merge against its pre-lock snapshot, so both answers must be
    present afterwards and the payload must be internally coherent.
    """
    await _seed(sessions, {"item": {"food": "Chicken"}, "answered": {}})

    await asyncio.gather(
        _hold_under_lock(sessions, _fat(True), hold_open=0.4),
        _hold_under_lock(sessions, _quantity()))

    answered = await _answered(sessions)
    assert set(answered) == {_fat(True).field_id, _quantity().field_id}, (
        f"a shape-changing answer and a concurrent one did not both land: "
        f"{sorted(answered)}")

    # The reconciler, run over the DURABLE state, must now see the dependent
    # field active — proving the merge produced coherent state, not a torn one.
    from core import field_activation as fa
    from core.semantics import patch_from_payload

    state = fa.state_from({"food": "Chicken"},
                          {k: patch_from_payload(v)
                           for k, v in answered.items()})
    assert ClarificationAttribute.ADDED_FAT_AMOUNT.value in \
        fa.active_attributes(state)


# ── GATE 3: an aborted writer leaves nothing behind ────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_a_failed_writer_leaves_the_last_committed_payload(sessions):
    """Writer A locks, mutates in memory, then fails. B must see the last
    COMMITTED payload — not A's aborted state, and not an empty one."""
    await _seed(sessions, {"item": {"food": "Chicken"}, "answered": {}})
    await _hold_under_lock(sessions, _preparation())

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom):
        async with sessions() as db:
            async with db.begin():
                locked = await repo.locked_operation(db, OPERATION)
                payload = dict(locked.payload)
                payload["answered"] = {_quantity().field_id:
                                       _quantity().to_payload()}
                locked.write(payload)
                db.add(locked.row)
                await db.flush()
                raise _Boom("the writer dies after staging")

    answered = await _answered(sessions)
    assert set(answered) == {_preparation().field_id}, (
        f"an aborted writer's state survived or the committed one was lost: "
        f"{sorted(answered)}")


# ── the boundary is shared, not buried ─────────────────────────────────────

def test_the_lock_is_a_shared_primitive_not_one_functions_secret():
    """B-1.6 retraction and B-1.8 repair need the identical guarantee. A
    boundary only one caller uses is a boundary the second caller routes
    around — so `with_for_update` lives in the repository, and nowhere else."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = [p.name for p in list((root / "core").glob("*.py"))
                 if "with_for_update" in p.read_text(encoding="utf-8")
                 and p.name != "pending_repository.py"]
    assert not offenders, (
        f"{offenders} take the row lock directly instead of going through the "
        f"operation-state mutation boundary")


def test_nothing_expensive_runs_inside_the_critical_section():
    """The lock is held across reconciliation only, and reconciliation is pure
    by construction. A provider, model or pricing call under the lock would
    turn a microsecond critical section into a network round trip."""
    import ast
    import inspect
    import textwrap

    from core import b1_quantity_operation as ops

    source = textwrap.dedent(inspect.getsource(ops.hold_answer))
    tree = ast.parse(source)
    awaited = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
               for n in ast.walk(tree) if isinstance(n, ast.Await)
               for n in [n.value] if isinstance(n, ast.Call)}
    forbidden = {"resolve", "price", "search", "analyze", "_analyze_food",
                 "complete", "acreate", "qualify"}
    assert not (awaited & forbidden), (
        f"{sorted(awaited & forbidden)} is awaited while the operation row is "
        f"locked — the critical section must contain no provider, model or "
        f"pricing work")


def test_the_merge_reads_the_locked_row_not_the_pre_lock_snapshot():
    """⭐ THE SUBTLE WAY A CORRECT LOCK STILL PROTECTS A STALE READ.

    `SELECT ... FOR UPDATE` serializes the critical section. It does NOT make
    the object the request arrived with fresh. `OwnedOperation` is hydrated
    from an unlocked read long before this function runs, so:

        locked = await repo.locked_operation(db, ...)   # correct lock
        held = dict(owned.answered or {})               # STALE MERGE

    would acquire the lock, wait properly, and still lose the other writer's
    answer — because the map being merged into is the one read before waiting.
    Both overlap gates would pass under exactly this bug on a fast machine, so
    the claim is asserted structurally rather than left to timing.
    """
    import ast
    import inspect
    import textwrap

    from core import b1_quantity_operation as ops

    tree = ast.parse(textwrap.dedent(inspect.getsource(ops.hold_answer)))

    stale = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
             and n.attr == "answered"
             and getattr(n.value, "id", "") == "owned"]
    assert not stale, (
        "hold_answer still reads `owned.answered` — that map was decoded "
        "before the lock was taken, so merging into it discards whatever the "
        "other writer committed while we waited")

    locked_names = {
        t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
        if any(isinstance(c, ast.Call)
               and (getattr(c.func, "attr", "") or getattr(c.func, "id", ""))
               == "locked_operation"
               for c in ast.walk(n.value))}
    assert locked_names, "hold_answer never opens the mutation boundary"

    held = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "held" for t in n.targets)]
    assert held, "`held` is no longer assigned"
    from_locked = any(c.id in locked_names for a in held
                      for c in ast.walk(a.value) if isinstance(c, ast.Name))
    assert from_locked, (
        "`held` is not derived from the locked row — the lock is being held "
        "over a merge into state that predates it")


@pg_only
@pytest.mark.asyncio
async def test_an_uncontended_lock_is_cheap(sessions):
    """The critical section contains only pure reconciliation, so acquiring
    the row lock with nobody else on it must cost approximately nothing. This
    is the baseline `operation_lock_wait_ms` is compared against later — a
    number nobody measured before tuning is how contention gets argued about
    instead of observed."""
    await _seed(sessions, {"item": {"food": "Chicken"}, "answered": {}})
    waited = await _hold_under_lock(sessions, _quantity())
    assert waited < 250, (
        f"an uncontended acquire took {waited} ms — either something "
        f"expensive moved inside the critical section or the lock is "
        f"queueing behind work that should not be there")
