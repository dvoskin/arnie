"""THE SEMANTIC EVIDENCE BOUNDARY — mechanism, contract, and nothing else.

The seam between probabilistic interpretation and deterministic execution:

    typed intent  +  bounded EvidenceRecord[]
        -> semantic resolver (model, schema-closed, versioned)
        -> SemanticAssessment[]     typed relationship + extracted semantics
        -> deterministic policy     authority, thresholds, abstention
        -> qualified evidence

WHY IT EXISTS, measured on 2026-08-07 and preserved in
`tests/evidence_corpus/`: a bare USDA query for "chicken" returns chicken
spread, meatless chicken, chicken FAT at 900 kcal, frankfurter and bologna in
its top eight; Open Food Facts returns SPICY CHICKEN & 'NDUJA PIZZA — graded
`_match: "exact"`, the same grade it gives four correct branded matches. A
provider's own confidence carries no information about comparability, and
string overlap is not identity. Production priced 80 g of papaya at 200 kcal
off the heavy-syrup row because nothing in the system could say "this record
is not about the food the user meant."

CORE KNOWS NO DOMAIN. This module never names a food, a preparation, an
exercise or any other domain concept. The domain supplies a `SemanticDomain` —
its relationship vocabulary, its intent rendering, its extraction fields, its
version — and core supplies invocation, schema enforcement, abstention,
bounding and the policy seam. THE HONESTY TEST IS A GATE
(`test_workouts_could_adopt_this_without_a_core_change`): if Phase E/F needs a
core edit, this seam failed.

THE MODEL INTERPRETS MEANING; CODE DECIDES AUTHORITY. An assessment may say
`relationship=COMPATIBLE, confidence=0.94`. It may never say "use this row" or
"log 226 calories" — there is deliberately no such field in the schema, and
`confidence` authorizes nothing by itself: deterministic policy owns every
threshold, and nutrition numbers still come from the existing resolver ladder.

FAIL CLOSED, PER RECORD AND PER BATCH. A malformed reply, an unknown
relationship, an out-of-range confidence or a resolver exception yields
ABSTENTION (`INSUFFICIENT_EVIDENCE` at confidence 0.0) — never a guess, and
never a crash into the food-logging path. Abstention is a first-class answer:
rejecting a useful candidate costs another lookup; accepting chicken fat as
chicken costs a wrong meal.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: The one relationship every domain shares: "cannot tell". It is core's
#: because abstention is mechanism, not meaning — the fail-closed value must
#: exist even for a domain that forgot to define one.
ABSTAIN = "INSUFFICIENT_EVIDENCE"

#: Hard cap on records per resolution batch. The resolver classifies a BOUNDED
#: candidate set; it does not replace search (§25).
MAX_RECORDS = 16


@dataclass(frozen=True)
class EvidenceRecord:
    """One retrieved record, structurally normalized and semantically raw.

    Adapters map fields that GENUINELY EXIST on the provider's response —
    brand if the provider has a brand field, nothing inferred. The
    human-readable text stays human-readable: deciding that "Fat, chicken" is
    rendered fat rather than chicken is the resolver's job, never the
    adapter's, because comma-position parsing is regex identity wearing a
    structure costume.
    """
    evidence_id: str
    provider: str                      # "usda" | "off" | "web" | ...
    title: str = ""
    description: str = ""
    brand: str = ""
    #: Whatever nutrition the provider states, as it states it.
    nutrition: dict = dc_field(default_factory=dict)
    #: What KIND of thing this is — "structured_record" or "synthesized_text".
    #: A Tavily answer is synthesized: no source_record_id, not re-derivable,
    #: and policy treats it differently PER CLAIM (materiality yes, pricing no).
    evidence_type: str = "structured_record"
    provider_record_id: str = ""
    source_reference: str = ""
    #: Provider-reported quality signals, preserved verbatim and TRUSTED FOR
    #: NOTHING — OFF said "exact" about a pizza.
    provider_metadata: dict = dc_field(default_factory=dict)

    def __post_init__(self):
        if not self.evidence_id or not self.provider:
            raise ValueError("evidence must say what it is and where it came "
                             "from — an unattributable record cannot be "
                             "audited and therefore cannot be used")


@dataclass(frozen=True)
class SemanticAssessment:
    """The resolver's typed conclusion about ONE record. No chain-of-thought.

    `relationship` is validated against the DOMAIN's closed vocabulary;
    anything else became ABSTAIN before this object was built. `extracted` may
    hold only the domain's declared extraction fields — the model cannot smuggle
    new semantics through a side channel.
    """
    evidence_id: str
    relationship: str
    #: Semantic confidence: how sure the model is about the RELATIONSHIP.
    #: Explicitly NOT source quality (Instagram can be confidently about fried
    #: chicken) and NOT authorization (policy owns thresholds).
    confidence: float
    #: Domain-declared fields only, e.g. {"preparation": "roasted"}.
    extracted: dict = dc_field(default_factory=dict)
    resolver_version: str = ""

    @property
    def abstained(self) -> bool:
        return self.relationship == ABSTAIN


@dataclass(frozen=True)
class SemanticDomain:
    """What a domain teaches the shared mechanism. Meaning lives here;
    mechanism stays in core.

    Registration mirrors `core.semantic_fields`: nutrition supplies the food
    vocabulary and projections, workouts will supply theirs, and core changes
    for neither.
    """
    name: str
    #: The policy identity: model+prompt+schema are one versioned unit, and a
    #: persisted assessment must remain attributable to the version that made
    #: it (changing the prompt cannot silently redefine history).
    version: str
    #: Closed relationship vocabulary. ABSTAIN is added by core.
    relationships: tuple
    #: Field names the model may extract, e.g. ("preparation", "brand_variant").
    extraction_fields: tuple = ()
    #: Renders the typed intent for the prompt. A FUNCTION so core never
    #: imports the domain's intent type.
    render_intent: Optional[Callable] = None
    #: Domain guidance appended to the classification instruction — what the
    #: relationships MEAN in this domain, with the domain's own examples.
    guidance: str = ""

    def vocabulary(self) -> frozenset:
        return frozenset(self.relationships) | {ABSTAIN}


def _prompt(domain: SemanticDomain, intent, records) -> str:
    """One bounded batch, one call. The task is controlled classification —
    never "tell us what to log"."""
    lines = [
        "Classify how each evidence record relates to the user's intended "
        "item. This is semantic classification only — do not decide what to "
        "use, do not compute totals.",
        f"\nIntended item:\n{domain.render_intent(intent)}",
        f"\nRelationship vocabulary (choose exactly one per record):",
    ]
    lines += [f"  {r}" for r in (*domain.relationships, ABSTAIN)]
    if domain.guidance:
        lines.append(f"\n{domain.guidance}")
    if domain.extraction_fields:
        lines.append(
            "\nFor each record also extract these attributes when the record "
            f"itself states them, else omit: {', '.join(domain.extraction_fields)}. "
            "Never invent a value the record does not support.")
    lines.append(
        "\nEvidence records:")
    for record in records:
        bits = [f"provider={record.provider}"]
        if record.brand:
            bits.append(f"brand={record.brand}")
        if record.title:
            bits.append(f"title={record.title!r}")
        if record.description and record.description != record.title:
            bits.append(f"description={record.description!r}")
        if record.evidence_type != "structured_record":
            bits.append(f"type={record.evidence_type}")
        lines.append(f"  [{record.evidence_id}] " + " ".join(bits))
    lines.append(
        '\nReply with ONLY a JSON array, one object per record:\n'
        '[{"evidence_id": "...", "relationship": "...", '
        '"confidence": 0.0-1.0, "extracted": {...}}]\n'
        'Use INSUFFICIENT_EVIDENCE with low confidence when you cannot tell — '
        'abstaining is correct and expected; guessing is the failure mode.')
    return "\n".join(lines)


def _abstain(record, domain, why: str) -> SemanticAssessment:
    logger.info("event=semantic_abstain evidence=%s domain=%s why=%s",
                record.evidence_id, domain.name, why)
    return SemanticAssessment(evidence_id=record.evidence_id,
                              relationship=ABSTAIN, confidence=0.0,
                              resolver_version=domain.version)


def _typed(raw, record, domain: SemanticDomain) -> SemanticAssessment:
    """One raw model object -> one typed assessment, failing closed on every
    deviation rather than repairing any of them."""
    if not isinstance(raw, dict):
        return _abstain(record, domain, "not_an_object")
    relationship = str(raw.get("relationship") or "")
    if relationship not in domain.vocabulary():
        # The model invented a category. That is information about the
        # vocabulary (§26: rising unknowns argue for extending it) but it is
        # not a classification anything downstream may act on.
        return _abstain(record, domain, f"unknown_relationship:{relationship}")
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        return _abstain(record, domain, "unparseable_confidence")
    if not (0.0 <= confidence <= 1.0):
        return _abstain(record, domain, "confidence_out_of_range")
    extracted_raw = raw.get("extracted") or {}
    extracted = {k: v for k, v in extracted_raw.items()
                 if k in domain.extraction_fields and v not in (None, "")} \
        if isinstance(extracted_raw, dict) else {}
    return SemanticAssessment(
        evidence_id=record.evidence_id, relationship=relationship,
        confidence=confidence, extracted=extracted,
        resolver_version=domain.version)


async def resolve(domain: SemanticDomain, intent, records,
                  complete: Callable) -> tuple:
    """Classify every record, one bounded batch. Returns one
    `SemanticAssessment` PER RECORD, in record order — a record the model
    skipped is an abstention, not a hole.

    `complete` is `async (prompt: str) -> str`: the caller supplies the model
    call, so core owns no API client and tests supply a script. Any failure in
    it abstains the whole batch — the boundary must degrade to "no semantic
    evidence", never crash into the logging path (§33).
    """
    records = list(records)[:MAX_RECORDS]
    if not records or domain.render_intent is None:
        return tuple(_abstain(r, domain, "no_intent_renderer")
                     for r in records)
    try:
        text = (await complete(_prompt(domain, intent, records)) or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:].strip() if text[:4].lower() == "json" else text
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("resolver reply is not a list")
    except Exception:
        logger.warning("event=semantic_resolver_failed domain=%s — abstaining "
                       "the whole batch", domain.name, exc_info=True)
        return tuple(_abstain(r, domain, "resolver_failed") for r in records)

    by_id = {}
    for raw in parsed:
        if isinstance(raw, dict) and raw.get("evidence_id"):
            by_id.setdefault(str(raw["evidence_id"]), raw)
    return tuple(
        _typed(by_id[r.evidence_id], r, domain) if r.evidence_id in by_id
        else _abstain(r, domain, "not_in_reply")
        for r in records)


def qualified(assessments, *, accept: frozenset,
              minimum_confidence: float) -> tuple:
    """THE DETERMINISTIC POLICY SEAM, in one place.

    Downstream consumers receive only assessments whose relationship is in
    `accept` AND whose confidence clears `minimum_confidence` — thresholds the
    CALLER states, because a default here would be core deciding authority.
    """
    return tuple(a for a in assessments
                 if a.relationship in accept
                 and a.confidence >= minimum_confidence)
