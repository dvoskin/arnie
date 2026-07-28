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
    assert len(line) <= 30, f"{line!r} is too long for a heads-up bubble"
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
