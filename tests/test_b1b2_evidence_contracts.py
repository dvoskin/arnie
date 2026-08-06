"""B-1.9 commit 2 — the typed quantity-evidence contracts.

Every gate the directive names, each asserted against the CONTRACT rather than
against a producer, because these types exist to be relied on by code that has
not been written yet.

The question they answer is not "what is this source called" but "what is this
evidence ABOUT, and can it speak for this person eating this thing" — the
distinction that decides whether "not sure" may commit at all.
"""
from decimal import Decimal

import pytest

from core.semantics import (CandidateSelectionDecision, CandidateSet,
                            CandidateSource, CanonicalQuantity,
                            ConversionEvidence, EstimateEvidence,
                            EvidenceScope, EVIDENCE_SCHEMA_VERSION,
                            QuantityCandidateEvidence, ServingBasis)


def _ev(**kw):
    base = dict(canonical_entity_id="food:chicken_breast",
                quantity=CanonicalQuantity(grams=Decimal("182")),
                serving_basis=ServingBasis.MASS,
                source_type=CandidateSource.USER_HISTORY,
                source_record_id="food_entry:2871",
                subject_scope=EvidenceScope.THIS_USER,
                subject_user_id=26)
    base.update(kw)
    return QuantityCandidateEvidence(**base)


# ── applicability is declared, never inferred from a name ───────────────────

def test_applicability_comes_from_scope_not_from_the_source_name():
    """CF-1. The source's NAME must not decide anything.

    The shipped stand-in matched `{"user_history", "catalog"}` as strings,
    which held only because those lanes happen to be entity-specific. Here the
    same source name appears with two different scopes and the answer follows
    the SCOPE both times — so a lane added tomorrow is judged on what it says
    its evidence is about.
    """
    mine = _ev(source_type=CandidateSource.USER_HISTORY,
               subject_scope=EvidenceScope.THIS_USER, subject_user_id=26)
    assert mine.authorizes_assumption

    # Same lane name, population scope: it may be offered, never assumed.
    general = _ev(source_type=CandidateSource.USER_HISTORY,
                  subject_scope=EvidenceScope.POPULATION,
                  subject_user_id=None)
    assert not general.authorizes_assumption

    # A lane whose name means nothing to us, but which declares its subject.
    product = _ev(source_type=CandidateSource.CATALOG,
                  subject_scope=EvidenceScope.THIS_PRODUCT,
                  subject_user_id=None, product_variant_id="off:5901234")
    assert product.authorizes_assumption

    ontology = _ev(source_type=CandidateSource.ONTOLOGY,
                   subject_scope=EvidenceScope.POPULATION, subject_user_id=None)
    assert not ontology.authorizes_assumption


def test_a_scope_without_its_subject_cannot_be_constructed():
    """A claim about "this user" that does not name one is not a claim."""
    with pytest.raises(ValueError, match="name the user"):
        _ev(subject_scope=EvidenceScope.THIS_USER, subject_user_id=None)
    with pytest.raises(ValueError, match="name the variant"):
        _ev(subject_scope=EvidenceScope.THIS_PRODUCT, subject_user_id=None,
            product_variant_id="")


# ── fail shut on anything we cannot interpret ───────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("serving_basis", "handfuls"),
    ("source_type", "vibes"),
    ("subject_scope", "everyone_ish"),
])
def test_an_unknown_enum_value_fails_shut(field, value):
    """A value we cannot interpret must not travel as though we could."""
    with pytest.raises(ValueError):
        _ev(**{field: value})


def test_an_unknown_evidence_version_fails_shut():
    """A record written under another contract is migrated, never guessed at."""
    with pytest.raises(ValueError, match="evidence_version"):
        _ev(evidence_version=EVIDENCE_SCHEMA_VERSION + 1)


def test_unauditable_evidence_cannot_be_constructed():
    with pytest.raises(ValueError, match="canonical entity"):
        _ev(canonical_entity_id="  ")
    with pytest.raises(ValueError, match="source record"):
        _ev(source_record_id="")


# ── conversions need an authority ───────────────────────────────────────────

