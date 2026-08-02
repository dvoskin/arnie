"""Macro-consistency invariant (prod 0801): sugar/fibre can't exceed carbs.

Whiskey logged sugar 39g against 0 carbs; Drizzlicious sugar 22g against 6g carbs.
Root: the only cap lived in the estimator branch AND bypassed itself when carbs==0
(`min(sug,carbs) if carbs else sug`), and a label's own numbers were never checked.
`_enforce_macro_consistency` runs on the FINAL result, every source.
"""
from types import SimpleNamespace
from handlers.tool_executor import _enforce_macro_consistency


def _r(carbs, sugar=None, fiber=None):
    return SimpleNamespace(carbs=carbs, sugar=sugar, fiber=fiber)


def test_zero_carbs_caps_sugar_to_zero():          # the whiskey case
    assert _enforce_macro_consistency(_r(0, sugar=39.34)).sugar == 0.0


def test_sugar_capped_to_carbs():                   # the Drizzlicious case
    assert _enforce_macro_consistency(_r(6, sugar=22.0)).sugar == 6.0


def test_fiber_capped_to_carbs():
    assert _enforce_macro_consistency(_r(5, fiber=12.0)).fiber == 5.0


def test_valid_macros_untouched():
    r = _enforce_macro_consistency(_r(30, sugar=10, fiber=4))
    assert r.sugar == 10 and r.fiber == 4


def test_none_carbs_is_left_alone():
    # No carb count to check against — don't invent a cap.
    assert _enforce_macro_consistency(_r(None, sugar=5)).sugar == 5
