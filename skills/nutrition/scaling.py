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
    """
    serving_mass_g: Optional[float] = None
    serving_ml: Optional[float] = None
    servings_per_package: Optional[float] = None
    as_served: bool = False
    basis = "per_serving"


@dataclass(frozen=True)
class PerUnit:
    """One piece, slice, bagel, bar. `unit_mass_g` is what makes it scalable
    against a mass; without it, only whole-unit counts work.

    `as_served` carries the same meaning as on PerServing: the unit is whatever
    the user described, not a measured piece."""
    unit_mass_g: Optional[float] = None
    as_served: bool = False
    basis = "per_unit"


SourceBasis = Union[Per100g, Per100ml, PerServing, PerUnit]

_SPEC_BASES = {"per_100g": Per100g, "per_100ml": Per100ml}


def basis_from_spec(kind: str, *, as_served: bool = False,
                    serving_mass_g: Optional[float] = None,
                    serving_ml: Optional[float] = None,
                    servings_per_package: Optional[float] = None
                    ) -> SourceBasis:
    """Build a basis from a declared kind. One factory, because the same four
    lines had been rewritten in the readiness report (twice) and the gold
    harness, and a basis field added in one place stayed missing in the others.
    """
    if kind in _SPEC_BASES:
        return _SPEC_BASES[kind]()
    if kind == "per_serving":
        return PerServing(serving_mass_g=serving_mass_g, serving_ml=serving_ml,
                          servings_per_package=servings_per_package,
                          as_served=as_served)
    return PerUnit(unit_mass_g=serving_mass_g, as_served=as_served)


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
        if countable:
            return float(count)
        if count is not None:
            raise ScalingRefused(
                "per-serving values need a serving mass; this portion is an "
                "estimated helping, not a count of the label's servings")
        raise ScalingRefused(
            "per-serving values need a serving mass or a serving count")

    if isinstance(basis, PerUnit):
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
