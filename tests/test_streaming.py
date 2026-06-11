"""
T2.1 — Tests for Telegram streaming via ||| bubble emission.

The big perceived-UX win in the unified rewrite. Pre-T2.1, every tool turn made
the user wait 6-10s for the full LLM response before any bubble landed. Now the
LLM streams text; each completed ||| bubble flushes to Telegram as soon as it's
complete. First bubble lands in <1.5s; subsequent bubbles arrive at LLM gen
speed (no artificial 250ms pauses).

These tests pin the contract:
  - _BubbleStreamer flushes per ||| during streaming, trailing buffer on finalize
  - run_turn surfaces streamed_bubble_count so the handler knows what NOT to re-send
  - Streaming path leaves untouched bubbles for the handler (dashboard link extras)
  - Non-streaming mode (iMessage / no on_text_bubble) keeps existing buffered behavior
"""
import pytest
from types import SimpleNamespace

import core.conversation as C
from core.conversation import _BubbleStreamer


async def _async_return(value):
    """Wrap a value in an awaitable so monkeypatched async funcs return it cleanly."""
    return value


# ── _BubbleStreamer unit tests ──────────────────────────────────────────────


async def test_streamer_flushes_one_bubble_per_separator():
    """The core contract: every ||| in the stream becomes a separate bubble."""
    seen: list[str] = []

    async def _on_bubble(text):
        seen.append(text)

    s = _BubbleStreamer(_on_bubble)
    # Simulate a typical streaming pattern: many small deltas, |||  arrives
    # in the middle of one delta (the model didn't break mid-token).
    for delta in ["Hey ", "Danny, ", "logged ✅", "|||", "you're at ",
                  "1840 cal", "|||", "what's dinner?"]:
        await s.on_delta(delta)
    # Last bubble has no trailing |||; finalize flushes it.
    await s.finalize()

    assert seen == ["Hey Danny, logged ✅", "you're at 1840 cal", "what's dinner?"]
    assert s.flushed_count == 3


async def test_streamer_handles_separator_split_across_deltas():
    """The ||| may arrive across delta boundaries (e.g. '|' + '||' or '||' + '|').
    The streamer must NOT split incorrectly on a partial separator."""
    seen: list[str] = []

    async def _on_bubble(text):
        seen.append(text)

    s = _BubbleStreamer(_on_bubble)
    # The ||| arrives across THREE deltas: "|", "|", "|".
    for delta in ["first", "|", "|", "|", "second"]:
        await s.on_delta(delta)
    await s.finalize()

    assert seen == ["first", "second"]


async def test_streamer_skips_empty_or_whitespace_only_bubbles():
    """Successive ||| (e.g. '|||  |||') shouldn't flush a blank bubble — that
    would land as an empty Telegram message."""
    seen: list[str] = []

    async def _on_bubble(text):
        seen.append(text)

    s = _BubbleStreamer(_on_bubble)
    await s.on_delta("first|||   |||second")
    await s.finalize()

    assert seen == ["first", "second"]


async def test_streamer_finalize_idempotent_no_trailing_buffer():
    """finalize() with an empty trailing buffer is a no-op (no double-flush)."""
    seen: list[str] = []

    async def _on_bubble(text):
        seen.append(text)

    s = _BubbleStreamer(_on_bubble)
    # Stream ends EXACTLY on a ||| boundary — buffer is empty post-flush.
    await s.on_delta("only-bubble|||")
    await s.finalize()
    await s.finalize()  # second finalize must not double-send

    assert seen == ["only-bubble"]
    assert s.flushed_count == 1


async def test_streamer_keeps_flushing_when_on_bubble_raises():
    """A flaky network on a single bubble must NOT abort the whole stream —
    log + continue is the right call (we'd rather lose one bubble than the turn)."""
    seen: list[str] = []
    fail_on_second = {"i": 0}

    async def _on_bubble(text):
        fail_on_second["i"] += 1
        if fail_on_second["i"] == 2:
            raise RuntimeError("simulated send fail")
        seen.append(text)

    s = _BubbleStreamer(_on_bubble)
    await s.on_delta("a|||b|||c")
    await s.finalize()

    # First and third bubble landed; second was lost but didn't kill the stream.
    assert seen == ["a", "c"]


# ── Integration: run_turn populates streamed_bubble_count ───────────────────


