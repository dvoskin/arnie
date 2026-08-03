"""Part 5 END-TO-END: the resolve-then-ask promotion through the whole turn.

`test_food_turn_resolve_then_ask.py` pins the decision functions in isolation.
These drive the REAL turn — a mocked interpreter in, a rendered ask or a
committed log out — which is the conversational-path validation the readiness
posture (NUTRITION_ACCURACY_V2: canary, not global) requires: an overconfident
`log` from the model becomes a question when the doubt is material, commits when
it is not, and is inert with the flag off. No DB — `FT.run` returns the PLAN
(the tool_calls), and the harness mirrors the other food_turn tests.
"""
import json
import pytest
from types import SimpleNamespace

import core.food_turn as FT


def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        fc.last_content = messages[-1]["content"]
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


def _user(mode="moderate"):
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=mode))


def _log(items):
    return {"action": "log", "items": items}


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "true")


SPOON = {"food": "Peanut butter", "amount": 1, "unit": "spoon",
         "calories": 350, "protein": 14, "carbs": 12, "fats": 28}


@pytest.mark.asyncio
async def test_the_spoon_becomes_a_question(v2, monkeypatch):
    # The production case: the model committed 350 on "a spoon"; V2 asks instead.
    monkeypatch.setattr(FT, "chat", _fake_chat(_log([SPOON])))
    out = await FT.run("a spoon of peanut butter", _user())
    assert out["action"] == "ask"
    assert "?" in out["text"] and "how much" in out["text"].lower()
    assert not out.get("tool_calls")           # nothing commits while it is open


@pytest.mark.asyncio
async def test_a_small_vague_unit_still_commits(v2, monkeypatch):
    # A handful of spinach is a vague unit too — but 7 cal is immaterial, and the
    # SAME engine that promotes the spoon must not interrupt for this.
    monkeypatch.setattr(FT, "chat", _fake_chat(_log([
        {"food": "Spinach", "amount": 1, "unit": "handful", "calories": 7,
         "protein": 1, "carbs": 1, "fats": 0}])))
    out = await FT.run("a handful of spinach", _user())
    assert out["action"] == "log"


@pytest.mark.asyncio
async def test_an_explicit_mass_commits_untouched(v2, monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat(_log([
        {"food": "Peanut butter", "amount": 16, "unit": "g", "calories": 94,
         "protein": 4, "carbs": 3, "fats": 8}])))
    out = await FT.run("16 g of peanut butter", _user())
    assert out["action"] == "log"


@pytest.mark.asyncio
async def test_flag_off_commits_the_spoon(monkeypatch):
    # Same overconfident log, flag OFF → v1 commits it. The capability is dark
    # until NUTRITION_ACCURACY_V2 is set — the whole point of a canary.
    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.setattr(FT, "chat", _fake_chat(_log([SPOON])))
    out = await FT.run("a spoon of peanut butter", _user())
    assert out["action"] == "log"


@pytest.mark.asyncio
async def test_unstated_fat_on_a_protein_asks_on_strict(v2, monkeypatch):
    # The prep/marinade ask — a 100-cal fat swing clears strict's bar, not
    # moderate's, so mode is the throttle end-to-end.
    steak = _log([{"food": "Sirloin steak", "amount": 8, "unit": "oz",
                   "calories": 440, "protein": 46, "carbs": 0, "fats": 28}])
    monkeypatch.setattr(FT, "chat", _fake_chat(steak))
    out = await FT.run("sirloin steak for dinner", _user(mode="strict"))
    assert out["action"] == "ask"
    assert any(w in out["text"].lower() for w in ("oil", "butter", "dressing"))


@pytest.mark.asyncio
async def test_moderate_does_not_ask_about_the_steak_fat(v2, monkeypatch):
    # Same steak on moderate: the 100-cal swing is below the bar, so it commits.
    steak = _log([{"food": "Sirloin steak", "amount": 8, "unit": "oz",
                   "calories": 440, "protein": 46, "carbs": 0, "fats": 28}])
    monkeypatch.setattr(FT, "chat", _fake_chat(steak))
    out = await FT.run("sirloin steak for dinner", _user(mode="moderate"))
    assert out["action"] == "log"


@pytest.mark.asyncio
async def test_the_settled_food_waits_with_the_doubtful_one(v2, monkeypatch):
    """AN ASK WRITES NOTHING — be65fb6's decision, restored 2026-08-03.

    This asserted the opposite until now: the banana committed while the spoon
    was asked about. That is right in principle and wrong in practice, because
    an ask carrying writes loses its own question — `discard_held` bins the
    held bubble whenever a logging tool fires, and the structured-narration
    gate has no "ask" in its action tuple. Live symptom: "Had some chicken and
    rice" wrote the rice, never mentioned it, and asked about the chicken.

    THE DEFAULT NOW, and the flag is left unset here on purpose so this test
    fails if the default drifts back. "Nothing is lost by waiting, the answer
    turn re-reads the whole message" was the premise, and
    tests/test_leave_no_food_behind.py falsifies it: an item neither asked
    about nor marked ready is LOST, not deferred. So waiting is only honest
    because the banana now RIDES the question as a built write — asserted
    below, and end-to-end in
    tests/test_every_food_survives_the_clarification.py.
    """
    monkeypatch.setattr(FT, "chat", _fake_chat(_log([
        SPOON,
        {"food": "Banana", "amount": 1, "unit": "medium", "calories": 105,
         "protein": 1, "carbs": 27, "fats": 0}])))
    monkeypatch.delenv("FOOD_PARTIAL_COMMIT", raising=False)
    out = await FT.run("a spoon of peanut butter and a banana", _user())
    assert out["action"] == "ask"
    assert not (out.get("tool_calls") or []), (
        "an ask must carry no writes — the whole meal waits for the answer")
    # WAITING IS NOT DROPPING. Without this line the assertion above is
    # satisfied just as well by losing the banana.
    held = [(c.get("input") or {}).get("food_name")
            for c in (out.get("deferred_calls") or [])]
    assert "Banana" in held, (
        f"the settled food was held but not stashed — it is now lost: {held}")
    assert "Peanut butter" not in held, "the asked food answered its own question"


@pytest.mark.asyncio
async def test_the_switch_still_commits_the_settled_food(v2, monkeypatch):
    """The old behaviour, kept under FOOD_PARTIAL_COMMIT. Coverage stays so the
    switch is a real way back rather than a dead flag — and so the narration
    guards that make it safe to flip keep being exercised."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "true")
    monkeypatch.setattr(FT, "chat", _fake_chat(_log([
        SPOON,
        {"food": "Banana", "amount": 1, "unit": "medium", "calories": 105,
         "protein": 1, "carbs": 27, "fats": 0}])))
    out = await FT.run("a spoon of peanut butter and a banana", _user())
    assert out["action"] == "ask"
    committed = [c["input"]["food_name"] for c in (out.get("tool_calls") or [])]
    assert "Banana" in committed and "Peanut butter" not in committed
    # WRITTEN OR HELD, NEVER BOTH — a food in both lists lands twice.
    assert not (out.get("deferred_calls") or []), (
        "the writing path also stashed; the banana would be logged twice")
