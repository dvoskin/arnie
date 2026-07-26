"""When the unit word IS the product (shipped: Nissin Cup Noodles).

    USER   Just had a cup noodles protein chicken flavor
    ARNIE  I'm reading that as a cup noodles protein chicken flavor. Right?
    USER   Yes sir
    LOGGED 220 cal, 15g protein          (actual: 320 / 16)

Identity resolution was perfect — it found the brand, the product and the
line. The nutrition was wrong, and so was every micronutrient under it,
because "1 cup" of Cup Noodles was converted to 236 ml and then to 140 g of
nothing. The package is 64 g. Every calorie, macro and micro was scaled from
a mass with no relation to the food.

`_count_basis` already carried this exception for VAGUE units — "1 bowl" of a
Chipotle burrito bowl counts the product, not a helping. But mass and volume
conversion happens EARLIER in `normalize_quantity` and returns before that
check is reached, so the exception could not apply to the case that needed it
most.
"""
import pytest

from skills.nutrition.normalize import _unit_names_the_food, normalize_quantity


def test_the_shipped_case():
    q = normalize_quantity("1 cup", "Nissin Cup Noodles Protein Chicken Flavor")
    assert q.count == 1
    assert q.unit == "cup"
    assert q.grams is None, "236 ml of Cup Noodles is a mass of nothing"


def test_a_measure_that_really_is_a_measure_still_converts():
    """The discriminator is "of". In "cup of coffee" the cup measures the
    coffee; in "Cup Noodles" it names them."""
    assert normalize_quantity("1 cup", "cup of coffee").milliliters is not None
    assert normalize_quantity("1 cup", "rice").grams == pytest.approx(158.5, abs=1)
    assert normalize_quantity("2 cups", "milk").milliliters is not None


@pytest.mark.parametrize("unit,food,expected", [
    ("cup", "Nissin Cup Noodles", True),
    ("cup", "cup of coffee", False),
    ("cup", "rice", False),
    ("bowl", "Chipotle burrito bowl", True),
    ("bowl", "bowl of chowder", False),
])
def test_the_of_rule(unit, food, expected):
    assert _unit_names_the_food(unit, food) is expected


def test_a_count_unit_in_the_food_name_keeps_its_piece_weight():
    """Narrowed to units that CONVERT. "2 cookies" of a cookie is already
    handled by the countable path, which gives it a piece weight — and
    intercepting it here would throw that away."""
    q = normalize_quantity("2 cookies", "chocolate chip cookie")
    assert q.grams is not None and q.grams > 0


def test_a_stated_mass_is_never_reinterpreted():
    """"6 oz" is a measurement whatever the food is called."""
    assert normalize_quantity("6 oz", "6 oz steak").grams == pytest.approx(
        170.1, abs=0.5)
