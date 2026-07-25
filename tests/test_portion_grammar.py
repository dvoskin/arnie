"""Portion grammar, parsed rather than suffixed (directive 2026-07-25, §11).

A portion arrives as free text — "2 small slice", "2 large", "3 stick" — and the
old renderer took everything after the number as one opaque unit string and
pluralized it by suffix. Three shipped screenshots came out of that:

    "Two small sliceses of vodka pizza"
    "Three stickses of mozzarella sticks with marinara"
    "Two larges of eggs"

The fix is structural, not a list of special cases: a portion is

    amount · size descriptor · unit head · food name

and each part is inflected as what it is. A descriptor is an adjective and never
takes a plural. A unit head that is already plural is left alone. A unit that
names the food is dropped. The food's own head noun is the thing that inflects,
which is not always its last word.
"""
import pytest

from core.food_response import describe_portion


# ── the exact outputs the directive requires ──────────────────────────────────
@pytest.mark.parametrize("portion,food,expected", [
    ("2 small slice", "vodka pizza", "two small slices of vodka pizza"),
    ("2 small slices", "vodka pizza", "two small slices of vodka pizza"),
    ("3 stick", "mozzarella sticks with marinara",
     "three mozzarella sticks with marinara"),
    ("2 large", "eggs", "two large eggs"),
    ("0.75 cup", "egg whites", "three quarters of a cup of egg whites"),
    ("0.5 hero", "chicken parm hero", "half a chicken parm hero"),
])
def test_the_required_phrasings(portion, food, expected):
    assert describe_portion(portion, food) == expected


#: The three strings that shipped. None may ever be producible again.
FORBIDDEN = ("sliceses", "stickses", "larges of", "eses ")


@pytest.mark.parametrize("portion,food", [
    ("2 small slice", "vodka pizza"), ("2 small slices", "vodka pizza"),
    ("3 stick", "mozzarella sticks with marinara"),
    ("3 sticks", "mozzarella sticks"), ("2 large", "eggs"),
    ("2 larges", "eggs"), ("4 thin slice", "bread"),
    ("6 thin slices", "turkey"), ("2 small box", "raisins"),
    ("3 large glass", "orange juice"), ("2 medium ear", "corn"),
])
def test_no_malformed_pluralization(portion, food):
    out = describe_portion(portion, food)
    for bad in FORBIDDEN:
        assert bad not in out, f"{portion!r} {food!r} produced {out!r}"


# ── compound units named in the directive ─────────────────────────────────────
@pytest.mark.parametrize("portion,food", [
    ("2 small slice", "pizza"),
    ("2 large egg", "eggs"),
    ("1 heaping tablespoon", "peanut butter"),
    ("1 thin piece", "filet mignon"),
    ("1 small bowl", "caesar salad"),
    ("1 medium ear", "corn"),
    ("1 mini bar", "Snickers"),
])
def test_compound_units_keep_both_words(portion, food):
    """The size word and the unit head are different things, and both survive."""
    descriptor = portion.split()[1]
    out = describe_portion(portion, food, branded=True)
    assert descriptor in out, f"{portion!r} lost its size word: {out!r}"


def test_a_descriptor_is_never_a_unit():
    """"2 large" of eggs has no unit at all — the descriptor belongs to the
    food. It used to be pluralized as though it were the noun."""
    assert describe_portion("2 large", "eggs") == "two large eggs"
    assert describe_portion("1 large", "egg") == "a large egg"


def test_a_bare_count_unit_still_disappears():
    """"piece" says nothing on its own and is dropped — but "thin piece" says
    the thing the user bothered to tell us, so it stays."""
    assert describe_portion("2 piece", "filet mignon") == "two filet mignons"
    assert describe_portion("1 thin piece", "filet mignon") == \
        "a thin piece of filet mignon"


def test_a_unit_already_in_the_food_name_is_said_once():
    """The dedupe used to check only the END of the food name, so a unit in the
    middle survived: "three sticks of mozzarella sticks with marinara"."""
    out = describe_portion("3 stick", "mozzarella sticks with marinara")
    assert out.count("stick") == 1, out


def test_the_food_head_inflects_not_its_last_word():
    """"mozzarella sticks with marinara" is a kind of STICK. Pluralizing the
    last word inflected the sauce."""
    assert "marinaras" not in describe_portion(
        "3 stick", "mozzarella sticks with marinara")
    assert describe_portion("2 piece", "chicken with rice") == \
        "two chickens with rice"


def test_one_of_a_plural_food_reads_singular():
    assert describe_portion("1 large egg", "eggs") == "a large egg"


# ── §13: the card owns the facts, the text does not repeat them ───────────────
def _card_plan(*names):
    from core.food_response import (CARD_FACTS, FoodItemSummary,
                                    FoodResponseIntent, FoodResponsePlan,
                                    apply_policy)
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT, card_will_render=True,
        facts_visible_in_card=CARD_FACTS,
        committed_items=tuple(FoodItemSummary(name=n) for n in names)))


def test_the_logged_roll_call_is_dropped_when_a_card_renders():
    """It shipped directly above a card listing the same four names with their
    macros. A receipt printed twice is noise between the user and the card."""
    from core.food_response import strip_card_recitation
    plan = _card_plan("Mashed Potato", "Grilled Corn", "Filet Mignon",
                      "Reese's Pieces")
    text = "Logged: Mashed Potato, Grilled Corn, Filet Mignon, Reese's Pieces."
    assert strip_card_recitation(text, plan) == ""


@pytest.mark.parametrize("sentence", [
    "That leaves about 240 calories for the day, so the rest needs to stay light.",
    "Protein is running light, though, about 60g to go, so make your next meal protein-forward.",
    "That leaves about 10 calories for the day, so the rest needs to stay light.",
    "You have 1,990 remaining.",
])
def test_the_remaining_budget_is_not_restated_beneath_the_card(sentence):
    """The card renders "240 cal left · 60g protein to go" and often its own
    "Next:" line. These survived the old check by ending forward-looking, which
    is exactly the shape that shipped: the remaining row twice, with advice
    stapled to the second copy."""
    from core.food_response import strip_card_recitation
    assert strip_card_recitation(sentence, _card_plan("Eggs")) == ""


@pytest.mark.parametrize("sentence", [
    "I'd aim for 30-40g at lunch.",
    "Nice work getting a vegetable in there.",
    "Worth pairing that with something lean tonight.",
])
def test_a_real_recommendation_still_earns_its_words(sentence):
    """A target for a FUTURE meal is not a restatement of today's balance."""
    from core.food_response import strip_card_recitation
    assert strip_card_recitation(sentence, _card_plan("Eggs")) == sentence


def test_nothing_is_stripped_where_no_card_renders():
    """Telegram has no card frame — there these sentences are the only
    confirmation the user gets."""
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    apply_policy, strip_card_recitation)
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COMMIT,
                                         card_will_render=False))
    text = "That leaves about 240 calories for the day."
    assert strip_card_recitation(text, plan) == text
