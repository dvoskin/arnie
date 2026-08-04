"""A food that comes in pieces is bracketed — and asked about — in pieces.

Measured 2026-08-04, after the chicken-and-rice work: the human-unit chips
covered 7 of 24 ordinary foods. Danny's test was "this should work equally well
for a burger and fries as well as any other meal combo", and burger and fries
both came back `[30g] [80g] [200g]`.

Grams were the smaller half of that problem. `food_category` returns "default"
for burger, fries, potato, egg, meatball and most of what people eat, so every
one of them was bracketed by `some.default` — 30-200 g. A burger is 226 g. The
single most ordinary meal in the product was bracketed ENTIRELY BELOW its own
weight, and the chips built from that bracket offered portions of a burger
nobody eats. That is not a less precise answer than the right one; it is an
answer to a different question.

The missing tier was never missing data. `PIECE_WEIGHTS_G` has held burger=226,
egg=50 and chicken breast=174 all along, and `distribution_for` never consulted
it.

Two derived gates decide whether the tier applies — no constant is introduced:

  * the food has a piece weight at all, head-noun matched, so "banana bread" is
    not a banana;
  * and that piece is SERVING-SCALE, meaning at least the smallest portion the
    ontology already calls a portion of this food. One french fry is 8 g
    against a floor of 30, so fries keep their category row and are not
    counted. That gate is the whole reason this does not produce "5 fries".
"""
import pytest

from core.food_pipeline import _measure_options
from skills.nutrition.normalize import normalize_quantity as nq
from skills.nutrition.portions import Specificity, distribution_for


# ── the bracket ──────────────────────────────────────────────────────────────

def test_a_burger_is_bracketed_as_a_burger():
    """The headline. Was (30, 80, 200) for a 226 g food."""
    d = distribution_for("some", "burger")
    assert d.specificity is Specificity.PIECE
    assert d.median_g == 226.0
    assert d.lower_g <= 226.0 <= d.upper_g, (
        "the food's own weight has to be inside its own bracket")


@pytest.mark.parametrize("food,median", [
    ("burger", 226.0), ("eggs", 50.0), ("apple", 182.0),
    ("hot dog", 76.0), ("meatballs", 30.0), ("potatoes", 213.0),
    ("chicken breast", 174.0),
])
def test_countable_foods_use_their_own_unit(food, median):
    d = distribution_for("some", food)
    assert d.specificity is Specificity.PIECE and d.median_g == median


@pytest.mark.parametrize("food", ["fries", "tortilla chips"])
def test_a_sub_unit_is_not_a_portion(food):
    """THE GATE THAT KEEPS THIS HONEST. These foods HAVE a piece weight —
    that is exactly why they are dangerous. One fry is 8 g, well under the
    smallest portion the ontology allows, so the piece tier declines and they
    keep the category row they had. Without this the chips read "4 fries"."""
    d = distribution_for("some", food)
    assert d.specificity is not Specificity.PIECE


@pytest.mark.parametrize("food", ["banana bread", "eggplant parmesan",
                                  "orange chicken", "chipotle bowl"])
def test_the_head_noun_guard_still_holds(food):
    """A compound is not its modifier. Banana bread is not 118 g of banana."""
    d = distribution_for("some", food)
    assert d.specificity is not Specificity.PIECE


def test_chicken_and_rice_are_untouched():
    """The foods the earlier pass fixed keep their category rows — this tier
    sits above the category one and must not shadow it."""
    assert distribution_for("some", "chicken").specificity \
        is Specificity.CATEGORY
    assert distribution_for("some", "rice").specificity is Specificity.CATEGORY


# ── the chips that follow from it ────────────────────────────────────────────

@pytest.mark.parametrize("food,expected", [
    ("burger", ["1 burger", "2 burgers"]),
    ("eggs", ["1 egg", "2 eggs"]),
    ("potatoes", ["1 potato", "2 potatoes"]),
    ("apple", ["1 apple", "2 apples"]),
    ("hot dog", ["1 hot dog", "2 hot dogs"]),
])
def test_a_counted_food_is_asked_about_in_counts(food, expected):
    """Named with the TABLE's singular key, not the user's wording: "1
    potatoes" is not a chip anyone taps. And pluralised properly — `+ "s"`
    wrote "potatos" and "friess"."""
    d = distribution_for("some", food)
    assert list(_measure_options("some", d, food)) == expected


@pytest.mark.parametrize("food", ["burger", "eggs", "potatoes", "apple",
                                  "hot dog", "meatballs", "tomatoes"])
def test_every_count_chip_prices(food):
    """The invariant that makes a chip safe to tap: a tapped label is recorded
    as the user's OWN figure, so one that does not price puts an unpriceable
    portion on the board under their name."""
    d = distribution_for("some", food)
    labels = _measure_options("some", d, food)
    assert labels, f"{food} produced no options at all"
    for label in labels:
        assert nq(label, food).grams, f"{label!r} does not price for {food}"


def test_counts_are_not_offered_for_uncounted_foods():
    """`_count_labels` reads the TIER, not the piece table. Reading the table
    directly offered "4 friess" and "8 chips" — foods that have a piece weight
    precisely because the piece is a sub-unit."""
    for food in ("fries", "tortilla chips", "chicken", "rice"):
        d = distribution_for("some", food)
        for label in _measure_options("some", d, food):
            assert not label[:1].isdigit() or " " not in label or \
                not label.split()[1].startswith(("fri", "chip")), \
                f"{food} should not be counted: {label!r}"


# ── the parsing bug found underneath it ──────────────────────────────────────

@pytest.mark.parametrize("stated,food,grams", [
    ("1 potato", "potatoes", 213.0),
    ("1 tomato", "tomatoes", 123.0),
    ("2 potatoes", "potatoes", 426.0),
    ("1 egg", "eggs", 50.0),
    ("1 burger", "burgers", 226.0),
])
def test_a_stated_count_prices_against_a_plural_food(stated, food, grams):
    """FOUND WHILE BUILDING THE CHIPS, AND WORSE THAN THEM. `food_as_unit`
    compared `rstrip("s")` stems, so "1 potato" against a food read as
    "potatoes" compared "potato" to "potatoe", decided the food was not its own
    unit, and returned NO MASS for a portion the user had stated exactly. Every
    -o and -y food had it. This is the user's own typing, not a chip."""
    assert nq(stated, food).grams == grams
