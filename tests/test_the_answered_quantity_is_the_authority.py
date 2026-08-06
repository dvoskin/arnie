"""THE ANSWERED QUANTITY IS THE ONLY QUANTITY AUTHORITY — B-1.75.

B-1 asks one question: how much was it. Its entire claim is that the answer,
not the interpreter's guess, determines what gets committed. Today
`core/b1_quantity_operation.settle` builds the pricing input as

    inp = {**item, "quantity": quantity_text}

so `_analyze_food` receives the macros belonging to the ASK-TIME quantity
alongside the ANSWERED one, and `analyze()` decides between them by its own
documented policy:

    "The LLM's calories/protein anchor the portion unless the quantity is an
     explicit mass and the winner is trustworthy."

That policy is reasonable where it lives. It is the wrong authority here: after
a user has stated the amount, there is nothing left to arbitrate.

WHAT THIS FILE ASSERTS, AND WHAT IT DELIBERATELY DOES NOT. It tests the
CONTRACT — that committed nutrition responds to the answered quantity — and
never the ACCURACY of any particular food. Whether chicken breast is 165 or 110
calories per 100 g is a nutrition question owned by a later phase; asserting it
here would make this file fail for reasons that have nothing to do with B-1,
and would quietly turn a contract gate into an accuracy gate.

So the property is relational: answer the SAME food twice, once with half the
quantity, and the committed calories must move with it. A row that ignores the
answer commits the same number twice, and no lookup table can make that right.

WHY THIS SHAPE RATHER THAN THE PRODUCTION EXAMPLES. B-1.75 was first argued
from two live operations, and both readings were wrong — the oatmeal was
correct (half a cup of dry oats IS one cup cooked) and the chicken was
confounded by preparation content in the answer. Reproducing either as a test
would have encoded a misreading. A relational property cannot be confounded
that way: it holds or it does not, for reasons internal to the code.
"""
import pytest

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, operations, say,
)


#: Ask-time bases the interpreter really produces. The macros on each are
#: whatever it estimated FOR THAT basis — which is exactly the stale input
#: under test, so they are deliberately identical across bases: any difference
#: in the committed result then comes from the BASIS, not from the numbers.
BASES = [
    pytest.param({"amount": 100, "unit": "g"}, id="grams"),
    pytest.param({"amount": 6, "unit": "oz"}, id="ounces"),
    pytest.param({"amount": 1, "unit": "cup cooked"}, id="cup"),
    pytest.param({"amount": 1, "unit": "breast"}, id="piece"),
    pytest.param({"amount": 1, "unit": ""}, id="unitless"),
]


def _plan(food, basis):
    return {
        "action": "ask",
        "points": [{"label": food, "q": "How much?"}],
        "items": [item(food, cal=200, **basis)],
        "ready": [],
    }


async def _answer(edges, user, food, basis, answer):
    """One full ask -> answer -> commit, returning the row it committed."""
    before = len(await rows(user))
    edges.plans.append(_plan(food, basis))
    await say(user, f"I had some {food.lower()}")
    await say(user, answer)
    board = await rows(user)
    assert len(board) == before + 1, (
        f"answering {answer!r} committed {len(board) - before} rows, expected 1 "
        f"— board={[(r.parsed_food_name, r.quantity) for r in board]}")
    return board[-1]


@pytest.mark.xfail(strict=True, reason="B-1.75 open: the ask-time macros pass through unchanged, so the answered quantity does not reach pricing. strict=True — this marker MUST be deleted when D1 lands, or the suite fails.")
@pytest.mark.parametrize("basis", BASES)
@pytest.mark.asyncio
async def test_committed_calories_follow_the_answered_quantity(
        edges, b1_live, basis):
    """Half the amount, half the calories — whatever basis the ask carried.

    The one property B-1 cannot be right without. If the ask-time macros win,
    both answers commit the SAME number and the question was decorative.

    Tolerance is wide on purpose: repricing may legitimately re-resolve the
    food, round, or seat a different candidate, and none of that is what this
    test is about. It fails only when the answer made no difference, or made a
    difference in the wrong direction.
    """
    small = await _answer(edges, b1_live, "Chicken breast", basis, "50 g")
    large = await _answer(edges, b1_live, "Chicken breast", basis, "100 g")

    assert small.calories and large.calories, (
        f"a committed row with no calories: {small.calories} / {large.calories}")
    assert large.calories > small.calories, (
        f"doubling the answered quantity did not increase the committed "
        f"calories — the answer is not the authority. basis={basis} "
        f"50g={small.calories} 100g={large.calories} "
        f"(quantities as stored: {small.quantity!r} / {large.quantity!r})")

    ratio = large.calories / small.calories
    assert 1.5 <= ratio <= 2.5, (
        f"committed calories did not scale with the answered quantity: "
        f"basis={basis} 50g={small.calories} 100g={large.calories} "
        f"ratio={ratio:.2f}, expected ~2.0")


@pytest.mark.parametrize("basis", BASES)
@pytest.mark.asyncio
async def test_the_stored_quantity_is_the_one_the_user_answered(
        edges, b1_live, basis):
    """Whatever the pricing does, the ROW must say what the person said.

    Separate from the calories assertion because they can fail independently,
    and the failure means different things: a wrong quantity on the row is a
    lie in the log the user reads back, while wrong calories with the right
    quantity is a pricing fault.
    """
    row = await _answer(edges, b1_live, "Chicken breast", basis, "50 g")
    q = (row.quantity or "").lower().replace(" ", "")
    assert "50" in q, (
        f"the user answered 50 g and the row stored {row.quantity!r} — the "
        f"ask-time basis {basis} survived into the committed quantity")


@pytest.mark.xfail(strict=True, reason="B-1.75 open: the ask-time macros pass through unchanged, so the answered quantity does not reach pricing. strict=True — this marker MUST be deleted when D1 lands, or the suite fails.")
@pytest.mark.asyncio
async def test_a_free_text_answer_is_as_authoritative_as_a_measured_one(
        edges, b1_live):
    """Free text is a first-class route (C15), not a degraded one.

    "Other" is always offered, so the path a user takes when no option fits
    must carry the same authority as one that does. If typed answers are
    priced from the ask-time macros while option answers are not, the option
    list is silently the only thing that works.
    """
    small = await _answer(edges, b1_live, "Chicken breast",
                          {"amount": 6, "unit": "oz"}, "about 50 grams")
    large = await _answer(edges, b1_live, "Chicken breast",
                          {"amount": 6, "unit": "oz"}, "about 100 grams")
    assert large.calories > small.calories, (
        f"a hedged free-text quantity did not drive the price: "
        f"{small.calories} vs {large.calories}")
