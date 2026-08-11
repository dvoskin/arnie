"""PHASE 0 — DETERMINISTIC ELIGIBILITY, the layer between evidence and opinion.

    evidence  ->  DETERMINISTIC ELIGIBILITY  ->  advisory semantics  ->  ranking
                  (this module)                  (the model)            (code)

WHY THIS EXISTS. Build-time qualification held stochastic authority: two
artifact builds from identical seeds produced different evidence, because a
model decided every dimension and its verdicts varied. `temperature` is not
available on the resolver model, so determinism cannot be bought by
configuring it. It has to come from the model deciding LESS.

Everything here is decided from STRUCTURED FIELDS THE PROVIDER STATES —
`data_type`, `basis`, a serving mass, an identifier. Not from prose, not from
a phrase table, and not from anything a language model produced. Given the
same record, this returns the same verdict forever.

⭐ ELIGIBILITY VETOES; IT NEVER ADMITS. Every rule answers exactly one
question — "is this record MECHANICALLY INCOMPATIBLE with the claim?" — and
the only outcomes are a reasoned veto or silence. A rule that could ADMIT
would be a second authority on identity, which is the defect this migration
removes rather than relocates.

⭐⭐ AND A VETO IS NOT AN ABSTENTION. The whole point of the invariant this
session produced —

    AN ABSENT ANSWER MUST NEVER BE REPRESENTABLE AS A NEGATIVE ANSWER

— is that "we could not evaluate" and "this is incompatible" are different
outcomes with different consequences. `Ineligible` carries a REASON from a
closed vocabulary; there is deliberately no reason meaning "unknown", because
a rule that cannot evaluate its dimension must stay silent rather than
manufacture a negative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from skills.nutrition import cooking_state

#: Bumped when a rule is added, removed, or changes meaning. The artifact
#: records it, so a candidate that disappears between builds is attributable
#: to a POLICY CHANGE rather than filed as unexplained drift.
ELIGIBILITY_POLICY_VERSION = "food_eligibility_v1"

#: The closed vocabulary of mechanical vetoes. A cause that is not here is not
#: a mechanical cause, and belongs to the advisory layer.
BRANDED_FOR_GENERIC = "branded_record_for_generic_intent"
INCOMPATIBLE_BASIS = "nutrition_basis_not_convertible"
NO_ENERGY = "record_states_no_energy"
DUPLICATE = "duplicate_of_an_earlier_record"
COOKING_STATE_CONFLICT = "cooking_state_conflicts_with_the_request"
COOKING_MEDIUM_CONFLICT = "cooking_medium_conflicts_with_the_request"

REASONS = frozenset({BRANDED_FOR_GENERIC, INCOMPATIBLE_BASIS, NO_ENERGY,
                     DUPLICATE, COOKING_STATE_CONFLICT,
                     COOKING_MEDIUM_CONFLICT})

#: USDA's own record classification. CURATED data types are generic reference
#: foods; `Branded` rows are manufacturer-submitted product entries.
_CURATED = frozenset({"foundation", "sr legacy", "survey (fndds)"})

#: Bases the pricing path can actually scale from. `scaling.py` owns the
#: conversion; this only refuses one it could never perform.
_SCALABLE_BASES = frozenset({"per_100g", "per_100ml", "per_serving"})


@dataclass(frozen=True)
class Ineligible:
    """One mechanical veto, with the dimension and reason that produced it."""
    evidence_id: str
    reason: str
    detail: str = ""

    def __post_init__(self):
        if self.reason not in REASONS:
            raise ValueError(
                f"{self.reason!r} is not a mechanical veto reason. A cause "
                f"that is not structural belongs to the advisory layer, where "
                f"it cannot delete evidence")


def _text(record, key: str) -> str:
    return str((getattr(record, "structured", None) or {}).get(key) or "")


def _is_branded(record) -> bool:
    """From the provider's OWN classification, never from the description.

    `data_type` is a field USDA sets. Reading it is not string matching in the
    sense this codebase forbids — the forbidden thing is inferring identity
    from prose, and a record's own type is neither prose nor identity.
    """
    data_type = _text(record, "data_type").strip().lower()
    if not data_type:
        return False          # unknown: SILENT, never a veto
    return data_type not in _CURATED


def _energy(record) -> Optional[float]:
    try:
        value = (getattr(record, "nutrition", None) or {}).get("calories")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _duplicate_key(record):
    """What makes two records the SAME evidence rather than two opinions.

    Identifier first — two rows with one id are one row. Otherwise an exact
    energy+protein match on an identical title, which is USDA re-publishing a
    food under two ids. Deliberately strict: near-equality would start
    deciding that two foods are the same, which is identity work.
    """
    identifier = str(getattr(record, "provider_record_id", "") or "")
    if identifier:
        return ("id", identifier)
    nutrition = getattr(record, "nutrition", None) or {}
    return ("value", str(getattr(record, "title", "")).strip().lower(),
            nutrition.get("calories"), nutrition.get("protein"))


def vetoes(records, *, generic_intent: bool = True,
           requested_identity: str = "") -> tuple:
    """Every mechanical veto over these records, in record order.

    `requested_identity` is the composed identity being priced — "mackerel,
    roasted". Supplied rather than derived, because composing it is the
    identity boundary's job and this module must not become a second place
    that knows how. When it is empty the cooking-state rule simply does not
    apply, which is silence, not approval.

    `generic_intent` says whether the user named a PRODUCT. Asking for
    "chicken" and being handed a manufacturer's breaded-nugget entry is a
    mechanical mismatch; asking for a brand by name is not, and then the rule
    does not apply. Supplied by the caller because whether an intent is
    branded is the caller's knowledge, not this module's.
    """
    out, seen = [], set()
    for record in records or ():
        evidence_id = str(getattr(record, "evidence_id", "") or "")

        key = _duplicate_key(record)
        if key in seen:
            out.append(Ineligible(evidence_id, DUPLICATE, detail=str(key)))
            continue
        seen.add(key)

        if generic_intent and _is_branded(record):
            out.append(Ineligible(evidence_id, BRANDED_FOR_GENERIC,
                                  detail=_text(record, "data_type")))
            continue

        basis = _text(record, "basis").strip().lower()
        if basis and basis not in _SCALABLE_BASES:
            out.append(Ineligible(evidence_id, INCOMPATIBLE_BASIS,
                                  detail=basis))
            continue

        # ⭐ THE DIMENSION THAT ACTUALLY CAUSED THE INSTABILITY. A request for
        # a ROASTED food cannot be served by a row that states it is RAW, and
        # establishing that needs no language model. Both sides must classify
        # and conflict; anything else is silence.
        if requested_identity and cooking_state.conflict(
                requested_identity, getattr(record, "title", "")):
            out.append(Ineligible(evidence_id, COOKING_STATE_CONFLICT,
                                  detail=cooking_state.classify(
                                      getattr(record, "title", "")).value))
            continue

        # 0.3 — INCOMPATIBLE HEAT MEDIA. Deliberately narrower than "a
        # different preparation": a specific method never conflicts with the
        # generic term containing it (roasted vs "cooked, dry heat" are both
        # DRY), and grilled vs roasted is a real difference that is not a
        # mechanical incompatibility, so it stays with ranking. Only genuinely
        # exclusive media veto — roasted vs stewed, roasted vs fried.
        if requested_identity and cooking_state.medium_conflict(
                requested_identity, getattr(record, "title", "")):
            out.append(Ineligible(
                evidence_id, COOKING_MEDIUM_CONFLICT,
                detail=cooking_state.medium(getattr(record, "title", "")).value))
            continue

        energy = _energy(record)
        if energy is None:
            # A record with no energy cannot price ANYTHING. This is a veto
            # rather than silence because the absence is the record's own
            # statement about itself, not our failure to evaluate it.
            out.append(Ineligible(evidence_id, NO_ENERGY))
    return tuple(out)


def ineligible_ids(records, *, generic_intent: bool = True,
                   requested_identity: str = "") -> frozenset:
    return frozenset(v.evidence_id for v in vetoes(
        records, generic_intent=generic_intent,
        requested_identity=requested_identity))
