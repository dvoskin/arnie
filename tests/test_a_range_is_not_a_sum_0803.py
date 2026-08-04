"""A hyphen between two digits is a range, not a mixed number.

`_parse_amount` works on a de-hyphenated copy, which is right for WORDS —
"three-quarters" and "three quarters" are one portion — and catastrophic for
DIGITS, because "5-6" became "5 6", which `_QTY_RE` reads as a mixed number and
ADDS:

    "5-6 pieces" -> 11        "2-3 eggs" -> 5
    "1-2 cups"   -> 3 (360g)  "3-4 oz"   -> 7 oz (198g)

Worst downstream: `_per_serving_for("2-3 bars", <190-cal panel>)` returned
**950 cal** — count x the label's own panel, on a path that sets
`computed_forward` and takes NO overcount demotion, so nothing objected.

THIS IS LIVE ON 47d0b01. It needs none of the 2026-08-03 portion work to hurt
anyone; the portion work only made the bad amount authoritative in more places.

THE MIDPOINT, not an end. The user stated both halves, so their own central
value is the honest reading. Not the high end — which is what shipped, "5-6
pcs" logged as 6 — and not the low, which quietly under-counts. "Bias high at
low confidence" is a rule about OUR estimates, not about a number the user gave
us both ends of.
"""
import pytest

from skills.nutrition.normalize import normalize_quantity


@pytest.mark.parametrize("quantity,expected", [
    ("5-6 pieces", 5.5),
    ("2-3 eggs", 2.5),
    ("1-2 cups", 1.5),
    ("2-3 bars", 2.5),
    ("3-4 oz", 3.5),
    ("2 - 3 slices", 2.5),      # spaced hyphen
    ("10-12 chips", 11.0),
])
def test_a_stated_range_becomes_its_midpoint(quantity, expected):
    assert normalize_quantity(quantity, "X").amount == pytest.approx(expected)


@pytest.mark.parametrize("quantity,expected", [
    # A MIXED NUMBER IS STILL A MIXED NUMBER. The slash lookahead is what keeps
    # "1-1/2" out of the range arm, and it is easy to break.
    ("1 1/2 cups", 1.5),
    ("1-1/2 cups", 1.5),
    ("2 1/4 cups", 2.25),
    # Words keep their de-hyphenation.
    ("three-quarters cup", 0.75),
    ("half a cup", 0.5),
    # Plain amounts are untouched.
    ("2 eggs", 2.0),
    ("200 g", 200.0),
    ("6 oz", 6.0),
    ("1 cup", 1.0),
    # The "to" form never reached the mixed-number arm and already took the
    # low end. Pinned so a future unification is a deliberate choice.
    ("5 to 6 pieces", 5.0),
])
def test_what_must_not_be_read_as_a_range(quantity, expected):
    assert normalize_quantity(quantity, "X").amount == pytest.approx(expected)


def test_a_range_no_longer_multiplies_a_label_panel():
    """The 950-calorie case, end to end through analyze().

    `_per_serving_for` multiplies the label's own per-serving panel by the
    count, and that arm returns with `computed_forward` set and no overcount
    demotion — so a doubled count is committed as label-grade fact.
    """
    import core.food_intelligence as FI
    src = {"description": "Quest Bar", "_match": "exact",
           "per100g": {"calories": 339, "protein": 36, "carbs": 43, "fat": 11},
           "per_serving": {"calories": 190, "protein": 21, "carbs": 24,
                           "fat": 6},
           "serving_text": "1 bar (56g)"}
    two_three = FI.analyze("Quest Bar", "2-3 bars", None, None, None, None,
                           memory_match=src)
    two = FI.analyze("Quest Bar", "2 bars", None, None, None, None,
                     memory_match=src)
    three = FI.analyze("Quest Bar", "3 bars", None, None, None, None,
                       memory_match=src)
    assert round(two.calories) == 380 and round(three.calories) == 570
    assert round(two_three.calories) == 475, (
        f"'2-3 bars' committed {two_three.calories} — a range was summed into "
        f"5 servings of a 190-cal bar")
    assert two.calories < two_three.calories < three.calories
