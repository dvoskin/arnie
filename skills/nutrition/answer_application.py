"""Applying an answer to a resolution we already have — cause A's second half.

The codec (`staged_codec`) lets a resolution outlive its turn. This is what the
answering turn does with it: settle the answered field on the stored item and
price the result **from the numbers already on it**, so answering a question
costs no lookup at all.

That is the whole point of the exercise. Today an answer turn re-interprets the
raw message and re-runs the enrichment ladder, which is why the three slowest
turns in the production window were all re-enrichments of a food priced one turn
earlier — 16.2s to re-price a cheesecake whose estimate we had computed and
thrown away, and which came back disagreeing with itself (the ask said 10 g of
protein, the answer logged 8 g).

**Two rules decide whether this path may run at all.**

*An answer that changes identity is not an application.* "Actually it was the
sopressata" replaces the thing being priced, so the stored per-100g basis
describes a different food and re-resolution is correct. Only an answer that
settles a portion, a preparation or a variant of the SAME food may be applied
arithmetically. `_identity_fields` is the test, and it is deliberately broad:
being wrong in this direction prices the wrong food, so anything touching
identity declines.

*Refusing is normal, and it is free.* Every failure here returns None, and the
caller's fallback is the interpreter turn it runs today. So this may only
commit when it is certain: a winning candidate, a profile, a basis it can name,
and a portion `scale_profile` will accept. `ScalingRefused` exists precisely
because a per-serving row without a serving mass cannot be scaled by a vague
helping, and inventing a factor there is how a 400 g plate becomes "one
serving". We decline and pay for the lookup instead.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

#: Answering any of these replaces the food, so the stored pricing no longer
#: describes it. Kept as names rather than as a check on the resolved object,
#: because the decision has to be made from the ANSWER, before anything is
#: applied.
_IDENTITY_FIELDS = frozenset({
    "canonical_name", "brand", "product_line", "variant", "barcode",
    "package_size",
})

#: Fields the caller may settle arithmetically.
_APPLICABLE_FIELDS = frozenset({
    "stated_amount", "stated_unit", "consumed_fraction", "container_count",
    "estimated_mass_g", "method", "modifiers",
})


def changes_identity(values: Mapping) -> bool:
    """Whether this answer replaces the food rather than describing it."""
    return any(k in _IDENTITY_FIELDS for k in (values or {}))


def find_item(items, staged_item_id: str = ""):
    """The item the question was bound to. Falls back to the sole item, and to
    nothing at all when the choice would be a guess — applying an answer to the
    wrong row is the failure this whole mechanism exists to prevent."""
    items = tuple(items or ())
    if not items:
        return None
    if staged_item_id:
        for item in items:
            if item.staged_item_id == staged_item_id:
                return item
        return None
    return items[0] if len(items) == 1 else None


def apply_answer(item, values: Mapping):
    """Settle the answered fields on the stored item. Pure.

    Returns None when the answer changes identity — the caller re-resolves —
    and when there is nothing applicable to settle.
    """
    if item is None or not values:
        return None
    if changes_identity(values):
        return None
    fields = {k: v for k, v in values.items() if k in _APPLICABLE_FIELDS}
    if not fields:
        return None
    quantity_fields = {k: v for k, v in fields.items()
                       if k not in ("method", "modifiers")}
    resolved = item.resolving(**quantity_fields) if quantity_fields else item
    if "method" in fields:
        # A preparation the user has now STATED. `stated=True` is the whole
        # point of recording it here: §4.2b's "pan fried" became a standing
        # default on later steaks precisely because a value we inferred was
        # indistinguishable from one they gave.
        from dataclasses import replace as _replace
        resolved = _replace(
            resolved,
            preparation=_replace(resolved.preparation,
                                 method=str(fields["method"]), stated=True))
    return resolved


def _best_candidate(item):
    """The candidate the ask was priced from.

    Delegates so the ask and the answer cannot rank the same set differently —
    which they did while this picked the highest `overall_score`. That score
    measures how well the WORDS line up, so with a real mixed-tier set (the
    label, USDA, the user's own regular) the row whose name matched best won
    over the row whose numbers described the product. `SourceTier` is the
    precedence the resolver already applies at write time; one definition of
    it, in `ask_candidates`, is the point of the join.
    """
    from skills.nutrition.ask_candidates import best_candidate
    return best_candidate(item)


def _normalized_portion(item, candidate):
    """The consumed quantity, in a shape `scale_profile` accepts — or None.

    Conservative by design. A mass we know, or a count against a basis that
    genuinely counts, and nothing else. Anything vaguer is exactly the case the
    scaler refuses, and guessing here would put a number on the board that no
    lookup ever produced.
    """
    from skills.nutrition.models import NormalizedQuantity

    q = item.quantity
    grams = q.estimated_mass_g
    unit = (q.unit or "").strip().lower()
    amount = q.amount
    if grams is None and amount is not None and unit in ("g", "gram", "grams"):
        grams = float(amount)
    if grams is not None:
        return NormalizedQuantity(amount=float(amount if amount is not None
                                               else grams),
                                  unit=unit or "g", grams=float(grams),
                                  unit_label=q.descriptor or "")
    # No mass. A count is only usable when the source's numbers are per unit or
    # per serving — counting servings of a per-100g row means nothing.
    basis = (candidate.serving_basis or "").strip().lower()
    if basis in ("per_serving", "per_unit") and amount is not None:
        return NormalizedQuantity(amount=float(amount), unit=unit or "serving",
                                  count=float(amount),
                                  unit_label=q.descriptor or "")
    return None


def price_from_resolution(item) -> Optional[dict]:
    """The item priced from its OWN stored numbers, as an interpreter-shaped
    item dict ready for `_log_call`. None whenever anything is missing.

    The macros here are the same ones the question was asked against, which is
    what stops the ask and the answer disagreeing about the same food.
    """
    if item is None:
        return None
    try:
        from skills.nutrition.scaling import ScalingRefused, basis_from_spec
        from skills.nutrition.scaling import scale_profile

        candidate = _best_candidate(item)
        if candidate is None:
            return None
        declared = (candidate.serving_basis or "").strip().lower()
        if not declared:
            # Fall back to what the numbers themselves declare — a
            # NutrientValue carries its own basis, and a candidate that never
            # set `serving_basis` is common enough that refusing on it alone
            # would make this path unreachable.
            first = next(iter(candidate.nutrient_profile.values.values()), None)
            declared = (getattr(first, "basis", "") or "").strip().lower()
        if declared not in ("per_100g", "per_100ml", "per_serving", "per_unit"):
            return None
        portion = _normalized_portion(item, candidate)
        if portion is None:
            return None
        basis = basis_from_spec(
            declared,
            as_served=bool(getattr(candidate.tier, "is_estimate", False)),
            serving_mass_g=(item.quantity.estimated_mass_g
                            if declared in ("per_serving", "per_unit")
                            else None))
        try:
            scaled = scale_profile(candidate.nutrient_profile, basis, portion)
        except ScalingRefused as refused:
            # The documented, expected outcome for a vague helping against a
            # measured serving. One lookup is the correct price for it.
            logger.info(f"event=answer_apply outcome=scaling_refused "
                        f"reason={refused}")
            return None

        calories = scaled.amount("calories")
        if calories is None:
            return None

        out: dict[str, Any] = {
            # The row is named by the SAME describe() that named the card and
            # the question — no second name-builder that could disagree with
            # them. It used to be one, patching a canonical name that
            # describe() dropped; describe() keeps the name now. The
            # interpreter's own words stand in when there is no identity at
            # all, clipped to what a row will hold.
            "food": (item.identity.describe() or item.original_text)[:60],
            "calories": calories,
        }
        for field, key in (("protein", "protein"), ("carbs", "carbs"),
                           ("fat", "fats")):
            value = scaled.amount(field)
            if value is not None:
                out[key] = value
        amount, unit = item.quantity.amount, item.quantity.unit
        if amount is not None:
            out["amount"] = amount
        if unit:
            out["unit"] = unit
        # The user gave the number that settled this, so the write says so
        # rather than calling its own arithmetic an estimate.
        out["basis"] = "stated" if item.quantity.is_stated else "estimate"
        if item.food_class.value == "branded":
            out["branded"] = True
        assumptions = [{"text": a.user_visible_text}
                       for a in (item.assumptions or ()) if a.user_visible_text]
        if assumptions:
            out["_assumed"] = assumptions[:3]
        return out
    except Exception as e:
        logger.warning(f"answer application unavailable: {e}")
        return None


def commit_from_answer(staged_payload, staged_item_id: str,
                       values: Mapping) -> Optional[dict]:
    """The whole path, for the answering turn: decode, apply, price.

    None means "this turn is not a zero-lookup commit" — every caller's
    fallback is the interpreter pass it already runs.
    """
    from skills.nutrition.staged_codec import decode_items

    items = decode_items(staged_payload)
    if not items:
        return None
    item = find_item(items, staged_item_id)
    resolved = apply_answer(item, values)
    if resolved is None:
        return None
    return price_from_resolution(resolved)
