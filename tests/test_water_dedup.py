"""Unit tests for the server-side water dedup guard (Phase 1.3).

Mirror of test_food_dedup.py / test_exercise_dedup.py. Speculative bug —
no demonstrated production case yet — but the failure mode is identical
to food/exercise and the cost of the guard is one helper function.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from skills.nutrition.water_dedup import (
    is_duplicate_water, format_dedup_result,
)


def _w(id_=1, ml=500, context="random", ts=None):
    return SimpleNamespace(
        id=id_,
        amount_ml=ml,
        context=context,
        timestamp=ts or datetime(2026, 6, 12, 10, 0, 0),
    )


# ── positive ────────────────────────────────────────────────────────────────

def test_exact_payload_within_60_min_is_dup():
    now = datetime(2026, 6, 12, 10, 30, 0)
    prior = _w(id_=10, ml=500, ts=datetime(2026, 6, 12, 10, 0, 0))
    dup = is_duplicate_water(
        amount_ml=500, context="random",
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior


def test_30ml_tolerance_matches():
    """16oz → 473.18ml vs 473ml: rounding can't break dedup."""
    now = datetime(2026, 6, 12, 10, 30, 0)
    prior = _w(ml=473.18, ts=datetime(2026, 6, 12, 10, 0, 0))
    dup = is_duplicate_water(
        amount_ml=500, context="random",
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior


def test_none_context_treated_as_random():
    """log_water without context = random bucket. A prior random log
    matches even if the incoming call has no context field set."""
    now = datetime(2026, 6, 12, 10, 30, 0)
    prior = _w(context="random", ts=datetime(2026, 6, 12, 10, 0, 0))
    dup = is_duplicate_water(
        amount_ml=500, context=None,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior


# ── negative ────────────────────────────────────────────────────────────────

def test_outside_60_min_window_not_dup():
    """61 min apart — real second drink, both should log."""
    now = datetime(2026, 6, 12, 11, 1, 0)
    prior = _w(ts=datetime(2026, 6, 12, 10, 0, 0))
    dup = is_duplicate_water(
        amount_ml=500, context="random",
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_different_amount_not_dup():
    now = datetime(2026, 6, 12, 10, 30, 0)
    prior = _w(ml=500, ts=datetime(2026, 6, 12, 10, 15, 0))
    dup = is_duplicate_water(
        amount_ml=250, context="random",
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_different_context_not_dup():
    """Morning glass + post-workout glass at the same size = two real
    drinks at different times of day, both should log."""
    now = datetime(2026, 6, 12, 10, 30, 0)
    prior = _w(ml=500, context="morning", ts=datetime(2026, 6, 12, 10, 0, 0))
    dup = is_duplicate_water(
        amount_ml=500, context="post_workout",
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_empty_existing_returns_none():
    assert is_duplicate_water(
        amount_ml=500, context="random",
        existing_entries=[], now_utc=datetime(2026, 6, 12, 12, 0, 0),
    ) is None


def test_none_amount_returns_none():
    """Defensive — malformed tool call without amount."""
    now = datetime(2026, 6, 12, 12, 0, 0)
    prior = _w(ts=now - timedelta(seconds=10))
    assert is_duplicate_water(
        amount_ml=None, context="random",
        existing_entries=[prior], now_utc=now,
    ) is None


# ── format ─────────────────────────────────────────────────────────────────

def test_format_dedup_result_prefix_and_age():
    now = datetime(2026, 6, 12, 10, 30, 0)
    dup = _w(id_=42, ml=500, ts=datetime(2026, 6, 12, 10, 0, 0))
    msg = format_dedup_result(dup, now_utc=now)
    assert msg.startswith("Already on the board:")
    assert "500ml" in msg
    # Bare "#id", not the bracketed "[#id]" marker that leaked.
    assert "#42" in msg
    assert "[#42]" not in msg
    assert "30 min ago" in msg
    # DATA ONLY — no model-facing directives, no leak tokens.
    for leak in ("YOUR REPLY", "do NOT", "do not", "never tell", "dedup guard",
                 "force it through", "[TODAY]", "[#"):
        assert leak not in msg, f"leak token in dedup result: {leak!r}"
