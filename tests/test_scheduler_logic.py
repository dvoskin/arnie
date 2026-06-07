"""Pure-logic gates that guard proactive outreach (overnight-spam prevention)."""
import os
import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import scheduler.proactive_scheduler as sched


def _row(source_type="text", raw_message="hi", response="reply", mins_ago=10):
    """Duck-typed ConversationLog row at a given age (newest-first lists in prod)."""
    ts = datetime.utcnow() - timedelta(minutes=mins_ago)
    return SimpleNamespace(
        source_type=source_type, raw_message=raw_message,
        response=response, timestamp=ts,
    )


def test_in_window():
    assert sched._in_window("12:00", "09:00", "21:00") is True
    assert sched._in_window("08:59", "09:00", "21:00") is False
    assert sched._in_window("21:01", "09:00", "21:00") is False
    assert sched._in_window("09:00", "09:00", "21:00") is True  # inclusive edges
    assert sched._in_window("21:00", "09:00", "21:00") is True


def test_has_timezone():
    assert sched._has_timezone(SimpleNamespace(timezone="America/New_York")) is True
    assert sched._has_timezone(SimpleNamespace(timezone="UTC")) is False  # unknown default
    assert sched._has_timezone(SimpleNamespace(timezone=None)) is False
    assert sched._has_timezone(SimpleNamespace(timezone="")) is False


def test_proactive_enabled_defaults_off(monkeypatch):
    monkeypatch.delenv("PROACTIVE_MESSAGING_ENABLED", raising=False)
    importlib.reload(sched)
    assert sched.proactive_enabled() is False
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    assert sched.proactive_enabled() is True
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "false")
    assert sched.proactive_enabled() is False


# ── Silence streak (D3) — derived from the shared newest-first window ───────────

def test_silence_streak_counts_consecutive_proactive_since_last_user_msg():
    # newest-first: two proactive check-ins on top of a user turn → streak 2
    rows = [
        _row(source_type="proactive", raw_message="", mins_ago=5),
        _row(source_type="proactive", raw_message="", mins_ago=60),
        _row(source_type="text", mins_ago=200),  # the user's last real turn
        _row(source_type="proactive", raw_message="", mins_ago=300),
    ]
    assert sched._silence_streak(rows) == 2


def test_silence_streak_zero_when_user_replied_most_recently():
    rows = [
        _row(source_type="text", mins_ago=5),
        _row(source_type="proactive", raw_message="", mins_ago=60),
    ]
    assert sched._silence_streak(rows) == 0


def test_silence_streak_all_proactive():
    rows = [_row(source_type="proactive", raw_message="", mins_ago=i * 30) for i in range(4)]
    assert sched._silence_streak(rows) == 4


def test_silence_streak_empty_window():
    assert sched._silence_streak([]) == 0


# ── _last_exchange counts USER messages only (D3 self-trigger fix) ──────────────

def test_last_exchange_ignores_proactive_rows():
    # a fresh proactive send sits on top of a 200-min-old user message; the
    # live-convo clock must read the USER message (200m), not the nudge (5m).
    rows = [
        _row(source_type="proactive", raw_message="", response="just checking in", mins_ago=5),
        _row(source_type="text", raw_message="had lunch", response="logged", mins_ago=200),
    ]
    mins, last_u, last_a = sched._last_exchange(rows)
    assert 199 < mins < 201            # the USER message age, not the nudge
    assert last_u == "had lunch"
    assert last_a == "logged"
    # and therefore NOT treated as live (a just-sent nudge can't self-trigger)
    assert sched._is_live_convo(mins) is False


def test_last_exchange_none_when_only_proactive():
    rows = [_row(source_type="proactive", raw_message="", mins_ago=5)]
    mins, last_u, last_a = sched._last_exchange(rows)
    assert mins is None
    assert (last_u, last_a) == ("", "")


def test_last_exchange_empty_window():
    assert sched._last_exchange([]) == (None, "", "")


# ── recent check-ins block (D2 continuity) ──────────────────────────────────────

def test_recent_checkins_block_lists_sent_nudges():
    rows = [
        _row(source_type="proactive", raw_message="", response="morning|||log breakfast", mins_ago=5),
        _row(source_type="proactive", raw_message="", response="still training today?", mins_ago=60),
    ]
    block = sched._recent_checkins_block(rows)
    assert "morning / log breakfast" in block   # ||| flattened for readability
    assert "still training today?" in block
    assert "do NOT repeat" in block


def test_recent_checkins_block_empty():
    assert sched._recent_checkins_block([]) == ""
    # rows present but all blank responses → still empty
    assert sched._recent_checkins_block([_row(source_type="proactive", response="")]) == ""


# ── INT-1 (c): proactive continuity is VOICED, not canned ───────────────────────
#
# The third user-facing new-path: a proactive nudge must be generated through the
# NUDGE_SYSTEM-voiced LLM path WITH the recent-check-ins block in scope (so it never
# repeats itself), NOT a hardcoded string. This asserts the observable: _llm_nudge
# returns the LLM's voiced text, and it fed NUDGE_SYSTEM + the recent block in.

async def test_llm_nudge_is_voiced_through_nudge_system_with_recent_block(monkeypatch):
    import core.llm as llm
    from core.prompts.nudges import NUDGE_SYSTEM

    captured = {}

    async def _fake_chat(messages, system, tools=True, max_tokens=1024, model=None):
        captured["system"] = system
        captured["prompt"] = messages[0]["content"]
        captured["tools"] = tools
        return {"text": "morning.|||hop on the scale.|||what's breakfast?",
                "tool_calls": [], "raw_content": None, "stop_reason": "end_turn"}

    # _llm_nudge does `from core.llm import chat` at call time → patch the source.
    monkeypatch.setattr(llm, "chat", _fake_chat)

    log = SimpleNamespace(
        total_calories=0, total_protein=0, total_water_ml=0,
        workout_completed=False, cardio_completed=False,
        food_entries=[], exercise_entries=[],
    )
    prefs = SimpleNamespace(calorie_target=2100, protein_target=180,
                            preferred_language="English")
    user = SimpleNamespace(primary_goal="cut", training_experience="intermediate",
                           dietary_preferences=None)
    # A recent proactive send that the nudge must not repeat.
    recent = [_row(source_type="proactive", raw_message="",
                   response="already pinged about lunch", mins_ago=120)]

    out = await sched._llm_nudge(user, log, prefs, None, "morning_checkin",
                                 "Danny", recent_proactive=recent)

    # Observable: the VOICED LLM text is returned (bubbles), not a canned constant.
    assert out == "morning.|||hop on the scale.|||what's breakfast?"
    assert "|||" in out
    # It went through the NUDGE_SYSTEM voice, tool-free.
    assert captured["system"] == NUDGE_SYSTEM
    assert captured["tools"] is False
    # And the recent-check-ins continuity block was in scope so it won't repeat.
    assert "already pinged about lunch" in captured["prompt"]
    assert "do NOT repeat" in captured["prompt"]
