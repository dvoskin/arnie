"""THE CANONICAL LANE PRICES ITS OWN FOOD.

    ResolvedFields (entity + preparation + quantity)
        -> memory | product | artifact | estimate      one rung wins
        -> deterministic ranking                        ~0 ms, already proven
        -> PricedFood
        -> ResolvedMeal -> canonical commit

WHY THIS EXISTS, MEASURED IN PRODUCTION 2026-08-07/08. Canonical settlement
rented its pricing from `handlers.tool_executor._analyze_food` — one import,
the ONLY thing the canonical spine took from the legacy pipeline. Everything
slow or wrong lived on the far side of it:

    settle.commit      (canonical)        17 ms
    pricing.ranking    (deterministic)     0 ms
    settle.pricing     (legacy)        8,171 ms of an 8,225 ms tap
    legacy ladder      -> Mackerel 80 g committed at 0.0 kcal / 0 g protein
    legacy qualify     -> "Chicken, fried" 120 g priced 295 then 329 kcal

The canonical parts were free and correct. So this does not optimise
`_analyze_food`; it retires it from the canonical lane.

NOT A PORT. The legacy ladder's behaviour is evidence of what NOT to inherit —
it produced a silently zero-calorie row and two different prices for one
identity. The legitimate capabilities are re-expressed here behind canonical
contracts, reusing the machinery that was never the problem: `scaling` for
portion basis, `get_user_food_match` for memory, `best_candidate` for the
deterministic winner.

⭐ THE ZERO RULE, and why it needs no food list.

A zero-calorie row is either a fact or a corruption, and the difference is
NOT the food — it is where the number came from:

    zero FROM EVIDENCE      legitimate. Black coffee is really ~0 kcal, and
                            entry 2820 is a correct row.
    zero FROM A FAILURE     corruption. Mackerel is not zero; entry 2932 is a
                            silent under-count of someone's day.

So evidence-backed rungs may return zero and the estimate rung may not. A
curated list of "foods that are allowed to be zero" would be a food-name
branch, and wrong for the first zero-calorie food nobody listed.

AND A FOOD WE CANNOT PRICE IS NOT COMMITTED. When no rung can produce a
defensible number, this returns None and settlement declines. An error the
user can see beats a row that quietly reads zero — the whole reason the
mackerel defect survived is that nothing looked wrong.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Rung(str, Enum):
    """WHICH KIND OF EVIDENCE PRICED THIS FOOD, in descending authority.

    Recorded on the result because "how confident are we" and "where did the
    number come from" are different questions, and the audit only ever
    answers the second one honestly.
    """
    #: This user has logged this exact food before and it was trusted.
    MEMORY = "memory"
    #: A branded/product record — authoritative for its own product, and
    #: admissible WITHOUT semantic qualification because a barcode or product
    #: identity is not an ambiguous string match.
    PRODUCT = "product"
    #: Qualified structured evidence from the committed artifact, ranked
    #: deterministically. The generic-food path.
    ARTIFACT = "artifact"
    #: A bounded deterministic estimate. May never be zero.
    ESTIMATE = "estimate"


#: The rungs whose numbers come from EVIDENCE about this food. Only these may
#: legitimately price something at zero.
EVIDENCE_BACKED = frozenset({Rung.MEMORY, Rung.PRODUCT, Rung.ARTIFACT})


@dataclass(frozen=True)
class PricedFood:
    """What one food costs, and what said so."""
    calories: float
    protein: float
    carbs: float
    fats: float
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    micros: Optional[dict] = None
    micros_estimated: bool = False

    rung: Rung = Rung.ESTIMATE
    #: WHICH RECORD WON. The determinism gate reads this: the same canonical
    #: input against the same artifact must select the same evidence_id, not
    #: merely land on the same calorie number by coincidence.
    evidence_id: str = ""
    #: The basis the numbers were scaled FROM (per 100 g, per serving, …),
    #: kept so a later correction has something to correct against — the
    #: defect `resolution` was added to the ledger to fix.
    basis: str = ""
    assumptions: tuple = ()

    @property
    def estimated(self) -> bool:
        return self.rung is Rung.ESTIMATE

    @property
    def evidence_backed(self) -> bool:
        return self.rung in EVIDENCE_BACKED

    def is_defensible(self) -> bool:
        """May this be committed?

        THE ONE RULE THAT WOULD HAVE STOPPED ENTRY 2932. A zero from evidence
        is a fact; a zero from an estimate is a pricing failure wearing a
        number. There is no food-name check here and there must never be one.
        """
        if self.calories > 0:
            return True
        return self.evidence_backed


class PricingRefused(Exception):
    """No rung could price this food defensibly.

    Raised rather than returned so a caller cannot accidentally treat it as a
    zero-calorie meal — which is precisely how the legacy path failed.
    """


def refuse_or_return(priced: Optional[PricedFood], *, food_name: str
                     ) -> PricedFood:
    """The single exit through which every price must pass.

    Centralised so "never commit an indefensible price" is one line that every
    rung inherits, rather than a check each rung remembers.
    """
    if priced is None:
        logger.warning("event=pricing_refused food=%s reason=no_rung",
                       food_name)
        raise PricingRefused(f"no rung could price {food_name!r}")
    if not priced.is_defensible():
        logger.warning(
            "event=pricing_refused food=%s reason=zero_without_evidence "
            "rung=%s — a zero from a failed estimate is a silent under-count, "
            "not a fact about the food", food_name, priced.rung.value)
        raise PricingRefused(
            f"{food_name!r} priced at zero from {priced.rung.value}, which is "
            f"not evidence")
    logger.info("event=canonical_priced food=%s rung=%s kcal=%.0f evidence=%s",
                food_name, priced.rung.value, priced.calories,
                priced.evidence_id or "-")
    return priced
