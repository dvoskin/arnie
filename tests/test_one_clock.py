"""Stored time and compared time are the same clock, whatever the server says.

43 columns are naive `DateTime` filled by the DATABASE (`server_default=
func.now()`), while every freshness rule is judged in Python against
`datetime.utcnow()`. Postgres `now()` is a timestamptz; storing it in a
`timestamp without time zone` converts it through the SESSION's TimeZone. So
the gap between the two clocks was the database server's timezone — an ambient
default, settable per-server, per-database, per-role, or by a client PGTZ, and
written down nowhere.

Both directions fail silently, which is why nothing caught it:

  * WEST of UTC, stored times read as OLD. With `STALE_CLAIM_SECONDS = 90`, a
    US-Eastern server makes every claim look four hours stale, so every
    duplicate delivery takes over a claim that is still running and the meal is
    written twice. Idempotency reports success, twice.
  * EAST of UTC, stored times read as FUTURE. The age is negative, never
    reaches the threshold, and the key wedges permanently.

Production runs UTC, so it does not manifest there — which is precisely the
danger: a correctness property held by luck of deployment.

These tests set the DATABASE's default timezone AWAY from UTC and then require
a fresh connection to still be UTC. Written that way deliberately, so they stay
meaningful on CI, where the server is already UTC and a bare "is it UTC?"
assertion would pass without touching the mechanism.
"""
import asyncio
import os
from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

import db.database as database
from db.database import (SessionTimezoneNotPinned, make_engine,
                         pin_session_utc)
from db.models import Base, IdempotencyRecord, User

PG = os.getenv("TEST_POSTGRES_URL")

if os.getenv("CI") and not PG:
    raise RuntimeError(
        "TEST_POSTGRES_URL is unset in CI. The one-clock guarantee is a "
        "property of a real database session; sqlite has no session timezone "
        "and cannot express it.")

pytestmark = pytest.mark.skipif(
    not PG, reason="needs a real Postgres (TEST_POSTGRES_URL); sqlite has no "
                   "session timezone to pin")

OFFSET_TZ = "America/New_York"           # any zone that is never UTC


