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
        # **kwargs absorbs forward-compat params like stream_handler (T2.1).
        async def _fake_chat(messages, system, tools=True, max_tokens=1024,
                             model=None, stream_handler=None, **kwargs):
            calls["chat"] += 1
            if stream_handler is not None and text:
                await stream_handler(text)
            return {"text": text, "tool_calls": tool_calls or [], "raw_content": [{"x": 1}]}

        async def _fake_follow_up(messages, raw, tcs, results, system,
                                  max_tokens=512, stream_handler=None, **kwargs):
            calls["follow_up"] += 1
            if stream_handler is not None and follow_up_text:
                await stream_handler(follow_up_text)
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


async def _seed_onboarding_user(Maker, address="+15550003333", **fields):
    """A user mid-onboarding (onboarding_completed=False) with optional pre-set
    fields, for brain-dump / completion tests."""
    from db.models import User, UserPreferences
    im_id = f"im:{address}"
    async with Maker() as db:
        u = User(telegram_id=im_id, onboarding_completed=False, **fields)
        db.add(u)
        await db.flush()
        db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
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
async def test_multi_item_message_logs_every_item(pipeline_env):
    """
    REGRESSION: a message listing several foods must log ALL of them in one turn, not
    just the first. Previously the first-pass max_tokens (1024) truncated the response
    after ~1 tool call, so a 7-item dump logged only the grilled chicken wrap. The
    executor loops over every tool_call — this proves N calls => N persisted entries
    and a total that sums all of them.
    """
    env = pipeline_env
    await _seed_user(env["Maker"])
    items = [
        ("grilled chicken wrap", 450, 35),
        ("shnitzel sandwich", 600, 30),
        ("chicken poppers", 280, 18),
        ("spicy tuna sushi", 350, 20),
        ("cookies", 300, 4),
        ("babka slice", 300, 6),
        ("cinnamon roll", 350, 5),
    ]
    env["set_llm"](
        text="",
        tool_calls=[
            {"name": "log_food", "input": {"food_name": n, "calories": c,
                                           "protein": p, "carbs": 40, "fats": 15}}
            for (n, c, p) in items
        ],
        follow_up_text="logged the whole list 🎊|||that's ~2,630 for the day.",
    )
    await env["H"].run_imessage_pipeline(
        "+15550001111", "iMessage;-;+15550001111",
        "grilled chicken wrap, shnitzel sandwich, chicken poppers, spicy tuna sushi, "
        "cookies, babka slice, cinnamon roll", message_guid="multi1",
    )
    from sqlalchemy import select, func
    from db.models import FoodEntry, DailyLog
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(FoodEntry))).scalar()
        total = (await db.execute(select(func.sum(DailyLog.total_calories)))).scalar()
    assert n == len(items), f"expected all {len(items)} items logged, got {n}"
    assert total == sum(c for _, c, _ in items), f"day total should sum all items, got {total}"


