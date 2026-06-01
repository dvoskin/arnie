"""Alembic environment — wired to the app's models and DATABASE_URL.

Alembic runs with a SYNC engine. The app uses async drivers (aiosqlite / psycopg),
so we coerce the URL to its sync equivalent here:
  - sqlite+aiosqlite://  -> sqlite://        (pysqlite, the stdlib sync driver)
  - postgresql+asyncpg:// -> postgresql+psycopg://  (psycopg3 is sync AND async)
  - postgresql+psycopg:// -> unchanged       (already sync-capable)

DATABASE_URL is read from the environment so the same migrations run locally and on
Render. Falls back to the app's default SQLite path when unset.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the app package importable when alembic is invoked from the repo root.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# App metadata — single source of truth for the schema.
from db.database import Base  # noqa: E402
from db import models  # noqa: E402,F401  (import registers all tables on Base)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    """Resolve DATABASE_URL and coerce async drivers to their sync equivalents."""
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///arnie.db")
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return url


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    url = _sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=_is_sqlite(url),  # SQLite needs batch mode for ALTERs
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _sync_url()
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_is_sqlite(url),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
