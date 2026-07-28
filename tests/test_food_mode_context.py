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


def test_every_mode_injects_nothing_under_one_path():
    """ONE PATH (2026-07-27). Three postures meant three sets of prose
    competing to decide one thing, and the losing behaviour was always the
    same: the write got held. Measured on a clean-room set with production
    config, strict logged 4 of 10 plainly-stated foods against quick's 10 of
    10 — a spread produced by wording, not by any deliberate accuracy trade.

    All three now fall through to the static FOOD_ACCURACY block, which IS the
    moderate policy: log when reasonably interpretable, clarify NON-BLOCKINGLY
    after the write, never re-ask what they already said."""
    for mode in ("quick", "moderate", "strict", "QUICK", "  Strict "):
        assert food_mode_directive(mode) == "", mode


def test_the_per_mode_prose_is_reverted_by_a_flag_not_deleted():
    """FOOD_ONE_PATH=false restores the three postures without a deploy. They
    are a product decision to revisit, not a mistake to erase — so the prose
    stays covered rather than rotting behind a dead branch."""
    import importlib
    import os

    import core.context_builder as cb
    from core.food_ledger import ASK_THRESHOLDS

    prior = os.environ.get("FOOD_ONE_PATH")
    os.environ["FOOD_ONE_PATH"] = "false"
    try:
        importlib.reload(cb)
        quick = cb.food_mode_directive("quick")
        strict = cb.food_mode_directive("strict")

        assert quick.startswith("[FOOD LOGGING MODE: quick]")
        assert "best estimate" in quick
        assert f">{ASK_THRESHOLDS['quick']} cal" in quick

        assert strict.startswith("[FOOD LOGGING MODE: strict]")
        assert "BEFORE the write" in strict
        assert "hold the log" in strict
        assert "LOG EVERY item FIRST" not in strict   # the inversion stays gone

        # And the fix that stopped strict interrogating plainly-stated food:
        # an ambiguity is what they did NOT say, never what could been added.
        assert "did not mention butter" in strict
        assert "COMPLETE description" in strict

        # Case handling still belongs to the per-mode path.
        assert cb.food_mode_directive("QUICK").startswith(
            "[FOOD LOGGING MODE: quick]")
        assert cb.food_mode_directive("  Strict ").startswith(
            "[FOOD LOGGING MODE: strict]")
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
    # the lists are anchored to a single principle, not ad-hoc
    assert "50%+" in s
