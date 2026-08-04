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


@pytest.mark.parametrize("question,label,expected", [
    # THE OPENER. An enumeration of interrogatives missed "was that" and
    # "were those", so the commonest question form in English kept its opener
    # and shipped it as a chip: ["Was that homemade", "Store-bought"], which
    # the user taps and sends back verbatim. Matched on shape now.
    ("Was that homemade or store-bought?", "", ["Homemade", "Store-bought"]),
    ("Were those baked or fried?", "", ["Baked", "Fried"]),
    ("Is it whole milk or skim?", "Milk", ["Whole milk", "Skim"]),
    ("Was the chicken grilled or fried?", "Chicken", ["Grilled", "Fried"]),
    ("What kind of bread, white or wheat?", "Bread", ["White", "Wheat"]),
    # THE SUBJECT. The interpreter writes facets both ways, and a leading food
    # name produced ["Chicken grilled", "Fried"]. The label IS the item this
    # question is attached to, so stripping it is exact rather than a guess.
    ("Chicken grilled or fried?", "Chicken", ["Grilled", "Fried"]),
    ("Rice white or brown?", "Rice", ["White", "Brown"]),
])
def test_the_opener_and_the_subject_are_not_answers(question, label, expected):
    assert _stated_options([question], label=label) == expected


def test_a_spelled_count_is_left_to_the_portion_path():
    """"one or two" is a COUNT. `_portion_options` prices it against the
    ontology; echoing the words back offers the same thing unpriced, and wins,
    because this is tried second."""
    assert _stated_options(["did you have one or two?"], label="Eggs") == []
    assert _stated_options(["a half or a whole?"], label="Bagel") == []


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


# ── a serial list is one question, not three fragments ───────────────────────

@pytest.mark.parametrize("text,label,expected", [
    ("Grilled, baked, or fried?", "Chicken", ["Grilled", "Baked", "Fried"]),
    ("Chicken grilled, baked, or fried?", "Chicken",
     ["Grilled", "Baked", "Fried"]),
    ("Hot, iced, or blended?", "Coffee", ["Hot", "Iced", "Blended"]),
])
def test_a_serial_list_survives_the_clause_splitter(text, label, expected):
    """LIVE, 2026-08-04. "Grilled, baked, or fried?" shipped NO chips.

    Two independent barriers, either of which was fatal:

      * the clause splitter ran on every comma, so the commonest three-way
        choice in English arrived as ["Grilled", "baked", "or fried"] — three
        fragments with no alternation left in any of them, so all three failed
        the both-sides test;
      * and that test was pinned at `len(parts) != 2`, so a three-way choice
        was rejected even on the rare occasions one survived the split.

    Both are fixed by one grammatical observation: a comma list whose LAST item
    is introduced by "or" is a serial list, and a serial list is one question.
    """
    assert _stated_options([text], label=label) == expected


def test_and_is_not_a_serial_conjunction():
    """The distinction that keeps the fix honest. "or" joins CHOICES; "and"
    joins CLAUSES. Matching both read the second question as a third choice and
    offered "About how much" as an answer to how the chicken was cooked, so the
    serial test requires "or" specifically — and a genuine two-question string
    still splits, still answers only its alternation."""
    assert _stated_options(["grilled or fried, and about how much?"],
                           label="Chicken") == ["Grilled", "Fried"]


def test_a_list_wider_than_the_chip_row_is_declined():
    """`chip_labels` caps a row at four, so a five-way list is not a row we
    could render. Declining is correct: a silently truncated list drops a real
    answer the user gave the question."""
    assert _stated_options(["Grilled, baked, fried, air-fried, or poached?"],
                           label="Chicken") == []


def test_the_existing_guards_survive_the_wider_split():
    """Widening 2 to 2-4 must not re-admit anything the narrow form rejected —
    these are the exact rows iOS shipped before the server owned chips."""
    assert _stated_options(["Any more coming or you calling it?"]) == []
    assert _stated_options(["one or two?"], label="Bars") == []
    assert _stated_options(["1 or 2?"], label="Bars") == []