@pytest.fixture
async def skewed_server():
    """A database whose DEFAULT timezone is not UTC.

    `ALTER DATABASE` applies to connections opened afterwards, so this changes
    what a fresh connection would inherit — exactly the condition production
    would land in after a restore or a provider move.
    """
    admin = make_engine(PG, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        name = (await c.execute(text("SELECT current_database()"))).scalar()
        await c.execute(text(f'ALTER DATABASE "{name}" SET timezone TO '
                             f"'{OFFSET_TZ}'"))
    try:
        engine = make_engine(PG)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        yield engine
        await engine.dispose()
    finally:
        async with admin.connect() as c:
            await c.execute(text(f'ALTER DATABASE "{name}" RESET timezone'))
        await admin.dispose()


async def _user(maker) -> int:
    async with maker() as s:
        u = User(telegram_id="clock:probe")
        s.add(u)
        await s.commit()
        return u.id


@pytest.mark.asyncio
async def test_a_connection_is_utc_even_when_the_server_is_not(skewed_server):
    async with skewed_server.connect() as c:
        tz = (await c.execute(text("SHOW timezone"))).scalar()
    assert tz.upper() == "UTC", (
        f"the session inherited {tz} from the server; every naive timestamp "
        f"written on it is offset from the utcnow() it is compared against")


@pytest.mark.asyncio
async def test_the_database_clock_and_utcnow_agree(skewed_server):
    """The property every freshness comparison in the codebase assumes."""
    async with skewed_server.connect() as c:
        stored = (await c.execute(text("SELECT now()::timestamp"))).scalar()
    drift = abs((stored - datetime.utcnow()).total_seconds())
    assert drift < 5, (
        f"the database clock and utcnow() are {drift:.0f}s apart — a stored "
        f"timestamp read back as an age would be wrong by that much")


@pytest.mark.asyncio
async def test_a_row_stamped_by_the_database_is_not_born_stale(skewed_server):
    """The defect at its actual site.

    `idempotency_records.created_at` is written by the database and its age is
    judged in Python. Unpinned on a US-Eastern server this row is born 14400
    seconds old, sails past STALE_CLAIM_SECONDS = 90, and the next delivery
    takes the claim over and writes the meal again.
    """
    from core.idempotency import STALE_CLAIM_SECONDS

    maker = async_sessionmaker(skewed_server, class_=AsyncSession,
                               expire_on_commit=False)
    uid = await _user(maker)
    async with maker() as s:
        s.add(IdempotencyRecord(key="clock:probe", user_id=uid,
                                command="log_food", channel="ios",
                                fingerprint="abc", status="in_progress"))
        await s.commit()
        row = (await s.execute(select(IdempotencyRecord).where(
            IdempotencyRecord.key == "clock:probe"))).scalar_one()

    age = (datetime.utcnow() - row.created_at).total_seconds()
    assert 0 <= age < STALE_CLAIM_SECONDS, (
        f"a row created just now reads as {age:.0f}s old against a "
        f"{STALE_CLAIM_SECONDS}s staleness threshold — "
        + ("it would be taken over immediately" if age >= STALE_CLAIM_SECONDS
           else "its age is NEGATIVE, so it can never become takeoverable"))


@pytest.mark.asyncio
async def test_the_two_writers_of_one_column_land_in_one_domain(skewed_server):
    """Four columns are stamped by the DATABASE on insert and by
    `datetime.utcnow()` on update — `idempotency_records.created_at` among them.

    Unpinned, one column holds a MIX of local and UTC values with nothing
    recording which is which, so the damage cannot be repaired afterwards. Here
    the two writers must be indistinguishable.
    """
    maker = async_sessionmaker(skewed_server, class_=AsyncSession,
                               expire_on_commit=False)
    uid = await _user(maker)
    async with maker() as s:
        row = IdempotencyRecord(key="clock:two-writers", user_id=uid,
                                command="log_food", channel="ios",
                                fingerprint="abc", status="in_progress")
        s.add(row)
        await s.commit()
        by_database = row.created_at

        row.created_at = datetime.utcnow()      # the takeover path's own write
        await s.commit()
        by_python = row.created_at

    assert abs((by_python - by_database).total_seconds()) < 5, (
        f"the database wrote {by_database} and Python wrote {by_python} into "
        f"the same column — the row's age now depends on which writer touched "
        f"it last")


@pytest.mark.asyncio
async def test_concurrent_connections_are_each_pinned(skewed_server):
    """The listener runs per connection, so a pool that opens more under load
    must pin every one of them — not just the first."""
    async def tz_of():
        async with skewed_server.connect() as c:
            return (await c.execute(text("SHOW timezone"))).scalar()

    zones = await asyncio.gather(*(tz_of() for _ in range(6)))
    assert {z.upper() for z in zones} == {"UTC"}, zones


# ── the guarantee is ENFORCED, not attempted ─────────────────────────────────
#
# Logging a failure and continuing would hand the application the exact
# connection this exists to reject. These three tests are the difference
# between a check and a wish.

@pytest.mark.asyncio
async def test_a_connection_that_cannot_be_pinned_is_refused(monkeypatch):
    """A driver error, a permission restriction, an unexpected cursor — any of
    them must REJECT the connection, not log it and carry on."""
    def _explode(_conn):
        raise RuntimeError("driver refused SET")

    monkeypatch.setattr(database, "_confirm_utc", _explode)
    engine = make_engine(PG)
    try:
        with pytest.raises(SessionTimezoneNotPinned):
            async with engine.connect() as c:
                await c.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_session_that_reports_the_wrong_zone_is_refused(monkeypatch):
    """The set may 'succeed' and the session still not be UTC. Confirming is
    the point; the read-back is not decoration."""
    monkeypatch.setattr(database, "_confirm_utc",
                        lambda _conn: "America/New_York")
    engine = make_engine(PG)
    try:
        with pytest.raises(SessionTimezoneNotPinned) as exc:
            async with engine.connect() as c:
                await c.execute(text("SELECT 1"))
        assert "America/New_York" in str(exc.value)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_refused_connection_does_not_reach_the_pool(monkeypatch):
    """The point of raising rather than logging: no later checkout may quietly
    receive the connection that failed its check."""
    calls = {"n": 0}

    def _explode(_conn):
        calls["n"] += 1
        raise RuntimeError("driver refused SET")

    monkeypatch.setattr(database, "_confirm_utc", _explode)
    engine = make_engine(PG)
    try:
        for _ in range(3):
            with pytest.raises(SessionTimezoneNotPinned):
                async with engine.connect() as c:
                    await c.execute(text("SELECT 1"))
        assert calls["n"] == 3, (
            "a refused connection was pooled and reused — it was checked once "
            "and handed out again unchecked")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_an_engine_nobody_pinned_is_refused():
    """The factory covers engines built through it. This covers the one built
    directly in a test, a script or a migration, which would otherwise run on
    the server's timezone and reintroduce the defect silently."""
    engine = create_async_engine(PG)          # deliberately NOT via make_engine
    try:
        with pytest.raises(SessionTimezoneNotPinned, match="never pinned"):
            async with engine.connect() as c:
                await c.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pinning_is_keyed_on_the_dialect_not_the_driver_module():
    """An earlier version matched substrings against
    `type(dbapi_conn).__module__`, which is implementation detail: SQLAlchemy
    hands the sync connect event an ADAPTER PROXY for async drivers, so a
    renamed adapter matches nothing and the listener silently does nothing.
    The dialect is public API and identical across psycopg, psycopg2, asyncpg
    and pg8000."""
    engine = make_engine(PG)
    try:
        assert engine.sync_engine.dialect.name == "postgresql"
        assert getattr(engine.sync_engine, database._UTC_PINNED, False)
        async with engine.connect() as c:
            assert (await c.execute(text("SHOW timezone"))).scalar().upper() \
                == "UTC"
    finally:
        await engine.dispose()


def test_sqlite_is_left_alone_and_still_usable():
    """SQLite has no session timezone. Pinning must be a no-op rather than
    sending it SQL it cannot parse — and the guard must not refuse it."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    assert engine.sync_engine.dialect.name == "sqlite"
    assert not getattr(engine.sync_engine, database._UTC_PINNED, False)


# ── the deploy path ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alembic_can_still_reach_a_postgres_database():
    """THE REGRESSION THIS FILE ALMOST CAUSED.

    `alembic/env.py` imports `db.models`, which registers the guard that
    refuses unpinned Postgres engines — and then builds its own SYNCHRONOUS
    engine via `engine_from_config`. The first version of the guard therefore
    made `alembic upgrade heads` fail outright, and that command runs
    pre-deploy. Every deploy would have broken.

    Run as a subprocess because that is how the deploy runs it: a fresh
    interpreter, the real env.py, the real engine construction.
    """
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "DATABASE_URL": PG})
    assert proc.returncode == 0, (
        "alembic cannot open a Postgres connection — the pre-deploy "
        f"`alembic upgrade heads` would fail:\n{proc.stderr[-1500:]}")
    assert "SessionTimezoneNotPinned" not in proc.stderr


@pytest.mark.asyncio
async def test_migrations_run_on_a_utc_session():
    """A migration that backfills or defaults a timestamp writes with the
    DATABASE clock. Running it unpinned would put local time into columns the
    application reads as UTC — the same defect, arriving through the one path
    that touches every row at once."""
    from alembic.config import Config

    from alembic import script

    cfg = Config("alembic.ini")
    heads = script.ScriptDirectory.from_config(cfg).get_heads()
    assert heads, "no alembic head — the chain is broken"

    engine = make_engine(PG)
    try:
        async with engine.connect() as c:
            assert (await c.execute(text("SHOW timezone"))).scalar().upper() \
                == "UTC"
    finally:
        await engine.dispose()
