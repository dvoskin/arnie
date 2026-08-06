"""Real `QuantityCandidate` objects for tests that used to build
`CandidateValue`.

NOT A MOCK. The producer emits exactly this shape now, so a fixture that
short-circuited any of the contract's gates — evidence, offered expression,
source versioning — would prove the selector works on candidates production
can never build.
"""
from decimal import Decimal

from core.semantics import (CandidateSource, EvidenceScope, Provenance,
                            QuantityCandidate, QuantityCandidateEvidence,
                            ServingBasis, ServingExpression, SourceReference)
from skills.nutrition import quantity_clarification as qc

ENTITY = "food:chicken breast"


def candidate(candidate_id, grams, source=CandidateSource.ONTOLOGY,
              prior=0.5, confidence=0.6, entity=ENTITY, user_id=26):
    """One typed candidate, the way the generator builds them."""
    history = source is CandidateSource.USER_HISTORY
    prov = Provenance.USER_HISTORY if history else Provenance.ONTOLOGY
    q = qc._quantity(grams, provenance=prov, confidence=confidence,
                     basis=f"{source.value} evidence")
    ref = (qc._history_source(candidate_id) if history
           else qc._ontology_source(f"{entity}:{candidate_id}"))
    evidence = (QuantityCandidateEvidence(
        source_type=source, source=ref, observed_quantity=q,
        observed_basis=ServingBasis.MASS,
        subject_scope=(EvidenceScope.THIS_USER if history
                       else EvidenceScope.POPULATION),
        subject_user_id=user_id if history else None,
        confidence=Decimal(str(confidence))),)
    return QuantityCandidate(
        candidate_id=candidate_id, canonical_entity_id=entity, quantity=q,
        serving_basis=ServingBasis.MASS,
        offered=ServingExpression(amount=q.grams, unit_id="g",
                                  basis=ServingBasis.MASS, normalized=q),
        evidence=evidence, prior=Decimal(str(prior)),
        semantic_hash=qc._semantic_hash(q.grams, ServingBasis.MASS.value))


def candidates(*specs, entity=ENTITY, user_id=26):
    """`(candidate_id, grams, source, prior, confidence)` tuples."""
    return tuple(candidate(cid, g, source=src, prior=p, confidence=c,
                           entity=entity, user_id=user_id)
                 for cid, g, src, p, c in specs)
