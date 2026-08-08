"""ASSEMBLE what already exists. This module LOADS; it never BUILDS.

    memory     user_food_matches            a DB read
    product    exact authoritative identity  carried on the item, if any
    artifact   pricing_evidence_v1.json      a file read
    estimate   the interpreter's own numbers already on the item

NOT A GENERATOR, and the distinction is the P1's whole safety story. An
artifact MISS falls to a lower rung; it does not invoke the generator, does
not call a provider, and does not run the semantic resolver. Generation
happens offline in `scripts/build_pricing_artifact.py` or it does not happen
this turn.

This function is `async` ONLY because food memory is a database read. There is
no provider client and no model call in it, which is what keeps
`canonical_pricing.price()` able to stay synchronous — the property that makes
"no network on the settle path" structural rather than aspirational.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def _memory(db, user_id: int, identity: str):
    """This user's trusted match for the identity, as `MemoryEvidence`.

    Reuses `user_food_matches` UNCHANGED — measured at 133 ms on a warm
    production settle, and explicitly not redesigned by this P1.
    """
    from core.canonical_pricing import MemoryEvidence

    try:
        from core.food_intelligence import normalize_name
        from db.queries import get_user_food_match

        name_norm = normalize_name(identity)
        if not name_norm:
            return None
        m = await get_user_food_match(db, user_id, name_norm)
        if m is None or not getattr(m, "cal_100", None):
            return None
        per100g = {"calories": m.cal_100, "protein": m.protein_100,
                   "carbs": m.carbs_100, "fat": m.fat_100,
                   "fiber": m.fiber_100, "sugar": m.sugar_100,
                   "sodium": m.sodium_100}
        return MemoryEvidence(
            per100g={k: v for k, v in per100g.items() if v is not None},
            source_id=str(getattr(m, "fdc_id", "") or ""),
            confidence=float(getattr(m, "confidence", 0.9) or 0.9))
    except Exception:
        logger.debug("memory rung unavailable for %s", identity, exc_info=True)
        return None


def _artifact(entity: str, preparation: str):
    """Qualified structured evidence, or None. A file read; never a fetch."""
    try:
        from skills.nutrition import pricing_artifact

        return pricing_artifact.evidence_for(entity, preparation)
    except Exception:
        logger.debug("artifact rung unavailable for %s|%s", entity,
                     preparation, exc_info=True)
        return None


def _estimate(item: dict, basis_grams=None):
    """The interpreter's numbers, and the mass they described.

    `basis_grams` is what makes the estimate REPRICEABLE: it is a statement
    about a specific amount made before the user answered, not a per-portion
    constant. Its calories may be None or zero — `refuse_or_return` decides
    that is not a meal, not this function, so the failure has one owner.
    """
    from core.canonical_pricing import EstimateEvidence

    return EstimateEvidence(
        calories=item.get("calories"), protein=item.get("protein"),
        carbs=item.get("carbs"), fat=item.get("fats"),
        basis_grams=basis_grams)


async def assemble(db, *, user_id: int, entity: str, preparation: str,
                   identity: str, item: dict,
                   basis_grams=None) -> dict:
    """Every rung's evidence, ready for a synchronous `price()`.

    Keyed deliberately on TWO names: `identity` is the composed food
    ("Chicken, fried") that memory and pricing speak, while `entity` and
    `preparation` are the artifact's key. Collapsing them would either lose the
    preparation from memory lookups or lose the artifact hit.
    """
    return {
        "memory": await _memory(db, user_id, identity),
        # PRODUCT stays None until an exact authoritative identifier is
        # carried on the item. A fuzzy name match must never be promoted here:
        # `_match: "exact"` once said so about a pizza.
        "product": None,
        "artifact": _artifact(entity, preparation),
        "estimate": _estimate(item, basis_grams),
    }
