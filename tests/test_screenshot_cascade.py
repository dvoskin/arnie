"""
Integration tests locking in the exact screenshot-cascade failure modes.

These tests reproduce the specific scenarios from the 2026-06-11 screenshots
(Elmhurst shake → chicken+rice topic drift, "Got that. / 200 / 2126" generic-net
loop, 3:19 PM dinner triple-nudge) at the conversation-pipeline level. They
verify the wave-1/2/3/4 fixes prevent each regression individually so a future
edit can't silently bring them back.

No LLM, no network — every external call is stubbed. The pipeline_env fixture
from test_pipeline lives in conftest-style imports; we re-use the same harness.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.database import Base, _migrate
from db import models  # noqa: F401


@pytest_asyncio.fixture
async def cascade_env(monkeypatch):
    """Mirror of pipeline_env from test_pipeline.py — fresh in-memory DB +
    stubbed LLM + captured outbound bubbles."""
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
    monkeypatch.setattr(H, "AsyncSessionLocal", Maker)

    sent: list[str] = []

    async def _fake_send(chat_guid, text):
        sent.append(text)
        return True

    async def _noop(*a, **kw):
        return True

    monkeypatch.setattr(H, "bb_send_text", _fake_send)
    monkeypatch.setattr(H, "bb_set_typing", _noop)
    monkeypatch.setattr(H, "bb_send_reaction", _noop)
    monkeypatch.setattr(H, "bb_send_text_with_effect", _fake_send)

    calls = {"chat": 0, "follow_up": 0}

    def set_llm(text="", tool_calls=None, follow_up_text="Logged."):
        async def _chat(messages, system, tools=True, max_tokens=4096,
                        model=None, stream_handler=None, **kw):
            calls["chat"] += 1
            return {"text": text, "tool_calls": tool_calls or [],
                    "raw_content": [{"x": 1}], "stop_reason": "end_turn"}

        async def _fu(messages, system, raw_content=None, tool_results=None,
                      max_tokens=512, stream_handler=None, **kw):
            calls["follow_up"] += 1
            return {"text": follow_up_text}

        monkeypatch.setattr(C, "chat", _chat)
        monkeypatch.setattr(C, "chat_follow_up", _fu)

    yield {"H": H, "C": C, "Maker": Maker, "sent": sent, "calls": calls,
           "set_llm": set_llm}
    await engine.dispose()


async def _seed_user(Maker, **prefs):
    from db.models import User, UserPreferences
    im_id = "im:+15550009999"
    async with Maker() as db:
        u = User(telegram_id=im_id, name="Test", onboarding_completed=True,
                 current_weight_kg=80.0, primary_goal="cut",
                 city="NYC", timezone="America/New_York")
        db.add(u)
        await db.flush()
        db.add(UserPreferences(
            user_id=u.id, proactive_messaging_enabled=False,
            calorie_target=2100, protein_target=180, **prefs))
        await db.commit()
    return im_id


# ═══════════════════════════════════════════════════════════════════════════
# WAVE 1 — Web-first packaged + idempotency + body weight sanity
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_packaged_flag_routes_through_web_lookup(monkeypatch, cascade_env):
    """is_packaged=True must trigger _web_lookup_packaged for branded items —
    the screenshot fix for Elmhurst Clean Protein."""
    import handlers.tool_executor as TE

    web_called = {"n": 0, "queries": []}
    usda_called = {"n": 0}

    async def _fake_web(name, qty):
        web_called["n"] += 1
        web_called["queries"].append(name)
        return {
            "fdc_id": None, "_match": "likely",
            "per100g": {"calories": 200.0, "protein": 27.0, "carbs": 4.0,
                        "fat": 7.0, "fiber": None, "sugar": None, "sodium": None},
        }

    async def _fake_usda(*a, **kw):
        usda_called["n"] += 1
        return []

    monkeypatch.setattr(TE, "_web_lookup_packaged", _fake_web)
    from api import usda as _USDA
    monkeypatch.setattr(_USDA, "search_food", _fake_usda)

    env = cascade_env
    await _seed_user(env["Maker"])
    env["set_llm"](
        text="",
        tool_calls=[{
            "name": "log_food",
            "input": {
                "food_name": "Elmhurst Clean Protein Sea Salt Chocolate",
                "quantity": "11 fl oz", "calories": 190, "protein": 27,
                "carbs": 10, "fats": 5, "from_photo": True, "is_packaged": True,
            },
        }],
        follow_up_text="Elmhurst shake logged — 190 cal, 27g protein.",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "[Food photo] just got one of these", message_guid="cas1",
    )
    assert web_called["n"] == 1, (
        f"web lookup must fire for is_packaged=True (got {web_called['n']} calls)"
    )
    assert "Elmhurst" in web_called["queries"][0]
    assert usda_called["n"] == 0, (
        "USDA must NOT be consulted before web for branded products "
        "(was called {usda_called['n']} times)"
    )


@pytest.mark.asyncio
async def test_branded_text_mention_caught_by_heuristic(monkeypatch, cascade_env):
    """When the model forgets is_packaged=True, _looks_branded should still catch
    obvious brand patterns like 'Elmhurst Clean Protein' and route to web."""
    import handlers.tool_executor as TE

    web_called = {"n": 0}

    async def _fake_web(name, qty):
        web_called["n"] += 1
        return None  # miss — falls back to USDA

    async def _fake_usda(*a, **kw):
        return []

    monkeypatch.setattr(TE, "_web_lookup_packaged", _fake_web)
    from api import usda as _USDA
    monkeypatch.setattr(_USDA, "search_food", _fake_usda)

    env = cascade_env
    await _seed_user(env["Maker"])
    env["set_llm"](
        text="",
        tool_calls=[{
            "name": "log_food",
            "input": {
                "food_name": "Elmhurst Clean Protein shake",
                "quantity": "1 bottle", "calories": 190, "protein": 27,
                "carbs": 10, "fats": 5,
                # is_packaged NOT set — relying on heuristic fallback
            },
        }],
        follow_up_text="Got it.",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "logged the Elmhurst shake", message_guid="cas2",
    )
    assert web_called["n"] == 1, (
        "_looks_branded must route obvious brand patterns to web lookup "
        "even without the explicit is_packaged flag"
    )


@pytest.mark.asyncio
async def test_cross_turn_duplicate_log_returns_existing(cascade_env):
    """Logging the same (food, qty) within 5 minutes returns the existing entry
    instead of a duplicate row — the screenshot shake-confirmation cascade
    can no longer create double-logs."""
    env = cascade_env
    await _seed_user(env["Maker"])

    # Turn 1: log the shake.
    env["set_llm"](
        text="",
        tool_calls=[{
            "name": "log_food",
            "input": {"food_name": "Elmhurst shake", "quantity": "11 fl oz",
                      "calories": 190, "protein": 27, "carbs": 10, "fats": 5},
        }],
        follow_up_text="Shake logged.",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "log the elmhurst", message_guid="dup1",
    )

    # Turn 2: same item, same qty — should hit the idempotency check.
    env["set_llm"](
        text="",
        tool_calls=[{
            "name": "log_food",
            "input": {"food_name": "Elmhurst shake", "quantity": "11 fl oz",
                      "calories": 190, "protein": 27, "carbs": 10, "fats": 5},
        }],
        follow_up_text="Already on the board.",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "log the elmhurst again", message_guid="dup2",
    )

    from sqlalchemy import select, func
    from db.models import FoodEntry
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(FoodEntry))).scalar()
    assert n == 1, (
        f"cross-turn idempotency must collapse retries within 5 min — "
        f"got {n} entries instead of 1"
    )


@pytest.mark.asyncio
async def test_body_weight_unit_typo_does_not_corrupt_trend(cascade_env):
    """14 kg when current is 80 kg is a unit-mix-up — must not write the entry."""
    env = cascade_env
    await _seed_user(env["Maker"])

    env["set_llm"](
        text="",
        tool_calls=[{"name": "log_body_weight",
                     "input": {"weight": 14, "unit": "kg"}}],
        follow_up_text="Was that 14 kg or 14 lb?",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "weight 14", message_guid="bw1",
    )

    from sqlalchemy import select, func
    from db.models import BodyMetric
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(BodyMetric))).scalar()
    assert n == 0, f"unit-mixup guard must block the write (got {n} body metrics)"


@pytest.mark.asyncio
async def test_body_weight_sane_value_writes_normally(cascade_env):
    """A normal weight reading near current_weight_kg writes through."""
    env = cascade_env
    await _seed_user(env["Maker"])

    env["set_llm"](
        text="",
        tool_calls=[{"name": "log_body_weight",
                     "input": {"weight": 79.2, "unit": "kg"}}],
        follow_up_text="Logged — solid morning reading.",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "weight 79.2", message_guid="bw2",
    )

    from sqlalchemy import select, func
    from db.models import BodyMetric
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(BodyMetric))).scalar()
    assert n == 1, f"sane weight should log normally (got {n} entries)"


# ═══════════════════════════════════════════════════════════════════════════
# WAVE 2 — Repair pipeline (stall trigger + anchor in repair prompt)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stall_with_no_tool_calls_triggers_repair(cascade_env, monkeypatch):
    """The exact 'Checking the label on that one.' pattern from the screenshot:
    text contains a stall phrase, no tool ran. Repair must fire and produce a
    second LLM call so the user doesn't see a dangling 'checking…'."""
    env = cascade_env
    await _seed_user(env["Maker"])

    import core.conversation as C

    # First chat call: stall text, no tools (the bug).
    # Repair call: real coaching response.
    chat_call_count = {"n": 0}

    async def _chat(messages, system, tools=True, max_tokens=4096, **kw):
        chat_call_count["n"] += 1
        if chat_call_count["n"] == 1:
            return {"text": "Checking the label on that one.",
                    "tool_calls": [], "raw_content": [{"x": 1}],
                    "stop_reason": "end_turn"}
        else:
            return {"text": "My bad — what were you logging just now?",
                    "tool_calls": [], "raw_content": [{"x": 1}],
                    "stop_reason": "end_turn"}

    async def _fu(messages, system, raw_content=None, tool_results=None,
                  max_tokens=512, **kw):
        return {"text": ""}

    monkeypatch.setattr(C, "chat", _chat)
    monkeypatch.setattr(C, "chat_follow_up", _fu)

    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "what's the macro on a quest bar", message_guid="stall1",
    )
    # The self-heal retry fires for stalls too — first pass detects "Checking…"
    # is a stall, retries with a nudge.  Plus the post-text quality repair runs.
    # Either way the count must be >= 2 (no longer dead-ends on the stall).
    assert chat_call_count["n"] >= 2, (
        f"stall with no tool calls must trigger a retry (got {chat_call_count['n']} chat calls)"
    )


