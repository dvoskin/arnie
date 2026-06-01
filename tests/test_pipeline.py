"""
Behavioral test harness for the conversation pipeline.

Covers both iMessage and Telegram handlers, both of which now delegate to the
shared core/conversation.py::run_turn orchestrator.  Tests drive the real
handler end-to-end with:
  - the LLM (core.conversation.chat / chat_follow_up) mocked to return canned
    tool-calls + text
  - platform delivery stubs (BlueBubbles calls / Telegram reply_text) captured
  - AsyncSessionLocal pointed at a fresh in-memory SQLite

Asserts: tools run once per turn, bubbles get sent, coach-unmute path is taken
on logs, profile/logs persist — without any network or live LLM.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.database import Base, _migrate
from db import models  # noqa: F401


# ── A sessionmaker over a fresh in-memory DB that survives across `async with` ──
# run_imessage_pipeline opens its own `async with AsyncSessionLocal() as db`, so we
# need a maker bound to a single shared in-memory connection (StaticPool-style).

@pytest_asyncio.fixture
async def pipeline_env(monkeypatch):
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import bot.imessage_handler as H
    import core.conversation as C

    # Point the handler's session factory at our in-memory DB.
    monkeypatch.setattr(H, "AsyncSessionLocal", Maker)

    # Capture every outbound bubble; stub typing + reactions.
    sent: list[str] = []
    reactions: list[str] = []

    async def _fake_send_text(chat_guid, text):
        sent.append(text)
        return True

    async def _fake_set_typing(chat_guid, typing):
        return True

    async def _fake_send_reaction(chat_guid, message_guid, reaction, message_text=""):
        reactions.append(reaction)
        return True

    async def _fake_send_text_with_effect(chat_guid, text, effect_id):
        sent.append(text)
        return True

    monkeypatch.setattr(H, "bb_send_text", _fake_send_text)
    monkeypatch.setattr(H, "bb_set_typing", _fake_set_typing)
    monkeypatch.setattr(H, "bb_send_reaction", _fake_send_reaction)
    monkeypatch.setattr(H, "bb_send_text_with_effect", _fake_send_text_with_effect)

    # Track how many times the LLM is called per turn (guards against double-processing).
    calls = {"chat": 0, "follow_up": 0}

    def set_llm(text="", tool_calls=None, follow_up_text="Logged it."):
        async def _fake_chat(messages, system, tools=True, max_tokens=1024, model=None):
            calls["chat"] += 1
            return {"text": text, "tool_calls": tool_calls or [], "raw_content": [{"x": 1}]}

        async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
            calls["follow_up"] += 1
            return follow_up_text

        # Patch on core.conversation — the shared orchestrator now owns LLM calls.
        monkeypatch.setattr(C, "chat", _fake_chat)
        monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)

    yield {"H": H, "C": C, "Maker": Maker, "sent": sent, "reactions": reactions,
           "calls": calls, "set_llm": set_llm}
    await engine.dispose()


async def _seed_user(Maker, address="+15550001111", onboarded=True):
    """Create an onboarded iMessage user so the pipeline takes the coaching path."""
    from db.models import User, UserPreferences
    im_id = f"im:{address}"
    async with Maker() as db:
        u = User(telegram_id=im_id, name="Danny", onboarding_completed=onboarded,
                 current_weight_kg=86.0, primary_goal="cut",
                 training_experience="intermediate", city="NYC",
                 timezone="America/New_York")
        db.add(u)
        await db.flush()
        db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False,
                               calorie_target=2100, protein_target=180))
        await db.commit()
    return im_id


# ── Tests ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plain_chat_turn_sends_bubbles(pipeline_env):
    """A non-logging message: the LLM's text is sent as multi-bubble, no tools run."""
    env = pipeline_env
    await _seed_user(env["Maker"])
    env["set_llm"](text="Weight's up.|||Not panic-worthy.|||We track the 7-day trend.")
    await env["H"].run_imessage_pipeline("+15550001111", "iMessage;-;+15550001111",
                                         "my weight is up today", message_guid="g1")
    assert len(env["sent"]) == 3, f"expected 3 bubbles, got {env['sent']}"
    assert env["calls"]["chat"] == 1  # exactly one LLM call, no double-processing


@pytest.mark.asyncio
async def test_food_log_runs_tool_once_and_coaches(pipeline_env):
    """Logging a food: tool executes, and the reply COACHES (follow-up), not a bare
    template. This is the coach-unmute behavior — must survive the pipeline merge."""
    env = pipeline_env
    await _seed_user(env["Maker"])
    env["set_llm"](
        text="",
        tool_calls=[{"name": "log_food",
                     "input": {"food_name": "chicken bowl", "calories": 650,
                               "protein": 45, "carbs": 60, "fats": 18}}],
        follow_up_text="Logged.|||Solid protein.|||Keep dinner lean.",
    )
    await env["H"].run_imessage_pipeline("+15550001111", "iMessage;-;+15550001111",
                                         "had a chicken bowl", message_guid="g2")
    # coaching follow-up was used (not just the deterministic template)
    assert env["calls"]["follow_up"] == 1
    assert len(env["sent"]) >= 1
    # the food actually persisted exactly once
    from sqlalchemy import select, func
    from db.models import FoodEntry
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(FoodEntry))).scalar()
    assert n == 1, f"expected exactly 1 food entry, got {n}"