@pytest.mark.asyncio
async def test_redo_today_clears_then_relogs_in_one_turn(pipeline_env):
    """
    "Redo today as the following: ..." must wipe today's log and rebuild it in ONE turn
    (clear_day_log first, then a log_food per item) — not stack the new items on top of
    a messed-up day. Guards the prod case where babka got logged 4x and nothing matched.
    """
    env = pipeline_env
    addr, chat = "+15550001111", "iMessage;-;+15550001111"
    await _seed_user(env["Maker"])

    # Turn 1: a messed-up day — distinct items, one of which the user wants to wipe.
    # (We can't use two identical babka calls anymore because the intra-turn dedup
    # at conversation.py and the cross-turn idempotency check at tool_executor.py
    # both correctly collapse same-name same-quantity logs within seconds.)
    env["set_llm"](text="", tool_calls=[
        {"name": "log_food", "input": {"food_name": "babka", "quantity": "1 slice",
                                       "calories": 300, "protein": 4, "carbs": 40, "fats": 15}},
        {"name": "log_food", "input": {"food_name": "babka", "quantity": "2 slices",
                                       "calories": 600, "protein": 8, "carbs": 80, "fats": 30}},
    ], follow_up_text="logged.")
    await env["H"].run_imessage_pipeline(addr, chat, "babka and babka", message_guid="d1")

    from sqlalchemy import select, func
    from db.models import FoodEntry, DailyLog
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(FoodEntry))).scalar()
    assert n == 2, f"setup: expected 2 entries before redo, got {n}"

    # Turn 2: redo today clean → clear_day_log FIRST, then the real list.
    env["set_llm"](text="", tool_calls=[
        {"name": "clear_day_log", "input": {}},
        {"name": "log_food", "input": {"food_name": "grilled chicken wrap", "calories": 450,
                                       "protein": 35, "carbs": 40, "fats": 15}},
        {"name": "log_food", "input": {"food_name": "shnitzel sandwich", "calories": 600,
                                       "protein": 30, "carbs": 40, "fats": 20}},
    ], follow_up_text="wiped it and rebuilt 🎊|||you're at 1,050 today.")
    await env["H"].run_imessage_pipeline(
        addr, chat, "redo today as the following: grilled chicken wrap, shnitzel sandwich",
        message_guid="d2",
    )

    # Only the 2 new items remain (babkas gone), and the total sums just those.
    async with env["Maker"]() as db:
        n = (await db.execute(select(func.count()).select_from(FoodEntry))).scalar()
        total = (await db.execute(select(func.sum(DailyLog.total_calories)))).scalar()
    assert n == 2, f"redo should leave exactly the 2 new items, got {n}"
    assert total == 1050, f"total should be just the rebuilt day (450+600), got {total}"


@pytest.mark.asyncio
async def test_move_day_via_update_date_resyncs_both_days(pipeline_env):
    """
    Moving a whole day = update_food_entry(date="yesterday") once per entry (the SAME
    primitive as moving one item — no bespoke move tool). Today drains to zero, yesterday
    holds the moved totals, and BOTH days' totals resync so the dashboard always matches.
    """
    env = pipeline_env
    addr, chat = "+15550001111", "iMessage;-;+15550001111"
    await _seed_user(env["Maker"])

    # Turn 1: log two items to today.
    env["set_llm"](text="", tool_calls=[
        {"name": "log_food", "input": {"food_name": "chicken wrap", "calories": 450,
                                       "protein": 35, "carbs": 40, "fats": 15}},
        {"name": "log_food", "input": {"food_name": "premier shake", "calories": 160,
                                       "protein": 30, "carbs": 5, "fats": 2}},
    ], follow_up_text="logged both.")
    await env["H"].run_imessage_pipeline(addr, chat, "wrap and a shake", message_guid="m1")

    from sqlalchemy import select
    from db.models import FoodEntry, DailyLog, User
    async with env["Maker"]() as db:
        ids = (await db.execute(select(FoodEntry.id).order_by(FoodEntry.id))).scalars().all()
    assert len(ids) == 2, f"setup: expected 2 entries, got {len(ids)}"

    # Turn 2: move each entry to yesterday — the composable primitive, one call per item.
    env["set_llm"](text="", tool_calls=[
        {"name": "update_food_entry", "input": {"entry_id": ids[0], "date": "yesterday"}},
        {"name": "update_food_entry", "input": {"entry_id": ids[1], "date": "yesterday"}},
    ], follow_up_text="moved both to yesterday 👊|||that day's at 610 now.")
    await env["H"].run_imessage_pipeline(
        addr, chat, "put this log for yesterday instead of today", message_guid="m2",
    )

    from datetime import timedelta
    from db.queries import _user_today
    async with env["Maker"]() as db:
        u = (await db.execute(
            select(User).where(User.telegram_id == f"im:{addr}")
        )).scalar_one()
        # Anchor on the user's LOGGING day (grace-window aware), the same notion
        # food logging and "yesterday" parsing use — otherwise this flakes around
        # the 4am rollover.
        today = _user_today(u.timezone or "UTC")
        yest = today - timedelta(days=1)
        today_log = (await db.execute(
            select(DailyLog).where(DailyLog.user_id == u.id, DailyLog.date == today)
        )).scalar_one_or_none()
        yest_log = (await db.execute(
            select(DailyLog).where(DailyLog.user_id == u.id, DailyLog.date == yest)
        )).scalar_one_or_none()

    assert today_log is not None and round(today_log.total_calories or 0) == 0, \
        "today should drain to zero after moving both entries"
    assert yest_log is not None and round(yest_log.total_calories or 0) == 610, \
        f"yesterday should hold the moved entries (610), got {yest_log and yest_log.total_calories}"


