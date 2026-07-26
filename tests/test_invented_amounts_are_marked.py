"""An amount nobody stated is never shown as though they stated it.

    You:   had a Barebells caramel cashew bar and some chicken and rice
    Arnie: Here's how I'm interpreting that:
           • A barebells caramel cashew protein bar
           • One cup of white rice            <- a cup nobody said
           • Some chicken breast
           The chicken breast is the only part I'm unsure about.
           Was the some closer to 30g or 200g?

Three defects in one turn, and they compound. "Some" distributes over both the
chicken and the rice; the interpreter attached the hedge to the chicken and
invented a cup for the rice. The invented cup was then printed in the same
voice as the bar the user actually named, and the next sentence asserted that
the chicken was the ONLY open question — certainty about a number we had made
up one line earlier, which tells the user not to look.

On strict this is the whole promise inverted: strict exists so nothing is
asserted that the user did not say.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from core.food_response import FoodItemSummary


def _interp(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


_MEAL = {"action": "log", "items": [
    {"food": "Barebells Caramel Cashew Protein Bar", "amount": 1,
     "unit": "bar", "branded": True, "basis": "stated",
     "calories": 200, "protein": 20},
    {"food": "Chicken breast", "amount": 6, "unit": "oz", "basis": "estimate",
     "calories": 280, "protein": 52},
    {"food": "White rice", "amount": 1, "unit": "cup", "basis": "estimate",
     "calories": 205, "protein": 4}],
    "say": "Logged, {batch_cal} cal."}
_MSG = "had a Barebells caramel cashew bar and some chicken and rice"


async def _turn(monkeypatch, mode):
    monkeypatch.setattr(FT, "chat", _interp(_MEAL))
    return await FT.run(_MSG, SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode=mode)))


# ── 1. our amounts are marked as ours ─────────────────────────────────────────
def test_an_inferred_amount_carries_a_marker():
    summary = FoodItemSummary(name="white rice", portion="1 cup",
                              estimated=True)
    assert "(my estimate)" in summary.describe()


def test_a_stated_amount_carries_none():
    summary = FoodItemSummary(name="white rice", portion="1 cup",
                              estimated=False)
    assert "(my estimate)" not in summary.describe()


def test_the_marker_does_not_change_the_layout():
    """Layout measures how long a FOOD reads. Letting an annotation count
    flipped a two-item review out of prose and into a list."""
    summary = FoodItemSummary(name="white rice", portion="1 cup",
                              estimated=True)
    assert "(my estimate)" not in summary.describe_bare()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
async def test_the_invented_cup_is_not_presented_as_the_users(monkeypatch,
                                                              mode):
    out = await _turn(monkeypatch, mode)
    text = out.get("text", "")
    assert "white rice (my estimate)" in text.lower(), text


# ── 2. no certainty claimed over an unmarked guess ────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
async def test_it_does_not_claim_the_asked_item_is_the_only_doubt(monkeypatch,
                                                                  mode):
    out = await _turn(monkeypatch, mode)
    assert "only part I'm unsure about" not in out.get("text", "")


@pytest.mark.asyncio
async def test_it_says_the_other_amounts_are_ours(monkeypatch):
    out = await _turn(monkeypatch, "moderate")
    assert "I picked the other amounts myself" in out.get("text", "")


def test_the_sole_estimate_wording_survives_when_it_is_true():
    """One open amount and nothing else inferred — the original sentence is
    correct there and is kept."""
    from core.food_pipeline import _vague_prompt
    text = _vague_prompt("peanut butter", "scoop",
                         ["one tablespoon", "three tablespoons"],
                         sole_estimate=True)
    assert "only part I'm unsure about" in text


# ── 3. a hedge is not a measure ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_hedge_is_not_asked_about_as_a_noun(monkeypatch):
    """"Was the some closer to 30g or 200g?" — the same defect as "One some of
    mustard", one layer over."""
    out = await _turn(monkeypatch, "moderate")
    text = out.get("text", "")
    assert "the some" not in text.lower(), text
    assert "how much of the chicken breast" in text.lower(), text


def test_a_real_measure_keeps_its_frame():
    from core.food_pipeline import _vague_prompt
    text = _vague_prompt("peanut butter", "scoop",
                         ["one tablespoon", "three tablespoons"])
    assert "Was the scoop closer" in text
