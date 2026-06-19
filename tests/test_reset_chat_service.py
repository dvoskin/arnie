"""
Regression tests for the iOS / web / iMessage chat-service path now
intercepting /reset slash commands the same way bot/telegram_handler does.

Background: prior to 2026-06-18, iOS users typing "/reset all confirm" hit the
LLM (which refused). The slash-command parser lived only in the Telegram
handler. This test pins the new behavior:

  • parse_reset_command tolerates case + whitespace
  • run_chat_turn intercepts BEFORE calling the LLM (no LLM key needed)
  • /reset today wipes only TODAY's conversations, not the entire history
"""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta

from sqlalchemy import event, select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.database import Base, _migrate
from db import models  # noqa: F401
from db.models import User, UserPreferences, ConversationLog
from db.queries import clear_today_conversations, log_conversation
from core.reset import parse_reset_command
from core.chat_service import run_chat_turn


@pytest_asyncio.fixture
async def fk_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(eng.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(fk_engine):
    Session = async_sessionmaker(fk_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest_asyncio.fixture
async def user(db):
    u = User(telegram_id="999", name="Test", timezone="UTC",
             onboarding_completed=True)
    db.add(u)
    db.add(UserPreferences(user=u))
    await db.commit()
    await db.refresh(u)
    return u


def test_parse_reset_command_basic_forms():
    assert parse_reset_command("/reset") == ("help", False)
    assert parse_reset_command("/reset today") == ("today", False)
    assert parse_reset_command("/reset all") == ("all", False)
    assert parse_reset_command("/reset all confirm") == ("all", True)
    assert parse_reset_command("hi there") == (None, False)
    assert parse_reset_command("") == (None, False)


def test_parse_reset_command_tolerates_case_and_whitespace():
    assert parse_reset_command("  /Reset Today ") == ("today", False)
    assert parse_reset_command("/RESET ALL CONFIRM") == ("all", True)
    assert parse_reset_command("/reset garbage") == ("help", False)


@pytest.mark.asyncio
async def test_clear_today_conversations_scopes_to_today(db, user):
    """clear_today_conversations used to wipe ALL history. It must now only
    delete rows whose timestamp falls inside the user's local calendar day."""
    yesterday = datetime.utcnow() - timedelta(days=2)
    db.add(ConversationLog(
        user_id=user.id, raw_message="old", response="old reply",
        timestamp=yesterday,
    ))
    db.add(ConversationLog(
        user_id=user.id, raw_message="today", response="today reply",
    ))
    await db.commit()

    await clear_today_conversations(db, user.id, "UTC")

    rows = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == user.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].raw_message == "old"


@pytest.mark.asyncio
async def test_run_chat_turn_intercepts_reset_help_without_llm(db, user):
    """/reset (no args) must short-circuit BEFORE the LLM call — proves it by
    succeeding without any LLM credentials set."""
    turn = await run_chat_turn(
        db, user, "/reset",
        platform="ios", source_type="ios",
        schedule_background=False,
    )
    text = " ".join(turn.response.bubbles).lower()
    assert "/reset today" in text
    assert "/reset all confirm" in text
    assert turn.tool_calls == []


@pytest.mark.asyncio
async def test_run_chat_turn_intercepts_reset_all_unconfirmed(db, user):
    """/reset all (no confirm) must warn and require explicit confirm."""
    turn = await run_chat_turn(
        db, user, "/reset all",
        platform="ios", source_type="ios",
        schedule_background=False,
    )
    text = " ".join(turn.response.bubbles).lower()
    assert "confirm" in text
    assert "wipe" in text or "delete" in text


@pytest.mark.asyncio
async def test_run_chat_turn_intercepts_reset_today_and_clears(db, user):
    """/reset today writes a non-LLM reply AND scopes the conversation wipe
    to today (the prior conversation row from yesterday survives)."""
    yesterday = datetime.utcnow() - timedelta(days=2)
    db.add(ConversationLog(
        user_id=user.id, raw_message="old", response="old reply",
        timestamp=yesterday,
    ))
    await db.commit()

    turn = await run_chat_turn(
        db, user, "/reset today",
        platform="ios", source_type="ios",
        schedule_background=False,
    )
    text = " ".join(turn.response.bubbles).lower()
    assert "nothing logged" in text or "cleared" in text

    surviving = (await db.execute(
        select(ConversationLog).where(
            ConversationLog.user_id == user.id,
            ConversationLog.raw_message == "old",
        )
    )).scalars().first()
    assert surviving is not None, (
        "yesterday's conversation should survive /reset today"
    )


@pytest.mark.asyncio
async def test_log_conversation_tags_platform_from_chat_service(db, user):
    """Was a bug: chat_service called log_conversation without platform=, so
    every iOS row landed with platform='telegram' (model default). The reset
    interception is now the simplest place to assert the tag flows through."""
    await run_chat_turn(
        db, user, "/reset",
        platform="ios", source_type="ios",
        schedule_background=False,
    )
    row = (await db.execute(
        select(ConversationLog)
        .where(ConversationLog.user_id == user.id)
        .order_by(ConversationLog.id.desc())
    )).scalars().first()
    assert row is not None
    assert row.platform == "ios"
    assert row.source_type == "ios"
