"""The food lane's lookup line is routine, so it sounds like him and it varies.

`_TOOL_HEADS_UP_BUBBLES` is flat on purpose, and its own test explains why:
those lines fire only when the model emitted a tool_use block with no text in
front of it — "a rare degenerate case" — and the wit is meant to live in the
model-written heads-up. Sound reasoning for every lane it was written for.

It does not survive the structured food lane. That branch sets
`result["text"] = ""` by construction, so `_model_wrote_text` is False on every
food turn and there is no model line to carry the voice. The deterministic
string is not the fallback there; it is the whole experience.

The same test names the condition: "If a user sees these routinely, the
upstream bug is the model skipping text; the fix is the prompt rule, not these
strings." Nothing is skipping anything here — there is no first pass to
instruct — so the fix is a pool of its own.

What carries over from the emergency rules, because it was right: short, no
forced-casual filler, and it describes a LOOKUP. Nothing may suggest the row
has landed before it has.
"""
import pytest

from handlers.tool_executor import (FOOD_LOOKUP_HEADS_UP,
                                    _FOOD_LOOKUP_BUBBLES,
                                    _TOOL_HEADS_UP_BUBBLES, tool_heads_up)

FOODS = ["cheez doodles", "takis fuego", "legendary protein roll",
         "mcdonalds cheeseburger", "apple", "greek yogurt", "quest chips",
         "a scoop of peanut butter", "birria tacos", "cottage cheese"]


def test_it_has_its_own_pool_and_did_not_loosen_the_emergency_ones():
    """The emergency lines stay generic for the lanes that still want them."""
    assert FOOD_LOOKUP_HEADS_UP not in _TOOL_HEADS_UP_BUBBLES
    assert len(_FOOD_LOOKUP_BUBBLES) >= 10, "a run of logs must not repeat"


def test_a_run_of_different_foods_does_not_repeat_itself():
    """The old index was `len(seed) % len(bubbles)` — every eleven-character
    food got the same line, so the pool sat unused while the user saw one
    string. Keyed on a hash now."""
    lines = {tool_heads_up(FOOD_LOOKUP_HEADS_UP, f) for f in FOODS}
    assert len(lines) >= 4, lines


def test_the_same_food_always_gets_the_same_line():
    """Deterministic, so a retry of one turn does not change its wording."""
    for food in FOODS:
        assert (tool_heads_up(FOOD_LOOKUP_HEADS_UP, food)
                == tool_heads_up(FOOD_LOOKUP_HEADS_UP, food))


@pytest.mark.parametrize("line", _FOOD_LOOKUP_BUBBLES)
def test_every_line_describes_a_lookup_and_never_a_write(line):
    """`NO TRANSACTION NARRATION` removed "Logging all 2 now" because a bubble
    claiming a write is underway duplicates the indicator and reads as
    stalling. A heads-up says we are checking a source."""
    lowered = line.lower()
    for banned in ("log", "add", "sav", "writ", "track", "enter"):
        assert banned not in lowered, f"{line!r} sounds like a write"


@pytest.mark.parametrize("line", _FOOD_LOOKUP_BUBBLES)
def test_every_line_keeps_the_rules_that_were_right(line):
    lowered = line.lower()
    # RAISED FROM 30 on request (2026-07-31): the clipped fragments read as
    # terse rather than as a coach speaking. Still a ceiling — this is a bubble
    # that appears for a second or two while a lookup runs, and a sentence the
    # user has to read twice defeats the point of reassurance.
    assert len(line) <= 44, f"{line!r} is too long for a heads-up bubble"
    assert line == lowered, "pinned literals stay lowercase; voice lifts them"
    for banned in ("lemme", "real quick", "hang tight", "hang on", "one sec"):
        assert banned not in lowered, f"{line!r} is try-hard casual"


def test_the_food_lane_asks_for_its_own_pool():
    import inspect

    import core.conversation as C
    body = inspect.getsource(C._run_turn)
    assert "FOOD_LOOKUP_HEADS_UP" in body
    assert '"name": "search_food_database"' not in body, (
        "the food lane must not borrow the emergency pool")


# ── the line may not promise a lookup that will not happen ────────────────────
def test_the_neutral_pool_never_claims_a_label():
    """Nine of the twelve original lines asserted a LABEL — "checking the
    label", "reading the label", "checking the brand's numbers". A label exists
    for a packaged product; it does not exist for "harissa chicken", "two eggs"
    or "my usual coffee". For most food the line described a lookup that was
    never going to happen.

    Same defect as `component_estimate` rendering "Estimated from its
    components" with no engine behind it: prose asserting an action nobody
    performed.
    """
    from handlers.tool_executor import _FOOD_LOOKUP_BUBBLES

    for line in _FOOD_LOOKUP_BUBBLES:
        assert "label" not in line.lower(), line
        assert "brand" not in line.lower(), line


def test_a_packaged_product_does_get_the_label_line():
    """...and the branded pool must not become unreachable in the process.

    The first attempt keyed this on `classify_food`, which only returns BRANDED
    when handed a brand or `is_packaged` — from a bare product name it never
    does, so the branded pool was dead code wearing the shape of a fix.
    """
    from handlers.tool_executor import (FOOD_LOOKUP_HEADS_UP,
                                        _FOOD_LOOKUP_BUBBLES_BRANDED,
                                        tool_heads_up)

    line = tool_heads_up(FOOD_LOOKUP_HEADS_UP, "quest chips",
                         subject="Quest Tortilla Style Protein Chips")
    assert line.lower().rstrip(".") in [
        b.lower().rstrip(".") for b in _FOOD_LOOKUP_BUBBLES_BRANDED], line


def test_a_dish_never_gets_the_label_line():
    """The report that started this: rotating strings that do not fit the
    message. A bowl of rice has no label to check."""
    from handlers.tool_executor import FOOD_LOOKUP_HEADS_UP, tool_heads_up

    for food in ("Harissa Chicken", "two eggs", "chicken and rice bowl",
                 "my usual coffee", "leftover soup"):
        line = tool_heads_up(FOOD_LOOKUP_HEADS_UP, f"had {food}", subject=food)
        assert "label" not in line.lower(), f"{food} -> {line}"


def test_the_food_decides_it_even_when_the_message_rambles():
    """`seed` is the whole user message and only ever feeds the hash. Classify
    the sentence instead of the food and "checking the label" lands on a bowl
    of rice."""
    from handlers.tool_executor import FOOD_LOOKUP_HEADS_UP, tool_heads_up

    rambling = "ok so I finally tried that quest chips thing everyone posts about"
    assert "label" not in tool_heads_up(
        FOOD_LOOKUP_HEADS_UP, rambling, subject="Chicken and rice").lower()
