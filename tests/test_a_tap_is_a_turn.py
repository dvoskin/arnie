"""A tap is a turn — the iOS quick-log path is not exempt from turn identity.

`record_ledger_event` stamps the canonical turn id from the ambient contextvar
(`core.turn_identity.CURRENT_TURN_ID`). Every chat surface sets it; the
tap-log REST endpoints in `api/quick_log.py` never did. So the write landed,
the ledger event landed, and the event landed with `turn_id = NULL` — a
canonical row nothing can trace to the request that caused it.

Audit O-1 fixed the MISSING event. It did not give the event an identity. The
comment in `quick_log.py` says "A TAP IS A TURN" above a call that, on the
deployed revision (433cdf39f2d0), produces a turn-less event.

Two properties are pinned here, and both fail before the fix:

  * a tap-logged row's `created` event carries the turn id (the join I16
    measures at 93% is broken for exactly this surface)
  * the same tap delivered twice — a double tap, a mobile retry on a flaky
    network, an OS-level request replay — commits ONE row, not two

The second is the data-integrity half. `FoodEntry` has no unique constraint
covering a repeated manual log, because a user genuinely may eat two bananas;
only the CLIENT knows whether this is the same tap. That is what the
idempotency key is for, and why it must be enforced in the database rather
than by an application-level "did I see this recently" check.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.quick_log import (
    ExerciseLogBody,
    FoodLogBody,
    log_exercise_entry,
    log_food_entry,
)
from db.models import ExerciseEntry, FoodEntry, LedgerEvent


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


# ── the event can be traced to its turn ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_keyless_tap_still_produces_a_traceable_event(
    patched_session_local, db, make_user,
):
    """The defect, in the caller's own words.

    This is the deployed call — no idempotency key, exactly what the shipped
    iOS build sends. It fails on 433cdf39f2d0 with `turn_id = None`, and it
    fails on an ASSERTION rather than a signature error, so it measures the
    behaviour and not the refactor.

    Traceability must not depend on the client sending anything: a build that
    predates `Idempotency-Key` still has to produce a joinable event. The
    hash fallback in `make_turn_id` is what guarantees that.
    """
    user = await make_user(telegram_id="ios:keyless")
    await log_food_entry(
        FoodLogBody(food_name="Apple", calories=95, protein=0, carbs=25, fats=0),
        identity="ios:keyless",
    )

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()

    assert len(events) == 1
    assert events[0].turn_id is not None, (
        "a tap-logged event with no turn id cannot be joined to the request "
        "that caused it — this is the deployed defect"
    )
    assert events[0].turn_id.startswith("ios:h:"), (
        "with no client key the id must come from the documented hash "
        "fallback, not from an invented format"
    )


@pytest.mark.asyncio
async def test_a_tap_logged_food_event_carries_its_turn_id(
    patched_session_local, db, make_user,
):
    """The `created` event for a tap-logged food names the turn that caused it."""
    user = await make_user(telegram_id="ios:tap-turn-food")
    await log_food_entry(
        FoodLogBody(food_name="Greek yogurt", quantity="200g",
                    calories=120, protein=18, carbs=8, fats=0),
        identity="ios:tap-turn-food",
        client_request_id="TAP-UUID-1",
    )

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()

    assert len(events) == 1, "the tap should record exactly one created event"
    assert events[0].turn_id, (
        "a tap-logged food event has no turn id — it cannot be joined to the "
        "request that created it"
    )
    assert events[0].turn_id == "ios:TAP-UUID-1"


@pytest.mark.asyncio
async def test_a_tap_logged_exercise_event_carries_its_turn_id(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:tap-turn-ex")
    await log_exercise_entry(
        ExerciseLogBody(exercise_name="Barbell row", sets=3, reps="8,8,8",
                        weight=60.0),
        identity="ios:tap-turn-ex",
        client_request_id="TAP-UUID-2",
    )

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()

    assert len(events) == 1
    assert events[0].turn_id == "ios:TAP-UUID-2"


# ── the same tap twice is one row ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_same_tap_delivered_twice_commits_one_food_row(
    patched_session_local, db, make_user,
):
    """A retry replays the client's request id byte-for-byte. It must not eat
    twice."""
    user = await make_user(telegram_id="ios:tap-retry")
    body = FoodLogBody(food_name="Banana", quantity="1 medium",
                       calories=105, protein=1, carbs=27, fats=0)

    first = await log_food_entry(body, identity="ios:tap-retry",
                                 client_request_id="RETRY-ME")
    second = await log_food_entry(body, identity="ios:tap-retry",
                                  client_request_id="RETRY-ME")

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Banana")
    )).scalars().all()

    assert len(rows) == 1, "a replayed tap created a duplicate food row"
    assert second["entry_id"] == first["entry_id"], (
        "the replay must return the ORIGINAL committed result, not a new one"
    )
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_the_same_tap_delivered_twice_commits_one_exercise_row(
    patched_session_local, db, make_user,
):
    await make_user(telegram_id="ios:tap-retry-ex")
    body = ExerciseLogBody(exercise_name="Cable crunch", sets=3, reps="12,12,12",
                           weight=40.0)

    first = await log_exercise_entry(body, identity="ios:tap-retry-ex",
                                     client_request_id="RETRY-EX")
    second = await log_exercise_entry(body, identity="ios:tap-retry-ex",
                                      client_request_id="RETRY-EX")

    rows = (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.exercise_name == "Cable crunch")
    )).scalars().all()

    assert len(rows) == 1
    assert second["entry_id"] == first["entry_id"]


@pytest.mark.asyncio
@pytest.mark.skipif(not __import__("os").getenv("TEST_POSTGRES_URL"),
                    reason="two deliveries racing needs two real connections; "
                           "the sqlite fixture shares ONE, so either's "
                           "rollback destroys the other's in-flight work — a "
                           "fixture artifact, not a production semantic")
async def test_two_concurrent_deliveries_of_one_tap_commit_one_row(
    make_user, monkeypatch,
):
    """The double-tap race, on the database that runs in production.

    The invariant is ONE ROW. The loser may either receive the winner's result
    (the winner finished first) or a retryable 409 (the winner is still
    writing) — both are correct, and which one happens depends on scheduling.
    What is never correct is two rows.

    PG-gated since the promotion: the canonical spine holds its transaction
    open across the whole mutation, which on the shared-connection sqlite
    fixture lets delivery B's rollback destroy delivery A's staged work. Real
    connections do not share transactions; the same race at the coordinator
    level is proven in test_two_connections_one_commit.py.
    """
    import asyncio
    import os

    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from api import quick_log as QL
    from db.database import make_engine
    from db.models import Base, User

    engine = make_engine(os.environ["TEST_POSTGRES_URL"],
                         pool_size=5, max_overflow=5)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession,
                                     expire_on_commit=False)
        monkeypatch.setattr(QL, "AsyncSessionLocal", factory)
        async with factory() as s:
            s.add(User(telegram_id="ios:tap-race"))
            await s.commit()

        body = FoodLogBody(food_name="Protein shake", quantity="1 scoop",
                           calories=130, protein=25, carbs=3, fats=2)
        results = await asyncio.gather(
            log_food_entry(body, identity="ios:tap-race",
                           client_request_id="RACE-1"),
            log_food_entry(body, identity="ios:tap-race",
                           client_request_id="RACE-1"),
            return_exceptions=True,
        )

        async with factory() as s:
            rows = (await s.execute(
                select(FoodEntry)
                .where(FoodEntry.parsed_food_name == "Protein shake")
            )).scalars().all()
        assert len(rows) == 1, f"the double tap wrote {len(rows)} rows"

        entry_ids, retryable = set(), 0
        for r in results:
            if isinstance(r, HTTPException):
                assert r.status_code == 409, r
                assert r.detail.get("retryable") is True, (
                    "the loser must be told to retry, not to report a bug")
                retryable += 1
            elif isinstance(r, Exception):
                raise AssertionError(f"a delivery failed outright: {r!r}")
            else:
                entry_ids.add(r["entry_id"])
        assert entry_ids <= {rows[0].id}, (
            f"a delivery answered with a row that does not exist: {entry_ids}")
        assert (len(entry_ids) == 1 and retryable <= 1), results
    finally:
        await engine.dispose()
@pytest.mark.asyncio
async def test_the_database_rejects_a_duplicate_claim(db, make_user):
    """The structural guarantee, independent of any application check.

    If this constraint is ever dropped, every other test here still passes and
    the duplicate protection is gone — so it is pinned directly."""
    from sqlalchemy.exc import IntegrityError

    from core.idempotency import build_key
    from db.models import IdempotencyRecord

    user = await make_user(telegram_id="ios:constraint")
    key = build_key("ios", "log_food", user.id, "DUPE")

    db.add(IdempotencyRecord(key=key, user_id=user.id, command="log_food",
                             channel="ios", fingerprint="abc",
                             status="completed"))
    await db.commit()

    db.add(IdempotencyRecord(key=key, user_id=user.id, command="log_food",
                             channel="ios", fingerprint="abc",
                             status="completed"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# ── a reused key with a different meal is a bug, not a retry ─────────────────


@pytest.mark.asyncio
async def test_a_reused_key_with_a_different_payload_fails_loudly(
    patched_session_local, db, make_user,
):
    """Silently returning the first result would hide a client bug that is
    losing the user's food."""
    from fastapi import HTTPException

    await make_user(telegram_id="ios:tap-conflict")
    await log_food_entry(
        FoodLogBody(food_name="Oatmeal", calories=300, protein=10, carbs=54, fats=5),
        identity="ios:tap-conflict", client_request_id="SAME-KEY",
    )

    with pytest.raises(HTTPException) as excinfo:
        await log_food_entry(
            FoodLogBody(food_name="Pizza", calories=900, protein=35, carbs=90, fats=40),
            identity="ios:tap-conflict", client_request_id="SAME-KEY",
        )
    assert excinfo.value.status_code == 409
