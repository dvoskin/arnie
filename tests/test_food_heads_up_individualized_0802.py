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

#: COMPLETED write forms, not the verb. The rule this enforces is that a
#: heads-up must never claim the row is already down — that duplicates the
#: commit indicator and reads as a stall. It was written as a substring ban on
#: "log"/"add"/"sav", which cannot tell "logged that" (a false claim) from "so
#: I log this accurately" (a reason for the pause, and the exact wording Danny
#: asked for on 2026-08-04). Narrowed to the completed forms, which is what the
#: rule was always about.
_BANNED_WRITE = ("logged", "logging", "added", "adding", "saved", "saving",
                 "written", "writing", "tracked", "tracking", "entered")


@pytest.mark.parametrize("line", _FOOD_LOOKUP_TEMPLATES + _FOOD_LOOKUP_TEMPLATES_BRANDED)
def test_template_names_food_describes_a_lookup_never_a_write(line):
    lowered = line.lower()
    assert "{food}" in line, "a template must name the food"
    for banned in _BANNED_WRITE:
        assert banned not in lowered, f"{line!r} sounds like a write"
    assert line == lowered, "pinned literals stay lowercase; voice lifts them"
    assert "—" not in line, "no em dash in voice"
    words = len(line.replace("{food}", "food").split())
    # SHORTER (Danny, 2026-08-04). The 10-15 target produced lines that read as
    # the opening of the final reply rather than as cover for a pause —
    # "verifying the numbers on that chicken so what you see is right" is
    # procedural, and on a live screenshot it blended straight into the
    # clarification underneath it. The brief is now one short sentence; the
    # preferred wording is eight words. Still a floor, because a two-word
    # fragment reads as terse rather than as a coach speaking.
    assert 4 <= words <= 11, f"{line!r} is {words} words (target 5-10)"


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
