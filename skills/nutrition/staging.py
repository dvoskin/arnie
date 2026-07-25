"""Staged food items (directive 2026-07-25, build order 1, 2, 13).

Ambiguity is not a meal-level boolean. "Fairlife, some turkey and a little mac
and cheese" is three items with three independent resolution states, and
treating it as one uncertain blob produces the two failures that follow from
it: clear foods get re-questioned because a neighbour was vague, and a vague
food gets committed because a neighbour was clear.

So every interpreted food becomes a StagedFoodItem BEFORE enrichment or
execution, and carries its own identity, quantity, ambiguities, assumptions
and status.

The separation that does the most work here is identity vs quantity. A food
can have a known identity and unknown amount ("a Fairlife"), or an exact
amount and unknown identity ("14 oz of something"). Collapsing them into one
"how sure are we" number loses the only information that says which question
to ask.

And within quantity, package size is not consumed amount. "14 oz bottle" and
"drank 14 oz" are different facts, and a model that stores them in one field
will eventually log a third of a bottle as a whole one.

Note on types: the directive specifies Decimal for quantities. This uses
float, for consistency with the scaling engine and NutrientProfile, which are
float throughout — a Decimal boundary here would convert at every call and buy
nothing at these magnitudes. Fractions like 0.5 and 0.33 carry no meaningful
drift against portion masses measured in grams.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Optional, Tuple


class FoodClass(str, Enum):
    """What KIND of thing this is, which decides what "resolved" requires.
    A branded product needs product identity, serving basis and consumed
    quantity; a generic food needs identity and amount. One universal
    completeness check would be wrong for both."""
    BRANDED = "branded"
    GENERIC = "generic"
    RESTAURANT = "restaurant"
    COMPOSITE = "composite"
    UNKNOWN = "unknown"


class ResolutionStatus(str, Enum):
    UNRESOLVED = "unresolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    RESOLVED_EXACT = "resolved_exact"
    RESOLVED_ESTIMATED = "resolved_estimated"
    REJECTED = "rejected"

    @property
    def is_resolved(self) -> bool:
        return self in (ResolutionStatus.RESOLVED_EXACT,
                        ResolutionStatus.RESOLVED_ESTIMATED)

    @property
    def is_committable(self) -> bool:
        """Held and staged items are NEVER describable as committed. This is
        the property the renderer reads."""
        return self.is_resolved


@dataclass(frozen=True)
class Quantity:
    """An amount with a unit, and nothing implied about what it measures."""
    amount: float
    unit: str

    def describe(self) -> str:
        return f"{_trim(self.amount)} {self.unit}".strip()


@dataclass(frozen=True)
class FoodIdentity:
    """WHAT it is. Every field is independently unknown-able, because they are
    independently askable: a user can know the brand and not the variant."""
    canonical_name: Optional[str] = None
    brand: Optional[str] = None
    product_line: Optional[str] = None
    variant: Optional[str] = None
    package_size: Optional[Quantity] = None
    barcode: Optional[str] = None

    def known_fields(self) -> tuple:
        return tuple(f for f in ("canonical_name", "brand", "product_line",
                                 "variant", "package_size", "barcode")
                     if getattr(self, f) is not None)

    def describe(self) -> str:
        parts = [p for p in (self.brand, self.product_line, self.variant)
                 if p]
        if not parts and self.canonical_name:
            return self.canonical_name
        if self.package_size is not None:
            parts.append(self.package_size.describe())
        return " ".join(parts) or (self.canonical_name or "")


@dataclass(frozen=True)
class QuantityIntent:
    """HOW MUCH was consumed — deliberately not the same object as identity.

    `package_size` lives on FoodIdentity because it describes the product.
    What lives here is what went in: an amount, a fraction of a container, a
    count of containers, or nothing but a descriptor ("some", "a little").
    """
    stated_amount: Optional[float] = None
    stated_unit: Optional[str] = None
    #: What the INTERPRETER produced when the user did not state an amount.
    #: Kept apart from `stated_*` because the difference is the whole point:
    #: "a scoop of peanut butter" arriving as 1 tbsp is a number we chose, and
    #: a field that cannot tell the two apart reports it as the user's own —
    #: which is how a 190-calorie assumption reached a review turn disguised as
    #: a fact the user had already given us.
    inferred_amount: Optional[float] = None
    inferred_unit: Optional[str] = None
    consumed_fraction: Optional[float] = None
    container_count: Optional[float] = None
    estimated_mass_g: Optional[float] = None
    descriptor: Optional[str] = None
    mass_confidence: Optional[float] = None
    mass_range_g: Optional[Tuple[float, float]] = None

    @property
    def is_stated(self) -> bool:
        """The user gave a number and a unit. Anything else is inference,
        however good."""
        return self.stated_amount is not None and bool(self.stated_unit)

    @property
    def is_inferred(self) -> bool:
        """We chose a number the user did not give. Disclosable, correctable,
        and never presentable as though they had given it."""
        return self.inferred_amount is not None

    @property
    def amount(self) -> Optional[float]:
        """Whatever amount is in force, stated or inferred."""
        return (self.stated_amount if self.stated_amount is not None
                else self.inferred_amount)

    @property
    def unit(self) -> Optional[str]:
        return self.stated_unit or self.inferred_unit

    @property
    def is_vague(self) -> bool:
        return (not self.is_stated and self.consumed_fraction is None
                and self.container_count is None)

    def describe(self) -> str:
        if self.is_stated:
            return f"{_trim(self.stated_amount)} {self.stated_unit}"
        if self.is_inferred:
            return f"{_trim(self.inferred_amount)} {self.inferred_unit or ''}".strip()
        if self.consumed_fraction is not None:
            return f"{_fraction_words(self.consumed_fraction)}"
        if self.container_count is not None:
            return f"{_trim(self.container_count)}×"
        return self.descriptor or ""


@dataclass(frozen=True)
class PreparationIntent:
    """Preparation is separate because it is separately material: raw vs
    roasted moves calories, while the plate it was served on does not."""
    method: Optional[str] = None          # raw | roasted | fried | ...
    stated: bool = False                  # the user said it, vs we inferred it
    modifiers: tuple = ()                 # "no bun", "extra cheese"


@dataclass(frozen=True)
class NutrientDeltaRange:
    """What an assumption could cost if it is wrong."""
    calories: float = 0.0
    protein: float = 0.0
    carbs: float = 0.0
    fat: float = 0.0

    @property
    def is_material(self) -> bool:
        return any((self.calories, self.protein, self.carbs, self.fat))


@dataclass(frozen=True)
class FoodAssumption:
    """A decision made on the user's behalf, in a shape that can be explained,
    contradicted and learned from. A free-text string can do none of those."""
    staged_item_id: str
    field_name: str
    assumed_value: Any
    alternatives: tuple = ()
    confidence: float = 0.5
    nutrition_impact: NutrientDeltaRange = field(
        default_factory=NutrientDeltaRange)
    user_visible_text: str = ""

    def describe(self) -> str:
        return self.user_visible_text or (
            f"Assumed {self.field_name.replace('_', ' ')} was "
            f"{self.assumed_value}.")


@dataclass(frozen=True)
class StagedFoodItem:
    """One food, with everything known and unknown about it.

    Nothing downstream re-derives identity or quantity from `original_text` —
    that re-derivation is what makes a clarification answer land on the wrong
    row.
    """
    staged_item_id: str
    original_text: str
    ordinal: int = 0
    food_class: FoodClass = FoodClass.UNKNOWN
    identity: FoodIdentity = field(default_factory=FoodIdentity)
    quantity: QuantityIntent = field(default_factory=QuantityIntent)
    preparation: PreparationIntent = field(default_factory=PreparationIntent)
    candidate_products: tuple = ()
    ambiguities: tuple = ()
    resolution_status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    assumptions: tuple = ()
    meal_group_id: str = ""

    # ── ambiguity access ──────────────────────────────────────────────────────
    def ambiguity_for(self, field_name: str):
        return next((a for a in self.ambiguities
                     if a.field_name == field_name), None)

    def material_ambiguities(self, threshold: float = 1.0) -> tuple:
        return tuple(a for a in self.ambiguities
                     if a.materiality_score >= threshold)

    # ── transitions ───────────────────────────────────────────────────────────
    def with_status(self, status: ResolutionStatus) -> "StagedFoodItem":
        return replace(self, resolution_status=status)

    def with_ambiguities(self, ambiguities) -> "StagedFoodItem":
        return replace(self, ambiguities=tuple(ambiguities))

    def with_assumption(self, assumption: FoodAssumption) -> "StagedFoodItem":
        return replace(self, assumptions=self.assumptions + (assumption,))

    def resolving(self, **fields) -> "StagedFoodItem":
        """Apply answered fields to identity and quantity, and drop the
        ambiguities they settled. The item's IDENTITY as a staged row never
        changes — that is what makes a late answer safe."""
        identity_fields = {k: v for k, v in fields.items()
                           if k in FoodIdentity.__dataclass_fields__}
        quantity_fields = {k: v for k, v in fields.items()
                           if k in QuantityIntent.__dataclass_fields__}
        item = self
        if identity_fields:
            item = replace(item, identity=replace(item.identity,
                                                  **identity_fields))
        if quantity_fields:
            item = replace(item, quantity=replace(item.quantity,
                                                  **quantity_fields))
        settled = set(fields)
        return replace(item, ambiguities=tuple(
            a for a in item.ambiguities if a.field_name not in settled))


# ── construction ──────────────────────────────────────────────────────────────
def make_staged_item_id(turn_id: str, ordinal: int, text: str) -> str:
    """Stable within a turn, unique across turns. A clarification answer
    arriving an hour later must still name exactly one row."""
    digest = hashlib.sha1(
        f"{turn_id}|{ordinal}|{(text or '').strip().lower()}".encode("utf-8")
    ).hexdigest()[:12]
    return f"item_{digest}"


def make_meal_group_id(turn_id: str) -> str:
    """Shared by every item in one meal, so a partial commit and its later
    completion land in the same card rather than two disconnected ones."""
    digest = hashlib.sha1((turn_id or "").encode("utf-8")).hexdigest()[:10]
    return f"meal_{digest}"


def classify_food(name: str, brand: Optional[str] = None,
                  is_packaged: bool = False) -> FoodClass:
    """Best-effort class from the words alone. Wrong guesses cost a
    completeness rule, not a nutrient — and UNKNOWN is a legitimate answer."""
    n = (name or "").lower().strip()
    if not n:
        return FoodClass.UNKNOWN
    if brand or is_packaged:
        return FoodClass.BRANDED
    if any(w in n for w in _RESTAURANT_HINTS):
        return FoodClass.RESTAURANT
    if any(w in n for w in _COMPOSITE_HINTS):
        return FoodClass.COMPOSITE
    if len(n.split()) <= 4:
        return FoodClass.GENERIC
    return FoodClass.COMPOSITE


_RESTAURANT_HINTS = ("starbucks", "chipotle", "mcdonald", "dunkin", "subway",
                     "cava", "sweetgreen", "panera", "chick-fil-a", "wendy",
                     "taco bell", "restaurant", "takeout", "take-out")
_COMPOSITE_HINTS = ("bowl", "platter", "sandwich", "burrito", "wrap", "salad",
                    "stew", "casserole", "curry", "stir fry", "stir-fry",
                    "lasagna", "pasta with", "plate of")


# ── completeness (directive 24) ───────────────────────────────────────────────
#: What each class must know before it counts as resolved. Deliberately not one
#: universal check: a branded product is not resolved without a serving basis,
#: and a generic food does not need one.
REQUIRED_FIELDS = {
    FoodClass.BRANDED: ("identity", "serving_basis", "consumed_quantity"),
    FoodClass.GENERIC: ("identity", "consumed_quantity"),
    FoodClass.RESTAURANT: ("identity", "consumed_quantity"),
    FoodClass.COMPOSITE: ("identity", "consumed_quantity"),
    FoodClass.UNKNOWN: ("identity", "consumed_quantity"),
}


def missing_requirements(item: StagedFoodItem,
                         serving_basis_known: bool = False) -> tuple:
    """Which required facts this item still lacks."""
    required = REQUIRED_FIELDS.get(item.food_class,
                                   REQUIRED_FIELDS[FoodClass.UNKNOWN])
    missing = []
    if "identity" in required and not _identity_known(item):
        missing.append("identity")
    if "serving_basis" in required and not serving_basis_known:
        missing.append("serving_basis")
    if "consumed_quantity" in required and not _quantity_known(item):
        missing.append("consumed_quantity")
    return tuple(missing)


def _identity_known(item: StagedFoodItem) -> bool:
    identity = item.identity
    if item.food_class is FoodClass.BRANDED:
        # A brand alone is not an identity — Fairlife makes four products with
        # materially different nutrition.
        return bool(identity.barcode) or bool(
            identity.brand and (identity.product_line or identity.variant))
    return bool(identity.canonical_name or identity.brand)


def _quantity_known(item: StagedFoodItem) -> bool:
    q = item.quantity
    return (q.is_stated or q.consumed_fraction is not None
            or q.container_count is not None
            or q.estimated_mass_g is not None)


# ── helpers ───────────────────────────────────────────────────────────────────
_FRACTION_WORDS = {0.25: "a quarter", 0.5: "half", 0.75: "three quarters",
                   1.0: "all of it"}


def _fraction_words(f: float) -> str:
    for value, words in _FRACTION_WORDS.items():
        if abs(f - value) < 0.02:
            return words
    return f"{_trim(f * 100)}%"


def _trim(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"