@pytest.mark.asyncio
async def test_workout_logged_for_yesterday_lands_on_yesterday(pipeline_env):
    """Workouts get the same date-flexibility as food: 'yesterday I benched and squatted'
    logs both exercises onto yesterday, not today."""
    env = pipeline_env
    addr, chat = "+15550001111", "iMessage;-;+15550001111"
    await _seed_user(env["Maker"])

    env["set_llm"](text="", tool_calls=[
        {"name": "log_exercise", "input": {"exercise_name": "bench press", "sets": 4,
                                           "reps": "5", "weight": 185, "date": "yesterday"}},
        {"name": "log_exercise", "input": {"exercise_name": "squat", "sets": 3,
                                           "reps": "5", "weight": 225, "date": "yesterday"}},
    ], follow_up_text="logged yesterday's session 💪")
    await env["H"].run_imessage_pipeline(
        addr, chat, "yesterday I benched 185 and squatted 225", message_guid="w1",
    )

    from sqlalchemy import select, func
    from db.models import User, DailyLog, ExerciseEntry
    from datetime import timedelta
    from db.queries import _user_today
    async with env["Maker"]() as db:
        u = (await db.execute(select(User).where(User.telegram_id == f"im:{addr}"))).scalar_one()
        # Anchor on the LOGGING day (grace-window aware), matching where "yesterday"
        # parsing and food/exercise logging land — otherwise flaky around 4am.
        today = _user_today(u.timezone or "UTC")
        yest = today - timedelta(days=1)
        yest_log = (await db.execute(
            select(DailyLog).where(DailyLog.user_id == u.id, DailyLog.date == yest)
        )).scalar_one_or_none()
        n_yest = (await db.execute(
            select(func.count()).select_from(ExerciseEntry)
            .where(ExerciseEntry.daily_log_id == (yest_log.id if yest_log else -1))
        )).scalar()
        today_log = (await db.execute(
            select(DailyLog).where(DailyLog.user_id == u.id, DailyLog.date == today)
        )).scalar_one_or_none()
        n_today = 0 if today_log is None else (await db.execute(
            select(func.count()).select_from(ExerciseEntry)
            .where(ExerciseEntry.daily_log_id == today_log.id)
        )).scalar()
    assert yest_log is not None and n_yest == 2, f"both lifts should be on yesterday, got {n_yest}"
    assert n_today == 0, f"nothing should land on today, got {n_today}"
    assert yest_log.workout_completed, "yesterday should be marked workout_completed"


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


@pytest.mark.asyncio
async def test_turn_records_then_resolves_profile_question(pipeline_env):
    """End-to-end: a coaching turn for a stats-missing user opens a profile_stats
    follow-up loop; once the stats land, the next turn resolves it. (The seeded
    user has weight + goal but no age/sex/height.)"""
    env = pipeline_env
    im_id = await _seed_user(env["Maker"])
    from db.queries import get_open_pending_question

    # Turn 1: plain chat → loop opens (user is missing age/sex/height).
    env["set_llm"](text="Noted.|||Keep me posted.")
    await env["H"].run_imessage_pipeline("+15550001111", "iMessage;-;+15550001111",
                                         "hey", message_guid="p1")
    async with env["Maker"]() as db:
        from db.queries import resolve_user
        u = await resolve_user(db, im_id)
        pq = await get_open_pending_question(db, u.id, "profile_stats")
        assert pq is not None and pq.tier == "goal_critical"

    # Fill the stats out-of-band (simulating an update_profile having landed).
    async with env["Maker"]() as db:
        from db.queries import resolve_user
        u = await resolve_user(db, im_id)
        u.age, u.sex, u.height_cm = 31, "male", 178.0
        await db.commit()

    # Turn 2: another plain chat → loop resolves now that stats are complete.
    env["set_llm"](text="Got it.")
    await env["H"].run_imessage_pipeline("+15550001111", "iMessage;-;+15550001111",
                                         "thanks", message_guid="p2")
    async with env["Maker"]() as db:
        from db.queries import resolve_user
        u = await resolve_user(db, im_id)
        assert await get_open_pending_question(db, u.id, "profile_stats") is None


