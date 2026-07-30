"""Every persisted turn names the build and flags that produced it.

Three audits in a row spent their first hour inferring the deployed SHA from
behavioural markers because deploys are manual and nothing recorded them.
`/health` says what runs NOW; only the turn can say what ran WHEN. This is the
master directive's Phase 1.1 ("confirm the exact deployed SHA and runtime
flags") made permanent: coverage-by-SHA and mixed-deployment windows become one
query over `reasoning_json`.

Through the real boundary: `log_conversation` against a database, read back.
"""
import json

import pytest
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

import db.queries as Q
from db.models import Base, ConversationLog, User


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        u = User(telegram_id="build-stamp-test")
        s.add(u)
        await s.commit()
        yield s, u.id
    await engine.dispose()


async def _log(db, uid, reasoning):
    await Q.log_conversation(db, uid, "test msg", "chat", "reply",
                             source_type="ios", reasoning=reasoning)
    row = (await db.execute(
        ConversationLog.__table__.select().where(
            ConversationLog.user_id == uid))).mappings().first()
    return json.loads(row["reasoning_json"])


@pytest.mark.anyio
async def test_a_persisted_turn_carries_sha_and_flags(session, monkeypatch):
    db, uid = session
    monkeypatch.setattr(Q, "_BUILD_STAMP_CACHE", None)
    monkeypatch.setenv("RENDER_GIT_COMMIT",
                       "abcdef1234567890deadbeef")
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")
    monkeypatch.delenv("FOOD_GATE_OPEN", raising=False)

    stored = await _log(db, uid, {"duration_ms": 1234, "route": {"lane": "x"}})
    assert stored["build"]["sha"] == "abcdef123456"          # 12 chars
    assert stored["build"]["flags"]["FOOD_GATE_MODEL"] == "true"
    # unset stays None — "unset" and "false" must remain distinguishable
    assert stored["build"]["flags"]["FOOD_GATE_OPEN"] is None
    # the caller's own reasoning survives beside it
    assert stored["duration_ms"] == 1234
    assert stored["route"] == {"lane": "x"}


@pytest.mark.anyio
async def test_without_render_the_stamp_says_local_not_a_guess(session,
                                                               monkeypatch):
    """A dev checkout's HEAD is not a deployment; the stamp must not invent
    one from git state."""
    db, uid = session
    monkeypatch.setattr(Q, "_BUILD_STAMP_CACHE", None)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    stored = await _log(db, uid, {"route": {"lane": "y"}})
    assert stored["build"]["sha"] == "local"


@pytest.mark.anyio
async def test_the_callers_reasoning_dict_is_not_mutated(session, monkeypatch):
    db, uid = session
    monkeypatch.setattr(Q, "_BUILD_STAMP_CACHE", None)
    reasoning = {"steps": [1, 2]}
    await _log(db, uid, reasoning)
    assert reasoning == {"steps": [1, 2]}, "caller's dict grew a build key"
