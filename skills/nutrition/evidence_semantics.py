"""FOOD MEANING for the semantic evidence boundary.

`core.semantic_evidence` owns the mechanism — invocation, schema enforcement,
abstention, the policy seam. This module owns what any of it MEANS for food:
the intent, the relationship vocabulary, the provider adapters, and the two
field projections (preparation, product variant) that prove the layer generic.

THE VOCABULARY IS DRIVEN BY MEASURED FAILURE CLASSES, not hypothetical
completeness — every member below has a real captured record behind it in
`tests/evidence_corpus/GROUND_TRUTH.md`:

    SAME_IDENTITY                  Papayas, raw                (for "papaya")
    COMPATIBLE_SPECIALIZATION      Fish, salmon, chinook, raw  (for "salmon")
    COMPOSITE_CONTAINING_IDENTITY  SPICY CHICKEN & 'NDUJA PIZZA
    DERIVED_OR_EXTRACTED_FORM      Fat, chicken · Papaya, heavy syrup
    SUBSTITUTE_OR_ANALOGUE         Chicken, meatless
    DIFFERENT_IDENTITY             Frankfurter, chicken

UNDER-SPECIFICATION IS EXPLICIT. "I had chicken" means base identity chicken
and everything else unstated. It does not mean "anything whose description
contains chicken", and it does not mean "assume chicken breast".
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

from core.semantic_evidence import (ABSTAIN, EvidenceRecord, SemanticDomain,
                                    qualified)

#: The policy identity: model + prompt + schema, one versioned unit.
VERSION = "food_evidence_semantics_v1"

#: CALIBRATED, NOT CHOSEN (2026-08-07, scripts/eval_semantic_evidence.py over
#: the captured corpus, n=41 human-labelled records):
#:
#:   claude-sonnet-5   80% exact · at conf>=0.80: 0 false-compatible,
#:                     13/20 true-compatible kept
#:   claude-haiku-4-5  78% exact · false-compatibles at 0.90/0.95 — NO
#:                     threshold separates them; the tier is disqualified,
#:                     not merely worse
#:
#: Both models reproduced the shipped papaya defect (heavy-syrup judged
#: COMPATIBLE) — Sonnet at 0.75, under the threshold; Haiku at 0.95, over it.
#: Precision > recall by design: the seven rejected true-compatibles cost
#: seven fallback lookups; one accepted false-compatible costs a wrong meal.
RESOLVER_MODEL = "claude-sonnet-5"
MINIMUM_IDENTITY_CONFIDENCE = 0.80

RELATIONSHIPS = (
    "SAME_IDENTITY",
    "COMPATIBLE_SPECIALIZATION",
    "COMPOSITE_CONTAINING_IDENTITY",
    "DERIVED_OR_EXTRACTED_FORM",
    "SUBSTITUTE_OR_ANALOGUE",
    "DIFFERENT_IDENTITY",
)

#: Which relationships can support reasoning about the intended food ITSELF.
#: A composite (pizza) or an extract (chicken fat) is ABOUT the food without
#: BEING it, and neither may reach nutrition, preparation or variant policy
#: for the original intent.
IDENTITY_BEARING = frozenset({"SAME_IDENTITY", "COMPATIBLE_SPECIALIZATION"})


@dataclass(frozen=True)
class FoodIntent:
    """What Arnie believes the user meant. Unknown stays unknown."""
    base_identity: str
    brand: str = ""
    variant: str = ""
    preparation: str = ""
    form: str = ""
    modifiers: tuple = ()

    def __post_init__(self):
        if not str(self.base_identity or "").strip():
            raise ValueError("an intent with no base identity compares "
                             "against nothing")


def _render_intent(intent: FoodIntent) -> str:
    parts = [f"base identity: {intent.base_identity}"]
    for label, value in (("brand", intent.brand), ("variant", intent.variant),
                         ("preparation", intent.preparation),
                         ("form", intent.form)):
        if value:
            parts.append(f"{label}: {value}")
    if intent.modifiers:
        parts.append(f"modifiers: {', '.join(intent.modifiers)}")
    parts.append(
        "Attributes not listed are UNSPECIFIED — an under-specified base "
        "identity, not permission for arbitrary qualifiers. A candidate that "
        "narrows it (a cut, a cooking method) is a COMPATIBLE_SPECIALIZATION; "
        "a candidate that changes what the thing IS (an extract, a composite "
        "dish, an imitation, a different product that merely names it) is not "
        "compatible.")
    return "\n".join(parts)


DOMAIN = SemanticDomain(
    name="food",
    version=VERSION,
    relationships=RELATIONSHIPS,
    # `kcal_per_100g` is DECLARED, not parsed. Web evidence states densities
    # in prose ("grilled 165, fried 250") and pulling numbers out with a regex
    # is the identity-by-string-matching this layer exists to delete. The
    # model extracts it under the closed schema instead.
    #
    # IT CANNOT PRICE A MEAL. `admissible_for_pricing` refuses
    # `synthesized_text` by TYPE, so a model-extracted density can only ever
    # answer "is this question worth asking" — never "what did they eat".
    extraction_fields=("preparation", "form", "brand", "variant",
                       "kcal_per_100g"),
    render_intent=_render_intent,
    guidance=(
        "These are food evidence records from nutrition databases and web "
        "search. Judge what each record actually DESCRIBES, not which words "
        "it shares with the intent — lexical overlap is the trap "
        "(a chicken frankfurter is not chicken; chicken fat is not chicken; "
        "a dish containing the food is not the food). Provider-reported match "
        "grades are unreliable and must be ignored. For `preparation`, "
        "normalize wording to one of: grilled, roasted, fried — otherwise "
        "omit it rather than inventing a nearby value. Extract "
        "`kcal_per_100g` ONLY when the record states energy per 100 g for "
        "that preparation of this food; omit it for a per-serving figure, a "
        "different food, or any number you would have to convert or infer."),
)


# ── provider adapters: structural mapping ONLY ──────────────────────────────

def from_usda(rows) -> tuple:
    """USDA rows -> EvidenceRecord. `description` is passed through as natural
    language — no comma parsing, no base-term extraction. That judgement is
    the resolver's."""
    out = []
    for i, row in enumerate(rows or ()):
        row = row or {}
        out.append(EvidenceRecord(
            evidence_id=f"usda:{row.get('fdc_id') or i}",
            provider="usda",
            title=str(row.get("description") or ""),
            brand=str(row.get("brand") or ""),
            nutrition=dict(row.get("per100g") or {}),
            provider_record_id=str(row.get("fdc_id") or ""),
            # PRESERVED, NOT PARSED. These are facts USDA states about the
            # row; deterministic eligibility reads them so the model does not
            # have to be asked about things a field already answers.
            structured={
                "data_type": str(row.get("data_type") or ""),
                "basis": str(row.get("basis") or ""),
                "serving_mass_g": row.get("serving_mass_g"),
                "serving_ml": row.get("serving_ml"),
            },
        ))
    return tuple(out)


