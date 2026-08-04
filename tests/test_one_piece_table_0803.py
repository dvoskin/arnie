"""Two piece tables existed and only one of them priced anything.

`skills/nutrition/normalize.PIECE_WEIGHTS_G` is what `normalize_quantity`
reads, so it decides whether "1 burger" has a mass at all.
`core/portions._PIECE_GRAMS` carries 34 single-item weights and feeds ONLY
`portion_check`, which returns an advisory string appended to a coach note
AFTER the write:

    "portion check: calories imply ~94 g but '1 burger' is typically ~226 g"

29 of its rows had no counterpart in the live table, so "1 burger",
"1 avocado", "1 potato", "1 chicken breast" and "1 muffin" resolved to NO MASS
and fell to the estimate path — where the model's calorie guess becomes the
portion. That is symptom 7's burger from the 2026-08-03 transcript: 240 cal
committed against a published ~500, with the correct 226 g printed underneath
in a note nothing acts on.

Folded rather than copied, so the two cannot drift.
"""
import pytest

from skills.nutrition.normalize import (PIECE_WEIGHTS_G,
                                        portion_mass_for_pricing)


def test_every_advisory_weight_can_now_price():
    """The gap itself. Anything `portion_check` knows how to complain about,
    pricing must be able to use."""
    from core.portions import _PIECE_GRAMS
    missing = [k for k in _PIECE_GRAMS if k not in PIECE_WEIGHTS_G]
    assert not missing, f"advisory-only piece weights: {missing}"


@pytest.mark.parametrize("quantity,food,grams", [
    ("1 burger", "Homemade burger", 226.0),
    ("1 avocado", "Avocado", 150.0),
    ("1 potato", "Potato", 213.0),
    ("1 muffin", "Muffin", 113.0),
    ("1 chicken breast", "Chicken breast", 174.0),
    ("2 chicken breast", "Chicken breast", 348.0),
])
def test_a_counted_whole_food_has_a_mass(quantity, food, grams):
    assert portion_mass_for_pricing(quantity, food) == pytest.approx(grams)


def test_an_existing_row_wins_over_the_advisory_one():
    """The live table's rows carry MEASURED spreads and were tuned against real
    logs; the advisory ones are bare medians. A fold must not overwrite the
    better data — bagel is 98 g here and 105 g there."""
    assert PIECE_WEIGHTS_G["bagel"][0] == 98.0
    assert PIECE_WEIGHTS_G["egg"] == (50.0, 6.0)


def test_the_burger_is_no_longer_priced_from_the_guess():
    """End to end, the transcript's own case."""
    import core.food_intelligence as FI
    usda = {"description": "Hamburger, single patty with bun",
            "_match": "exact",
            "per100g": {"calories": 254, "protein": 13.0, "carbs": 21.0,
                        "fat": 12.0}}
    out = FI.analyze("Homemade burger", "1 burger", 240, 35, 0, 0,
                     usda_candidate=usda)
    assert round(out.calories) > 450, (
        f"committed {out.calories} — a published burger is ~500-575 and the "
        f"model's 240 was still deciding the portion")


def test_a_folded_row_carries_a_spread():
    """`portion_check`'s table is a bare median. The spread is a STATED
    assumption — 25% of the median — not a measurement, and it matters because
    `confident_lower_mass` and `confident_upper_mass` read it to decide
    refusals."""
    grams, spread = PIECE_WEIGHTS_G["burger"]
    assert grams == 226.0
    assert spread == pytest.approx(226.0 * 0.25, abs=0.5)