# ═══════════════════════════════════════════════════════════════════════════
# WAVE 3 — Reminder hygiene (hook gates, freq, bubble cap)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_logging_turn_question_does_not_open_hook(cascade_env):
    """A coaching tag-question ('what's the plan tonight?') at the end of a
    logging turn must NOT queue a 30-min re-ask — that's exactly how the
    3:19 PM dinner triple started."""
    env = cascade_env
    await _seed_user(env["Maker"])

    env["set_llm"](
        text="",
        tool_calls=[{
            "name": "log_food",
            "input": {"food_name": "chicken bowl", "quantity": "1 bowl",
                      "calories": 650, "protein": 45, "carbs": 60, "fats": 18},
        }],
        follow_up_text="Logged 650 cal.|||515/2126 today.|||What's the plan tonight?",
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "had a chicken bowl", message_guid="hook1",
    )

    from sqlalchemy import select, func
    from db.models import PendingQuestion
    async with env["Maker"]() as db:
        n = (await db.execute(
            select(func.count())
            .select_from(PendingQuestion)
            .where(PendingQuestion.kind == "conversation_hook")
        )).scalar()
    assert n == 0, (
        f"logging turn's closing 'what's the plan tonight?' must NOT open a "
        f"conversation_hook (found {n})"
    )


