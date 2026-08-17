"""The one scaling engine (review 2026-07-25, work order step 6).

Every source adapter currently scales its own numbers, which means the
per-100g→portion arithmetic exists in several places with several sets of
assumptions. Forward-scaling mistakes have already caused incidents.

So: no adapter scales anything. Each declares what its numbers describe —

    Per100g()                       per 100 g
    Per100ml()                      per 100 ml
    PerServing(serving_mass_g=43)   one serving, with its mass
    PerUnit(unit_mass_g=54)         one piece/slice, with its mass

— and this module does the only multiplication in the system.

Scaling is refused, not guessed, when the bases cannot be reconciled: a
per-serving panel with no serving mass cannot answer "how much in 86 g". A
refusal surfaces as an unknown, which the validators and the clarification
ladder can act on. A guess surfaces as a confident wrong number.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Optional, Union

from skills.nutrition.models import NormalizedQuantity, NutrientProfile

logger = logging.getLogger(__name__)


class ScalingRefused(ValueError):
    """The bases cannot be reconciled. Not an error to swallow — the caller
    must record an unknown rather than substitute an estimate."""


# ── what a source's numbers describe ──────────────────────────────────────────
@dataclass(frozen=True)
class Per100g:
    basis = "per_100g"


@dataclass(frozen=True)
class Per100ml:
    basis = "per_100ml"


@dataclass(frozen=True)
class PerServing:
    """One serving, ideally with its mass.

    `as_served` says whose serving it is. A branded label or a USDA row defines
    a MEASURED serving — 43 g, 240 ml — and a vague helping is not one of them.
    A restaurant-item estimate, a provisional guess or the user's own saved
    regular defines the dish AS SERVED, so one helping of it genuinely is one
    serving however loosely the user described the helping.

    Without that flag the two collapse, and "one plate" reads as one serving of
    a packaged label whose serving mass we never knew.

    ⛔⛔ `unit_id` IS WHAT A COUNT MUST MATCH BEFORE IT MAY MULTIPLY *(P17b.1,
    2026-08-17)*. A label states "1 BAR = 200 kcal"; without the unit named, a
    count of two BOTTLES multiplies it just as happily, because
    `count_is_serving_compatible` answers about the COUNT alone and can never
    see what the source is counting. Set it and the count path demands identity;
    leave it unset and behaviour is exactly as before.

    ⚠ `servings_per_package` IS CARRIED AND NOT YET CONSUMED. `_factor` has no
    package path, so "1 bottle = 2 servings" does NOT resolve today. It is not
    package support; it is the field package support will read.
    """
    serving_mass_g: Optional[float] = None
    serving_ml: Optional[float] = None
    servings_per_package: Optional[float] = None
    as_served: bool = False
    #: What ONE serving IS — "bar", "bottle", "large egg". Identity, not prose.
    unit_id: str = ""
    basis = "per_serving"


@dataclass(frozen=True)
class PerUnit:
    """One piece, slice, bagel, bar. `unit_mass_g` is what makes it scalable
    against a mass; without it, only whole-unit counts work.

    `as_served` carries the same meaning as on PerServing: the unit is whatever
    the user described, not a measured piece."""
    unit_mass_g: Optional[float] = None
    as_served: bool = False
    unit_id: str = ""
    basis = "per_unit"


@dataclass(frozen=True)
class SourcedMeasure:
    """"One <unit> weighs N grams", ACCORDING TO THE RECORD THAT IS PRICING.

    ⛔⛔ IT LIVES HERE, NOT IN `canonical_pricing`, AND THAT IS THE POINT
    *(moved on review, 2026-08-17)*. The first version put this shape and its
    matching logic beside the pricer, which grew a SECOND conversion engine next
    to the scaling one — with its own regex for "is this the same unit". Two
    definitions of unit compatibility eventually disagree, and the one that
    matters most is the one P17g will ask: `decide()` has to be able to pose the
    same question the pricer answers, or coverage and pricing drift apart. That
    drift is the entire defect `has_mass` was written to prevent.

    ⛔ A CONVERSION ON THE CONSUMED QUANTITY, NEVER A BASIS ON THE EVIDENCE.
    Per-100 g numbers plus "1 large egg = 50 g" means `2 eggs -> 100 g -> the
    per-100 g rung scales normally`. Declaring `PerUnit(unit_mass_g=50)` over
    those numbers would instead claim they DESCRIBE one egg.
    """
    unit_text: str
    grams_per_unit: float
    source_id: str = ""


def unit_matches(consumed, unit_id: str) -> bool:
    """Does the user's counted unit name the SAME thing the source counts?

    ⭐ ONE AUTHORITY, DELIBERATELY. The sourced-measure conversion in
    `canonical_pricing` asks the same question about a serving panel, and two
    implementations of "is this the same unit" would eventually disagree — which
    is the predicate/pricer drift the whole tranche is built to avoid.

    Word-boundary and singular-or-plural, and NARROW ON PURPOSE: "piece" must
    not match "bar", because knowing a whole bar weighs 55 g says nothing about
    what one piece of it weighs.
    """
    want = str(getattr(consumed, "unit_label", "")
               or getattr(consumed, "unit", "")).strip().lower()
    target = str(unit_id or "").strip().lower()
    if not want or not target:
        return False
    return bool(re.search(rf"\b{re.escape(want)}s?\b", target)
                or re.search(rf"\b{re.escape(target)}s?\b", want))


#: A serving panel states a COUNT and a unit: "2 cookies", "1 bar", "1 large
#: egg". The count matters — 30 g for "2 cookies" is 15 g per cookie.
_PANEL = re.compile(r"^\s*(\d+(?:\.\d+)?)?\s*(.+?)\s*$")


def measure_from_panel(serving_text, serving_mass_g, source_id=""):
    """A `SourcedMeasure` from a provider's own serving panel, or None."""
    try:
        grams = float(serving_mass_g)
    except (TypeError, ValueError):
        return None
    if grams <= 0:
        return None
    match = _PANEL.match(str(serving_text or "").strip().lower())
    if not match or not match.group(2):
        return None
    count = float(match.group(1)) if match.group(1) else 1.0
    if count <= 0:
        return None
    return SourcedMeasure(unit_text=match.group(2),
                          grams_per_unit=grams / count, source_id=source_id)


