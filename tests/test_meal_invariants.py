"""Twelve combined meals, both modes, asserted on invariants.

Screenshot-driven fixes patch the meal in the screenshot. This runs a spread of
real shapes — ambiguous portions, exact masses, sauces, dressings, oils,
branded products, fractions of branded products, restaurant bowls, condiments —
through the real `food_turn.run()` and asserts the RULES, so a regression shows
up on whichever meal happens to trip it rather than on the one someone
remembered to write a test for.

Three of the four rules below were live defects when this file was written, and
the fourth (the vague range being the same for a dressing and a chicken breast)
was found BY this file on its first run.
"""
import asyncio
import json
import re
from types import SimpleNamespace

import pytest

import core.food_turn as FT


def _interp(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


def I(food, amount=None, unit=None, basis="estimate", branded=False,
      cal=100, pro=5):
    return {"food": food, "amount": amount, "unit": unit, "basis": basis,
            "branded": branded, "calories": cal, "protein": pro}


MEALS = [
 ("bar + vague chicken + vague rice",
  "had a Barebells caramel cashew bar and some chicken and rice",
  [I("Barebells Caramel Cashew Protein Bar",1,"bar","stated",True,200,20),
   I("Chicken breast",6,"oz",cal=280,pro=52), I("White rice",1,"cup",cal=205,pro=4)]),
 ("salad + dressing drizzle",
  "big salad with some ranch dressing and grilled chicken",
  [I("Garden salad",1,"bowl",cal=80,pro=3), I("Ranch dressing",2,"tbsp",cal=145,pro=1),
   I("Grilled chicken breast",5,"oz",cal=230,pro=43)]),
 ("branded + exact mass",
  "200g of ground turkey and a Fairlife Core Power",
  [I("Ground turkey",200,"g","stated",False,340,44),
   I("Fairlife Core Power",1,"bottle","stated",True,170,26)]),
 ("sauce heavy pasta",
  "pasta with a lot of marinara and some parmesan",
  [I("Spaghetti",2,"cup",cal=390,pro=14), I("Marinara sauce",1,"cup",cal=140,pro=4),
   I("Parmesan cheese",2,"tbsp",cal=45,pro=4)]),
 ("all stated",
  "3 eggs and 2 slices of sourdough",
  [I("Eggs",3,"egg","stated",False,215,19), I("Sourdough bread",2,"slice","stated",False,240,8)]),
 ("restaurant bowl",
  "cava bowl with double chicken and tahini",
  [I("Cava bowl",1,"bowl",cal=600,pro=45), I("Tahini sauce",2,"tbsp",cal=180,pro=5)]),
 ("branded snack, vague count",
  "a few Barebells bites and a coffee",
  [I("Barebells Protein Bites",1,"handful",branded=True,cal=180,pro=12),
   I("Coffee",1,"cup",cal=5,pro=0)]),
 ("condiments only",
  "put mayo and mustard on a turkey sandwich",
  [I("Turkey sandwich",1,"sandwich",cal=380,pro=28),
   I("Mayonnaise",1,"tbsp",cal=90,pro=0), I("Mustard",1,"tsp",cal=3,pro=0)]),
 ("fraction of a branded item",
  "half a Legendary sweet roll",
  [I("Legendary Foods Sweet Roll",0.5,"roll","stated",True,105,10)]),
 ("vague everything",
  "some leftovers, a bit of rice and a little sauce",
  [I("Leftover chicken",1,"portion",cal=250,pro=30), I("White rice",1,"cup",cal=205,pro=4),
   I("Soy sauce",1,"tbsp",cal=10,pro=1)]),
 ("big branded multi",
  "a Nissin Cup Noodles and a Royo everything bagel with cream cheese",
  [I("Nissin Cup Noodles",1,"container","stated",True,320,16),
   I("Royo Everything Bagel",1,"bagel","stated",True,80,10),
   I("Cream cheese",2,"tbsp",cal=100,pro=2)]),
 ("oil and dressing invisible calories",
  "chicken salad, made it with olive oil and balsamic",
  [I("Chicken salad",1,"bowl",cal=350,pro=35), I("Olive oil",1,"tbsp",cal=120,pro=0),
   I("Balsamic vinegar",1,"tbsp",cal=14,pro=0)]),
]



async def _run(monkeypatch, message, items, mode):
    monkeypatch.setattr(FT, "chat", _interp(
        {"action": "log", "items": items, "say": "Logged, {batch_cal} cal."}))
    out = await FT.run(message, SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode=mode)))
    return out, (out.get("text", "") if out["action"] == "ask" else "")


