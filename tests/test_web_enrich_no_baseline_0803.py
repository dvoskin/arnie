"""No baseline is not no objection.

The web meal enrich replaces an estimate with an absolute total pulled off a
search result, and its only backstop is a plausibility cap: a move bigger than
`FOOD_PLAUSIBILITY_CAP` (5x) is a wrong-dish or wrong-unit hit and is declined.

`_delta_ratio` returns None when either side is <= 0. That is CORRECT — there is
no ratio between "no number" and 400, and returning infinity would be a lie
about what a ratio is. The defect was caller-side: the condition read
`_x is not None and _x >= _cap`, so "no ratio available" was consent.

Which made a 0 -> 400 move the one move the cap could never see, and it is the
least defensible move there is: reaching this lane at all means every path that
could price the food declined, and the answer to "nobody could price it" is not
"believe a search result outright".

Prod 2026-08-03, the Cali Roll. The interpreter had reasoned 283. The unit-change
path popped it, `analyze` received no calories and produced 0, the zero-calorie
refusal set `source="estimate"` — which is the gate that OPENS this lane — and
400 committed with the macros then force-fit to match it.
"""
import pytest

from skills.nutrition.promotion import _delta_ratio


def test_delta_ratio_is_right_to_say_nothing():
    """Pinned so the fix is not "make _delta_ratio lie". There is no ratio
    here, and the caller is what needed to change."""
    assert _delta_ratio(0, 400) is None
    assert _delta_ratio(None, 400) is None
    assert _delta_ratio(-5, 400) is None
    # A real move still measures.
    assert _delta_ratio(283, 400) == pytest.approx(400 / 283)
    assert _delta_ratio(205, 1) == pytest.approx(205.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("interp_cal,web_cal,expect_web_wins", [
    (None, 400, False),   # the Cali Roll: no baseline -> refuse
    (0,    400, False),
    (283,  400, True),    # 1.41x, well inside the cap
    (100,  600, False),   # 6x, over the cap
])
async def test_the_executor_refuses_a_web_total_with_no_baseline(
        monkeypatch, interp_cal, web_cal, expect_web_wins):
    """Driven through `_analyze_food`, NOT re-implemented.

    The first version of this test recomputed the condition in the test body
    and asserted on its own arithmetic — which would have stayed green with the
    fix deleted. A gate that cannot fail is not a gate, so this exercises the
    real decision and reads the committed calories back out.
    """
    import handlers.tool_executor as te

    async def _web(food_name, quantity):
        return {"calories": web_cal, "protein": 8, "carbs": 30, "fat": 15,
                "confidence": "high"}

    monkeypatch.setattr(te, "_web_lookup_meal", _web)
    monkeypatch.setenv("WEB_MEAL_ENRICH", "true")
    monkeypatch.setenv("FOOD_PLAUSIBILITY_CAP", "5.0")
    # No lookups: the estimate path is the one that opens the web lane.
    monkeypatch.setattr(te, "fetch_candidates",
                        lambda *a, **k: _none_candidates())

    inp = {"food_name": "Cali Roll", "quantity": "8 piece",
           "calories": interp_cal, "protein": 8, "carbs": 54, "fats": 4}
    out = await te._analyze_food(None, _user(), "Cali Roll", inp)

    if expect_web_wins:
        assert round(out.calories) == web_cal, (
            f"a {web_cal}/{interp_cal} move should have been accepted")
    else:
        assert round(out.calories) != web_cal, (
            f"the web total {web_cal} was committed over a baseline of "
            f"{interp_cal!r} — the cap cannot see a move from nothing")


def _user():
    from types import SimpleNamespace
    return SimpleNamespace(
        id=1, preferences=SimpleNamespace(food_logging_mode="moderate"))


async def _none_candidates():
    from handlers.tool_executor import FoodCandidates
    return FoodCandidates()