def mass_from_measures(consumed, measures) -> Optional[float]:
    """The mass a BARE COUNT implies, per a sourced measure that counts the
    SAME unit — or None, which leaves the portion exactly as unpriceable.

    ⭐ IT ASKS `unit_matches`, THE SAME FUNCTION THE COUNT PATHS ASK. This used
    to carry its own regex, which is how a codebase ends up with two answers to
    one question.

    ⛔ NEVER A FALLBACK GUESS. If no measure names the unit the user counted,
    this returns None and the rung declines. Inventing a mass here is exactly
    the "a model guesses 1 serving ~ X grams, therefore canonical owns it" the
    directive forbids — the conversion is evidence or it is nothing.
    """
    if consumed is None or getattr(consumed, "grams", None) is not None:
        return None
    count = getattr(consumed, "count", None)
    if not count:
        return None
    # ⚠ A PART OF A UNIT IS NOT ONE OF IT. "half a bar" may not take the whole
    # bar's mass, for the same reason the PerServing path refuses it.
    if getattr(consumed, "unit_is_fraction", False):
        return None
    want = str(getattr(consumed, "unit_label", "")
               or getattr(consumed, "unit", "")).strip().lower()
    if not want or want in ("g", "gram", "grams", "ml"):
        return None
    for measure in measures or ():
        if unit_matches(consumed, measure.unit_text):
            return float(count) * measure.grams_per_unit
    return None


SourceBasis = Union[Per100g, Per100ml, PerServing, PerUnit]

_SPEC_BASES = {"per_100g": Per100g, "per_100ml": Per100ml}


def basis_from_spec(kind: str, *, as_served: bool = False,
                    serving_mass_g: Optional[float] = None,
                    serving_ml: Optional[float] = None,
                    servings_per_package: Optional[float] = None,
                    unit_id: str = "") -> SourceBasis:
    """Build a basis from a declared kind. One factory, because the same four
    lines had been rewritten in the readiness report (twice) and the gold
    harness, and a basis field added in one place stayed missing in the others.

    ⛔⛔ AND THAT IS EXACTLY WHAT HAPPENED TO `unit_id` *(caught on review,
    2026-08-17)*. It was added to `PerServing` and `PerUnit` as the field that
    proves a count counts the right thing, and this factory — whose entire
    reason for existing is the sentence above — kept building bases WITHOUT it.
    Every basis it produced would have silently lost its identity gate, which is
    the same dead-field defect P17c found one layer upstream in the artifact
    builder. A canonical factory must round-trip every load-bearing field.
    """
    if kind in _SPEC_BASES:
        return _SPEC_BASES[kind]()
    if kind == "per_serving":
        return PerServing(serving_mass_g=serving_mass_g, serving_ml=serving_ml,
                          servings_per_package=servings_per_package,
                          as_served=as_served, unit_id=unit_id)
    return PerUnit(unit_mass_g=serving_mass_g, as_served=as_served,
                   unit_id=unit_id)


