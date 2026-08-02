"""Individualized slow-food-log heads-up (Danny 0802).

The wait bubble used to be a generic pool line ("working this one out properly.").
Now it names the extracted food and reassures on accuracy ("let me pull the real
calories on that skirt steak so it's exactly right."), with ~18 generic / 10
branded variations so a run of logs never reads the same twice.

Rules it inherits from test_the_food_heads_up_is_not_an_emergency: describes a
LOOKUP not a write, lowercase-lead (voice lifts on output), no em dash. New here:
it must actually name the food and never leak the {food} placeholder.
"""
import pytest

from core.conversation import _food_heads_up_subject
from handlers.tool_executor import (FOOD_LOOKUP_HEADS_UP, _FOOD_LOOKUP_TEMPLATES,
                                    _FOOD_LOOKUP_TEMPLATES_BRANDED, tool_heads_up)

_BANNED_WRITE = ("log", "add", "sav", "writ", "track", "enter")


@pytest.mark.parametrize("line", _FOOD_LOOKUP_TEMPLATES + _FOOD_LOOKUP_TEMPLATES_BRANDED)
def test_template_names_food_describes_a_lookup_never_a_write(line):
    lowered = line.lower()
    assert "{food}" in line, "a template must name the food"
    for banned in _BANNED_WRITE:
        assert banned not in lowered, f"{line!r} sounds like a write"
    assert line == lowered, "pinned literals stay lowercase; voice lifts them"
    assert "—" not in line, "no em dash in voice"
    words = len(line.replace("{food}", "food").split())
    assert 9 <= words <= 16, f"{line!r} is {words} words (target 10-15)"


def test_generic_food_is_named_and_placeholder_never_leaks():
    line = tool_heads_up(FOOD_LOOKUP_HEADS_UP, "i had a skirt steak",
                         subject="skirt steak")
    assert "skirt steak" in line.lower()
    assert "{food}" not in line
    assert "—" not in line
    assert "label" not in line.lower()   # a dish has no label


def test_branded_food_keeps_its_case_and_gets_label_wording():
    line = tool_heads_up(FOOD_LOOKUP_HEADS_UP, "had a barebells",
                         subject="Barebells bar")
    assert "Barebells" in line          # brand case preserved, not lowercased
    assert "label" in line.lower()
    assert "{food}" not in line


def test_no_subject_uses_the_neutral_pool_without_a_placeholder():
    line = tool_heads_up(FOOD_LOOKUP_HEADS_UP, "eggs toast bacon", subject=None)
    assert "{food}" not in line
    assert line.strip()


def test_an_overlong_name_falls_back_rather_than_reading_as_a_paragraph():
    huge = "my enormous leftover thanksgiving plate with everything piled on it"
    line = tool_heads_up(FOOD_LOOKUP_HEADS_UP, "had leftovers", subject=huge)
    assert "{food}" not in line
    assert huge not in line              # too long to name; neutral pool instead


def test_subject_builder_one_two_and_many():
    def tc(name):
        return {"name": "log_food", "input": {"food_name": name}}
    assert _food_heads_up_subject([tc("skirt steak")]) == "skirt steak"
    assert _food_heads_up_subject([tc("chicken"), tc("rice")]) == "chicken and rice"
    # three or more -> None (the neutral pool, not a clumsy list)
    assert _food_heads_up_subject([tc("eggs"), tc("toast"), tc("bacon")]) is None
    # non-food tool calls are ignored
    assert _food_heads_up_subject([{"name": "store_attribute", "input": {}}]) is None


def test_a_run_of_foods_varies():
    foods = ["skirt steak", "greek yogurt", "birria tacos", "cottage cheese",
             "oatmeal", "poke bowl", "chicken thigh", "ribeye"]
    lines = {tool_heads_up(FOOD_LOOKUP_HEADS_UP, f"had {f}", subject=f) for f in foods}
    assert len(lines) >= 5, lines
