import logging
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


def _resolve_database_url() -> str:
    """
    Resolve DATABASE_URL and ensure the parent directory exists.
    Falls back to /tmp/arnie.db if the preferred path can't be created
    (e.g. no persistent disk mounted on Render yet).
    """
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///arnie.db")

    # Render's managed-Postgres connection string is libpq-style ("postgresql://..."
    # or the legacy "postgres://..."). SQLAlchemy maps a bare postgresql:// to
    # psycopg2 (which we don't install) — coerce to our async driver, psycopg3.
    # Also normalize asyncpg if someone set that. Idempotent.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    elif url.startswith("postgresql+asyncpg://"):
        url = "postgresql+psycopg://" + url[len("postgresql+asyncpg://"):]

    if "sqlite" not in url:
        return url  # Postgres or other — no dir to create

    # Extract the file path from sqlite+aiosqlite:////data/arnie.db
    path_str = url.split("///")[-1]
    if not path_str.startswith("/"):
        return url  # relative path, no action needed

    db_path = Path(path_str)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Database directory ready: {db_path.parent}")
        return url
    except (PermissionError, OSError) as e:
        fallback = "sqlite+aiosqlite:////tmp/arnie.db"
        logger.warning(
            f"Cannot create {db_path.parent} ({e}). "
            f"Falling back to {fallback} — data will not persist across restarts. "
            f"Add a persistent disk in the Render dashboard to fix this."
        )
        return fallback


DATABASE_URL = _resolve_database_url()
_IS_SQLITE = "sqlite" in DATABASE_URL

# SQLite concurrency hardening. Telegram + iMessage webhooks write concurrently
# (async); with default settings that raises "database is locked" under contention
# — a real source of intermittent glitches (a log that doesn't save, a reply that
# errors). WAL lets readers run without blocking the writer; busy_timeout makes a
# contending write WAIT for the lock instead of erroring immediately. Guarded so a
# future Postgres URL is unaffected.
_engine_kwargs = {"echo": False}
if _IS_SQLITE:
    _engine_kwargs["connect_args"] = {"timeout": 30}

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

if _IS_SQLITE:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

# ── ONE CLOCK ────────────────────────────────────────────────────────────────
# Every Postgres connection proves its session is UTC before it is used, or it
# is refused.
#
# THE TWO CLOCKS HAVE TO AGREE, AND NOTHING MADE THEM. 43 columns are naive
# `DateTime` filled by the DATABASE clock (`server_default=func.now()`), while
# freshness is judged in Python against `datetime.utcnow()`. Postgres `now()`
# returns timestamptz; storing it in a `timestamp without time zone` column
# converts it using the SESSION's TimeZone. So the offset between those two
# clocks is whatever the database server's timezone happens to be — an ambient
# default, settable per-server, per-database, per-role or by a client PGTZ, and
# recorded nowhere in this repo.
#
# Both failure directions are silent:
#
#   * WEST of UTC, stored times read as OLD. `idempotency.STALE_CLAIM_SECONDS`
#     is 90, so on a US-Eastern server every claim looks 4 hours stale, every
#     duplicate delivery "takes over" a claim that is actually still running,
#     and the meal is written twice. Idempotency does not report an error; it
#     reports success, twice.
#   * EAST of UTC, stored times read as FUTURE. The age is negative, so it never
#     reaches the threshold, every retry raises IdempotencyInProgress, and the
#     key wedges permanently.
#
# Worse, four columns are written by the database clock on INSERT and by
# `datetime.utcnow()` on UPDATE — idempotency_records.created_at among them.
# On a non-UTC server one column then holds a MIX of local and UTC values with
# nothing recording which is which, so the damage is not repairable after the
# fact.
#
# Production runs UTC today, which is exactly what makes this dangerous: it is
# a correctness property that is true by luck of deployment and would fail
# silently on a restore, a provider move, or a `SET timezone` in a dashboard.
#
# THIS IS NOT THE WHOLE UNIFICATION. It removes the timezone axis outright; it
# does not merge the two clocks into one source, so host clock skew between the
# app and the database still exists — bounded by NTP at seconds rather than
# hours, but real against a 90-second threshold. Collapsing every freshness
# comparison onto ONE authoritative clock is tracked in
# docs/ONE_CLOCK_MIGRATION.md and gates removal of the legacy lane.
from sqlalchemy import event as _event
from sqlalchemy.engine import Engine as _Engine


