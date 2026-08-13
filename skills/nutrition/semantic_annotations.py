"""PHASE 0.4 — THE MODEL ANNOTATES ONCE. CODE DECIDES WHAT IT MEANS.

    source evidence
        -> deterministic mechanical eligibility        (eligibility.py)
        -> VERSIONED SEMANTIC ANNOTATION               (this module)
        -> DETERMINISTIC SEMANTIC POLICY               (this module)
        -> deterministic ranking
        -> price

WHY. Build-time qualification re-sampled the model on every rebuild, and the
resolver exposes no determinism knob (`temperature` returns
`400 deprecated for this model`). A row scoring 0.75 in one build and 0.80 in
the next entered or left the candidate universe, changing eligibility, winner
and price with no source change.

Removing the model entirely was MEASURED and is not viable: with mechanical
eligibility alone, deterministic fuzzy ranking selects `Babyfood, guava and
papaya with tapioca` for "papaya", `Chicken spread` for "chicken", and
`Fish oil, salmon` at 902 kcal for "salmon". The semantic boundary is load
bearing.

So the model is neither removed nor re-sampled. It becomes a ONE-TIME
ANNOTATOR whose output is durable, versioned, reviewable DATA.

⭐ THE MODEL PRODUCES `relationship`. IT NEVER PRODUCES `eligible`.

    annotation.relationship == SAME_IDENTITY
        -> deterministic policy
        -> eligible

NOT:

    model -> eligible=true

That distinction is the whole slice. Persisting the model's own eligibility
conclusion would SERIALIZE the gate rather than remove it, and a serialized
gate is the same authority with a longer cache.

⭐⭐ AN ABSENT ANNOTATION IS `UNRESOLVED`, NEVER `DIFFERENT_IDENTITY`.

A timeout, a malformed reply, a no-text reply, a truncated reply and a row
nobody has classified yet are all UNRESOLVED. None of them is evidence that a
record is a different food. Unresolved evidence is PRESERVED and recorded as
unresolved — its absence from the priced set is attributable, diffable and
revisitable, which a silent drop is not.

⭐⭐⭐ STICKINESS IS THE POINT, NOT A SIDE EFFECT. A wrong-but-stable
annotation can be inspected, reproduced, reviewed, invalidated, corrected and
regression-tested. A right-on-average-but-varying one cannot. A NEWER MODEL IS
NOT AN INVALIDATION EVENT: model improvement must never silently rewrite
historical semantic facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

#: Bumped when the MEANING of a relationship changes, or when the policy
#: mapping relationships to eligibility changes. Part of the annotation key,
#: so a policy change is a visible re-annotation rather than silent drift.
SEMANTIC_POLICY_VERSION = "food_semantic_policy_v1"

#: Semantic, never operational. There is deliberately no `ELIGIBLE` member —
#: eligibility is a POLICY RESULT, and a vocabulary that could express it
#: would let the model state a conclusion instead of an observation.
SAME_IDENTITY = "SAME_IDENTITY"
COMPATIBLE_SPECIALIZATION = "COMPATIBLE_SPECIALIZATION"
DIFFERENT_IDENTITY = "DIFFERENT_IDENTITY"
AMBIGUOUS = "AMBIGUOUS"
UNRESOLVED = "UNRESOLVED"

RELATIONSHIPS = frozenset({SAME_IDENTITY, COMPATIBLE_SPECIALIZATION,
                           DIFFERENT_IDENTITY, AMBIGUOUS, UNRESOLVED})

#: Relationships a MODEL may assert. `UNRESOLVED` is absent on purpose: it is
#: what the SYSTEM records when no verdict exists, and a model that could
#: claim it would be able to launder a failure into a stored fact.
MODEL_ASSERTABLE = frozenset({SAME_IDENTITY, COMPATIBLE_SPECIALIZATION,
                              DIFFERENT_IDENTITY, AMBIGUOUS})

#: Closed vocabulary. `rebuild`, `retry`, `new_model_available` and
#: `confidence_changed` are deliberately NOT causes — each was a way an
#: existing judgement could be replaced without anyone deciding to.
SOURCE_REMOVED = "source_removed"
SOURCE_CHANGED = "source_changed"
POLICY_CHANGED = "policy_changed"
NORMALIZER_CHANGED = "normalizer_changed"
RESOLVER_MIGRATION = "resolver_migration"
MANUAL_INVALIDATION = "manual_invalidation"

#: ⭐ NARROWLY SCOPED, AND DELIBERATELY NOT AN ORDINARY CAUSE. Phase 1.5
#: adjudicates the FIRST baseline: rows already priced in production and rows
#: surfaced by repeated cold starts are reviewed, and the review is written
#: down as durable semantic data. That is a one-time migration, so this cause
#: is legal ONLY while `baseline_migration_open()` is true and is unavailable
#: to every ordinary rebuild afterwards.
#:
#: Without the scoping it would become the universal escape hatch — a cause
#: that means "because I said so", available forever, which is exactly the
#: unaccountable replacement the closed vocabulary exists to prevent.
BASELINE_MIGRATION = "baseline_migration"

INVALIDATION_CAUSES = frozenset({SOURCE_REMOVED, SOURCE_CHANGED,
                                 POLICY_CHANGED, NORMALIZER_CHANGED,
                                 RESOLVER_MIGRATION, MANUAL_INVALIDATION})

#: Causes admissible ONLY during the baseline migration.
_MIGRATION_ONLY_CAUSES = frozenset({BASELINE_MIGRATION})

_baseline_migration_open = False


def baseline_migration_open() -> bool:
    return _baseline_migration_open


def open_baseline_migration() -> None:
    """Explicit, and explicitly temporary. The reviewer opens it; ordinary
    builds never do."""
    global _baseline_migration_open
    _baseline_migration_open = True


def close_baseline_migration() -> None:
    global _baseline_migration_open
    _baseline_migration_open = False


def _admissible_causes() -> frozenset:
    return (INVALIDATION_CAUSES | _MIGRATION_ONLY_CAUSES
            if _baseline_migration_open else INVALIDATION_CAUSES)


class AnnotationReplacementRefused(Exception):
    """An existing judgement cannot be overwritten without a stated cause."""


@dataclass(frozen=True)
class Annotation:
    """One durable semantic judgement about one (identity, evidence) pair.

    Carries its own provenance so that a future change is explainable: which
    model, under which resolver and policy version, over which source
    fingerprint, and whether a human has reviewed it.
    """
    identity_key: str
    evidence_id: str
    relationship: str
    confidence: float = 0.0
    resolver_model: str = ""
    resolver_version: str = ""
    semantic_policy_version: str = SEMANTIC_POLICY_VERSION
    source_fingerprint: str = ""
    created_at: str = ""
    review_status: str = "unreviewed"
    invalidation_reason: str = ""

    def __post_init__(self):
        if self.relationship not in RELATIONSHIPS:
            raise ValueError(
                f"{self.relationship!r} is not a semantic relationship. The "
                f"vocabulary is closed and contains no operational member — "
                f"eligibility is a policy result, not something an annotation "
                f"may assert")
        if not self.identity_key or not self.evidence_id:
            raise ValueError("an annotation is keyed by identity AND evidence")

    @property
    def resolved(self) -> bool:
        return self.relationship != UNRESOLVED

    def to_payload(self) -> dict:
        return {"identity_key": self.identity_key,
                "evidence_id": self.evidence_id,
                "relationship": self.relationship,
                "confidence": float(self.confidence),
                "resolver_model": self.resolver_model,
                "resolver_version": self.resolver_version,
                "semantic_policy_version": self.semantic_policy_version,
                "source_fingerprint": self.source_fingerprint,
                "created_at": self.created_at,
                "review_status": self.review_status,
                "invalidation_reason": self.invalidation_reason}

    @classmethod
    def from_payload(cls, data: dict) -> "Annotation":
        return cls(**{k: data.get(k, getattr(cls, k, None))
                      for k in ("identity_key", "evidence_id", "relationship",
                                "confidence", "resolver_model",
                                "resolver_version", "semantic_policy_version",
                                "source_fingerprint", "created_at",
                                "review_status", "invalidation_reason")
                      if data.get(k) is not None})


def key(identity_key: str, evidence_id: str) -> str:
    return f"{identity_key}␟{evidence_id}"


# ── ⭐ THE DETERMINISTIC SEMANTIC POLICY — code, not the model ─────────────

#: Relationships that can support pricing the intended food. A composite
#: (pizza containing chicken) or an extract (chicken fat) is ABOUT the food
#: without BEING it. AMBIGUOUS and UNRESOLVED are excluded for DIFFERENT
#: reasons, and the difference is recorded rather than collapsed.
PRICEABLE = frozenset({SAME_IDENTITY, COMPATIBLE_SPECIALIZATION})

#: Confidence floor. A POLICY constant owned here, applied to a FROZEN stored
#: value — not re-sampled per build, which is what made 0.75-vs-0.80 able to
#: move a price with no source change.
MINIMUM_CONFIDENCE = 0.80


def eligible(annotation: Optional[Annotation]) -> bool:
    """May this evidence compete to price this identity?

    ⭐ CODE OWNS THIS. The model states a relationship; this decides what the
    relationship MEANS. Reversing that — storing the model's own `eligible`
    conclusion — would serialize the gate rather than remove it.

    A missing annotation is NOT eligible and is NOT a negative: `disposition`
    reports it as unresolved so the build can preserve the evidence and say
    why it is not priced.
    """
    if annotation is None or not annotation.resolved:
        return False
    if annotation.invalidation_reason:
        return False
    return (annotation.relationship in PRICEABLE
            and float(annotation.confidence) >= MINIMUM_CONFIDENCE)


def disposition(annotation: Optional[Annotation]) -> str:
    """WHY this evidence is or is not priced — attributable, never silent.

    The distinction this function exists to preserve:

        UNRESOLVED         we have no judgement          -> revisit
        DIFFERENT_IDENTITY the model judged it not this  -> settled
        AMBIGUOUS          the model could not tell      -> revisit
        below_confidence   judged, but weakly            -> settled by policy

    Collapsing the first into the second is exactly the defect this whole
    phase exists to remove.
    """
    if annotation is None:
        return "unresolved_never_annotated"
    if not annotation.resolved:
        return "unresolved"
    if annotation.invalidation_reason:
        return f"invalidated:{annotation.invalidation_reason}"
    if annotation.relationship == DIFFERENT_IDENTITY:
        return "different_identity"
    if annotation.relationship == AMBIGUOUS:
        return "ambiguous"
    if float(annotation.confidence) < MINIMUM_CONFIDENCE:
        return "below_confidence"
    return "priceable"


# ── reuse, and the refusal to re-roll ──────────────────────────────────────

@dataclass
class Store:
    """The annotation set for a build. Reuse is the default and the point."""
    by_key: dict = dc_field(default_factory=dict)
    #: Pairs this build asked the resolver about. A build over entirely known
    #: evidence must leave this EMPTY — gate 0.4.1.
    resolved_this_build: list = dc_field(default_factory=list)

    def get(self, identity_key: str, evidence_id: str) -> Optional[Annotation]:
        return self.by_key.get(key(identity_key, evidence_id))

    def needs_resolution(self, identity_key: str, evidence_id: str,
                         source_fingerprint: str = "") -> bool:
        """True only when no usable annotation exists FOR THIS SOURCE.

        Deliberately does not consider whether the current model would agree,
        whether a newer model exists, or whether confidence looks marginal.
        Each of those was a way to re-roll a judgement without deciding to.

        ⭐ THE FINGERPRINT IS THE ONE EXCEPTION, AND IT IS NOT A RE-ROLL. A
        judgement is ABOUT a specific source row. If USDA republishes that row
        with different content, the stored verdict is about something that no
        longer exists — reusing it would be answering a question nobody asked.
        That is `source_changed`, an attributable cause, and it is the only
        property of the annotation this method may consult beyond existence.
        """
        existing = self.get(identity_key, evidence_id)
        if existing is None or not existing.resolved:
            return True
        if (source_fingerprint and existing.source_fingerprint
                and source_fingerprint != existing.source_fingerprint):
            return True
        return False

    def stale_source(self, identity_key: str, evidence_id: str,
                     source_fingerprint: str) -> bool:
        """Does a stored judgement describe a DIFFERENT version of this row?"""
        existing = self.get(identity_key, evidence_id)
        return bool(existing is not None and existing.resolved
                    and source_fingerprint and existing.source_fingerprint
                    and source_fingerprint != existing.source_fingerprint)

    def record(self, annotation: Annotation, *, cause: str = "") -> Annotation:
        """Store a judgement. Replacing one REQUIRES a stated cause.

        `cause` is checked against the closed vocabulary, so `rebuild`,
        `retry` and `new_model_available` cannot be spelled — a newer model is
        not authority to rewrite history.
        """
        k = key(annotation.identity_key, annotation.evidence_id)
        existing = self.by_key.get(k)
        if existing is not None and existing.resolved:
            if not cause:
                raise AnnotationReplacementRefused(
                    f"{k} already holds {existing.relationship} and no "
                    f"invalidation cause was given — an ordinary rebuild is "
                    f"not authority to change a semantic fact")
            if cause not in _admissible_causes():
                extra = ("" if baseline_migration_open() else
                         f" ({BASELINE_MIGRATION!r} is admissible only while "
                         f"the baseline migration is open)")
                raise AnnotationReplacementRefused(
                    f"{cause!r} is not an invalidation cause. Allowed: "
                    f"{sorted(_admissible_causes())}{extra}")
        self.by_key[k] = annotation
        return annotation

    def to_payload(self) -> dict:
        return {k: a.to_payload() for k, a in sorted(self.by_key.items())}

    @classmethod
    def from_payload(cls, data: Optional[dict]) -> "Store":
        store = cls()
        for k, raw in (data or {}).items():
            try:
                store.by_key[k] = Annotation.from_payload(raw)
            except Exception:
                # A corrupt row is UNRESOLVED, never a negative.
                continue
        return store
