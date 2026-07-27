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
from dataclasses import replace
from typing import Optional

from skills.nutrition.candidates import Candidate
from skills.nutrition.models import (FoodResolutionRequest,
                                     NormalizedQuantity, NutrientProfile,
                                     NutritionResolution, ResolutionAmbiguity)
from skills.nutrition.normalize import (MASS_UNKNOWN, count_units_compatible,
                                        normalize_quantity, serving_unit_mass)
from skills.nutrition.provenance import (CandidateRejection, DECISIVE_GRADES,
                                         MatchGrade, SourceTier)
from skills.nutrition.scaling import (Per100g, ScalingRefused, scale_profile,
                                      scaling_spans, scaling_uncertainty)
from skills.nutrition import validators as V

logger = logging.getLogger(__name__)

RESOLVER_VERSION = "nutrition_resolver_v1"

#: Grade ranking within a tier. A branded source with a category-only match
#: should not beat a branded source that matched the exact product.
_GRADE_RANK = {MatchGrade.EXACT: 0, MatchGrade.CLOSE: 1,
               MatchGrade.CATEGORY: 2, MatchGrade.WEAK: 3, MatchGrade.NONE: 4}

#: Calorie spans that justify interrupting, per mode. Mirrors the interpreter's
#: ASK_THRESHOLDS deliberately: one ladder, two places it is consulted.
#:
#: Left at 300/200/100 by the PR #31 calibration, after a detour worth
#: recording.
#:
#: The sweep first recommended 250/120/60, because two granolas 65 calories
#: apart on a 60 g serving went unasked in strict. Lowering the absolute
#: threshold would have caught them — and would also have started interrupting
#: on 80 calories of doubt in a 900-calorie platter, which is noise. The two
#: requirements are incompatible on the absolute axis: nothing satisfies
#: "ask at 65" and "stay quiet at 80" at once.
#:
#: They separate cleanly on the RELATIVE axis — 22% of the item against 9% —
#: which is what MATERIAL_FRACTION is for. So the absolute thresholds stayed
#: and the fraction rule moved. The lesson is in the sweep's blind spot: the
#: platter expectation lived in a unit test rather than the gold suite, so the
#: sweep could not see the conflict. It is a labelled gold case now.
from skills.nutrition.materiality import (  # noqa: E402
    FRACTION_FLOOR, MATERIAL_FRACTIONS, calorie_threshold, thresholds_for)

#: Derived. These were the CALIBRATED numbers — the sweep is recorded below —
#: which is why the shared policy adopted them rather than the staged
#: pipeline's self-described placeholders.
ASK_SPANS = {m: calorie_threshold(m) for m in ("quick", "moderate", "strict")}

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
    # `scaled` is empty when the portion could not be scaled at all — which is
    # exactly the case that most needs a question. Sizing the doubt from the
    # source's own row keeps it the right order of magnitude; a span of zero
    # would rank the worst case as the least worth asking about.
    item_cal = (scaled.amount("calories")
                or (unscaled.amount("calories") if unscaled else None) or 0.0)

    def _fraction(span: float) -> float:
        return round(span / item_cal, 3) if item_cal > 0 else 1.0

    for other in runners[:2]:
        # Compare the candidates AT THE PORTION, not per 100 g.
        #
        # The per-100g comparison sized every cross-source doubt in the wrong
        # units: two granolas 109 cal/100g apart became a "109 calorie" span on
        # a 60 g serving whose real gap was 65, and `calorie_fraction` divided
        # that per-100g number by a portion-scale total — overstating the doubt
        # ~3× on a small portion and understating it ~3× on a large one. Every
        # threshold in the ask ladder was being compared against a number in
        # the wrong unit (PR #31 calibration).
        gap = V.sources_disagree(_at_portion(winner, quantity),
                                 _at_portion(other, quantity))
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

    spans = scaling_spans(winner.profile, winner.basis, quantity)
    span = spans.get("calories")
    if spans:
        out.append(ResolutionAmbiguity(
            field="portion_size", options=(quantity.describe(),),
            calorie_span=span or 0.0,
            # A mass doubt scales protein exactly as it scales energy. Leaving
            # this at zero told the ladder protein was certain when the mass
            # was not.
            protein_span=spans.get("protein", 0.0),
            detail="portion mass is estimated, not stated",
            calorie_fraction=_fraction(span or 0.0)))
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