@pytest.fixture
async def _stream_env(monkeypatch):
    """Minimal run_turn harness — fake user, fake DB, fakes for chat /
    chat_follow_up / execute_tool_calls so we can drive run_turn deterministically.
    chat() invokes stream_handler with the full text if provided."""
    user = SimpleNamespace(
        id=1, telegram_id="42", name="Danny", timezone="America/New_York",
        onboarding_completed=True,
        preferences=SimpleNamespace(calorie_target=2100, protein_target=180,
                                    food_logging_mode="moderate"),
        nudges_sent="",
    )

    class _FakeDB:
        async def refresh(self, *_): pass
        async def commit(self): pass
        def add(self, *_): pass
        async def flush(self): pass
        async def execute(self, *_, **__):
            # The user fixture is what `reload_user(db, user_id)` re-fetches —
            # return it from scalar_one(); any other query returns empties.
            _u = user

            class _R:
                def scalar_one(_self): return _u
                def scalar_one_or_none(_self): return None
                def scalars(_self):
                    class _S:
                        def all(__): return []
                        def first(__): return None
                    return _S()
                def scalar(_self): return 0
            return _R()
    db = _FakeDB()

    # Pre-patch helpers run_turn calls after tool execution: get_or_create_today_log
    # (returns a minimal log-like object), get_or_create_webhook_token (used only on
    # the dashboard-link path, won't fire in these tests since nudges_sent is "").
    async def _fake_get_or_create_today_log(db, user_id, tz):
        return SimpleNamespace(
            id=99, total_calories=0, total_protein=0, total_carbs=0,
            total_fats=0, total_water_ml=0,
            workout_completed=False, cardio_completed=False,
            food_entries=[], exercise_entries=[],
        )

    async def _fake_sync_pending(db, user, llm_reply_text="", **kwargs):
        pass

    import db.queries as _DBQ
    monkeypatch.setattr(_DBQ, "get_or_create_today_log",
                        _fake_get_or_create_today_log)
    monkeypatch.setattr(_DBQ, "reload_user",
                        lambda db, uid: _async_return(user))
    import reminders.lifecycle as _RL
    monkeypatch.setattr(_RL, "sync_pending_questions", _fake_sync_pending)

    # Default fake_chat: streams the full text via stream_handler, no tool calls.
    state = {"chat_text": "Hey.|||Logged.|||What's next?", "tool_calls": None,
             "follow_up_text": "Logged it.|||Onward.", "stop_reason": "end_turn"}

    async def _fake_chat(messages, system, tools=True, max_tokens=1024,
                         model=None, stream_handler=None, **kwargs):
        if stream_handler is not None and state["chat_text"]:
            await stream_handler(state["chat_text"])
        return {"text": state["chat_text"], "tool_calls": state["tool_calls"] or [],
                "raw_content": [{"x": 1}], "stop_reason": state["stop_reason"]}

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None, **kwargs):
        if stream_handler is not None and state["follow_up_text"]:
            await stream_handler(state["follow_up_text"])
        return state["follow_up_text"]

    async def _fake_execute(tool_calls, user, log, db, source_type):
        return {tc["name"]: "Logged ✅" for tc in (tool_calls or [])}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    yield {"user": user, "db": db, "state": state}


async def test_run_turn_streams_bubbles_when_on_text_bubble_provided(_stream_env):
    """When the handler provides on_text_bubble, each ||| bubble flushes via
    the callback DURING the stream. The handler then sends bubbles[streamed:]."""
    env = _stream_env
    streamed: list[str] = []

    async def _on_bubble(text):
        streamed.append(text)

    turn = await C.run_turn(
        env["user"], env["db"],
        messages=[{"role": "user", "content": "had a coffee"}],
        system="SYS", platform="telegram",
        in_onboarding=False, was_onboarding=False,
        on_text_bubble=_on_bubble,
    )

    # All 3 bubbles streamed via the callback (no tool calls → no follow-up).
    assert streamed == ["Hey.", "Logged.", "What's next?"]
    assert turn.streamed_bubble_count == 3
    # response_text matches and resp.bubbles aligns 1:1.
    assert len(turn.response.bubbles) == 3
    # The handler subtracts streamed_bubble_count → sends nothing extra.
    assert turn.response.bubbles[turn.streamed_bubble_count:] == []


