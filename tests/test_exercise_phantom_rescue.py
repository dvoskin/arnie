"""run_turn integration: a phantom set (claimed, not written) is force-logged.

Danny 2026-07-23: opus replied "🏋️ … 60×13" but fired no log_exercise, so the set
vanished. This proves the exercise-phantom trigger force-logs it through the same
rescue that handles food phantoms.
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
        preferences=SimpleNamespace(calorie_target=2165, protein_target=180,
                                    food_logging_mode="moderate"),
    )


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
    return SimpleNamespace(
        id=None, total_calories=0, total_protein=0, total_carbs=0, total_fats=0,
        total_water_ml=0, workout_completed=False, cardio_completed=False,
        food_entries=[], exercise_entries=[])


@pytest.fixture(autouse=True)
def _noop_pending(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


@pytest.mark.asyncio
async def test_phantom_set_is_force_logged(monkeypatch):
    monkeypatch.setenv("EXERCISE_PHANTOM", "true")
    calls = {"n": 0}

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # pass-1: narrates a logged set but fires NO tool (the phantom).
            return {"text": "🏋️ Low-to-High Fly · set 2, 60×13, matched it.",
                    "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
        # rescue force-pass: actually logs the set.
        return {"text": "Logged.", "raw_content": [],
                "tool_calls": [{"name": "log_exercise",
                                "input": {"exercise_name": "Low-to-High Fly",
                                          "sets": 1, "reps": "13", "weight": 60}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    exec_names = []
    async def fake_exec(tool_calls, *a, **k):
        names = [(tc.get("input") or {}).get("exercise_name") for tc in tool_calls]
        exec_names.extend(n for n in names if n)
        return {"log_exercise": "Logged: " + ", ".join(str(n) for n in names)}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    turn = await run_turn(
        _user(), _DB(), [{"role": "user", "content": "60x13"}],
        "SYS", "imessage", in_onboarding=False, was_onboarding=False,
        today_log=_today_log())

    # The phantom set was force-logged through the executor.
    assert "Low-to-High Fly" in exec_names, f"phantom set NOT force-logged; got {exec_names}"
