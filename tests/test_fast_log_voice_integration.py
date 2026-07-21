"""
run_turn integration: a pure food-log turn must ship ONE clean reply (the fast voice)
and never the follow-up + deterministic DOUBLE the four screenshots showed (2026-07-21,
Twix / corn / Quest / Core Power).

Streaming mode is required because the double was a streaming artifact: the follow-up
streamed one reply and the deterministic confirmation shipped another right after it.
This drives run_turn with an on_text_bubble sink and asserts exactly the fast-voice
bubbles reach the client — no "good room left" / "protein-first next" tail behind them.
"""
import pytest
from types import SimpleNamespace

import core.conversation as C
import core.log_voice as LV
import db.queries as Q
import reminders.lifecycle as RL
from core.conversation import run_turn


def _user():
    return SimpleNamespace(
        id=1, onboarding_completed=True, timezone="UTC", name="Danny",
        primary_goal="recomp", nudges_sent="", log_unlocked_at="seeded",
        preferences=SimpleNamespace(calorie_target=2165, protein_target=180),
    )


class _DB:
    """Async DB stub — the peripheral reads (cards, achievements, telemetry) are all
    wrapped in try/except in run_turn, so benign no-ops are enough."""
    async def refresh(self, *a, **k): pass
    async def commit(self, *a, **k): pass
    async def rollback(self, *a, **k): pass

    async def execute(self, *a, **k):
        class _R:
            def scalar_one_or_none(self): return None
            def scalars(self): return self
            def all(self): return []
            def first(self): return None
            def scalar(self): return None
        return _R()


def _today_log():
    # id=None so run_turn skips db.refresh; totals are the committed day so far.
    return SimpleNamespace(
        id=None, total_calories=1527, total_protein=91, total_carbs=0,
        total_fats=0, total_water_ml=0, workout_completed=False,
        cardio_completed=False, food_entries=[], exercise_entries=[],
    )


@pytest.fixture(autouse=True)
def _noop_pending(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs):
        return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


@pytest.mark.asyncio
async def test_pure_food_log_ships_one_reply_no_double(monkeypatch):
    calls = {"chat": 0}

    # pass-1: model calls log_food and writes NO prose of its own.
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        calls["chat"] += 1
        return {"text": "", "raw_content": [{"type": "text", "text": ""}],
                "tool_calls": [{"name": "log_food", "input": {"food_name": "Twix bar"}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    async def fake_exec(*a, **k):
        return {"log_food": "Logged: Twix bar, 250 cal, 2g protein"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid):
        return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    # the fast voice returns its clean 2-bubble read (fixed for determinism)
    async def fake_voice(tool_calls, tool_results, log, user):
        return ("Twix is in, 250 cal and nothing behind it on protein.|||"
                "638 and 91g left, so dinner has to carry the protein.")
    monkeypatch.setattr(C, "voice_log", fake_voice)      # the binding run_turn calls
    monkeypatch.setattr(LV, "voice_log", fake_voice)

    sent = []
    async def on_text_bubble(b):
        sent.append(b)

    turn = await run_turn(
        _user(), _DB(), [{"role": "user", "content": "Twix bar"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False,
        today_log=_today_log(), on_text_bubble=on_text_bubble,
    )

    # EXACTLY the two fast-voice bubbles reached the client — nothing else.
    assert sent == [
        "Twix is in, 250 cal and nothing behind it on protein.",
        "638 and 91g left, so dinner has to carry the protein.",
    ], f"expected one clean reply, got {len(sent)} bubbles: {sent}"

    # the deterministic template tail must NOT have shipped behind it (the double)
    joined = " ".join(sent).lower()
    assert "good room left" not in joined, "deterministic tail leaked — the double is back"
    assert "protein-first next" not in joined, "deterministic tail leaked — the double is back"
    assert "logged." not in joined, "terse 'X logged.' template tail leaked — the double"

    assert len(turn.response.bubbles) == 2
    assert calls["chat"] == 1, f"pure log should be ONE model call, was {calls['chat']}"


@pytest.mark.asyncio
async def test_voice_log_miss_falls_to_deterministic_not_legacy_double(monkeypatch):
    """When voice_log returns None (a transient Sonnet miss), a pure food log must
    fall to the deterministic confirmation as a SINGLE source — NEVER the legacy
    follow-up, whose stream + catch-up is the double (Danny 17:23: the template
    reappeared with a long hidden reply + a late card)."""
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        return {"text": "", "raw_content": [{"type": "text", "text": ""}],
                "tool_calls": [{"name": "log_food", "input": {"food_name": "Twix bar"}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    async def fake_exec(*a, **k):
        return {"log_food": "Logged: Twix bar, 250 cal, 2g protein"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid):
        return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    async def fake_voice_miss(*a, **k):
        return None                      # the transient miss
    monkeypatch.setattr(C, "voice_log", fake_voice_miss)

    called = {"followup": 0}
    async def fake_followup(*a, **k):
        called["followup"] += 1
        return "LEGACY FOLLOW-UP TEXT THAT MUST NEVER SHIP ON A PURE FOOD LOG"
    monkeypatch.setattr(C, "chat_follow_up", fake_followup)

    sent = []
    async def on_text_bubble(b):
        sent.append(b)

    turn = await run_turn(
        _user(), _DB(), [{"role": "user", "content": "Twix bar"}], "SYS",
        "imessage", in_onboarding=False, was_onboarding=False,
        today_log=_today_log(), on_text_bubble=on_text_bubble,
    )

    joined = " ".join(sent)
    assert called["followup"] == 0, "legacy chat_follow_up was called on a pure food log (the double path)"
    assert "LEGACY FOLLOW-UP" not in joined, "legacy follow-up text reached the user (the double)"
    assert any("Twix bar logged" in b for b in sent), f"expected deterministic confirmation, got {sent}"