@pytest.mark.asyncio
async def test_voice_note_transcript_drives_pipeline(pipeline_env, monkeypatch):
    """End-to-end: a voice note is downloaded + transcribed, and the transcript flows
    through the normal pipeline as if it were typed text. Arnie does NOT echo the
    transcript back (a human coach responds, it doesn't parrot you) — it just coaches."""
    env = pipeline_env
    H = env["H"]
    await _seed_user(env["Maker"])

    async def fake_download(guid):
        return b"FAKE-CAF-BYTES"

    async def fake_transcribe(audio, transfer_name="audio.caf"):
        return "had a chicken bowl"

    monkeypatch.setattr(H, "bb_download_attachment", fake_download)
    monkeypatch.setattr(H, "transcribe_audio_message", fake_transcribe)

    env["set_llm"](text="Logged that.|||Solid protein.")
    await H.handle_imessage_audio(
        "+15550001111", "iMessage;-;+15550001111", "att-guid-1",
        message_guid="v1", transfer_name="Audio Message.caf",
    )

    # The pipeline produced a real coaching reply...
    assert env["calls"]["chat"] == 1            # pipeline ran exactly once
    assert len(env["sent"]) >= 1               # at least one reply bubble
    # ...and the raw transcript was NOT echoed back verbatim (no 🎙 parrot).
    assert not any(s.strip() == "had a chicken bowl" for s in env["sent"]), env["sent"]
    assert not any("🎙" in s for s in env["sent"]), env["sent"]


@pytest.mark.asyncio
async def test_voice_note_unintelligible_sends_fallback(pipeline_env, monkeypatch):
    """If transcription yields nothing, the user gets a friendly fallback and the
    pipeline never runs (no empty/garbage turn)."""
    env = pipeline_env
    H = env["H"]
    await _seed_user(env["Maker"])

    async def fake_download(guid):
        return b"FAKE-CAF-BYTES"

    async def fake_transcribe(audio, transfer_name="audio.caf"):
        return ""  # couldn't transcribe

    monkeypatch.setattr(H, "bb_download_attachment", fake_download)
    monkeypatch.setattr(H, "transcribe_audio_message", fake_transcribe)

    env["set_llm"](text="should never run")
    await H.handle_imessage_audio(
        "+15550001111", "iMessage;-;+15550001111", "att-guid-2", message_guid="v2",
    )

    assert env["calls"]["chat"] == 0           # pipeline did NOT run
    assert any("couldn't make out" in s.lower() for s in env["sent"]), env["sent"]


# ── Onboarding: brain-dump hybrid flow ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_contact_sends_scripted_intro_no_llm(pipeline_env):
    """A truly new user's first message triggers the scripted intro (asking their
    name), with no LLM call and no em dash."""
    env = pipeline_env
    H = env["H"]
    env["set_llm"](text="should-not-be-called")
    await H.run_imessage_pipeline(
        "+15550003333", "iMessage;-;+15550003333", "hey", message_guid="o0",
    )
    assert env["calls"]["chat"] == 0                  # intro is scripted
    assert len(env["sent"]) >= 1
    joined = " ".join(env["sent"]).lower()
    assert "—" not in joined
    assert "call you" in joined or "your name" in joined   # asks what to call them


