"""Mode-gradient clarify-on-swing — logic (mocked) + a live smoke on the real model."""
import os
import pytest
from types import SimpleNamespace

import core.clarify as C


def _user(mode):
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=mode))


def _tc(name, qty="", cal=None):
    inp = {"food_name": name, "quantity": qty}
    if cal is not None:
        inp["calories"] = cal
    return {"name": "log_food", "input": inp}


async def _fake_chat(text):
    async def _c(messages, system, **kw):
        # expose the system so a test can assert the threshold was passed
        _c.system = system
        return {"text": text}
    return _c


async def test_returns_question_on_swing(monkeypatch):
    monkeypatch.setattr(C, "chat", await _fake_chat("how much butter on the toast?"))
    q = await C.clarify_swings([_tc("toast with butter", "2 slices", 180)], {}, _user("strict"))
    assert q == "how much butter on the toast?"


async def test_none_when_model_says_none(monkeypatch):
    monkeypatch.setattr(C, "chat", await _fake_chat("NONE"))
    q = await C.clarify_swings([_tc("diet coke", "1 can", 0)], {}, _user("strict"))
    assert q is None


async def test_strips_tilde_and_dash(monkeypatch):
    monkeypatch.setattr(C, "chat", await _fake_chat("quick one — how much oil ~roughly?"))
    q = await C.clarify_swings([_tc("chicken", "6 oz", 300)], {}, _user("moderate"))
    assert "~" not in q and "—" not in q and q.startswith("quick one,")


async def test_no_food_items_skips(monkeypatch):
    called = {"n": 0}
    async def _c(*a, **k):
        called["n"] += 1; return {"text": "NONE"}
    monkeypatch.setattr(C, "chat", _c)
    assert await C.clarify_swings([{"name": "log_water", "input": {}}], {}, _user("strict")) is None
    assert called["n"] == 0          # no model call when there's no food


async def test_mode_threshold_passed(monkeypatch):
    fc = await _fake_chat("NONE")
    monkeypatch.setattr(C, "chat", fc)
    await C.clarify_swings([_tc("eggs", "2", 140)], {}, _user("quick"))
    assert "250" in fc.system        # quick threshold
    await C.clarify_swings([_tc("eggs", "2", 140)], {}, _user("strict"))
    assert "60" in fc.system         # strict threshold


async def test_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("CLARIFY_SWINGS", "false")
    q = await C.clarify_swings([_tc("toast with butter", "2 slices", 180)], {}, _user("strict"))
    assert q is None


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs API key")
async def test_live_butter_asks_diet_coke_quiet():
    """The real model: strict + 'toast with butter' should ASK; 'diet coke' should not."""
    ask = await C.clarify_swings(
        [_tc("toast with butter", "2 slices", 180), _tc("diet coke", "1 can", 0)],
        {}, _user("strict"))
    assert ask and ("butter" in ask.lower())            # it asks about the butter
    quiet = await C.clarify_swings([_tc("diet coke", "1 can", 0)], {}, _user("quick"))
    assert quiet is None                                # nothing to ask on a diet coke


# ── OUTPUT GUARD: the model's ask-or-not REASONING must never ship (Danny 07-22) ──

async def test_leaked_reasoning_without_question_returns_none(monkeypatch):
    """The narrated no-ask analysis (no '?') leaked to a user. Must be None."""
    monkeypatch.setattr(C, "chat", await _fake_chat(
        "Jif peanut butter at 2 tsp is usually closer to 130 cal, not 190, but "
        "that's a stated quantity so no real ambiguity to ask about. Both items "
        "here are exact branded products with fixed macros."))
    q = await C.clarify_swings([_tc("jif peanut butter", "2 tsp", 190)], {}, _user("strict"))
    assert q is None


async def test_reasoning_ending_in_none_sentinel_returns_none(monkeypatch):
    """The model prepended reasoning before the NONE sentinel — still None."""
    monkeypatch.setattr(C, "chat", await _fake_chat(
        "Fritos are a fixed portion at a set calorie count per ounce, so there's "
        "no unstated detail here that would swing things more than 60 kcal. NONE"))
    q = await C.clarify_swings([_tc("fritos", "1 oz", 160)], {}, _user("strict"))
    assert q is None


async def test_a_real_question_still_passes(monkeypatch):
    monkeypatch.setattr(C, "chat", await _fake_chat(
        "quick one so these are right, was the chicken grilled or fried?"))
    q = await C.clarify_swings([_tc("chicken", "6 oz", 300)], {}, _user("strict"))
    assert q and q.endswith("?")
