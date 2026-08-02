"""The ten properties every Class A update/delete route must hold.

Class A routes mutate the user's canonical logged history, so the failures
that matter are the ones a happy-path test never reaches: a process that dies
between two commits, two deliveries interleaving, a retry arriving after the
original already succeeded. Each property below is one of those.

    1.  a repeated identical request applies once
    2.  the same key with a different payload is refused
    3.  a crash BEFORE commit leaves nothing behind and stays retryable
    4.  a crash AFTER commit is not re-executed
    5.  two workers editing concurrently produce one effect
    6.  deleting something already deleted reports the original success
    7.  a retry reconstructs its answer from durable history
    8.  exactly one ledger effect per logical request
    9.  undo reaches the right row
    10. the write carries a canonical turn id and a build attribution

Properties 3, 4 and 7 are about the window between the row committing and the
claim completing. The contract closes it by putting BOTH in one transaction
(`claim_id=` on the domain write), so the states these tests construct should
be unreachable going forward — they are pinned because the previous design
DID reach them, and because a future refactor that splits the commits again
would pass every other test in this file.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.exercise_edit import ExerciseUpdateBody, delete_exercise, update_exercise
from api.food_edit import FoodUpdateBody, delete_food, update_food
from api.quick_log import ExerciseLogBody, FoodLogBody, log_exercise_entry, log_food_entry
from api.water import WaterLogBody, WaterUpdateBody, delete_water, log_water, update_water
from db.models import FoodEntry, LedgerEvent, WaterEntry


@pytest_asyncio.fixture
async def patched(monkeypatch, engine):
    from api import exercise_edit, food_edit, quick_log, water
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    for mod in (quick_log, water, food_edit, exercise_edit):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    return factory


async def _events(db, user_id, domain, event_type=None):
    q = select(LedgerEvent).where(LedgerEvent.user_id == user_id,
                                  LedgerEvent.domain == domain)
    if event_type:
        q = q.where(LedgerEvent.event_type == event_type)
    return (await db.execute(q.order_by(LedgerEvent.id))).scalars().all()


async def _seed_food(identity, key="SEED-F"):
    return await log_food_entry(
        FoodLogBody(food_name="Rice bowl", calories=500, protein=20,
                    carbs=80, fats=10),
        identity=identity, client_request_id=key)


async def _seed_water(identity, key="SEED-W"):
    return await log_water(WaterLogBody(amount_ml=500), identity=identity,
                           client_request_id=key)


async def _seed_exercise(identity, key="SEED-E"):
    return await log_exercise_entry(
        ExerciseLogBody(exercise_name="Deadlift", sets=3, reps="5,5,5",
                        weight=140.0),
        identity=identity, client_request_id=key)


# ── 1. a repeated identical request applies once ────────────────────────────


@pytest.mark.asyncio
async def test_repeated_identical_update_applies_once(patched, db, make_user):
    user = await make_user(telegram_id="ios:p1")
    seed = await _seed_food("ios:p1")

    for _ in range(3):
        await update_food(seed["entry_id"], FoodUpdateBody(calories=600),
                          identity="ios:p1", client_request_id="P1")

    assert len(await _events(db, user.id, "food", "updated")) == 1
    row = await db.get(FoodEntry, seed["entry_id"])
    await db.refresh(row)
    assert row.calories == 600


@pytest.mark.asyncio
async def test_repeated_identical_delete_applies_once(patched, db, make_user):
    user = await make_user(telegram_id="ios:p1d")
    seed = await _seed_water("ios:p1d")

    for _ in range(3):
        await delete_water(seed["entry_id"], identity="ios:p1d",
                           client_request_id="P1D")

    assert len(await _events(db, user.id, "water", "deleted")) == 1


# ── 2. the same key with a different payload is refused ─────────────────────


@pytest.mark.asyncio
async def test_same_key_different_payload_is_refused(patched, db, make_user):
    """Serving the first result would hide a client bug that is losing the
    user's correction."""
    from fastapi import HTTPException

    await make_user(telegram_id="ios:p2")
    seed = await _seed_food("ios:p2")

    await update_food(seed["entry_id"], FoodUpdateBody(calories=600),
                      identity="ios:p2", client_request_id="P2")
    with pytest.raises(HTTPException) as e:
        await update_food(seed["entry_id"], FoodUpdateBody(calories=900),
                          identity="ios:p2", client_request_id="P2")
    assert e.value.status_code == 409

    row = await db.get(FoodEntry, seed["entry_id"])
    await db.refresh(row)
    assert row.calories == 600, "the refused request must not have applied"