@pytest.mark.asyncio
async def test_brain_dump_completion_reflects_then_pushes_to_log(pipeline_env):
    """
    RETENTION: after the intro, the user dumps everything in one message. Arnie
    extracts it in a single update_profile call, onboarding auto-completes — and the
    reply is the REFLECTION (an intelligent read of who they are), generated via the
    coaching follow-up, NOT a canned "you're in, start logging" template. The
    reflection is the retention moment; discarding it for boilerplate was the bug.
    """
    env = pipeline_env
    H = env["H"]
    addr, im_id = "+15550003333", "im:+15550003333"

    # Turn 1: first contact → scripted intro, returns (no LLM).
    env["set_llm"](text="")
    await H.run_imessage_pipeline(addr, f"iMessage;-;{addr}", "hey", message_guid="o0")
    intro_count = len(env["sent"])
    assert env["calls"]["chat"] == 0

    # Turn 2: the all-in-one brain dump → ONE update_profile (name+goal+weight+bonuses).
    # First pass writes no text (just the tool); the reflection comes from the follow-up.
    env["set_llm"](
        text="",
        tool_calls=[{"name": "update_profile", "input": {"fields": {
            "name": "Danny", "primary_goal": "cut",
            "current_weight_kg": 86.0, "goal_weight_kg": 80.0,
            "training_experience": "intermediate",
        }}}],
        follow_up_text=("got the full picture.|||190 to 178, and training's already "
                        "there.|||send me what you ate today, rough is fine."),
    )
    await H.run_imessage_pipeline(
        addr, f"iMessage;-;{addr}",
        "I'm Danny, cutting from 190 to 178, 6ft, lift 4x a week", message_guid="o1",
    )

    # Essentials saved once, onboarding auto-completed, check-ins enabled natively.
    async with env["Maker"]() as db:
        from db.queries import resolve_user
        from sqlalchemy import select as _select
        from db.models import UserPreferences
        u = await resolve_user(db, im_id)
        assert (u.name, u.primary_goal, u.current_weight_kg) == ("Danny", "cut", 86.0)
        assert u.onboarding_completed is True
        prefs = (await db.execute(
            _select(UserPreferences).where(UserPreferences.user_id == u.id)
        )).scalar_one()
        assert prefs.proactive_messaging_enabled is True, "check-ins should turn on at completion"

    # The reply REFLECTS what was understood, then drives to the first log — and it is
    # NOT the canned "you're in" boilerplate.
    new_bubbles = env["sent"][intro_count:]
    joined = " ".join(new_bubbles).lower()
    assert "—" not in " ".join(new_bubbles), new_bubbles
    assert ("190" in joined or "picture" in joined), f"reflection missing: {new_bubbles}"
    assert "today" in joined, f"should still drive to first log: {new_bubbles}"
    assert "you're in" not in joined, f"canned completion leaked: {new_bubbles}"
    assert env["calls"]["chat"] == 1
    assert env["calls"]["follow_up"] == 1  # reflection generated via the follow-up


@pytest.mark.asyncio
async def test_brain_dump_completion_keeps_first_pass_reflection(pipeline_env):
    """
    If the LLM reflects in the SAME response as the update_profile call (text block +
    tool block), that reflection must be kept — not overwritten by canned completion,
    and not regenerated via a redundant follow-up.
    """
    env = pipeline_env
    H = env["H"]
    addr, im_id = "+15550005555", "im:+15550005555"

    # First contact → scripted intro.
    env["set_llm"](text="")
    await H.run_imessage_pipeline(addr, f"iMessage;-;{addr}", "hey", message_guid="r0")
    intro_count = len(env["sent"])

    # Dump turn: the LLM writes the reflection inline AND calls update_profile.
    reflection = ("alright, got you.|||86kg now, chasing the cut.|||"
                  "send me what you ate today, rough is fine.")
    env["set_llm"](
        text=reflection,
        tool_calls=[{"name": "update_profile", "input": {"fields": {
            "name": "Mia", "primary_goal": "cut", "current_weight_kg": 86.0,
        }}}],
    )
    await H.run_imessage_pipeline(
        addr, f"iMessage;-;{addr}", "I'm Mia, cutting, 86kg", message_guid="r1",
    )

    new_bubbles = env["sent"][intro_count:]
    joined = " ".join(new_bubbles).lower()
    assert "got you" in joined or "chasing the cut" in joined, f"first-pass reflection dropped: {new_bubbles}"
    assert "you're in" not in joined, "canned completion overwrote the reflection"
    # No redundant follow-up when the first pass already produced the reflection.
    assert env["calls"]["follow_up"] == 0