class SessionTimezoneNotPinned(RuntimeError):
    """A Postgres connection whose session timezone is not provably UTC.

    RAISED, NOT LOGGED. An earlier version logged and returned, which handed
    the application the exact connection the check exists to reject: a driver
    error, a permission restriction or an unexpected cursor behaviour would be
    recorded and then the unreliable connection used anyway, and every
    freshness comparison made on it — idempotency's included — would be wrong
    by hours with no further signal. Logging is not enforcement.

    The contract is binary: UTC confirmed -> the connection may be used;
    not confirmed -> nothing gets it.
    """


#: Set on an engine once `pin_session_utc` has attached its listener. The
#: guard below reads it to tell "pinned" from "nobody pinned this".
_UTC_PINNED = "_arnie_utc_pinned"


def _confirm_utc(dbapi_conn) -> str:
    """Set the session to UTC and READ IT BACK. Returns what the session says.

    A module-level function rather than a closure so the failure path is
    reachable from a test — a rejection nobody can trigger is a rejection
    nobody has checked.

    THE COMMIT IS LOAD-BEARING. `SET` is transactional and the pool rolls back
    every connection it hands out, so without it the statement runs, raises
    nothing, and is silently reverted: a fix that reads as correct and does
    nothing. The read-back then confirms rather than assumes, which is the
    difference between "we tried to pin it" and "it is pinned".
    """
    cur = dbapi_conn.cursor()
    try:
        cur.execute("SET TimeZone='UTC'")
    finally:
        cur.close()
    dbapi_conn.commit()
    cur = dbapi_conn.cursor()
    try:
        cur.execute("SHOW timezone")
        return (cur.fetchone() or [None])[0]
    finally:
        cur.close()


def pin_session_utc(engine):
    """Require every connection this engine opens to be UTC. Returns `engine`.

    KEYED ON THE DIALECT, not on the driver's module name. An earlier version
    matched substrings like "psycopg" against `type(dbapi_conn).__module__`,
    which is implementation detail: SQLAlchemy hands the sync `connect` event
    an adapter proxy for async drivers, so a renamed or unanticipated adapter
    silently matches nothing and the listener does nothing at all — failing
    open in the quietest possible way. `dialect.name == "postgresql"` is public
    API and true for psycopg, psycopg2, asyncpg and pg8000 alike.

    Applied through a shared factory rather than globally to every engine in
    the process, so forcing a session setting on someone else's database is a
    deliberate act with an owner, not a side effect of importing this module.
    Engines that skip the factory are refused by the guard below rather than
    quietly running unpinned.
    """
    sync_engine = getattr(engine, "sync_engine", engine)
    if sync_engine.dialect.name != "postgresql":
        return engine                      # sqlite has no session timezone
    if getattr(sync_engine, _UTC_PINNED, False):
        return engine

    @_event.listens_for(sync_engine, "connect")
    def _set_utc(dbapi_conn, _record):
        try:
            actual = _confirm_utc(dbapi_conn)
        except Exception as exc:
            raise SessionTimezoneNotPinned(
                "could not pin this Postgres session to UTC; refusing the "
                "connection rather than letting freshness and idempotency "
                "comparisons run against an unknown clock") from exc
        if str(actual).upper() != "UTC":
            raise SessionTimezoneNotPinned(
                f"session timezone is {actual!r} after being set to UTC; "
                f"refusing the connection")

    setattr(sync_engine, _UTC_PINNED, True)
    return engine


