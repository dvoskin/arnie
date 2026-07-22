"""run_turn integration: the ASK-FIRST hold NEVER loses a held meal (option A).

Turn 1 held the meal and stashed the log_food inputs on the pending
(payload_json). On the answer turn opus sometimes CLARIFY-LOOPS (fires no tool).
This proves that when the model loops, the stashed items are replayed
DETERMINISTICALLY through the executor — the meal is captured, not dropped.
"""
import json
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
                                    food_logging_mode="strict"),
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
async def test_ask_first_answer_replays_stash_when_model_loops(monkeypatch):
    monkeypatch.setenv("ASK_FIRST_HOLD", "true")

    # The model LOOPS on the answer — every pass fires NO tool, just another
    # question. Without the stash the held meal would be lost.
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        return {"text": "quick one, how much oil exactly?", "raw_content": [],
                "tool_calls": [], "stop_reason": "end_turn"}
    monkeypatch.setattr(C, "chat", fake_chat)

    # An OPEN ask-first hold with the turn-1 stash (what would have been logged).
    stash = [
        {"food_name": "chicken cutlet", "quantity": "half", "calories": 190,
         "protein": 22, "carbs": 8, "fats": 8},
        {"food_name": "white bread", "quantity": "1 slice", "calories": 80,
         "protein": 3, "carbs": 15, "fats": 1},
    ]
    pending = SimpleNamespace(
        id=7, kind="food_ask_first", item_referenced="chicken cutlet",
        payload_json=json.dumps(stash), answered_at=None, follow_up_count=0)

    async def fake_get_open(db, user_id, kind):
        return pending if kind == "food_ask_first" else None
    monkeypatch.setattr(Q, "get_open_pending_question", fake_get_open)

    exec_names = []
    async def fake_exec(tool_calls, *a, **k):
        names = [(tc.get("input") or {}).get("food_name") for tc in tool_calls]
        exec_names.extend(names)
        return {"log_food": "Logged: " + ", ".join(str(n) for n in names)}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    monkeypatch.setattr(C, "deterministic_confirmation",
                        lambda *a, **k: "chicken cutlet and white bread logged.")

    async def fake_reload(db, uid):
        return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    async def fake_voice(tool_calls, tool_results, log, user):
        return None
    monkeypatch.setattr(C, "voice_log", fake_voice)
    monkeypatch.setattr(LV, "voice_log", fake_voice)

    turn = await run_turn(
        _user(), _DB(),
        [{"role": "user", "content": "it was fried and the bread was plain"}],
        "SYS", "imessage", in_onboarding=False, was_onboarding=False,
        today_log=_today_log(),
    )

    # Both stashed items were logged via the deterministic replay — nothing lost.
    assert "chicken cutlet" in exec_names, f"stash NOT replayed; executor got {exec_names}"
    assert "white bread" in exec_names, f"second stashed item lost; executor got {exec_names}"
    # The pending was resolved so it never re-asks.
    assert pending.answered_at is not None
    # The user-facing reply is the clean confirmation, not the model's loop question.
    reply = "|||".join(turn.response.bubbles) if turn.response else ""
    assert "how much oil" not in reply.lower()