@pytest.mark.asyncio
async def test_onboarding_completes_on_final_essential(pipeline_env):
    """Resume mid-onboarding: name+goal already known, the user gives weight, and
    that one essential flips onboarding complete (no re-asking the known fields)."""
    env = pipeline_env
    H = env["H"]
    im_id = await _seed_onboarding_user(
        env["Maker"], address="+15550004444", name="Danny", primary_goal="cut",
    )
    env["set_llm"](
        text="",
        tool_calls=[{"name": "update_profile",
                     "input": {"fields": {"current_weight_kg": 86.0}}}],
    )
    await H.run_imessage_pipeline(
        "+15550004444", "iMessage;-;+15550004444", "190 lbs", message_guid="o2",
    )
    async with env["Maker"]() as db:
        from db.queries import resolve_user
        u = await resolve_user(db, im_id)
        assert u.onboarding_completed is True
    assert "—" not in " ".join(env["sent"])
    assert len(env["sent"]) >= 1


@pytest.mark.asyncio
async def test_im_calculate_button_routes_through_run_turn_not_canned_card(pipeline_env):
    """
    A2/A3 behavior change: the stale "calculate for me" onboarding button no longer
    emits a canned completion bubble. It persists the targets, completes onboarding,
    enables check-ins ONCE, and FALLS THROUGH into run_turn so the just_completed
    reflection is voiced by the LLM. completion_facts (TDEE/goal) reach run_turn.
    """
    env = pipeline_env
    H = env["H"]
    addr, im_id = "+15550006666", "im:+15550006666"
    # All stats present so calc_targets succeeds; targets not yet set.
    await _seed_onboarding_user(
        env["Maker"], address=addr, name="Danny", primary_goal="cut",
        current_weight_kg=86.0, height_cm=178.0, age=31, sex="male",
    )
    # First pass writes the reflection inline → kept as the just_completed voice.
    env["set_llm"](
        text="alright, locked you in.|||~2,300 a day for the cut.|||"
             "send me what you ate today, rough is fine.",
    )
    await H.run_imessage_pipeline(addr, f"iMessage;-;{addr}", "Calculate for me",
                                  message_guid="calc1")

    async with env["Maker"]() as db:
        from db.queries import resolve_user
        from sqlalchemy import select as _select
        from db.models import UserPreferences
        u = await resolve_user(db, im_id)
        assert u.onboarding_completed is True
        prefs = (await db.execute(
            _select(UserPreferences).where(UserPreferences.user_id == u.id)
        )).scalar_one()
        assert prefs.proactive_messaging_enabled is True, "check-ins on at completion"
        assert prefs.calorie_target is not None, "targets persisted before run_turn"

    joined = " ".join(env["sent"]).lower()
    assert "—" not in " ".join(env["sent"]), env["sent"]
    # The LLM reflection is what the user sees, NOT the old canned "you're in 🎉" card.
    assert "locked you in" in joined or "cut" in joined, env["sent"]
    assert env["calls"]["chat"] == 1, "fell through to run_turn (one LLM pass)"


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
        # **kwargs absorbs forward-compat params like stream_handler (T2.1).
        # When streaming is on, run_turn passes stream_handler=... to chat();
        # we simulate streaming by emitting deltas to the handler so the test
        # path mirrors prod behavior (the handler accumulates and emits bubbles).
        async def _fake_chat(messages, system, tools=True, max_tokens=1024,
                             model=None, stream_handler=None, **kwargs):
            calls["chat"] += 1
            if stream_handler is not None and text:
                await stream_handler(text)
            return {"text": text, "tool_calls": tool_calls or [], "raw_content": [{"x": 1}]}
        async def _fake_follow_up(messages, raw, tcs, results, system,
                                  max_tokens=512, stream_handler=None, **kwargs):
            calls["follow_up"] += 1
            if stream_handler is not None and follow_up_text:
                await stream_handler(follow_up_text)
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