def _factor(basis: SourceBasis, consumed: NormalizedQuantity) -> float:
    """How many of the source's units the user ate."""
    grams = consumed.grams
    ml = consumed.milliliters
    count = consumed.count

    if isinstance(basis, Per100g):
        if grams is None:
            raise ScalingRefused(
                "per-100g values need a mass, and this portion has none")
        return grams / 100.0

    if isinstance(basis, Per100ml):
        if ml is None:
            # Water-density fallback is a real assumption, not a conversion.
            # Refuse rather than silently treat 100 g of oil as 100 ml.
            raise ScalingRefused(
                "per-100ml values need a volume, and this portion has none")
        return ml / 100.0

    # A count is only a multiplier for these two bases when it counts the SAME
    # unit the source describes. "One plate of pasta" arrives as count=1 beside
    # a 400 g estimate; reading that as one serving of a packaged label discards
    # the estimate and reports a container as a package. Either the count counts
    # discrete units, or the source's serving is itself the helping.
    countable = (consumed.count is not None
                 and (consumed.count_is_serving_compatible
                      or getattr(basis, "as_served", False)))

    if isinstance(basis, PerServing):
        if grams is not None and basis.serving_mass_g:
            return grams / float(basis.serving_mass_g)
        if ml is not None and basis.serving_ml:
            return ml / float(basis.serving_ml)
        # A FRACTION OF THE DISH IS NOT ONE OF THE DISH. `countable` asks
        # whether the count may multiply this source's serving, and both of its
        # inputs answer about the COUNT alone — neither can see that the source
        # has no idea how many pieces the thing came in. Prod 2026-08-03
        # fe#2719: a restaurant lookup for a special roll, no serving panel,
        # count=1 unit="piece" — multiplied the WHOLE ROLL by one and committed
        # 460 cal over the interpreter's own correct 130-190.
        #
        # Gated on the source stating NO panel, which is what makes it narrow.
        # "15 pieces" against "35 g (12 pieces)" is untouched: that panel knows
        # what one piece weighs, so a mass resolves above and the count is
        # never the multiplier. `unit_is_fraction` is likewise false when the
        # unit IS the product ("6 slices" of turkey deli slice).
        _no_panel = basis.serving_mass_g is None and basis.serving_ml is None
        # ⛔⛔ IDENTITY BEFORE MULTIPLICATION *(P17b.1)*. Reached only when the
        # mass and volume paths could not reconcile the bases themselves — a
        # gram portion needs no name match, because the mass IS the common
        # ground. Here there is only a count, so the source must say what it
        # counts and the count must be of that thing.
        if basis.unit_id:
            if not unit_matches(consumed, basis.unit_id):
                raise ScalingRefused(
                    f"this source states its serving as {basis.unit_id!r}, and "
                    f"{consumed.unit_label or consumed.unit!r} is not that — a "
                    f"count may only multiply the unit the evidence describes")
            # A PART OF THE UNIT IS NOT ONE OF THE UNIT, panel or no panel.
            # Knowing a whole bar weighs 55 g does not say what one piece of it
            # weighs, so a stated serving mass must NOT license a fraction.
            if consumed.unit_is_fraction:
                raise ScalingRefused(
                    f"one {consumed.unit} of a {basis.unit_id} is a PART of the "
                    f"serving this source describes, and its size is not stated")
        if countable and not (consumed.unit_is_fraction and _no_panel):
            return float(count)
        if consumed.unit_is_fraction and _no_panel and count is not None:
            raise ScalingRefused(
                f"this source states no serving panel, so one "
                f"{consumed.unit} of it cannot be priced as a whole serving")
        if count is not None:
            raise ScalingRefused(
                "per-serving values need a serving mass; this portion is an "
                "estimated helping, not a count of the label's servings")
        raise ScalingRefused(
            "per-serving values need a serving mass or a serving count")

    if isinstance(basis, PerUnit):
        # ⛔⛔ THE SAME IDENTITY GATE AS PerServing, AND ITS ABSENCE HERE WAS A
        # REAL HOLE *(found on review, 2026-08-17)*. `unit_id` was added to this
        # class and then never consulted, so "every count multiplication proves
        # the count is of the unit the evidence describes" was true of one path
        # and false of the other — which is worse than not having the field,
        # because the field made it look handled.
        if basis.unit_id and count is not None:
            if not unit_matches(consumed, basis.unit_id):
                raise ScalingRefused(
                    f"this source states its unit as {basis.unit_id!r}, and "
                    f"{consumed.unit_label or consumed.unit!r} is not that — a "
                    f"count may only multiply the unit the evidence describes")
            if consumed.unit_is_fraction:
                raise ScalingRefused(
                    f"one {consumed.unit} of a {basis.unit_id} is a PART of the "
                    f"unit this source describes, and its size is not stated")
        if countable:
            return float(count)
        if grams is not None and basis.unit_mass_g:
            return grams / float(basis.unit_mass_g)
        if count is not None:
            raise ScalingRefused(
                "per-unit values need a known unit mass; this portion is an "
                "estimated helping, not a count of the label's units")
        raise ScalingRefused(
            "per-unit values need a count or a known unit mass")

    raise ScalingRefused(f"unknown source basis: {basis!r}")


