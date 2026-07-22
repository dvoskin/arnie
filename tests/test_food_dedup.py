"""Unit tests for the server-side food dedup guard (Phase 1.2).

Pins the behavior that prevents the re-log-on-context-shift bug Danny hit
on 2026-06-12 (chicken+rice logged twice, 58 minutes apart, while the
user was asking about Apple Health). The dedup helper is a pure function
— these tests are fast and isolated, no DB.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from skills.nutrition.food_dedup import (
    is_duplicate_food,
    normalize_food_name,
    normalize_quantity,
    format_dedup_result,
)


def _entry(id_=1, name="Grilled shredded chicken breast", qty="150g",
           calories=205.0, ts=None):
    return SimpleNamespace(
        id=id_,
        parsed_food_name=name,
        quantity=qty,
        calories=calories,
        timestamp=ts or datetime(2026, 6, 12, 1, 1, 38),
    )


# ── normalization ────────────────────────────────────────────────────────────

def test_normalize_collapses_whitespace_and_case():
    assert normalize_food_name("Grilled shredded chicken breast") == (
        "grilled shredded chicken breast"
    )
    assert normalize_food_name("  CHICKEN   BREAST  ") == "chicken breast"


def test_normalize_handles_none_and_empty():
    assert normalize_food_name(None) == ""
    assert normalize_food_name("") == ""


def test_normalize_quantity_collapses_and_lowercases():
    assert normalize_quantity("150g") == "150g"
    assert normalize_quantity("1 Cup") == "1 cup"
    assert normalize_quantity("  150 g  ") == "150 g"
    assert normalize_quantity(None) == ""


# ── is_duplicate_food: the Danny case ────────────────────────────────────────

def test_dannys_chicken_rice_relog_caught():
    """The exact bug: chicken logged at 01:01, model re-fires at 01:59
    while answering Apple Health question. 58 min < 90 min window."""
    bug_now = datetime(2026, 6, 12, 1, 59, 45)
    prior_chicken = _entry(
        id_=593, name="Grilled shredded chicken breast",
        qty="150g", calories=205.0,
        ts=datetime(2026, 6, 12, 1, 1, 38),
    )
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=205.0,
        existing_entries=[prior_chicken],
        now_utc=bug_now,
    )
    assert dup is prior_chicken
    assert dup.id == 593


def test_dannys_rice_relog_caught_too():
    """Same scenario, rice side."""
    bug_now = datetime(2026, 6, 12, 1, 59, 45)
    prior_rice = _entry(
        id_=594, name="White rice (plain, steamed)",
        qty="100g", calories=130.0,
        ts=datetime(2026, 6, 12, 1, 1, 38),
    )
    dup = is_duplicate_food(
        food_name="White rice (plain, steamed)",
        quantity="100g",
        calories=130.0,
        existing_entries=[prior_rice],
        now_utc=bug_now,
    )
    assert dup is prior_rice


# ── is_duplicate_food: window edges ──────────────────────────────────────────

def test_just_inside_90_minute_window():
    """89 min apart — should still flag."""
    now = datetime(2026, 6, 12, 2, 30, 0)
    prior = _entry(ts=datetime(2026, 6, 12, 1, 1, 0))  # 89 min ago
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=205.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is prior


def test_just_outside_90_minute_window():
    """91 min apart — NOT a dup, treat as a legit second meal."""
    now = datetime(2026, 6, 12, 2, 32, 0)
    prior = _entry(ts=datetime(2026, 6, 12, 1, 1, 0))  # 91 min ago
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=205.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is None


def test_3_hours_apart_not_dup():
    """Real second portion of the same thing at a later meal. Lunch
    chicken and dinner chicken should both log."""
    now = datetime(2026, 6, 12, 18, 0, 0)
    prior = _entry(ts=datetime(2026, 6, 12, 13, 0, 0))  # 5 hours ago
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=205.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is None


# ── is_duplicate_food: match-key sensitivity ─────────────────────────────────

def test_different_quantity_not_dup():
    """User had 150g for lunch, 200g for dinner. Different quantities,
    both should log."""
    now = datetime(2026, 6, 12, 2, 0, 0)
    prior = _entry(qty="150g", ts=datetime(2026, 6, 12, 1, 0, 0))
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="200g",
        calories=275.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is None


def test_quantity_phrasing_drift_same_calories_is_dup():
    """The Deny 2026-07-22 gap: same food logged twice ~4 min apart with the
    quantity phrased differently each turn ("Творог 200г" then just "творог").
    Calories agree (portion is the same), so the exact-quantity-string mismatch
    must NOT let the second copy through."""
    now = datetime(2026, 7, 22, 10, 4, 0)
    prior = _entry(name="творог", qty="200 г", calories=248.0,
                   ts=datetime(2026, 7, 22, 10, 0, 0))  # 4 min ago
    dup = is_duplicate_food(
        food_name="творог",
        quantity="порция",          # different STRING, same portion
        calories=250.0,             # within 15% of 248
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is prior


def test_quantity_drift_without_calories_still_requires_exact_qty():
    """Conservative guard: when a calorie is missing we can't confirm the portion
    from calories, so a different quantity string must NOT match (otherwise a
    genuinely different portion logged before enrichment would be swallowed)."""
    now = datetime(2026, 7, 22, 10, 4, 0)
    prior = _entry(name="творог", qty="200 г", calories=248.0,
                   ts=datetime(2026, 7, 22, 10, 0, 0))
    dup = is_duplicate_food(
        food_name="творог",
        quantity="порция",
        calories=None,              # not yet enriched — portion unconfirmed
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is None


def test_different_name_not_dup():
    now = datetime(2026, 6, 12, 2, 0, 0)
    prior = _entry(name="Chicken thigh", ts=datetime(2026, 6, 12, 1, 0, 0))
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=205.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is None


def test_calorie_variance_within_15pct_still_matches():
    """USDA enrichment variance: same 150g chicken might land at 205 or
    230 cal across lookup branches. ±15% tolerance absorbs this."""
    now = datetime(2026, 6, 12, 2, 0, 0)
    prior = _entry(calories=205.0, ts=datetime(2026, 6, 12, 1, 0, 0))
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=230.0,  # +12% — within tolerance
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is prior


def test_calorie_variance_beyond_tolerance_not_dup():
    """A 30% calorie swing is large enough that it might be a different
    portion or a different meal entirely. Don't false-positive."""
    now = datetime(2026, 6, 12, 2, 0, 0)
    prior = _entry(calories=205.0, ts=datetime(2026, 6, 12, 1, 0, 0))
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=350.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is None


