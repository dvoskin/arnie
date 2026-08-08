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


# ══ THE RUNGS ═══════════════════════════════════════════════════════════════

from skills.nutrition.models import NormalizedQuantity          # noqa: E402
from core.canonical_pricing import (ArtifactEvidence,           # noqa: E402
                                    EstimateEvidence,
                                    MemoryEvidence, ProductEvidence, price)

#: Real USDA shape, as `from_usda`/the artifact carries it.
CHICKEN_FRIED = (
    {"fdc_id": 171477, "description": "Chicken, broilers or fryers, meat only, "
     "cooked, fried", "per100g": {"calories": 219.0, "protein": 30.0,
                                  "carbs": 0.0, "fat": 10.0}},
    {"fdc_id": 171478, "description": "Chicken, broilers or fryers, dark meat, "
     "meat only, cooked, fried", "per100g": {"calories": 239.0,
                                             "protein": 28.0, "carbs": 0.0,
                                             "fat": 13.0}},
)


def _g(grams: float) -> NormalizedQuantity:
    return NormalizedQuantity(amount=grams, unit="g", grams=grams)


# ── GATE B: no synchronous evidence acquisition ─────────────────────────────

def test_pricing_cannot_await_anything():
    """GATE B, STRUCTURALLY. A synchronous signature is a stronger guarantee
    than any mock: there is no `await` in `price`, so no provider or model call
    can hide on the normal settle path. This is why the rungs are HANDED their
    evidence."""
    import asyncio
    import textwrap
    import inspect
    assert not asyncio.iscoroutinefunction(price)
    # AST, not substring: the first version asserted `"await" not in src` and
    # matched the word inside this function's own DOCSTRING. A text ratchet
    # producing a false positive inside the gate against hidden awaits.
    tree = ast.parse(textwrap.dedent(inspect.getsource(price)))
    awaits = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Await)]
    assert not awaits, f"the pricer acquired an await at {awaits}"


def test_every_rung_prices_with_the_network_and_resolver_poisoned(monkeypatch):
    """GATE B, BEHAVIOURALLY. Memory, product and artifact hits must all settle
    with providers and the semantic resolver unreachable."""
    async def _boom(*a, **kw):                                # pragma: no cover
        raise AssertionError("the pricer reached the network")

    import api.usda as usda
    monkeypatch.setattr(usda, "search_food", _boom)
    monkeypatch.setattr(usda, "_search", _boom)
    monkeypatch.setattr("core.semantic_evidence.resolve", _boom)

    memory = price(entity="Chicken breast", consumed=_g(100),
                   memory=MemoryEvidence(per100g={"calories": 165.0,
                                                  "protein": 31.0,
                                                  "carbs": 0.0, "fat": 3.6},
                                         source_id="171077"))
    product = price(entity="Barebells bar", consumed=_g(55),
                    product=ProductEvidence(identifier="7340001234567",
                                            per100g={"calories": 364.0,
                                                     "protein": 36.0,
                                                     "carbs": 30.0,
                                                     "fat": 11.0}))
    artifact = price(entity="Chicken, fried", consumed=_g(120),
                     artifact=ArtifactEvidence(candidates=CHICKEN_FRIED))
    assert memory.rung is Rung.MEMORY
    assert product.rung is Rung.PRODUCT
    assert artifact.rung is Rung.ARTIFACT


# ── GATE C / F: deterministic pricing, and chicken stability ────────────────

def test_the_same_artifact_selects_the_same_record_every_run():
    """GATE C + GATE F. "Chicken, fried" priced 295 kcal and then 329 kcal in
    production because fresh qualification produced a different candidate set
    and a different record won. Against a FIXED artifact the winner must be a
    function of the evidence, not of when you asked.

    Asserts the selected `evidence_id`, not merely the calorie total — two
    different records can coincide on calories and still be different facts.
    """
    runs = [price(entity="Chicken, fried", consumed=_g(120),
                  artifact=ArtifactEvidence(candidates=CHICKEN_FRIED))
            for _ in range(8)]
    assert len({r.evidence_id for r in runs}) == 1, (
        f"the winner moved between runs: {[r.evidence_id for r in runs]}")
    assert len({r.calories for r in runs}) == 1
    assert runs[0].evidence_id.startswith("usda:")


def test_candidate_order_does_not_change_the_winner():
    """Determinism must survive the artifact being read in a different order —
    across processes, dict/JSON ordering is not a contract."""
    forward = price(entity="Chicken, fried", consumed=_g(120),
                    artifact=ArtifactEvidence(candidates=CHICKEN_FRIED))
    reverse = price(entity="Chicken, fried", consumed=_g(120),
                    artifact=ArtifactEvidence(
                        candidates=tuple(reversed(CHICKEN_FRIED))))
    assert forward.evidence_id == reverse.evidence_id


