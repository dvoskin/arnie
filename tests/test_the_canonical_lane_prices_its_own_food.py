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


# ── THE NON-MUTATION GATE: a refusal writes nothing ─────────────────────────

def test_pricing_refusal_is_raised_before_anything_is_written():
    """P1.4's required gate, asserted STRUCTURALLY.

    `settle` prices BEFORE `commit_or_load_existing`, so a `PricingRefused`
    cannot reach a write — no food row, no ledger event, and the operation
    never reports APPLIED. That ordering is the guarantee; this pins it, so a
    later edit that moves pricing below the commit fails here rather than in
    production.
    """
    import inspect
    import textwrap

    from core import b1_quantity_operation as b1

    tree = ast.parse(textwrap.dedent(inspect.getsource(b1.settle)))
    price_line = commit_line = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name == "price" and price_line is None:
            price_line = node.lineno
        if name == "commit_or_load_existing":
            commit_line = node.lineno
    assert price_line and commit_line, (price_line, commit_line)
    assert price_line < commit_line, (
        "pricing moved BELOW the commit — a refusal could now leave a written "
        "row behind, which is the failure entry 2932 already demonstrated")


def test_the_refusal_is_caught_by_type_and_never_generically():
    """A bare `except Exception` around settle would turn a refusal back into
    a fallback number — the exact defect being deleted. The handler must name
    `PricingRefused` and return REFUSED, not APPLIED."""
    import inspect

    from core import b1_answer_turn as at

    tree = ast.parse(inspect.getsource(at))
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        name = getattr(node.type, "id", "") or getattr(node.type, "attr", "")
        if name != "PricingRefused":
            continue
        found = True
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        assert returns, "the refusal handler returns nothing"
        rendered = ast.dump(returns[0])
        assert "REFUSED" in rendered, "a refusal did not return REFUSED"
        assert "APPLIED" not in rendered
    assert found, "no PricingRefused handler — a refusal would crash the turn"


# ══ THE ADVERSARIAL AUDIT, 2026-08-08 ═══════════════════════════════════════
#
# Four defects found by probing `price()` with hostile portions, in code that
# had just gone green on 8,588 tests. The suite could not see any of them
# because nothing exercised a portion that could not be massed. Each gate below
# is one of those findings.

#: A USDA row as the artifact stores it, carrying micros the profile model does
#: not have fields for — which is exactly how they went missing.
USDA_WITH_MICROS = (
    {"fdc_id": 1, "description": "Chicken",
     "per100g": {"calories": 165.0, "protein": 31.0, "carbs": 0.0, "fat": 3.6,
                 "iron": 1.0, "calcium": 15.0, "potassium": 256.0,
                 "vitamin_b12": 0.3}},
)
AN_ESTIMATE = EstimateEvidence(calories=280.0, protein=53.0, carbs=0.0,
                               fat=6.0, basis_grams=170.0)


def test_micronutrients_survive_pricing_and_scale_with_the_portion():
    """FINDING 1: `micros` was never populated, so EVERY canonical row would
    have lost its micronutrients — silently, and the Daily Log reveal reads
    them.

    `NutrientProfile` models only six micros (MICRO_FIELDS) while a USDA row
    carries ~22, so reading them back off the profile alone still drops most.
    They are scaled from the raw per-basis dict by the factor the profile
    itself moved by, which keeps one scaling authority.
    """
    priced = price(entity="Chicken", consumed=_g(200),
                   artifact=ArtifactEvidence(candidates=USDA_WITH_MICROS))
    assert priced.calories == pytest.approx(330.0), priced.calories
    assert priced.micros, "every canonical row would have lost its micros"
    for name, per100g in (("iron", 1.0), ("calcium", 15.0),
                          ("potassium", 256.0), ("vitamin_b12", 0.3)):
        assert priced.micros.get(name) == pytest.approx(per100g * 2.0), (
            f"{name} did not scale with the portion: {priced.micros}")
    # The macros keep their own columns and must not be duplicated as micros.
    for macro in ("calories", "protein", "carbs", "fat"):
        assert macro not in priced.micros


@pytest.mark.parametrize("label,quantity", [
    ("count-only, no mass", NormalizedQuantity(amount=1, unit="breast",
                                               grams=None, count=1)),
    ("zero grams", NormalizedQuantity(amount=0, unit="g", grams=0)),
    ("negative grams", NormalizedQuantity(amount=-5, unit="g", grams=-5)),
    ("no quantity at all", None),
])
def test_no_hostile_portion_escapes_as_anything_but_pricing_refused(
        label, quantity):
    """FINDING 2, THE WORST ONE. `scale_profile` raises `ScalingRefused` for a
    portion it cannot mass, and a count-only answer ("1 breast") is an ordinary
    production case, not an exotic one.

    `ScalingRefused` is NOT `PricingRefused`, so it escaped the narrow handler
    in `b1_answer_turn` and took the whole turn down — worse than the
    zero-calorie row this P1 exists to delete. Only `PricingRefused` may leave
    this function.
    """
    try:
        price(entity="Chicken", consumed=quantity,
              artifact=ArtifactEvidence(candidates=USDA_WITH_MICROS))
    except PricingRefused:
        pass                       # the one escape the caller handles
    except Exception as exc:       # pragma: no cover - the failure being gated
        pytest.fail(f"{label}: {type(exc).__name__} escaped price() — "
                    f"b1_answer_turn catches PricingRefused only, so this "
                    f"crashes the turn: {exc}")


