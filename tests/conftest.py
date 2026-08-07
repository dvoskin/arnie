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
# Semantic evidence qualification is HALTED for the suite: no resolver exists
# here, and fail-closed semantics would discard every fixture USDA row (B-1.75's
# controlled densities included). Qualification suites monkeypatch.delenv this.
os.environ.setdefault("EVIDENCE_QUALIFICATION_HALT", "1")
os.environ.setdefault("PROACTIVE_MESSAGING_ENABLED", "false")
# Scribe off in tests — it launches a real Haiku extraction; run_turn tests stay
# hermetic. Prod defaults it ON. Tests that exercise the scribe set it explicitly.
os.environ.setdefault("SCRIBE_ENABLED", "false")

from db.database import Base, _migrate  # noqa: E402
from db import models  # noqa: E402,F401  (registers tables)


@pytest_asyncio.fixture
async def engine():
    # The shared :memory: engine, deliberately BARE. Its StaticPool gives every
    # session one connection — fine for the logical assertions 7,500 tests
    # make, and wrong for exactly one family: crash/transaction-boundary tests,
    # where the pysqlite driver commits the outermost savepoint on release and
    # a dying session's transaction lingers on the shared connection. Those
    # tests override this fixture with a real file database via make_engine
    # (see test_a_crash_cannot_replay_the_meal.py); moving EVERY test onto real
    # per-session connections was tried and rejected — sqlite is a single-
    # writer database, so genuinely concurrent fixtures either deadlock on
    # deferred upgrades or self-deadlock under BEGIN IMMEDIATE when a handler
    # nests a second session. Concurrency truth lives in the Postgres suites.
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

    `_RELEVANCE_CACHE` is the same hazard and was missed. It memoizes the
    food-relevance verdict by message text, so a test that classified
    "Oh and a bag of quest chips" normally left a True behind, and a LATER
    test asserting that a broken classifier yields False got the earlier
    test's answer instead. That is the intermittent
    `test_ask_authority::test_the_lane_is_never_lost_to_a_failing_model`
    failure — it only appeared when the shuffle happened to order those two
    the wrong way round, which is exactly the class of bug shuffling exists
    to surface and exactly the kind that gets written off as flakiness.

    `core.food_ledger._SEEN` is the same hazard again and was also missed. It
    is the exactly-once registry, keyed by turn id — which for a client that
    sends no message id is sha1(channel, USER_ID, text, hour bucket). Every
    test seeds user id 1, so two tests in one process that send the same words
    an hour apart or less produce the SAME key, and the second one is answered
    "Already got that one - it's on the board from a moment ago" having written
    nothing. Found 2026-08-03 building `test_a_full_day_of_food.py`: a two-turn
    exchange answering "deli" silently became a duplicate turn because an
    earlier test in the file had already said "deli". Nothing failed at the
    seam — the turn returned 200 with a plausible reply and an empty board.
    """
    import core.food_turn as _FT
    import handlers.tool_executor as _TE
    import core.food_ledger as _FL
    import skills.nutrition.off as _OFF
    for cache in (_FT._SPREAD_CACHE, _FT._RELEVANCE_CACHE,
                  _TE._INFLIGHT_FETCHES, _FL._SEEN, _OFF._BREAKER):
        cache.clear()
    yield
    for cache in (_FT._SPREAD_CACHE, _FT._RELEVANCE_CACHE,
                  _TE._INFLIGHT_FETCHES, _FL._SEEN, _OFF._BREAKER):
        cache.clear()