def _at_portion(candidate: Candidate,
                quantity: NormalizedQuantity) -> NutrientProfile:
    """This candidate's numbers for the portion actually eaten.

    Falls back to the unscaled profile when the candidate's basis cannot be
    reconciled with the portion — a comparison in mixed units is still more
    informative than no comparison, and the alternative is dropping the
    ambiguity entirely on exactly the turns that are hardest to scale.
    """
    try:
        return scale_profile(candidate.profile, candidate.basis, quantity)
    except ScalingRefused:
        return candidate.profile


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

    Asks `skills.nutrition.branded` at STRONG, the same module the executor's
    source gate asks at WEAK+. Sharing it is the fix: this used to accept only
    an explicit brand, the is_packaged flag, or a product-family rule, so
    "Peanut M&Ms" was not a branded request and the disclosure below never
    fired on the very transcript it was written for.

    STRONG and not WEAK+, because this gate decides whether to TELL the user a
    generic row stood in for their product. "Peanut Butter" is worth a branded
    lookup and is not worth a caveat.
    """
    from skills.nutrition.branded import names_a_specific_product
    return names_a_specific_product(request.food_name, request.brand,
                                    request.is_packaged)


def _anchor_count_to_serving(quantity: NormalizedQuantity,
                             winner: Candidate) -> NormalizedQuantity:
    """Give a bare count a mass, using the winner's OWN serving panel.

    "15 pieces" of a per-100g row is unscalable, so the resolution came back
    empty, `promotable()` declined it, and the interpreter's guess was
    committed — wearing the database's name. That is the shipped transcript:
    "Logged Peanut M&Ms — 135 cal, from the USDA database", where nothing from
    USDA had in fact been scaled at all.

    A label that says "35 g (12 pieces)" knows what one piece of THAT product
    weighs. `PIECE_WEIGHTS_G` never can — it describes foods, and a table of
    food-shaped averages cannot know a Peanut M&M is three times a plain one.
    So the mass comes from the selected record, per product, and a different
    variant or a reformulation carries its own.

    Returns the quantity unchanged whenever the panel does not say both things
    or names a different object. Unscalable is a state the ask ladder can act
    on; a substituted average is not.
    """
    if quantity.grams is not None or quantity.count is None:
        return quantity
    unit_mass = serving_unit_mass(winner.serving_text, winner.serving_mass_g)
    if unit_mass is None:
        return quantity
    grams_per, serving_unit = unit_mass
    if not count_units_compatible(quantity.unit, serving_unit):
        return quantity
    # The mass is known now, so "portion mass unknown" is no longer true.
    # Assumptions are shown to the user; carrying a superseded one beside the
    # thing that superseded it reads as the system contradicting itself.
    kept = tuple(a for a in quantity.assumptions if a != MASS_UNKNOWN)
    return replace(
        quantity, grams=round(quantity.count * grams_per, 1),
        assumptions=kept + (
            f"{grams_per:g} g per {serving_unit}, from the "
            f"{winner.source} serving panel",))


#: A doubt covering this much of an item's own calories is worth asking about
#: even when its absolute size is small — being 100% wrong about an 80-calorie
#: bagel is not a small error. Applied below quick mode only, since quick
#: exists precisely to accept that risk.
#: A doubt covering this much of an item's own calories is material even when
#: its absolute size is small.
#:
#: The PR #31 sweep found 0.3 equally clean — but so were 0.35, 0.4 and the
#: incumbent 0.5, which means the labelled set cannot distinguish them and
#: tightening would be a change with no evidence behind it. Deliberately left
#: alone. The calorie thresholds moved in the same sweep because there the
#: evidence was positive: a specific case was being missed. "Nothing got worse"
#: is not the same finding as "something got better", and only the second one
#: justifies moving a threshold.
#:
#: What would settle it: the production frequency of small-item ambiguities,
#: which the labelled set under-represents.
#: Per MODE, which is the actual finding. A single constant served both
#: moderate and strict, so it could not express "strict cares about a fifth of
#: a small item, moderate does not" — every attempt to tighten it for strict
#: started interrupting moderate users on the same cases.
#:
#: 0.3/0.15 is the only setting in the sweep with zero missed material
#: ambiguities and zero needless interruptions across all 73 labelled
#: expectations. Rerun with `python -m skills.nutrition.calibration`.
#:
#: The pair that pinned the shape: 65 calories on a 293-calorie item (22%) must
#: ask in strict, and 80 on a 900-calorie platter (9%) must not. Both are
#: labelled gold cases now — the second used to live only in a unit test, where
#: the sweep could not see it and therefore recommended a setting that broke
#: it.
#:
#: Quick is 1.01 rather than a sentinel: quick exists to accept exactly this
#: risk, and a number above 1.0 says "no fraction is material here" in the same
#: units as the rest of the table rather than as a special case in the code.
#: Back-compat alias. Some callers and tests read the scalar. The table and the
#: floor are imported from `materiality` at the top of this module — the
#: fraction rule is what makes ONE calorie threshold safe to share across every
#: layer, so it cannot be a resolver-local idea.
MATERIAL_FRACTION = MATERIAL_FRACTIONS["moderate"]

#: Protein spans that justify interrupting, per mode (PR #31 calibration).
#:
#: Calibrated rather than picked: the tightest setting in the sweep that adds no
#: needless interruption to any of the 69 labelled ask expectations. Rerun with
#: `python -m skills.nutrition.calibration`.
#:
#: Stated honestly: every setting from 15/8/4 upward is clean on the labelled
#: set, so the evidence says tightening to here COSTS nothing — not that it
#: catches more than 25/15/8 would. The tightest clean setting is the right
#: default for a new rule, because a threshold that could have been tighter for
#: free leaves real ambiguity unasked. Production frequency data is what will
#: distinguish these rows.
#:
#: Tighter than the calorie thresholds in energy terms, because a protein miss
#: is not interchangeable with a calorie miss for the people who track it —
#: they are logging to hit a protein target, and 8 g is a meaningful part of it.
ASK_PROTEIN_SPANS = {m: thresholds_for(m)["protein"]
                     for m in ("quick", "moderate", "strict")}


def should_ask(ambiguities: tuple, mode: str) -> Optional[ResolutionAmbiguity]:
    """The strictness ladder, applied to resolution uncertainty. Returns the
    ambiguity worth interrupting for, or None.

    This decides WHEN to ask — never which value is true. A mode change must
    not change the nutrition answer, only the friction.
    """
    mode = (mode or "moderate").lower()
    threshold = ASK_SPANS.get(mode, ASK_SPANS["moderate"])
    protein_threshold = ASK_PROTEIN_SPANS.get(mode,
                                              ASK_PROTEIN_SPANS["moderate"])
    worst = None
    for a in ambiguities or ():
        material = a.calorie_span >= threshold
        if not material and mode != "quick":
            material = (a.calorie_fraction >= MATERIAL_FRACTIONS.get(
                            mode, MATERIAL_FRACTIONS["moderate"])
                        and a.calorie_span >= FRACTION_FLOOR)
        if not material:
            # Protein on its own can carry the decision. This is the third and
            # last part of the calorie-blindness fix: making the span material
            # and populating it changes nothing until the ladder reads it.
            material = a.protein_span >= protein_threshold
        if not material:
            continue
        # Ranked by calorie span still, with protein as the tiebreak — the
        # ordering only decides WHICH question to ask when several qualify, and
        # energy remains the better proxy for "how wrong could this meal be".
        if worst is None or (a.calorie_span, a.protein_span) > (
                worst.calorie_span, worst.protein_span):
            worst = a
    return worst


def resolve(request: FoodResolutionRequest, candidates: list) -> NutritionResolution:
    """Score, validate, select, scale — in that order, every time.

    Never raises. An unresolvable request returns a provisional resolution
    carrying the reason, because a food turn that cannot answer still has to
    answer.

    Memoized on (request, candidates). Safe because this is a pure function of
    exactly those two things — no clock, no database, no environment — so a
    cached answer and a recomputed one are the same answer. `test_food_caching`
    fails if that stops being true.
    """
    # Trace OUTSIDE, memoize INSIDE. The order matters in both directions: a
    # cache hit still has to appear in the trace, or the latency report stops
    # being able to show what the cache is worth; and the memo has to sit closer
    # to the computation than the timer, or every hit would be recorded as a
    # resolve that did no work.
    from core import food_trace
    from skills.nutrition.cache import memoize
    with food_trace.stage(food_trace.Stage.RESOLVE) as timed:
        out = memoize(request, candidates,
                      lambda: _resolve(request, candidates))
        timed.counts.update(candidates=len(candidates or ()),
                            rejected=len(out.rejected_candidates or ()),
                            ambiguities=len(out.ambiguities or ()))
        if out.source == "unresolved":
            timed.outcome = food_trace.Outcome.HELD
            timed.detail = "unresolved"
    return out


def _resolve(request: FoodResolutionRequest,
             candidates: list) -> NutritionResolution:
    """The resolution itself. Split from `resolve` so the timing wrapper and the
    memo each have one exit to work with — resolve has several, and wrapping each
    of them separately is how one of them ends up untimed or uncached."""
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
            serving_text=candidate.serving_text,
            serving_mass_g=candidate.serving_mass_g,
            serving_ml=candidate.serving_ml))

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

    # A bare count gets its mass from the winner's own serving panel, before
    # anything is scaled. Deliberately AFTER the winner is chosen: the mass
    # must come from the record whose numbers are about to be used, not from
    # whichever candidate happened to carry a panel.
    quantity = _anchor_count_to_serving(quantity, winner)

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

    # ── §9: does the scaled result describe a food at all? ──────────────────
    # Scaling is arithmetic, and arithmetic does not notice when its premise is
    # wrong: every failure here is a correct multiplication against a basis
    # that did not describe the source. The checks run on the SCALED profile,
    # because the source row was fine in each of the shipped cases.
    #
    # An impossible result is dropped rather than persisted. Keeping it "with a
    # warning" is what put 588 calories of peanut butter in a day's totals
    # behind a warning nobody read — unknown is not zero, and it is not the
    # wrong portion either.
    from skills.nutrition import sanity as _sanity
    basis_findings = _sanity.check(scaled, winner.basis, quantity)
    fatal = [f for f in basis_findings if f.is_fatal]
    for finding in basis_findings:
        warnings.append(f"{finding.code}: {finding.message}")
    if fatal:
        logger.warning(
            "sanity refusal for %r: %s",
            request.food_name, "; ".join(f.code for f in fatal))
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
    if basis_findings and not fatal:
        # Physically possible, probably scaled against the wrong basis. A
        # penalty and a disclosure — not a refusal, because oils, nut butters
        # and spirits sit near these bounds legitimately and refusing there
        # would trade a rare wrong answer for a common missing one.
        confidence *= 0.7
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
