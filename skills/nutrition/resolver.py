"""Candidate selection and resolution (review 2026-07-25, work order steps 4/5).

candidates.py fetches. This decides. The separation means fetch order can be
whatever is fastest while winner priority stays a deliberate policy:

    user label > saved regular > branded exact > generic exact > estimate
                                                              > provisional

within which a better MATCH GRADE wins, because a branded source can still be
a poor match for what the user actually ate.

Three things this does that a ladder cannot:

  • it can lose. A candidate that fails identity or bounds validation is
    rejected WITH ITS REASON, and the reason travels on the resolution — "we
    picked USDA's garlic powder" is only diagnosable if the alternatives are
    in the log next to the winner.
  • it can mix. Macros from a label and sodium from an exact USDA match is a
    legitimate answer, and field-level provenance makes it expressible.
  • it can say "I don't know". A field nothing established stays unknown
    rather than being filled with zero or a neighbouring candidate's guess.

Mode does not decide what is TRUE. It decides when uncertainty is worth
interrupting the user for.
"""
from __future__ import annotations

import logging
from typing import Optional

from skills.nutrition.candidates import Candidate
from skills.nutrition.models import (FoodResolutionRequest,
                                     NormalizedQuantity, NutrientProfile,
                                     NutritionResolution, ResolutionAmbiguity)
from skills.nutrition.normalize import normalize_quantity
from skills.nutrition.provenance import (CandidateRejection, DECISIVE_GRADES,
                                         MatchGrade, SourceTier)
from skills.nutrition.scaling import (Per100g, ScalingRefused, scale_profile,
                                      scaling_uncertainty)
from skills.nutrition import validators as V

logger = logging.getLogger(__name__)

RESOLVER_VERSION = "nutrition_resolver_v1"

#: Grade ranking within a tier. A branded source with a category-only match
#: should not beat a branded source that matched the exact product.
_GRADE_RANK = {MatchGrade.EXACT: 0, MatchGrade.CLOSE: 1,
               MatchGrade.CATEGORY: 2, MatchGrade.WEAK: 3, MatchGrade.NONE: 4}

#: Calorie spans that justify interrupting, per mode. Mirrors the interpreter's
#: ASK_THRESHOLDS deliberately: one ladder, two places it is consulted.
ASK_SPANS = {"quick": 300.0, "moderate": 200.0, "strict": 100.0}

#: Micros worth pulling from a lower-tier candidate when the winner is silent.
#: Macros are never mixed — a calorie count from one source and protein from
#: another describes no real food.
_MIXABLE_FIELDS = ("fiber", "sugar", "sodium", "saturated_fat", "cholesterol",
                   "potassium")


def _grade(request: FoodResolutionRequest, candidate: Candidate) -> str:
    """How well this candidate matches what was asked for. The candidate's own
    reported grade is an input, not the answer — a source reporting "exact"
    means it matched its own index, not that it matched the user."""
    verdict = V.validate_identity(
        request.food_name, candidate.name,
        requested_brand=request.brand, candidate_brand=candidate.brand,
        requested_variant=request.variant, candidate_variant=candidate.variant)
    if verdict.outcome == V.REJECT:
        return MatchGrade.NONE
    if verdict.outcome == V.DOWNGRADE:
        return MatchGrade.CATEGORY
    return candidate.reported_grade or MatchGrade.CLOSE


def score(request: FoodResolutionRequest, candidate: Candidate) -> tuple:
    """Sort key — lower is better. Tier first, then match grade, then the
    source's own confidence. Never the order it was fetched in."""
    grade = _grade(request, candidate)
    confidence = candidate.profile.get("calories")
    conf = confidence.confidence if confidence is not None else 0.0
    return (int(candidate.tier), _GRADE_RANK.get(grade, 4), -conf)