def fix_sqlite_savepoints(engine):
    """Make SAVEPOINT mean savepoint on sqlite. Returns `engine`.

    pysqlite (and aiosqlite wrapping it) never emits BEGIN before SAVEPOINT —
    it only autobegins before DML — so releasing the OUTERMOST savepoint
    commits it as its own transaction. Found the hard way: `claim_commit`'s
    `begin_nested()` at the start of a fresh transaction left a DURABLE
    MealCommit row while the food that followed rolled back — food without an
    authoritative claim-to-rows pairing, the exact state the coordinator
    exists to make impossible, manufactured by the test driver itself.

    This is the workaround the SQLAlchemy docs prescribe: take over
    transaction control from the driver (isolation_level=None) and emit BEGIN
    ourselves. Postgres needs none of this; the guard is dialect-keyed like
    the UTC pin above.
    """
    sync_engine = getattr(engine, "sync_engine", engine)
    if sync_engine.dialect.name != "sqlite":
        return engine
    if getattr(sync_engine, "_arnie_savepoints_fixed", False):
        return engine

    @_event.listens_for(sync_engine, "connect")
    def _driver_level_autocommit(dbapi_conn, _record):
        # ON THE ADAPTER, exactly as the SQLAlchemy docs prescribe — it
        # marshals the assignment to the driver's worker thread. Reaching
        # through to the inner aiosqlite connection touches sqlite3 from the
        # wrong thread and raises ProgrammingError on first use. Measured, not
        # assumed: bare engine leaks savepoint contents through a crash; this
        # recipe leaves nothing; the reach-in variant cannot connect at all.
        dbapi_conn.isolation_level = None
        # WAL + busy_timeout travel WITH the engine, not just the app's
        # module-level one. Without WAL a file database runs DELETE-journal,
        # where any open READ transaction blocks every writer — so a test
        # fixture holding a read snapshot deadlocks the very session under
        # test, and "database is locked" reads as a concurrency bug in the
        # code being tested rather than a missing pragma in the harness.
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

    @_event.listens_for(sync_engine, "begin")
    def _emit_begin(conn):
        # No try/except. With driver-level transaction handling off there is
        # no implicit BEGIN to collide with, and a collision that somehow
        # happens anyway is a state bug that must surface, not be papered
        # over with a blind ROLLBACK that swallows the original error.
        #
        # DEFERRED, deliberately, after measuring IMMEDIATE. Taking the write
        # lock at BEGIN reads as the safer choice and self-deadlocks twice
        # over: a handler that nests a second session waits 30s on its own
        # outer transaction, and a fixture session holding a "read" then
        # blocks the very writer under test. Engines built here do not run
        # concurrent sqlite writers — concurrency truth lives in the Postgres
        # suites — so deferred plus WAL is exactly enough.
        conn.exec_driver_sql("BEGIN")

    sync_engine._arnie_savepoints_fixed = True
    return engine


def make_engine(url: str, **kwargs):
    """The one way to build an engine. Production, tests and scripts all use
    this, so the UTC guarantee — and honest savepoints on sqlite — cannot be
    missed by construction."""
    return fix_sqlite_savepoints(pin_session_utc(create_async_engine(url, **kwargs)))


@_event.listens_for(_Engine, "engine_connect")
def _refuse_unpinned_postgres(conn):
    """FAIL CLOSED for a Postgres engine nobody pinned.

    `pin_session_utc` covers engines built through the factory. This covers the
    engine somebody builds directly — in a test, a script, a migration — which
    would otherwise run with the server's timezone and reintroduce the whole
    defect silently.

    An in-process attribute check, not a query: it costs nothing per checkout,
    and a round trip here would be paid on every transaction. `conn.engine` is
    public API and carries the real dialect, which is what the connect event
    does not.
    """
    if conn.engine.dialect.name != "postgresql":
        return
    if not getattr(conn.engine, _UTC_PINNED, False):
        raise SessionTimezoneNotPinned(
            "this Postgres engine was never pinned to UTC — build it with "
            "db.database.make_engine(), or call pin_session_utc(engine). "
            "Running unpinned would make every freshness comparison depend on "
            "the database server's timezone (see docs/ONE_CLOCK_MIGRATION.md)")


