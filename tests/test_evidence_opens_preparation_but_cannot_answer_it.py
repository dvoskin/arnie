"""THE INVARIANT COMMIT 2 IS BUILT AROUND:

    external evidence establishes the SPACE of plausible answers
    only user evidence — or an explicit assumption policy — resolves the VALUE

A compatible record saying `Chicken breast, roasted` is evidence that ROASTED
EXISTS as a material preparation for this food. It is NOT evidence that the
user ate roasted chicken. Collapsing those two is how a clarification system
quietly stops asking and starts assuming — and it is exactly the shape that
would let semantic evidence mutate user state, which the whole boundary
exists to prevent.

So: qualified evidence may OPEN the preparation field and populate its
options. It may never construct a `SetPreparation`. The only writers of a
resolved preparation are the user's tap, the user's stated text, and (later,
B-1.7) a disclosed assumption policy.
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib

import pytest

from core.semantic_evidence import SemanticAssessment
from skills.nutrition import evidence_semantics as food

CORPUS = pathlib.Path(__file__).parent / "evidence_corpus"


def _record(evidence_id, title, kcal):
    from core.semantic_evidence import EvidenceRecord

    return EvidenceRecord(evidence_id=evidence_id, provider="usda",
                          title=title, nutrition={"calories": kcal})


def _compatible(record, preparation, confidence=0.92):
    return SemanticAssessment(
        evidence_id=record.evidence_id,
        relationship="COMPATIBLE_SPECIALIZATION", confidence=confidence,
        extracted={"preparation": preparation},
        resolver_version=food.VERSION)


#: Two registered preparations, materially apart — the shape that justifies
#: asking. Densities are the real USDA/web numbers for roasted vs fried
#: chicken (165 / 253), captured in GROUND_TRUTH.md.
def _material_pair():
    roasted = _record("usda:1", "Chicken breast, meat only, roasted", 165)
    fried = _record("usda:2", "Chicken, thigh, fried", 253)
    return ([roasted, fried],
            [_compatible(roasted, "roasted"), _compatible(fried, "fried")])


# ── evidence establishes the SPACE ──────────────────────────────────────────

def test_qualified_evidence_yields_a_preparation_space():
    records, assessments = _material_pair()
    space = food.preparation_evidence(assessments, records,
                                      minimum_confidence=0.80)
    assert {e.preparation_id for e in space} == {"roasted", "fried"}
    assert {e.kcal_per_100g for e in space} == {165.0, 253.0}


def test_only_identity_bearing_evidence_shapes_the_space():
    """A fried SANDWICH is not evidence about chicken's fried density."""
    records, assessments = _material_pair()
    sandwich = _record("usda:3", "Fast foods, chicken sandwich, fried", 290)
    records.append(sandwich)
    assessments.append(SemanticAssessment(
        evidence_id="usda:3", relationship="COMPOSITE_CONTAINING_IDENTITY",
        confidence=0.95, extracted={"preparation": "fried"},
        resolver_version=food.VERSION))

    space = food.preparation_evidence(assessments, records,
                                      minimum_confidence=0.80)
    assert [e.evidence_id for e in space] == ["usda:1", "usda:2"]


def test_low_confidence_evidence_shapes_nothing():
    records, assessments = _material_pair()
    weak = [_compatible(records[0], "roasted", confidence=0.55),
            _compatible(records[1], "fried", confidence=0.60)]
    assert food.preparation_evidence(weak, records,
                                     minimum_confidence=0.80) == ()


# ── ...but never the VALUE ──────────────────────────────────────────────────

def test_preparation_evidence_carries_no_patch_and_no_answer():
    """The projection is EVIDENCE, structurally. It has no field through which
    a resolved value could travel — the same negative-capability discipline as
    `SemanticAssessment` having no 'use this row'."""
    fields = set(food.PreparationEvidence.__dataclass_fields__)
    assert fields == {"preparation_id", "kcal_per_100g", "provider",
                      "confidence", "evidence_id"}
    assert "patch" not in fields and "answer" not in fields


def test_no_evidence_path_constructs_a_preparation_patch():
    """THE RATCHET. `SetPreparation` may be constructed by the OPTION producer
    (each chip carries its patch, which is how a tap means something) and by
    nothing in the evidence or activation path.

    If evidence could build a patch, "roasted exists" would become "you ate
    roasted" one refactor later, and no test would notice."""
    root = pathlib.Path(__file__).resolve().parent.parent
    allowed = {
        # The option producer: a chip's meaning IS its patch (C11).
        "skills/nutrition/quantity_clarification.py",
        # The answer path: turns a user's tap/text into the value they chose.
        "core/clarification_answer.py",
        "core/semantics.py",            # defines it
    }
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")):
            continue
        if rel in allowed or ("/" not in rel and rel.startswith(("simulate_",
                                                                "test_"))):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    getattr(node.func, "id", "") == "SetPreparation":
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"{offenders} construct a resolved preparation outside the option "
        f"producer and the answer path — external evidence establishes the "
        f"SPACE of plausible answers; only the user resolves the VALUE")


def test_the_evidence_modules_never_import_the_patch_type():
    """Stronger than the call ratchet: the evidence layer cannot even name
    the type it must not build."""
    from skills.nutrition import evidence_qualification as eq

    for module in (food, eq):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
        assert "SetPreparation" not in imported, module.__name__


def test_a_stated_preparation_is_the_users_word_not_the_evidences():
    """The other direction: when the USER states a preparation, evidence does
    not get to disagree — the field simply does not open. `stated` exists to
    distinguish a told method from an inferred one."""
    from skills.nutrition.staging import PreparationIntent

    told = PreparationIntent(method="grilled", stated=True)
    assert told.stated and told.method == "grilled"
    inferred = PreparationIntent(method="grilled", stated=False)
    assert not inferred.stated, (
        "an inferred method must remain distinguishable from a told one, or "
        "an assumption becomes indistinguishable from the user's own word")
