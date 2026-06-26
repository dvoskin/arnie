"""
Regression tests for run_chat_turn's double-fire idempotency collapse.

Background: the iOS client can resubmit the SAME message (double-tap, or an
auto-retry after a slow/errored turn). The original guard collapsed a verbatim
repeat ONLY when the prior turn fired no tools — so a resent LOG message re-ran
and could double-write (observed 2026-06-25: shrugs "3×14,14,15" logged twice on
user 26 when "Got 15, doing upright rows now" arrived 8s apart). These tests pin
the tightened behavior:

  • no-tools repeat within the window     → collapse (unchanged)
  • tool-firing SUBSTANTIAL phrase, tight window → collapse (the fix)
  • tool-firing SHORT set-entry ("130x12")       → DO NOT collapse (logs again)
  • repeat that lands on an ERROR reply          → DO NOT collapse (must retry)

The collapse runs BEFORE build_context/run_turn, so we prove "did not collapse"
by monkeypatching run_turn to raise — reaching it means no collapse happened.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.database import Base, _migrate
from db import models  # noqa: F401
from db.models import User, UserPreferences, ConversationLog
import core.chat_service as cs
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
    u = User(telegram_id="ios:test", name="Test", timezone="UTC",
             onboarding_completed=True)
    db.add(u)
    db.add(UserPreferences(user=u))
    await db.commit()
    await db.refresh(u)
    return u


class _ReachedRunTurn(Exception):
    """Raised by the patched run_turn to prove the turn did NOT collapse."""


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    async def _boom(*a, **k):
        raise _ReachedRunTurn()

    async def _ctx(*a, **k):
        return ""

    monkeypatch.setattr(cs, "run_turn", _boom)
    monkeypatch.setattr(cs, "build_context", _ctx)
    monkeypatch.setattr(cs, "build_arnie_system", lambda *a, **k: "")


async def _seed_prior(db, user, *, text, response, skills, age_sec):
    db.add(ConversationLog(
        user_id=user.id, raw_message=text, response=response,
        skills_fired=skills, platform="ios", source_type="ios",
        timestamp=datetime.utcnow() - timedelta(seconds=age_sec),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_collapse_no_tools_repeat(db, user):
    """Original behavior: a no-tools informational reply collapses on repeat."""
    await _seed_prior(db, user, text="tell me more",
                      response="Here's the deep dive.", skills="", age_sec=3)
    turn = await run_chat_turn(db, user, "tell me more",
                               platform="ios", source_type="ios",
                               schedule_background=False)
    assert turn.tool_calls == []
    assert "deep dive" in " ".join(turn.response.bubbles).lower()


@pytest.mark.asyncio
async def test_collapse_tool_firing_substantial_phrase(db, user):
    """The fix: a verbatim substantial phrase that fired a tool collapses within
    the tight window instead of double-writing the log."""
    await _seed_prior(db, user, text="Got 15, doing upright rows now",
                      response="Shrugs 3×14,14,15 logged.|||What weight on rows?",
                      skills="log_exercise", age_sec=6)
    turn = await run_chat_turn(db, user, "Got 15, doing upright rows now",
                               platform="ios", source_type="ios",
                               schedule_background=False)
    assert turn.tool_calls == []
    assert "logged" in " ".join(turn.response.bubbles).lower()


@pytest.mark.asyncio
async def test_no_collapse_short_set_entry(db, user):
    """A short set-entry ("130x12") is a plausible deliberate repeat (next set) —
    it must NOT collapse and should reach the normal turn (per-tool dedup decides)."""
    await _seed_prior(db, user, text="130x12",
                      response="Shoulder press logged.", skills="log_exercise",
                      age_sec=4)
    with pytest.raises(_ReachedRunTurn):
        await run_chat_turn(db, user, "130x12",
                            platform="ios", source_type="ios",
                            schedule_background=False)


@pytest.mark.asyncio
async def test_no_collapse_tool_phrase_outside_tight_window(db, user):
    """A substantial tool-firing phrase OUTSIDE the tight window is treated as a
    real new turn, not a client retry."""
    await _seed_prior(db, user, text="Got 15, doing upright rows now",
                      response="Shrugs logged.", skills="log_exercise",
                      age_sec=15)  # > _DEDUP_TOOL_WINDOW_SEC (10)
    with pytest.raises(_ReachedRunTurn):
        await run_chat_turn(db, user, "Got 15, doing upright rows now",
                            platform="ios", source_type="ios",
                            schedule_background=False)


@pytest.mark.asyncio
async def test_no_collapse_onto_error_reply(db, user):
    """A resend after an errored turn must RETRY, never echo the canned recovery
    line — otherwise the user loops on 'Wires crossed' and never gets logged."""
    await _seed_prior(db, user, text="Wrapped doing shrugs now 190x14 first set",
                      response="Wires crossed for a sec.|||resend it and I'll get it cleanly.",
                      skills="", age_sec=3)
    with pytest.raises(_ReachedRunTurn):
        await run_chat_turn(db, user, "Wrapped doing shrugs now 190x14 first set",
                            platform="ios", source_type="ios",
                            schedule_background=False)