# The application's own engine goes through the same gate as everything
# else — without this the guard above would refuse it, which is exactly the
# behaviour intended for an unpinned Postgres engine.
#
# ⛔⛔ AND THE SAVEPOINT FIX TOO. This line applied `pin_session_utc` ALONE,
# while `make_engine` applies BOTH — so the application's own engine was the
# one place `fix_sqlite_savepoints` did not reach. On SQLite that is not
# cosmetic: it is the documented failure in that function's own docstring —
# `claim_commit`'s `begin_nested()` releases as its OWN transaction, leaving a
# DURABLE MealCommit while the food that follows rolls back. Food without an
# authoritative claim-to-rows pairing, manufactured by the engine construction.
#
# Measured 2026-08-16: a settlement whose execution view could not be built
# rolled back its FoodEntry and left its MealCommit behind — on this engine,
# and not on one built through `make_engine`. The fix already existed; only
# this construction path was skipping it.
fix_sqlite_savepoints(pin_session_utc(engine))

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    from db import models  # noqa: F401 — import triggers model registration

    # Postgres: Alembic owns the schema. The app must NOT create_all or run the
    # hand-rolled _migrate() — migrations are applied out-of-band (`alembic upgrade
    # head`, wired into the Render start command). Doing create_all here would race
    # Alembic and bypass version tracking.
    if not _IS_SQLITE:
        logger.info("Postgres detected — schema managed by Alembic, skipping create_all/_migrate.")
        # Startup probe: confirm we can connect AND the schema is present. If the
        # `users` table is missing, the DB is a fresh/empty Postgres and `alembic
        # upgrade head` never ran — every real query would 500. Fail loud and clear
        # here instead of leaving cryptic per-request errors. Also stamps the live
        # connection so it's visible in boot logs (answers "are we really on PG?").
        from sqlalchemy import text
        try:
            async with engine.connect() as conn:
                ver = (await conn.execute(text("SELECT version()"))).scalar()
                has_users = (await conn.execute(text(
                    "SELECT to_regclass('public.users')"
                ))).scalar()
                rev = (await conn.execute(text(
                    "SELECT version_num FROM alembic_version"
                ))).scalar() if has_users else None
            short = (ver or "")[:40]
            if has_users:
                logger.info(f"Postgres OK — connected ({short}...), alembic_version={rev}, schema present.")
            else:
                # Fail loud AND hard: a started-but-schemaless app looks healthy to the
                # load balancer while every real request 500s. Crash so the bad deploy is
                # visible and rolls back, instead of silently serving a dead app.
                raise RuntimeError(
                    "Postgres CONNECTED but EMPTY — the 'users' table is missing. "
                    "`alembic upgrade head` did not run (Render Pre-Deploy Command or "
                    "service Shell). Refusing to start."
                )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Postgres connectivity check FAILED: {e}. Verify DATABASE_URL points "
                f"at the running Render Postgres (internal connection string)."
            ) from e
        return

    # SQLite (local dev + in-memory tests): keep the existing create_all + inline
    # migration path so nothing local changes. SQLAlchemy create_all() doesn't add
    # columns to existing tables, hence _migrate()'s ALTER list + auto-heal net.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


