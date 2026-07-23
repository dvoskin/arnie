"""Tool-caller orchestrator (I) — the small/fast tool-only caller. Default OFF,
never raises, emits calls for a report and nothing for chit-chat."""
import pytest
import core.orchestrator as O


def test_orchestrator_default_on_and_revertable(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR", raising=False)
    assert O.orchestrator_enabled() is True    # default ON (deep-session A/B backed)
    monkeypatch.setenv("ORCHESTRATOR", "false")
    assert O.orchestrator_enabled() is False   # reverts cleanly


def test_orchestrator_uses_a_small_model(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_MODEL", raising=False)
    assert "haiku" in O.orchestrator_model().lower()


@pytest.mark.asyncio
async def test_call_tools_returns_the_calls(monkeypatch):
    seen = {}
    async def fake_chat(messages, system, tools=True, max_tokens=600, model=None, **k):
        seen["tools"] = tools
        seen["model"] = model
        return {"tool_calls": [{"name": "log_food", "input": {"food_name": "eggs"}}],
                "text": "", "raw_content": []}
    monkeypatch.setattr(O, "chat", fake_chat)

    calls = await O.call_tools("had 2 eggs")
    assert calls == [{"name": "log_food", "input": {"food_name": "eggs"}}]
    assert seen["tools"] is True, "orchestrator must get the tool registry"
    assert "haiku" in (seen["model"] or "").lower(), "should run on the small model"


@pytest.mark.asyncio
async def test_call_tools_empty_on_blank_message():
    assert await O.call_tools("") == []
    assert await O.call_tools("   ") == []


@pytest.mark.asyncio
async def test_call_tools_never_raises(monkeypatch):
    async def boom(*a, **k): raise RuntimeError("api down")
    monkeypatch.setattr(O, "chat", boom)
    # Must degrade to [] so the caller falls back to the normal pass.
    assert await O.call_tools("had a bagel") == []


# ── Integration: the orchestrator catches a full phantom PROACTIVELY ─────────────
from types import SimpleNamespace
import core.conversation as C
import db.queries as Q
import reminders.lifecycle as RL
from core.conversation import run_turn


def _user():
    return SimpleNamespace(
        id=1, onboarding_completed=True, timezone="UTC", name="Danny",
        primary_goal="recomp", nudges_sent="", log_unlocked_at="seeded",
        preferences=SimpleNamespace(calorie_target=2165, protein_target=180,
                                    food_logging_mode="moderate"))


class _DB:
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
    return SimpleNamespace(id=1, total_calories=0, total_protein=0, total_carbs=0,
                          total_fats=0, total_water_ml=0, workout_completed=False,
                          cardio_completed=False, food_entries=[], exercise_entries=[])


@pytest.mark.asyncio
async def test_orchestrator_catches_phantom_without_reprompt(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR", "true")
    monkeypatch.setenv("PHANTOM_RESCUE_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_FOOD", "false")   # exercise the legacy net
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)
    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    chat_calls = {"n": 0}
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **k):
        chat_calls["n"] += 1                       # pass-1: worded phantom, no tool
        return {"text": "Eggs logged, 140 cal and 12g protein on the board.",
                "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
    monkeypatch.setattr(C, "chat", fake_chat)

    async def fake_orch(user_message, extra_context=""):
        return [{"name": "log_food", "input": {"food_name": "eggs", "calories": 140}}]
    monkeypatch.setattr(O, "call_tools", fake_orch)

    logged = []
    async def fake_exec(tcs, *a, **k):
        logged.extend((tc.get("input") or {}).get("food_name") for tc in tcs)
        return {"log_food": "Logged: eggs"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    turn = await run_turn(_user(), _DB(), [{"role": "user", "content": "had 2 eggs"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())

    assert "eggs" in logged, f"orchestrator should have caught the drop; got {logged}"
    assert chat_calls["n"] == 1, \
        "orchestrator path must NOT re-prompt the big model (only pass-1 ran)"