@pytest.mark.parametrize("grams", [0, -5])
def test_a_degenerate_portion_is_refused_even_from_an_evidence_rung(grams):
    """FINDING 3: the mackerel defect returning through another door.

    Scaling 165 kcal/100 g by zero grams yields a zero from an EVIDENCE-backed
    rung, and `is_defensible()` waves those through — correctly, because black
    coffee really is zero. The degenerate thing here is the PORTION, not the
    food, so it is refused before any rung runs.
    """
    with pytest.raises(PricingRefused):
        price(entity="Chicken",
              consumed=NormalizedQuantity(amount=grams, unit="g", grams=grams),
              artifact=ArtifactEvidence(candidates=USDA_WITH_MICROS))


def test_an_unscalable_rung_falls_through_instead_of_refusing_the_meal():
    """FINDING 4: fixing the crash introduced a refusal.

    A count-only answer cannot scale a per-100 g artifact basis — but a
    perfectly good estimate sits on the next rung. Refusing the meal there
    throws away an answer we have. Scaling therefore happens INSIDE the rung
    loop: a rung that cannot be scaled has simply failed, and the ladder
    continues.
    """
    priced = price(entity="Chicken",
                   consumed=NormalizedQuantity(amount=1, unit="breast",
                                               grams=None, count=1),
                   artifact=ArtifactEvidence(candidates=USDA_WITH_MICROS),
                   estimate=AN_ESTIMATE)
    assert priced.rung is Rung.ESTIMATE, (
        f"the artifact rung could not scale, so the estimate should have "
        f"priced it; got {priced.rung}")
    assert priced.calories == pytest.approx(280.0)


def test_an_indefensible_rung_also_falls_through():
    """The same rule for a rung that produces a zero rather than an exception:
    a zero ESTIMATE must not end the ladder while real evidence waits.

    WRITTEN THE WRONG WAY FIRST, and the failure was informative. The original
    version seeded a zero MEMORY rung and expected the artifact to win — but an
    evidence-backed zero is legitimate by design (that is the black-coffee
    rule), so memory correctly won and the test was asserting against the
    contract. It was also unreachable: `_memory` drops a falsy `cal_100`, so a
    zero memory row never reaches the pricer at all.

    The estimate rung is the one that genuinely may not price zero, so it is
    the one that must yield to real evidence.
    """
    priced = price(entity="Chicken", consumed=_g(100),
                   artifact=ArtifactEvidence(candidates=USDA_WITH_MICROS),
                   estimate=EstimateEvidence(calories=0.0, protein=0.0,
                                             carbs=0.0, fat=0.0))
    assert priced.rung is Rung.ARTIFACT and priced.calories > 0


# ══ ONE TYPED IDENTITY, ONE KEY ═════════════════════════════════════════════
#
# Measured in production 2026-08-10. Preparation reaches pricing by two routes:
# answered as a FIELD, or named in the message and composed into the food. They
# built different keys, so the second missed evidence the artifact already
# held — and stating the preparation made pricing WORSE than omitting it:
#
#     Beef          120 g   151 kcal   29.0 g protein   evidence
#     Beef, grilled 120 g   151 kcal   24.0 g protein   estimate
#
# Not a coverage gap. `beef|grilled` held five qualified candidates the whole
# time; `beef, grilled|` simply could not address them.

from skills.nutrition import pricing_artifact as _pricing_artifact  # noqa: E402


@pytest.mark.parametrize("entity,preparation", [
    ("Beef", "grilled"),            # answered as a field
    ("Beef, grilled", ""),          # composed by `name_with`
    ("grilled beef", ""),           # natural order, preparation first
    ("BEEF,  GRILLED", ""),         # case and spacing
    ("Beef, grilled", "grilled"),   # both, because `name_with` is idempotent
])
def test_every_expression_of_one_identity_makes_the_same_key(entity,
                                                             preparation):
    assert _pricing_artifact.key(entity, preparation) == "beef|grilled"


def test_the_evidence_that_was_unreachable_is_reachable_from_both_routes():
    """THE REGRESSION, against the committed artifact: whichever way the user
    said it, the same five candidates must be found."""
    _pricing_artifact._reset_for_tests()
    by_field = _pricing_artifact.evidence_for("Beef", "grilled")
    by_name = _pricing_artifact.evidence_for("Beef, grilled", "")
    assert by_field and by_name, "the artifact rung is unreachable"
    assert len(by_field.candidates) == len(by_name.candidates) > 0
    assert ({c.get("fdc_id") for c in by_field.candidates}
            == {c.get("fdc_id") for c in by_name.candidates}), (
        "the two routes reach DIFFERENT evidence, so pricing depends on how "
        "the user phrased it")


