"""Deterministic LOG-CONFIRM marker (Danny 2026-07-23).

The model appends [[LOGGED]] whenever it claims a write. It's stripped before the
user sees it, and if it's present with NO logging tool fired, the write didn't
happen -> force-log. One signal for every log type, no freeform-phrasing guessing.
"""
import pytest
from types import SimpleNamespace

import core.conversation as C
import db.queries as Q
import reminders.lifecycle as RL
from core.conversation import run_turn
from core.platform import _sanitize_bubble


def test_marker_is_stripped_from_user_text():
    assert _sanitize_bubble("Bench logged. [[LOGGED]]") == "Bench logged."
    assert _sanitize_bubble("done [[ LOGGED ]] keep going") == "done keep going"
    assert "[[" not in _sanitize_bubble("2×8 on the board [[LOGGED]]")


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
    return SimpleNamespace(id=None, total_calories=0, total_protein=0, total_carbs=0,
                          total_fats=0, total_water_ml=0, workout_completed=False,
                          cardio_completed=False, food_entries=[], exercise_entries=[])


@pytest.fixture(autouse=True)
def _noop_pending(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


@pytest.mark.asyncio
async def test_marker_without_tool_is_force_logged(monkeypatch):
    monkeypatch.setenv("LOG_MARKER", "true")
    calls = {"n": 0}

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # Claims a log via the marker, but fires NO tool — the phantom.
            return {"text": "Logged 2 eggs, solid protein start. [[LOGGED]]",
                    "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
        return {"text": "Logged.", "raw_content": [],
                "tool_calls": [{"name": "log_food",
                                "input": {"food_name": "eggs", "quantity": "2",
                                          "calories": 140, "protein": 12}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    logged = []
    async def fake_exec(tool_calls, *a, **k):
        logged.extend((tc.get("input") or {}).get("food_name") for tc in tool_calls)
        return {"log_food": "Logged: eggs"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    interim, started = [], []
    async def _ci(t): interim.append(t)
    async def _cs(n): started.append(n)
    turn = await run_turn(_user(), _DB(), [{"role": "user", "content": "had 2 eggs"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log(), on_interim=_ci, on_tool_start=_cs)

    assert "eggs" in logged, f"marker phantom NOT force-logged; executor got {logged}"
    # And the marker never reaches the user.
    assert "[[LOGGED]]" not in "|||".join(turn.response.bubbles if turn.response else [])
    # Universal announce (not lookup-only): the write rescue announced its round-trip.
    assert interim, "write rescue should announce its round-trip (universal helper)"


# Every log-type: the model CLAIMS a write (marker) but fires no tool → the rescue
# force-logs it. Proves the marker is log-type-agnostic (Danny: "any situation
# where Arnie needs to make a tool call and log something and fails").
_SCENARIOS = [
    ("had turkey and rice",
     "Logged turkey and rice, clean meal. [[LOGGED]]",
     [{"name": "log_food", "input": {"food_name": "turkey", "calories": 200}},
      {"name": "log_food", "input": {"food_name": "rice", "calories": 130}}],
     {"log_food:turkey", "log_food:rice"}),
    ("weighed in at 194",
     "Got your weight, 194. [[LOGGED]]",
     [{"name": "log_body_weight", "input": {"weight": 194}}],
     {"log_body_weight:?"}),
    ("drank 16oz of water",
     "16oz of water is in. [[LOGGED]]",
     [{"name": "log_water", "input": {"amount_ml": 473}}],
     {"log_water:?"}),
]


@pytest.mark.parametrize("user_msg,pass1_text,rescue_calls,expected", _SCENARIOS)
@pytest.mark.asyncio
async def test_marker_force_logs_every_type(monkeypatch, user_msg, pass1_text,
                                            rescue_calls, expected):
    monkeypatch.setenv("LOG_MARKER", "true")
    calls = {"n": 0}

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:                      # claims the log, fires NO tool
            return {"text": pass1_text, "raw_content": [], "tool_calls": [],
                    "stop_reason": "end_turn"}
        return {"text": "Done.", "raw_content": [], "tool_calls": rescue_calls,
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    got = set()
    async def fake_exec(tool_calls, *a, **k):
        for tc in tool_calls:
            nm = tc.get("name")
            fn = (tc.get("input") or {}).get("food_name")
            got.add(f"{nm}:{fn}" if fn else f"{nm}:?")
        return {tc["name"]: "Logged." for tc in tool_calls}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    await run_turn(_user(), _DB(), [{"role": "user", "content": user_msg}],
                   "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                   today_log=_today_log())

    assert expected <= got, f"marker rescue missed {expected - got}; executor got {got}"


@pytest.mark.asyncio
async def test_did_manifest_write_phantom_force_logged(monkeypatch):
    """The generalized [[DID: log_food]] manifest (not just legacy [[LOGGED]]) also
    force-logs a claimed-but-unfired write."""
    monkeypatch.setenv("LOG_MARKER", "true")
    calls = {"n": 0}

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:                      # claims log_food by NAME, fires nothing
            return {"text": "Logged your chicken, 200 cal. [[DID: log_food]]",
                    "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
        return {"text": "Logged.", "raw_content": [],
                "tool_calls": [{"name": "log_food",
                                "input": {"food_name": "chicken", "calories": 200}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(C, "chat", fake_chat)

    logged = []
    async def fake_exec(tool_calls, *a, **k):
        logged.extend((tc.get("input") or {}).get("food_name") for tc in tool_calls)
        return {"log_food": "Logged: chicken"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    turn = await run_turn(_user(), _DB(), [{"role": "user", "content": "had chicken"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())

    assert "chicken" in logged, f"[[DID: log_food]] phantom NOT force-logged; got {logged}"
    assert "[[DID" not in "|||".join(turn.response.bubbles if turn.response else [])
