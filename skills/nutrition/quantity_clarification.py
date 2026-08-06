"""B-1: the canonical producer for ONE food's unresolved consumed mass.

The first slice where the canonical clarification path owns a real production
turn end to end — for exactly one shape of turn:

    "I had some chicken breast."

Deliberately food-specific and deliberately narrow. The generalized
`ClarificationOptionGenerator` across every field family is milestone 9;
building it here is how a vertical slice becomes a horizontal layer, and the
four legacy producers exist because that happened once already.

THE PIPELINE, and who owns each step (directive §Ownership):

    unresolved field  ->  candidates  ->  selection  ->  typed patches
                                                     ->  rendered labels

`candidates()` produces evidence. `select()` decides which evidence becomes an
offer. `build_interaction()` binds them to a semantic field. Labels are
rendered LAST, from the chosen quantities, and are never read back — a tap
returns `option_id`, and the meaning comes from the stored `SetQuantity`.

WHAT THIS DOES NOT INVENT. Both candidate sources already exist and are
already trusted for other purposes:

  * the user's own logged history for the same food (the resolver already
    treats it as ground truth over USDA);
  * the calibrated portion ontology's distribution — the SAME bracket
    `food_turn._portion_stakes` already computes to RANK this question and
    then discards. Offering the numbers that decided the question is worth
    asking introduces no new judgement.

Web search, LLM-proposed candidates, catalog variants and cross-unit ranking
are excluded from B-1 by the directive, not by accident.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: At most three numeric options. A fourth is not more helpful; it is a longer
#: row to read before answering, and the directive caps it here.
MAX_NUMERIC_OPTIONS = 3

#: Two options within this ratio of each other are the same answer wearing two
#: labels. `4.8 / 5.0 / 5.2` was the measured failure of ranking by
#: probability alone: three chips, one meaning, no information gained.
NEAR_DUPLICATE_RATIO = 1.25

#: Below this spread the question is not worth asking in the first place, so
#: it is not worth offering a bracket for either. Same bar the pipeline uses.
MIN_USEFUL_SPREAD = 1.35


class Ineligible(str, Enum):
    """WHY a turn is not B-1's. A typed reason rather than a bool, because
    "how often, and for what" is the measurement that sizes B-1.5 and B-2 —
    and a bare False cannot answer it."""
    ELIGIBLE = "eligible"
    NO_ITEMS = "no_items"
    MULTIPLE_ITEMS = "multiple_items"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    IDENTITY_AMBIGUOUS = "identity_ambiguous"      # product/variant/package
    QUANTITY_ALREADY_STATED = "quantity_already_stated"
    NO_QUANTITY_QUESTION = "no_quantity_question"
    OTHER_MATERIAL_AMBIGUITY = "other_material_ambiguity"
    PREPARATION_DEPENDENCY = "preparation_dependency"
    NOT_MASS = "not_mass"
    CORRECTION_TURN = "correction_turn"
    CLIENT_INCAPABLE = "client_incapable"
    NO_CANDIDATES = "no_candidates"
    #: A branded item on a turn that never fetched the product shelf. Without
    #: that lookup `derive_variant_ambiguity` cannot find a variant question,
    #: so the item comes back looking unambiguous — indistinguishable from
    #: genuinely being so. "We did not look" must never read as "we know".
    IDENTITY_UNVERIFIED = "identity_unverified"


@dataclass(frozen=True)
class Eligibility:
    reason: Ineligible
    item: Any = None

    @property
    def ok(self) -> bool:
        return self.reason is Ineligible.ELIGIBLE


# ── eligibility ──────────────────────────────────────────────────────────────

#: THE ONE AMBIGUITY B-1 ANSWERS, keyed on the semantic TYPE rather than on a
#: field-name string.
#:
#: The first version keyed on `field_name == "estimated_mass_g"` and rejected
#: every real turn, because that name is not an ambiguity field at all — it is
#: a `FoodAssumption` field in `clarify_policy`, answering a different question
#: ("what did we assume, and must we disclose it"). The portion question the
#: pipeline actually emits — from the user's own hedge and the calibrated
#: ontology, the same bracket B-1's candidates are built from — carries
#: `ambiguity_type=CONSUMED_QUANTITY` and `field_name="consumed_fraction"`.
#:
#: I wrote that clause from the type NAME instead of from what the pipeline
#: emits, and the unit fixtures constructed the shape I had assumed, so 152
#: tests validated the predicate against an ambiguity production never
#: produces. The fixtures now come from `derive_semantics` for exactly that
#: reason.
#:
#: Keyed on the ENUM so a new ambiguity type defaults to ineligible: B-1
#: declining a turn it could have handled costs nothing, and B-1 claiming one
#: it cannot handle strands a meal.
def _is_quantity_question(amb) -> bool:
    from skills.nutrition.ambiguity import AmbiguityType

    return getattr(amb, "ambiguity_type", None) is \
        AmbiguityType.CONSUMED_QUANTITY


def is_eligible(decision, *, message: str = "",
                client_capable: bool = False,
                identity_evidence: bool = True) -> Eligibility:
    """Does this turn match B-1's predicate exactly?

    Conjunctive and conservative. Every clause is a thing B-1 has NOT built,
    so a decline is the correct outcome and the turn stays legacy, untouched.
    """
    if not client_capable:
        # NOT a fallback — an exclusion. Rendering canonical options as prose
        # for a client that cannot read the payload would keep the sentence
        # parser alive inside the replacement, which is the defect being
        # deleted. Old clients stay wholly legacy until they update.
        return Eligibility(Ineligible.CLIENT_INCAPABLE)

    items = tuple(getattr(decision, "staged_items", ()) or ())
    if not items:
        return Eligibility(Ineligible.NO_ITEMS)
    if len(items) > 1:
        return Eligibility(Ineligible.MULTIPLE_ITEMS)
    item = items[0]

    if _is_correction(message):
        return Eligibility(Ineligible.CORRECTION_TURN)

    identity = getattr(item, "identity", None)
    if not getattr(identity, "canonical_name", None):
        return Eligibility(Ineligible.IDENTITY_UNRESOLVED)

    # FAIL CLOSED ON EVIDENCE WE DID NOT FETCH. A branded item whose product
    # shelf was never looked up has no derived variant ambiguity — not because
    # there is none, but because nothing went looking. Claiming that turn would
    # ask "how much?" about a food we cannot yet name, which is the ordering
    # B-1's own predicate forbids (identity first, quantity second).
    if not identity_evidence and (getattr(identity, "brand", None)
                                  or getattr(identity, "product_line", None)
                                  or getattr(identity, "variant", None)):
        return Eligibility(Ineligible.IDENTITY_UNVERIFIED)

    quantity = getattr(item, "quantity", None)
    if getattr(quantity, "is_stated", False):
        # They told us. There is nothing to ask, and asking anyway is how a
        # clarification becomes an interrogation.
        return Eligibility(Ineligible.QUANTITY_ALREADY_STATED)

    material = tuple(getattr(item, "material_ambiguities", lambda: ())())
    if not material:
        return Eligibility(Ineligible.NO_QUANTITY_QUESTION)

    for amb in material:
        kind = getattr(getattr(amb, "ambiguity_type", None), "value", "")
        if getattr(getattr(amb, "ambiguity_type", None), "is_identity", False):
            return Eligibility(Ineligible.IDENTITY_AMBIGUOUS)
        if kind == "preparation":
            return Eligibility(Ineligible.PREPARATION_DEPENDENCY)
        if not _is_quantity_question(amb):
            return Eligibility(Ineligible.OTHER_MATERIAL_AMBIGUITY)

    if not any(_is_quantity_question(a) for a in material):
        return Eligibility(Ineligible.NO_QUANTITY_QUESTION)

    # A FRACTION OF A CONTAINER IS B-2.5'S SLICE, not this one — "half a Core
    # Power" is a question about the package, not about a mass. Read off the
    # quantity INTENT, which is where that distinction actually lives; the
    # ambiguity's field name cannot tell the two apart because both arrive as
    # `consumed_fraction`.
    if (getattr(quantity, "container_count", None) is not None
            or getattr(quantity, "consumed_fraction", None) is not None):
        return Eligibility(Ineligible.NOT_MASS)

    return Eligibility(Ineligible.ELIGIBLE, item=item)


#: Correction and destructive wording. Kept literal and small: this is a
#: DECLINE gate, so a miss costs a legacy turn (today's behaviour) rather than
#: a wrong canonical one.
_CORRECTION_MARKERS = (
    "actually", "correct", "change", "undo", "delete", "remove", "instead",
    "meant", "not ", "yesterday", "earlier", "wrong", "fix ",
)


def _is_correction(message: str) -> bool:
    low = (message or "").lower()
    return any(m in low for m in _CORRECTION_MARKERS)


# ── candidates ───────────────────────────────────────────────────────────────

#: Masses are held to a tenth of a gram. Not a precision claim — nothing here
#: was weighed — but a STABILITY one: option ids, labels and stored patches all
#: derive from this number, and an unquantized 141.70000000000002 would make
#: two runs of the same evidence produce two different chips.
_GRAM_STEP = Decimal("0.1")


def _quantity(grams, *, provenance, unit_id: str = "g",
              confidence: float = 0.0, basis: str = "") -> Any:
    """A `CanonicalQuantity` in grams, WITHOUT a float round trip.

    `Decimal(str(v))`, never `Decimal(str(round(float(v), 1)))`: the second
    form re-widens an already-imprecise value into a binary float before
    narrowing it again, which is how `Decimal("0.1")` stops equalling itself.
    `CanonicalQuantity` holds `Decimal` precisely so a portion survives the
    round trip into storage that B-0c proved — spending that guarantee at the
    point of construction would make the guarantee decorative.
    """
    from core.semantics import CanonicalQuantity, Confidence, Dimension

    g = (grams if isinstance(grams, Decimal) else Decimal(str(grams)))
    g = g.quantize(_GRAM_STEP)
    return CanonicalQuantity(
        amount=g, unit_id=unit_id, dimension=Dimension.MASS, grams=g,
        provenance=provenance,
        confidence=Confidence(score=float(confidence), basis=basis))


#: WHICH GENERATOR BUILT A UNIVERSE. Bumped when the candidate sources, their
#: priors, or the shape of what they emit change — never for a bug fix that
#: leaves the same candidates. Sets built under different versions are
#: different populations and must not be pooled.
GENERATOR_VERSION = "b1_quantity_gen_v1"

#: The ontology is a dataset, and its rows mean different masses across
#: refreshes. Evidence cites this so `portion:chicken_breast:large` cannot
#: silently change value while looking like the same claim.
ONTOLOGY_DATASET = "portion_ontology"
ONTOLOGY_DATASET_VERSION = "2026-08-06"

#: The user's own logs. MUTABLE — a correction rewrites the row — so evidence
#: from here must carry the row version, never the id alone.
HISTORY_DATASET = "food_entries"
HISTORY_DATASET_VERSION = "live"


async def generate(db, *, user_id, item, message: str = "", operation_id: str,
                   revision: int = 0, field_id: str, context) -> Any:
    """EVERYTHING this quantity could plausibly be, as a persistable universe.

    Ordered by the directive's authority ladder — the user's own history
    first, the calibrated ontology second — and NOT scored here. Producing
    evidence and choosing what to offer are different jobs with different
    owners (§Ownership); collapsing them is what made the legacy option
    builders unauditable.

    THE GENERATOR OWNS THE CANDIDATE SET AND NOTHING ELSE. It does not rank,
    does not render, and does not emit options — a producer that emits a
    `ClarificationOption` has decided presentation, and no later stage can
    then explain why an option looked the way it did.

    Inputs that cannot form a candidate are returned as REJECTIONS rather than
    dropped, because "the matcher found nothing" and "the matcher found a row
    it could not use" are different failures that look identical downstream.
    """
    from core.semantics import (CandidateSet, CandidateSource,
                                CandidateGenerationRejection,
                                GenerationRejectionReason, Provenance)

    out, rejected = [], []
    name = str(getattr(getattr(item, "identity", None), "canonical_name", "")
               or "").strip()
    entity = str(getattr(context, "canonical_entity_id", "") or "")
    # COMPUTED FIRST, because a candidate's id is scoped to the set it belongs
    # to — and the set's id is deterministic from its addressing triple, so
    # replay of the same revision resolves to the same ids without rerunning
    # anything.
    set_id = _set_id(operation_id, revision, field_id)

    # 1 — THE USER'S OWN LOG. Ground truth for a repeat item; it beats a
    # generic ontology row for the same reason it beats USDA.
    seen = None
    if name:
        try:
            seen = await _history_observation(db, user_id, name)
        except Exception:
            logger.debug("b1 history candidate unavailable", exc_info=True)
    if seen is not None:
        try:
            out.append(_history_candidate(seen, entity=entity,
                                          user_id=user_id, set_id=set_id))
        except ValueError as exc:
            rejected.append(CandidateGenerationRejection(
                producer=CandidateSource.USER_HISTORY,
                source=_history_source(seen.entry_id),
                reason=GenerationRejectionReason.MALFORMED_QUANTITY,
                generator_version=GENERATOR_VERSION, detail=str(exc)[:200]))

    # 2 — THE CALIBRATED ONTOLOGY, via the bracket that already ranked this
    # question. `_portion_stakes` walks exactly this chain and throws the
    # distribution away.
    dist = _distribution_for(item, message, name) if name else None
    if dist is not None and dist.lower_g:
        wide = dist.upper_g / max(dist.lower_g, 1e-6) >= MIN_USEFUL_SPREAD
        anchors = ((("low", dist.lower_g, 0.2), ("mid", dist.median_g, 0.5),
                    ("high", dist.upper_g, 0.3)) if wide
                   else (("mid", dist.median_g, 0.6),))
        for anchor, grams, prior in anchors:
            key = f"{name}:{getattr(dist, 'specificity', '')}:{anchor}"
            if not grams:
                # AN ANCHOR WITH NO MASS IS A GENERATION FAILURE, recorded as
                # one. Silently skipping it made an ontology row with a hole
                # indistinguishable from an ontology row that never matched.
                rejected.append(CandidateGenerationRejection(
                    producer=CandidateSource.ONTOLOGY,
                    source=_ontology_source(key),
                    reason=GenerationRejectionReason.NO_QUANTITY,
                    generator_version=GENERATOR_VERSION,
                    detail=f"{anchor} anchor carried no mass"))
                continue
            try:
                out.append(_ontology_candidate(
                    grams, key=key, anchor=anchor, prior=prior, entity=entity,
                    set_id=set_id,
                    confidence=float(getattr(dist, "confidence", 0.6) or 0.6)))
            except ValueError as exc:
                rejected.append(CandidateGenerationRejection(
                    producer=CandidateSource.ONTOLOGY,
                    source=_ontology_source(key),
                    reason=GenerationRejectionReason.MALFORMED_QUANTITY,
                    generator_version=GENERATOR_VERSION,
                    detail=str(exc)[:200]))

    return CandidateSet(
        candidate_set_id=set_id,
        operation_id=operation_id, user_id=user_id, context=context,
        interaction_revision=revision, field_id=field_id,
        generator_version=GENERATOR_VERSION,
        generation_input_fingerprint=_fingerprint(
            entity=entity, user_id=user_id, name=name, dist=dist, seen=seen),
        candidates=tuple(out), rejections=tuple(rejected))


async def candidates(db, *, user_id, item, message: str = "") -> tuple:
    """The candidate list alone, for callers that do not persist a universe.

    Kept because the offline scorecard and several proofs want the candidates
    without an operation to hang them on. The ASK PATH does not use this — it
    calls `generate`, because an ask must have a universe to be explained by.
    """
    from core.semantics import EvidenceContext

    entity = _entity_id_for(item)
    universe = await generate(
        db, user_id=user_id, item=item, message=message,
        operation_id="unpersisted", revision=0, field_id="unpersisted",
        context=EvidenceContext(user_id=user_id, canonical_entity_id=entity))
    return universe.candidates


def _entity_id_for(item) -> str:
    """The canonical entity a staged item is about."""
    ident = getattr(item, "identity", None)
    return (str(getattr(ident, "canonical_entity_id", "") or "").strip()
            or f"food:{str(getattr(ident, 'canonical_name', '') or '').strip().lower()}")


def _set_id(operation_id: str, revision: int, field_id: str) -> str:
    """DETERMINISTIC, AND OPAQUE. A hash of the addressing triple, so the same
    revision of the same field resolves to the same set on replay without the
    id itself leaking a user, a food or a label."""
    import hashlib

    raw = f"{operation_id}|{int(revision)}|{field_id}".encode()
    return "cs_" + hashlib.sha256(raw).hexdigest()[:24]


def _candidate_id(set_id: str, semantic_hash: str) -> str:
    import hashlib

    return "cand_" + hashlib.sha256(
        f"{set_id}|{semantic_hash}".encode()).hexdigest()[:24]


def _semantic_hash(grams: Decimal, basis_value: str) -> str:
    """CONTENT IDENTITY, not an address. Two producers arriving at the same
    amount on the same basis describe the same candidate — which is what lets
    them merge later without either losing its provenance."""
    import hashlib

    return hashlib.sha256(f"{basis_value}|{grams}".encode()).hexdigest()[:32]


def _fingerprint(*, entity: str, user_id: int, name: str, dist, seen) -> str:
    """A DIGEST OF THE SEMANTIC INPUTS, so regenerating the same revision from
    different inputs fails loudly instead of silently returning the old
    universe. Covers meaning, never incidental object representation.
    """
    import hashlib

    parts = [entity, str(user_id), name,
             str(getattr(dist, "specificity", "") or ""),
             str(getattr(dist, "lower_g", "") or ""),
             str(getattr(dist, "median_g", "") or ""),
             str(getattr(dist, "upper_g", "") or ""),
             str(getattr(seen, "entry_id", "") or ""),
             str(getattr(seen, "grams", "") or "")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _history_source(entry_id):
    from core.semantics import SourceReference

    return SourceReference(dataset_id=HISTORY_DATASET,
                           dataset_version=HISTORY_DATASET_VERSION,
                           record_key=str(entry_id),
                           # MUTABLE: a correction rewrites the row, so the
                           # value at generation time is pinned here.
                           record_version=f"entry:{entry_id}")


def _ontology_source(key: str):
    from core.semantics import SourceReference

    return SourceReference(dataset_id=ONTOLOGY_DATASET,
                           dataset_version=ONTOLOGY_DATASET_VERSION,
                           record_key=key,
                           immutable_within_version=True)


def _mass_candidate(grams, *, entity, set_id, evidence, prior, provenance,
                    basis_text):
    """One mass candidate, said in grams, with its offered expression."""
    from core.semantics import (QuantityCandidate, ServingBasis,
                                ServingExpression)

    q = _quantity(grams, provenance=provenance, basis=basis_text)
    digest = _semantic_hash(q.grams, ServingBasis.MASS.value)
    return QuantityCandidate(
        candidate_id=_candidate_id(set_id, digest),
        canonical_entity_id=entity, quantity=q,
        serving_basis=ServingBasis.MASS,
        offered=ServingExpression(amount=q.grams, unit_id="g",
                                  basis=ServingBasis.MASS, normalized=q),
        evidence=evidence, semantic_hash=digest, prior=Decimal(str(prior)))


def _history_candidate(seen, *, entity, user_id, set_id):
    from core.semantics import (CandidateSource, EvidenceScope, Provenance,
                                QuantityCandidateEvidence, ServingBasis)

    q = _quantity(seen.grams, provenance=Provenance.USER_HISTORY,
                  confidence=0.9, basis="the user's own last log")
    evidence = (QuantityCandidateEvidence(
        source_type=CandidateSource.USER_HISTORY,
        source=_history_source(seen.entry_id),
        # THE VALUE AS OBSERVED, quantized the same way the candidate is —
        # they are the same fact, and the contract requires them to agree.
        observed_quantity=q, observed_basis=ServingBasis.MASS,
        observed_at=seen.observed_at,
        subject_scope=EvidenceScope.THIS_USER, subject_user_id=user_id,
        confidence=Decimal("0.9")),)
    return _mass_candidate(
        seen.grams, entity=entity,
        set_id=set_id, evidence=evidence, prior=0.55,
        provenance=Provenance.USER_HISTORY,
        basis_text="the user's own last log")


def _ontology_candidate(grams, *, key, anchor, prior, entity, set_id,
                        confidence):
    from core.semantics import (CandidateSource, EvidenceScope, Provenance,
                                QuantityCandidateEvidence, ServingBasis)

    q = _quantity(grams, provenance=Provenance.ONTOLOGY,
                  confidence=confidence, basis=f"portion ontology ({anchor})")
    evidence = (QuantityCandidateEvidence(
        source_type=CandidateSource.ONTOLOGY, source=_ontology_source(key),
        observed_quantity=q, observed_basis=ServingBasis.MASS,
        # POPULATION. True about people in general, and never sufficient to
        # assert what one person ate.
        subject_scope=EvidenceScope.POPULATION,
        confidence=Decimal(str(round(float(confidence), 4)))),)
    return _mass_candidate(
        grams, entity=entity, set_id=set_id, evidence=evidence,
        prior=prior, provenance=Provenance.ONTOLOGY,
        basis_text=f"portion ontology ({anchor})")


#: How far back the history scan will read before it gives up. Bounds a
#: pathological account rather than a normal one: 90 days of heavy logging is
#: a few hundred rows, and this is an order of magnitude above that. Reaching
#: it is logged, because the bug this replaced was a cap that truncated in
#: silence.
HISTORY_SCAN_CAP = 2000


class HistoryQuantity:
    """One prior log, WITH ITS IDENTITY AND ITS VALUE AT THE TIME.

    A bare number cannot be audited and a bare row id cannot be trusted: a
    `food_entries` row is mutable, so an id alone points at whatever it says
    now rather than at what it said when this candidate was generated. Both
    travel, so the evidence can still state "candidate X existed because entry
    2871 held 182 g on 2026-08-04".
    """

    __slots__ = ("grams", "entry_id", "observed_at")

    def __init__(self, grams, entry_id, observed_at):
        self.grams, self.entry_id, self.observed_at = grams, entry_id, observed_at


async def _history_grams(db, user_id, food_name: str) -> Optional[float]:
    """Back-compatible view of `_history_observation` — grams only."""
    seen = await _history_observation(db, user_id, food_name)
    return None if seen is None else seen.grams


async def _history_observation(db, user_id,
                               food_name: str) -> Optional["HistoryQuantity"]:
    """The user's most recent NON-ESTIMATED log of this exact food, in grams.

    Reuses `_logged_history_match`'s guards deliberately: >=2 content tokens
    (so a bare "bagel" cannot speak for every bagel), exact content-token-set
    equality (so "grilled chicken breast" never answers for "chicken breast"),
    and `estimated_flag is False` — because a row is not ground truth just
    because we wrote it, and one bad auto-estimate would otherwise launder
    itself into a permanent chip.
    """
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from db.models import DailyLog, FoodEntry
    from handlers.tool_executor import _content_tokens

    tokens = _content_tokens(food_name)
    if len(tokens) < 2:
        return None
    cutoff = date.today() - timedelta(days=90)
    # THE CAP MUST NOT TRUNCATE BEFORE THE FOOD FILTER.
    #
    # This was `.limit(50)` over ALL foods, with the name compared afterwards
    # in Python. For anyone logging more than a handful of items a day, 50
    # rows is about a week — so the 90-day window above was dead code, and a
    # food not eaten in the last few days was invisible no matter how often it
    # had been logged. Measured 2026-08-06: a rice question with FIFTEEN exact
    # non-estimated priors offered only ontology options, because the 50 most
    # recent rows reached back just to 2026-07-29.
    #
    # Not pre-filtered in SQL either. `normalize_name` strips punctuation, so
    # "grass-fed" becomes the single token "grassfed" and a portable LIKE
    # would silently miss exactly the rows this is meant to find — trading a
    # visible cap for an invisible one.
    #
    # Two columns, bounded by the 90-day window, matched here. The scan is
    # small because it is columns rather than entities, and a B-1 ask is not
    # a hot path.
    rows = (await db.execute(
        select(FoodEntry.parsed_food_name, FoodEntry.quantity, FoodEntry.id,
               DailyLog.date)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id, DailyLog.date >= cutoff,
               FoodEntry.estimated_flag.is_(False),
               FoodEntry.quantity.isnot(None))
        .order_by(DailyLog.date.desc(), FoodEntry.id.desc())
        .limit(HISTORY_SCAN_CAP))).all()
    # A CAP THAT SAYS WHEN IT BITES. The defect above was silent truncation;
    # a backstop that hides the same way is the same defect with a larger
    # number, so hitting this is a LOUD event rather than a quiet ceiling.
    if len(rows) >= HISTORY_SCAN_CAP:
        logger.warning(
            "event=b1_history_scan_capped user=%s cap=%d — the 90-day window "
            "no longer fits; history recall is now truncated and will "
            "under-report", user_id, HISTORY_SCAN_CAP)
    for name, quantity, entry_id, logged_on in rows:
        if _content_tokens(name or "") != tokens:
            continue
        from skills.nutrition.normalize import normalize_quantity
        nq = normalize_quantity(quantity or "", name or "")
        if nq is not None and getattr(nq, "grams", None):
            return HistoryQuantity(grams=float(nq.grams), entry_id=int(entry_id),
                                   observed_at=_as_utc(logged_on))
    return None


def _as_utc(logged_on):
    """A logging DATE, read as an instant, in UTC.

    Timezone-aware because the evidence contract refuses a naive one: a source
    time that cannot be compared across a rollover boundary is a source time
    that will eventually be compared wrongly.
    """
    from datetime import datetime, time, timezone

    if logged_on is None:
        return None
    if isinstance(logged_on, datetime):
        return (logged_on.replace(tzinfo=timezone.utc)
                if logged_on.tzinfo is None else logged_on)
    return datetime.combine(logged_on, time(0, 0), tzinfo=timezone.utc)


def _distribution_for(item, message: str, name: str):
    """The ontology's distribution for the user's own vague word, or for the
    food itself when they used none.

    `vague_measure` is read off the STAGED ITEM first: it was recorded on the
    turn whose message contained the word, and re-deriving it from whatever
    message is current loses it the moment a meal spans two turns.
    """
    try:
        from skills.nutrition.portions import distribution_for
        measure = (str(getattr(item, "vague_measure", "") or "").strip()
                   or _measure_in(message, name))
        if not measure:
            # No hedge of their own — the food's own typical serving is still
            # honest evidence, and "some" is the neutral row for it.
            measure = "some"
        return distribution_for(measure, name)
    except Exception:
        logger.debug("b1 ontology candidate unavailable", exc_info=True)
        return None


def _measure_in(message: str, name: str) -> str:
    try:
        from core.food_pipeline import _vague_measure_in
        return _vague_measure_in(message or "", name or "") or ""
    except Exception:
        return ""


# ── selection ────────────────────────────────────────────────────────────────

#: WHICH POLICY REDUCED A UNIVERSE. Owned by `candidate_selection`, re-exported
#: here because the ask path and the proofs both read it from this module.
from skills.nutrition.candidate_selection import (  # noqa: E402
    SELECTION_POLICY_VERSION)

#: WHICH RENDERER WORDED THE OPTIONS. Load bearing: `RENDER_COLLISION` is a
#: judgement about wording, so it is only reproducible against the renderer
#: that did the wording.
RENDERER_CONTRACT_VERSION = "b1_labels_v1"


def selection_context(*, capability, locale: str = "en"):
    """The conditions the decision was made under.

    Persisted with the decision because a policy version alone does not
    determine the outcome: the same universe yields a text row on Telegram and
    a structured one on iOS, and can word them differently by locale.
    """
    from core.semantics import CandidateSelectionContext, SelectionSurface

    surface = (SelectionSurface.ID_ADDRESSED
               if str(getattr(capability, "value", capability) or "")
               == "id_addressed" else SelectionSurface.LABEL_TEXT)
    return CandidateSelectionContext(
        surface=surface, locale=locale or "en",
        maximum_options=MAX_NUMERIC_OPTIONS,
        renderer_contract_version=RENDERER_CONTRACT_VERSION)


def reduce_universe(universe, *, field, context, food_name: str = "",
                    policy_version=None):
    """Turn a universe into the row the user reads, and the record of why.

    THREE STAGES WITH THREE OWNERS, and the separation is the point:

        select      what each candidate MEANS      pure, versioned, no labels
        present     what each candidate SAYS       renders, reports collisions
        record      what was offered and why not   the durable decision

    Selection used to render labels itself, which made a wording judgement
    indistinguishable from a semantic one: `RENDER_COLLISION` was attributed
    to the policy, and a locale that worded two candidates differently would
    have silently changed what got SELECTED. Now the policy never sees a
    label, and a collision is attributed to the renderer version that caused
    it.

    Returns `(options, decision_record)`. Every option carries a typed
    `SetQuantity` and the id of the candidate it came from, so there is no
    path here producing a label without a patch or without a justification.
    """
    from dataclasses import replace

    from core.semantics import (CandidateDecisionRecord, CandidateExclusion,
                                CandidateSelectionDecision,
                                ClarificationOption, ExclusionReason,
                                PresentedCandidateOption, Provenance,
                                SetQuantity)
    from skills.nutrition import candidate_selection as policy

    version = policy_version or policy.SELECTION_POLICY_VERSION
    chosen, excluded = policy.select(universe, context=context,
                                     policy_version=version)
    excluded = list(excluded)

    # ── presentation ────────────────────────────────────────────────────────
    #
    # DEDUPE ON WHAT THE USER ACTUALLY READS. Selection compares meaning; a
    # chip row is compared by eye. Measured on the first wired turn: chicken
    # breast's ontology bracket (130.5 / 174 / 435 g) is well separated
    # numerically — 1.33x between the first two — and renders as
    # "5 oz / 6 oz / 16 oz". Nobody reads 5 and 6 ounces as two different
    # answers, so that row offers three chips and two choices, and the third
    # is a pound of chicken.
    ranked = sorted(universe.candidates, key=policy.rank_of, reverse=True)
    chosen, labels, collided = _collapse_by_label(list(chosen), ranked,
                                                  food_name)
    excluded.extend((c.candidate_id, ExclusionReason.RENDER_COLLISION)
                    for c in collided)

    options, presented = [], []
    for position, (cand, label) in enumerate(zip(chosen, labels)):
        # A TAP IS A SELECTION, NOT A STATEMENT. The user accepted a figure we
        # produced; recording it as their own is the measured 2026-08-04
        # disclosure defect, and provenance is the only thing that keeps the
        # distinction once the answer applies.
        quantity = replace(cand.quantity, provenance=Provenance.USER_SELECTED)
        option_id = f"opt_{cand.candidate_id}"
        options.append(ClarificationOption(
            label=label, option_id=option_id, field_id=field.field_id,
            patch=SetQuantity(event_id=field.event_id,
                              field_id=field.field_id, quantity=quantity,
                              provenance=Provenance.USER_SELECTED),
            source=cand.evidence[0].source_type,
            candidate_id=cand.candidate_id,
            candidate_set_id=universe.candidate_set_id,
            candidate=cand))
        presented.append(PresentedCandidateOption(
            option_id=option_id, candidate_id=cand.candidate_id,
            candidate_set_id=universe.candidate_set_id,
            interaction_revision=universe.interaction_revision,
            selected_position=position, rendered_label=label,
            renderer_contract_version=RENDERER_CONTRACT_VERSION))

    decision = CandidateSelectionDecision(
        candidate_set_id=universe.candidate_set_id,
        selection_policy_version=version, context=context,
        selected_candidate_ids=tuple(c.candidate_id for c in chosen),
        exclusions=tuple(CandidateExclusion(candidate_id=cid, reason=reason)
                         for cid, reason in excluded))
    record = CandidateDecisionRecord(candidate_set=universe, decision=decision,
                                     presented=tuple(presented))
    return tuple(options), record


def select(candidates_in, *, field, food_name: str = "") -> tuple:
    """The offered options alone, for callers with no universe to persist.

    The ASK PATH DOES NOT USE THIS. It calls `reduce_universe`, because an ask
    that cannot say why it offered what it offered is the thing this whole
    commit removes.
    """
    from core.semantics import (CandidateSelectionContext, CandidateSet,
                                EvidenceContext, SelectionSurface)

    cands = tuple(candidates_in or ())
    if not cands:
        return ()
    # THE SUBJECT IS READ OFF THE CANDIDATES, never invented. A placeholder
    # user here would make the set's ownership check reject perfectly valid
    # history evidence — the gate firing on the shim rather than on a defect.
    owner = next((e.subject_user_id for c in cands for e in c.evidence
                  if e.subject_user_id), 0) or 1
    universe = CandidateSet(
        candidate_set_id="cs_unpersisted", operation_id="unpersisted",
        user_id=owner, interaction_revision=0, field_id=field.field_id,
        context=EvidenceContext(
            user_id=owner, canonical_entity_id=cands[0].canonical_entity_id),
        generator_version=GENERATOR_VERSION,
        generation_input_fingerprint="unpersisted", candidates=cands)
    options, _record = reduce_universe(
        universe, field=field, food_name=food_name,
        context=CandidateSelectionContext(
            surface=SelectionSurface.LABEL_TEXT, locale="en",
            maximum_options=MAX_NUMERIC_OPTIONS,
            renderer_contract_version=RENDERER_CONTRACT_VERSION))
    return options


def _rank(cand) -> float:
    """Kept as a re-export: the offline scorecard ranks candidates the same
    way the policy does, and duplicating the formula there would let the two
    drift."""
    from skills.nutrition.candidate_selection import rank_of

    return rank_of(cand)


def _near(a: float, b: float) -> bool:
    lo, hi = min(a, b), max(a, b)
    return lo > 0 and hi / lo < NEAR_DUPLICATE_RATIO


def _collapse_by_label(chosen, ranked, food_name: str):
    """Drop options whose LABELS say the same thing, then re-render.

    Re-rendering after each drop is not wasted work: `_everyday_labels` picks
    a rendering per anchor relative to its neighbours, so removing one anchor
    can legitimately change how the survivors are said.

    ONLY WITHIN A BASIS. Two candidates on different bases are different
    choices — `1 piece` and `150 g` — so their labels are never compared, and
    a coincidence of wording cannot delete one of them.
    """
    rank = {id(c): i for i, c in enumerate(ranked)}
    dropped = []
    while True:
        labels = _render_labels(chosen, food_name)
        drop = None
        for i in range(len(chosen) - 1):
            if _basis_of(chosen[i]) is not _basis_of(chosen[i + 1]):
                continue
            a, b = _label_mass(labels[i], food_name), \
                _label_mass(labels[i + 1], food_name)
            if labels[i] == labels[i + 1] or (
                    a and b and _near(a, b)):
                # Keep the better-evidenced one; ranked order decided that.
                drop = (i if rank.get(id(chosen[i]), 99)
                        > rank.get(id(chosen[i + 1]), 99) else i + 1)
                break
        if drop is None:
            return chosen, labels, tuple(dropped)
        dropped.append(chosen[drop])
        chosen = chosen[:drop] + chosen[drop + 1:]
        if len(chosen) <= 1:
            return chosen, _render_labels(chosen, food_name), tuple(dropped)


def _basis_of(cand):
    """The candidate's serving basis, or MASS for the lightweight stand-ins
    the offline dry run builds."""
    from core.semantics import ServingBasis

    return getattr(cand, "serving_basis", None) or ServingBasis.MASS


def _render_labels(chosen, food_name: str) -> tuple:
    """How each option is SAID.

    MASS GOES THROUGH `_everyday_labels`, which is the accumulated judgement
    about how people say weights — ounces for meat, cups for rice — and is
    inherently mass-specific.

    EVERY OTHER BASIS IS SAID BY ITS OWN OFFERED EXPRESSION. This is why
    `ServingExpression` exists: `21 g + VOLUME` does not tell a renderer
    whether to write `1 tbsp`, `15 ml` or `3 tsp`, so the candidate carries
    what it is offered AS.

    Before this, every candidate was pushed through `float(grams)` — so the
    first volume, count, piece, package or fraction candidate to reach a real
    ask would have raised `TypeError` on `float(None)` and taken the whole
    turn down. Found by the commit-6 class sweep, which is what a class sweep
    is for: the platform claimed to carry these bases and could not render one.
    """
    from core.semantics import ServingBasis

    mass_positions = [i for i, c in enumerate(chosen)
                      if _basis_of(c) is ServingBasis.MASS]
    labels = [None] * len(chosen)
    if mass_positions:
        rendered = labels_for(
            tuple(float(_grams_of(chosen[i])) for i in mass_positions),
            food_name)
        for slot, label in zip(mass_positions, rendered):
            labels[slot] = label
    for i, cand in enumerate(chosen):
        if labels[i] is None:
            labels[i] = _expression_label(cand)
    return tuple(labels)


def _expression_label(cand) -> str:
    """`3 tbsp`, `2 pieces`, `0.5 package` — read off the candidate's own
    offered expression, with the unit written BY THE REGISTRY.

    The obvious rule — append "s" when the amount is not one — produces
    `240 mls`, `3 tbsps` and `2 ozs`, and no better rule fixes it, because
    nothing in a canonical unit id says whether it is an abbreviation. It also
    does not survive a second language. So the written forms are a table, and
    the table is versioned.
    """
    from core import unit_registry

    offered = getattr(cand, "offered", None)
    if offered is None:
        return f"{float(_grams_of(cand) or 0):g}g"
    amount = offered.amount
    said = (f"{int(amount)}" if amount == amount.to_integral_value()
            else f"{amount.normalize():f}")
    return f"{said} {unit_registry.say(amount, offered.unit_id)}"


def _grams_of(cand):
    """Mass off either shape.

    The collapse pass is also driven by the offline dry run, which builds
    lightweight stand-ins rather than full candidates — so this reads
    `quantity` first and falls back to the older `semantic_value`.
    """
    q = getattr(cand, "quantity", None) or getattr(cand, "semantic_value", None)
    return getattr(q, "grams", 0)


def _label_mass(label: str, food_name: str) -> Optional[float]:
    """What this label means when READ BACK — the only definition of "these
    two chips say the same thing" that matches how a user compares them."""
    try:
        from skills.nutrition.normalize import normalize_quantity
        grams = normalize_quantity(label, food_name or "").grams
        return float(grams) if grams else None
    except Exception:
        return None


