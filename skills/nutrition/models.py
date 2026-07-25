"""Nutrition resolution contracts (review 2026-07-25, work order step 3).

The executor should receive ONE resolved object. It should not know how USDA,
OpenFoodFacts or web-label lookup work, and it should not be the place where
source precedence, unit conversion and sanity checking happen to meet.

The contract that makes that possible:

    FoodResolutionRequest  →  [ resolution ]  →  NutritionResolution

Everything about how the answer was reached — which candidates lost and why,
what was assumed, what remains uncertain — travels WITH the answer instead of
being logged and forgotten.

The single most important rule in this module: **unknown is not zero.** A
NutrientProfile stores a value only for fields something actually established.
Zero sodium and unknown sodium are different product facts, and a profile that
cannot tell them apart will confidently report a salt bomb as clean.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Optional

from skills.nutrition.provenance import (CandidateRejection, MatchGrade,
                                         NutrientValue, SourceTier)

#: Fields a profile can carry. Macros first — they drive every downstream
#: number — then the micros most often wrong in ways that matter.
MACRO_FIELDS = ("calories", "protein", "carbs", "fat")
MICRO_FIELDS = ("fiber", "sugar", "sodium", "saturated_fat", "cholesterol",
                "potassium")
ALL_FIELDS = MACRO_FIELDS + MICRO_FIELDS

#: kcal per gram, for the energy-consistency check.
ATWATER = {"protein": 4.0, "carbs": 4.0, "fat": 9.0}


@dataclass(frozen=True)
class NutrientProfile:
    """A set of per-field values. A field absent from `values` is UNKNOWN and
    must stay that way — never defaulted, never zero-filled."""
    values: Mapping[str, NutrientValue] = field(default_factory=dict)

    def get(self, name: str) -> Optional[NutrientValue]:
        return (self.values or {}).get(name)

    def amount(self, name: str) -> Optional[float]:
        v = self.get(name)
        return None if v is None else v.value

    def known(self) -> tuple:
        return tuple(k for k in ALL_FIELDS if k in (self.values or {}))

    def unknown(self) -> tuple:
        return tuple(k for k in ALL_FIELDS if k not in (self.values or {}))

    def with_values(self, **updates) -> "NutrientProfile":
        merged = dict(self.values or {})
        for k, v in updates.items():
            if v is None:
                merged.pop(k, None)     # explicit "we no longer know this"
            else:
                merged[k] = v
        return NutrientProfile(values=merged)

    def merge(self, other: "NutrientProfile",
              prefer_self: bool = True) -> "NutrientProfile":
        """Field-level merge — the mechanism behind mixed-authority answers
        (macros from a label, sodium from an exact USDA match). Nothing is
        invented: a field neither side knows stays unknown."""
        merged = dict(other.values or {})
        for k, v in (self.values or {}).items():
            if prefer_self or k not in merged:
                merged[k] = v
        return NutrientProfile(values=merged)

    def as_dict(self) -> dict:
        """Plain numbers for persistence. Unknown fields are OMITTED, not
        zeroed — the caller must decide what a missing key means, which is the
        whole point."""
        return {k: v.value for k, v in (self.values or {}).items()}

    @property
    def is_empty(self) -> bool:
        return not (self.values or {})


@dataclass(frozen=True)
class NormalizedQuantity:
    """What the user ate, in one canonical shape.

    `grams` is the scaling currency when it is known. When it is not — "six
    thin deli slices" — `count` and `unit_label` carry the intent and
    `uncertainty_g` carries the honesty. That uncertainty is what the
    clarification ladder reads; it is not a number to hide.
    """
    amount: float
    unit: str                            # g | ml | piece | slice | serving | ...
    grams: Optional[float] = None
    milliliters: Optional[float] = None
    count: Optional[float] = None
    unit_label: str = ""                 # the user's own words
    uncertainty_g: Optional[float] = None
    assumptions: tuple = ()

    @property
    def is_mass_known(self) -> bool:
        return self.grams is not None

    def describe(self) -> str:
        return self.unit_label or f"{_trim(self.amount)} {self.unit}"


@dataclass(frozen=True)
class FoodResolutionRequest:
    """One food operation, before any lookup. Everything the resolver is
    allowed to know — no db handle, no user object, no turn state."""
    food_name: str
    amount: float = 1.0
    unit: str = "serving"
    brand: Optional[str] = None
    variant: Optional[str] = None
    package_serving_text: Optional[str] = None
    user_label_values: Optional[NutrientProfile] = None
    provisional_values: Optional[NutrientProfile] = None
    prior_food_id: Optional[int] = None
    mode: str = "moderate"               # quick | moderate | strict
    is_packaged: bool = False
    raw_quantity: str = ""

    @property
    def has_user_label(self) -> bool:
        return (self.user_label_values is not None
                and not self.user_label_values.is_empty)


@dataclass(frozen=True)
class ResolutionAmbiguity:
    """An unresolved choice, sized by what it would cost to get wrong. The
    strictness ladder decides whether to ask; this only reports the stakes."""
    field: str
    options: tuple = ()
    calorie_span: float = 0.0
    protein_span: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class NutritionResolution:
    """The one object the executor receives."""
    canonical_name: str
    quantity: NormalizedQuantity
    nutrients: NutrientProfile
    source: str = "provisional"
    tier: SourceTier = SourceTier.PROVISIONAL
    source_id: Optional[str] = None
    match_grade: str = MatchGrade.NONE
    confidence: float = 0.0
    assumptions: tuple = ()
    warnings: tuple = ()
    ambiguities: tuple = ()
    rejected_candidates: tuple = ()
    resolver_version: str = "nutrition_resolver_v1"

    @property
    def is_estimate(self) -> bool:
        return self.tier.is_estimate

    def with_warning(self, warning: str) -> "NutritionResolution":
        return replace(self, warnings=self.warnings + (warning,))

    def with_assumption(self, assumption: str) -> "NutritionResolution":
        return replace(self, assumptions=self.assumptions + (assumption,))


def _trim(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"


def profile_from_values(source: str, basis: str = "per_serving",
                        confidence: float = 0.5, estimated: bool = False,
                        source_id: Optional[str] = None,
                        **amounts) -> NutrientProfile:
    """Build a profile from plain numbers, keeping unknown fields unknown.

    None is dropped, so `sodium=None` means "we did not learn sodium" rather
    than "this product has no sodium". Callers that genuinely mean zero must
    pass 0.0 explicitly.
    """
    units = {"calories": "kcal", "sodium": "mg", "cholesterol": "mg",
             "potassium": "mg"}
    values = {}
    for name, amount in amounts.items():
        if name not in ALL_FIELDS or amount is None:
            continue
        try:
            v = float(amount)
        except (TypeError, ValueError):
            continue
        values[name] = NutrientValue(
            value=v, unit=units.get(name, "g"), source=source,
            confidence=confidence, basis=basis, source_id=source_id,
            estimated=estimated)
    return NutrientProfile(values=values)


def field_sources(profile: NutrientProfile) -> dict:
    """{field: source} — the line that makes a mixed-authority answer legible
    in a log."""
    return {k: v.source for k, v in (profile.values or {}).items()}