def from_off(best, variants=()) -> tuple:
    """OFF best-match + siblings -> EvidenceRecord. `_match` rides in
    provider_metadata, verbatim and trusted for nothing — it said "exact"
    about a pizza."""
    out = []
    for i, product in enumerate([best, *list(variants or ())]):
        if not product:
            continue
        out.append(EvidenceRecord(
            evidence_id=f"off:{product.get('code') or i}",
            provider="off",
            title=str(product.get("name") or ""),
            brand=str(product.get("brand") or ""),
            nutrition=dict(product.get("per100g") or {}),
            provider_record_id=str(product.get("code") or ""),
            provider_metadata={"_match": product.get("_match"),
                               "serving_text": product.get("serving_text"),
                               "package_text": product.get("package_text")},
        ))
    return tuple(out)


def from_web(result) -> tuple:
    """A `core.search.SearchResult` -> EvidenceRecord[].

    The synthesized answer is ONE record typed `synthesized_text`, so policy
    can admit it per claim (materiality) and refuse it per claim (pricing).
    Individual results carry their URLs for source-quality scoring.
    """
    if result is None or getattr(result, "error", None):
        return ()
    out = []
    if getattr(result, "answer", ""):
        out.append(EvidenceRecord(
            evidence_id="web:answer", provider="web",
            description=str(result.answer),
            evidence_type="synthesized_text",
            source_reference=str(getattr(result, "query", ""))))
    for i, item in enumerate(getattr(result, "results", ()) or ()):
        item = item or {}
        out.append(EvidenceRecord(
            evidence_id=f"web:{i}", provider="web",
            title=str(item.get("title") or ""),
            source_reference=str(item.get("url") or "")))
    return tuple(out)