@pytest.mark.asyncio
async def test_non_logging_substantive_question_opens_hook(cascade_env):
    """A real abandoned-loop question on a non-logging turn still opens a hook —
    the gate from Change 3 is precise, not blanket."""
    env = cascade_env
    await _seed_user(env["Maker"])

    env["set_llm"](
        text=("Your protein's been trending light all week.|||"
              "Want me to bump the target by 20g, or work it through meals first?"),
        tool_calls=[],
    )
    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "how's my week look", message_guid="hook2",
    )

    from sqlalchemy import select, func
    from db.models import PendingQuestion
    async with env["Maker"]() as db:
        n = (await db.execute(
            select(func.count())
            .select_from(PendingQuestion)
            .where(PendingQuestion.kind == "conversation_hook")
        )).scalar()
    assert n == 1, (
        f"a real long abandoned-loop question SHOULD still open a hook "
        f"(found {n})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Goodnight / sign-off — quality repair stays off, "Sleep well" ships clean
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_goodnight_signoff_does_not_trigger_repair(cascade_env, monkeypatch):
    """User says 'goodnight', Arnie's reply ending in 'Sleep well 🌙' is
    correct and must NOT be repaired away into a logging turn (the previous
    'Logged: Ground turkey after goodnight' regression)."""
    env = cascade_env
    await _seed_user(env["Maker"])

    import core.conversation as C
    chat_call_count = {"n": 0}

    async def _chat(messages, system, tools=True, max_tokens=4096, **kw):
        chat_call_count["n"] += 1
        return {"text": "Day's closed at 1,840.|||Right on target.|||Sleep well 🌙",
                "tool_calls": [], "raw_content": [{"x": 1}],
                "stop_reason": "end_turn"}

    async def _fu(messages, system, raw_content=None, tool_results=None,
                  max_tokens=512, **kw):
        return {"text": ""}

    monkeypatch.setattr(C, "chat", _chat)
    monkeypatch.setattr(C, "chat_follow_up", _fu)

    await env["H"].run_imessage_pipeline(
        "+15550009999", "iMessage;-;+15550009999",
        "goodnight", message_guid="gn1",
    )
    # Exactly one chat call — no repair retry triggered by the sign-off guard.
    assert chat_call_count["n"] == 1, (
        f"sign-off reply must not trigger repair (got {chat_call_count['n']} chat calls)"
    )
    # The closeout reply made it through unmodified.
    full = "|||".join(env["sent"])
    assert "Sleep well" in full
    assert "1,840" in full
