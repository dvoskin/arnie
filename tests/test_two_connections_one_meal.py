"""Two real connections, one key, one meal — the guarantee sqlite cannot test.

Every other concurrency test in this repo runs on `sqlite+aiosqlite:///:memory:`,
which SQLAlchemy backs with a StaticPool: two sessions share ONE connection, so
what looks like a race is really async interleaving. That is a fine test of the
handler's logic and no test at all of the thing the whole design rests on —
the unique index on `idempotency_records.key` rejecting a second claim arriving
on a SECOND connection, in a second transaction, with no shared session state.

That claim has been made repeatedly in commit messages today. It has never been
exercised. These tests exercise it, against a real Postgres.

They SKIP without `TEST_POSTGRES_URL` rather than passing quietly. A test that
cannot run must say so — a green tick standing in for an unrun check is how the
per-100g bug survived a passing suite for a month.
"""
import asyncio
import os

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from core import idempotency
from core.idempotency import build_key, claim_request, fingerprint_of
from db.models import Base, IdempotencyRecord, User

PG = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not PG, reason="needs a real Postgres (TEST_POSTGRES_URL); sqlite shares "
                   "one connection and cannot express this race")


@pytest.fixture
async def pg():
    """A clean schema per test, on an engine whose pool hands out REAL
    independent connections."""
    engine = create_async_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _user(maker) -> int:
    async with maker() as s:
        u = User(telegram_id="pg:race")
        s.add(u)
        await s.commit()
        return u.id


@pytest.mark.asyncio
async def test_two_connections_racing_one_key_produce_one_claim(pg):
    """THE structural guarantee. Two sessions, two connections, no shared
    identity map — exactly one may own the key."""
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    uid = await _user(maker)
    payload = {"food_name": "Stew", "calories": 400}

    async def attempt():
        async with maker() as s:
            try:
                return await claim_request(
                    s, channel="ios", command="log_food", user_id=uid,
                    client_key="RACE", payload=payload, turn_id="ios:RACE")
            except (idempotency.IdempotencyInProgress,
                    idempotency.IdempotencyConflict) as e:
                return e

    results = await asyncio.gather(attempt(), attempt(), attempt(),
                                   return_exceptions=True)

    owners = [r for r in results
              if isinstance(r, idempotency.Claim) and not r.replay]
    assert len(owners) == 1, (
        f"{len(owners)} callers were told they own the key — the unique index "
        f"did not hold across connections ({results})"
    )

    async with maker() as s:
        rows = (await s.execute(
            select(IdempotencyRecord)
            .where(IdempotencyRecord.key ==
                   build_key("ios", "log_food", uid, "RACE"))
        )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_the_database_rejects_the_second_insert_not_the_application(pg):
    """Proves the guard is the INDEX, not a select-then-insert window. If this
    passes while the index is gone, every other assertion here is decoration."""
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    uid = await _user(maker)
    key = build_key("ios", "log_food", uid, "DUPE")

    def row():
        return IdempotencyRecord(key=key, user_id=uid, command="log_food",
                                 channel="ios", fingerprint="abc",
                                 status="completed")

    async with maker() as a:
        a.add(row())
        await a.commit()

    async with maker() as b:          # a genuinely separate connection
        b.add(row())
        with pytest.raises(IntegrityError):
            await b.commit()


@pytest.mark.asyncio
async def test_a_conflicting_payload_across_connections_still_conflicts(pg):
    """The conflict check must survive the race too: whoever loses the insert
    still has to notice the payload differs rather than replaying blindly."""
    maker = async_sessionmaker(pg, class_=AsyncSession, expire_on_commit=False)
    uid = await _user(maker)

    async with maker() as s:
        await claim_request(s, channel="ios", command="log_food", user_id=uid,
                            client_key="MIX", payload={"food_name": "Stew"},
                            turn_id="ios:MIX")

    async with maker() as s:
        with pytest.raises(idempotency.IdempotencyConflict):
            await claim_request(s, channel="ios", command="log_food",
                                user_id=uid, client_key="MIX",
                                payload={"food_name": "Pizza"},
                                turn_id="ios:MIX")


def test_the_fingerprint_is_stable_across_processes():
    """Reconciliation compares fingerprints written by DIFFERENT processes, so
    the hash must not depend on dict ordering or interpreter state."""
    a = fingerprint_of({"food_name": "Stew", "calories": 400})
    b = fingerprint_of({"calories": 400, "food_name": "Stew"})
    assert a == b
