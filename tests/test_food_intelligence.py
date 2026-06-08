"""Pure-logic tests for food name handling — the generic-food gate that this
session shipped to stop silent memory reuse."""
import pytest
from core.food_intelligence import (
    normalize_name, is_generic_food_name, score_match, normalize_food_logging_mode,
)


@pytest.mark.parametrize("raw,expected", [
    ("Oikos Triple Zero Vanilla", "oikos triple zero vanilla"),
    ("a banana", "a banana"),            # normalize doesn't strip articles
    ("Chicken Breast 6oz", "chicken breast"),  # strips quantity
    ("  Built  Bar  ", "built bar"),
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("name", [
    "protein bar", "a protein bar", "the protein bar", "shake", "protein shake",
    "smoothie", "some smoothie", "a bowl", "snack", "trail mix", "energy drink",
    "milkshake", "cappuccino", "burrito", "taco", "pizza", "burger", "ramen",
    "oatmeal", "toast", "bagel", "cookies", "a cocktail", "beer", "leftovers",
])
def test_generic_names_flagged(name):
    assert is_generic_food_name(name) is True, name


@pytest.mark.parametrize("name", [
    "banana", "a banana", "chicken breast", "2 eggs", "built bar",
    "oikos shake", "barebells caramel", "rxbar chocolate", "quest bar",
    "dark chocolate", "chocolate banana", "grilled chicken", "white rice",
    "almond milk", "greek yogurt", "peanut butter", "chicken burrito",
    "beef taco", "margherita pizza", "starbucks latte", "apple", "salmon",
    "the usual shake", "my usual bar",
])
def test_specific_names_not_flagged(name):
    assert is_generic_food_name(name) is False, name


def test_score_match():
    assert score_match("banana", "banana, raw") == "exact"
    assert score_match("chicken breast", "chicken, breast, grilled") in ("likely", "exact")
    assert score_match("banana", "battery acid") == "estimated"


@pytest.mark.parametrize("value,current,expected", [
    # exact tier names pass through
    ("quick", "moderate", "quick"),
    ("moderate", "quick", "moderate"),
    ("strict", "moderate", "strict"),
    # UI synonyms for the default
    ("balanced", "strict", "moderate"),
    ("default", "quick", "moderate"),
    # relative steps from current tier
    ("less", "moderate", "quick"),
    ("more", "moderate", "strict"),
    ("less", "strict", "moderate"),
    ("more", "quick", "moderate"),
    # relative never overshoots the ladder ends
    ("less", "quick", "quick"),
    ("more", "strict", "strict"),
    # natural-language synonyms
    ("careful", "moderate", "strict"),
    ("just log it", "strict", "moderate"),  # unrecognized → safe default
    ("", "strict", "moderate"),
    (None, "quick", "moderate"),
])
def test_normalize_food_logging_mode(value, current, expected):
    assert normalize_food_logging_mode(value, current) == expected