def labels_for(grams: tuple, food_name: str = "") -> tuple:
    """Ascending grams, said in the unit the user serves this food in.

    Rendered LAST and never read back. `_everyday_labels` already owns this
    judgement — ounces for meat, cups for rice — and its acceptance test is
    entirely derived: a label survives only if its re-parsed mass is closer to
    its OWN anchor than to a neighbour's, so a chip can never silently stand
    in for a portion the user did not mean. That check is relative to the
    whole row, which is why the row is rendered in one call rather than a
    label at a time. Grams remain the fallback and remain what all of this is
    measured in.
    """
    try:
        from core.food_pipeline import _everyday_labels
        rendered = _everyday_labels(tuple(grams), food_name or "")
        if rendered and len(rendered) == len(grams):
            return tuple(str(r) for r in rendered)
    except Exception:
        logger.debug("everyday labels unavailable", exc_info=True)
    return tuple(f"{int(round(g))}g" for g in grams)


# ── the interaction ──────────────────────────────────────────────────────────

def event_id_for(item) -> str:
    """The event a patch targets. The staged item's id, which is stable across
    the ask and the answer turn — unlike list position or display text, which
    is what the adapter's ids were made of and why an answer could land on the
    wrong row."""
    return f"food_{getattr(item, 'staged_item_id', '') or 'unknown'}"