# ── 3. a crash BEFORE commit leaves nothing behind ──────────────────────────


@pytest.mark.asyncio
async def test_a_crash_before_commit_leaves_no_row_change_and_no_event(
    patched, db, make_user, monkeypatch,
):
    """The row, its ledger event and the claim share one transaction, so a
    failure anywhere inside it must roll all three back — no half-applied
    edit, and no event describing a change that did not happen."""
    user = await make_user(telegram_id="ios:p3")
    seed = await _seed_water("ios:p3")

    real_commit = AsyncSession.commit

    async def boom(self):
        # Fail the water edit's commit only — the seed above already committed.
        raise RuntimeError("process died mid-write")

    monkeypatch.setattr(AsyncSession, "commit", boom)
    with pytest.raises(RuntimeError):
        await update_water(seed["entry_id"], WaterUpdateBody(amount_ml=999),
                           identity="ios:p3", client_request_id="P3")
    monkeypatch.setattr(AsyncSession, "commit", real_commit)

    await db.rollback()
    row = await db.get(WaterEntry, seed["entry_id"])
    await db.refresh(row)
    assert row.amount_ml == 500, "a crashed edit left a partially applied row"
    assert await _events(db, user.id, "water", "updated") == [], (
        "an event describes a change that never committed")


# ── 4 & 7. a crash AFTER commit is reconstructed, not re-executed ───────────


@pytest.mark.asyncio
async def test_a_claim_left_in_progress_is_reconciled_from_the_ledger(
    patched, db, make_user,
):
    """Property 4 and 7 together — the window the contract exists to close.

    The old design completed the claim in a SEPARATE commit after the write.
    A process dying in between left the edit committed and the claim
    `in_progress`, and the next delivery took the stale claim over and applied
    the edit a second time. `committed_result` asks the LEDGER whether the
    operation landed, because a timer answers 'is the original process
    probably dead', which is a different question from 'did its work commit'.

    Constructed by hand: the in-transaction completion makes this state
    unreachable now, and that is exactly why it must stay pinned.
    """
    from core.idempotency import committed_result
    from db.models import IdempotencyRecord

    user = await make_user(telegram_id="ios:p4")
    seed = await _seed_water("ios:p4")
    await update_water(seed["entry_id"], WaterUpdateBody(amount_ml=750),
                       identity="ios:p4", client_request_id="P4")

    record = (await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.command == "update_water")
    )).scalars().first()
    assert record is not None
    # Rewind it to the state a crash would have left.
    record.status = "in_progress"
    record.result_entry_id = None
    await db.commit()

    landed = await committed_result(db, record)
    assert landed is not None, (
        "the committed edit could not be reconstructed from durable history — "
        "a retry would re-apply it")
    assert landed["entry_id"] == seed["entry_id"]


@pytest.mark.asyncio
async def test_a_deletes_proof_is_a_deleted_event_not_a_created_one(
    patched, db, make_user,
):
    """A delete reconciles on its OWN event type.

    If `deleted` commands accepted `created` events, the original log of the
    row would stand as evidence that a later delete committed — reporting a
    delete as already done when it never ran, and silently dropping it.
    """
    from core.idempotency import committed_result
    from db.models import IdempotencyRecord

    await make_user(telegram_id="ios:p7")
    seed = await _seed_water("ios:p7")   # writes a `created` event

    # A delete claim whose work never ran: same turn as the create, so a
    # loose event-type match would find the `created` event and lie.
    rec = IdempotencyRecord(key="k:delete_water:never", user_id=1,
                            command="delete_water", channel="ios",
                            turn_id="ios:SEED-W", fingerprint="x",
                            status="in_progress")
    db.add(rec)
    await db.commit()

    assert await committed_result(db, rec) is None, (
        "a delete that never ran was reported as already committed")


# ── 5. two workers editing concurrently produce one effect ──────────────────


@pytest.mark.asyncio
async def test_two_concurrent_edits_of_one_request_produce_one_effect(
    patched, db, make_user,
):
    from fastapi import HTTPException

    user = await make_user(telegram_id="ios:p5")
    seed = await _seed_exercise("ios:p5")

    results = await asyncio.gather(
        update_exercise(seed["entry_id"], ExerciseUpdateBody(sets=5),
                        identity="ios:p5", client_request_id="P5"),
        update_exercise(seed["entry_id"], ExerciseUpdateBody(sets=5),
                        identity="ios:p5", client_request_id="P5"),
        return_exceptions=True,
    )

    events = await _events(db, user.id, "exercise", "updated")
    assert len(events) == 1, (
        f"two deliveries of one edit wrote {len(events)} events "
        f"(results: {results})")
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
        if isinstance(r, HTTPException):
            assert r.status_code == 409


