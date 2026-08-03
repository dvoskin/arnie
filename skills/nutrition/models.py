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


#: What a `count` actually counts. The distinction exists because a count is
#: only a valid multiplier for a per-serving or per-unit label when the thing
#: counted IS that label's unit.
#:
#: UNIT is the default because it is what a bare count means nearly everywhere:
#: "2 bagels", "6 slices", "1 bottle". Only the vague measures are the exception,
#: they all come from one module, and they say so explicitly.
COUNT_BASIS_UNIT = "unit"        # discrete units/products: 2 bagels, 1 bottle
COUNT_BASIS_ESTIMATE = "estimate"  # a vague container or portion: a bowl, a plate


@dataclass(frozen=True)
class NormalizedQuantity:
    """What the user ate, in one canonical shape.

    `grams` is the scaling currency when it is known. When it is not — "six
    thin deli slices" — `count` and `unit_label` carry the intent and
    `uncertainty_g` carries the honesty. That uncertainty is what the
    clarification ladder reads; it is not a number to hide.

    `count_basis` says what the count counts. "One plate of pasta" and "one
    bottle of Fairlife" both arrive with count=1, but only the second is one of
    the label's servings; the first is a container we estimated a mass for. A
    per-serving source that multiplies by the count regardless turns a 400 g
    plate estimate into "exactly one serving", so the basis has to travel with
    the count rather than being re-guessed downstream.
    """
    amount: float
    unit: str                            # g | ml | piece | slice | serving | ...
    grams: Optional[float] = None
    milliliters: Optional[float] = None
    count: Optional[float] = None
    unit_label: str = ""                 # the user's own words
    uncertainty_g: Optional[float] = None
    assumptions: tuple = ()
    count_basis: str = COUNT_BASIS_UNIT
    #: The count names a PART of the food, not one of it — "1 piece" of an
    #: eight-piece roll, "1 slice" of a pizza. Travels with the count for the
    #: same reason `count_basis` does: only here are the unit AND the food name
    #: both in hand, and downstream cannot re-derive it. A source that has no
    #: serving panel must not multiply its numbers by a fraction of the dish —
    #: prod 2026-08-03 fe#2719 read one piece as one whole roll, 460 cal over
    #: the interpreter's own correct 130-190.
    #:
    #: FALSE when the unit IS the product ("6 slices" of turkey deli slice),
    #: which is why this cannot be answered from the unit word alone. It is
    #: also NOT a licence to refuse whenever it is true: a panel that
    #: enumerates the same unit ("35 g (12 pieces)") knows exactly what one
    #: piece weighs, and that path resolves a mass long before any count is
    #: multiplied.
    unit_is_fraction: bool = False

    # ── What the USER said, kept separate from what we made of it (§2, §10) ──
    #
    # These four are provenance, not inputs. Once a portion had been normalized
    # there was no way back to the words that produced it, so every layer
    # downstream — the card, the coach line, a clarifying question — had to
    # paraphrase from `amount` and `unit` and quietly replaced the user's own
    # phrasing with our reconstruction of it. "Half a bagel" came back as "0.5
    # bagel"; a clarification about something else in the meal reprinted it that
    # way, and the user is then reading their own sentence rewritten by us.
    #
    # Keeping the original is also the only way to be honest about the seam:
    # `user_stated_amount` is None when the user stated no number at all, which
    # is a different thing from stating one that happened to be 1.
    original_user_wording: str = ""       # exactly as typed, case intact
    user_stated_amount: Optional[float] = None
    user_stated_unit: str = ""
    size_descriptor: str = ""             # "large", "small" — theirs, not ours

    #: HOW the mass or volume was arrived at: mass_conversion | volume_conversion
    #: | vessel | piece_weight | ontology | none. A conversion is exact and an
    #: estimate is not, and a single `grams` field cannot tell them apart —
    #: which is how estimated masses were presented with the same certainty as
    #: "200 g".
    normalization_source: str = ""
    #: 0–1. Coarse on purpose; four or five states, not a continuum.
    normalization_confidence: float = 0.0

    @property
    def is_mass_known(self) -> bool:
        return self.grams is not None

    @property
    def normalized_mass_g(self) -> Optional[float]:
        """Alias with the direction stated. `grams` reads as though it were
        given; this reads as what it is — the output of a normalization whose
        method `normalization_source` names."""
        return self.grams

    @property
    def normalized_volume_ml(self) -> Optional[float]:
        return self.milliliters

    @property
    def mass_is_exact(self) -> bool:
        return self.normalization_source in ("mass_conversion",
                                             "volume_conversion")

    @property
    def count_is_serving_compatible(self) -> bool:
        """True when `count` may be read as N of a label's servings/units."""
        return (self.count is not None
                and self.count_basis != COUNT_BASIS_ESTIMATE)

    def describe(self) -> str:
        """The portion, in the user's words wherever they exist (§10).

        The reconstruction — `f"{amount} {unit}"` — is the last resort, not the
        default, because it is not what anyone said. "Half a bagel" becomes
        amount=0.5, unit="bagel", and reconstructing from those quotes the
        user's own sentence back to them as "0.5 bagel". `original_user_wording`
        is exactly as typed, so it leads; `unit_label` (lowercased, in some
        paths synthesised) follows; the reconstruction is what we fall to when
        there is genuinely nothing else.
        """
        return (self.original_user_wording or self.unit_label
                or f"{_trim(self.amount)} {self.unit}")


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
    # The span as a fraction of the item's own calories. An 80-calorie doubt
    # is trivial on a 900-calorie platter and total on an 80-calorie bagel;
    # an absolute threshold alone cannot tell those apart.
    calorie_fraction: float = 0.0


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
