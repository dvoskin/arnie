"""Migration safety: _migrate adds new columns, heals an old schema, and is
idempotent — the area that took the bot fully offline this session."""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from db.database import Base, _migrate
from db import models  # noqa: F401


async def _cols(conn, table):
    res = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {r[1] for r in res.fetchall()}


async def test_migrate_adds_recent_columns():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await _migrate(c)
        cols = await _cols(c, "users")
        for col in ("city", "channel_preference", "timezone", "linked_to_user_id"):
            assert col in cols, col
    await eng.dispose()


async def test_auto_heal_adds_missing_column_on_old_schema():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        # Old-style minimal users table missing city + channel_preference
        await c.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id VARCHAR, "
            "name VARCHAR, timezone VARCHAR)"))
        await c.execute(text("CREATE TABLE user_preferences (id INTEGER PRIMARY KEY, "
                             "proactive_messaging_enabled INTEGER)"))
        await c.execute(text("CREATE TABLE conversation_logs (id INTEGER PRIMARY KEY)"))
        await c.execute(text("CREATE TABLE health_snapshots (id INTEGER PRIMARY KEY)"))
        await c.execute(text("INSERT INTO users (telegram_id, name) VALUES ('1','Danny')"))
        await _migrate(c)
        cols = await _cols(c, "users")
        assert "city" in cols and "channel_preference" in cols
        # the query that crashed prod must now work
        row = (await c.execute(text(
            "SELECT id, city, channel_preference FROM users WHERE telegram_id='1'"))).fetchall()
        assert len(row) == 1
    await eng.dispose()


async def test_migrate_idempotent():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await _migrate(c)
        await _migrate(c)  # second run must not raise
        assert "city" in await _cols(c, "users")
    await eng.dispose()
