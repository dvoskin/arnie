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
    is unconditional; whether to ASK is the caller's decision with the mode."""
    out = []
    # `scaled` is empty when the portion could not be scaled at all — which is
    # exactly the case that most needs a question. Sizing the doubt from the
    # source's own row keeps it the right order of magnitude; a span of zero
    # would rank the worst case as the least worth asking about.
    item_cal = (scaled.amount("calories")
                or (unscaled.amount("calories") if unscaled else None) or 0.0)

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
    elif not span and _mass_is_a_loose_guess(quantity):
        # The portion HAS an estimated mass, the estimate is loose, and the
        # source scales by count or serving — so the looseness never reached
        # `span` and would otherwise be silent. Having a number is not the same
        # as knowing it: "a plate" resolving to 400 g ± 200 g is a wider doubt
        # than having no mass at all, and it must not be quieter.
        share = min(1.0, quantity.uncertainty_g / quantity.grams)
        out.append(ResolutionAmbiguity(
            field="serving_basis", options=(quantity.describe(),),
            calorie_span=round(item_cal * share, 1),
            detail="portion mass is a broad estimate",
            calorie_fraction=round(share, 3)))
    return tuple(out)


#: Above this ratio of uncertainty to mass, an estimated portion is a guess
#: rather than an estimate. Chosen to sit above the ontology's category rows
#: (a handful of nuts is 30 g ± 11) and below its broad fallbacks (a plate is
#: 400 g ± 200) — which is exactly the line the ask ladder should care about.
LOOSE_MASS_RATIO = 0.4


def _mass_is_a_loose_guess(quantity: NormalizedQuantity) -> bool:
    if not quantity.grams or not quantity.uncertainty_g:
        return False
    return quantity.uncertainty_g / quantity.grams >= LOOSE_MASS_RATIO


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
    from core import food_trace
    with food_trace.stage(food_trace.Stage.RESOLVE) as timed:
        out = _resolve(request, candidates)
        timed.counts.update(candidates=len(candidates or ()),
                            rejected=len(out.rejected_candidates or ()),
                            ambiguities=len(out.ambiguities or ()))
        if out.source == "unresolved":
            timed.outcome = food_trace.Outcome.HELD
            timed.detail = "unresolved"
    return out


def _resolve(request: FoodResolutionRequest,
             candidates: list) -> NutritionResolution:
    """The resolution itself. Split from `resolve` only so the timing wrapper
    has one exit to measure — resolve has several, and timing each of them
    separately is how one of them ends up untimed."""
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
            # The portion was still normalized, and what we assumed about it
            # is still true. Dropping those on the unresolved path left the
            # turn unable to say "I read that as a 400 g plate" at the exact
            # moment the user most needs to know what we thought they ate.
            assumptions=tuple(quantity.assumptions),
            warnings=("no candidate survived validation",),
            rejected_candidates=tuple(rejections),
            resolver_version=RESOLVER_VERSION)

    winner, runners = viable[0], viable[1:]
    # A candidate that lost on precedence lost. It was previously dropped
    # silently, which made "why USDA and not the label?" unanswerable from the
    # resolution alone — the one question this object exists to answer. Fields
    # borrowed from a runner are still reported by the mix notes below; losing
    # the selection and contributing a micro are not mutually exclusive.
    rejections.extend(
        CandidateRejection(
            r.source, r.name, "outranked",
            f"{winner.source} ({winner.tier.label}) ranked higher",
            r.source_id)
        for r in runners)
    merged, mix_notes = _mix_micros(winner.profile, runners, request)

    warnings = []
    try:
        scaled = scale_profile(merged, winner.basis, quantity)
    except ScalingRefused as e:
        # The source's own unscaled numbers are NOT a fallback. They describe a
        # different portion than the one that was eaten, and persisting them
        # logged a teaspoon of sugar as 387 calories — the per-100g row, with a
        # warning nobody sees, in the day's totals.
        #
        # This is the "unknown is not zero" rule applied one level up: unknown
        # is also not "the wrong portion". An unscalable portion produces no
        # nutrients, which is the state the ask ladder can act on.
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
