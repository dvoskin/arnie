"""⭐ B-1.8a — A CORRECTION REUSES WHAT ARNIE ALREADY KNEW.

The crucial proof, per the GO ruling: "2 eggs -> 3 eggs" changes the scaling
factor against stored evidence — it never rediscovers USDA, never invokes a
provider. This file proves the primitive is pure arithmetic over the row: no
network, no artifact, no model, and a typed refusal wherever determinism ends.

Driven through the REAL `normalize_quantity` — the standing lesson: synthetic
quantity shapes hid every interesting seam this month.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from core.canonical_repair import (RepairRefused, reprice_quantity)
from skills.nutrition.normalize import normalize_quantity


@dataclass
class _Row:
    """A committed food row, as the primitive sees it."""
    id: int = 1
    calories: float = 180.0
    protein: float = 12.6
    carbs: float = 1.6
    fats: float = 13.2
    fiber: Optional[float] = 0.0
    sugar: Optional[float] = 0.4
    sodium: Optional[float] = 190.0
    micronutrients_json: Optional[str] = None
    # P17f receipt
    scaling_factor: Optional[float] = None
    resolved_grams: Optional[float] = None


def _q(text, food="Egg"):
    return normalize_quantity(text, food)


# ── THE HEADLINE: COUNT CORRECTIONS ─────────────────────────────────────────

def test_two_eggs_to_three_eggs_is_pure_arithmetic(monkeypatch):
    """2 -> 3 of the same thing: every field × 1.5, and NOTHING is fetched —
    the network, the artifact and the resolver are all poisoned."""
    import api.usda as usda
    monkeypatch.setattr(usda, "search_food", _boom)
    monkeypatch.setattr(usda, "food_portions", _boom)
    import skills.nutrition.off as off_mod
    monkeypatch.setattr(off_mod, "_get_json", _boom)
    monkeypatch.setattr("skills.nutrition.pricing_artifact.evidence_for",
                        _boom_sync)

    row = _Row(scaling_factor=0.92, resolved_grams=92.0)
    repaired = reprice_quantity(entry=row, old_quantity=_q("2 eggs"),
                                new_quantity=_q("3 eggs"))

    assert repaired.ratio == pytest.approx(1.5)
    assert repaired.method == "count_ratio"
    assert repaired.changes["calories"] == pytest.approx(270.0)
    assert repaired.changes["protein"] == pytest.approx(18.9)
    assert repaired.changes["sodium"] == pytest.approx(285.0)
    # The receipt moves WITH the correction; the evidence does not change.
    assert repaired.receipt_updates["scaling_factor"] == pytest.approx(1.38)
    assert repaired.receipt_updates["resolved_grams"] == pytest.approx(138.0)


async def _boom(*a, **kw):                                # pragma: no cover
    raise AssertionError("the repair primitive reached a provider")


def _boom_sync(*a, **kw):                                 # pragma: no cover
    raise AssertionError("the repair primitive reached the artifact")


def test_six_oz_to_eight_oz_is_a_grams_ratio():
    """"actually 8 oz": both quantities carry EXACT masses (oz is a
    mass_conversion), so the ratio is their gram ratio — 4/3."""
    row = _Row(calories=304.0, protein=34.0, carbs=0.0, fats=18.0,
               fiber=None, sugar=None, sodium=100.0)
    repaired = reprice_quantity(entry=row,
                                old_quantity=_q("6 oz", "salmon"),
                                new_quantity=_q("8 oz", "salmon"))
    assert repaired.ratio == pytest.approx(8 / 6)
    assert repaired.method == "grams_ratio"
    assert repaired.changes["calories"] == pytest.approx(405.33, abs=0.01)
    assert "fiber" not in repaired.changes, (
        "a field the row never had must not be invented by a repair")


def test_micros_scale_by_the_same_ratio():
    row = _Row(micronutrients_json='{"iron": 2.0, "vitamin_d": 40.0}',
               scaling_factor=None)
    repaired = reprice_quantity(entry=row, old_quantity=_q("2 eggs"),
                                new_quantity=_q("4 eggs"))
    assert repaired.micros == {"iron": 4.0, "vitamin_d": 80.0}


def test_the_receipt_bridge_prices_a_count_corrected_to_grams():
    """"2 eggs -> actually 100 g": cross-dimension, computable ONLY because
    the receipt persisted what mass the count was priced AT. resolved 92 g ->
    ratio 100/92, from evidence already on the row."""
    row = _Row(scaling_factor=0.92, resolved_grams=92.0)
    repaired = reprice_quantity(entry=row, old_quantity=_q("2 eggs"),
                                new_quantity=_q("100 g"))
    assert repaired.method == "receipt_grams_bridge"
    assert repaired.ratio == pytest.approx(100 / 92)
    assert repaired.receipt_updates["resolved_grams"] == pytest.approx(100.0)


# ── THE REFUSALS: DETERMINISM ENDS, ASKING BEGINS ───────────────────────────

def test_a_count_of_a_different_thing_is_refused():
    """"2 bars -> 3 bottles" shares no unit; a count may only correct a count
    of the same thing — the ONE unit matcher decides, not a new one."""
    with pytest.raises(RepairRefused):
        reprice_quantity(entry=_Row(),
                         old_quantity=_q("2 bars", "protein bar"),
                         new_quantity=_q("3 bottles", "protein bar"))


def test_cross_dimension_without_a_receipt_is_refused():
    """The pre-P17f population: no receipt, so "2 eggs -> 100 g" has no
    deterministic bridge. Typed refusal — the caller asks, never guesses."""
    with pytest.raises(RepairRefused) as excinfo:
        reprice_quantity(entry=_Row(resolved_grams=None),
                         old_quantity=_q("2 eggs"),
                         new_quantity=_q("100 g"))
    assert "resolved_grams" in str(excinfo.value)


def test_a_heuristic_mass_on_the_correction_does_not_participate():
    """⛔ P17c.2's precedence applies to corrections identically. "2 eggs" and
    "3 eggs" BOTH carry heuristic piece-weight grams — if those participated,
    this would be a grams_ratio of two guesses. It must be the COUNT ratio."""
    repaired = reprice_quantity(entry=_Row(), old_quantity=_q("2 eggs"),
                                new_quantity=_q("3 eggs"))
    assert repaired.method == "count_ratio", (
        "heuristic normalized masses outranked the exact count ratio")


def test_grams_to_count_has_no_bridge_and_says_so():
    with pytest.raises(RepairRefused):
        reprice_quantity(entry=_Row(resolved_grams=170.0),
                         old_quantity=_q("6 oz", "salmon"),
                         new_quantity=_q("2 fillets", "salmon"))


def test_unreadable_micros_are_left_alone_not_corrupted():
    row = _Row(micronutrients_json="{not json")
    repaired = reprice_quantity(entry=row, old_quantity=_q("2 eggs"),
                                new_quantity=_q("3 eggs"))
    assert repaired.micros is None
    assert repaired.changes["calories"] == pytest.approx(270.0)


# ── ANTI-COMPOUNDING: A TWICE-CORRECTED MEAL PRICES FROM ITS OWN HISTORY ────

def test_two_corrections_compose_exactly():
    """2 -> 3 -> 4 eggs must equal 2 -> 4 directly: the receipt's factor moves
    with each correction, so repair N+1 reprices from repair N's state and the
    numbers never drift."""
    row = _Row(scaling_factor=0.92, resolved_grams=92.0)
    first = reprice_quantity(entry=row, old_quantity=_q("2 eggs"),
                             new_quantity=_q("3 eggs"))
    after_first = _Row(
        calories=first.changes["calories"], protein=first.changes["protein"],
        carbs=first.changes["carbs"], fats=first.changes["fats"],
        fiber=first.changes.get("fiber"), sugar=first.changes.get("sugar"),
        sodium=first.changes.get("sodium"),
        scaling_factor=first.receipt_updates["scaling_factor"],
        resolved_grams=first.receipt_updates["resolved_grams"])
    second = reprice_quantity(entry=after_first, old_quantity=_q("3 eggs"),
                              new_quantity=_q("4 eggs"))
    direct = reprice_quantity(entry=row, old_quantity=_q("2 eggs"),
                              new_quantity=_q("4 eggs"))
    assert second.changes["calories"] == pytest.approx(
        direct.changes["calories"], abs=0.01)
    assert after_first.scaling_factor * second.ratio == pytest.approx(
        direct.receipt_updates["scaling_factor"], abs=1e-6)
