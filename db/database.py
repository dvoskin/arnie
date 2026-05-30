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
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    from db import models  # noqa: F401 — import triggers model registration
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Inline migrations: ALTER TABLE for columns added after initial schema.
        # SQLAlchemy create_all() doesn't add columns to existing tables.
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
        ("health_snapshots", "recovery_score", "INTEGER"),
        ("health_snapshots", "strain", "FLOAT"),
        ("health_snapshots", "skin_temp_celsius", "FLOAT"),
        ("health_snapshots", "spo2_percentage", "FLOAT"),
        ("user_preferences", "preferred_language", "VARCHAR"),
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
            r2 = await conn.execute(text(
                "UPDATE daily_logs SET "
                "  cardio_completed = CASE WHEN EXISTS (SELECT 1 FROM exercise_entries "
                "       WHERE exercise_entries.daily_log_id = daily_logs.id "
                "       AND cardio_type IS NOT NULL AND cardio_type != '') THEN 1 ELSE 0 END, "
                "  workout_completed = CASE WHEN EXISTS (SELECT 1 FROM exercise_entries "
                "       WHERE exercise_entries.daily_log_id = daily_logs.id "
                "       AND (cardio_type IS NULL OR cardio_type = '')) THEN 1 ELSE 0 END"
            ))
            logger.info(f"Reconcile: recomputed workout/cardio flags for {r2.rowcount} daily logs")
            await conn.execute(
                text("INSERT INTO schema_meta (key) VALUES (:k)"), {"k": _rk}
            )
    except Exception as e:
        logger.warning(f"Reconcile totals_reconcile_2026_05_30 failed: {e}")
