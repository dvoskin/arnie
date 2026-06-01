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
    async def _noop(db, user):
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
