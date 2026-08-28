"""THE ONE ASK-TYPE VOCABULARY.

⛔⛔⛔ TWO VOCABULARIES EXISTED AND DISAGREED. `core/food_turn._KIND_PHRASING`
said `portion|identity|preparation|extras|detail`; the
`note_food_clarification` tool schema said
`portion|brand|cook_method|ingredient|other`. They agreed on `portion` and
diverged everywhere else. That is the four-tables condition
`skills/nutrition/materiality.py` was written to end, recreated one layer up —
so this module is the single vocabulary, and a structural test forbids a second.

⭐⭐⭐ CLASSIFICATION IS FROM THE INTERPRETER'S STRUCTURED `field`, NEVER FROM
QUESTION TEXT. The mechanism being replaced, `_FACET_KINDS`, matched prose
needles ("how much", "grilled", "toppings") against the rendered question — a
classifier reconstructing intent from the words it had just generated. A type
recovered from prose is a guess about a decision the system already made.

Measured 2026-08-27 over 158 turns / 105 asks
(`docs/ASK_TYPE_TAXONOMY_2026-08-27.md`): the seven types below, of which
`portion` alone conflated THREE with different defaults, and one —
`consumption_complete` — was inexpressible in either old vocabulary. The one
ask type with no defensible food-knowledge default was the one the system could
not name.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

#: ⭐ A quantity question on a BRANDED item: the chain publishes an enumerable
#: size set with known values, so a modal default exists ("medium").
MENU_SIZE = "menu_size"
#: A quantity question on an unbranded item. A default exists (standard
#: serving) but is inherently softer than a menu size.
CONTINUOUS_PORTION = "continuous_portion"
#: ⛔ "Did you finish it?" — USER STATE, not food knowledge. NO amount of
#: nutrition data yields this. EXCLUDED from defaultability by decision
#: (Danny, 2026-08-27).
CONSUMPTION_COMPLETE = "consumption_complete"
#: "Grilled or pan-seared?" — owned by the OILS tranche, not by defaulting.
PREPARATION_FAT = "preparation_fat"
#: "Any toppings?" — default is "as stated, nothing more".
UNSTATED_EXTRAS = "unstated_extras"
#: "Single or double scoop?" inside a fixed container. Default is single.
PORTION_MULTIPLIER = "portion_multiplier"
#: "Little or regular?", "whole or half?" — an IDENTITY question. Belongs to
#: the canonical identity lane, not to a defaulting policy.
IDENTITY_VARIANT = "identity_variant"
#: ⭐ NOT A TYPE — the absence of one. A field this module cannot map is
#: recorded AS unmapped rather than folded into a real type: a silently
#: mis-bucketed ask corrupts the denominator that a policy is sized against.
#: A rising `unclassified` rate is the signal that the vocabulary has drifted
#: from what the interpreter emits.
UNCLASSIFIED = "unclassified"

ALL = (MENU_SIZE, CONTINUOUS_PORTION, CONSUMPTION_COMPLETE, PREPARATION_FAT,
       UNSTATED_EXTRAS, PORTION_MULTIPLIER, IDENTITY_VARIANT, UNCLASSIFIED)

#: Types for which a defensible default may exist. `CONSUMPTION_COMPLETE` is
#: absent BY DECISION, not by oversight. `PREPARATION_FAT` is absent because
#: OILS owns it; `IDENTITY_VARIANT` because it is not a portion question.
DEFAULTABLE_CANDIDATES = (MENU_SIZE, CONTINUOUS_PORTION, UNSTATED_EXTRAS,
                          PORTION_MULTIPLIER)

#: The interpreter's own `ambiguities[].field` vocabulary → this one.
#: Quantity-shaped fields are deliberately absent: they need the ITEM to split
#: MENU_SIZE from CONTINUOUS_PORTION, so they are handled in `classify`.
_FIELD_MAP = {
    "consumed": CONSUMPTION_COMPLETE,
    "prep": PREPARATION_FAT, "preparation": PREPARATION_FAT,
    "cook_method": PREPARATION_FAT, "cooking": PREPARATION_FAT,
    "extras": UNSTATED_EXTRAS, "ingredient": UNSTATED_EXTRAS,
    "ingredients": UNSTATED_EXTRAS, "toppings": UNSTATED_EXTRAS,
    "identity": IDENTITY_VARIANT, "brand": IDENTITY_VARIANT,
    "variant": IDENTITY_VARIANT, "flavor": IDENTITY_VARIANT,
    "flavour": IDENTITY_VARIANT, "type": IDENTITY_VARIANT,
}
_QUANTITY_FIELDS = frozenset({"quantity", "amount", "portion", "size",
                              "servings", "count"})

#: Legacy values from the two retired vocabularies, for reading historical rows.
#: ⚠ `portion` MAPS TO CONTINUOUS_PORTION AND THAT IS LOSSY. Historical
#: `portion` rows conflate MENU_SIZE, CONTINUOUS_PORTION and PORTION_MULTIPLIER.
#: **Never size a MENU_SIZE policy from pre-instrumentation rows.**
LEGACY_MAP = {
    "portion": CONTINUOUS_PORTION,      # ⚠ lossy — see above
    "identity": IDENTITY_VARIANT, "brand": IDENTITY_VARIANT,
    "preparation": PREPARATION_FAT, "cook_method": PREPARATION_FAT,
    "extras": UNSTATED_EXTRAS, "ingredient": UNSTATED_EXTRAS,
    "detail": UNCLASSIFIED, "other": UNCLASSIFIED, "clarify": UNCLASSIFIED,
    "confirm": IDENTITY_VARIANT,
}


def classify(field: Optional[str], *, branded: bool = False) -> str:
    """One ambiguity → one type, from STRUCTURE only.

    `branded` is what separates a menu size from a continuous portion: a
    quantity question about a Shake Shack fries has an enumerable answer set
    with published values; the same question about "a side of rice" does not.
    """
    f = (field or "").strip().lower()
    if not f:
        return UNCLASSIFIED
    if f in _QUANTITY_FIELDS:
        return MENU_SIZE if branded else CONTINUOUS_PORTION
    return _FIELD_MAP.get(f, UNCLASSIFIED)


def classify_all(ambiguities: Optional[Iterable[dict]],
                 items: Optional[Sequence[dict]] = None) -> tuple:
    """Every type present in ONE ask, deduplicated, in vocabulary order.

    ⭐ A TUPLE, NOT A SCALAR. Asks are COMPOUND: case 2 asks about identity,
    consumption, extras and portion in one turn. Recording a single type per
    ask would silently discard most of what was asked, and the discarded part
    is exactly what a per-type policy needs to see.
    """
    if not ambiguities:
        return ()
    branded_by_name = {}
    for it in (items or ()):
        name = str((it or {}).get("food") or (it or {}).get("name") or "").strip().lower()
        if name:
            branded_by_name[name] = bool((it or {}).get("branded"))
    found = set()
    for a in ambiguities:
        if not isinstance(a, dict):
            continue
        item = str(a.get("item") or "").strip().lower()
        # An unrecognised item name means unknown brandedness, which must not
        # silently read as "not branded" — that would push every unmatched
        # quantity ask into CONTINUOUS_PORTION and understate MENU_SIZE, the
        # very type the first policy experiment is sized against.
        branded = branded_by_name.get(item)
        found.add(classify(a.get("field"),
                           branded=bool(branded) if branded is not None else False))
    return tuple(t for t in ALL if t in found)


#: ⭐⭐⭐ THE STAGED CLARIFICATION PIPELINE'S OWN VOCABULARY
#: (`skills/nutrition/ambiguity.AmbiguityType`) → this one.
#:
#: ⛔⛔ THE STAGED PIPELINE IS A SECOND ASK AUTHORITY, and until 2026-08-27 the
#: typing code read the INTERPRETER's `data["ambiguities"]` even for asks the
#: pipeline raised. Confirmed by durable-row provenance: 3/3 `unclassified`
#: asks carried `question_id` + `staged_item_id`; 0/10 interpreter-typed asks
#: did. The asks were never unstructured — they were structured HERE.
#:
#: ⚠ AND THIS STORE IS RICHER THAN THE INTERPRETER'S. It distinguishes
#: `consumed_quantity` and `component_breakdown` natively — two subjects
#: recorded as having ZERO producers when only the interpreter store was read.
_STAGED_MAP = {
    "consumed_quantity": CONSUMPTION_COMPLETE,
    "package_size": MENU_SIZE,
    "preparation": PREPARATION_FAT,
    "component_breakdown": UNSTATED_EXTRAS,
    "product_identity": IDENTITY_VARIANT,
    "product_line": IDENTITY_VARIANT,
    "product_variant": IDENTITY_VARIANT,
    "unit_interpretation": CONTINUOUS_PORTION,
    # `serving_basis` ("what the label's numbers mean") has NO canonical
    # subject. Left unmapped ON PURPOSE rather than folded into a portion type
    # — that is the CF28 question, and mis-bucketing it would corrupt the
    # denominator a defaultability policy is sized against.
}


def classify_staged(field: Optional[str]) -> str:
    """One staged `AmbiguityType` / requested field → one canonical type."""
    return _STAGED_MAP.get((field or "").strip().lower(), UNCLASSIFIED)


def classify_all_staged(questions: Optional[Iterable]) -> tuple:
    """Canonical types for a STAGED-PIPELINE ask, read from the producer that
    raised it.

    ⭐ THE AUTHORITY RULE: a durable measurement of a semantic outcome must
    identify the producer that owned that outcome and read from THAT producer's
    state. Typing a pipeline-raised ask from the interpreter's store is how ~150
    turns were spent characterising a defect that was an instrument looking in
    the wrong place.
    """
    found = set()
    for q in (questions or ()):
        for f in (getattr(q, "requested_fields", None) or ()):
            found.add(classify_staged(str(f)))
    return tuple(t for t in ALL if t in found)


def from_legacy(kind: Optional[str]) -> str:
    """Read a historical `kind` from either retired vocabulary. Lossy for
    `portion` — see `LEGACY_MAP`."""
    return LEGACY_MAP.get((kind or "").strip().lower(), UNCLASSIFIED)
