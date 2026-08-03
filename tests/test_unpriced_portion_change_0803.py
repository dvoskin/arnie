"""A portion and its macros may not disagree.

Every accuracy failure on 2026-08-03 was this one shape:

  1-cal rice          amount counted cups while unit said "ml"
  c360fad fallout     unit changed meaning; consumers matched the old token
  5-cal chicken       a "1 slice (5 g)" serving paired with "1 breast"
  460-cal roll        a whole-dish value paired with a one-piece count
  140-cal gummy       quantity became "1 burger", macros never re-derived

The last one is this file. `_apply_portion_correction` returns without touching
`changes` when both re-pricing arms decline, and prod le#936 carried
`{"quantity": "1 burger", "parsed_food_name": ...}` with NO calorie key — so
the row kept the 15-piece bag's 140 cal against one gummy burger.
"""
from skills.nutrition.correction_application import (apply_count_correction,
                                                     apply_portion)
from skills.nutrition.normalize import _serving_count


COMMITTED = {"calories": 140.0, "protein": 1.4, "carbs": 32.2, "fats": 0.0,
             "fiber": None, "sugar": None, "sodium": None}


def test_the_real_correction_still_declines_both_arms():
    """Documents WHY the fall-through matters — this is not hypothetical. A bag
    and a burger are different objects with no mass at either end, so neither
    arm can price it, and something has to happen other than silence."""
    assert apply_portion(
        food_name="Sour Gummy Mini Burgers", old_quantity="1 small snack bag",
        new_quantity="1 burger", committed=COMMITTED,
        per100={"calories": 350.0, "protein": 3.33, "carbs": 80.0, "fat": 0.0},
        serving_text="15 PIECES") is None
    assert apply_count_correction(
        food_name="Sour Gummy Mini Burgers", old_quantity="1 small snack bag",
        new_quantity="1 burger", committed=COMMITTED) is None


def test_an_uppercase_serving_panel_is_readable():
    """USDA writes panels in caps. `_singular` does not lowercase, so "15
    PIECES" became "PIECE" and missed a lowercase `_COUNT_UNITS` — the panel on
    the very row this incident is about was unreadable."""
    assert _serving_count("15 PIECES") == (15.0, "piece")
    assert _serving_count("35 g (12 PIECES)") == (12.0, "piece")
    assert _serving_count("1 SLICE (5 g)") == (1.0, "slice")
    # Still parses what it always did.
    assert _serving_count("12 pieces") == (12.0, "piece")


def test_the_seam_marks_an_unpriceable_change_estimated():
    """The invariant, at the one seam B2 proved is the only one: a quantity
    change that could not be re-derived may not present its inherited macros as
    derived. The correction still lands — the user's words are not in doubt —
    but the row says it is an estimate and the mismatch is logged."""
    import inspect

    import handlers.tool_executor as TE

    src = inspect.getsource(TE._apply_portion_correction)
    assert "unpriced_portion_change" in src, (
        "the unpriceable fall-through no longer logs the mismatch")
    assert 'changes["estimated_flag"] = True' in src, (
        "an unpriceable portion change must not present inherited macros as "
        "derived")
    # And it must only fire when the caller supplied NO macros of its own —
    # a user reading us a number ("it says 80 online") still wins untouched.
    assert 'if not any(k in changes for k in' in src