def build_interaction(*, operation_id: str, revision: int, item,
                      options, introduction: str = "") -> Any:
    """One group, one field, ID-addressed.

    Structural validity is not re-checked here: `UnresolvedField`,
    `ClarificationGroup` and `ClarificationInteraction` refuse a mixed row, a
    foreign-field option, an operation mismatch and a blank select at
    construction (B-0c). Re-implementing those checks in the producer is how
    two owners of one invariant appear.
    """
    from core.semantics import ClarificationGroup, ClarificationInteraction

    event_id = event_id_for(item)
    field = quantity_field(operation_id=operation_id, revision=revision,
                           item=item, options=options)
    label = str(getattr(getattr(item, "identity", None), "canonical_name", "")
                or getattr(item, "original_text", "") or "").strip()
    return ClarificationInteraction(
        interaction_id=f"ix_{operation_id}:{revision}",
        operation_id=operation_id, revision=revision,
        introduction=introduction,
        groups=(ClarificationGroup(event_id=event_id, label=label,
                                   fields=(field,)),))


def quantity_field(*, operation_id: str, revision: int, item, options=(),
                   uncertainty=None) -> Any:
    """The one unresolved field B-1 owns.

    `FREE_TEXT_FALLBACK` when nothing could be offered, never an empty select:
    C15 exists because a blank options row is what the client "repaired" by
    parsing prose. Saying the fallback out loud is the whole difference.
    """
    from core.semantics import (ClarificationAttribute, ResponseType,
                                UncertaintyEvidence, UnresolvedField)

    return UnresolvedField(
        operation_id=operation_id, revision=revision,
        event_id=event_id_for(item),
        attribute=ClarificationAttribute.QUANTITY,
        allowed_dimensions=("mass",), allowed_units=("g", "oz"),
        uncertainty=uncertainty or UncertaintyEvidence(),
        response_type=(ResponseType.SINGLE_SELECT if options
                       else ResponseType.FREE_TEXT_FALLBACK),
        options=tuple(options or ()))