_IDS = [m[0] for m in MEALS]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("label,message,items", MEALS, ids=_IDS)
async def test_no_hedge_is_treated_as_a_noun(monkeypatch, mode, label,
                                             message, items):
    """"Was the some closer to..." / "One some of mustard"."""
    _, text = await _run(monkeypatch, message, items, mode)
    assert not re.search(r"\bthe some\b|\bone some\b|\ba some\b", text, re.I), text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("label,message,items", MEALS, ids=_IDS)
async def test_no_whole_parse_confirm(monkeypatch, mode, label, message,
                                      items):
    _, text = await _run(monkeypatch, message, items, mode)
    assert "Does that all look right?" not in text, text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("label,message,items", MEALS, ids=_IDS)
async def test_an_invented_amount_is_never_listed_unmarked(monkeypatch, mode,
                                                           label, message,
                                                           items):
    """The rice that came back as "One cup of white rice" in the user's own
    voice. Checked on every item of every meal, not just that one."""
    _, text = await _run(monkeypatch, message, items, mode)
    for item in items:
        if item["basis"] == "stated" or not item["amount"] or not text:
            continue
        for line in text.split("\n"):
            if line.strip().startswith("\u2022") \
                    and item["food"].lower() in line.lower():
                assert "(my estimate)" in line, line


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("label,message,items", MEALS, ids=_IDS)
async def test_certainty_is_not_claimed_over_our_own_guesses(monkeypatch, mode,
                                                             label, message,
                                                             items):
    _, text = await _run(monkeypatch, message, items, mode)
    if sum(1 for i in items if i["basis"] != "stated") > 1:
        assert "only part I'm unsure about" not in text, text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("label,message,items", MEALS, ids=_IDS)
async def test_one_question_per_turn(monkeypatch, mode, label, message, items):
    """Two questions in one turn is two things to answer and one to forget."""
    _, text = await _run(monkeypatch, message, items, mode)
    assert text.count("?") <= 1, text


# ── the rule this file found on its first run ────────────────────────────────
def test_a_vague_range_is_plausible_for_the_food_it_names():
    """"some ranch dressing" and "some chicken" were both asked about as
    "closer to 30g or 200g?". 200 g of ranch is most of a bottle, and a
    question whose own range is absurd for the food cannot be answered
    honestly either way. The category machinery already existed and classified
    these correctly — the "some" and "little" measures simply had no rows."""
    from skills.nutrition.portions import distribution_for
    tight = {"ranch dressing": 120, "olive oil": 60, "parmesan cheese": 100,
             "soy sauce": 120, "mixed nuts": 100}
    for food, ceiling in tight.items():
        d = distribution_for("some", food)
        assert d is not None and d.upper_g <= ceiling, (food, d)


def test_a_little_of_something_is_smaller_than_some_of_it():
    from skills.nutrition.portions import distribution_for
    for food in ("ranch dressing", "olive oil", "parmesan cheese"):
        assert distribution_for("little", food).upper_g < \
            distribution_for("some", food).upper_g, food


def test_preparation_is_not_acquisition():
    """"chicken salad, made it with olive oil and balsamic" asked "did you eat
    all 3 of those, or is that for later?" — about a meal plainly described as
    eaten. Someone who cooked a thing overwhelmingly ate it."""
    from core.food_turn import STATE_ACQUIRED, consumption_state
    for line in ("chicken salad, made it with olive oil and balsamic",
                 "made eggs", "cooked some chicken", "brought lunch from home"):
        assert consumption_state(line) != STATE_ACQUIRED, line
    for line in ("Got a Barebells bar", "picked up a poke bowl"):
        assert consumption_state(line) == STATE_ACQUIRED, line
