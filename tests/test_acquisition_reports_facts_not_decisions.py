"""ACQUIRE may establish evidence. It may never establish a verdict.

⛔⛔⛔ THE PRODUCER-FAITHFUL COUNTERFACTUAL ALREADY MADE THIS MISTAKE, in a
script, and published two wrong conclusions off it ("evidence recovers 0
meals", then "scaling is the lever") before the flipped booleans were found.
Both were artifacts of SETTING outcomes that `decide()` is supposed to derive.
Danny's directive names the same failure prospectively:

    "Do not have ACQUIRE() set supported=True, authoritative=True, or
     otherwise bypass decide(). That is the same counterfactual mistake
     already caught experimentally."

So the guard is structural and it is checked three ways — by NAME over the
dataclass fields, by CONSTRUCTION when a decision field is added in good faith,
and by AST over the module's imports. A grep would check spelling; these check
structure.
"""
import ast
import pathlib
from dataclasses import dataclass, fields

import pytest

from skills.nutrition import acquisition as acq

_SRC = pathlib.Path(acq.__file__)


def test_no_field_of_the_contract_is_a_decision():
    """Reflective, so a field added later is covered without editing this test."""
    banned = ("supported", "authoritative", "priced", "settled", "owned",
              "covered", "eligible", "admissible", "approved")
    for f in fields(acq.AcquiredEvidence):
        low = f.name.lower()
        assert not low.startswith("has_"), f"{f.name} is a decide() gate name"
        assert not low.startswith("is_"), f"{f.name} is a predicate, not a fact"
        for b in banned:
            assert b not in low, f"{f.name} names the verdict {b!r}"


def test_adding_a_decision_field_in_good_faith_is_refused_at_construction():
    """The name check runs in __post_init__, so it binds SUBCLASSES too.

    ⭐ This is the case review would miss: nobody adds `supported` to a class
    whose docstring forbids it. They add it to a subclass, six weeks later,
    because one call site needed to remember something.
    """

    @dataclass(frozen=True)
    class WithAVerdict(acq.AcquiredEvidence):
        selected_rung_authoritative: bool = True

    with pytest.raises(TypeError, match="names a DECISION"):
        WithAVerdict(canonical_identity="cod|", identity_evidence={},
                     nutrition_evidence=({"evidence_id": "usda:1"},),
                     source_type="usda", source_identifier="1",
                     authority_grade=acq.SOURCED_COMPOSITION,
                     nutrition_basis="per_100g", serving_basis=(),
                     quantity_compatibility=frozenset(), provenance={})


@pytest.mark.parametrize("field_name,clause", [
    # ⛔⛔ THE THREE CLAUSES OF THE GUARD, PROVEN INDEPENDENTLY. The first
    # version of this file tested only the third: `selected_rung_authoritative`
    # trips the substring list, so disarming `startswith("has_")` left all six
    # tests GREEN. Reachable, but not observable — the mutation was invisible
    # because the TEST SET was too narrow, not because the guard was sound.
    #
    # ⭐ AND THE UNPROVEN CLAUSE WAS THE LOAD-BEARING ONE. `has_quantity`,
    # `has_artifact`, `has_identity`, `has_memory` are the literal gate names
    # in `decide()` — the exact fields someone would add — and not one of them
    # contains a banned substring. Only `startswith("has_")` stops them.
    ("has_quantity", "has_"),
    ("has_artifact", "has_"),
    ("has_identity", "has_"),
    ("has_memory", "has_"),
    ("is_priceable", "is_"),
    ("is_supported", "is_"),
    ("selected_rung_authoritative", "substring"),
    ("meal_is_covered", "substring"),
])
def test_each_clause_of_the_decision_guard_refuses_its_own_names(field_name, clause):
    """One case per clause, so disarming any single clause turns this RED."""
    ns = {"__annotations__": {field_name: bool}, field_name: True}
    subclass = dataclass(frozen=True)(
        type("Added", (acq.AcquiredEvidence,), ns))
    with pytest.raises(TypeError, match="names a DECISION"):
        subclass(canonical_identity="cod|", identity_evidence={},
                 nutrition_evidence=({"evidence_id": "usda:1"},),
                 source_type="usda", source_identifier="1",
                 authority_grade=acq.SOURCED_COMPOSITION,
                 nutrition_basis="per_100g", serving_basis=(),
                 quantity_compatibility=frozenset(), provenance={})


def test_acquisition_cannot_reach_the_settlement_gates():
    """AST over imports: the module may not name `decide` or its verdicts.

    ⛔ THE ONLY CHANNEL FROM ACQUISITION TO SETTLEMENT IS PERSISTED EVIDENCE.
    If this module could import `Supported`, it could return one — and the
    ladder that makes canonical trustworthy would have a second entrance.
    """
    tree = ast.parse(_SRC.read_text())
    forbidden = {"decide", "Supported", "Unsupported", "ItemFacts",
                 "coverage_for", "BoundUnpriceable"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "general_settlement" not in (node.module or ""), \
                "acquisition imported the settlement module"
            for alias in node.names:
                assert alias.name not in forbidden, \
                    f"acquisition imported the verdict {alias.name!r}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "general_settlement" not in alias.name


def test_a_legacy_estimate_cannot_be_given_an_authority_grade():
    """⛔⛔ THE FAILURE THAT WOULD DESTROY THE METRIC QUIETLY.

        legacy estimated 487 calories -> write artifact -> now "canonical"

    Ownership climbs, authority is gone, and the number measures its own
    contamination. The vocabulary is closed so the row cannot be written.
    """
    for laundered in ("estimate", "web", "model", "heuristic", "interpreter",
                      "legacy", ""):
        assert laundered not in acq.ADMISSIBLE_GRADES
        with pytest.raises(acq.AcquisitionRefused) as e:
            acq.AcquiredEvidence(
                canonical_identity="chicken breast|",
                identity_evidence={"note": "the interpreter said 487 kcal"},
                nutrition_evidence=({"calories": 487.0},),
                source_type="interpreter", source_identifier="turn-1",
                authority_grade=laundered, nutrition_basis="per_100g",
                serving_basis=(), quantity_compatibility=frozenset(),
                provenance={})
        assert e.value.reason == acq.GRADE_INADMISSIBLE


def test_an_entry_with_no_candidate_is_a_refusal_not_an_empty_success():
    """A hit at the rung that prices nothing is worse than a miss."""
    with pytest.raises(acq.AcquisitionRefused) as e:
        acq.AcquiredEvidence(
            canonical_identity="гречка|", identity_evidence={},
            nutrition_evidence=(), source_type="usda", source_identifier="0",
            authority_grade=acq.SOURCED_COMPOSITION, nutrition_basis="per_100g",
            serving_basis=(), quantity_compatibility=frozenset(), provenance={})
    assert e.value.reason == acq.IDENTITY_UNQUALIFIED


def test_every_refusal_reason_is_named_and_countable():
    """⭐ A refusal you can COUNT is how the next tranche learns which adapter
    to build. `return None` produces a miss indistinguishable from never trying.
    """
    reasons = {acq.NO_IDENTITY, acq.NO_SOURCE_RECORD, acq.IDENTITY_UNQUALIFIED,
               acq.GRADE_INADMISSIBLE, acq.BASIS_UNUSABLE,
               acq.PROVIDER_UNAVAILABLE}
    assert len(reasons) == 6, "reasons collided — a count would merge outcomes"
    for r in reasons:
        assert r.startswith("ACQUIRE_") and r.isupper()
