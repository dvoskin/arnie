"""H — ASK-FIRST mode-aware phantom (ASK_FIRST_HOLD, default OFF). In strict mode, a
claimed-but-unfired FOOD write with an unstated swing should HOLD + ask (stash for
the answer), NOT force-log. Off by default → the phantom force-logs as before."""
import pytest
from types import SimpleNamespace

import core.conversation as C
import core.clarify as CL
import core.orchestrator as O
import db.queries as Q
import reminders.lifecycle as RL
from core.conversation import run_turn


def _user(mode="strict"):
    return SimpleNamespace(
        id=1, onboarding_completed=True, timezone="UTC", name="Danny",
        primary_goal="recomp", nudges_sent="", log_unlocked_at="seeded",
        preferences=SimpleNamespace(calorie_target=2165, protein_target=180,
                                    food_logging_mode=mode))


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


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)
    monkeypatch.setenv("LOG_MARKER", "true")
    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)
    # pass-1: a FOOD phantom (claims log, fires nothing); the rescue re-prompt
    # (when H is off + orchestrator off) returns the real log_food call.
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        if "[SYSTEM HEALTH CHECK" in str(messages):
            return {"text": "", "raw_content": [], "stop_reason": "tool_use",
                    "tool_calls": [{"name": "log_food",
                                    "input": {"food_name": "chicken breast", "calories": 300}}]}
        return {"text": "Logged your chicken. [[DID: log_food]]", "raw_content": [],
                "tool_calls": [], "stop_reason": "end_turn"}
    monkeypatch.setattr(C, "chat", fake_chat)
    # the small caller derives the intended item.
    async def fake_orch(user_message, extra_context=""):
        return [{"name": "log_food", "input": {"food_name": "chicken breast", "calories": 300}}]
    monkeypatch.setattr(O, "call_tools", fake_orch)
    logged = []
    async def fake_exec(tcs, *a, **k):
        logged.extend((tc.get("input") or {}).get("food_name") for tc in tcs)
        return {tc["name"]: "Logged." for tc in tcs}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)
    monkeypatch._logged = logged


@pytest.mark.asyncio
async def test_ask_first_holds_phantom_and_asks(monkeypatch):
    monkeypatch.setenv("ASK_FIRST_HOLD", "true")
    async def fake_swing(tool_calls, tool_results, user, user_message=""):
        return "Quick one so it's right, was the chicken grilled or fried?"
    monkeypatch.setattr(CL, "clarify_swings", fake_swing)
    recorded = {}
    async def fake_pending(db, uid, kind=None, question=None, **kw):
        recorded["kind"] = kind
        recorded["question"] = question
        return SimpleNamespace(item_referenced=None, payload_json=None)
    monkeypatch.setattr(Q, "record_pending_question", fake_pending)

    turn = await run_turn(_user("strict"), _DB(), [{"role": "user", "content": "had chicken"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    assert "grilled or fried" in reply, f"should ASK before logging; got {reply!r}"
    assert recorded.get("kind") == "food_ask_first", "must stash a food_ask_first hold"
    assert not monkeypatch._logged, f"must NOT force-log the held meal; logged {monkeypatch._logged}"


@pytest.mark.asyncio
async def test_ask_first_off_force_logs(monkeypatch):
    monkeypatch.setenv("ASK_FIRST_HOLD", "false")   # default
    # Rescue re-derives + force-logs (the normal phantom path).
    async def fake_swing(*a, **k): return "should not be called"
    monkeypatch.setattr(CL, "clarify_swings", fake_swing)
    turn = await run_turn(_user("strict"), _DB(), [{"role": "user", "content": "had chicken"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    assert "chicken" in " ".join(monkeypatch._logged), \
        f"ask-first OFF must force-log the phantom; logged {monkeypatch._logged}"
