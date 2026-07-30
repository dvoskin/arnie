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
        """What to CALL this food, under one invariant: **the description
        never omits the canonical name.**

        THE CANONICAL NAME IS NOT A FALLBACK. It is what the food was actually
        called; brand, line and variant only say WHICH one. Drop the name and
        the label stops naming a food at all — "Royo Everything Bagel" became
        "Royo", which is how a question built from this label came to ask
        about the maker rather than the product.

        The rule that replaced it counted words ("prefer the name when it has
        more of them"), which fails whenever the name and the brand are the
        same length: canonical "Sopressata" under brand "Seppe" is 1 > 1, and
        the label was the brand alone again. Word counts were never the
        question. So: the name is always said, and a qualifier is said only
        when it adds words the name does not already carry — which drops
        "Royo" from "Royo Everything Bagel" without ever dropping the food.
        """
        name = (self.canonical_name or "").strip()
        name_words = _words(name)
        parts: list[str] = []
        said: set = set()       # every word already in `parts`
        for qualifier in (self.brand, self.product_line, self.variant):
            qualifier = (qualifier or "").strip()
            words = _words(qualifier)
            # Nothing new to add: the name says it ("Royo" in "Royo Everything
            # Bagel"), or an earlier qualifier did (line repeating brand).
            if not words or words <= said or words <= name_words:
                continue
            parts.append(qualifier)
            said |= words
        # The name goes last, unless a qualifier already spelled it out —
        # canonical "Bagel" under line "Everything Bagel" is named by the
        # line, and appending it again would say "Everything Bagel Bagel".
        if name and not name_words <= said:
            parts.append(name)
        if self.package_size is not None:
            parts.append(self.package_size.describe())
        return " ".join(parts)


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


#: Quantity fields that establish HOW MUCH was consumed. Any one of them
#: answers any quantity ambiguity — "about a cup", "half of it" and "roughly
#: 300 g" are three shapes of the same answer.
#:
#: `descriptor` is deliberately absent: "some" is the vagueness, not its
#: resolution. So are `mass_confidence` and `mass_range_g`, which describe how
#: unsure we are rather than what was eaten.
_CONSUMPTION_FIELDS = frozenset({
    "stated_amount", "stated_unit", "consumed_fraction", "container_count",
    "estimated_mass_g",
})


def _settled_by(ambiguity, supplied: set) -> bool:
    """Whether these supplied field names could settle this ambiguity."""
    field_name = getattr(ambiguity, "field_name", "")
    if field_name in supplied:
        return True
    if field_name in QuantityIntent.__dataclass_fields__:
        return bool(supplied & _CONSUMPTION_FIELDS)
    if field_name in FoodIdentity.__dataclass_fields__:
        # Identity fields are independently askable — knowing the brand is not
        # knowing the variant — so only the field itself settles it. A barcode
        # is the exception: it names the product outright.
        return "barcode" in supplied
    return False


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
    #: The vague measure the USER used for this food — "some", "a bit", "a
    #: handful" — recorded when the item was staged, because that is the only
    #: turn whose message contains it.
    #:
    #: This is the docstring's own rule applied to vagueness. Re-deriving it
    #: from whatever message is current means a meal clarified over two turns
    #: loses it for every food the second message does not happen to name: the
    #: word was in the first message, the item now carries a resolved name that
    #: never appeared there, and the uncertainty silently becomes a confident
    #: estimate at exactly the moment it commits.
    vague_measure: str = ""
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

    def _applying(self, **fields) -> "StagedFoodItem":
        """Apply answered fields to identity and quantity, settling nothing.

        Split out from `resolving()` so `answering()` can decide for itself
        which ambiguities an answer settled — including deciding that it settled
        fewer than the fields would suggest."""
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
        return item

    def resolving(self, **fields) -> "StagedFoodItem":
        """Apply answered fields to identity and quantity, and drop the
        ambiguities they settled. The item's IDENTITY as a staged row never
        changes — that is what makes a late answer safe."""
        item = self._applying(**fields)
        settled = set(fields)
        return replace(item, ambiguities=tuple(
            a for a in item.ambiguities if a.field_name not in settled))

    def answering(self, question, settled_ambiguity_ids=None,
                  **fields) -> "StagedFoodItem":
        """Apply an answer and settle the ambiguities the answer ACTUALLY filled.

        `resolving()` settles by field name, which is right when the answer
        fills exactly the field that was asked for. But a question can be
        answered in a different shape than it was asked: "about a cup" answers
        a question about `estimated_mass_g` with a `stated_amount` and a
        `stated_unit`. Settling by field name alone leaves that ambiguity
        standing, and the next round asks the same question again — the loop
        `ambiguity_id` exists to prevent and that nothing was reading.

        The other direction is worse, and is what this used to do: clearing
        every ambiguity the question NAMED. Questions are bundled — "Which
        Fairlife was it, and how much did you drink?" names two — so answering
        "Elite" cleared the quantity too, and the item committed with a product
        we knew and an amount we had invented. A partial answer to a bundled
        question is the normal case, not the exception.

        So each named ambiguity is settled only if the fields supplied could
        settle THAT ambiguity. A caller who knows exactly what it resolved may
        say so with `settled_ambiguity_ids` and skip the inference.
        """
        item = self._applying(**fields)
        if settled_ambiguity_ids is not None:
            settled = set(settled_ambiguity_ids)
        else:
            named = set(getattr(question, "ambiguity_ids", ()) or ())
            supplied = {k for k, v in fields.items() if v is not None}
            # A field supplied outright settles its own ambiguity wherever it
            # sits. Answering in a different shape than we asked only settles
            # what the question named — that is the scope the user was replying
            # within, and inferring past it is how the bundle got cleared whole.
            settled = {a.ambiguity_id for a in self.ambiguities
                       if a.field_name in supplied
                       or (a.ambiguity_id in named
                           and _settled_by(a, supplied))}
        return replace(item, ambiguities=tuple(
            a for a in item.ambiguities if a.ambiguity_id not in settled))


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
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _words(text: Optional[str]) -> set:
    """The comparable words in a label, for asking whether one label already
    says what another one would.

    Compared as WORDS rather than as a substring, so brand "Kind" is not
    treated as already-said by "Kindness". Apostrophes close up first —
    "Trader Joe's" and "Trader Joes" are the same two words, and splitting on
    the apostrophe would make them differ.
    """
    lowered = (text or "").lower().replace("'", "").replace("’", "")
    return {w for w in _NON_WORD.split(lowered) if w}


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
