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


# ══ THE EVIDENCE THE PRICER CONSUMES ════════════════════════════════════════
#
# EVERY RUNG IS HANDED ITS EVIDENCE. Nothing here retrieves: no provider
# client, no model call, no `await` on a network. That is not a style rule —
# it is Gate B, and it is what makes a canonical settle survive with provider
# and resolver access poisoned. Acquisition belongs to adapters upstream, the
# same boundary `preparation_activation` already holds for materiality.


@dataclass(frozen=True)
class MemoryEvidence:
    """This user has logged this food before and the match was trusted.
    Straight from `user_food_matches` — measured at 133 ms in production, and
    the reason a warm settle is already fast."""
    per100g: dict
    source_id: str = ""
    confidence: float = 0.9


@dataclass(frozen=True)
class ProductEvidence:
    """An EXACT authoritative product: barcode, GTIN, or a provider record
    identified by one.

    Admissible without semantic qualification because a barcode is not an
    ambiguous string match — it names one product. A FUZZY OFF NAME MATCH IS
    NOT THIS, and must never be constructed here: `_match: "exact"` once said
    so about a pizza.
    """
    identifier: str
    per100g: dict
    serving_grams: Optional[float] = None
    source_id: str = ""


@dataclass(frozen=True)
class ArtifactEvidence:
    """Qualified structured candidates for (entity, preparation), read from the
    committed pricing artifact.

    QUALIFIED CANDIDATES, NOT A CHOSEN WINNER. The artifact stores the evidence
    a model judged admissible; `best_candidate` — deterministic, measured at
    0 ms — still picks. Storing the winner would move ranking authority into a
    model, which is the opposite of the fix.
    """
    candidates: tuple = ()
    fingerprint: str = ""


@dataclass(frozen=True)
class EstimateEvidence:
    """The interpreter's own numbers. The last rung, and the only one that may
    not price at zero.

    ⭐ IT CARRIES THE QUANTITY IT DESCRIBED. An estimate is not a per-portion
    constant — it is a statement about a SPECIFIC amount made before the user
    answered. Treating it as final breaks B-1.75's whole contract: measured in
    the suite, 50 g and 100 g both committed 200.0 kcal, so the answered
    quantity stopped being the authority the moment the artifact missed.

    `basis_grams` is the mass the estimate described, so answering reprices it.
    Without it the number is unscalable and the estimate is used as-is — which
    is honest only when no basis was ever stated.
    """
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    basis_grams: Optional[float] = None


def _profile(per100g: dict, *, source: str, source_id: str,
             confidence: float, estimated: bool):
    """A per-100 g profile, with unknown fields left UNKNOWN.

    `profile_from_values` drops None, so a missing sodium stays missing rather
    than becoming a confident zero — the same distinction the zero rule makes
    one level up.
    """
    from skills.nutrition.models import profile_from_values

    return profile_from_values(
        source=source, basis="per_100g", confidence=confidence,
        estimated=estimated, source_id=source_id,
        **{k: v for k, v in (per100g or {}).items()})


def _from_memory(ev: MemoryEvidence):
    return (_profile(ev.per100g, source="memory", source_id=ev.source_id,
                     confidence=ev.confidence, estimated=False),
            Rung.MEMORY, ev.source_id or "memory", dict(ev.per100g or {}))


def _from_product(ev: ProductEvidence):
    return (_profile(ev.per100g, source="product", source_id=ev.identifier,
                     confidence=0.95, estimated=False),
            Rung.PRODUCT, ev.identifier, dict(ev.per100g or {}))


def _ranker_query(entity: str, preparation: str) -> str:
    """The composed identity, or the entity if the artifact cannot say.

    The ranker must be asked about the SAME identity the artifact was keyed
    by; asking it about the bare entity threw away evidence that had already
    been found. Falling back to `entity` keeps a pricing rung from depending
    on an import — a rung that cannot rank is a rung that cannot price.
    """
    try:
        from skills.nutrition.pricing_artifact import priced_identity

        return priced_identity(entity, preparation) or entity
    except Exception:
        logger.warning("identity composition failed for %r", entity,
                       exc_info=True)
        return entity


def _from_artifact(ev: ArtifactEvidence, *, query: str):
    """Qualified candidates -> the deterministic winner.

    `best_candidate` is the ranker production already uses and the one the
    trace measured at 0 ms. Passing it ONLY qualified candidates is the whole
    change: the legacy path ranked over raw rows, which is how one identity
    priced 295 kcal and then 329.
    """
    from core.food_intelligence import best_candidate

    winner, _conf = best_candidate(query, list(ev.candidates or ()))
    if not winner:
        return None
    per100g = winner.get("per100g") or {}
    if not per100g:
        return None
    fdc = str(winner.get("fdc_id") or "")
    return (_profile(per100g, source="usda", source_id=fdc,
                     confidence=0.85, estimated=False),
            Rung.ARTIFACT, f"usda:{fdc}" if fdc else "usda", dict(per100g))


def _from_estimate(ev: EstimateEvidence):
    """The bounded fallback, REPRICED against the answer when it can be.

    The estimate described `basis_grams`; the user answered something else. So
    it is scaled like any other basis rather than being handed through — the
    difference between "answering reprices the meal" and "answering changes
    the label on the same number".
    """
    if ev.calories is None:
        return None
    profile = _profile({"calories": ev.calories, "protein": ev.protein,
                        "carbs": ev.carbs, "fat": ev.fat},
                       source="estimate", source_id="", confidence=0.4,
                       estimated=True)
    return profile, Rung.ESTIMATE, "", {}


