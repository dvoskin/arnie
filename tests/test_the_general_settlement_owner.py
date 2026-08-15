"""A1–A9 — the general canonical settlement owner, gated against §3a.2.

⭐ THE CRITERIA ARE THE TEST NAMES. This slice was specified before it was
built precisely so it could be judged against the contract rather than against
whatever it turned out to do, and A6/A7 were amended (P4) because as first
written each would have admitted a false proof:

  A6  demanded every settlement report `rung=artifact`, which A10 must
      contradict to measure anything — the only way to satisfy both would have
      been to bend rung precedence to pass a test.
  A7  poisoned the resolver globally, which kills the PRE-SETTLEMENT identity
      work the turn needs to produce a structured item at all — the proof
      would have passed by never reaching settlement.

⛔ SO A6 CARRIES A FIXTURE PER REACHABLE DECIDING RUNG *(Danny, 2026-08-16)*,
not only ARTIFACT, or provenance quietly becomes an artifact-specific contract
again.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from core.canonical_pricing import (ArtifactEvidence, EstimateEvidence,
                                    MemoryEvidence, PricingRefused, Rung,
                                    price)
from core.general_settlement import (GeneralSettlementOwner, ItemFacts,
                                     Supported, Unsupported, coverage_for,
                                     decide, settlement_cohort)

PER100 = {"calories": 165.0, "protein": 31.0, "carbs": 0.0, "fat": 3.6}


def _facts(**over):
    base = dict(identity="Chicken breast", entity="chicken", preparation="",
                has_identity=True, has_quantity=True, has_memory=False,
                has_artifact=False)
    base.update(over)
    return ItemFacts(**base)


# ══ A11 — the coverage predicate: pure, pre-settlement, DESCRIPTIVE ═════════

def test_a11_the_predicate_is_pure_and_touches_nothing():
    """⛔ NO DATABASE, NO CLOCK, NO NETWORK, NO WRITE. Structural, not spelling:
    the AST of `decide` may contain no call at all beyond its own dataclass
    constructors, so there is nowhere for a lookup, a price or a claim to hide."""
    tree = ast.parse(inspect.getsource(decide)).body[0]
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert called <= {"Supported", "Unsupported"}, (
        f"the predicate calls {called} — it must decide from facts alone")
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Await)], (
        "the predicate awaits something — it is no longer pre-settlement")


@pytest.mark.parametrize("over,expected_source", [
    ({"has_memory": True}, "memory"),
    ({"has_artifact": True}, "artifact"),
    ({"has_memory": True, "has_artifact": True}, "memory"),
])
def test_a11_local_evidence_is_supported_and_names_its_expected_rung(
        over, expected_source):
    verdict = decide(_facts(**over))
    assert isinstance(verdict, Supported)
    # Memory outranks artifact, and the PREDICTION must say so — otherwise the
    # expected/actual comparison is meaningless the moment both exist.
    assert verdict.expected_source == expected_source


def test_a11_no_local_evidence_is_unsupported_and_says_why():
    """⛔⛔ THE CLIFF, ROUTED AROUND RATHER THAN HIDDEN. `assemble()` retrieves
    NOTHING, so a food in neither artifact nor memory would be priced from the
    interpreter's own estimate while legacy would have found a live USDA row.
    Declining is the honest answer; the reason is the telemetry A10 needs."""
    verdict = decide(_facts())
    assert isinstance(verdict, Unsupported)
    assert "estimate would be worse than legacy" in verdict.reason


def test_a11_is_descriptive_not_aspirational():
    """⭐ 'CAN THE CURRENT SYSTEM SETTLE THIS SAFELY', never 'should we support
    this eventually' *(Danny, 2026-08-16)*. A food with no identity or no
    quantity is not a future feature — it is a decline today."""
    assert isinstance(decide(_facts(has_identity=False)), Unsupported)
    assert isinstance(decide(_facts(has_quantity=False)), Unsupported)


@pytest.mark.asyncio
async def test_a11_one_unsupported_item_declines_the_whole_meal(monkeypatch):
    """⛔ PARTIAL OWNERSHIP IS DUAL AUTHORITY. Two items canonical and one
    legacy would write one meal in two transactions under two owners, with the
    exactly-once claim describing half of it."""
    import core.general_settlement as gs

    async def fake_look(db, *, user_id, item):
        return _facts(has_memory=bool(item.get("known")))

    monkeypatch.setattr(gs, "look", fake_look)
    verdict = await coverage_for(None, user_id=1, items=[{"known": True},
                                                         {"known": False}])
    assert isinstance(verdict, Unsupported)


# ══ the cohort ══════════════════════════════════════════════════════════════

def test_the_cohort_fails_closed(monkeypatch):
    """⛔⛔ UNSET MEANS NOBODY. This flag decides WHICH CODE OWNS THE WRITE; an
    operator who enables the lane and forgets the cohort would move the whole
    fleet onto a settlement path that has never carried their traffic."""
    monkeypatch.delenv("GENERAL_SETTLEMENT_ALLOWLIST", raising=False)
    assert settlement_cohort(26) is False
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", "")
    assert settlement_cohort(26) is False
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", "26")
    assert settlement_cohort(26) is True
    assert settlement_cohort(27) is False
    # A turn with no user id is nobody, not everybody.
    assert settlement_cohort(None) is False


# ══ A2 — the boundary, asserted structurally ════════════════════════════════

def test_a2_the_owner_imports_nothing_from_the_legacy_executor():
    """⛔⛔ THE ONE THING THE CANONICAL SPINE RENTED FROM LEGACY WAS
    `_analyze_food`, AND EVERY CANONICAL DEFECT WAS ON ITS FAR SIDE — 8,171 ms
    of an 8,225 ms tap, and entry 2932 committed at 0.0 kcal. Gated by the AST
    of the module, not by reading it."""
    source = pathlib.Path("core/general_settlement.py").read_text()
    tree = ast.parse(source)
    imported, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not [m for m in imported if m.startswith("handlers")], (
        f"the settlement owner imports from handlers: "
        f"{[m for m in imported if m.startswith('handlers')]} — A2 forbids it")

    # ⚠ AST, NOT `"_analyze_food" in source` — the first version of this
    # assertion failed on the module's own DOCSTRING, which names the seam it
    # was written to delete. A grep gate is a grep trap even when it is right
    # about the rule: what is forbidden is REFERENCING the symbol, and only the
    # tree can tell a reference from prose.
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    referenced |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    referenced |= names
    assert "_analyze_food" not in referenced, (
        "the settlement owner references _analyze_food")


def test_a2_pricing_is_synchronous_so_nothing_can_retrieve():
    """⭐ GATE B, AS A TYPE. `price` has no `await` in its signature, so no
    provider or model call can hide on the settle path. If this ever becomes a
    coroutine the guarantee is gone whatever the comments say."""
    import asyncio

    assert not asyncio.iscoroutinefunction(price)


# ══ A6 — provenance names the rung that ACTUALLY decided ════════════════════
#
# ⛔ ONE FIXTURE PER REACHABLE DECIDING RUNG. Not only ARTIFACT — that is
# exactly how A6 became artifact-specific in its first draft.

def test_a6_memory_decides_and_says_memory():
    priced = price(entity="Chicken breast",
                   memory=MemoryEvidence(per100g=PER100, source_id="ufm:1"),
                   artifact=ArtifactEvidence(candidates=()),
                   consumed=None)
    assert priced.rung is Rung.MEMORY


def _an_artifact_identity() -> str:
    """A REAL committed identity, taken from the artifact itself.

    ⛔⛔ AND IT FAILS RATHER THAN SKIPS. The first version of the A6 artifact
    fixture hard-coded `chicken`, which has no artifact row — so it SKIPPED,
    silently, and A6's artifact case was not being tested at all while the file
    reported green. A skipped fixture for the criterion that exists to prove
    provenance is the vacuity this slice was warned about by name.
    """
    from skills.nutrition.pricing_artifact import _artifact, evidence_for

    entries = getattr(_artifact(), "entries", None) or {}
    assert entries, "the committed pricing artifact is EMPTY — A6 cannot "\
                    "be proven and must not report green"
    for identity in entries:
        entity = str(identity).split("|")[0]
        if evidence_for(entity, "") is not None:
            return entity
    raise AssertionError("no artifact identity yields evidence — A6's artifact "
                         "fixture cannot be built, and a skip would hide it")


def test_a6_the_artifact_decides_only_when_memory_is_absent():
    """⭐ THE FIXTURE FORCES THE ARTIFACT RATHER THAN BENDING PRECEDENCE:
    memory ABSENT, artifact PRESENT and ELIGIBLE, artifact must WIN."""
    from skills.nutrition.pricing_artifact import evidence_for

    entity = _an_artifact_identity()
    evidence = evidence_for(entity, "")
    priced = price(entity=entity, memory=None, artifact=evidence, consumed=None)
    assert priced.rung is Rung.ARTIFACT
    assert priced.evidence_id, "an artifact price with no evidence_id is not "\
                               "provenance — a matching calorie number is not "\
                               "provenance either (banana 210 = 2x105)"


def test_a6_memory_still_outranks_a_present_artifact():
    """⛔ AND PRECEDENCE IS NOT BENT TO SUIT A6. With BOTH present, memory wins
    — which is exactly why A6 had to be amended away from 'always report
    artifact'."""
    from skills.nutrition.pricing_artifact import evidence_for

    entity = _an_artifact_identity()
    priced = price(entity=entity,
                   memory=MemoryEvidence(per100g=PER100, source_id="ufm:9"),
                   artifact=evidence_for(entity, ""), consumed=None)
    assert priced.rung is Rung.MEMORY