async def test_run_turn_buffered_path_unchanged_when_no_on_text_bubble(_stream_env):
    """iMessage path: no on_text_bubble → existing buffered behavior. The
    streamed_bubble_count is 0 so the handler iterates all bubbles."""
    env = _stream_env

    turn = await C.run_turn(
        env["user"], env["db"],
        messages=[{"role": "user", "content": "had a coffee"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )

    assert turn.streamed_bubble_count == 0
    assert len(turn.response.bubbles) == 3


async def test_streaming_with_tool_calls_flushes_first_pass_then_follow_up(_stream_env):
    """Tool-call turn: first-pass text streams, tools run, follow-up text streams.
    streamed_bubble_count = total bubbles from BOTH passes."""
    env = _stream_env
    # First pass: 2 bubbles + tool call. Follow-up: 2 bubbles.
    env["state"]["chat_text"] = "logged that.|||quick read coming"
    env["state"]["tool_calls"] = [{"name": "log_food", "id": "t1",
                                   "input": {"food_name": "coffee"}}]
    env["state"]["stop_reason"] = "tool_use"
    env["state"]["follow_up_text"] = "good morning hit.|||what's lunch?"

    streamed: list[str] = []

    async def _on_bubble(text):
        streamed.append(text)

    turn = await C.run_turn(
        env["user"], env["db"],
        messages=[{"role": "user", "content": "coffee"}],
        system="SYS", platform="telegram",
        in_onboarding=False, was_onboarding=False,
        on_text_bubble=_on_bubble,
    )

    # All 4 bubbles streamed: 2 from first pass + 2 from follow-up.
    assert streamed == ["logged that.", "quick read coming",
                        "good morning hit.", "what's lunch?"]
    assert turn.streamed_bubble_count == 4


async def test_streaming_falls_back_emit_when_deterministic_confirmation_fires(_stream_env):
    """When chat() returns NO text and no follow-up text either, run_turn
    falls back to deterministic_confirmation. In streaming mode that fallback
    must ALSO be sent via on_text_bubble (post-build catch-up loop)."""
    env = _stream_env
    env["state"]["chat_text"] = ""
    env["state"]["tool_calls"] = [{"name": "log_water", "id": "t1",
                                   "input": {"amount_ml": 500}}]
    env["state"]["stop_reason"] = "tool_use"
    env["state"]["follow_up_text"] = ""  # follow-up also empty

    streamed: list[str] = []

    async def _on_bubble(text):
        streamed.append(text)

    turn = await C.run_turn(
        env["user"], env["db"],
        messages=[{"role": "user", "content": "drank some water"}],
        system="SYS", platform="telegram",
        in_onboarding=False, was_onboarding=False,
        on_text_bubble=_on_bubble,
    )

    # The deterministic_confirmation message (e.g. "Water logged 💧|||Keep sipping.")
    # was emitted via on_text_bubble post-build, NOT lost.
    assert len(streamed) >= 1, "deterministic fallback must reach the user via stream"
    assert turn.streamed_bubble_count == len(turn.response.bubbles)


# ── REGRESSION GUARD — the heads-up bug from the Royo challah incident ─────


async def test_heads_up_streamed_then_followup_fails_still_delivers_answer(_stream_env):
    """REGRESSION: a user typing 'Check online' caused Arnie to stream the
    web_search heads-up bubble ("lemme look that up real quick 🔎") but then
    the follow-up returned empty (Tavily error / re-voice fail). The old
    index-based catch-up saw flushed_count(1) == len(resp.bubbles)(1) and
    emitted nothing — leaving the user staring at a heads-up for 5+ minutes
    with no real answer. The fix tracks _response_streamed: when the final
    response_text came from a non-streamed fallback, ALL resp.bubbles emit
    via on_text_bubble regardless of what was already streamed."""
    env = _stream_env
    # First pass streams a heads-up + emits a web_search tool call.
    env["state"]["chat_text"] = "lemme look that up real quick 🔎"
    env["state"]["tool_calls"] = [{"name": "web_search", "id": "t1",
                                   "input": {"query": "royo challah roll calories"}}]
    env["state"]["stop_reason"] = "tool_use"
    # Follow-up returns EMPTY (simulating Tavily error / re-voice fail).
    env["state"]["follow_up_text"] = ""

    streamed: list[str] = []

    async def _on_bubble(text):
        streamed.append(text)

    turn = await C.run_turn(
        env["user"], env["db"],
        messages=[{"role": "user", "content": "Check online"}],
        system="SYS", platform="telegram",
        in_onboarding=False, was_onboarding=False,
        on_text_bubble=_on_bubble,
    )

    # The user MUST see something after the heads-up — a fallback answer,
    # an honest "I couldn't pull that up", anything. Pre-fix this assertion
    # would have failed with len(streamed) == 1 (just the heads-up).
    assert len(streamed) >= 2, (
        f"User saw {len(streamed)} bubble(s); the heads-up landed but no "
        f"real answer followed — the exact bug from the screenshot."
    )
    # First was the heads-up that streamed during the first pass.
    assert "look that up" in streamed[0].lower()
    # The rest is the fallback answer that the catch-up correctly emitted.
    assert any(b.strip() for b in streamed[1:])
