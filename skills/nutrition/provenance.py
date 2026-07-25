"""Where a nutrient number came from (review 2026-07-25, work order step 3/7).

The enrichment cascade currently returns one blended answer with one source
label. That is too coarse to be safe: a candidate can be entirely trustworthy
for calories and macros while being dangerous for micros — the match is a
seasoning, a concentrate, or a per-package panel read as per-serving, and
sodium comes back at 20,000 mg per 100 g.

So trust is assigned PER FIELD, not per candidate. A single resolution may
legitimately be:

    calories  label
    protein   label
    carbs     label
    fat       label
    fiber     unknown
    sodium    USDA exact match
    sugar     unknown

and each field is validated on its own terms.

The authority tiers below decide winners. They are deliberately separate from
retrieval order: candidates are fetched in whatever order is fastest, then
scored. Fetch order must never equal winner priority — that is the bug behind
"USDA cousin beats the actual product label".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class SourceTier(IntEnum):
    """Authority classes, highest first. Lower number wins.

    A tier is about how directly the number describes THIS product, not about
    how much data the source has behind it. USDA is a better database than a
    user's memory of a label; the label is still the better answer for the
    thing in their hand.
    """
    USER_LABEL = 1        # the user read us the label. We asked; they answered.
    USER_REGULAR = 2      # an exact saved regular of theirs — same product,
                          # brand, variant and serving basis.
    BRANDED_EXACT = 3     # barcode, or an exact branded-label match.
    GENERIC_EXACT = 4     # USDA on a genuinely exact generic identity.
    ESTIMATED = 5         # deterministic components, or a model estimate of a
                          # composite/restaurant item. Marked as an estimate.
    PROVISIONAL = 6       # the interpreter's first guess. Fallback only.

    @property
    def label(self) -> str:
        return _TIER_LABELS[self]

    @property
    def is_estimate(self) -> bool:
        return self >= SourceTier.ESTIMATED

    @property
    def describes_as_served(self) -> bool:
        """Whether one serving of this source is the dish AS SERVED.

        A branded label and a USDA row define a MEASURED serving — 43 g, 240 ml
        — so "one plate" is not one of them. Every other tier describes the
        helping the user actually had: the label they read us, their own saved
        regular, a restaurant-item estimate, the interpreter's guess. For those,
        one helping is one serving however vaguely it was described.

        Read by scaling to decide whether a count may multiply a per-serving or
        per-unit source; see PerServing.as_served.
        """
        return self not in (SourceTier.BRANDED_EXACT, SourceTier.GENERIC_EXACT)


_TIER_LABELS = {
    SourceTier.USER_LABEL: "user_label",
    SourceTier.USER_REGULAR: "user_regular",
    SourceTier.BRANDED_EXACT: "branded_exact",
    SourceTier.GENERIC_EXACT: "generic_exact",
    SourceTier.ESTIMATED: "estimated",
    SourceTier.PROVISIONAL: "provisional",
}

TIER_BY_LABEL = {v: k for k, v in _TIER_LABELS.items()}


class MatchGrade(str):
    """How well the candidate matched the thing the user actually ate. Kept
    separate from tier: a branded source can still be a poor match."""
    EXACT = "exact"           # same product, brand, variant, serving basis
    CLOSE = "close"           # same product, a detail unconfirmed
    CATEGORY = "category"     # right food class, different preparation/brand
    WEAK = "weak"             # token overlap and hope
    NONE = "none"


#: Grades that may win on their own. Anything weaker has to be disclosed as an
#: assumption, or trigger a clarification, depending on mode.
DECISIVE_GRADES = (MatchGrade.EXACT, MatchGrade.CLOSE)


@dataclass(frozen=True)
class NutrientValue:
    """One number, with everything needed to judge it later.

    `basis` records what the number described BEFORE scaling — per_100g,
    per_serving, per_unit — because a value is meaningless without it, and
    reinterpreting a per-package panel as per-serving is one of the ways this
    system produces confident nonsense.
    """
    value: float
    unit: str                      # kcal | g | mg | mcg
    source: str                    # usda | off | web_label | user_label | ...
    confidence: float = 0.5
    basis: str = "per_serving"     # per_100g | per_100ml | per_serving | per_unit
    source_id: Optional[str] = None
    estimated: bool = False

    def with_value(self, value: float, basis: Optional[str] = None) -> "NutrientValue":
        """A scaled copy. Provenance survives scaling — the number changes, the
        story of where it came from does not."""
        return NutrientValue(value=value, unit=self.unit, source=self.source,
                             confidence=self.confidence,
                             basis=basis or self.basis,
                             source_id=self.source_id, estimated=self.estimated)


@dataclass(frozen=True)
class CandidateRejection:
    """Why a candidate lost. Recorded rather than discarded: "we picked USDA's
    garlic powder" is only diagnosable if the rejected alternatives are in the
    log next to it."""
    source: str
    name: str
    reason: str
    detail: str = ""
    source_id: Optional[str] = None
