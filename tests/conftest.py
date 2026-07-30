"""
Shared pytest fixtures and plain helper factories.

Every DB test runs against a fresh in-memory SQLite database built from the real
models + the real _migrate() pass, so tests exercise the exact schema path prod
uses. Query functions all take an explicit `db` session, so we never touch the
app's global engine.

Plain helpers (_prefs, _log) are module-level functions — import them directly in
any test file that needs them rather than duplicating identical 2-liners everywhere.
"""
import os
from types import SimpleNamespace
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


# ── Shared stubs (non-fixture) ────────────────────────────────────────────────

def _prefs(cal_t=1800, pro_t=200):
    """Minimal UserPreferences stub with optional calorie + protein targets."""
    return SimpleNamespace(calorie_target=cal_t, protein_target=pro_t)


def _log(cal=0, pro=0):
    """Minimal DailyLog stub with total_calories + total_protein."""
    return SimpleNamespace(total_calories=cal, total_protein=pro)

# ── HERMETIC BY CONSTRUCTION ──────────────────────────────────────────────────
#
# The suite used to inherit whatever the working directory happened to contain,
# and it did so in total silence. Two channels, both real, both measured:
#
#   `.env`      main.py calls load_dotenv(override=True) AT IMPORT. conftest
#               runs first, so every default below was set and then overwritten
#               the moment any test imported main — pulling in live API keys and,
#               far worse, live FEATURE FLAGS. SEARCH_ENABLED, FOOD_GATE_MODEL
#               and TURN_COORDINATOR_MODE from a developer's file decided what
#               the tests were testing.
#   `arnie.db`  nothing pinned DATABASE_URL, so a sqlite file sitting in the
#               repo root became the database under test — carrying rows from
#               whatever ran last, and mutated by each run in turn.
#
# Measured 2026-07-28 on identical source: 2 failures in a clean worktree, 21 to
# 34 in one holding a developer `.env` and an `arnie.db`. Both counts STABLE
# across repeated runs, which is what made it expensive — it never presented as
# flakiness. It presented as a regression, and a previous session recorded the
# swing as inherent nondeterminism and concluded the suite was not a gate.
#
# It is a gate. It just had two doors propped open. A suite that can be moved
# this far by files it never mentions cannot answer the only question it is for.
import dotenv
dotenv.load_dotenv = lambda *a, **k: False        # a test never reads a .env

# Assignment, not setdefault: OVERRIDING an inherited value is the entire point,
# and an inherited one is exactly the case that hurt. Every DB test builds its
# own in-memory engine anyway (see `engine` below) — this closes the path for
# any code that reaches for the global URL on its own.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# Deterministic env for tests that read it. These stay `setdefault` so an
# explicit shell override (`SCRIBE_ENABLED=true pytest ...`) still works — that
# is a deliberate act, unlike a file the runner never knew was there.
os.environ.setdefault("LINKING_ENABLED", "true")
os.environ.setdefault("PROACTIVE_MESSAGING_ENABLED", "false")
# Scribe off in tests — it launches a real Haiku extraction; run_turn tests stay
# hermetic. Prod defaults it ON. Tests that exercise the scribe set it explicitly.
os.environ.setdefault("SCRIBE_ENABLED", "false")

from db.database import Base, _migrate  # noqa: E402
from db import models  # noqa: E402,F401  (registers tables)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest_asyncio.fixture
async def make_user(db):
    """Factory: create + persist a User with sensible defaults; returns the row."""
    from db.models import User, UserPreferences

    async def _make(telegram_id="100", name="Tester", onboarded=True, **kw):
        u = User(telegram_id=telegram_id, name=name,
                 onboarding_completed=onboarded, **kw)
        db.add(u)
        await db.flush()
        db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
        await db.commit()
        return u

    return _make


@pytest.fixture(autouse=True)
def _isolate_turn_scoped_caches():
    """No test inherits another test's product lookups.

    `core.food_turn._SPREAD_CACHE` is process-global and name-keyed, which is
    correct in production — the shelf behind a given product name is a stable
    fact, and that is exactly why spreads are cached across turns. In a test
    process it makes behaviour depend on test ORDER: once one test has looked
    up a Barebells bar, every later test asking about one silently gets a shelf
    it never fetched.

    That surfaced the moment the cache began carrying product ROWS as well as
    spreads (the §8.1 join), because `derive_assumed_identity` reads those rows
    to decide whether a flavour is a real choice — so an unrelated test could
    turn a silent log into a question. Same for the in-flight enrichment
    registry, which is keyed by turn id and would otherwise hand a stale future
    to a test that never started one.
    """
    import core.food_turn as _FT
    import handlers.tool_executor as _TE
    _FT._SPREAD_CACHE.clear()
    _TE._INFLIGHT_FETCHES.clear()
    yield
    _FT._SPREAD_CACHE.clear()
    _TE._INFLIGHT_FETCHES.clear()