@pytest.mark.asyncio
async def test_tg_post_reset_first_message_shows_intro_not_name(tg_pipeline_env):
    """
    REGRESSION (Telegram bug 2): a fresh / post-reset user (no name, no prior convo)
    must get the scripted intro on their FIRST message — the message must NOT be
    treated as their name. Before the fix, _run_pipeline went straight to the
    GET_NAME onboarding prompt and saved 'hey there' as the user's name.
    """
    env = tg_pipeline_env
    env["set_llm"](text="should-not-be-called")  # intro is scripted, no LLM
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(
            env["update"], env["context"], "hey there", "text", db
        )
    assert env["calls"]["chat"] == 0, "intro must be scripted (no LLM call)"
    assert len(env["sent"]) >= 3, f"expected multi-bubble intro, got {env['sent']}"
    joined = " ".join(env["sent"]).lower()
    assert "call you" in joined or "your name" in joined
    # the first message was NOT saved as the name
    from db.queries import resolve_user
    async with env["Maker"]() as db:
        u = await resolve_user(db, str(_FakeUser.id))
        assert u.name is None, f"first message wrongly saved as name: {u.name!r}"


@pytest.mark.asyncio
async def test_tg_intro_logged_so_it_does_not_refire(tg_pipeline_env):
    """
    The intro is logged, so the user's SECOND message (their actual name) does not
    re-trigger the intro — it flows into the onboarding LLM instead. Guards against
    a double-intro loop.
    """
    env = tg_pipeline_env
    # Turn 1: first contact → scripted intro, logged, no LLM.
    env["set_llm"](text="should-not-be-called")
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(env["update"], env["context"], "hey", "text", db)
    assert env["calls"]["chat"] == 0
    intro_count = len(env["sent"])
    assert intro_count >= 3

    # Turn 2: the name reply. Intro must NOT re-fire; onboarding LLM runs instead.
    env["set_llm"](text="good to meet you, Daniel.|||what are you chasing right now?")
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(env["update"], env["context"], "Daniel", "text", db)
    assert env["calls"]["chat"] == 1, "second turn should hit the onboarding LLM"
    new_bubbles = env["sent"][intro_count:]
    assert new_bubbles, "second turn produced no reply"
    assert not any("call you" in b.lower() for b in new_bubbles), "intro re-fired"


@pytest.mark.asyncio
async def test_tg_skip_button_routes_through_run_turn_not_canned_card(tg_pipeline_env):
    """
    A2 behavior change (Telegram): the stale "Skip for now" button no longer emits
    the canned HTML welcome card. It completes onboarding, enables check-ins ONCE,
    and FALLS THROUGH into run_turn so the just_completed reflection is the voiced
    reply. No completion_facts on the skip path (no TDEE computed).
    """
    env = tg_pipeline_env
    from db.models import User, UserPreferences
    # Mid-onboarding user with the three essentials present but no targets yet.
    async with env["Maker"]() as db:
        u = User(telegram_id=str(_FakeUser.id), name="Danny",
                 onboarding_completed=False, primary_goal="cut",
                 current_weight_kg=86.0, timezone="America/New_York")
        db.add(u)
        await db.flush()
        db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=False))
        await db.commit()

    # The LLM voices the completion reflection on the fall-through.
    env["set_llm"](text="you're set.|||we'll dial targets in as we go.|||"
                        "what did you eat today? start there.")
    async with env["Maker"]() as db:
        await env["TH"]._run_pipeline(
            env["update"], env["context"], "Skip for now", "text", db
        )

    async with env["Maker"]() as db:
        from db.queries import resolve_user
        from sqlalchemy import select as _select
        u = await resolve_user(db, str(_FakeUser.id))
        assert u.onboarding_completed is True
        prefs = (await db.execute(
            _select(UserPreferences).where(UserPreferences.user_id == u.id)
        )).scalar_one()
        assert prefs.proactive_messaging_enabled is True, "check-ins on at completion"

    joined = " ".join(env["sent"]).lower()
    assert env["calls"]["chat"] == 1, "fell through to run_turn (one LLM pass)"
    assert "you're set" in joined or "start there" in joined, env["sent"]
    # Dashboard inline button still fires exactly once on just_completed.
    assert sum("dashboard is live" in s.lower() for s in env["sent"]) == 1, env["sent"]