# ── field projections: same assessments, different views ────────────────────

@dataclass(frozen=True)
class PreparationEvidence:
    """What one identity-bearing record says about preparation. The field
    policy sees THIS — never the raw record, never the assessment's prose."""
    preparation_id: str
    kcal_per_100g: Optional[float]
    provider: str
    confidence: float
    evidence_id: str


def preparation_evidence(assessments, records, *,
                         minimum_confidence: float) -> tuple:
    """Identity-bearing assessments -> preparation states with densities.

    Only records the resolver judged to BE the food (or a specialization of
    it) participate — the fried density of a chicken sandwich is not evidence
    about chicken. The preparation value comes from the resolver's constrained
    extraction, never from tokens in the description.
    """
    by_id = {r.evidence_id: r for r in records}
    out = []
    for a in qualified(assessments, accept=IDENTITY_BEARING,
                       minimum_confidence=minimum_confidence):
        preparation = str(a.extracted.get("preparation") or "")
        if not preparation:
            continue
        record = by_id.get(a.evidence_id)
        kcal = None
        if record is not None:
            try:
                kcal = float(record.nutrition.get("calories"))
            except (TypeError, ValueError):
                kcal = None
        if kcal is None:
            # The extracted figure, for records that state a density in prose
            # rather than in a nutrition field. Materiality only — the claim
            # gate keeps it out of pricing.
            try:
                kcal = float(a.extracted.get("kcal_per_100g"))
            except (TypeError, ValueError):
                kcal = None
        out.append(PreparationEvidence(
            preparation_id=preparation, kcal_per_100g=kcal,
            provider=record.provider if record else "",
            confidence=a.confidence, evidence_id=a.evidence_id))
    return tuple(out)


@dataclass(frozen=True)
class VariantEvidence:
    """What one identity-bearing record says about which product this is —
    the §29 second consumer, sharing the SAME assessments with a different
    projection and no identity matcher of its own."""
    brand: str
    variant: str
    kcal_per_100g: Optional[float]
    provider: str
    confidence: float
    evidence_id: str


def variant_evidence(assessments, records, *,
                     minimum_confidence: float) -> tuple:
    by_id = {r.evidence_id: r for r in records}
    out = []
    for a in qualified(assessments, accept=IDENTITY_BEARING,
                       minimum_confidence=minimum_confidence):
        record = by_id.get(a.evidence_id)
        if record is None:
            continue
        brand = str(a.extracted.get("brand") or record.brand or "")
        variant = str(a.extracted.get("variant") or "")
        if not (brand or variant):
            continue
        try:
            kcal = float(record.nutrition.get("calories"))
        except (TypeError, ValueError):
            kcal = None
        out.append(VariantEvidence(
            brand=brand, variant=variant, kcal_per_100g=kcal,
            provider=record.provider, confidence=a.confidence,
            evidence_id=a.evidence_id))
    return tuple(out)
