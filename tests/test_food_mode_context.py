"""
Guard the wire that makes the dashboard food-accuracy slider change Arnie's
behavior: food_mode_directive() renders the per-turn [FOOD LOGGING MODE]
override that build_context injects into the system context.

ONE POSTURE, THREE APPETITES (2026-07-27). Every mode now clarifies BEFORE the
write — nothing commits on a guess when a question would have settled it. What
the mode changes is the BAR for "worth asking about", so stricter is more
insistent rather than differently shaped.

The three postures used to disagree about the SHAPE, and the losing behaviour
was always that the write got held: measured on a clean-room food set with
production config and live USDA, strict logged 4 of 10 plainly-stated foods
where quick logged 10 of 10. That spread was produced by wording, not by any
deliberate accuracy trade.
"""
import pytest

from core.context_builder import food_mode_directive
from skills.nutrition.materiality import (day_fraction_for,
                                          min_item_share_for)

MODES = ("quick", "moderate", "strict")


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_clarifies_before_the_write(mode):
    d = food_mode_directive(mode)
    assert d.startswith("[FOOD LOGGING MODE]")
    assert "Clarify BEFORE the write" in d
    assert "hold the log until they answer" in d


@pytest.mark.parametrize("mode", MODES)
def test_an_ambiguity_is_what_they_did_not_say(mode):
    """The half that makes clarify-first survivable in every mode.

    Without it the directive manufactured doubt about details the user had
    already stated — "was the sweet potato plain, or did you add butter?" — and
    a tablespoon of butter is 102 cal, so on a 100 cal bar EVERY food had a
    qualifying hypothetical swing. "Ask when it clears the threshold" therefore
    degenerated to "always ask", and the adjacent "clearly-stated items log
    DIRECTLY" could never win against it.
    """
    d = food_mode_directive(mode)
    assert "did not mention butter" in d
    assert "COMPLETE description" in d
    assert "IF THEY ALREADY GAVE YOU THE VARIABLE, LOG" in d


def test_the_bar_is_proportional_not_a_calorie_floor():
    """`materiality` already retired the flat threshold and says why: "This is
    what the old flat 50-calorie floor was reaching for and could not express,
    because it tested the SPAN."

    A raw calorie number cannot scale — 80 calories is trivia on a slice of
    pizza and the whole story on a drizzle of oil — so the directive must quote
    the PROPORTIONS the engine actually gates on, not ASK_THRESHOLDS.
    """
    for mode in MODES:
        d = food_mode_directive(mode)
        assert "clears ~" not in d, f"{mode} reinstated a flat calorie floor"
        assert "PROPORTIONS, NEVER A CALORIE COUNT" in d
        assert "DAY'S TARGET" in d


def test_the_bar_falls_as_the_mode_tightens():
    """The ONLY thing a mode buys, on every gate at once. Values come from
    materiality's swept tables rather than a copy that can drift."""
    day = [day_fraction_for(m) for m in MODES]
    item = [min_item_share_for(m) for m in MODES]
    assert day == [0.02, 0.01, 0.005]
    assert item == [0.035, 0.02, 0.01]
    assert day[0] > day[1] > day[2], "stricter must ask about more"
    assert item[0] > item[1] > item[2]

    # ...and the rendered prose carries those same numbers.
    for mode, d_frac, i_frac in zip(MODES, day, item):
        d = food_mode_directive(mode)
        assert f"~{d_frac:.1%} of their DAY'S TARGET" in d, mode
        assert f"~{i_frac:.1%} of their day" in d, mode


def test_quicks_item_gate_is_rendered_as_off_not_as_101_percent():
    """MATERIAL_FRACTIONS['quick'] is 1.01 — deliberately >1.0, materiality's
    way of switching the item gate off. Rendered naively that becomes "is the
    doubt at least ~101% of THAT FOOD?", an impossible test."""
    assert "101%" not in food_mode_directive("quick")
    assert "does not gate you here" in food_mode_directive("quick")
    assert "~30% of THAT FOOD" in food_mode_directive("moderate")
    assert "~15% of THAT FOOD" in food_mode_directive("strict")


def test_stricter_reads_as_more_insistent():
    assert "Only the biggest swings" in food_mode_directive("quick")
    assert "Be thorough" in food_mode_directive("strict")


@pytest.mark.parametrize("mode", [None, "", "unknown", "balanced"])
def test_unknown_or_missing_falls_back_to_moderate(mode):
    assert food_mode_directive(mode) == food_mode_directive("moderate")


def test_case_and_whitespace_are_tolerated():
    assert food_mode_directive("QUICK") == food_mode_directive("quick")
    assert food_mode_directive("  Strict ") == food_mode_directive("strict")


def test_the_per_mode_prose_is_reverted_by_a_flag_not_deleted():
    """FOOD_ONE_PATH=false restores the three original postures without a
    deploy. They are a product decision to revisit, not a mistake to erase, so
    the prose stays covered rather than rotting behind a dead branch."""
    import importlib
    import os

    import core.context_builder as cb

    prior = os.environ.get("FOOD_ONE_PATH")
    os.environ["FOOD_ONE_PATH"] = "false"
    try:
        importlib.reload(cb)
        assert cb.food_mode_directive("moderate") == ""     # the old default
        quick = cb.food_mode_directive("quick")
        strict = cb.food_mode_directive("strict")
        assert quick.startswith("[FOOD LOGGING MODE: quick]")
        assert strict.startswith("[FOOD LOGGING MODE: strict]")
        assert "LOG EVERY item FIRST" not in strict   # the inversion stays gone
    finally:
        if prior is None:
            os.environ.pop("FOOD_ONE_PATH", None)
        else:
            os.environ["FOOD_ONE_PATH"] = prior
        importlib.reload(cb)


def test_strict_mode_does_not_overclarify_plain_generics():
    """Strict mode must NOT interrogate low-variance plain items (black coffee,
    plain tea, toast) — the user complaint was over-clarification on these. The
    'never ask' carve-out distinguishes a plain coffee from a milk drink."""
    from core.prompts import build_arnie_system
    s = build_arnie_system(platform="telegram")
    assert "plain/black coffee" in s
    assert "NOT a milk drink" in s          # plain coffee != latte
    assert "plain toast" in s
    # raw whole fruit is a known low-variance food → never interrogate
    assert "raw whole fruit" in s and "banana" in s
    # The lists are anchored to a single principle, not ad-hoc — and that
    # principle is now DERIVED. "50%+" was hardcoded in three places while
    # MATERIAL_FRACTIONS is 0.3 moderate / 0.15 strict, so the prompt was 1.7x
    # stricter than the engine on moderate and 3.3x on strict: the model
    # declined to ask about spans the policy would have held the write for.
    from skills.nutrition.materiality import fraction_for
    assert "50%+" not in s
    assert f"{fraction_for('moderate'):.0%}+" in s
    assert f"{fraction_for('strict'):.0%}+" in s
