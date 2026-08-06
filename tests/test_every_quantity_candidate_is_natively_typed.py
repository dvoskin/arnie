"""B-1.9 commit 4 — the compatibility bridges are gone, and stay gone.

Three of these are SOURCE SCANS rather than behavioural tests, deliberately.
The defect being prevented is a REAPPEARING BRIDGE — a second path that
behaves identically to the canonical one until the day it diverges. Nothing
observable distinguishes them in the meantime, so nothing observable can catch
them; only the code can.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION = ("core", "skills", "handlers", "api", "db")


def _production_files():
    for root in PRODUCTION:
        for path in (REPO / root).rglob("*.py"):
            yield path


def test_the_legacy_source_scope_bridge_is_deleted():
    """A source NAME decided applicability while producers were migrated.

    It worked only because the lanes it named happened to be entity-specific,
    and it would have drifted the moment a lane was added whose name says
    nothing about what its evidence is ABOUT. Every production producer emits
    typed candidates now, so the bridge is deleted rather than left as a path
    that could quietly become load-bearing again.
    """
    offenders = [str(p.relative_to(REPO)) for p in _production_files()
                 if "_LEGACY_SOURCE_SCOPE" in p.read_text()]
    assert not offenders, (
        f"the source-name bridge is back in {offenders} — applicability is a "
        f"property of the evidence, never of the lane's name")


def test_no_production_caller_uses_the_compatibility_shims():
    """`candidates()` and `select()` survive for offline tooling and proofs.

    The ASK PATH must not use them: they invent a placeholder operation, a
    placeholder field and an unpersisted set, so an ask built through them
    would have no durable universe behind it — a question nothing can explain,
    which is the state the whole slice removes.
    """
    pattern = re.compile(r"\bqc\.(candidates|select)\s*\(|"
                         r"quantity_clarification\.(candidates|select)\s*\(")
    offenders = []
    for path in _production_files():
        if path.name == "quantity_clarification.py":
            continue          # defines them
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}  {line.strip()}")
    assert not offenders, (
        "production reached a compatibility shim:\n  " + "\n  ".join(offenders))


def test_generation_and_reduction_have_one_production_entry_each():
    """`generate()` is the only way a universe is built and
    `reduce_universe()` the only way one is reduced — so every ask has a
    durable record, by construction rather than by review."""
    from core import b1_quantity_operation as b1

    source = (REPO / "core" / "b1_quantity_operation.py").read_text()
    assert "qc.generate(" in source
    assert "qc.reduce_universe(" in source
    assert "qc.candidates(" not in source
    assert "qc.select(" not in source
    assert b1.DOMAIN == "food"


@pytest.mark.parametrize("attribute", ["candidate_id", "candidate_set_id"])
def test_an_option_carries_its_provenance_across_the_wire(attribute):
    """The typed candidate stays in memory; the IDS travel.

    A client receives identifiers and labels, never semantics it could
    reinterpret — and the ids are what let the answer turn resolve the
    justification back out of the persisted universe.
    """
    from core.semantics import ClarificationOption

    option = ClarificationOption(label="6 oz", option_id="opt_1",
                                 candidate_id="cand_x",
                                 candidate_set_id="cs_x")
    payload = option.to_payload()
    assert payload[attribute]
    assert "candidate" not in payload, (
        "the typed candidate must not travel; a client could reinterpret it")
    assert ClarificationOption.from_payload(payload).candidate is None


def test_every_production_candidate_is_natively_typed():
    """The generator emits `QuantityCandidate` and nothing else.

    Checked on the real producer rather than on a fixture: every candidate
    carries typed evidence with an explicit scope and subject, a versioned
    source, and a serving expression that can be rendered without the
    renderer reinventing it.
    """
    import asyncio

    from core.semantics import (EvidenceContext, EvidenceScope,
                                QuantityCandidate, ServingExpression)
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                          StagedFoodItem)

    item = StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some")
    universe = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        qc.generate(None, user_id=26, item=item, message="some chicken breast",
                    operation_id="op_x", revision=0, field_id="f_x",
                    context=EvidenceContext(
                        user_id=26,
                        canonical_entity_id=qc._entity_id_for(item))))

    assert universe.candidates, "the ontology produced nothing to check"
    for cand in universe.candidates:
        assert isinstance(cand, QuantityCandidate)
        assert isinstance(cand.offered, ServingExpression)
        assert cand.semantic_hash and cand.prior is not None
        for ev in cand.evidence:
            assert isinstance(ev.subject_scope, EvidenceScope)
            # A VERSIONED, AUDITABLE SOURCE. A bare key is not an identity
            # when the thing it names can change.
            assert ev.source.dataset_id and ev.source.dataset_version
            assert ev.source.record_version or ev.source.immutable_within_version
            assert ev.observed_quantity is not None
            if ev.subject_scope is EvidenceScope.THIS_USER:
                assert ev.subject_user_id
            if ev.conversion_evidence is not None:
                assert ev.conversion_evidence.source is not None


def test_an_option_without_a_candidate_cannot_authorise_an_assumption():
    """FAIL SHUT. An option reaching the estimate path with no typed candidate
    is a producer that was never migrated, and guessing on its behalf is the
    defect CF-1 removed."""
    from core.clarification_answer import _authorizes_assumption
    from core.semantics import CandidateSource, ClarificationOption, EvidenceContext

    bare = ClarificationOption(label="6 oz", option_id="opt_1",
                               source=CandidateSource.USER_HISTORY)
    assert not _authorizes_assumption(
        bare, EvidenceContext(user_id=26, canonical_entity_id="food:x"))
    assert not _authorizes_assumption(bare, None)
