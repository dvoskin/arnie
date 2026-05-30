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
        ("users", "sport", "VARCHAR"),
        ("users", "units_preference", "VARCHAR DEFAULT 'imperial'"),
        ("users", "nudges_sent", "TEXT DEFAULT ''"),
        ("users", "whoop_last_notified", "VARCHAR"),
        ("users", "weekly_recap_week", "VARCHAR"),
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
