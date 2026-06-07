"""
run_turn self-heal: when the first LLM pass truncates (ran out of token budget) or
stalls on a dangling action-preamble ("Now logging everything:") with no tool calls,
run_turn must retry once and use the retry's result — never ship the broken preamble.

This is the guard behind the prod screenshots where Arnie sent "Now logging
everything:" / "estimating both:" and logged nothing.
"""
import pytest
from types import SimpleNamespace

import core.conversation as C
import reminders.lifecycle as RL
from core.conversation import run_turn


def _user():
    return SimpleNamespace(
        id=1, onboarding_completed=True, timezone="UTC", name="Danny",
        nudges_sent="", preferences=SimpleNamespace(calorie_target=2000, protein_target=180),
    )


@pytest.fixture(autouse=True)
def _noop_pending(monkeypatch):
    async def _noop(db, user, llm_reply_text=""):
        return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


def _seq_chat(results):
    """Return an async chat() stub that yields `results` in order, tracking call count."""
    state = {"n": 0}
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None):
        i = min(state["n"], len(results) - 1)
        state["n"] += 1
        return results[i]
    return fake_chat, state


@pytest.mark.asyncio
async def test_dangling_preamble_triggers_retry(monkeypatch):
    fake_chat, state = _seq_chat([
        {"text": "Now logging everything:", "tool_calls": [], "raw_content": [],
         "stop_reason": "end_turn"},                                   # dangling stall
        {"text": "logged it all, you're at 1,200 today.", "tool_calls": [],
         "raw_content": [], "stop_reason": "end_turn"},               # retry succeeds
    ])
    monkeypatch.setattr(C, "chat", fake_chat)

    turn = await run_turn(
        _user(), None, [{"role": "user", "content": "log my whole day"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
    )
    assert state["n"] == 2, "a dangling preamble must trigger exactly one retry"
    joined = " ".join(turn.response.bubbles).lower()
    assert "now logging everything:" not in joined, "the dangling preamble was shipped"
    assert "logged it all" in joined


@pytest.mark.asyncio
async def test_truncation_triggers_retry(monkeypatch):
    fake_chat, state = _seq_chat([
        {"text": "logging:", "tool_calls": [], "raw_content": [],
         "stop_reason": "max_tokens"},                                # truncated
        {"text": "done — logged all 7, you're at 2,630.", "tool_calls": [],
         "raw_content": [], "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(C, "chat", fake_chat)

    turn = await run_turn(
        _user(), None, [{"role": "user", "content": "huge food list"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
    )
    assert state["n"] == 2, "a truncated (max_tokens) first pass must retry"
    assert "logged all 7" in " ".join(turn.response.bubbles).lower()


@pytest.mark.asyncio
async def test_period_ending_narration_triggers_retry(monkeypatch):
    """
    REGRESSION: the dangling-stall detector used to only catch ':' endings. The
    move-to-yesterday loop stalled with PERIOD-ending narration ("Let me do that now.",
    "On it — clearing today and relogging.") which slipped through. These must retry too.
    """
    for stall_text in (
        "Let me do that now.",
        "On it — clearing today and relogging everything to yesterday.",
        "I need to delete all of today's entries and relog them to yesterday. Let me do that now.",
        "Let me handle this — deleting all of today's entries first, then relogging to yesterday.",
    ):
        fake_chat, state = _seq_chat([
            {"text": stall_text, "tool_calls": [], "raw_content": [],
             "stop_reason": "end_turn"},
            {"text": "moved it all to yesterday — that day's at 1,845 now.",
             "tool_calls": [], "raw_content": [], "stop_reason": "end_turn"},
        ])
        monkeypatch.setattr(C, "chat", fake_chat)
        turn = await run_turn(
            _user(), None, [{"role": "user", "content": "move today to yesterday"}],
            "SYS", "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
        )
        assert state["n"] == 2, f"narration should retry: {stall_text!r}"
        joined = " ".join(turn.response.bubbles).lower()
        assert "let me" not in joined and "on it" not in joined, \
            f"stall shipped instead of retry result: {turn.response.bubbles}"


@pytest.mark.asyncio
async def test_conversational_no_tool_reply_not_retried(monkeypatch):
    """A legit no-tool reply that happens to say 'let me know' must NOT be misread as a
    stall (guards against over-eager retry / false positives)."""
    fake_chat, state = _seq_chat([
        {"text": "solid day.|||let me know what you have for dinner and we'll close it out.",
         "tool_calls": [], "raw_content": [], "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(C, "chat", fake_chat)
    turn = await run_turn(
        _user(), None, [{"role": "user", "content": "that's it for lunch"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
    )
    assert state["n"] == 1, "'let me know' is conversational, not a stall — must not retry"


@pytest.mark.asyncio
async def test_bare_done_after_an_answer_is_repaired(monkeypatch):
    """
    The user answered a question and the model replied just "done." — a banned dead-end.
    With no tool calls, run_turn retries once for a substantive reply, and the bare
    "done" never reaches the user.
    """
    fake_chat, state = _seq_chat([
        {"text": "done.", "tool_calls": [], "raw_content": [], "stop_reason": "end_turn"},
        {"text": "got it, 2,000 a day is a fine base.|||that puts your cut around 1,650. "
                 "what's a normal breakfast look like?",
         "tool_calls": [], "raw_content": [], "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(C, "chat", fake_chat)

    turn = await run_turn(
        _user(), None, [{"role": "user", "content": "i usually eat around 2000 cals"}],
        "SYS", "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
    )
    assert state["n"] == 2, "a bare 'done' with no tools should trigger a repair retry"
    reply = " ".join(turn.response.bubbles).lower()
    assert reply.strip() != "done." and "done." not in turn.response.bubbles, \
        f"bare dead-end shipped: {turn.response.bubbles}"
    assert "breakfast" in reply or "1,650" in reply, "repair should be substantive"
    assert "dead_end" in turn.health_flags


@pytest.mark.asyncio
async def test_wall_of_text_is_flagged_not_retried(monkeypatch):
    """A reply over the bubble cap gets a wall_of_text health flag (telemetry only —
    it's not a stall or dead-end, so no retry)."""
    six = "|||".join(f"coaching point number {i} with real substance" for i in range(6))
    fake_chat, state = _seq_chat([
        {"text": six, "tool_calls": [], "raw_content": [], "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(C, "chat", fake_chat)
    turn = await run_turn(
        _user(), None, [{"role": "user", "content": "hey"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
    )
    assert state["n"] == 1, "a long-but-valid reply must NOT trigger a retry"
    assert "wall_of_text" in turn.health_flags
    assert len(turn.response.bubbles) == 6


@pytest.mark.asyncio
async def test_complete_turn_not_retried(monkeypatch):
    fake_chat, state = _seq_chat([
        {"text": "weight's up, not panic-worthy.|||we track the 7-day trend.",
         "tool_calls": [], "raw_content": [], "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(C, "chat", fake_chat)

    turn = await run_turn(
        _user(), None, [{"role": "user", "content": "my weight is up"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False, today_log=None,
    )
    assert state["n"] == 1, "a clean, complete turn must NOT retry"
    assert len(turn.response.bubbles) == 2
