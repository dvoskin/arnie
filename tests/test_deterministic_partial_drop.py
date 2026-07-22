"""run_turn integration: the DETERMINISTIC partial-drop net (2026-07-21).

When pass-1 logs only some of a multi-item meal, the scribe (mocked here) finds
the full list and the missing item is logged DIRECTLY from the scribe's macros
through the executor — NO second Opus call. Proves: the drop is caught, the
executor gets the missing item, and pass-1 fired exactly ONE model call.
"""
import pytest
from types import SimpleNamespace

import core.conversation as C
import core.log_voice as LV
import core.scribe as SC
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
        id=None, total_calories=500, total_protein=40, total_carbs=0,
        total_fats=0, total_water_ml=0, workout_completed=False,
        cardio_completed=False, food_entries=[], exercise_entries=[],
    )


@pytest.fixture(autouse=True)
def _noop_pending(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs):
        return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


@pytest.mark.asyncio
async def test_deterministic_partial_drop_logs_missing_without_opus(monkeypatch):
    monkeypatch.setenv("SCRIBE_ENABLED", "true")
    calls = {"chat": 0}

    # pass-1 logs ONLY the turkey — drops the rice.
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        calls["chat"] += 1
        return {"text": "", "raw_content": [],
                "tool_calls": [{"name": "log_food",
                                "input": {"food_name": "Ground turkey", "quantity": "175g"}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    # scribe finds BOTH, with macros (mocked — no real Haiku).
    async def fake_extract(msg):
        return [
            {"name": "turkey", "quantity": "175g", "calories": 287, "protein": 54, "carbs": 0, "fats": 7},
            {"name": "rice", "quantity": "100g", "calories": 130, "protein": 3, "carbs": 28, "fats": 0},
        ]
    monkeypatch.setattr(SC, "extract_food_items", fake_extract)

    exec_names = []
    async def fake_exec(tool_calls, *a, **k):
        names = [(tc.get("input") or {}).get("food_name") for tc in tool_calls]
        exec_names.extend(names)
        return {"log_food": "Logged: " + ", ".join(str(n) for n in names)}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid):
        return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    async def fake_voice(tool_calls, tool_results, log, user):
        return "turkey and rice logged, you're on pace."
    monkeypatch.setattr(C, "voice_log", fake_voice)
    monkeypatch.setattr(LV, "voice_log", fake_voice)

    turn = await run_turn(
        _user(), _DB(), [{"role": "user", "content": "175g turkey and 100g rice"}],
        "SYS", "imessage", in_onboarding=False, was_onboarding=False,
        today_log=_today_log(),
    )

    # The dropped rice was logged DIRECTLY (fuzzy-picked as the missing item).
    assert "rice" in exec_names, f"missing rice was NOT deterministically logged; executor got {exec_names}"
    assert "Ground turkey" in exec_names, "pass-1 turkey should have gone through the executor"
    # And it cost NO extra Opus call — pass-1 was the only model call.
    assert calls["chat"] == 1, f"deterministic drop must add no Opus call; chat fired {calls['chat']}x"
