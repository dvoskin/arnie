"""
Guard the wire that makes the dashboard food-accuracy slider change Arnie's
behavior: food_mode_directive() renders the per-turn [FOOD LOGGING MODE] override
that build_context injects into the system context. Moderate (default) injects
nothing — the static FOOD_ACCURACY block is the baseline; quick/strict override it.
"""
import pytest
from core.context_builder import food_mode_directive


def test_moderate_injects_nothing():
    assert food_mode_directive("moderate") == ""


@pytest.mark.parametrize("mode", [None, "", "unknown", "balanced"])
def test_unknown_or_missing_defaults_to_moderate(mode):
    assert food_mode_directive(mode) == ""


def test_quick_overrides_threshold_downward():
    d = food_mode_directive("quick")
    assert d.startswith("[FOOD LOGGING MODE: quick]")
    assert "best estimate" in d
    assert ">300 cal" in d  # explicitly relaxes the static >120 cal rule


def test_strict_overrides_threshold_upward():
    d = food_mode_directive("strict")
    assert d.startswith("[FOOD LOGGING MODE: strict]")
    assert "cook method" in d.lower()
    assert "under 120 cal" in d  # tightens below the static threshold


def test_case_insensitive():
    assert food_mode_directive("QUICK").startswith("[FOOD LOGGING MODE: quick]")
    assert food_mode_directive("  Strict ").startswith("[FOOD LOGGING MODE: strict]")
