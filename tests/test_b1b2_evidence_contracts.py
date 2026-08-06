"""B-1.9 commits 2–3a — the typed candidate and evidence contracts.

Every gate the directive names, each asserted against the CONTRACT rather than
against a producer, because these types exist to be relied on by code that has
not been written yet.

The question they answer is not "what is this source called" but "what is this
evidence ABOUT, and can it speak for this person eating this thing" — the
distinction that decides whether "not sure" may commit at all.

COMMIT 3a MOVED THE BOUNDARY. A candidate and its evidence are different
things: one candidate may be supported by exact user history AND package
metadata AND a canonical serving record. Identity therefore lives on the
candidate and evidence describes only why the candidate exists and what its
source observed. The gates below enforce that split, because a shape that
implies one-candidate-one-source has to be undone the moment two sources
agree.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.semantics import (CandidateDecisionRecord, CandidateExclusion,
                            CandidateGenerationRejection,
                            CandidateSelectionContext,
                            CandidateSelectionDecision, CandidateSet,
                            CandidateSource, CanonicalQuantity,
                            ConversionEvidence, EstimateEvidence,
                            EvidenceContext, EvidenceScope,
                            EVIDENCE_SCHEMA_VERSION, ExclusionReason,
                            GenerationRejectionReason, QuantityCandidate,
                            QuantityCandidateEvidence, SelectionSurface,
                            ServingBasis, SourceReference)

CTX = EvidenceContext(user_id=26, canonical_entity_id="food:chicken_breast")

SRC = SourceReference(dataset_id="food_entries", dataset_version="live",
                      record_key="2871", record_version="ledger:88121")


def _ev(**kw):
    """One evidence record. Observes 182 g of mass, about user 26."""
    base = dict(source_type=CandidateSource.USER_HISTORY,
                source=SRC,
                observed_quantity=CanonicalQuantity(grams=Decimal("182")),
                observed_basis=ServingBasis.MASS,
                subject_scope=EvidenceScope.THIS_USER,
                subject_user_id=26,
                observed_at=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))
    base.update(kw)
    return QuantityCandidateEvidence(**base)


def _cand(**kw):
    """One candidate offering 182 g, supported by one history record."""
    base = dict(candidate_id="c1",
                canonical_entity_id="food:chicken_breast",
                quantity=CanonicalQuantity(grams=Decimal("182")),
                serving_basis=ServingBasis.MASS,
                evidence=(_ev(),))
    base.update(kw)
    return QuantityCandidate(**base)


def _prod_ev(**kw):
    """A catalog record about a specific variant's declared serving.

    Expressed in `standard_serving` because THIS_PRODUCT_QUANTITY requires a
    basis that denotes an amount — the commit-2 rule that keeps identity from
    passing as consumption.
    """
    base = dict(source_type=CandidateSource.CATALOG,
                source=SourceReference(dataset_id="catalog",
                                       dataset_version="2026-07",
                                       record_key="sku:991"),
                observed_quantity=CanonicalQuantity(grams=Decimal("182")),
                observed_basis=ServingBasis.STANDARD_SERVING,
                subject_scope=EvidenceScope.THIS_PRODUCT_QUANTITY,
                subject_user_id=None, product_variant_id="sku:991")
    base.update(kw)
    return QuantityCandidateEvidence(**base)


def _prod_cand(**kw):
    base = dict(serving_basis=ServingBasis.STANDARD_SERVING,
                evidence=(_prod_ev(),))
    base.update(kw)
    return _cand(**base)


def _set(**kw):
    base = dict(candidate_set_id="cs1", operation_id="op1", user_id=26,
                interaction_revision=0, field_id="f1",
                generator_version="gen_v1",
                generation_input_fingerprint="fp1",
                candidates=(_cand(),))
    base.update(kw)
    return CandidateSet(**base)


SEL_CTX = CandidateSelectionContext(surface=SelectionSurface.LABEL_TEXT,
                                    locale="en", maximum_options=3,
                                    renderer_contract_version="labels_v1")


def _decision(**kw):
    base = dict(candidate_set_id="cs1", selection_policy_version="sel_v1",
                context=SEL_CTX, selected_candidate_ids=("c1",))
    base.update(kw)
    return CandidateSelectionDecision(**base)


# ── the candidate owns identity; evidence explains it ───────────────────────

def test_one_candidate_may_be_supported_by_several_sources():
    """THE WHOLE POINT OF THE 3a BOUNDARY.

    History and a package panel agreeing on 182 g is ONE offered amount with
    two justifications, not two candidates. If identity lived on the evidence
    this could not be expressed without either duplicating the option or
    discarding a source — and discarding provenance to make the model fit is
    how "why was this offered?" stops being answerable.
    """
    cand = _prod_cand(evidence=(
        _ev(observed_basis=ServingBasis.STANDARD_SERVING),
        _prod_ev()))
    assert len(cand.evidence) == 2
    assert {e.source_type for e in cand.evidence} == {
        CandidateSource.USER_HISTORY, CandidateSource.CATALOG}
    # Still one candidate, one id, one offered quantity.
    assert cand.candidate_id == "c1"
    assert cand.quantity.grams == Decimal("182")


def test_a_candidate_must_carry_at_least_one_reason():
    """A quantity offered for no recorded reason is what this all prevents."""
    with pytest.raises(ValueError, match="no evidence"):
        _cand(evidence=())


def test_the_candidate_owns_the_offered_amount():
    """OWNERSHIP MUST BE UNAMBIGUOUS.

    Candidate 21 g citing evidence that observed 30 g, on the same basis, with
    nothing explaining the gap: two objects claiming the same fact and no
    defined authority between them. The record would look complete and mean
    nothing.
    """
    with pytest.raises(ValueError, match="no authority"):
        _cand(quantity=CanonicalQuantity(grams=Decimal("21")),
              evidence=(_ev(observed_quantity=CanonicalQuantity(
                  grams=Decimal("30"))),))

    # Agreeing on the same basis is fine.
    ok = _cand(quantity=CanonicalQuantity(grams=Decimal("30")),
               evidence=(_ev(observed_quantity=CanonicalQuantity(
                   grams=Decimal("30"))),))
    assert ok.quantity.grams == Decimal("30")


def test_crossing_bases_requires_a_sourced_conversion():
    """Evidence observed in volume cannot support a mass candidate alone.

    Not a formatting difference — it is the step where an invented density
    becomes a calorie. The conversion must exist, and must start from what the
    evidence actually saw.
    """
    volume = _ev(observed_basis=ServingBasis.VOLUME,
                 observed_quantity=CanonicalQuantity(
                     milliliters=Decimal("240")))
    with pytest.raises(ValueError, match="nobody's authority"):
        _cand(evidence=(volume,))

    conv = ConversionEvidence(from_basis=ServingBasis.VOLUME,
                              to_basis=ServingBasis.MASS,
                              source_record_id="usda:density:5062",
                              factor=Decimal("0.758"))
    assert _cand(evidence=(_ev(observed_basis=ServingBasis.VOLUME,
                               observed_quantity=CanonicalQuantity(
                                   milliliters=Decimal("240")),
                               conversion_evidence=conv),)).evidence

    # A conversion that starts somewhere the evidence never was.
    wrong_start = ConversionEvidence(from_basis=ServingBasis.PIECE,
                                     to_basis=ServingBasis.MASS,
                                     source_record_id="usda:piece:1",
                                     factor=Decimal("174"))
    with pytest.raises(ValueError, match="did not see"):
        _cand(evidence=(_ev(observed_basis=ServingBasis.VOLUME,
                            observed_quantity=CanonicalQuantity(
                                milliliters=Decimal("240")),
                            conversion_evidence=wrong_start),))


def test_a_conversion_must_land_on_this_candidates_basis():
    """A volume candidate carrying a piece-to-mass row proves nothing about
    itself, and must not pass construction by looking well-sourced."""
    conv = ConversionEvidence(from_basis=ServingBasis.PIECE,
                              to_basis=ServingBasis.MASS,
                              source_record_id="usda:piece_weight:1",
                              factor=Decimal("174"))
    with pytest.raises(ValueError, match="does not land"):
        _cand(serving_basis=ServingBasis.VOLUME,
              quantity=CanonicalQuantity(milliliters=Decimal("240")),
              evidence=(_ev(observed_basis=ServingBasis.VOLUME,
                            observed_quantity=CanonicalQuantity(
                                milliliters=Decimal("240")),
                            conversion_evidence=conv),))


# ── applicability is declared, never inferred from a name ───────────────────

def test_applicability_comes_from_scope_not_from_the_source_name():
    """CF-1. The source's NAME must not decide anything.

    The shipped stand-in matched `{"user_history", "catalog"}` as strings,
    which held only because those lanes happen to be entity-specific. Here the
    same source name appears with two different scopes and the answer follows
    the SCOPE both times — so a lane added tomorrow is judged on what it says
    its evidence is about.
    """
    assert _cand().authorizes_assumption(CTX)

    general = _cand(evidence=(_ev(source_type=CandidateSource.USER_HISTORY,
                                  subject_scope=EvidenceScope.POPULATION,
                                  subject_user_id=None),))
    assert not general.authorizes_assumption(CTX)

    product = _prod_cand()
    assert product.authorizes_assumption(
        EvidenceContext(user_id=26,
                        canonical_entity_id="food:chicken_breast",
                        product_variant_id="sku:991"))


def test_one_sufficient_record_authorizes_and_population_neither_helps_nor_dilutes():
    """A candidate is authorised if ANY of its evidence is sufficient alone.

    Two population records do not add up to one user record, and a population
    record sitting beside a matching user record does not weaken it. Both
    directions matter: the first is how a generic prior would sneak in, the
    second would make richer provenance reduce what we may do with it.
    """
    pop = _ev(subject_scope=EvidenceScope.POPULATION, subject_user_id=None)
    assert not _cand(evidence=(pop, pop)).authorizes_assumption(CTX)
    assert _cand(evidence=(pop, _ev(), pop)).authorizes_assumption(CTX)


def test_evidence_about_another_user_cannot_authorize():
    """THE P0 FROM COMMIT 2. Scope was checked; the subject never was."""
    mine = _cand()
    assert mine.authorizes_assumption(CTX)
    assert not mine.authorizes_assumption(
        EvidenceContext(user_id=456,
                        canonical_entity_id="food:chicken_breast"))


def test_evidence_about_another_entity_cannot_authorize():
    """Evidence about rice says nothing about salmon, however well-sourced."""
    assert not _cand().authorizes_assumption(
        EvidenceContext(user_id=26, canonical_entity_id="food:salmon"))


def test_product_evidence_matches_the_selected_variant():
    cand = _prod_cand()
    assert not cand.authorizes_assumption(
        EvidenceContext(user_id=26,
                        canonical_entity_id="food:chicken_breast",
                        product_variant_id="sku:000"))
    assert not cand.authorizes_assumption(CTX)      # no variant selected


def test_identifying_a_product_is_not_knowing_how_much_was_eaten():
    """THIS_PRODUCT_QUANTITY needs a basis that denotes an amount.

    Knowing a jar is Brand X honey does not establish that three tablespoons
    were eaten. Without this, future product metadata could authorise a
    default merely by recognising the item.
    """
    with pytest.raises(ValueError, match="without stating an amount"):
        _cand(serving_basis=ServingBasis.PIECE,
              evidence=(_prod_ev(observed_basis=ServingBasis.PIECE),))
    assert _prod_cand()


def test_population_evidence_never_authorizes_at_any_confidence():
    hot = _ev(subject_scope=EvidenceScope.POPULATION, subject_user_id=None,
              confidence=Decimal("0.999"))
    assert not _cand(evidence=(hot,)).authorizes_assumption(CTX)


def test_a_scope_without_its_subject_cannot_be_constructed():
    with pytest.raises(ValueError, match="claim without a claimant"):
        _ev(subject_scope=EvidenceScope.THIS_USER, subject_user_id=None)
    with pytest.raises(ValueError, match="must name the variant"):
        _ev(subject_scope=EvidenceScope.THIS_PRODUCT_QUANTITY,
            subject_user_id=None, product_variant_id="")


# ── fail shut on anything uninterpretable ───────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("observed_basis", "handfuls"),
    ("source_type", "vibes"),
    ("subject_scope", "everyone_ish"),
])
def test_an_unknown_enum_value_fails_shut(field, value):
    with pytest.raises(ValueError):
        _ev(**{field: value})


def test_an_unknown_evidence_version_fails_shut():
    with pytest.raises(ValueError, match="must be migrated"):
        _ev(evidence_version=EVIDENCE_SCHEMA_VERSION + 1)


def test_a_source_reference_must_be_auditable():
    """A key alone is not an identity when the thing it names can change.

    `portion:chicken_breast:large` can mean 174 g today and 190 g after a
    refresh; two incomparable claims would present as one.
    """
    for missing in ("dataset_id", "dataset_version", "record_key"):
        with pytest.raises(ValueError, match=missing):
            SourceReference(**{**dict(dataset_id="d", dataset_version="v",
                                      record_key="k"), missing: ""})


def test_evidence_snapshots_what_the_source_said():
    """A row id alone cannot explain a candidate after the row is corrected.

    The observed value travels with the evidence so the system can still say
    "candidate X existed because event Y contained 182 g at the time".
    """
    ev = _ev()
    assert ev.observed_quantity.grams == Decimal("182")
    assert ev.observed_at is not None
    assert ev.source.record_version == "ledger:88121"
    back = QuantityCandidateEvidence.from_payload(ev.to_payload())
    assert back.observed_quantity.grams == Decimal("182")
    assert back.observed_at == ev.observed_at


# ── construction is keyword-only ────────────────────────────────────────────

@pytest.mark.parametrize("cls,args", [
    (QuantityCandidate, ("c1", "food:x")),
    (CandidateSet, ("cs1", "op1")),
    (CandidateExclusion, ("c1", ExclusionReason.SELECTION_CAP)),
    (CandidateSelectionDecision, ("cs1", "v1")),
    (CandidateDecisionRecord, (None, None)),
    (CandidateSelectionContext, (SelectionSurface.LABEL_TEXT, "en")),
    (SourceReference, ("d", "v")),
])
def test_the_new_contracts_are_keyword_only(cls, args):
    """POSITIONAL CONSTRUCTION IS A TRAP HERE.

    These records grow fields as the slice does, and a positional call
    silently reinterprets an old argument as a new field. Keyword-only turns
    that class of mistake into an import-time error.
    """
    with pytest.raises(TypeError):
        cls(*args)


# ── the set is the universe; the decision reduces it ────────────────────────

def test_a_candidate_set_names_its_generator_user_and_inputs():
    for missing, match in (("generator_version", "generator"),
                           ("generation_input_fingerprint", "fingerprint"),
                           ("candidate_set_id", "candidate_set_id")):
        with pytest.raises(ValueError, match=match):
            _set(**{missing: ""})
    with pytest.raises(ValueError, match="must name the user"):
        _set(user_id=0)


def test_candidate_ids_are_unique_within_a_set():
    """Two candidates sharing an id is an unresolvable reference: every later
    question about the option has two answers."""
    with pytest.raises(ValueError, match="must be unique"):
        _set(candidates=(_cand(), _cand()))


def test_selection_is_reproducible_only_with_its_context():
    """A policy version alone does not determine the outcome.

    The same universe under the same policy yields three text options on
    Telegram and five structured ones on iOS. Without the context, two
    decisions that legitimately differ look like a policy that changed
    underneath us.
    """
    d = _decision()
    assert d.context.surface is SelectionSurface.LABEL_TEXT
    assert d.context.maximum_options == 3
    assert d.context.renderer_contract_version == "labels_v1"
    with pytest.raises(ValueError, match="never produce an option"):
        CandidateSelectionContext(surface=SelectionSurface.LABEL_TEXT,
                                  locale="en", maximum_options=0,
                                  renderer_contract_version="labels_v1")
    with pytest.raises(ValueError, match="renderer_contract_version"):
        CandidateSelectionContext(surface=SelectionSurface.LABEL_TEXT,
                                  locale="en", maximum_options=3,
                                  renderer_contract_version="")


def test_selected_order_is_data_and_survives_storage():
    """Order decides which option is first, and therefore prominence and
    selection rates. It must not be recovered from insertion order."""
    d = _decision(selected_candidate_ids=("c3", "c1", "c2"))
    assert d.selected_candidate_ids == ("c3", "c1", "c2")
    assert CandidateSelectionDecision.from_payload(
        d.to_payload()).selected_candidate_ids == ("c3", "c1", "c2")


def test_a_candidate_has_exactly_one_terminal_status():
    with pytest.raises(ValueError, match="selected twice"):
        _decision(selected_candidate_ids=("c1", "c1"))
    with pytest.raises(ValueError, match="excluded twice"):
        _decision(selected_candidate_ids=(),
                  exclusions=(CandidateExclusion(
                      candidate_id="c1",
                      reason=ExclusionReason.SELECTION_CAP),) * 2)
    with pytest.raises(ValueError, match="selected and excluded at once"):
        _decision(selected_candidate_ids=("c1",),
                  exclusions=(CandidateExclusion(
                      candidate_id="c1",
                      reason=ExclusionReason.SEMANTIC_DUPLICATE),))


def test_a_decision_cannot_exceed_the_slots_its_context_allowed():
    with pytest.raises(ValueError, match="context allowed"):
        _decision(selected_candidate_ids=("c1", "c2", "c3", "c4"))


def test_a_decision_must_name_its_policy_and_its_set():
    with pytest.raises(ValueError, match="policy version"):
        _decision(selection_policy_version="")
    with pytest.raises(ValueError, match="must name the candidate set"):
        _decision(candidate_set_id="")


def test_an_exclusion_reason_is_closed():
    """Prose reasons fragment the population: the same cause arrives spelled
    four ways and nothing can be counted."""
    with pytest.raises(ValueError):
        CandidateExclusion(candidate_id="c1", reason="it looked wrong")
    ok = CandidateExclusion(candidate_id="c1",
                            reason=ExclusionReason.RENDER_COLLISION)
    assert ok.reason is ExclusionReason.RENDER_COLLISION


def test_there_is_no_generic_exclusion_reason():
    """"Not selected" restates the fact already recorded and answers nothing.

    Every member must name a real policy branch, so that analysis can say WHY
    the user's expected candidate disappeared.
    """
    names = {r.value for r in ExclusionReason}
    assert names == {"semantic_duplicate", "render_collision", "selection_cap"}


def test_a_label_collision_is_named_as_a_rendering_outcome():
    """A label is presentation, not meaning.

    Two candidates can be semantically distinct and still collide in English
    while differing in another locale. Recording that as a semantic duplicate
    would assert they meant the same thing when they did not.
    """
    assert ExclusionReason.RENDER_COLLISION.value == "render_collision"
    assert not hasattr(ExclusionReason, "DUPLICATE_LABEL")


# ── the partition: nothing vanishes, nothing is invented ────────────────────

def test_every_generated_candidate_is_selected_or_excluded():
    """THE LOAD-BEARING GATE.

    Without it, "history never appeared" reads identically whether the matcher
    found nothing or the selector dropped it — different engineering problems
    that one number would hide.
    """
    two = _set(candidates=(_cand(), _cand(candidate_id="c2")))
    with pytest.raises(ValueError, match="neither selected nor excluded"):
        CandidateDecisionRecord(candidate_set=two, decision=_decision())

    rec = CandidateDecisionRecord(
        candidate_set=two,
        decision=_decision(selected_candidate_ids=("c1",),
                           exclusions=(CandidateExclusion(
                               candidate_id="c2",
                               reason=ExclusionReason.SEMANTIC_DUPLICATE),)))
    assert rec.selected[0].candidate_id == "c1"
    assert rec.decision.excluded_candidate_ids == {"c2"}


def test_a_decision_cannot_reference_a_candidate_that_was_never_generated():
    with pytest.raises(ValueError, match="never generated"):
        CandidateDecisionRecord(
            candidate_set=_set(),
            decision=_decision(selected_candidate_ids=("c1", "ghost")))


def test_a_decision_belongs_to_the_set_it_reduced():
    with pytest.raises(ValueError, match="explains nothing about this one"):
        CandidateDecisionRecord(candidate_set=_set(),
                                decision=_decision(candidate_set_id="other"))


def test_selected_resolves_to_candidates_in_shown_order():
    two = _set(candidates=(_cand(), _cand(candidate_id="c2")))
    rec = CandidateDecisionRecord(
        candidate_set=two,
        decision=_decision(selected_candidate_ids=("c2", "c1")))
    assert [c.candidate_id for c in rec.selected] == ["c2", "c1"]
    assert rec.operation_id == "op1" and rec.user_id == 26 and rec.revision == 0


# ── generation failures are not selection decisions ─────────────────────────

def test_an_unusable_input_is_a_rejection_not_an_exclusion():
    """Point 10. Forcing invalid data into the universe to account for it
    would mean constructing invalid candidates just to mark them excluded —
    defeating the construction-time gates and corrupting the denominator of
    every selection metric.

    It also separates two retrieval outcomes that otherwise look identical:
    "found nothing" and "found a row that could not be used".
    """
    rej = CandidateGenerationRejection(
        producer=CandidateSource.USER_HISTORY,
        source_record_key="food_entry:9",
        reason=GenerationRejectionReason.NO_QUANTITY,
        generator_version="gen_v1")
    s = _set(rejections=(rej,))
    # A rejection is NOT a universe member: the partition ignores it.
    rec = CandidateDecisionRecord(candidate_set=s, decision=_decision())
    assert rec.candidate_set.rejections[0].reason is (
        GenerationRejectionReason.NO_QUANTITY)
    assert rec.candidate_set.candidate_ids == {"c1"}
    assert CandidateSet.from_payload(s.to_payload()).rejections[0].reason is (
        GenerationRejectionReason.NO_QUANTITY)


def test_a_rejection_reason_is_closed_too():
    with pytest.raises(ValueError):
        CandidateGenerationRejection(producer=CandidateSource.ONTOLOGY,
                                     source_record_key="k",
                                     reason="dunno",
                                     generator_version="gen_v1")


# ── storage fidelity ────────────────────────────────────────────────────────

def test_every_contract_round_trips_as_its_concrete_type():
    rec = CandidateDecisionRecord(candidate_set=_set(), decision=_decision())
    back = CandidateDecisionRecord.from_payload(rec.to_payload())
    assert back == rec
    assert back.selected[0].evidence[0].source_type is (
        CandidateSource.USER_HISTORY)
    assert back.decision.context.surface is SelectionSurface.LABEL_TEXT

    est = EstimateEvidence(chosen=_cand(), policy_version="p1", context=CTX,
                           considered=(_cand(candidate_id="c2"),))
    assert EstimateEvidence.from_payload(est.to_payload()) == est


def test_decimals_survive_storage_exactly():
    """Floats do not round-trip: 0.1 + 0.2 is the reason these are strings."""
    ev = _ev(confidence=Decimal("0.905"), uncertainty_g=Decimal("12.25"))
    p = ev.to_payload()
    assert isinstance(p["confidence"], str)
    back = QuantityCandidateEvidence.from_payload(p)
    assert back.confidence == Decimal("0.905")
    assert back.uncertainty_g == Decimal("12.25")


def test_a_caller_cannot_mutate_what_was_recorded():
    cands = [_cand()]
    s = _set(candidates=cands)
    cands.append(_cand(candidate_id="c2"))
    assert s.candidate_ids == {"c1"}
    with pytest.raises(Exception):
        s.candidates = ()


def test_an_assumption_records_who_it_was_made_for():
    with pytest.raises(ValueError, match="WHO it was made for"):
        EstimateEvidence(chosen=_cand(), policy_version="p1", context=None)


def test_estimate_evidence_refuses_a_population_prior():
    pop = _cand(evidence=(_ev(subject_scope=EvidenceScope.POPULATION,
                              subject_user_id=None),))
    with pytest.raises(ValueError, match="manufactures certainty"):
        EstimateEvidence(chosen=pop, policy_version="p1", context=CTX)


def test_a_cited_authority_without_a_value_converts_nothing():
    with pytest.raises(ValueError, match="converts nothing"):
        ConversionEvidence(from_basis=ServingBasis.VOLUME,
                           to_basis=ServingBasis.MASS,
                           source_record_id="usda:density:5062", factor=None)


def test_a_same_basis_conversion_cannot_quietly_rescale():
    with pytest.raises(ValueError):
        ConversionEvidence(from_basis=ServingBasis.MASS,
                           to_basis=ServingBasis.MASS, factor=Decimal("2"))