@pytest.mark.asyncio
async def test_log_persists_once_not_per_bubble(pipeline_env):
    """Even with a multi-bubble reply, the log is written once per event."""
    env = pipeline_env
    await _seed_user(env["Maker"])
    env["set_llm"](
        text="",
        tool_calls=[{"name": "log_water", "input": {}}],
        follow_up_text="Water in.|||💧|||Keep sipping.|||Nice.",
    )
    await env["H"].run_imessage_pipeline("+15550001111", "iMessage;-;+15550001111",
                                         "drank a glass of water", message_guid="g3")
    # 4-bubble reply, but the conversation log is written once
    from sqlalchemy import select, func
    from db.models import ConversationLog
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(ConversationLog))).scalar()
    assert n == 1, f"expected exactly 1 conversation log, got {n}"


@pytest.mark.asyncio
async def test_empty_llm_never_dead_ends(pipeline_env):
    """If the LLM returns nothing and no tools ran, the user still gets a real reply
    (never silence, never a bare 'done.')."""
    env = pipeline_env
    await _seed_user(env["Maker"])
    env["set_llm"](text="", tool_calls=[], follow_up_text="")
    await env["H"].run_imessage_pipeline("+15550001111", "iMessage;-;+15550001111",
                                         "hey", message_guid="g4")
    assert len(env["sent"]) >= 1
    joined = " ".join(env["sent"]).lower()
    assert joined.strip() not in ("", "done.", "got it.")


# ── Telegram twin fixture ──────────────────────────────────────────────────────

class _FakeMessage:
    message_id = 42
    async def reply_text(self, text="", **kwargs):
        self._sent.append(text)
    async def reply_photo(self, photo, caption=None):
        pass


class _FakeUser:
    id = 77777


class _FakeChat:
    id = 88888


class _FakeBot:
    async def send_chat_action(self, chat_id, action, **kwargs):
        pass
    async def set_message_reaction(self, **kwargs):
        pass


@pytest_asyncio.fixture
async def tg_pipeline_env(monkeypatch):
    """
    Telegram pipeline harness — mirrors pipeline_env but drives _run_pipeline.
    Stubs Telegram's reply_text to capture sent bubbles; mocks core.conversation
    LLM calls so no real API is hit.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import bot.telegram_handler as TH
    import core.conversation as C

    monkeypatch.setattr(TH, "AsyncSessionLocal", Maker)

    sent: list[str] = []
    calls = {"chat": 0, "follow_up": 0}

    msg = _FakeMessage()
    msg._sent = sent  # share the list

    class _FakeUpdate:
        effective_chat = _FakeChat()
        effective_user = _FakeUser()
        message = msg

    class _FakeContext:
        bot = _FakeBot()

    def set_llm(text="", tool_calls=None, follow_up_text="Logged it."):
        async def _fake_chat(messages, system, tools=True, max_tokens=1024, model=None):
            calls["chat"] += 1
            return {"text": text, "tool_calls": tool_calls or [], "raw_content": [{"x": 1}]}
        async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
            calls["follow_up"] += 1
            return follow_up_text
        monkeypatch.setattr(C, "chat", _fake_chat)
        monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)

    yield {
        "TH": TH, "C": C, "Maker": Maker,
        "sent": sent, "calls": calls, "set_llm": set_llm,
        "update": _FakeUpdate(), "context": _FakeContext(),
    }
    await engine.dispose()


async def _seed_tg_user(Maker, tg_id="77777", onboarded=True):
    """Create an onboarded Telegram user so _run_pipeline takes the coaching path."""
    from db.models import User, UserPreferences
    async with Maker() as db:
        u = User(telegram_id=str(tg_id), name="Danny", onboarding_completed=onboarded,
                 current_weight_kg=86.0, primary_goal="cut",
                 training_experience="intermediate", city="NYC",
                 timezone="America/New_York")
        db.add(u)
        await db.flush()
        db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False,
                               calorie_target=2100, protein_target=180))
        await db.commit()


# ── Telegram twin tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tg_plain_chat_turn_sends_bubbles(tg_pipeline_env):
    """Telegram: non-logging turn sends multi-bubble reply via reply_text."""
    env = tg_pipeline_env
    await _seed_tg_user(env["Maker"])
    env["set_llm"](text="Weight's up.|||Not panic-worthy.|||Track the 7-day trend.")
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(
            env["update"], env["context"], "my weight is up", "text", db
        )
    assert len(env["sent"]) == 3, f"expected 3 bubbles, got {env['sent']}"
    assert env["calls"]["chat"] == 1


@pytest.mark.asyncio
async def test_tg_food_log_coaches_not_template(tg_pipeline_env):
    """Telegram: logging food uses the coach-unmute follow-up, not a canned template."""
    env = tg_pipeline_env
    await _seed_tg_user(env["Maker"])
    env["set_llm"](
        text="",
        tool_calls=[{"name": "log_food",
                     "input": {"food_name": "salmon", "calories": 400,
                               "protein": 40, "carbs": 0, "fats": 18}}],
        follow_up_text="Logged.|||Great protein source.|||Stay under 500 cal for dinner.",
    )
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(
            env["update"], env["context"], "had salmon for lunch", "text", db
        )
    assert env["calls"]["follow_up"] == 1
    assert len(env["sent"]) >= 1
    from sqlalchemy import select, func
    from db.models import FoodEntry
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(FoodEntry))).scalar()
    assert n == 1, f"expected exactly 1 food entry, got {n}"


@pytest.mark.asyncio
async def test_tg_empty_llm_never_dead_ends(tg_pipeline_env):
    """Telegram: if LLM returns nothing and no tools, user still gets a real reply."""
    env = tg_pipeline_env
    await _seed_tg_user(env["Maker"])
    env["set_llm"](text="", tool_calls=[], follow_up_text="")
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(
            env["update"], env["context"], "hey", "text", db
        )
    assert len(env["sent"]) >= 1
    joined = " ".join(env["sent"]).lower()
    assert joined.strip() not in ("", "done.", "got it.")