def _validate(request: FoodResolutionRequest,
              candidate: Candidate) -> tuple:
    """(kept_profile, rejection). A rejection means the candidate is out; a
    kept profile may still have had impossible fields dropped to unknown."""
    grade = _grade(request, candidate)
    if grade == MatchGrade.NONE:
        return None, CandidateRejection(
            candidate.source, candidate.name, "identity_conflict",
            f"{request.food_name!r} vs {candidate.name!r}",
            candidate.source_id)

    energy = V.validate_energy(candidate.profile)
    if energy.outcome == V.REJECT:
        return None, CandidateRejection(
            candidate.source, candidate.name, energy.reason, energy.detail,
            candidate.source_id)

    basis = getattr(candidate.basis, "basis", "per_serving")
    bounds, bad_fields = V.validate_bounds(candidate.profile,
                                           request.food_name, basis=basis)
    if bounds.outcome == V.REJECT:
        return None, CandidateRejection(
            candidate.source, candidate.name, bounds.reason, bounds.detail,
            candidate.source_id)

    profile = candidate.profile
    if bad_fields:
        # The field was wrong, so we no longer know it. Dropping it to unknown
        # keeps the good macros and refuses to assert a value we disproved.
        profile = V.strip_out_of_bounds(profile, bad_fields)
        logger.info(f"nutrition: dropped out-of-bounds {','.join(bad_fields)} "
                    f"from {candidate.source} for {request.food_name!r}")
    return profile, None


def _mix_micros(winner_profile: NutrientProfile, others: list,
                request: FoodResolutionRequest) -> tuple:
    """Fill UNKNOWN micros from the best remaining candidate that knows them.

    Macros are never mixed: calories from one source and protein from another
    describes no real food. Micros are different — a label rarely lists
    potassium, and an exact USDA match for the same food legitimately does.
    """
    profile, notes = winner_profile, []
    for candidate in others:
        missing = [f for f in _MIXABLE_FIELDS if profile.amount(f) is None]
        if not missing:
            break
        if _grade(request, candidate) not in DECISIVE_GRADES:
            continue
        fill = {f: candidate.profile.get(f) for f in missing
                if candidate.profile.get(f) is not None}
        if not fill:
            continue
        profile = profile.with_values(**fill)
        notes.append(f"{', '.join(sorted(fill))} from {candidate.source}")
    return profile, tuple(notes)


def _ambiguities(request: FoodResolutionRequest, winner: Candidate,
                 runners: list, quantity: NormalizedQuantity,
                 scaled: NutrientProfile,
                 unscaled: Optional[NutrientProfile] = None) -> tuple:
    """Everything still genuinely uncertain, sized by what it costs. Reporting
    is unconditional; whether to ASK is the caller's decision with the mode.

    `unscaled` is the winner's own row, used ONLY to size doubt when scaling
    was refused and `scaled` is therefore empty. Refusing to scale is the
    resolver's least certain state, and sizing every span off an empty profile
    reported that state as zero doubt — which silenced the ask ladder exactly
    where it was most needed. The magnitude comes from the row; the ANSWER
    never does.
    """
    out = []
    item_cal = scaled.amount("calories") or 0.0
    if item_cal <= 0 and unscaled is not None:
        item_cal = unscaled.amount("calories") or 0.0

    def _fraction(span: float) -> float:
        return round(span / item_cal, 3) if item_cal > 0 else 1.0

    for other in runners[:2]:
        gap = V.sources_disagree(winner.profile, other.profile)
        if gap and _grade(request, other) in DECISIVE_GRADES:
            out.append(ResolutionAmbiguity(
                field="nutrient_values",
                options=(f"{winner.source}: {gap['options'][0]}",
                         f"{other.source}: {gap['options'][1]}"),
                calorie_span=gap["calorie_span"],
                protein_span=gap["protein_span"],
                detail="two high-confidence sources disagree materially",
                calorie_fraction=_fraction(gap["calorie_span"])))
    # A named product answered by a generic database row.
    #
    # From a shipped transcript: "15 peanut m&m" logged at 135 calories "from
    # the USDA database". A standard label puts 15 pieces near 175. The tier
    # order preferred branded correctly — there simply was no branded
    # candidate, so a generic won unopposed and was then presented with the
    # same confidence as a label read off the packet.
    #
    # What was missing is that a generic standing in for a NAMED PRODUCT is a
    # different kind of answer, and the user is entitled to know that is what
    # happened.
    if _is_branded_request(request) and int(winner.tier) >= int(
            SourceTier.GENERIC_EXACT):
        out.append(ResolutionAmbiguity(
            field="branded_source",
            options=(f"{winner.name} (generic)",),
            calorie_span=round(item_cal * BRANDED_FALLBACK_DOUBT, 1),
            detail="generic data standing in for a named product",
            calorie_fraction=BRANDED_FALLBACK_DOUBT))

    span = scaling_uncertainty(winner.profile, winner.basis, quantity)
    if span:
        out.append(ResolutionAmbiguity(
            field="portion_size", options=(quantity.describe(),),
            calorie_span=span,
            detail="portion mass is estimated, not stated",
            calorie_fraction=_fraction(span)))
    if quantity.grams is None and quantity.count is not None:
        out.append(ResolutionAmbiguity(
            field="serving_basis", options=(quantity.describe(),),
            calorie_span=item_cal,
            detail="no known mass for this portion",
            calorie_fraction=1.0))
    return tuple(out)


