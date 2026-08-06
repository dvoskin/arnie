"""B-1b.1's last gate: the canonical path against the REAL lookup ladder.

The rest of the matrix injects a deterministic density (2 cal/g) so repricing
can be asserted against an exact expected number. That proves the LOGIC and
says nothing about the INTEGRATION — whether real USDA/Open Food Facts data,
with its real ranking and its real refusals, reaches a committed row correctly.

WHY THIS IS GATED AND SEPARATE. It needs `USDA_API_KEY` and it talks to the
network, so it is neither hermetic nor deterministic. Folding it into the main
matrix would make an offline run silently weaker instead of loudly skipped —
the exact "cannot say" reading as "fine" that this slice keeps paying for.

ASSERTIONS ARE RELATIONAL, NOT ABSOLUTE. USDA's top hit for "chicken breast"
is currently "Chicken breast tenders, breaded, uncooked" at 263 cal/100 g;
for "white rice" it is rice FLOUR; for "salmon" it is fish OIL at 902. Pinning
a calorie number here would encode today's index and fail on a data refresh
for reasons that have nothing to do with B-1. What must hold regardless of
which row wins is that the ANSWERED QUANTITY drives the result.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("USDA_API_KEY"),
    reason="needs USDA_API_KEY — real enrichment is B-1b.1's remaining gate "
           "and its absence must SKIP loudly, never weaken the matrix quietly")

from tests.test_a_full_day_of_food import (  # noqa: F401,E402
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401,E402
    CAPABLE, b1_live, say, operations, vague,
)


@pytest.fixture
def real_lookups(monkeypatch):
    """Undo the harness's stubs for USDA and Open Food Facts only.

    The LLM stays scripted — the model is not what this gate is about, and a
    live model would make the run non-reproducible for a second reason.
    """
    import importlib

    import api.usda as usda
    import skills.nutrition.off as off

    importlib.reload(usda)
    monkeypatch.setattr(usda, "search_food", usda.search_food)
    monkeypatch.setattr(off, "search", off.search)
    return True


async def _ask(edges, user, food, cal=280, amount=6, unit="oz"):
    edges.plans.append({
        "action": "ask",
        "points": [{"label": food, "q": "How much?"}],
        "items": [vague(food, cal=cal, amount=amount, unit=unit)],
        "ready": [],
    })
    await say(user, f"I had some {food.lower()}")
    return await operations(user)


@pytest.mark.parametrize("food", ["Chicken breast", "White rice", "Salmon"])
@pytest.mark.asyncio
async def test_the_answer_drives_the_price_through_the_real_ladder(
        edges, b1_live, app_db, real_lookups, food):
    """Doubling the answered quantity roughly doubles the committed nutrition.

    True whichever row the ladder seats, and false for every implementation
    that lets the ask-time macros survive — which is the property, not the
    number. Wide tolerance on purpose: the ladder may legitimately seat a
    different row, apply a cooking yield, or refuse a candidate entirely and
    fall back to the estimate path. None of that is what this asserts.
    """
    await _ask(edges, b1_live, food)
    await say(b1_live, "50 g")
    small = (await rows(b1_live))[-1]

    await _ask(edges, b1_live, food)
    await say(b1_live, "100 g")
    large = (await rows(b1_live))[-1]

    assert small.calories and large.calories, (
        f"{food}: a committed row with no calories — "
        f"{small.calories} / {large.calories}")
    assert large.calories > small.calories, (
        f"{food}: doubling the answer did not raise the price "
        f"({small.calories} -> {large.calories}) — the ask-time nutrition "
        f"survived the answer even with real enrichment available")
    ratio = large.calories / small.calories
    assert 1.5 <= ratio <= 2.5, (
        f"{food}: committed calories did not scale with the answer — "
        f"{small.calories} -> {large.calories} (ratio {ratio:.2f})")


@pytest.mark.asyncio
async def test_a_real_lookup_does_not_override_the_answered_quantity(
        edges, b1_live, app_db, real_lookups):
    """The row must say what the user said, whatever the database calls it.

    USDA's best "salmon" match is fish oil. A ladder that seated it and then
    re-derived a portion from its own calories would quietly replace the
    user's amount — the resolver-override failure this migration exists to
    end, arriving through the enrichment door instead of the interpreter one.
    """
    await _ask(edges, b1_live, "Salmon")
    await say(b1_live, "137 g")

    board = await rows(b1_live)
    assert len(board) == 1, [(r.parsed_food_name, r.quantity) for r in board]
    assert "137" in (board[0].quantity or ""), (
        f"the answered quantity did not survive real enrichment: "
        f"{board[0].quantity!r}")
