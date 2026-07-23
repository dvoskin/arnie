"""D — marker-gated deterministic fast-path (LOG_FASTPATH, default OFF). When the
manifest is present AND a real log tool fired, the write is confirmed: ship the
deterministic confirmation (real DB numbers, zero model latency) and SKIP the
voice_log model pass. Off by default → voice_log still runs. Never fails a
confirmation (falls through to voice_log when the marker is absent)."""
import pytest
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
    return SimpleNamespace(id=1, total_calories=140, total_protein=12, total_carbs=1,
                          total_fats=10, total_water_ml=0, workout_completed=False,
                          cardio_completed=False, food_entries=[], exercise_entries=[])


def _lf(name="eggs"):
    return {"name": "log_food", "input": {"food_name": name, "calories": 140, "protein": 12}}


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)
    monkeypatch.setenv("LOG_MARKER", "true")
    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        return {"text": "Logged your eggs, solid protein start. [[DID: log_food]]",
                "raw_content": [], "tool_calls": [_lf("eggs")], "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)
    async def fake_exec(tcs, *a, **k): return {"log_food": "Logged: eggs"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)


async def _run_counting_voice_log(monkeypatch):
    calls = {"voice": 0}
    async def fake_voice(*a, **k):
        calls["voice"] += 1
        return "VOICE_LOG_OUTPUT"
    monkeypatch.setattr(C, "voice_log", fake_voice)
    monkeypatch.setattr(C, "deterministic_confirmation", lambda *a, **k: "DETERMINISTIC_OK")
    turn = await run_turn(_user(), _DB(), [{"role": "user", "content": "had 2 eggs"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    return calls, reply


@pytest.mark.asyncio
async def test_fastpath_on_skips_voice_log(monkeypatch):
    monkeypatch.setenv("LOG_FASTPATH", "true")
    calls, reply = await _run_counting_voice_log(monkeypatch)
    assert calls["voice"] == 0, "fast-path must SKIP the voice_log model pass"
    assert "DETERMINISTIC_OK" in reply, f"should ship deterministic confirmation; got {reply!r}"


@pytest.mark.asyncio
async def test_fastpath_off_uses_voice_log(monkeypatch):
    monkeypatch.setenv("LOG_FASTPATH", "false")   # default
    calls, reply = await _run_counting_voice_log(monkeypatch)
    assert calls["voice"] == 1, "default (off) must still use voice_log"
    assert "VOICE_LOG_OUTPUT" in reply


@pytest.mark.asyncio
async def test_fastpath_without_marker_falls_through(monkeypatch):
    """LOG_FASTPATH on but the model forgot the manifest → voice_log still runs
    (never fails a confirmation)."""
    monkeypatch.setenv("LOG_FASTPATH", "true")
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        return {"text": "Logged your eggs.", "raw_content": [],   # NO [[DID]] / [[LOGGED]]
                "tool_calls": [_lf("eggs")], "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)
    calls, reply = await _run_counting_voice_log(monkeypatch)
    assert calls["voice"] == 1, "no marker → must fall through to voice_log"
