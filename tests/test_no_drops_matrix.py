"""No-drops matrix for the LEGACY-path nets (post-rip, 2026-07-23).

Food-report turns are owned by the STRUCTURED food path (tests/test_food_turn.py)
— a question can't become an entry and items can't drop there by construction.
This matrix proves the remaining nets on the legacy paths still work:

  POSITIVE — a WORDED phantom claim ("logged" with no tool call) is force-run:
  food/weight/water via the phantom-claim heuristic (PHANTOM_RESCUE_ENABLED),
  exercise via the 🏋️/set-report heuristic (EXERCISE_PHANTOM, default on).

  NEGATIVE — questions, plans, sign-offs, chit-chat, and an already-correct log
  never trigger a false rescue or a double-log.

STRUCTURED_FOOD is disabled here on purpose: the matrix exercises the nets, not
the structured path.
"""
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
    return SimpleNamespace(id=1, total_calories=0, total_protein=0, total_carbs=0,
                          total_fats=0, total_water_ml=0, workout_completed=False,
                          cardio_completed=False, food_entries=[], exercise_entries=[])


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)
    monkeypatch.setenv("STRUCTURED_FOOD", "false")       # exercise the nets
    monkeypatch.setenv("PHANTOM_RESCUE_ENABLED", "true") # the worded-claim net
    monkeypatch.setenv("LOOKUP_RESCUE", "true")
    # Hermetic regardless of suite order: no scribe task, no voice model read.
    monkeypatch.setenv("SCRIBE_ENABLED", "false")
    monkeypatch.setenv("FAST_LOG_VOICE", "false")
    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)


async def _run(monkeypatch, user_msg, pass1_text, pass1_tools, rescue_tools):
    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        is_rescue = "[SYSTEM HEALTH CHECK" in str(messages)
        if is_rescue:
            return {"text": "", "raw_content": [], "tool_calls": rescue_tools,
                    "stop_reason": "tool_use" if rescue_tools else "end_turn"}
        return {"text": pass1_text, "raw_content": [], "tool_calls": pass1_tools,
                "stop_reason": "tool_use" if pass1_tools else "end_turn"}
    monkeypatch.setattr(C, "chat", fake_chat)

    seen = set()
    async def fake_exec(tool_calls, *a, **k):
        out = {}
        for tc in tool_calls:
            nm = tc.get("name")
            inp = tc.get("input") or {}
            arg = inp.get("food_name") or inp.get("exercise_name") or "?"
            seen.add(f"{nm}:{arg}")
            out[nm] = f"Logged: {arg}" if nm != "search_food_database" \
                else "USDA: 160 cal per 28g, 11g fat, 2g protein"
        return out
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_followup(messages, raw, tcs, results, system, **kw):
        return "160 cal per 28g, 11g fat, 2g protein. Real label."
    monkeypatch.setattr(C, "chat_follow_up", fake_followup)

    turn = await run_turn(_user(), _DB(), [{"role": "user", "content": user_msg}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    return seen, reply


def _lf(name, cal=200):
    return {"name": "log_food", "input": {"food_name": name, "calories": cal}}


# ── POSITIVE: a worded phantom claim with NO tool → the net force-runs it ────────
_POSITIVE = [
    ("food_phantom", "had 2 eggs",
     "Eggs logged, 140 cal and 12g protein on the board.", [],
     [_lf("eggs")], {"log_food:eggs"}),
    ("multi_food_phantom", "had turkey and rice",
     "Turkey and rice logged, 350 cal total for the pair.", [],
     [_lf("turkey"), _lf("rice")], {"log_food:turkey", "log_food:rice"}),
    ("exercise_phantom", "60x13 on the fly",
     "🏋️ Low-to-High Fly · 60×13, matched it.", [],
     [{"name": "log_exercise", "input": {"exercise_name": "Low-to-High Fly", "sets": 1}}],
     {"log_exercise:Low-to-High Fly"}),
    ("lookup_estimate_branded", "How many calories in a Quest Birthday Cake bar?",
     "About 190 cal, roughly, for a standard bar.", [],
     [{"name": "search_food_database", "input": {"food_name": "Quest Birthday Cake bar"}}],
     {"search_food_database:Quest Birthday Cake bar"}),
]


@pytest.mark.parametrize("tid,msg,p1,p1t,rt,must", _POSITIVE, ids=[c[0] for c in _POSITIVE])
@pytest.mark.asyncio
async def test_positive_nothing_drops(monkeypatch, tid, msg, p1, p1t, rt, must):
    seen, reply = await _run(monkeypatch, msg, p1, p1t, rt)
    assert must <= seen, f"[{tid}] dropped: expected {must}, executor saw {seen}"


# ── NEGATIVE: a non-action or already-correct log → NO false rescue ─────────────
_NEGATIVE = [
    ("pure_question", "what should I eat tonight?", "Grilled chicken and rice is a solid call.", []),
    ("plan_not_eaten", "might grab a burger later", "Sounds good, enjoy it when you do.", []),
    ("staple_lookup", "how many calories in an egg?", "About 70 cal, 6g protein.", []),
    ("sign_off", "calling it here, goodnight", "Sleep well 🌙", []),
    ("chit_chat", "how's it going?", "Good, ready when you are.", []),
]


@pytest.mark.parametrize("tid,msg,p1,p1t", _NEGATIVE, ids=[c[0] for c in _NEGATIVE])
@pytest.mark.asyncio
async def test_negative_no_false_rescue(monkeypatch, tid, msg, p1, p1t):
    seen, reply = await _run(monkeypatch, msg, p1, p1t, [_lf("PHANTOM_SHOULD_NOT_LOG")])
    assert not any("PHANTOM_SHOULD_NOT_LOG" in s for s in seen), \
        f"[{tid}] FALSE rescue fired; executor saw {seen}"


@pytest.mark.asyncio
async def test_correct_log_not_double_logged(monkeypatch):
    """pass-1 fired log_food and the reply confirms it → no rescue, no double."""
    seen, reply = await _run(
        monkeypatch, "had 2 eggs", "Eggs logged, 140 cal.",
        [_lf("eggs")], [_lf("eggs_DOUBLE")])
    assert "log_food:eggs" in seen
    assert not any("DOUBLE" in s for s in seen), f"double-logged: {seen}"
