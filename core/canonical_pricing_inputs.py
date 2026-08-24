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


async def _address_has_one_authority(db, name_norm: str) -> bool:
    """Can this normalized address establish a single source authority?

    FLEET-WIDE ON PURPOSE. The collision is a property of the ADDRESS, not of
    who happened to log it: `banana` -> fdc 2012128 sits on four accounts, and
    a per-user test would clear the three whose own row is the bad one.

    ⭐ AGREEMENT, NOT PLAUSIBILITY. Bindings that assert the same per-100g
    numbers are the same authority re-cached; bindings that assert different
    numbers are competing ones, and a competing address cannot be authoritative
    for anybody. Exact agreement, deliberately — a tolerance would be a
    threshold, and a threshold is where nutrition judgement gets smuggled in.
    """
    # ⭐ ONE DEFINITION, IN MEMORY'S OWN HOME. Both settlement owners must obey
    # the same rule, so it lives beside the rows in `db.queries` rather than
    # inside the canonical lane — legacy reading a canonical module would be
    # the wrong dependency for a shared EVIDENCE invariant.
    from db.queries import address_has_one_authority

    return await address_has_one_authority(db, name_norm)


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

    # ⛔⛔⛔ CF23 — THE SHARED TRUST BOUNDARY. Identical call in the legacy
    # pricer; one implementation, because a guard only one owner applies is
    # what let 2026-08-16 happen (canonical declined the corrupt cucumber
    # address, legacy priced the meal from the same row).
    from db.queries import memory_nutrition_is_trusted
    if not memory_nutrition_is_trusted(row):
        logger.info("event=memory_untrusted key=%r reason=no_provenance — the "
                    "row cannot name an authority that produced its numbers, "
                    "so they are not evidence", name_norm)
        return None

    # ⛔⛔ ADMISSIBILITY: A LEGACY SURFACE KEY MAY NOT IMPERSONATE CANONICAL
    # EVIDENCE *(Danny, 2026-08-16, after the canary)*.
    #
    # `user_food_matches` records NO canonical identity — a row is keyed by a
    # lossy surface normalization, so it is evidence about a STRING, not about
    # the identity being priced. Measured fleet-wide: 19 normalized addresses
    # are bound to more than one source record, and `banana` is one of them —
    # fdc 2012128 at 312 kcal/100g for FOUR users, beside fdc 173944 at 89.
    # Canonical settlement addressed the first and committed 368 kcal where
    # legacy priced 105.
    #
    # ⭐ THE TEST IS DISAGREEMENT BETWEEN AUTHORITIES, NOT PLAUSIBILITY. No
    # calorie ranges, no food names, no per-user exceptions: an address whose
    # bindings assert DIFFERENT numbers cannot establish authority, and one
    # whose bindings agree (the same record re-cached, or two ids carrying
    # identical values) still can. Characterized before it was written —
    # `<oil>` 800.0/800.0 is a history duplicate; `tomato` 71/302 is not.
    #
    # ⭐⭐ AND THE RUNG ABSTAINS RATHER THAN GUESSING. It does not pick a
    # binding, average them, or fail the meal: it returns None and THE LADDER
    # CONTINUES — for `banana` that is ARTIFACT at usda:173944, 89 kcal/100g,
    # which is the correct 105. Nothing about pricing is redesigned.
    #
    # ⚠ READ-TIME QUARANTINE, NOT A DELETION. The rows stay exactly as they
    # are; this refuses to treat them as canonical evidence. They remain
    # available to legacy and to a later migration onto canonical identity.
    if not await _address_has_one_authority(db, name_norm):
        logger.info("event=memory_inadmissible key=%r reason=ambiguous_address "
                    "— this surface key resolves to more than one source "
                    "record; MEMORY abstains and the ladder continues",
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
                   basis_grams=None, bound: bool = False) -> dict:
    """Every rung's evidence, ready for a synchronous `price()`.

    Keyed deliberately on TWO names: `identity` is the composed food
    ("Chicken, fried") that memory and pricing speak, while `entity` and
    `preparation` are the artifact's key. Collapsing them would either lose the
    preparation from memory lookups or lose the artifact hit.

    ⛔⛔ `bound=True` — B-1.8c2.2. The item is BOUND to one exact product
    snapshot (`item["product_evidence_id"]`), and a binding CONSTRAINS the
    evidence universe: memory, artifact and estimate are NOT READ AT ALL — not
    loaded-and-outranked, not consulted. "MEMORY disagrees -> never consulted"
    must be true mechanically, and the only mechanical proof is that the read
    never happens. Pair with `price(bound=True)`, which prices that snapshot
    or refuses.
    """
    if bound:
        pid = item.get("product_evidence_id")
        if not pid:
            raise ValueError("bound assemble needs item['product_evidence_id']")
        return {"memory": None,
                "product": await _product(db, pid),
                "artifact": None,
                "estimate": None}
    return {
        "memory": await _memory(db, user_id, identity,
                                str(item.get("canonical_entity_id") or "")),
        # ⭐ P17f.4 — PRODUCT is a LOAD of a persisted snapshot, and only that.
        # The item must carry the exact `product_evidence_id` a binding step
        # recorded; a fuzzy name match must never be promoted here (`_match:
        # "exact"` once said so about a pizza), and nothing here fetches — a
        # missing snapshot is a declined rung, never a provider call. Dark
        # today: no producer writes the reference until the P17f.5 wire.
        "product": await _product(db, item.get("product_evidence_id")),
        "artifact": _artifact(entity, preparation),
        "estimate": _estimate(item, basis_grams),
    }


async def _product(db, evidence_id):
    """The snapshot this item was bound to, or None. LOCAL READ ONLY."""
    if not evidence_id:
        return None
    try:
        from skills.nutrition.product_store import load_product_evidence

        return await load_product_evidence(db, evidence_id)
    except Exception:                                    # noqa: BLE001
        # An unavailable read is NOT an absence of evidence — same rule as
        # `_memory` above: decline the rung, log, never guess.
        logger.warning("product rung unavailable for evidence_id=%s",
                       evidence_id, exc_info=True)
        return None