#: How wrong a generic row can be about a specific product, as a fraction of
#: the item's own calories. Generic "candies, chocolate coated peanuts" against
#: the Peanut M&M's label is roughly this far apart on the count that shipped,
#: and branded formulations vary at least that much from a category average.
#:
#: Sizes the doubt; never changes the number. The resolver does not know the
#: label — it knows it is not reading one.
BRANDED_FALLBACK_DOUBT = 0.3


def _is_branded_request(request: FoodResolutionRequest) -> bool:
    """Whether the user named a PRODUCT rather than a food.

    Three signals, any of which is enough: the interpreter set a brand, it
    flagged the item as packaged, or the name matches a known product family.
    """
    if request.brand or request.is_packaged:
        return True
    try:
        from skills.nutrition.families import rule_for
        return rule_for(request.brand, request.food_name) is not None
    except Exception:
        return False


#: A doubt covering this much of an item's own calories is worth asking about
#: even when its absolute size is small — being 100% wrong about an 80-calorie
#: bagel is not a small error. Applied below quick mode only, since quick
#: exists precisely to accept that risk.
MATERIAL_FRACTION = 0.5
FRACTION_FLOOR = 50.0


def should_ask(ambiguities: tuple, mode: str) -> Optional[ResolutionAmbiguity]:
    """The strictness ladder, applied to resolution uncertainty. Returns the
    ambiguity worth interrupting for, or None.

    This decides WHEN to ask — never which value is true. A mode change must
    not change the nutrition answer, only the friction.
    """
    mode = (mode or "moderate").lower()
    threshold = ASK_SPANS.get(mode, ASK_SPANS["moderate"])
    worst = None
    for a in ambiguities or ():
        material = a.calorie_span >= threshold
        if not material and mode != "quick":
            material = (a.calorie_fraction >= MATERIAL_FRACTION
                        and a.calorie_span >= FRACTION_FLOOR)
        if not material:
            continue
        if worst is None or a.calorie_span > worst.calorie_span:
            worst = a
    return worst