def test_calories_none_on_either_side_still_matches():
    """Some calls come in before _analyze_food has computed calories.
    Don't refuse the dup just because the macro lookup hasn't run."""
    now = datetime(2026, 6, 12, 2, 0, 0)
    prior = _entry(calories=None, ts=datetime(2026, 6, 12, 1, 0, 0))
    dup = is_duplicate_food(
        food_name="Grilled shredded chicken breast",
        quantity="150g",
        calories=205.0,
        existing_entries=[prior],
        now_utc=now,
    )
    assert dup is prior


# ── is_duplicate_food: empty / edge ──────────────────────────────────────────

def test_empty_existing_returns_none():
    assert is_duplicate_food(
        food_name="Chicken", quantity="150g", calories=205.0,
        existing_entries=[],
        now_utc=datetime(2026, 6, 12, 12, 0, 0),
    ) is None


def test_empty_food_name_returns_none():
    """Defensive — malformed tool call without food_name."""
    now = datetime(2026, 6, 12, 12, 0, 0)
    prior = _entry(ts=now - timedelta(seconds=10))
    assert is_duplicate_food(
        food_name="", quantity="150g", calories=205.0,
        existing_entries=[prior], now_utc=now,
    ) is None


# ── format_dedup_result ──────────────────────────────────────────────────────

def test_format_dedup_result_starts_with_already_on_the_board():
    now = datetime(2026, 6, 12, 1, 59, 45)
    dup = _entry(
        id_=593, name="Grilled shredded chicken breast",
        qty="150g", calories=205.0,
        ts=datetime(2026, 6, 12, 1, 1, 38),
    )
    msg = format_dedup_result(dup, now_utc=now)
    assert msg.startswith("Already on the board:")
    assert "Grilled shredded chicken breast" in msg
    assert "150g" in msg
    assert "205 cal" in msg
    # Entry id is carried as a bare "#id" (NOT the bracketed "[#id]" marker that
    # leaked to users) — so the model can reference the row without echoing an
    # internal-looking token.
    assert "#593" in msg
    assert "[#593]" not in msg
    assert "58 min ago" in msg
    # DATA ONLY — the string must carry NO model-facing directives (those moved
    # into the system prompt). None of the leak tokens Danny saw may appear.
    for leak in ("YOUR REPLY", "do NOT", "do not", "never tell", "dedup guard",
                 "force it through", "[TODAY]", "[#"):
        assert leak not in msg, f"leak token in dedup result: {leak!r}"
