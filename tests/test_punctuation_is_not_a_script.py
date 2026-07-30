"""Smart punctuation must not admit a message to the food lane.

`_non_latin` exists so a Russian meal report is never turned away by English
shape rules. Its bare `ord(c) > 0x2FF` test also matched the iOS smart
apostrophe (U+2019), em-dashes, ellipses and emoji — which iOS keyboards put
in most messages. Production, 07-30 window (`legacy_reason=interpreter_none`,
`owner=gate_regex`): "Mark my Flat DB complete coach 💪", "7 couldn't do more"
and "Call the tool mate don't forget" were each admitted to the food lane on
their punctuation alone, paid a 5–8 s interpreter call, and fell to legacy —
which had been the right destination from the start.

The rule is now LETTERS in a non-Latin script, which is what the docstring
always meant.
"""
import pytest

from core.food_turn import _non_latin, applies


# ── punctuation and emoji are not a script ────────────────────────────────────
@pytest.mark.parametrize("text", [
    "7 couldn’t do more",                    # iOS smart apostrophe
    "Call the tool mate don’t forget",
    "Mark my Flat DB complete coach \U0001F4AA",  # emoji only
    "em—dash here",                          # em-dash
    "ellipsis…",
    "“quoted”",                         # curly double quotes
    "plain ascii",
])
def test_punctuation_and_emoji_are_not_a_script(text):
    assert _non_latin(text) is False, text


# ── real non-Latin letters still are ──────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Рагу из картофеля",          # Cyrillic — the case the check exists for
    "ккал 200",
    "съел борщ",
    "食べた",                      # CJK
    "אכלתי עוף",                  # Hebrew
])
def test_non_latin_letters_still_route_past_the_shape_rules(text):
    assert _non_latin(text) is True, text


# ── the production messages no longer pass the gate on punctuation ────────────
@pytest.mark.parametrize("text", [
    "Mark my Flat DB complete coach \U0001F4AA",
    "7 couldn’t do more",
    "Call the tool mate don’t forget",
])
def test_the_wasted_workout_turns_are_no_longer_admitted(text):
    """These carried no food shape at all — only smart punctuation got them
    through `applies()`. With the model gate on they may still be admitted by
    Haiku's judgment; what this asserts is that PUNCTUATION alone no longer
    decides."""
    assert applies(text) is False, text


def test_a_russian_food_report_is_still_admitted():
    assert applies("съел борщ и котлеты") is True


def test_a_smart_quote_inside_a_real_food_message_still_admits_on_shape():
    """The fix must not turn away food: "I've had 2 eggs" carries a consumed
    shape and passes on that, apostrophe style regardless."""
    assert applies("I’ve had 2 eggs and rice") is True
    assert applies("I've had 2 eggs and rice") is True