@pytest.mark.parametrize("entity,expected", [
    ("chicken, fried", ("chicken", "fried")),
    ("fried chicken", ("chicken", "fried")),
    ("salmon, roasted", ("salmon", "roasted")),
    ("mushrooms", ("mushrooms", "")),          # no preparation at all
    ("cod", ("cod", "")),
])
def test_the_split_generalises_across_entities_and_preparations(entity,
                                                                expected):
    """GENERIC, or it is a heuristic. If this only worked for beef and grilled
    it would be the food-name branch this codebase forbids."""
    assert _pricing_artifact.split_identity(entity) == expected


def test_the_split_is_driven_by_the_registry_and_names_no_food():
    """AST: no food and no preparation may be written into this module. A
    preparation is recognised because it is DECLARED, so extending the
    vocabulary extends the split for free."""
    import pathlib

    tree = ast.parse(pathlib.Path(_pricing_artifact.__file__).read_text(
        encoding="utf-8"))
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
    for banned in ("beef", "chicken", "grilled", "fried", "roasted", "salmon"):
        hits = [v for v in live if banned in v]
        assert not hits, f"the split acts on the literal {banned!r}: {hits}"

    calls = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "spec_for" in calls, (
        "the vocabulary is not read from the registry, so a new preparation "
        "will not be recognised")


def test_a_preparation_inside_a_word_is_not_stripped():
    """Word boundaries, not substrings. A substring test would silently change
    the FOOD — the one thing an identity boundary may never do."""
    assert _pricing_artifact.split_identity("friedcake") == ("friedcake", "")
    assert _pricing_artifact.split_identity("grilledine") == ("grilledine", "")


# ── THE SECOND CONSUMER OF THE IDENTITY BOUNDARY: THE RANKER ───────────────
#
# Fixing `key` made the evidence FINDABLE from both routes. It did not make it
# USABLE from both: `price` still asked `best_candidate` about the bare
# entity, so a preparation supplied as a field was addressable for the lookup
# and invisible to the ranker. Measured offline against the committed
# artifact, 2026-08-10 — same evidence object, opposite outcome:
#
#     entity="Beef, grilled"        -> 5 candidates -> 250 kcal   artifact rung
#     entity="Beef" prep="grilled"  -> 5 candidates -> REFUSED    no rung
#
# The refusal is the worse half. A miss falls to an estimate; this found the
# right evidence and discarded it, which is indistinguishable from never
# having generated the artifact at all.

def _one_candidate_per_preparation():
    """Two rows a ranker can tell apart only if the query names the prep."""
    return (
        {"fdc_id": 1, "description": "Beef, shoulder, cooked, grilled",
         "per100g": {"calories": 208.0, "protein": 28.4}},
        {"fdc_id": 2, "description": "Beef, ground, raw",
         "per100g": {"calories": 254.0, "protein": 17.2}},
    )


def test_a_preparation_answered_as_a_field_prices_like_one_named_in_the_food():
    """THE DEFECT, as a rule. Both routes express one identity, so both must
    reach the same record — a field answer must not price worse than saying
    it in the message."""
    ev = ArtifactEvidence(candidates=_one_candidate_per_preparation(),
                          fingerprint="f")

    composed = price(entity="Beef, grilled", consumed=_g(100), artifact=ev)
    fielded = price(entity="Beef", preparation="grilled",
                    consumed=_g(100), artifact=ev)
    spoken = price(entity="grilled beef", consumed=_g(100), artifact=ev)

    assert fielded.rung is Rung.ARTIFACT, (
        "a preparation answered as a field found its evidence and then "
        "discarded it — the ranker was asked about a different identity")
    for other in (composed, spoken):
        assert fielded.calories == other.calories
        assert fielded.protein == other.protein
        assert fielded.evidence_id == other.evidence_id


def test_the_ranker_is_asked_about_the_identity_the_artifact_was_keyed_by():
    """The two consumers must not drift apart again: whatever `key` splits,
    the ranker query composes from the SAME split."""
    from skills.nutrition import pricing_artifact as pa

    for entity, preparation in (("Beef", "grilled"), ("Beef, grilled", ""),
                                ("grilled beef", ""), ("Beef", ""),
                                ("BEEF,  GRILLED", "")):
        ent, prep = pa.split_identity(entity, preparation)
        assert pa.key(entity, preparation) == f"{ent}|{prep}"
        composed = pa.priced_identity(entity, preparation)
        assert ent in composed
        if prep:
            assert prep in composed, (
                f"{entity!r}/{preparation!r} keys as {prep!r} but the ranker "
                f"is asked about {composed!r}, which never says so")


def test_an_unregistered_preparation_still_prices_rather_than_refusing():
    """Composition may not become a new way to fail. A preparation the
    ontology does not hold leaves the entity alone; the rung still ranks."""
    ev = ArtifactEvidence(candidates=_one_candidate_per_preparation(),
                          fingerprint="f")
    priced = price(entity="Beef", preparation="sous-vide-at-dawn",
                   consumed=_g(100), artifact=ev)
    assert priced.rung is Rung.ARTIFACT