def test_a6_an_estimate_says_estimate_and_never_borrows_the_artifact_name():
    priced = price(entity="Something uncovered",
                   estimate=EstimateEvidence(calories=200.0, protein=10.0,
                                             carbs=20.0, fat=5.0),
                   consumed=None)
    assert priced.rung is Rung.ESTIMATE
    assert priced.evidence_id == ""


def test_a6_the_owner_records_the_deciding_rung_for_persistence():
    """The owner must put the rung it ACTUALLY got into the attributes the
    writer persists — not the rung it expected."""
    source = inspect.getsource(GeneralSettlementOwner.settle)
    assert 'priced.analysis.rung.value' in source, (
        "the persisted rung must come from the analysis, never from the "
        "coverage prediction")
    assert '"expected_source"' in source, (
        "the PREDICTION is recorded alongside so expected and actual can be "
        "compared rather than reconciled")


def test_a6_the_writer_persists_pricing_provenance_only_when_recorded():
    """⚠ OMITTED RATHER THAN DEFAULTED. A caller that recorded no rung must not
    be reported as having priced from one — B-1 and quick_log see no change."""
    source = inspect.getsource(__import__("core.canonical_writer",
                                          fromlist=["_read_back"])._read_back)
    assert '"pricing": dict(pricing)' in source
    assert "if pricing else {}" in source


