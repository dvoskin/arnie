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


async def _memory(db, user_id: int, identity: str,
                  canonical_entity_id: str = ""):
    """This user's trusted match for the identity, as `MemoryEvidence`.

    ⛔ THIS RUNG WAS DEAD FOR EVERY ROW IN PRODUCTION UNTIL 2026-08-14, and
    nothing said so. It did `float(m.confidence)` on a column holding
    `'likely'`, `'exact'`, `'estimated'`, `'user-confirmed'` — each of which
    raises — inside a bare `except Exception` that logged at DEBUG and returned
    None. 836 of 836 rows. `Rung.MEMORY` is the TOP of the ladder, so the
    canonical lane has been pricing from artifact and estimate alone since it
    was written, and every gate over it asserted that the function was CALLED.

    ⭐ THE REPAIR IS A NAMED BOUNDARY, NOT A GUESSED MAPPING.
    `food_intelligence.confidence_score` is the repository's already-declared
    grade vocabulary; inventing numbers at this call site is how policy gets
    smuggled into a type conversion.

    ⭐⭐ AND ABSENCE IS NOW DISTINGUISHABLE FROM INCOMPATIBILITY. "This user has
    no memory of this food" and "a row exists and we could not read it" are
    different facts that had one spelling. The first is silent and expected;
    the second is a WARNING naming the row, because a rung that fails
    permanently must be loud enough to notice.
    """
    from core.canonical_pricing import MemoryEvidence

    from core.food_intelligence import confidence_score, memory_key
    from db.queries import get_user_food_match

    # ⭐ THE RESOLVED IDENTITY WHEN THERE IS ONE, today's key when there is
    # not. `memory_key` is shared with the legacy lane deliberately: two
    # definitions of "which row is this food's" is how a cache comes to be
    # written where nobody reads it.
    name_norm = memory_key(identity, canonical_entity_id)
    if not name_norm:
        return None
    try:
        row = await get_user_food_match(db, user_id, name_norm)
    except Exception:
        # ⚠ NARROW, AND LOUD. Only the DB call is guarded here; anything else
        # failing is a defect that must not wear "no memory" as a disguise.
        logger.warning("event=memory_rung_unavailable key=%r user=%s — the "
                       "lookup itself failed; this is not an absence",
                       name_norm, user_id, exc_info=True)
        return None
    if row is None:
        return None                       # EXPECTED ABSENCE. Silent, correct.
    if not getattr(row, "cal_100", None):
        logger.info("event=memory_row_unusable key=%r reason=no_per100g_calories",
                    name_norm)
        return None

    score = confidence_score(getattr(row, "confidence", None))
    if score is None:
        # A grade nobody declared. The MACROS are still evidence, so the row is
        # not discarded over its metadata — but the unmapped word is named,
        # because silently substituting a number is what broke this rung.
        logger.warning("event=memory_confidence_unmapped key=%r value=%r — "
                       "using MemoryEvidence's declared default; add the grade "
                       "to food_intelligence._CONF_NUM if it is real",
                       name_norm, getattr(row, "confidence", None))

    per100g = {"calories": row.cal_100, "protein": row.protein_100,
               "carbs": row.carbs_100, "fat": row.fat_100,
               "fiber": row.fiber_100, "sugar": row.sugar_100,
               "sodium": row.sodium_100}
    evidence = {"per100g": {k: v for k, v in per100g.items() if v is not None},
                "source_id": str(getattr(row, "fdc_id", "") or "")}
    # Omitted rather than defaulted here, so the dataclass's OWN declared
    # default applies and there is exactly one place that number lives.
    if score is not None:
        evidence["confidence"] = score
    return MemoryEvidence(**evidence)


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
        "memory": await _memory(db, user_id, identity,
                                str(item.get("canonical_entity_id") or "")),
        # PRODUCT stays None until an exact authoritative identifier is
        # carried on the item. A fuzzy name match must never be promoted here:
        # `_match: "exact"` once said so about a pizza.
        "product": None,
        "artifact": _artifact(entity, preparation),
        "estimate": _estimate(item, basis_grams),
    }
