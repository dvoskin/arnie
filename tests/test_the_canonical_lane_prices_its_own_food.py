"""THE CANONICAL PRICER'S CONTRACT — written before the rungs that satisfy it.

Measured in production 2026-08-07/08, and every gate here is one of those
numbers turned into a rule:

    settle.commit    (canonical)        17 ms
    pricing.ranking  (deterministic)     0 ms
    settle.pricing   (legacy)        8,171 ms of an 8,225 ms tap
    entry 2932       Mackerel 80 g committed at 0.0 kcal / 0 g protein
    entry 2820       Black coffee at 0.0 kcal — CORRECT, and must stay loggable
    "Chicken, fried" 120 g priced 295 kcal, then 329 kcal, same identity

Gates 3 and 4 are RED until `settle` stops importing the legacy pricer. That
is deliberate: they are the definition of done, not a description of today.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from core.canonical_pricing import (EVIDENCE_BACKED, PricedFood,
                                    PricingRefused, Rung, refuse_or_return)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _priced(**kw) -> PricedFood:
    base = dict(calories=165.0, protein=31.0, carbs=0.0, fats=3.6,
                rung=Rung.ARTIFACT, evidence_id="usda:171077")
    base.update(kw)
    return PricedFood(**base)


# ── GATE 2: MISS != ZERO ────────────────────────────────────────────────────

def test_a_zero_from_a_failed_estimate_is_refused():
    """ENTRY 2932, AS A RULE. Mackerel is not a zero-calorie food; that row is
    a silent under-count of someone's day, and nothing about it looked wrong.
    """
    with pytest.raises(PricingRefused):
        refuse_or_return(
            _priced(calories=0.0, protein=0.0, carbs=0.0, fats=0.0,
                    rung=Rung.ESTIMATE, evidence_id=""),
            food_name="Mackerel")


@pytest.mark.parametrize("rung", sorted(EVIDENCE_BACKED, key=lambda r: r.value))
def test_a_zero_from_evidence_is_a_fact_and_is_allowed(rung):
    """ENTRY 2820. Black coffee really is ~0 kcal, and the canonical lane must
    keep being able to log it. The distinction is never the FOOD — it is
    whether the number came from evidence or from a failure."""
    priced = refuse_or_return(
        _priced(calories=0.0, protein=0.0, carbs=0.0, fats=0.0, rung=rung,
                evidence_id="usda:14209"),
        food_name="Black coffee")
    assert priced.calories == 0.0
    assert priced.evidence_backed


def test_no_food_name_decides_whether_zero_is_allowed():
    """A curated list of foods permitted to be zero is a food-name branch
    wearing a different hat, and wrong for the first zero-calorie food nobody
    listed. AST over the module: no string-literal comparisons, no literal
    string collections at module scope."""
    from core import canonical_pricing as cp

    tree = ast.parse(pathlib.Path(cp.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                assert not (isinstance(side, ast.Constant)
                            and isinstance(side.value, str) and side.value), (
                    f"line {node.lineno} compares against a string literal")
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for value in ast.walk(node):
                if isinstance(value, (ast.List, ast.Set)):
                    strings = [e for e in value.elts
                               if isinstance(e, ast.Constant)
                               and isinstance(e.value, str)]
                    assert not strings, (
                        f"line {node.lineno} holds a literal string collection")


def test_an_unpriceable_food_raises_rather_than_returning_a_meal():
    """Returned, a `None` price becomes a zero-calorie meal one `or 0.0` later
    — which is exactly how the legacy path failed. Raising makes the failure
    the caller's problem, visibly."""
    with pytest.raises(PricingRefused):
        refuse_or_return(None, food_name="Mackerel")


def test_a_real_price_passes_through_unchanged():
    priced = refuse_or_return(_priced(), food_name="Chicken breast")
    assert priced.calories == 165.0 and priced.rung is Rung.ARTIFACT


# ── GATE 3: canonical settle does not import the legacy pricer ──────────────

@pytest.mark.xfail(reason="RED until the canonical pricer replaces the rented "
                          "_analyze_food import — this gate is the definition "
                          "of done for that work", strict=False)
def test_canonical_settlement_does_not_import_the_legacy_pricer():
    """THE SEAM, AS AN IMPORT GATE.

    The canonical spine takes exactly ONE thing from the legacy pipeline:
    `from handlers.tool_executor import _analyze_food` in `settle`. Every
    production defect measured on the canonical lane — 8,171 ms of an 8,225 ms
    tap, the zero-calorie row, two prices for one identity — is on the far
    side of that import. When it is gone, the canonical lane owns its whole
    path for allowlisted users.
    """
    canonical = ["core/b1_quantity_operation.py", "core/canonical_writer.py",
                 "core/commit_coordinator.py", "core/b1_answer_turn.py",
                 "core/canonical_pricing.py"]
    offenders = []
    for rel in canonical:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "tool_executor" in node.module or "food_turn" in node.module:
                    names = ", ".join(a.name for a in node.names)
                    offenders.append(f"{rel}:{node.lineno} imports {names}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if "tool_executor" in a.name or "food_turn" in a.name:
                        offenders.append(f"{rel}:{node.lineno} imports {a.name}")
    assert not offenders, (
        "the canonical lane still rents from legacy:\n  "
        + "\n  ".join(offenders))


def test_the_pricer_itself_is_already_free_of_legacy():
    """Whatever the spine still does, the NEW module must never acquire the
    dependency it exists to remove."""
    tree = ast.parse((ROOT / "core/canonical_pricing.py").read_text(
        encoding="utf-8"))
    for node in ast.walk(tree):
        mod = ""
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
        elif isinstance(node, ast.Import):
            mod = ",".join(a.name for a in node.names)
        assert "tool_executor" not in mod and "food_turn" not in mod, mod