def test_no_food_name_branch_exists_in_the_pricer():
    """GATES E + F both end "no mackerel branch" / "no chicken branch".

    AST OVER EXECUTABLE STRINGS, not over the file text. The first version
    lowercased the source and banned the words outright — which failed on the
    DOCSTRINGS that record why entry 2932 and the 295/329 split happened. A
    gate that forbids documenting a production defect is the wrong gate; what
    must not exist is a food name the CODE acts on.
    """
    from core import canonical_pricing as cp

    tree = ast.parse(pathlib.Path(cp.__file__).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    live = [n.value.lower() for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings]
    for banned in ("mackerel", "chicken", "coffee", "salmon"):
        hits = [v for v in live if banned in v]
        assert not hits, f"the pricer acts on the food name {banned!r}: {hits}"


# ── GATE E: the mackerel regression ─────────────────────────────────────────

def test_a_food_with_no_usable_evidence_refuses_instead_of_pricing_zero():
    """ENTRY 2932. Mackerel reached settlement with no admissible evidence and
    the legacy ladder wrote 0.0 kcal / 0 g protein. Here the same situation
    raises, so the meal is not committed at all."""
    with pytest.raises(PricingRefused):
        price(entity="Mackerel", consumed=_g(80))

    with pytest.raises(PricingRefused):
        price(entity="Mackerel", consumed=_g(80),
              artifact=ArtifactEvidence(candidates=()),
              estimate=EstimateEvidence(calories=0.0, protein=0.0,
                                        carbs=0.0, fat=0.0))


def test_an_estimate_with_real_numbers_is_accepted():
    """The fallback must still WORK — refusing everything would be its own
    outage."""
    priced = price(entity="Mackerel", consumed=_g(80),
                   estimate=EstimateEvidence(calories=166.0, protein=15.0,
                                             carbs=0.0, fat=11.0))
    assert priced.rung is Rung.ESTIMATE and priced.calories == 166.0
    assert priced.estimated


def test_a_legitimately_zero_food_still_prices_from_evidence():
    """ENTRY 2820 stays loggable: zero is a fact when evidence says so."""
    priced = price(entity="Black coffee", consumed=_g(240),
                   memory=MemoryEvidence(per100g={"calories": 0.0,
                                                  "protein": 0.0,
                                                  "carbs": 0.0, "fat": 0.0},
                                         source_id="14209"))
    assert priced.calories == 0.0 and priced.rung is Rung.MEMORY


# ── GATE H: rung provenance, and rung ORDER is authority order ──────────────

def test_every_successful_price_names_the_rung_that_produced_it():
    priced = price(entity="Chicken, fried", consumed=_g(120),
                   artifact=ArtifactEvidence(candidates=CHICKEN_FRIED))
    assert priced.rung in set(Rung)
    assert priced.evidence_id, "an evidence-backed price named no evidence"


def test_authority_order_is_memory_then_product_then_artifact_then_estimate():
    """All four available: the most authoritative wins, every time."""
    priced = price(
        entity="Chicken, fried", consumed=_g(120),
        memory=MemoryEvidence(per100g={"calories": 200.0, "protein": 30.0,
                                       "carbs": 0.0, "fat": 8.0},
                              source_id="mem1"),
        product=ProductEvidence(identifier="123", per100g={"calories": 300.0}),
        artifact=ArtifactEvidence(candidates=CHICKEN_FRIED),
        estimate=EstimateEvidence(calories=999.0))
    assert priced.rung is Rung.MEMORY


# ── P1.2: portion basis goes through the existing scaler ────────────────────

def test_the_portion_is_scaled_by_the_existing_scaling_system():
    """219 kcal/100 g at 120 g must be ~263, and it must come from
    `scaling.py` rather than a second quantity system invented here."""
    priced = price(entity="Chicken, fried", consumed=_g(120),
                   artifact=ArtifactEvidence(candidates=CHICKEN_FRIED))
    assert 255 <= priced.calories <= 275, priced.calories
    assert priced.basis == "per_100g"


def test_the_pricer_builds_no_second_scaling_system():
    """AST: the only scaling in here is the imported one."""
    from core import canonical_pricing as cp
    tree = ast.parse(pathlib.Path(cp.__file__).read_text(encoding="utf-8"))
    names = {n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not {n for n in names if "scal" in n.lower() or "factor" in n.lower()}, (
        f"the pricer grew its own scaling: {names}")