async def _migrate(conn):
    """Add columns that were introduced after the initial schema."""
    from sqlalchemy import text

    # Each entry: (table_name, column_name, column_ddl)
    additions = [
        # ── original schema additions ──────────────────────────────────────────
        ("users", "webhook_token", "VARCHAR"),
        ("users", "whoop_access_token", "TEXT"),
        ("users", "whoop_refresh_token", "TEXT"),
        ("users", "whoop_token_expires_at", "DATETIME"),
        ("users", "whoop_user_id", "VARCHAR"),
        ("users", "oura_access_token", "TEXT"),
        ("users", "oura_refresh_token", "TEXT"),
        ("users", "oura_token_expires_at", "DATETIME"),
        ("conversation_logs", "feedback", "TEXT"),
        ("conversation_logs", "reasoning_json", "TEXT"),
        ("conversation_logs", "superseded_by", "INTEGER"),
        ("conversation_logs", "turn_id", "VARCHAR"),
        ("health_snapshots", "recovery_score", "INTEGER"),
        ("health_snapshots", "strain", "FLOAT"),
        ("health_snapshots", "skin_temp_celsius", "FLOAT"),
        ("health_snapshots", "spo2_percentage", "FLOAT"),
        ("user_preferences", "preferred_language", "VARCHAR"),
        ("user_preferences", "coach_layout", "TEXT"),
        ("users", "subscription_status", "VARCHAR DEFAULT 'trial'"),
        ("users", "stripe_customer_id", "VARCHAR"),
        ("users", "trial_ends_at", "DATETIME"),
        ("users", "subscription_ends_at", "DATETIME"),
        # ── 2026-05-29: architecture refactor additions ────────────────────────
        ("users", "city", "VARCHAR"),
        ("users", "channel_preference", "VARCHAR"),
        ("users", "sport", "VARCHAR"),
        ("users", "units_preference", "VARCHAR DEFAULT 'imperial'"),
        ("users", "nudges_sent", "TEXT DEFAULT ''"),
        ("users", "whoop_last_notified", "VARCHAR"),
        ("users", "weekly_recap_week", "VARCHAR"),
        ("users", "linked_to_user_id", "INTEGER"),
        ("users", "link_code", "VARCHAR"),
        ("users", "link_code_expires", "DATETIME"),
        ("users", "active_mission", "VARCHAR"),
        ("users", "mission_metric", "VARCHAR"),
        ("users", "mission_target", "FLOAT"),
        ("users", "mission_date", "VARCHAR"),
        ("conversation_logs", "platform", "VARCHAR DEFAULT 'telegram'"),
        ("conversation_logs", "skills_fired", "VARCHAR"),
        # ── 2026-06-04: dynamic user-profile system ────────────────────────────
        ("users", "user_bio", "TEXT"),
        ("users", "user_bio_updated_at", "DATETIME"),
        # ── 2026-06-16: per-set variable load ──────────────────────────────────
        ("exercise_entries", "weights", "VARCHAR"),
        # ── 2026-06-20: persist typed inline cards for native history restore ───
        ("conversation_logs", "cards_json", "TEXT"),
        # ── 2026-06-24: workout time-of-day + wearable auto-log dedup ───────────
        ("exercise_entries", "occurred_at", "DATETIME"),
        ("exercise_entries", "source_ref", "VARCHAR"),
        # ── 2026-06-25: wearable session avg heart rate ────────────────────────
        ("exercise_entries", "avg_hr", "INTEGER"),
        # ── 2026-06-26: per-send idempotency key (deterministic retry dedup) ────
        ("conversation_logs", "idempotency_key", "VARCHAR"),
        # ── 2026-06-27: weight source (manual vs apple_health) for source-aware
        #    per-(user, day, source) dedup. SQLite-only net — Postgres is handled
        #    by the paired alembic migration b3c4d5e6f7a8 (per migrate_postgres_gap).
        ("body_metrics", "source", "VARCHAR DEFAULT 'manual'"),
        # ── 2026-06-30: cache the per-100g micronutrient panel so repeat-logged
        #    foods keep their micros (memory hits used to drop them). SQLite-only
        #    net — Postgres handled by paired alembic migration f7a8b9c0d1e2.
        ("user_food_matches", "micros_100_json", "TEXT"),
        # ── 2026-06-30: flag LLM-estimated micros (gap foods) vs measured (USDA).
        #    Paired alembic migration a9b0c1d2e3f4.
        ("food_entries", "micros_estimated", "BOOLEAN DEFAULT 0"),
        # ── 2026-06-30: free-form onboarding "brain dump" (user's own words).
        #    SQLite-only net — Postgres handled by paired alembic migration c0d1e2f3a4b5.
        ("users", "brain_dump", "TEXT"),
        # ── 2026-07-03: NOVA-style processing class from the model at log time,
        #    preferred over the health score's keyword proxy. SQLite-only net —
        #    Postgres handled by paired alembic migration e2f3a4b5c6d7.
        ("food_entries", "processing_level", "VARCHAR"),
        # ── P17f pricing receipt (paired with alembic prodev001) ──────────────
        ("food_entries", "pricing_rung", "VARCHAR"),
        ("food_entries", "nutrition_evidence_id", "VARCHAR"),
        ("food_entries", "source_basis", "VARCHAR"),
        ("food_entries", "basis_evidence_id", "VARCHAR"),
        ("food_entries", "conversion_evidence_ids_json", "TEXT"),
        ("food_entries", "source_amount", "FLOAT"),
        ("food_entries", "source_unit", "VARCHAR"),
        ("food_entries", "scaling_factor", "FLOAT"),
        ("food_entries", "product_evidence_id", "INTEGER"),
        # ── 2026-07-17: activation gates — when the user earned the Log/Coach
        #    tabs (null = locked). SQLite-only net — Postgres handled by paired
        #    alembic migration e7750abe4362 (which also grandfathers existing users).
        ("users", "log_unlocked_at", "DATETIME"),
        ("users", "coach_unlocked_at", "DATETIME"),
        # ── 2026-07-25: which authority tier first produced a cached food
        #    profile, so a cache of our own generic answer stops re-entering as
        #    a user-confirmed regular. SQLite-only net — Postgres handled by
        #    paired alembic migration 9c814ca1d70d.
        ("user_food_matches", "origin_tier", "VARCHAR"),
    ]

    for table, column, ddl in additions:
        try:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing_cols = {row[1] for row in result.fetchall()}
            if column not in existing_cols:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                logger.info(f"Migration: added {table}.{column}")
        except Exception as e:
            logger.warning(f"Migration check for {table}.{column} failed: {e}")

    # ── Auto-heal safety net ────────────────────────────────────────────────────
    # Any column defined on a model but missing from the DB (e.g. a new column whose
    # explicit migration entry above was forgotten) is added here automatically.
    # This prevents a missing migration from bricking ALL queries against a table —
    # which is exactly what would otherwise take the whole bot offline. SQLite ADD
    # COLUMN is cheap and nullable by default, so this is safe.
    try:
        from db import models  # ensure models are imported / mapped
        _SA_TO_SQLITE = {
            "INTEGER": "INTEGER", "BIGINT": "INTEGER", "SMALLINT": "INTEGER",
            "FLOAT": "FLOAT", "NUMERIC": "FLOAT", "REAL": "FLOAT",
            "BOOLEAN": "BOOLEAN", "DATETIME": "DATETIME", "DATE": "DATE",
            "TEXT": "TEXT", "VARCHAR": "VARCHAR",
        }
        for tbl in Base.metadata.sorted_tables:
            try:
                res = await conn.execute(text(f"PRAGMA table_info({tbl.name})"))
                rows = res.fetchall()
                if not rows:
                    continue  # table created fresh by create_all — already complete
                existing = {r[1] for r in rows}
                for col in tbl.columns:
                    if col.name in existing:
                        continue
                    # Map the SQLAlchemy type to a SQLite-friendly DDL type
                    try:
                        type_str = col.type.compile(dialect=conn.dialect)
                    except Exception:
                        type_str = str(col.type)
                    base = type_str.split("(")[0].strip().upper()
                    sqlite_type = _SA_TO_SQLITE.get(base, "VARCHAR")
                    await conn.execute(
                        text(f"ALTER TABLE {tbl.name} ADD COLUMN {col.name} {sqlite_type}")
                    )
                    logger.warning(
                        f"Migration auto-heal: added missing column {tbl.name}.{col.name} "
                        f"({sqlite_type}) — add it to the explicit migration list."
                    )
            except Exception as e:
                logger.warning(f"Auto-heal scan for table {tbl.name} failed: {e}")
    except Exception as e:
        logger.warning(f"Migration auto-heal pass failed: {e}")

    # ── Data migrations ────────────────────────────────────────────────────────
    # Enable proactive messaging for all existing users who have it off
    try:
        result = await conn.execute(
            text("UPDATE user_preferences SET proactive_messaging_enabled = 1 "
                 "WHERE proactive_messaging_enabled = 0 OR proactive_messaging_enabled IS NULL")
        )
        if result.rowcount:
            logger.info(f"Migration: enabled proactive messaging for {result.rowcount} users")
    except Exception as e:
        logger.warning(f"Migration: proactive messaging update failed: {e}")

    # ── One-time backfill (2026-05-30): EST + reminders for active users ─────────
    # Runs ONCE, guarded by a marker row in schema_meta. Sets a real timezone +
    # enables reminders for everyone who has actually talked to Arnie, so the
    # 9am-9pm proactive window works for them. New signups set their own tz via
    # onboarding, so this must never re-run on future boots.
    try:
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY)"
        ))
        _marker = "est_backfill_2026_05_30"
        _done = (await conn.execute(
            text("SELECT 1 FROM schema_meta WHERE key = :k"), {"k": _marker}
        )).first()
        if _done:
            logger.info("Backfill est_backfill_2026_05_30 already applied — skipping.")
        else:
            # (B) Active users still on the UTC default → EST (don't clobber real tz)
            try:
                r = await conn.execute(text(
                    "UPDATE users SET timezone = 'America/New_York' "
                    "WHERE (timezone IS NULL OR timezone = 'UTC') "
                    "AND id IN (SELECT DISTINCT user_id FROM conversation_logs "
                    "           WHERE user_id IS NOT NULL)"
                ))
                logger.info(f"Backfill: set EST timezone for {r.rowcount} active users")
            except Exception as e:
                logger.warning(f"Backfill (timezone) failed: {e}")

            # (C) Enable reminders for everyone who has messaged Arnie
            try:
                r = await conn.execute(text(
                    "UPDATE user_preferences SET proactive_messaging_enabled = 1 "
                    "WHERE user_id IN (SELECT DISTINCT user_id FROM conversation_logs "
                    "                  WHERE user_id IS NOT NULL)"
                ))
                logger.info(f"Backfill: enabled reminders for {r.rowcount} active users")
            except Exception as e:
                logger.warning(f"Backfill (reminders) failed: {e}")

            # (D) Exception LAST — +380503675704 is in Ukraine, not EST.
            try:
                r = await conn.execute(text(
                    "UPDATE users SET timezone = 'Europe/Kyiv', city = 'Kyiv' "
                    "WHERE telegram_id LIKE '%380503675704%'"
                ))
                logger.info(f"Backfill: set Kyiv tz/city for {r.rowcount} row(s) (+380503675704)")
            except Exception as e:
                logger.warning(f"Backfill (Kyiv override) failed: {e}")

            await conn.execute(
                text("INSERT INTO schema_meta (key) VALUES (:k)"), {"k": _marker}
            )
            logger.info("Backfill est_backfill_2026_05_30 applied + marked.")
    except Exception as e:
        logger.warning(f"Backfill est_backfill_2026_05_30 pass failed: {e}")

    # ── One-time reconcile: heal drifted DailyLog totals (2026-05-30) ────────────
    # Historic add/update/delete used incremental delta math, so a partial write
    # or mid-write crash (e.g. the channel_preference outage) could leave a day's
    # stored total_* out of sync with its actual food entries — the dashboard then
    # showed a wrong number. Recompute every day's totals from the entry sums so
    # logs and dashboard match. Idempotent; guarded by its own marker.
    try:
        _rk = "totals_reconcile_2026_05_30"
        _rdone = (await conn.execute(
            text("SELECT 1 FROM schema_meta WHERE key = :k"), {"k": _rk}
        )).first()
        if not _rdone:
            r = await conn.execute(text(
                "UPDATE daily_logs SET "
                "  total_calories = COALESCE((SELECT SUM(calories) FROM food_entries "
                "                             WHERE food_entries.daily_log_id = daily_logs.id), 0), "
                "  total_protein  = COALESCE((SELECT SUM(protein)  FROM food_entries "
                "                             WHERE food_entries.daily_log_id = daily_logs.id), 0), "
                "  total_carbs    = COALESCE((SELECT SUM(carbs)    FROM food_entries "
                "                             WHERE food_entries.daily_log_id = daily_logs.id), 0), "
                "  total_fats     = COALESCE((SELECT SUM(fats)     FROM food_entries "
                "                             WHERE food_entries.daily_log_id = daily_logs.id), 0)"
            ))
            logger.info(f"Reconcile: recomputed food totals for {r.rowcount} daily logs")
            # Heal workout/cardio flags too — delete_exercise_entry historically
            # never unset them, so days can show 'workout done' with no exercises.
            # Cardio = has a cardio_type OR is duration-only (time, no sets).
            # Matches recompute_log_totals._is_cardio so app + migration agree.
            _is_cardio = ("(cardio_type IS NOT NULL AND cardio_type != '') "
                          "OR (duration_minutes IS NOT NULL AND sets IS NULL)")
            r2 = await conn.execute(text(
                "UPDATE daily_logs SET "
                f"  cardio_completed = CASE WHEN EXISTS (SELECT 1 FROM exercise_entries "
                f"       WHERE exercise_entries.daily_log_id = daily_logs.id "
                f"       AND ({_is_cardio})) THEN 1 ELSE 0 END, "
                f"  workout_completed = CASE WHEN EXISTS (SELECT 1 FROM exercise_entries "
                f"       WHERE exercise_entries.daily_log_id = daily_logs.id "
                f"       AND NOT ({_is_cardio})) THEN 1 ELSE 0 END"
            ))
            logger.info(f"Reconcile: recomputed workout/cardio flags for {r2.rowcount} daily logs")
            await conn.execute(
                text("INSERT INTO schema_meta (key) VALUES (:k)"), {"k": _rk}
            )
    except Exception as e:
        logger.warning(f"Reconcile totals_reconcile_2026_05_30 failed: {e}")

    # ── Unique (user_id, date) on daily_logs + health_snapshots (2026-06-20) ─────
    # Postgres gets this via Alembic (c1d2e3f4a5b6); this is the SQLite parity for
    # existing local/test DBs (fresh ones already have it from create_all's
    # __table_args__). Dedup first — CREATE UNIQUE INDEX fails if duplicates exist.
    # The constraint stops the get_or_create_today_log / upsert_health_snapshot
    # check-then-insert race from ever producing two rows for the same day again
    # (incident 2026-06-20). Guarded by IF NOT EXISTS, so it's a no-op once present.
    try:
        # daily_logs: keep the lowest id per (user_id, date), reparent children.
        dup_groups = (await conn.execute(text(
            "SELECT user_id, date, MIN(id) AS survivor FROM daily_logs "
            "GROUP BY user_id, date HAVING COUNT(*) > 1"
        ))).fetchall()
        for user_id, day, survivor in dup_groups:
            dup_ids = (await conn.execute(text(
                "SELECT id FROM daily_logs WHERE user_id = :u AND date = :d AND id <> :s"
            ), {"u": user_id, "d": day, "s": survivor})).scalars().all()
            for dup in dup_ids:
                for tbl in ("food_entries", "exercise_entries", "water_entries"):
                    await conn.execute(text(
                        f"UPDATE {tbl} SET daily_log_id = :s WHERE daily_log_id = :d"
                    ), {"s": survivor, "d": dup})
                await conn.execute(text("DELETE FROM daily_logs WHERE id = :d"), {"d": dup})
        # health_snapshots: no children — drop all but the lowest id per group.
        await conn.execute(text(
            "DELETE FROM health_snapshots WHERE id NOT IN "
            "(SELECT MIN(id) FROM health_snapshots GROUP BY user_id, date)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_log_user_date "
            "ON daily_logs (user_id, date)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_health_snapshot_user_date "
            "ON health_snapshots (user_id, date)"
        ))
        logger.info("Migration: ensured unique (user_id, date) on daily_logs + health_snapshots")
    except Exception as e:
        logger.warning(f"Migration: unique (user_id, date) constraint pass failed: {e}")