@pytest.mark.asyncio
async def test_two_concurrent_deletes_remove_one_row_once(
    patched, db, make_user,
):
    from fastapi import HTTPException

    user = await make_user(telegram_id="ios:p5d")
    seed = await _seed_food("ios:p5d")

    results = await asyncio.gather(
        delete_food(seed["entry_id"], identity="ios:p5d",
                    client_request_id="P5D"),
        delete_food(seed["entry_id"], identity="ios:p5d",
                    client_request_id="P5D"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, user.id, "food", "deleted")) == 1


# ── 6. deleting something already deleted ───────────────────────────────────


@pytest.mark.asyncio
async def test_deleting_an_already_deleted_row_reports_the_original_success(
    patched, db, make_user,
):
    """A retry of a delete that worked is not a failure. Returning 404 would
    make the client surface an error for work that succeeded."""
    await make_user(telegram_id="ios:p6")
    seed = await _seed_exercise("ios:p6")

    first = await delete_exercise(seed["entry_id"], identity="ios:p6",
                                  client_request_id="P6")
    second = await delete_exercise(seed["entry_id"], identity="ios:p6",
                                   client_request_id="P6")
    assert first["status"] == "ok" and second["status"] == "ok"
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_deleting_a_row_that_never_existed_is_a_404(patched, db, make_user):
    """A DIFFERENT request from a retry, and it must not be mistaken for one."""
    from fastapi import HTTPException

    await make_user(telegram_id="ios:p6b")
    with pytest.raises(HTTPException) as e:
        await delete_exercise(99999, identity="ios:p6b",
                              client_request_id="P6B")
    assert e.value.status_code == 404


# ── 8. exactly one ledger effect ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_logical_edit_leaves_exactly_one_ledger_effect(
    patched, db, make_user,
):
    """The master-audit failure, pointed at edits: two writers recording the
    same change made every operation look like two."""
    user = await make_user(telegram_id="ios:p8")
    seed = await _seed_food("ios:p8")

    await update_food(seed["entry_id"], FoodUpdateBody(calories=700),
                      identity="ios:p8", client_request_id="P8")

    events = await _events(db, user.id, "food")
    kinds = [e.event_type for e in events]
    assert kinds == ["created", "updated"], (
        f"one log and one edit produced {kinds}")


# ── 9. undo reaches the right row ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_undo_after_an_edit_targets_the_edited_row(
    patched, db, make_user,
):
    from core.ledger_undo import build_plan

    user = await make_user(telegram_id="ios:p9")
    seed = await _seed_food("ios:p9")
    await update_food(seed["entry_id"], FoodUpdateBody(calories=700),
                      identity="ios:p9", client_request_id="P9")

    plan = await build_plan(db, user, "undo that")
    assert plan is not None, "an edit left nothing to undo"
    assert plan["tool_calls"][0]["input"]["entry_id"] == seed["entry_id"]
    assert plan["tool_calls"][0]["input"]["calories"] == 500, (
        "undo must restore the value the entry had BEFORE the edit")


# ── 10. canonical turn id and build attribution ─────────────────────────────


@pytest.mark.asyncio
async def test_the_write_carries_a_canonical_turn_and_a_build(
    patched, db, make_user,
):
    """Build attribution is what persisting the trace buys — `TurnMetric`
    carries `build_sha`, so a turn can be tied to the code that served it."""
    from db.models import TurnMetric

    user = await make_user(telegram_id="ios:p10")
    seed = await _seed_water("ios:p10")
    out = await update_water(seed["entry_id"], WaterUpdateBody(amount_ml=800),
                             identity="ios:p10", client_request_id="P10")

    assert out["turn_id"] == "ios:P10"
    events = await _events(db, user.id, "water", "updated")
    assert events[0].turn_id == "ios:P10", (
        "the event and the response disagree about which turn this was")

    metrics = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "ios:P10")
    )).scalars().all()
    assert metrics, "no turn metric row — the request has no build attribution"
    assert metrics[0].build_sha, "the turn does not name the build that served it"