# ══ A8 — refusal is canonical, non-mutating, and does not fall back ═════════

def test_a8_a_food_with_no_evidence_refuses_rather_than_committing_a_number():
    with pytest.raises(PricingRefused):
        price(entity="Nothing at all", consumed=None)


def test_a8_a_zero_from_an_estimate_is_refused_not_committed():
    """⛔ ENTRY 2932 — Mackerel 80 g at 0.0 kcal. A zero from evidence is a
    fact; a zero from an estimate is a pricing failure wearing a number."""
    with pytest.raises(PricingRefused):
        price(entity="Mackerel",
              estimate=EstimateEvidence(calories=0.0, protein=0.0, carbs=0.0,
                                        fat=0.0), consumed=None)


def test_a8_the_owner_does_not_catch_pricing_refused():
    """⛔⛔ NO FALLBACK PAST ENTRY. Structural: neither `settle` nor `_price`
    may name `PricingRefused` in an except clause. Catching it to substitute a
    number is the failure being deleted; catching it to run legacy is the dual
    authority being prevented."""
    for function in (GeneralSettlementOwner.settle, GeneralSettlementOwner._price):
        tree = ast.parse(inspect.getsource(function).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                assert "PricingRefused" not in names, (
                    f"{function.__name__} catches PricingRefused")


def test_a8_the_native_stage_does_not_catch_around_settlement():
    """And the same at the seam: the stage's try/except covers the ROUTING
    decision only. An exception while deciding routes to legacy; an exception
    while settling propagates."""
    from core.turns.stages.execute_native import NativeExecutionStage

    run = ast.parse(inspect.getsource(NativeExecutionStage.run).lstrip()).body[0]
    handlers = [n for n in ast.walk(run) if isinstance(n, ast.ExceptHandler)]
    assert not handlers, (
        "NativeExecutionStage.run wraps settlement in an except — a canonical "
        "refusal could then reach the legacy executor")


# ══ A1 — one owner, and the routing that reaches it ═════════════════════════

def test_a1_the_owner_is_the_only_settlement_the_stage_invokes_when_supported():
    """The legacy executor import must sit AFTER the canonical branch returns,
    so a Supported turn cannot reach it at all."""
    from core.turns.stages.execute_native import NativeExecutionStage

    source = inspect.getsource(NativeExecutionStage.run)
    canonical = source.index("owner.settle")
    legacy = source.index("execute_tool_calls")
    assert canonical < legacy, (
        "the legacy executor is reachable before canonical settlement returns")
    # ⚠ THE PROPERTY, NOT THE STATEMENT. This pinned the literal
    # `return self._published()` and broke the moment the canonical branch
    # started returning its own execution view — a true change failing a gate
    # for a reason that had nothing to do with the contract. What A1 requires
    # is that the branch RETURNS before legacy is reachable, whatever it
    # returns.
    between = source[canonical:legacy]
    assert re.search(r"^\s+return\s+\S", between, re.M), (
        "canonical settlement does not return before the legacy executor — a "
        "supported turn could be settled twice")


def test_a1_the_chain_is_resolvedmeal_then_coordinator_then_writer():
    """⚠ ASKED OF THE CALLS, NOT OF THE TEXT. The first version indexed the raw
    source and read the IMPORT block as the call order — `commit_or_load_
    existing` appears at character 155 in an import and at 1073 as a call. The
    tree knows the difference."""
    tree = ast.parse(inspect.getsource(GeneralSettlementOwner.settle).lstrip())
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("ResolvedMeal", "commit_or_load_existing",
                        "write_canonical_meal"):
                order.append((node.lineno, node.col_offset, name))
    order.sort()
    sequence = [name for _, _, name in order]
    assert sequence.index("ResolvedMeal") < sequence.index(
        "commit_or_load_existing"), "the meal is built after it is committed"
    # The writer is INJECTED, so it is a Name in a keyword — not a call. Asked
    # of the keyword itself, which is the actual contract: the coordinator must
    # be handed the canonical writer and no other.
    writers = [kw.value for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and getattr(node.func, "id", None) == "commit_or_load_existing"
               for kw in node.keywords if kw.arg == "writer"]
    assert [getattr(w, "id", None) for w in writers] == ["write_canonical_meal"], (
        "the coordinator must be handed write_canonical_meal as its writer")


def test_a1_unsupported_never_enters_the_owner():
    """⛔ `Unsupported` reaches the UNTOUCHED legacy path — not a canonical
    attempt that falls back, and not a claim taken and released."""
    from core.turns.stages.execute_native import NativeExecutionStage

    source = inspect.getsource(NativeExecutionStage._canonical_route)
    assert "isinstance(coverage, Supported)" in source
    assert "return None" in source


def test_a1_corrections_are_not_this_slice():
    """`update_food_entry` and deletions route to legacy whole — canonical rows
    cannot be corrected through this path yet (B-1.8, §6)."""
    from core.turns.stages.execute_native import _food_inputs

    ops = [{"name": "log_food", "input": {"food_name": "x"}},
           {"name": "update_food_entry", "input": {}}]
    assert len(_food_inputs(ops)) == 1        # != len(ops), so routing declines


# ══ A3–A5 — quantity and preparation keys ═══════════════════════════════════

def test_a3_an_explicit_quantity_survives_settlement_unchanged():
    from skills.nutrition.normalize import normalize_quantity

    quantity = normalize_quantity("150 g", "Salmon")
    assert quantity.grams == 150.0
    priced = price(entity="Salmon",
                   memory=MemoryEvidence(per100g={"calories": 200.0,
                                                  "protein": 20.0,
                                                  "carbs": 0.0, "fat": 13.0}),
                   consumed=quantity)
    assert round(priced.calories) == 300        # 150 g of a 200/100 g basis


def test_a4_an_unstated_preparation_produces_the_bare_key():
    from skills.nutrition.pricing_artifact import split_identity

    entity, preparation = split_identity("Potato")
    assert (entity, preparation) == ("potato", "")


def test_a5_a_stated_preparation_produces_the_composed_key():
    from skills.nutrition.pricing_artifact import split_identity

    entity, preparation = split_identity("Chicken, fried")
    assert entity == "chicken" and preparation == "fried"
    # BOTH ROUTES REACH ONE KEY — the identity-boundary contract.
    assert split_identity("chicken, fried") == (entity, preparation)