def resolve(request: FoodResolutionRequest, candidates: list) -> NutritionResolution:
    """Score, validate, select, scale — in that order, every time.

    Never raises. An unresolvable request returns a provisional resolution
    carrying the reason, because a food turn that cannot answer still has to
    answer.
    """
    quantity = normalize_quantity(request.raw_quantity or "",
                                  request.food_name)
    rejections, viable = [], []

    for candidate in sorted(candidates or [],
                            key=lambda c: score(request, c)):
        profile, rejection = _validate(request, candidate)
        if rejection is not None:
            rejections.append(rejection)
            continue
        viable.append(Candidate(
            source=candidate.source, tier=candidate.tier, name=candidate.name,
            profile=profile, basis=candidate.basis, brand=candidate.brand,
            variant=candidate.variant, source_id=candidate.source_id,
            reported_grade=candidate.reported_grade,
            serving_text=candidate.serving_text))

    if not viable:
        return NutritionResolution(
            canonical_name=request.food_name, quantity=quantity,
            nutrients=NutrientProfile(), source="unresolved",
            tier=SourceTier.PROVISIONAL, match_grade=MatchGrade.NONE,
            confidence=0.0,
            warnings=("no candidate survived validation",),
            rejected_candidates=tuple(rejections),
            resolver_version=RESOLVER_VERSION)

    winner, runners = viable[0], viable[1:]
    merged, mix_notes = _mix_micros(winner.profile, runners, request)

    warnings = []
    try:
        scaled = scale_profile(merged, winner.basis, quantity)
    except ScalingRefused as e:
        # The source's own unscaled numbers are NOT a fallback. They describe a
        # different portion than the one eaten, and persisting them logged one
        # tablespoon of peanut butter as 588 calories — the per-100g row, with
        # a warning nobody sees, in the day's totals. Two tablespoons logged as
        # 588 as well, so answering the clarification changed nothing.
        #
        # This is "unknown is not zero" applied one level up: unknown is also
        # not "the wrong portion". An unscalable portion produces no nutrients,
        # which is a state the ask ladder and `promotable()` can both act on.
        warnings.append(f"portion not scaled: {e}")
        scaled = NutrientProfile()

    grade = _grade(request, winner)
    ambiguities = _ambiguities(request, winner, runners, quantity, scaled,
                               unscaled=merged)
    cal_value = scaled.get("calories")
    confidence = cal_value.confidence if cal_value is not None else 0.0
    if grade not in DECISIVE_GRADES:
        confidence *= 0.6

    assumptions = tuple(quantity.assumptions) + mix_notes
    if winner.tier.is_estimate:
        assumptions += (f"{winner.source} estimate, not a label",)
    if _is_branded_request(request) and int(winner.tier) >= int(
            SourceTier.GENERIC_EXACT):
        # Disclosure rather than a question. Asking about every named product
        # with no branded record would interrupt constantly; saying which kind
        # of source answered costs nothing and is the difference between "135
        # calories" and "135 calories, from generic data".
        assumptions += (
            f"generic data for a named product — no {request.food_name} "
            f"label available",)
        confidence *= 0.75
    if scaled.unknown():
        warnings.append(f"unknown: {', '.join(scaled.unknown())}")

    return NutritionResolution(
        canonical_name=winner.name or request.food_name,
        quantity=quantity, nutrients=scaled, source=winner.source,
        tier=winner.tier, source_id=winner.source_id, match_grade=grade,
        confidence=round(confidence, 3), assumptions=assumptions,
        warnings=tuple(warnings), ambiguities=ambiguities,
        rejected_candidates=tuple(rejections),
        resolver_version=RESOLVER_VERSION)


def resolution_log(request: FoodResolutionRequest,
                   resolution: NutritionResolution,
                   turn_id: str = "", entry_id=None) -> dict:
    """One structured line per resolution. This is what turns nutrient
    failures from anecdotes into queries."""
    n = resolution.nutrients
    return {
        "turn_id": turn_id,
        "entry_id": entry_id,
        "requested_name": request.food_name,
        "canonical_name": resolution.canonical_name,
        "source": resolution.source,
        "tier": resolution.tier.label,
        "match_grade": resolution.match_grade,
        "basis": resolution.quantity.describe(),
        "calories": n.amount("calories"),
        "protein": n.amount("protein"),
        "confidence": resolution.confidence,
        "unknown_fields": list(n.unknown()),
        "assumptions": list(resolution.assumptions),
        "warnings": list(resolution.warnings),
        "rejected": [{"source": r.source, "name": r.name, "reason": r.reason}
                     for r in resolution.rejected_candidates],
        "resolver_version": resolution.resolver_version,
    }
