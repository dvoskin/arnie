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


def _seeded(records, assessments, food_name="chicken"):
    """A context whose structured classification has ALREADY been done — what
    the pricing path leaves behind for preparation to await."""
    import asyncio

    from core.evidence_context import EvidenceContext
    from skills.nutrition.evidence_qualification import assessment_key

    ctx = EvidenceContext()
    done = asyncio.get_event_loop().create_future() \
        if False else asyncio.Future()
    done.set_result((tuple(records), tuple(assessments)))
    ctx._inflight[assessment_key(food_name, food.VERSION)] = done
    return ctx


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
    ctx = _seeded(records, composite)

    async def no_web(food_name, exclude=frozenset()):
        return {}

    monkeypatch.setattr(pa, "_web_space", no_web)
    assert await pa.preparation_space("chicken", ctx) == {}


@pytest.mark.asyncio
async def test_low_confidence_evidence_establishes_no_space(monkeypatch):
    records = [_web("web:1"), _web("web:2")]
    weak = [_assessment("web:1", "grilled", 165, confidence=0.55),
            _assessment("web:2", "fried", 250, confidence=0.60)]
    ctx = _seeded(records, weak)

    async def no_web(food_name, exclude=frozenset()):
        return {}

    monkeypatch.setattr(pa, "_web_space", no_web)
    assert await pa.preparation_space("chicken", ctx) == {}


# ── 1. the cache is turn-scoped, and says so ────────────────────────────────

def test_a_later_turn_cannot_reuse_an_earlier_turns_evidence():
    """THE LIFETIME, BY CONSTRUCTION rather than by a key.

    Three versions of this: a module dict called turn-scoped while nothing
    cleared it; then a turn id in the key; now the work lives on a context the
    TURN owns, so a later turn holds no reference to it at all. The shape that
    could leak is gone rather than guarded.
    """
    from core.evidence_context import EvidenceContext

    turn_a, turn_b = EvidenceContext(), EvidenceContext()
    assert not turn_a.reused("assess:chicken:v1")
    turn_a._inflight["assess:chicken:v1"] = object()
    assert turn_a.reused("assess:chicken:v1")
    assert not turn_b.reused("assess:chicken:v1"), (
        "a second turn saw the first turn's work")


@pytest.mark.asyncio
async def test_concurrent_consumers_share_one_acquisition():
    """The property a completed-value cache cannot give: two fields evaluated
    TOGETHER both miss a value cache and both pay. Memoizing the coroutine
    means the second awaits the first's future."""
    import asyncio

    from core.evidence_context import EvidenceContext

    ctx, calls = EvidenceContext(), []

    async def acquire():
        calls.append(1)
        await asyncio.sleep(0.02)
        return "assessments"

    both = await asyncio.gather(ctx.shared("k", acquire),
                                ctx.shared("k", acquire))
    assert both == ["assessments", "assessments"]
    assert len(calls) == 1, f"{len(calls)} acquisitions for one key"


@pytest.mark.asyncio
async def test_preparation_never_starts_its_own_retrieval():
    """§4: acquisition belongs to the pricing path. If it never ran this turn,
    preparation gets nothing rather than opening a second retrieval path."""
    from core.evidence_context import EvidenceContext

    ctx = EvidenceContext()

    async def no_web(food_name, exclude=frozenset()):
        return {}

    original, pa._web_space = pa._web_space, no_web
    try:
        assert await pa.preparation_space("chicken", ctx) == {}
    finally:
        pa._web_space = original
    assert ctx.meta["preparation"]["assessments_reused"] is False


# ── fields request evidence; they do not own retrieval lifecycles ───────────

@pytest.mark.asyncio
async def test_supplemental_evidence_is_deduplicated_by_the_context():
    """Two fields wanting the same supplemental evidence await ONE lookup.

    Without this the shape regrows one field at a time: PreparationField calls
    Tavily, VariantField calls something else, and every future field brings
    its own client and its own duplicate spend.
    """
    import asyncio

    from core.evidence_context import EvidenceContext

    calls = []

    async def fake_web(food_name, exclude=frozenset()):
        calls.append(food_name)
        await asyncio.sleep(0.01)
        return {"grilled": 165.0, "fried": 250.0}

    ctx = EvidenceContext()
    original, pa._web_space = pa._web_space, fake_web
    try:
        await asyncio.gather(pa.preparation_space("chicken", ctx),
                             pa.preparation_space("chicken", ctx))
    finally:
        pa._web_space = original
    assert len(calls) == 1, f"{len(calls)} supplemental lookups for one key"


def test_no_field_module_calls_a_provider_directly():
    """THE INVARIANT: fields project and REQUEST evidence; they do not own
    provider retrieval lifecycles. Acquisition functions exist, but a field
    reaches them only through `EvidenceContext.shared`.
    """
    import ast

    source = pathlib.Path(pa.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Every provider call must sit inside an acquisition function — one the
    # context invokes — never in the decision path.
    acquisitions = {"_web_space"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in acquisitions:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                name = (getattr(inner.func, "attr", "")
                        or getattr(inner.func, "id", ""))
                assert name not in ("search", "search_food"), (
                    f"{node.name} calls a provider directly at line "
                    f"{inner.lineno} — request evidence through the context")
