"""
Shared pytest fixtures and plain helper factories.

Every DB test runs against a fresh in-memory SQLite database built from the real
models + the real _migrate() pass, so tests exercise the exact schema path prod
uses. Query functions all take an explicit `db` session, so we never touch the
app's global engine.

Plain helpers (_prefs, _log) are module-level functions — import them directly in
any test file that needs them rather than duplicating identical 2-liners everywhere.
"""
import os
from types import SimpleNamespace
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


# ── Shared stubs (non-fixture) ────────────────────────────────────────────────

def _prefs(cal_t=1800, pro_t=200):
    """Minimal UserPreferences stub with optional calorie + protein targets."""
    return SimpleNamespace(calorie_target=cal_t, protein_target=pro_t)


def _log(cal=0, pro=0):
    """Minimal DailyLog stub with total_calories + total_protein."""
    return SimpleNamespace(total_calories=cal, total_protein=pro)

# Deterministic env for tests that read it.
os.environ.setdefault("LINKING_ENABLED", "true")
os.environ.setdefault("PROACTIVE_MESSAGING_ENABLED", "false")
# Scribe off in tests — it launches a real Haiku extraction; run_turn tests stay
# hermetic. Prod defaults it ON. Tests that exercise the scribe set it explicitly.
os.environ.setdefault("SCRIBE_ENABLED", "false")

from db.database import Base, _migrate  # noqa: E402
from db import models  # noqa: E402,F401  (registers tables)


@pytest.fixture(autouse=True)
def _hermetic_voice_log(request, monkeypatch):
    """Keep the default suite hermetic on KEYED machines too. log_voice binds
    `chat` at import (core/log_voice.py), so fixtures that patch conversation's
    chat never reach it — with ANTHROPIC_API_KEY set, voice_log was silently
    making live paid calls inside 'hermetic' tests (ironclad eval 2026-07-23).
    Block it by default; behavioral-marked tests keep the live path, and any
    test that wants a scripted voice patches core.log_voice.chat itself (a
    test-level monkeypatch overrides this autouse one)."""
    if request.node.get_closest_marker("behavioral"):
        yield
        return
    import core.log_voice as _LV

    async def _blocked_live_chat(*a, **k):
        raise RuntimeError("hermetic suite: live voice_log chat call blocked "
                           "(patch core.log_voice.chat in your test)")

    monkeypatch.setattr(_LV, "chat", _blocked_live_chat)
    yield


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest_asyncio.fixture
async def make_user(db):
    """Factory: create + persist a User with sensible defaults; returns the row."""
    from db.models import User, UserPreferences

    async def _make(telegram_id="100", name="Tester", onboarded=True, **kw):
        u = User(telegram_id=telegram_id, name=name,
                 onboarding_completed=onboarded, **kw)
        db.add(u)
        await db.flush()
        db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
        await db.commit()
        return u

    return _make
