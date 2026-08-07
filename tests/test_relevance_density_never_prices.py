"""The wall between RELEVANCE evidence and PRICING evidence, gated directly.

`kcal_per_100g` became a declared extraction field so the model could read a
density out of web prose ("grilled 165, fried 250") instead of a regex doing
it. That is acceptable ONLY because the value is relevance-only:

    extracted web density
      -> may establish materiality
      -> may open preparation
      -> may NEVER price settlement

If that wall ever softens, the model quietly becomes a nutrition calculator
and B-1.5E has undone its own purpose. These gates are the wall.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from core.semantic_evidence import EvidenceRecord, SemanticAssessment
from skills.nutrition import evidence_qualification as eq
from skills.nutrition import evidence_semantics as food
from skills.nutrition import preparation_activation as pa

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _web(evidence_id="web:answer"):
    return EvidenceRecord(evidence_id=evidence_id, provider="web",
                          description="grilled 165, fried 250 per 100 g",
                          evidence_type="synthesized_text")


def _assessment(evidence_id, preparation, kcal, relationship="SAME_IDENTITY",
                confidence=0.95):
    return SemanticAssessment(
        evidence_id=evidence_id, relationship=relationship,
        confidence=confidence,
        extracted={"preparation": preparation, "kcal_per_100g": kcal},
        resolver_version=food.VERSION)


# ── 2. the extracted density cannot reach pricing ───────────────────────────

def test_a_synthesized_record_is_never_admissible_for_pricing():
    assert eq.admissible_for_relevance(_web())
    assert not eq.admissible_for_pricing(_web())


def test_the_extracted_density_reaches_relevance_and_stops_there():
    """It populates `PreparationEvidence` — the relevance projection — and
    there is no pricing projection that carries it at all."""
    records = [_web("web:1"), _web("web:2")]
    assessments = [_assessment("web:1", "grilled", 165),
                   _assessment("web:2", "fried", 250)]

    relevance = food.preparation_evidence(
        assessments, records,
        minimum_confidence=food.MINIMUM_IDENTITY_CONFIDENCE)
    assert {e.kcal_per_100g for e in relevance} == {165.0, 250.0}

    # The variant projection is the only other consumer, and it carries no
    # density derived from extraction.
    variant = food.variant_evidence(
        assessments, records,
        minimum_confidence=food.MINIMUM_IDENTITY_CONFIDENCE)
    assert all(v.kcal_per_100g is None for v in variant), (
        "an extracted density leaked into a non-relevance projection")


def test_no_pricing_module_consumes_the_relevance_projection():
    """AST, repo-wide: nothing on the settlement or ranking path may import
    `PreparationEvidence` or `preparation_evidence` — the density's only
    consumer is activation."""
    allowed = {"skills/nutrition/evidence_semantics.py",      # defines it
               "skills/nutrition/preparation_activation.py"}  # sole consumer
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")) \
                or rel in allowed:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in ("PreparationEvidence",
                                      "preparation_evidence"):
                        offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"{offenders} import the relevance projection — a web-extracted "
        f"density must never reach ranking or settlement")


def test_settle_cannot_see_an_extracted_density():
    """The settlement path names neither the projection nor the field."""
    from core import b1_quantity_operation as b1

    source = inspect.getsource(b1.settle)
    for banned in ("kcal_per_100g", "PreparationEvidence",
                   "preparation_evidence", "preparation_space"):
        assert banned not in source, f"settle references {banned}"


# ── 3. density only where the source states it ──────────────────────────────

def test_the_schema_forbids_derived_densities():
    """No arithmetic inference: the model may not convert a per-serving figure
    into per-100g, because that would make it a nutrition calculator rather
    than a classifier."""
    guidance = food.DOMAIN.guidance
    assert "per 100 g" in guidance
    for phrase in ("per-serving", "convert", "infer"):
        assert phrase in guidance, (
            f"the extraction instruction no longer forbids {phrase!r} "
            f"densities")


# ── 4. interpreter uncertainty opens the field; options stay registered ─────

@pytest.mark.asyncio
async def test_interpreter_uncertainty_opens_the_field_with_registered_options():
    """Believing the interpreter that preparation is UNRESOLVED is fine.
    Believing its candidate VALUES would not be — the options come from the
    registry either way."""
    from core.semantic_fields import spec_for
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
    from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                          StagedFoodItem)

    item = StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken",
        identity=FoodIdentity(canonical_name="chicken"),
        quantity=QuantityIntent(descriptor="some"),
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.PREPARATION, field_name="preparation",
            materiality_score=1.5, calorie_span=90.0),))

    assert await pa.preparation_is_materially_unresolved(item)

    field = qc.preparation_field(operation_id="op_1", revision=0, item=item)
    offered = {o.patch.preparation_id for o in field.options}
    registered = set(spec_for("preparation").vocabulary) | {"unknown"}
    assert offered <= registered, (
        f"{offered - registered} came from somewhere other than the registry")


# ── 5. two densities are not two options unless QUALIFIED ───────────────────

@pytest.mark.asyncio
async def test_unqualified_evidence_establishes_no_space(monkeypatch):
    """Two strings saying "fried" and "roasted" are not a preparation space.
    The relationship must be identity-bearing and clear the confidence bar."""
    records = [_web("web:1"), _web("web:2")]
    composite = [
        _assessment("web:1", "grilled", 165,
                    relationship="COMPOSITE_CONTAINING_IDENTITY"),
        _assessment("web:2", "fried", 250,
                    relationship="DIFFERENT_IDENTITY"),
    ]
    eq.remember_assessments("chicken", records, composite)

    async def no_web(food_name, exclude=frozenset()):
        return {}

    monkeypatch.setattr(pa, "_web_space", no_web)
    assert await pa.preparation_space("chicken") == {}


@pytest.mark.asyncio
async def test_low_confidence_evidence_establishes_no_space(monkeypatch):
    records = [_web("web:1"), _web("web:2")]
    weak = [_assessment("web:1", "grilled", 165, confidence=0.55),
            _assessment("web:2", "fried", 250, confidence=0.60)]
    eq.remember_assessments("chicken", records, weak)

    async def no_web(food_name, exclude=frozenset()):
        return {}

    monkeypatch.setattr(pa, "_web_space", no_web)
    assert await pa.preparation_space("chicken") == {}


# ── 1. the cache is turn-scoped, and says so ────────────────────────────────

def test_the_assessment_cache_is_process_local_and_bounded():
    """Turn-scoped for now. A DURABLE cache would need the evidence
    fingerprint in the key too — the same food string can retrieve different
    evidence sets — and that is recorded rather than built."""
    assert isinstance(eq._ASSESSED, dict)
    assert eq._ASSESSED_MAX <= 256, "an unbounded cache is a memory leak"
    source = inspect.getsource(eq)
    assert "durable" in source.lower(), (
        "the cache no longer documents that it is not the durable one")
