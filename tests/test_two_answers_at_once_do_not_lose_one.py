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

    # ⛔ PROVENANCE IS FOLLOWED TRANSITIVELY, not one hop. `held` is decoded
    # from `_locked_data`, which is decoded from `locked.row` — a one-hop
    # check would call that stale and force the merge back onto a direct
    # `locked.…` call, which is the opposite of what this gate wants.
    derived = set(locked_names)
    for _ in range(8):                      # to a fixpoint; the chain is short
        grew = False
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign):
                continue
            if {c.id for c in ast.walk(n.value)
                    if isinstance(c, ast.Name)} & derived:
                for t in n.targets:
                    for sub in ast.walk(t):
                        if isinstance(sub, ast.Name) and sub.id not in derived:
                            derived.add(sub.id)
                            grew = True
        if not grew:
            break

    held = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "held" for t in n.targets)]
    assert held, "`held` is no longer assigned"
    from_locked = any(c.id in derived for a in held
                      for c in ast.walk(a.value) if isinstance(c, ast.Name))
    assert from_locked, (
        "`held` is not derived from the locked row — the lock is being held "
        "over a merge into state that predates it")


@pg_only
@pytest.mark.asyncio
async def test_two_real_owning_then_hold_answer_writers_do_not_lose_a_shape_change(
        sessions):
    """⛔ P17 PHASE 2, THIRD ROUND. The other races in this file drive
    `LockedOperation` directly, so they cannot see the defect that lived
    between `owning()` and the lock: BOTH writers hydrate the operation
    BEFORE either takes the lock, and the loser then reconciled from ITS
    pre-lock interaction and re-signed the result — overwriting the winner's
    transition with a valid-looking fingerprint.

    AND ONE WRITER GENUINELY CHANGES THE SHAPE. The first version of this
    proof had both writers answer the same quantity field, which does not
    activate anything — so nothing was reconciled, nothing was rebuilt, and
    the test's own name over-claimed what its body exercised. Here writer A
    answers "yes, fat was added", which turns two conditional fields on and
    re-issues the surface at a new revision, while writer B holds a chip for
    the ORIGINAL revision.

    Whatever order they serialise in: no writer that committed may have its
    answer missing from the row, a writer whose field the rebuild retired
    must be REFUSED as stale rather than applied to a question that no
    longer asks it, and the surviving digest must describe the surviving
    material."""
    import asyncio

    from core import b1_quantity_operation as b1
    from core.semantics import (ClarificationGroup, ClarificationInteraction,
                                Provenance, ResponseType, UnresolvedField)
    from db.models import PendingOperation, User, UserPreferences
    from sqlalchemy import select

    # a real user, so `owning()` can find the row
    async with sessions() as s:
        u = (await s.execute(select(User).where(User.id == 26))).scalar_one_or_none()
        if u is None:
            u = User(id=26, telegram_id="race-26", onboarding_completed=True)
            s.add(u)
            await s.flush()
            s.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
        await s.commit()

    op_id = "chat_quantity:26:race-real"
    async with sessions() as s:
        await s.execute(__import__("sqlalchemy").delete(PendingOperation).where(
            PendingOperation.user_id == 26))
        await s.commit()
    async with sessions() as s:
        user = (await s.execute(select(User).where(User.id == 26))).scalar_one()
        items, _g = __import__("core.food_pipeline", fromlist=["stage_items"]).stage_items(
            {"items": [{"food": "Oatmeal", "amount": 1, "unit": "bowl",
                        "calories": 150}]},
            turn_id="race-real", message="x", mode="strict")
        from skills.nutrition import quantity_clarification as qc
        field = qc.quantity_field(operation_id=op_id, revision=0, item=items[0])
        base = qc.build_interaction(operation_id=op_id, revision=0,
                                    item=items[0], options=field.options,
                                    introduction="How much oatmeal?",
                                    ask_preparation=False)
        # ONE ask, TWO questions: the quantity chip B will tap, and the
        # yes/no whose answer A gives, which activates two more fields.
        group = base.groups[0]
        fat = UnresolvedField(
            operation_id=op_id, revision=0, event_id=group.event_id,
            attribute=ClarificationAttribute.ADDED_FAT_PRESENT,
            response_type=ResponseType.FREE_TEXT)
        inter = ClarificationInteraction(
            interaction_id=base.interaction_id, operation_id=op_id,
            revision=0, introduction=base.introduction,
            groups=(ClarificationGroup(event_id=group.event_id,
                                       label=group.label,
                                       fields=group.fields + (fat,)),))
        await b1.open_operation(s, user=user,
                                interpreter_item={"food": "Oatmeal", "amount": 1},
                                interaction=inter, turn_id="race-real",
                                locale="en", cohort="allowlist",
                                capability=b1.ID_ADDRESSED)
        await s.commit()

    _f = inter.groups[0].fields[0]
    chip = (_f.options[0].patch if getattr(_f, "options", None)
            else SetQuantity(
                event_id=inter.groups[0].event_id, field_id=_f.field_id,
                quantity=CanonicalQuantity(amount=Decimal("120"), unit_id="g",
                                           dimension=Dimension.MASS)))
    shape_changer = SetAddedFatPresent(
        event_id=inter.groups[0].event_id, field_id=fat.field_id,
        present=True, provenance=Provenance.USER_SELECTED)

    # ⛔ THE INTERLEAVING IS PINNED, NOT RACED. The first version left the
    # order to a 0.25s sleep, and every assertion that mattered sat behind
    # `if outcome == "stale"` — so when a mutation let the stale chip through,
    # the branch simply never ran and the proof passed. Two real sessions,
    # one deterministic order: B hydrates at revision 0, THEN A changes the
    # shape and commits, THEN B tries to answer.
    hydrated, reshaped = asyncio.Event(), asyncio.Event()

    async def shape_writer():
        async with sessions() as s:
            user = (await s.execute(select(User).where(User.id == 26))).scalar_one()
            owned = await b1.owning(s, user)
            assert owned is not None and owned.interaction is not None
            await hydrated.wait()           # B is holding revision 0
            result = await b1.hold_answer(s, owned=owned, patch=shape_changer)
            await s.commit()
            reshaped.set()
            return ("shape", "held", sorted(result.held),
                    result.interaction.revision)

    async def chip_writer():
        async with sessions() as s:
            user = (await s.execute(select(User).where(User.id == 26))).scalar_one()
            owned = await b1.owning(s, user)      # hydrates BEFORE the change
            assert owned is not None and owned.interaction is not None
            hydrated.set()
            await reshaped.wait()                 # A's rebuild has committed
            try:
                result = await b1.hold_answer(s, owned=owned, patch=chip)
                await s.commit()
                return ("chip", "held", sorted(result.held),
                        result.interaction.revision)
            except b1.StaleAnswerField:
                await s.rollback()
                return ("chip", "stale", [], None)

    a, b = await asyncio.gather(shape_writer(), chip_writer())

    async with sessions() as s:
        row = (await s.execute(select(PendingOperation).where(
            PendingOperation.operation_id == op_id))).scalars().one()
        payload = json.loads(row.canonical_payload)

    # the digest describes the material that actually landed
    assert payload["fingerprint"] == b1.fingerprint_of_payload(payload)
    landed = set(payload.get("answered") or {})

    # A really did change the shape — without this the rest is hollow
    assert a == ("shape", "held", [str(fat.field_id)], 1), a
    assert payload["interaction"]["revision"] == 1
    assert str(fat.field_id) in landed, (
        "the shape writer committed and its answer is gone — the chip writer "
        "reconciled from its pre-lock snapshot and overwrote the transition")

    # B hydrated before the rebuild; its chip addresses the retired revision
    assert b[1] == "stale", (
        f"the chip aimed at revision 0 was accepted after the surface moved "
        f"to revision 1: {b}")
    assert str(chip.field_id) not in landed, (
        "a chip answering the retired question was applied to the re-issued "
        "one")

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
