import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///arnie.db")

# Ensure the directory for the SQLite file exists before the engine connects
def _ensure_db_dir():
    url = DATABASE_URL
    # sqlite+aiosqlite:////data/arnie.db  →  /data/arnie.db
    if "sqlite" in url:
        path_part = url.split("///")[-1]
        if path_part.startswith("/"):
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)

_ensure_db_dir()

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    from db import models  # noqa: F401 — import triggers model registration
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
