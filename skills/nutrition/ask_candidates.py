"""Ask-time candidates — the producer `StagedFoodItem.candidate_products` never had.

The 07-30 architecture audit's root finding (§8.1): ask time and write time are
two disjoint worlds joined only by the food's NAME as a string.

    ask time    core.food_pipeline.plan_turn — staging, ambiguity, materiality.
                Identity, quantity, spans. **No pricing.**
    write time  handlers.tool_executor -> shadow.candidates_from_live ->
                resolver.resolve -> scaling. **Pricing, then discarded.**

Every production resolution stored by the ask path carried
`candidate_products: null` and `anchor: None`, because in the whole repository
the only things that ever assigned that field were tests and the codec's own
decoder. So the answering turn held a pointer to an identity with no product
behind it, `FOOD_ANSWER_APPLY` declined 100% of the time, and a correction had
nothing to correct against but the string it started from.

This module is the adapter that closes it. It takes the rows the turn has
**already fetched** — the Open Food Facts variants pulled for the spread, the
speculative USDA/OFF lookup started while the interpreter was still writing —
and expresses them as the scored `ProductCandidate` set the staged item is
declared to hold.

**Nothing here reaches the network, and nothing here may raise.** Both rules are
load-bearing, for the same reason: a candidate set is an improvement to a
decision the turn can already make without it. A fetch on this path would put
the ask behind a product database; an exception would cost the turn its
question. A failure is an empty tuple and the behaviour we ship today.

Built on `shadow.candidates_from_live`, deliberately. That function is the one
place that knows the shape of each live source, and a second reader of those
shapes here is how the two halves drift back apart — which is the defect this
module exists to end, arriving one layer higher up.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


def _as_product(candidate) -> Optional[Any]:
    """One resolver `Candidate` as a `ProductCandidate`.

    The two types describe the same thing from opposite ends of the boundary —
    a source's answer, and one of the things this food might be — and the
    fields that matter to the answering turn are the ones that survive here:
    the ANCHOR (`source_id`), the BASIS (`serving_basis`), the profile, and the
    tier that says how directly the numbers describe this product.

    `serving_basis` comes from the basis object's own spec string rather than
    being re-derived from the source name. `answer_application.price_from_
    resolution` reads exactly that field to decide whether it may scale, so a
    candidate that dropped it would be a candidate nothing could price.
    """
    from skills.nutrition.candidate_sets import ProductCandidate

    profile = getattr(candidate, "profile", None)
    if profile is None or not (getattr(profile, "values", None) or {}):
        return None
    basis = getattr(candidate, "basis", None)
    return ProductCandidate(
        candidate_id="",          # assigned by build_candidate_set
        canonical_name=str(getattr(candidate, "name", "") or ""),
        brand=getattr(candidate, "brand", None),
        variant=getattr(candidate, "variant", None),
        serving_basis=str(getattr(basis, "basis", "") or ""),
        source=str(getattr(candidate, "source", "") or "provisional"),
        tier=candidate.tier,
        source_id=getattr(candidate, "source_id", None),
        nutrient_profile=profile,
        match_grade=str(getattr(candidate, "reported_grade", "") or "none"))


def candidates_for(food_name: str, *, brand: Optional[str] = None,
                   is_packaged: bool = False,
                   memory: Optional[Mapping] = None,
                   usda: Optional[Mapping] = None,
                   off: Optional[Mapping] = None,
                   variants: Sequence[Mapping] = ()) -> tuple:
    """The scored candidate set for one staged food, from rows already in hand.

    `variants` are the siblings Open Food Facts returned for the spread — the
    other products sharing this name. They are the reason a variant question
    can be asked at all, and until now they were reduced to a per-nutrient span
    and thrown away, so the ask knew the shelf disagreed and could not say what
    it disagreed about.

    The interpreter's own estimate is deliberately NOT seated here. It is not
    something the shelf says, it is already carried on the raw item, and as a
    candidate it would outrank every real source on name overlap — the stored
    resolution would then be the model quoting itself.
    """
    try:
        from skills.nutrition.candidate_sets import build_candidate_set
        from skills.nutrition.shadow import candidates_from_live

        name = (food_name or "").strip()
        if not name:
            return ()
        inp = {"is_packaged": bool(is_packaged)}
        found = list(candidates_from_live(name, inp, memory=memory or None,
                                          usda=usda or None, off=off or None))
        for row in (variants or ()):
            if not isinstance(row, Mapping) or not (row.get("per100g") or {}):
                continue
            # Each sibling goes through the SAME adapter as the primary Open
            # Food Facts hit — same envelope, same tier, same basis — so a
            # variant cannot end up described differently from the product it
            # is a variant of.
            found.extend(candidates_from_live(name, {}, off=dict(row)))

        products = [p for p in (_as_product(c) for c in found) if p is not None]
        if not products:
            return ()
        return tuple(build_candidate_set(products, requested_name=name,
                                         requested_brand=brand))
    except Exception as e:                       # never costs the turn its ask
        logger.warning(f"ask-time candidates unavailable for "
                       f"{food_name!r}: {e}")
        return ()


def best_candidate(item) -> Optional[Any]:
    """The candidate a stored resolution should be priced from.

    **Authority first, match quality second.** Ranking on `overall_score` alone
    ranks on name/brand/variant overlap, which is a measure of how well the
    words line up and says nothing about whether the numbers describe this
    product — so a provisional row named exactly as asked outranks the label
    that was actually read. `SourceTier` is the repo's existing answer to that
    question and the resolver already sorts by it; this is the same precedence,
    applied where the answering turn reads.
    """
    scored = [c for c in (getattr(item, "candidate_products", None) or ())
              if c.nutrient_profile is not None
              and (c.nutrient_profile.values or {})]
    if not scored:
        return None
    return min(scored, key=lambda c: (int(c.tier), -c.overall_score))