def price(*, entity: str, preparation: str = "", consumed=None,
          memory: Optional[MemoryEvidence] = None,
          product: Optional[ProductEvidence] = None,
          artifact: Optional[ArtifactEvidence] = None,
          estimate: Optional[EstimateEvidence] = None) -> PricedFood:
    """What this food costs. SYNCHRONOUS, and deliberately so.

    A synchronous signature is the strongest possible statement of Gate B:
    there is no `await` here, so no provider or model call can hide in the
    normal settle path. Evidence arrives already gathered.

    RUNG ORDER IS AUTHORITY ORDER — memory, product, artifact, estimate — and
    the first rung that can produce numbers wins. `refuse_or_return` is the
    single exit, so no rung can smuggle out an indefensible price.
    """
    from skills.nutrition.models import MACRO_FIELDS
    from skills.nutrition.scaling import (Per100g, PerServing,
                                          ScalingRefused,
                                          scale_profile)

    # A NON-POSITIVE PORTION IS NOT A MEAL. Scaling 165 kcal/100 g by zero
    # grams yields a legitimate-looking zero from an EVIDENCE-backed rung, so
    # `is_defensible` would wave it through — the mackerel defect returning
    # through a different door. The degenerate thing here is the portion, not
    # the food, so it is refused before any rung runs.
    if consumed is not None:
        _mass = getattr(consumed, "grams", None)
        if _mass is not None and float(_mass) <= 0:
            logger.warning("event=pricing_refused food=%s reason=portion_mass "
                           "grams=%s", entity, _mass)
            raise PricingRefused(f"{entity!r} has a non-positive portion mass")

    # ⭐ SCALING HAPPENS INSIDE THE LOOP, so an unscalable rung FALLS THROUGH.
    #
    # It used to run after a winner was chosen, which made "this rung's basis
    # cannot be massed" fatal to the whole meal. Measured adversarially: a
    # count-only answer ("1 breast") has no grams, `scale_profile` refuses a
    # per-100 g basis, and a perfectly good estimate on the next rung never
    # got its turn — the meal was refused instead of priced at 280 kcal. A
    # rung that cannot be scaled has simply failed; the ladder continues.
    #
    # `ScalingRefused` is also not `PricingRefused`, so escaping here would
    # bypass the narrow handler in `b1_answer_turn` and take the whole turn
    # down — worse than the zero-calorie row this P1 exists to delete.
    priced = None
    for ev, build in ((memory, _from_memory), (product, _from_product),
                      (artifact, lambda e: _from_artifact(
                          e, query=_ranker_query(entity, preparation))),
                      (estimate, _from_estimate)):
        if ev is None:
            continue
        try:
            chosen = build(ev)
        except Exception:
            logger.warning("rung failed for %s", entity, exc_info=True)
            continue
        if not chosen:
            continue
        profile, rung, evidence_id, raw_per_basis = chosen
        before = profile.amount("calories")

        basis_name = "per_portion"
        if consumed is not None:
            try:
                if rung is Rung.ESTIMATE:
                    # Per ITS OWN quantity, not per 100 g. Without a stated
                    # basis there is nothing to scale FROM, so it stands as
                    # given: it is already a statement about a portion, and an
                    # unscalable answer costs precision, not the meal.
                    grams = getattr(ev, "basis_grams", None)
                    if grams:
                        profile = scale_profile(
                            profile, PerServing(serving_mass_g=float(grams),
                                                as_served=True), consumed)
                        basis_name = "per_serving"
                else:
                    profile = scale_profile(profile, Per100g(), consumed)
                    basis_name = "per_100g"
            except ScalingRefused as exc:
                logger.info("event=rung_unscalable food=%s rung=%s — %s",
                            entity, rung.value, exc)
                continue

        # ⭐ THE FULL MICRONUTRIENT SET SURVIVES, scaled by the same factor.
        #
        # `NutrientProfile` models only six micros (MICRO_FIELDS), but a USDA
        # row carries ~22 — calcium, iron, the vitamins — and legacy stored all
        # of them in `micronutrients_json`. Reading micros back off the profile
        # alone would silently drop about nineteen from every canonical row.
        # So they are scaled from the RAW per-basis dict, by the factor the
        # profile itself moved by, which keeps one scaling authority.
        after = profile.amount("calories")
        factor = (float(after) / float(before)) if (before and after) else 1.0
        micros = {k: round(float(v) * factor, 4)
                  for k, v in (raw_per_basis or {}).items()
                  if k not in MACRO_FIELDS and k not in ("fiber", "sugar",
                                                         "sodium")
                  and isinstance(v, (int, float))}
        priced = PricedFood(
            calories=float(profile.amount("calories") or 0.0),
            protein=profile.amount("protein"),
            carbs=profile.amount("carbs"),
            fats=profile.amount("fat"),
            fiber=profile.amount("fiber"), sugar=profile.amount("sugar"),
            sodium=profile.amount("sodium"),
            micros=micros or None, micros_estimated=(rung is Rung.ESTIMATE),
            rung=rung, evidence_id=evidence_id, basis=basis_name)
        # AN INDEFENSIBLE PRICE IS ALSO A FAILED RUNG. Continuing is what turns
        # "the estimate was zero" into "try the next thing" rather than
        # "refuse the meal".
        if priced.is_defensible():
            break
        priced = None

    return refuse_or_return(priced, food_name=entity)
