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
    # thresholds come from the ONE dial both lanes share (P0 fix 2026-07-24)
    from core.food_ledger import ASK_THRESHOLDS
    assert f">{ASK_THRESHOLDS['quick']} cal" in d


def test_strict_overrides_threshold_upward():
    """Repinned 2026-07-24: strict now mirrors the structured lane's contract
    — clarify BEFORE the write, never log-first-ask-later (the two lanes said
    opposite things; that inversion was the P0 policy-duplication fix)."""
    d = food_mode_directive("strict")
    assert d.startswith("[FOOD LOGGING MODE: strict]")
    assert "cook method" in d.lower()
    assert "BEFORE the write" in d
    assert "hold the log" in d
    assert "LOG EVERY item FIRST" not in d      # the inverted directive is gone
    from core.food_ledger import ASK_THRESHOLDS
    assert f"{ASK_THRESHOLDS['strict']}+" in d


def test_case_insensitive():
    assert food_mode_directive("QUICK").startswith("[FOOD LOGGING MODE: quick]")
    assert food_mode_directive("  Strict ").startswith("[FOOD LOGGING MODE: strict]")


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
