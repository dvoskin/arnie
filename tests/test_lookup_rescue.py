"""Lookup rescue (B, 2026-07-23): the user asks about a SPECIFIC product and the
model answers with its own ESTIMATE instead of looking it up (Bonilla de la Vista,
IMG_8582). The generic action-manifest catches it (claimed lookup / hedged estimate
+ no lookup tool) and forces search_food_database, then re-voices real numbers.
Switch: LOOKUP_RESCUE."""
import pytest
from types import SimpleNamespace

import core.conversation as C
import db.queries as Q
import reminders.lifecycle as RL
from core.conversation import run_turn
from core.platform import _sanitize_bubble
from core.turn_health import looks_like_estimated_product_query


def test_did_manifest_is_stripped():
    assert _sanitize_bubble("Logged your chicken. [[DID: log_food]]") == "Logged your chicken."
    assert "[[" not in _sanitize_bubble("done [[DID: log_food, log_water]] keep going")
    assert "[[" not in _sanitize_bubble("checked it [[DID: search_food_database]]")


def test_estimated_product_query_detector():
    # Positive: a nutrition question answered with a hedged estimate.
    assert looks_like_estimated_product_query(
        "How many calories in Bonilla de la Vista potato chips?",
        "For a standard 1oz bag, about 160 cal, 2g protein.")
    # Negative: a flat looked-up answer (no hedge) is NOT a gap.
    assert not looks_like_estimated_product_query(
        "How many calories in Bonilla de la Vista chips?",
        "160 cal per 28g, 11g fat, 13g carbs, 2g protein.")
    # Negative: not a question (a food report, handled elsewhere).
    assert not looks_like_estimated_product_query(
        "had a bagel", "80 cal logged, nice.")
    # Negative: a question with no nutrition ask.
    assert not looks_like_estimated_product_query(
        "what should I eat tonight?", "try some grilled chicken, about 200 cal.")


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
def _noop_pending(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


@pytest.mark.asyncio
async def test_estimate_forces_a_lookup_and_revoices(monkeypatch):
    monkeypatch.setenv("LOOKUP_RESCUE", "true")

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None, **kw):
        blob = str(messages)
        if "gave your OWN estimate" in blob:      # the lookup-rescue nudge
            return {"text": "", "raw_content": [],
                    "tool_calls": [{"name": "search_food_database",
                                    "input": {"food_name": "Bonilla de la Vista potato chips"}}],
                    "stop_reason": "tool_use"}
        # pass-1: a hedged estimate, NO lookup tool fired (the miss).
        return {"text": "For a standard 1oz bag, about 160 cal, 2g protein.",
                "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
    monkeypatch.setattr(C, "chat", fake_chat)

    fired = []
    async def fake_exec(tool_calls, *a, **k):
        fired.extend(tc.get("name") for tc in tool_calls)
        return {"search_food_database": "USDA: 160 cal per 28g, 11g fat, 13g carbs, 2g protein"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_followup(messages, raw, tool_calls, tool_results, system, **kw):
        return "160 cal per 28g, 11g fat, 13g carbs, 2g protein. Real label, not a guess."
    monkeypatch.setattr(C, "chat_follow_up", fake_followup)

    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    interim, started = [], []
    async def _cap_interim(t): interim.append(t)
    async def _cap_start(names): started.append(names)

    turn = await run_turn(
        _user(), _DB(),
        [{"role": "user", "content": "How many calories in Bonilla de la Vista potato chips?"}],
        "SYS", "imessage", in_onboarding=False, was_onboarding=False,
        today_log=_today_log(), on_interim=_cap_interim, on_tool_start=_cap_start)

    assert "search_food_database" in fired, f"lookup NOT forced; executor got {fired}"
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    assert "per 28g" in reply, f"real numbers not re-voiced; got {reply!r}"
    assert "about 160" not in reply, "the estimate should have been replaced"
    # No dead air: the rescue announced itself (heads-up bubble + indicator morph).
    assert interim, "lookup rescue must send a heads-up before the search round-trip"
    assert any("search_food_database" in n for n in started), \
        "thinking indicator should morph to the lookup"
