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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
