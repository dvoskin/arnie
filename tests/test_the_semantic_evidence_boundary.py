"""The semantic evidence boundary: mechanism proven deterministically.

THREE LAYERS, DELIBERATELY SEPARATE (§12). This file is layer A — pure policy
over a SCRIPTED resolver, so it proves the mechanism (typing, abstention,
bounding, projections, ratchets) and claims NOTHING about whether the real
model classifies well. Layer B grounds the fixtures in captured provider
records (`tests/evidence_corpus/`, raw and ugly). Layer C — the model's actual
false-compatible rate over the ground truth — is `scripts/eval_semantic_evidence.py`
and the live smoke probe, because fourteen green gates against a synthetic
fixture already fooled us once; a scripted resolver here saying SAME_IDENTITY
proves the plumbing, not the judgement.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from core import semantic_evidence as se
from skills.nutrition import evidence_semantics as food

CORPUS = pathlib.Path(__file__).parent / "evidence_corpus"


def _record(evidence_id="e1", title="Chicken, roasted", **kw):
    return se.EvidenceRecord(evidence_id=evidence_id, provider="usda",
                             title=title, **kw)


def _scripted(replies):
    """A resolver that returns a canned JSON body."""
    async def complete(prompt):
        return json.dumps(replies)
    return complete


# ── layer A: mechanism ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_valid_reply_becomes_typed_assessments():
    records = [_record("e1"), _record("e2", title="Fat, chicken")]
    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"), records,
                           _scripted([
        {"evidence_id": "e1", "relationship": "COMPATIBLE_SPECIALIZATION",
         "confidence": 0.9, "extracted": {"preparation": "roasted"}},
        {"evidence_id": "e2", "relationship": "DERIVED_OR_EXTRACTED_FORM",
         "confidence": 0.95},
    ]))
    assert [a.relationship for a in out] == [
        "COMPATIBLE_SPECIALIZATION", "DERIVED_OR_EXTRACTED_FORM"]
    assert out[0].extracted == {"preparation": "roasted"}
    assert all(a.resolver_version == food.VERSION for a in out)


@pytest.mark.asyncio
async def test_an_invented_relationship_becomes_abstention():
    """The model cannot extend the vocabulary from inside a reply (§26)."""
    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"),
                           [_record()], _scripted([
        {"evidence_id": "e1", "relationship": "KIND_OF_SIMILAR",
         "confidence": 0.99}]))
    assert out[0].abstained and out[0].confidence == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence", [None, "high", -0.1, 1.7])
async def test_a_bad_confidence_becomes_abstention(confidence):
    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"),
                           [_record()], _scripted([
        {"evidence_id": "e1", "relationship": "SAME_IDENTITY",
         "confidence": confidence}]))
    assert out[0].abstained


@pytest.mark.asyncio
async def test_a_skipped_record_is_an_abstention_not_a_hole():
    records = [_record("e1"), _record("e2")]
    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"), records,
                           _scripted([
        {"evidence_id": "e1", "relationship": "SAME_IDENTITY",
         "confidence": 0.8}]))
    assert len(out) == 2 and out[1].abstained


@pytest.mark.asyncio
async def test_a_crashing_resolver_abstains_the_batch():
    """§33: the boundary degrades to 'no semantic evidence' — it never crashes
    into the food-logging path and never guesses."""
    async def boom(prompt):
        raise RuntimeError("model down")

    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"),
                           [_record("e1"), _record("e2")], boom)
    assert len(out) == 2 and all(a.abstained for a in out)


@pytest.mark.asyncio
async def test_prose_instead_of_json_abstains_the_batch():
    async def prose(prompt):
        return "Sure! The first record looks like real chicken to me."

    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"),
                           [_record()], prose)
    assert out[0].abstained


@pytest.mark.asyncio
async def test_extraction_is_constrained_to_declared_fields():
    """No smuggling semantics through a side channel."""
    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"),
                           [_record()], _scripted([
        {"evidence_id": "e1", "relationship": "SAME_IDENTITY",
         "confidence": 0.9,
         "extracted": {"preparation": "roasted", "calories_to_log": 226,
                       "use_this_row": True}}]))
    assert out[0].extracted == {"preparation": "roasted"}


@pytest.mark.asyncio
async def test_the_batch_is_bounded():
    """§25: classification over a bounded set, not a second search engine."""
    records = [_record(f"e{i}") for i in range(50)]
    out = await se.resolve(food.DOMAIN, food.FoodIntent("chicken"), records,
                           _scripted([]))
    assert len(out) == se.MAX_RECORDS


def test_policy_owns_thresholds_not_the_model():
    """`confidence=0.91` authorizes nothing (§17): the caller states the
    threshold, and there is no default that could decide for it."""
    import inspect

    signature = inspect.signature(se.qualified)
    assert signature.parameters["minimum_confidence"].default \
        is inspect.Parameter.empty
    a = se.SemanticAssessment("e1", "SAME_IDENTITY", 0.91)
    assert se.qualified([a], accept=food.IDENTITY_BEARING,
                        minimum_confidence=0.95) == ()


def test_the_assessment_cannot_say_use_this_row():
    """§8: the schema has no authorization field at all."""
    fields = {f for f in se.SemanticAssessment.__dataclass_fields__}
    assert fields == {"evidence_id", "relationship", "confidence",
                      "extracted", "resolver_version"}


# ── layer B: the fixtures are the CAPTURED corpus, not fiction ──────────────

def test_the_adapters_represent_the_real_ugly_corpus():
    """The pizza, the chicken fat and the heavy-syrup papaya must survive
    adaptation verbatim — cleaning them up here would rebuild the
    synthetic-fixture failure."""
    usda = json.loads((CORPUS / "usda_2026_08_07.json").read_text())
    chicken = food.from_usda(usda["queries"]["chicken"])
    titles = {r.title for r in chicken}
    assert "Fat, chicken" in titles and "Frankfurter, chicken" in titles

    off = json.loads((CORPUS / "off_2026_08_07.json").read_text())
    best = food.from_off(off["best_match"]["chicken"],
                         off["variants"]["chicken"])
    assert any("PIZZA" in r.title for r in best)
    # The provider's grade is PRESERVED and TRUSTED FOR NOTHING.
    assert best[0].provider_metadata.get("_match") == "exact"


def test_the_synthesized_answer_is_typed_as_synthesized():
    class _Result:
        error = None
        answer = "Grilled chicken breast has about 165 calories per 100g"
        query = "grilled vs fried"
        results = [{"title": "Instagram", "url": "https://instagram.com/x"}]

    records = food.from_web(_Result())
    assert records[0].evidence_type == "synthesized_text"
    assert records[1].source_reference.startswith("https://instagram.com")


# ── the projections: two consumers, one boundary (§29) ──────────────────────

def _assessed(records, spec):
    return [se.SemanticAssessment(r.evidence_id, rel, conf,
                                  extracted=ext, resolver_version=food.VERSION)
            for r, (rel, conf, ext) in zip(records, spec)]


def test_preparation_sees_only_identity_bearing_evidence():
    records = [
        _record("e1", title="Chicken breast, roasted",
                nutrition={"calories": 165}),
        _record("e2", title="Fried chicken sandwich",
                nutrition={"calories": 290}),
    ]
    assessments = _assessed(records, [
        ("COMPATIBLE_SPECIALIZATION", 0.9, {"preparation": "roasted"}),
        ("COMPOSITE_CONTAINING_IDENTITY", 0.9, {"preparation": "fried"}),
    ])
    out = food.preparation_evidence(assessments, records,
                                    minimum_confidence=0.7)
    assert [e.preparation_id for e in out] == ["roasted"], (
        "the sandwich's fried density is not evidence about chicken")
    assert out[0].kcal_per_100g == 165


def test_variant_reuses_the_same_assessments_without_its_own_matcher():
    """§29's reuse gate, deterministically: same assessments, different
    projection, zero identity logic in the variant path."""
    records = [
        _record("e1", title="Core Power Vanilla", nutrition={"calories": 85}),
        _record("e2", title="SPICY CHICKEN & 'NDUJA PIZZA",
                nutrition={"calories": 511}),
    ]
    assessments = _assessed(records, [
        ("SAME_IDENTITY", 0.92, {"brand": "fairlife", "variant": "vanilla"}),
        ("COMPOSITE_CONTAINING_IDENTITY", 0.9, {}),
    ])
    out = food.variant_evidence(assessments, records, minimum_confidence=0.7)
    assert len(out) == 1 and out[0].variant == "vanilla"
    assert out[0].kcal_per_100g == 85


# ── ratchets (§22) ──────────────────────────────────────────────────────────

def _imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_core_semantic_evidence_imports_no_domain_and_no_provider():
    imports = _imports_of(pathlib.Path(se.__file__))
    banned = {m for m in imports
              if m.split(".")[0] in ("skills", "api", "handlers")
              or "usda" in m or "off" in m or "search" in m}
    assert not banned, f"core imports {sorted(banned)}"


def test_semantic_fields_cannot_import_provider_clients():
    """Semantic fields consume QUALIFIED evidence; retrieval never leaks in."""
    from core import semantic_fields

    imports = _imports_of(pathlib.Path(semantic_fields.__file__))
    assert not any("usda" in m or "core.search" in m or ".off" in m
                   for m in imports), imports


def test_the_evidence_policy_contains_no_food_name_literals():
    """No `if food == "chicken"` anywhere in the boundary. Checked as AST
    comparisons, not substrings, so docstrings citing the pizza stay legal."""
    for module in (se, food):
        tree = ast.parse(pathlib.Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for side in [node.left, *node.comparators]:
                    if isinstance(side, ast.Constant) and \
                            isinstance(side.value, str):
                        # Mechanism literals, named individually so a food
                        # name cannot ride in under a loosened rule: the
                        # code-fence stripper's "json" and the record-type
                        # discriminator.
                        assert side.value in ("", "json",
                                              "structured_record"), (
                            f"{module.__name__}:{node.lineno} compares "
                            f"against {side.value!r}")


@pytest.mark.asyncio
async def test_workouts_could_adopt_this_without_a_core_change():
    """THE HONESTY TEST, run rather than promised: a second domain with its
    own vocabulary flows through the same core untouched."""
    workouts = se.SemanticDomain(
        name="workout", version="exercise_evidence_semantics_v0",
        relationships=("SAME_EXERCISE", "VARIATION", "DIFFERENT_EXERCISE"),
        extraction_fields=("equipment",),
        render_intent=lambda intent: f"exercise: {intent}",
        guidance="These are exercise records.")
    record = se.EvidenceRecord(evidence_id="x1", provider="web",
                               title="Barbell bench press")
    out = await se.resolve(workouts, "bench press", [record], _scripted([
        {"evidence_id": "x1", "relationship": "SAME_EXERCISE",
         "confidence": 0.9, "extracted": {"equipment": "barbell"}}]))
    assert out[0].relationship == "SAME_EXERCISE"
    assert out[0].extracted == {"equipment": "barbell"}
    assert out[0].resolver_version == "exercise_evidence_semantics_v0"
