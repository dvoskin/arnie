"""Every portion word Arnie offers has to be one the resolver can read back.

The shipped failure:

    Arnie asks   "palm-sized, plate-sized, or huge?"   (core/prompts/arnie.py)
    user says    "a palm size"
    card shows   "0.5 palm-size cutlet · 420 cal"

`detect_measure("a palm size")` returned None, so `derive_vague_quantities`
derived nothing, `_portion_stakes` scored zero, and nothing could turn a palm
into grams. With no resolution to constrain it the interpreter improvised — a
fractional count of a unit it made up on the spot, at calories that matched a
WHOLE palm. The number was fine and the label was fiction, which is worse than
a wrong number because nothing downstream can tell.

Of the three options in that question the table could read exactly one:

    palm-sized   -> None
    plate-sized  -> plate      (250 / 400 / 650 g)
    huge         -> None       (a SIZE_MODIFIER, not a measure)

This is the lane's recurring defect in its most expensive place: two lists
describing one thing, disagreeing — and here the list Arnie speaks from is the
one the user answers.
"""
import re

import pytest

from skills.nutrition.portions import (SIZE_MODIFIERS, detect_measure,
                                       distribution_for)

#: The gestures the prompt teaches. Kept here rather than parsed out of the
#: prompt so that adding one to the prompt without a distribution FAILS rather
#: than silently passing an empty set.
ASKABLE = ("palm", "fist", "thumb", "plate", "bowl", "handful", "scoop",
           "slice", "spoonful", "bite")


@pytest.mark.parametrize("measure", ASKABLE)
def test_every_askable_measure_resolves_to_a_mass(measure):
    assert detect_measure(f"about a {measure}") == measure
    dist = distribution_for(measure, "chicken")
    assert dist and dist.median_g > 0, (
        f"Arnie can ask in {measure!r} and cannot read the answer")


@pytest.mark.parametrize("phrasing", [
    "a palm size", "palm-sized", "palm sized", "about a palm",
    "the size of my palm", "two palms",
])
def test_the_ways_people_actually_say_palm(phrasing):
    assert detect_measure(phrasing) == "palm"


def test_the_prompts_own_example_question_is_fully_readable():
    """The question in `core/prompts/arnie.py` offers three options. Two of
    them used to resolve to nothing."""
    import pathlib
    src = pathlib.Path("core/prompts/arnie.py").read_text()
    match = re.search(r'"([^"]*palm-sized[^"]*)"', src)
    assert match, "the palm-sized example question moved — update this test"
    for option in re.findall(r"([a-z]+)-sized", match.group(1)):
        assert detect_measure(f"{option}-sized") == option, (
            f"the prompt offers {option!r} and the resolver cannot read it")


def test_a_size_word_is_not_a_measure_and_is_not_offered_alone():
    """"huge" scales a portion; it does not name one. It belongs beside a
    measure ("a huge handful"), never as a standalone answer."""
    assert detect_measure("huge") is None
    assert "huge" in SIZE_MODIFIERS
    assert detect_measure("a huge handful") == "handful"


def test_a_palm_of_meat_lands_near_a_deck_of_cards():
    """The standard protein gesture. There is no meat category — chicken,
    salmon and steak all reach `default` — so the default row IS the protein
    number rather than an average over foods nobody measures this way."""
    for food in ("chicken breast", "grilled salmon", "steak",
                 "chicken schnitzel, breaded and fried"):
        dist = distribution_for("palm", food)
        assert 80 <= dist.median_g <= 145, (food, dist.median_g)


# ── and the stored quantity is standardised ──────────────────────────────────
def test_a_hand_gesture_is_stored_as_the_mass_it_means():
    """The card shows the stored quantity and a tap edits it, so it has to be
    a number a person can reason about. "0.5 palm-size cutlet" is neither
    comparable across days nor correctable — there is no honest figure to
    raise or lower."""
    from core.food_turn import _log_call
    call = _log_call({"food": "Chicken schnitzel, breaded and fried",
                      "amount": 1, "unit": "palm size", "calories": 420})
    assert call["input"]["quantity"] == "110 g"


def test_the_shipped_fraction_would_now_read_as_a_mass():
    from core.food_turn import _log_call
    call = _log_call({"food": "Chicken schnitzel, breaded and fried",
                      "amount": 0.5, "unit": "palm-size cutlet",
                      "calories": 420})
    assert call["input"]["quantity"] == "55 g"


@pytest.mark.parametrize("amount,unit", [
    (1, "cup"), (2, "slices"), (1, "handful"), (150, "g"), (1, "bar"),
])
def test_a_real_unit_is_left_alone(amount, unit):
    """Only SIZE gestures are converted. A slice, a handful and a cup all name
    something countable, read naturally on a card, and can be edited."""
    from core.food_turn import _log_call
    call = _log_call({"food": "Toast", "amount": amount, "unit": unit,
                      "calories": 100})
    assert call["input"]["quantity"] == f"{amount} {unit}"
