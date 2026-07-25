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
from dataclasses import dataclass
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
    serving_mass_g: Optional[float] = None
    serving_ml: Optional[float] = None
    servings_per_package: Optional[float] = None
    basis = "per_serving"


@dataclass(frozen=True)
class PerUnit:
    """One piece, slice, bagel, bar. `unit_mass_g` is what makes it scalable
    against a mass; without it, only whole-unit counts work."""
    unit_mass_g: Optional[float] = None
    basis = "per_unit"


SourceBasis = Union[Per100g, Per100ml, PerServing, PerUnit]


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

    if isinstance(basis, PerServing):
        if grams is not None and basis.serving_mass_g:
            return grams / float(basis.serving_mass_g)
        if ml is not None and basis.serving_ml:
            return ml / float(basis.serving_ml)
        if count is not None:
            return float(count)
        raise ScalingRefused(
            "per-serving values need a serving mass or a serving count")

    if isinstance(basis, PerUnit):
        if count is not None:
            return float(count)
        if grams is not None and basis.unit_mass_g:
            return grams / float(basis.unit_mass_g)
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


def scaling_uncertainty(profile: NutrientProfile, source_basis: SourceBasis,
                        consumed: NormalizedQuantity) -> Optional[float]:
    """Calorie span implied by the portion's mass uncertainty — what "six thin
    deli slices" actually costs if we are wrong about the slices. Feeds the
    clarification ladder; None when there is nothing uncertain to report."""
    if consumed.uncertainty_g is None or consumed.grams is None:
        return None
    cal = profile.amount("calories")
    if cal is None:
        return None
    try:
        low = NormalizedQuantity(
            amount=consumed.amount, unit=consumed.unit,
            grams=max(0.0, consumed.grams - consumed.uncertainty_g),
            milliliters=consumed.milliliters, count=consumed.count)
        high = NormalizedQuantity(
            amount=consumed.amount, unit=consumed.unit,
            grams=consumed.grams + consumed.uncertainty_g,
            milliliters=consumed.milliliters, count=consumed.count)
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
