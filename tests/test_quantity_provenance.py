"""Directive §2, §3, §10 — what the user said, kept apart from what we made of it.

Three faults with one shape: the normalizer's output replaced its input.

  * §3 — every digit fraction was multiplied by its numerator. "3/4 cup" came
    back as amount 3 with unit "/4", because the amount pattern tried
    `\\d+(?:\\.\\d+)?` before `\\d+/\\d+` and regex alternation is leftmost-first.
    Three quarters of a cup of rice logged as three cups.
  * §2 — an assumed size arrived as a fact. PIECE_WEIGHTS_G's 50 g egg is a
    LARGE egg and nothing said so, so "2 eggs → 100 g" read as though the user
    had specified the size.
  * §10 — once normalized, there was no route back to the words that produced
    the number, so anything quoting the portion had to rebuild it: "half a
    bagel" returned to the user as "0.5 bagel".
"""
import pytest

from skills.nutrition.normalize import normalize_quantity


# ── §3: fractions ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("1/4 cup", 0.25),
    ("1/3 cup", 1 / 3),
    ("1/2 cup", 0.5),
    ("2/3 cup", 2 / 3),
    ("3/4 cup", 0.75),
])
def test_digit_fractions_are_the_fraction_not_the_numerator(text, expected):
    """The shipped bug, in the five forms a person actually types."""
    assert normalize_quantity(text, "rice").amount == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    ("½ cup", 0.5), ("⅓ cup", 1 / 3), ("⅔ cup", 2 / 3),
    ("¼ cup", 0.25), ("¾ cup", 0.75), ("⅛ cup", 0.125),
])
def test_unicode_fractions(text, expected):
    assert normalize_quantity(text, "rice").amount == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    ("half a bagel", 0.5),
    ("a half bagel", 0.5),
    ("one half bagel", 0.5),
    ("two thirds of a cup", 2 / 3),
    ("three quarters of a cup", 0.75),
    ("three-quarters of a cup", 0.75),
    ("a quarter of a pizza", 0.25),
])
def test_word_fractions(text, expected):
    """`startswith` against a flat table read "two thirds" as 2 and
    "three-quarters" as 1 — both of them portions the user stated exactly."""
    assert normalize_quantity(text, "bagel").amount == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    ("1 1/2 cups", 1.5),
    ("1 ½ cups", 1.5),
    ("2 1/2 cups", 2.5),
    ("one and a half bagels", 1.5),
])
def test_mixed_numbers(text, expected):
    assert normalize_quantity(text, "rice").amount == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    ("0.5 cup", 0.5), ("1.5 cups", 1.5), ("6 oz", 6.0), ("200g", 200.0),
])
def test_decimals_and_whole_numbers_still_parse(text, expected):
    assert normalize_quantity(text, "rice").amount == pytest.approx(expected)


def test_a_quarter_pounder_is_not_a_quarter_of_anything():
    """A fraction word inside a product name is part of the name."""
    assert normalize_quantity("a quarter pounder", "burger").amount == 1.0


def test_an_article_is_not_the_amount_when_a_number_follows():
    """"A couple of eggs" is two eggs. Reading the article as 1 halved it."""
    assert normalize_quantity("a couple of eggs", "eggs").amount == 2.0
    assert normalize_quantity("a few slices", "bread").amount == 3.0
    assert normalize_quantity("a dozen wings", "chicken wings").amount == 12.0


# ── §2: provenance ──────────────────────────────────────────────────────────

def test_an_assumed_size_arrives_as_an_assumption():
    """The 50 g default IS a large egg. Presenting it silently is a decision of
    ours wearing the user's authority."""
    q = normalize_quantity("2 eggs", "eggs")
    assert q.grams == 100.0
    assert any("assumed large egg" in a for a in q.assumptions)


def test_a_stated_size_is_not_re_assumed():
    """They said large. Telling them we assumed it is noise, and worse, it
    implies we might have chosen differently."""
    q = normalize_quantity("2 large eggs", "eggs")
    assert q.size_descriptor == "large"
    assert not any("assumed" in a for a in q.assumptions)


def test_stating_no_amount_is_not_the_same_as_stating_one():
    """`amount` defaults to 1.0 so the arithmetic has something to work with,
    and that default was indistinguishable downstream from a user who said
    "one". Only one of them is safe to quote back."""
    assert normalize_quantity("", "rice").user_stated_amount is None
    assert normalize_quantity("chicken", "chicken").user_stated_amount is None
    assert normalize_quantity("2 eggs", "eggs").user_stated_amount == 2.0


def test_the_unit_we_scale_in_is_not_the_unit_they_said():
    """"6 oz" becomes unit="g" because grams are the scaling currency. Correct
    arithmetic, wrong thing to quote back — they said ounces."""
    q = normalize_quantity("6 oz", "chicken")
    assert q.unit == "g" and q.grams == pytest.approx(170.1, abs=0.1)
    assert q.user_stated_unit == "oz"


def test_an_exact_conversion_and_a_guess_do_not_travel_as_the_same_number():
    """Both used to be a bare `grams` float, which is how an estimate got
    presented with the certainty of a measurement."""
    exact = normalize_quantity("200g", "rice")
    guess = normalize_quantity("a bowl of pasta", "pasta")
    assert exact.mass_is_exact and exact.normalization_source == "mass_conversion"
    assert not guess.mass_is_exact
    assert guess.normalization_confidence < exact.normalization_confidence


def test_normalized_mass_is_reachable_under_a_name_that_states_its_direction():
    q = normalize_quantity("6 oz", "chicken")
    assert q.normalized_mass_g == q.grams
    assert normalize_quantity("1 cup", "milk").normalized_volume_ml is not None


# ── §10: the user's words survive ───────────────────────────────────────────

def test_the_portion_is_described_in_the_users_own_words():
    """A clarification about something ELSE in the meal reprinted this line;
    the user then reads their own sentence rewritten by us."""
    q = normalize_quantity("Half a Bagel", "bagel")
    assert q.describe() == "Half a Bagel"
    assert "0.5" not in q.describe()


def test_wording_survives_when_the_amount_is_a_fraction_of_a_piece():
    q = normalize_quantity("three-quarters of a cup", "rice")
    assert q.original_user_wording == "three-quarters of a cup"


def test_the_reconstruction_is_the_last_resort_not_the_default():
    from skills.nutrition.models import NormalizedQuantity
    bare = NormalizedQuantity(amount=2.0, unit="slice")
    assert bare.describe() == "2 slice"