def test_an_unsupported_conversion_cannot_be_constructed():
    """Inventing a density to make numbers comparable is how a portion the
    user never gave becomes one they are told they ate."""
    with pytest.raises(ValueError, match="licenses it"):
        ConversionEvidence(from_basis=ServingBasis.VOLUME,
                           to_basis=ServingBasis.MASS,
                           factor=Decimal("140"))
    ok = ConversionEvidence(from_basis=ServingBasis.VOLUME,
                            to_basis=ServingBasis.MASS,
                            source_record_id="usda:fdc:170379",
                            factor=Decimal("140"))
    assert ok.factor == Decimal("140")
    # No basis change needs no authority — nothing was asserted.
    assert ConversionEvidence(from_basis=ServingBasis.MASS,
                              to_basis=ServingBasis.MASS)


# ── persistence ─────────────────────────────────────────────────────────────

def test_every_contract_round_trips_as_its_concrete_type():
    ev = _ev(conversion_evidence=ConversionEvidence(
                 from_basis=ServingBasis.VOLUME, to_basis=ServingBasis.MASS,
                 source_record_id="usda:fdc:170379", factor=Decimal("140")),
             confidence=Decimal("0.9"), uncertainty_g=Decimal("12.5"))
    back = QuantityCandidateEvidence.from_payload(ev.to_payload())
    assert back == ev
    assert isinstance(back.serving_basis, ServingBasis)
    assert isinstance(back.subject_scope, EvidenceScope)
    assert isinstance(back.source_type, CandidateSource)
    assert isinstance(back.conversion_evidence, ConversionEvidence)

    cs = CandidateSet(field_id="f1", candidates=(ev,), generator_version="g1")
    assert CandidateSet.from_payload(cs.to_payload()) == cs

    d = CandidateSelectionDecision(
        field_id="f1", selected=(ev,),
        excluded=((_ev(subject_scope=EvidenceScope.POPULATION,
                       subject_user_id=None), "near-duplicate label"),),
        policy_version="sel_v1")
    assert CandidateSelectionDecision.from_payload(d.to_payload()) == d

    est = EstimateEvidence(chosen=ev, policy_version="estimate_evidence_v1",
                           considered=(ev,))
    assert EstimateEvidence.from_payload(est.to_payload()) == est


def test_decimals_survive_storage_exactly():
    """Through `str`, never `float`. A portion re-widened to binary spends its
    precision twice and stops comparing equal to itself."""
    ev = _ev(quantity=CanonicalQuantity(grams=Decimal("182.35")),
             confidence=Decimal("0.925"), uncertainty_g=Decimal("0.1"))
    back = QuantityCandidateEvidence.from_payload(ev.to_payload())
    assert back.quantity.grams == Decimal("182.35")
    assert back.confidence == Decimal("0.925")
    assert back.uncertainty_g == Decimal("0.1")
    assert str(back.confidence) == "0.925"


def test_a_caller_cannot_mutate_what_was_recorded():
    """The list a caller passed in stays theirs; ours is a copy."""
    mine = [_ev()]
    cs = CandidateSet(field_id="f1", candidates=mine)
    mine.append(_ev(canonical_entity_id="food:rice"))
    assert len(cs.candidates) == 1
    assert isinstance(cs.candidates, tuple)
    with pytest.raises(Exception):
        cs.candidates = ()          # frozen


# ── an assumption may not be built on a population prior ────────────────────

def test_estimate_evidence_refuses_a_population_prior():
    """The type itself forbids it, so no caller can assemble the failing case.

    A candidate justifies being OFFERED; this justifies being CHOSEN on the
    user's behalf. Holding the first while committing the second is exactly
    how "not sure" logged 435 g of chicken breast.
    """
    prior = _ev(source_type=CandidateSource.ONTOLOGY,
                subject_scope=EvidenceScope.POPULATION, subject_user_id=None)
    with pytest.raises(ValueError, match="cannot authorise an assumption"):
        EstimateEvidence(chosen=prior, policy_version="estimate_evidence_v1")


def test_a_decision_must_name_its_policy():
    ev = _ev()
    with pytest.raises(ValueError, match="policy version"):
        CandidateSelectionDecision(field_id="f1", selected=(ev,))
    with pytest.raises(ValueError, match="policy"):
        EstimateEvidence(chosen=ev, policy_version="")


def test_an_exclusion_carries_its_reason():
    """"Why wasn't my usual portion there?" is a question the pipeline has to
    be able to answer about itself."""
    kept, dropped = _ev(), _ev(canonical_entity_id="food:rice")
    d = CandidateSelectionDecision(
        field_id="f1", selected=(kept,),
        excluded=((dropped, "collapsed: same label as a stronger candidate"),),
        policy_version="sel_v1")
    (_, reason), = d.excluded
    assert "collapsed" in reason