def scale_profile(profile: NutrientProfile, source_basis: SourceBasis,
                  consumed: NormalizedQuantity) -> NutrientProfile:
    """The portion's numbers. Every field scales by the SAME factor — a field
    scaling differently from its neighbours means the basis was wrong, and
    that is a bug to surface, not to route around.

    Provenance survives: each value keeps its source, and its basis becomes
    `per_portion` so nothing downstream can rescale it a second time.
    """
    factor = _factor(source_basis, consumed)
    if factor < 0:
        raise ScalingRefused("negative portion")
    scaled = {}
    for name, value in (profile.values or {}).items():
        scaled[name] = value.with_value(
            _round(value.value * factor, name), basis="per_portion")
    return NutrientProfile(values=scaled)


def scaling_spans(profile: NutrientProfile, source_basis: SourceBasis,
                  consumed: NormalizedQuantity) -> dict:
    """Per-field spans implied by the portion's mass uncertainty.

    What "six thin deli slices" actually costs if we are wrong about the
    slices — for every macro, not just calories. A mass doubt scales protein
    exactly as it scales energy, and the calorie-only version reported
    protein_span=0 on every portion ambiguity, which told the ask ladder that
    protein was certain when the mass was not (PR #31 calibration).

    Returns {} when there is nothing uncertain to report.
    """
    if consumed.uncertainty_g is None or consumed.grams is None:
        return {}
    out = {}
    for field in ("calories", "protein"):
        if profile.amount(field) is None:
            continue
        span = _span_for(profile, source_basis, consumed, field)
        if span:
            out[field] = span
    return out


def _span_for(profile: NutrientProfile, source_basis: SourceBasis,
              consumed: NormalizedQuantity, field: str) -> Optional[float]:
    try:
        low = NormalizedQuantity(
            amount=consumed.amount, unit=consumed.unit,
            grams=max(0.0, consumed.grams - consumed.uncertainty_g),
            milliliters=consumed.milliliters, count=consumed.count)
        high = NormalizedQuantity(
            amount=consumed.amount, unit=consumed.unit,
            grams=consumed.grams + consumed.uncertainty_g,
            milliliters=consumed.milliliters, count=consumed.count)
        lo = scale_profile(profile, source_basis, low).amount(field)
        hi = scale_profile(profile, source_basis, high).amount(field)
    except ScalingRefused:
        return None
    if lo is None or hi is None:
        return None
    return round(abs(hi - lo), 1)


def scaling_uncertainty(profile: NutrientProfile, source_basis: SourceBasis,
                        consumed: NormalizedQuantity) -> Optional[float]:
    """The calorie span alone. Kept as the narrow entry point callers already
    use; `scaling_spans` is the one that sees protein."""
    if consumed.uncertainty_g is None or consumed.grams is None:
        return None
    cal = profile.amount("calories")
    if cal is None:
        return None
    try:
        # `replace` rather than a fresh construction: rebuilding field by field
        # dropped whatever the portion knew that this function does not name,
        # and a lost `count_basis` turns a scalable count into a refusal.
        low = replace(
            consumed, grams=max(0.0, consumed.grams - consumed.uncertainty_g))
        high = replace(
            consumed, grams=consumed.grams + consumed.uncertainty_g)
        lo = scale_profile(profile, source_basis, low).amount("calories")
        hi = scale_profile(profile, source_basis, high).amount("calories")
    except ScalingRefused:
        return None
    if lo is None or hi is None:
        return None
    return round(abs(hi - lo), 1)


def _round(value: float, name: str) -> float:
    """Calories to whole numbers, everything else to a tenth. Storing
    247.30000000000004 g of protein is not precision."""
    return round(value) if name == "calories" else round(value, 1)
