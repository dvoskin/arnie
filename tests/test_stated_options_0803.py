"""The choice the question already names is an answer the server can ship.

Prod 2026-08-03. `conversation.py` is the only producer of `Response.buttons`,
and on the interpreter branch — where most asks come from — its option sources
were a branded Open Food Facts shelf and, since `portion-chips`, the ontology
bracket. A PREPARATION question ("fast food or homemade?") matched neither and
shipped nothing.

Nothing is not what the user saw. iOS falls back to `QuickReplyEngine.swift`,
which re-derives choices by parsing the RENDERED reply — it splits on the last
sentence terminator, then on "or"/commas. Two rows from that transcript:

    "Chicken grilled or fried, and about how much, a cup or two?
     And the rice, cup or more than that?"     ->  Rice | Cup | More than that
    "Any more coming or you calling it?"       ->  Coming | You calling it

The first discards the entire grilled-or-fried question — the parser only ever
sees the last sentence. The second is not a food question at all.

The server does not have that problem, because it is not parsing prose: it has
the facets as the interpreter authored them, one clause per question. Doing the
extraction here also gives it to Telegram and iMessage, which have no parser and
have always shipped no options whatsoever.

These pin both directions — what must be offered, and what must never be.
"""
import pytest

from core.food_turn import _stated_options


@pytest.mark.parametrize("question,expected", [
    ("fast food or homemade?", ["Fast food", "Homemade"]),
    ("deli or roasted?", ["Deli", "Roasted"]),
    ("a light scrape or a real spread?", ["A light scrape", "A real spread"]),
    ("was it the leaner one or the regular?", ["The leaner one", "The regular"]),
    # Two questions in one string: only the alternation is chip-answerable, and
    # the trailing portion ask must not bleed into the options.
    ("grilled or fried, and about how much?", ["Grilled", "Fried"]),
])
def test_the_choice_in_the_question_becomes_the_choice_on_the_wire(
        question, expected):
    assert _stated_options([question]) == expected


@pytest.mark.parametrize("question,why", [
    ("Any more coming or you calling it?",
     "not a food facet — this is the exact iOS 'Coming | You calling it' row"),
    ("how much, and what fat %?",
     "no alternation; the portion bracket answers this one properly"),
    ("which flavour was it?",
     "open question, no choices named"),
    ("did you have one or two?",
     "a count, which the portion path prices rather than echoes"),
    ("was it the one you always get or did you try the new seasonal thing?",
     "sides are sentences, not choices"),
])
def test_what_must_never_become_a_chip(question, why):
    assert _stated_options([question]) == [], why


def test_a_digit_is_left_to_the_portion_path():
    """A side carrying a number is a portion answer. `_portion_options` prices
    those against the ontology; echoing the words back would offer the same
    thing without the pricing, and would win because it is tried second."""
    assert _stated_options(["100g or 200g?"]) == []


def test_the_first_answerable_facet_wins():
    """The interpreter may raise several facets for one item. The chips bind to
    the question group, so the first facet that yields real choices is the one
    the row belongs to."""
    assert _stated_options(
        ["roughly how much?", "grilled or fried?"]) == ["Grilled", "Fried"]
