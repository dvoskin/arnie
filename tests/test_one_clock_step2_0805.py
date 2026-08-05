"""Step 2: one authoritative clock, and it is the database's.

Step 1 pinned every session to UTC — the two clocks agreed about the ZONE. They
were still two clocks: the application host and the database host keep time
separately, bounded by NTP at seconds and unbounded when NTP fails.

WHICH CLOCK WINS WAS MEASURED, NOT PREFERRED. Every freshness comparison in
this codebase reads a timestamp the DATABASE wrote (`server_default=func.now()`)
and compared it against `datetime.utcnow()`. All of them were cross-domain, and
the values live in the database — so the database is the only choice that makes
both sides of every comparison agree by construction.

The correction is arithmetic, not I/O: the offset is measured periodically and
`clock.now()` returns `utcnow() + offset`. That keeps comparisons which operate
on already-loaded objects (`core/llm.py` holds a `User` and asks how old the
account is — there is no query there to extend) without a round trip inside
scheduler loops.
"""
import os
import re
import pathlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import clock
from db.database import make_engine
from db.models import Base

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean():
    clock.reset()
    yield
    clock.reset()


# ── the default is safe ──────────────────────────────────────────────────────

def test_before_any_sync_it_is_exactly_utcnow():
    """A deployment that never syncs must be no worse off than before this
    module existed. That is what makes it adoptable without a flag."""
    assert clock.skew_seconds() is None, "unmeasured is not zero"
    assert clock.synced_at() is None
    assert abs((clock.now() - datetime.utcnow()).total_seconds()) < 0.05


def test_unmeasured_is_reported_as_unmeasured_not_as_zero():
    """A health surface printing 0.000s for 'never measured' claims a
    guarantee nobody checked — the failure this whole migration is about."""
    assert clock.skew_seconds() is None


# ── the offset is applied ────────────────────────────────────────────────────

def test_the_offset_moves_now(monkeypatch):
    clock.reset()
    monkeypatch.setattr(clock, "_offset", timedelta(seconds=7.5))
    delta = (clock.now() - datetime.utcnow()).total_seconds()
    assert 7.0 < delta < 8.0, delta


@pytest.mark.asyncio
async def test_a_failed_sync_keeps_the_previous_offset(monkeypatch):
    """A stale correction is closer than none, and a measurement that fails
    must not take down the caller that asked for it."""
    monkeypatch.setattr(clock, "_offset", timedelta(seconds=3))

    class _Broken:
        engine = None
        async def execute(self, *a, **k):
            raise RuntimeError("connection lost")

    assert await clock.sync(_Broken()) is None
    assert abs((clock.now() - datetime.utcnow()).total_seconds() - 3) < 0.05


# ── against a real database ──────────────────────────────────────────────────

PG = os.getenv("TEST_POSTGRES_URL")
pg_only = pytest.mark.skipif(not PG, reason="needs a real Postgres")


@pytest_asyncio.fixture
async def pg():
    engine = make_engine(PG)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pg_only
@pytest.mark.asyncio
async def test_sync_measures_a_real_database(pg):
    async with pg() as s:
        skew = await clock.sync(s)
    assert skew is not None, "the measurement did not run against Postgres"
    # Same machine, so the honest expectation is ~0 — the assertion that
    # matters is that it MEASURED, and that the midpoint correction kept the
    # query's own latency out of the number.
    assert abs(skew) < 2.0, f"implausible skew for one host: {skew}"
    assert clock.skew_seconds() == skew
    assert clock.synced_at() is not None


@pg_only
@pytest.mark.asyncio
async def test_now_tracks_the_database_clock(pg):
    from sqlalchemy import text

    async with pg() as s:
        await clock.sync(s)
        db_time = (await s.execute(text("SELECT now()::timestamp"))).scalar()
    assert abs((clock.now() - db_time).total_seconds()) < 2.0


@pytest.mark.asyncio
async def test_sqlite_is_not_measured():
    """sqlite runs IN THIS PROCESS — there is no second host. Measuring would
    report our own clock as the reference and imply a guarantee that does not
    exist."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, class_=AsyncSession)
    async with maker() as s:
        assert await clock.sync(s) is None
    assert clock.skew_seconds() is None
    await engine.dispose()


# ── the rule, enforced ───────────────────────────────────────────────────────

#: The ONE comparison that is legitimately on the application clock:
#: `whoop_token_expires_at` is computed by the app from the OAuth `expires_in`,
#: so comparing it to `utcnow()` is SAME-domain. Converting it would introduce
#: the cross-domain comparison this migration removes — the rule is "compare
#: with the clock that wrote it", and it cuts both ways.
_APP_CLOCK_BY_DESIGN = {"bot/telegram_handler.py"}


def _app_clock_comparisons() -> set:
    found = set()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", ".venv/")) \
                or rel.startswith("simulate_") or rel == "core/clock.py":
            continue
        try:
            src = path.read_text()
        except Exception:
            continue
        for line in src.splitlines():
            if "utcnow()" in line and re.search(
                    r"utcnow\(\)\s*-|-\s*[\w.]*utcnow\(\)", line):
                found.add(rel)
    return found


def test_every_freshness_comparison_uses_the_one_clock():
    """RATCHET. A new `utcnow()` comparison against a database-written
    timestamp reintroduces two clocks, silently, and the threshold it breaks
    might be the 90-second one."""
    found = _app_clock_comparisons()
    new = found - _APP_CLOCK_BY_DESIGN
    assert not new, (
        f"{sorted(new)} compare against the APPLICATION clock. Timestamps "
        f"written by the database must be compared with clock.now() — see "
        f"docs/ONE_CLOCK_MIGRATION.md.")
    stale = _APP_CLOCK_BY_DESIGN - found
    assert not stale, (
        f"{sorted(stale)} no longer compares against utcnow() — remove it from "
        f"_APP_CLOCK_BY_DESIGN so the ratchet keeps tightening")


def test_the_idempotency_claim_is_judged_on_the_database_clock():
    """The tightest threshold in the codebase, and the one that decides whether
    a meal is written twice."""
    src = (ROOT / "core" / "idempotency.py").read_text()
    assert "clock.now() - started < timedelta(seconds=STALE_CLAIM_SECONDS)" in src
    assert "datetime.utcnow() - started" not in src
