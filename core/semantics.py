"""The cross-domain semantic contracts. Food is their first implementation.

Every concept here is one that food was about to define a food-shaped version
of — quantities, references, clarification fields, pending lifecycle,
provenance. None of them is food-specific, and the reason to land them before
the food redesign rather than after is that the alternative has already
happened once: food grew its own, and generalising afterwards is the work this
document exists to avoid repeating.

WHAT THIS MODULE DELIBERATELY DOES NOT CONTAIN, and why that is the point:

  * `ExecutionResult` / `CallResult` — `core/execution_result.py` already
    defines them, already cross-domain, already consumed by food and exercise.
    Adding a second would be the exact anti-pattern this module exists to end.
    They are re-exported here so a caller reaching for "the canonical execution
    result" finds the one that exists.
  * a nutrition ontology, an exercise catalogue, a habit taxonomy. Domain
    ontologies are deferred on product need; the CONTRACTS are not.

WHAT IT REPLACES, EVENTUALLY. These types exist today in food-specific form and
should adapt into these rather than persist beside them:

    skills/nutrition/models.NormalizedQuantity      -> CanonicalQuantity
    skills/nutrition/clarify_policy.ClarificationOption  -> ClarificationOption
    skills/nutrition/ambiguity.AmbiguityOption      -> ClarificationOption
    skills/nutrition/clarify_policy.ClarificationQuestion -> ClarificationField
    db.models.PendingQuestion (+ payload_json)      -> PendingOperation

Note that food already has TWO option types. That is the duplication this is
meant to stop, visible inside a single domain before it has spread.

Nothing here is wired into a live path yet. Landing the types first, with
adapters and tests, is what lets each migration be a small reviewable change
instead of one uncontrolled pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, Optional

# The canonical execution result ALREADY EXISTS and is already cross-domain.
# Re-exported, never redefined.
from core.execution_result import CallResult, ExecutionResult  # noqa: F401

__all__ = [
    "CallResult", "ExecutionResult",
    "Provenance", "Confidence", "ResolutionStatus", "Dimension",
    "SemanticTurn", "CanonicalIntent", "CanonicalQuantity",
    "EventReference", "CanonicalEvent",
    "ClarificationOption", "ClarificationField",
    "PendingOperation", "PendingStatus",
    # B-0b/B-0c: the typed clarification layer and its storage form.
    "ClarificationAttribute", "ResponseType", "ClarificationStatus",
    "CandidateSource", "CandidateValue", "UncertaintyEvidence",
    "UnresolvedField", "ClarificationGroup", "ClarificationInteraction",
    "SemanticPatch", "SetQuantity", "SetConsumedFraction", "SelectEntity",
    "SelectProductVariant", "SetPreparation", "SetServingBasis",
    "PATCH_TYPES", "PATCH_SCHEMA_VERSION", "patch_from_payload",
    "UnknownPatchType",
]


# ── provenance ───────────────────────────────────────────────────────────────

class Provenance(str, Enum):
    """WHERE a value came from, which decides how much it may be trusted and
    whether it may be presented as the user's own.

    The distinction that matters most is `USER_STATED` vs `USER_SELECTED`. A
    typed "6 oz" is a figure the user produced; a tapped chip is a figure WE
    produced and they accepted. Collapsing them is how a system-generated
    portion gets recorded as user precision — measured in food on 2026-08-04,
    where a tapped chip cleared the `estimated` flag and with it the "(my
    estimate)" marker, the card range and the disclosure.
    """
    USER_STATED = "user_stated"
    USER_SELECTED = "user_selected"
    USER_CONFIRMED = "user_confirmed"
    LABEL = "label"
    CATALOG = "catalog"
    USER_HISTORY = "user_history"
    ONTOLOGY = "ontology"
    MODE_DEFAULT = "mode_default"
    MODEL_ESTIMATE = "model_estimate"
    UNKNOWN = "unknown"

    @property
    def is_users_own(self) -> bool:
        """Only a figure the user actually produced. A selection is not one."""
        return self is Provenance.USER_STATED

    @property
    def is_assumption(self) -> bool:
        """Must be disclosed, and must remain revisable."""
        return self in (Provenance.MODE_DEFAULT, Provenance.ONTOLOGY,
                        Provenance.MODEL_ESTIMATE)


@dataclass(frozen=True)
class Confidence:
    """A score with the evidence that produced it.

    A bare float is unauditable: 0.61 tells you nothing about whether to ask.
    `basis` is what a receipt renders and what telemetry groups by.
    """
    score: float = 0.0
    basis: str = ""

    def __post_init__(self):
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"confidence out of range: {self.score}")

    def to_payload(self) -> dict:
        return {"score": float(self.score), "basis": self.basis}

    @classmethod
    def from_payload(cls, data: Optional[dict]) -> "Confidence":
        if not data:
            return cls()
        return cls(score=float(data.get("score") or 0.0),
                   basis=data.get("basis") or "")


class NutritionProvenance(str, Enum):
    """WHO SUPPLIED THE NUMBERS — distinct from who chose the food.

    `Provenance` answers "where did this VALUE come from" for a quantity the
    user expressed. This answers the narrower question the ledger needs for
    every committed row: which system produced the calories and macros.

    NO DEFAULT THAT CLAIMS AUTHORITY. An unset field must not read as
    `SERVER_RESOLVED` — that is the resolver asserting it priced something it
    never saw, and it is unfalsifiable after the fact because the row looks
    identical to a genuinely resolved one. `UNKNOWN` is the only safe default:
    it says the pricing system was not recorded, which is true.
    """
    #: A product/food database supplied the panel.
    CATALOG = "catalog"
    #: The user typed the numbers themselves.
    USER_STATED = "user_stated"
    #: NARROW BY DESIGN: the user selected an explicit NUTRITIONAL VALUE
    #: option ("~300 cal") — not merely a food identity or a quantity chip.
    #: Picking "Elite 42g" identifies the PRODUCT; the numbers still come from
    #: the catalog, so that row is CATALOG here and `Provenance.USER_SELECTED`
    #: on the event. Answer provenance and pricing provenance are different
    #: axes, and this enum owns only the second — collapsing them is the exact
    #: conflation it exists to remove.
    USER_SELECTED = "user_selected"
    #: The CLIENT calculated them locally (a quick-log tap). Structured input,
    #: not authority — the boundary still validates it.
    CLIENT_ESTIMATED = "client_estimated"
    #: The server's nutrition resolver priced it.
    SERVER_RESOLVED = "server_resolved"
    #: A human overrode a previously committed value.
    MANUAL_OVERRIDE = "manual_override"
    #: Not recorded. The honest default; never an authority claim.
    UNKNOWN = "unknown"

    # NO `is_authoritative` PROPERTY, deliberately (removed before any
    # consumer existed). "Authoritative" is at least five different questions —
    # source authority, confidence, verification, presentation hedging, commit
    # eligibility — and one boolean would quietly come to govern all of them.
    # A high-confidence resolver output can be committable and still owe a
    # source disclosure; a user-stated number is authoritative as a statement
    # and can be factually wrong. When a policy consumer arrives it gets a
    # narrowly named predicate for its one question.


class ResolutionStatus(str, Enum):
    """UNKNOWN IS A VALID ANSWER. Forcing a match is how a false one gets a
    piece weight, merges two foods, or overwrites a correction target."""
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"

    @property
    def is_actionable(self) -> bool:
        return self is ResolutionStatus.RESOLVED


# ── quantity ─────────────────────────────────────────────────────────────────

class Dimension(str, Enum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"
    DURATION = "duration"
    DISTANCE = "distance"
    ENERGY = "energy"
    DIMENSIONLESS = "dimensionless"


# ── serialization primitives (B-0c) ──────────────────────────────────────────
#
# DECIMALS CROSS AS STRINGS, never as JSON numbers. `Decimal("0.1")` through a
# float is `0.1000000000000000055511151231257827`, so a round trip that looks
# equal at two decimal places is not equal, and `CanonicalQuantity` uses
# `Decimal` precisely to keep portion arithmetic exact. A string round-trips
# byte-for-byte and compares equal, which is what the round-trip test asserts.

def _dec_out(v: Optional[Decimal]) -> Optional[str]:
    return None if v is None else str(v)


def _dec_in(v) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    return Decimal(str(v))


@dataclass(frozen=True)
class CanonicalQuantity:
    """An amount, in one shape, for every domain.

    Cross-domain on purpose: a set of 8 reps, 500 ml of water, 80 kg of
    bodyweight and 4 oz of chicken are the same problem, and food currently
    solves it alone in `NormalizedQuantity`.

    DIMENSIONAL CONSISTENCY IS ENFORCED AT CONSTRUCTION. The directive names
    the failure exactly — an object claiming `amount=1, unit=ml,
    milliliters=236.6` is not a quantity, it is two quantities in a trench
    coat, and food has shipped that shape. It is rejected here rather than
    detected downstream, because downstream is where it becomes a calorie.

    `range_min`/`range_max` carry a stated span ("3-4 oz") rather than
    collapsing it to a midpoint the user never said.
    """
    amount: Optional[Decimal] = None
    unit_id: str = ""
    dimension: Dimension = Dimension.DIMENSIONLESS

    range_min: Optional[Decimal] = None
    range_max: Optional[Decimal] = None

    grams: Optional[Decimal] = None
    milliliters: Optional[Decimal] = None
    count: Optional[Decimal] = None
    count_entity_id: str = ""

    provenance: Provenance = Provenance.UNKNOWN
    confidence: Confidence = field(default_factory=Confidence)
    uncertainty: Optional[Decimal] = None
    surface_text: str = ""

    def __post_init__(self):
        # COERCED, LIKE EVERY OTHER ENUM FIELD IN THIS MODULE. A string
        # provenance survived construction and then failed at
        # `is_estimated` -> `provenance.is_users_own` (AttributeError on str),
        # or compared False against every `is` check — silently reclassifying
        # a user's own figure as an estimate. Values arrive as strings the
        # moment they come off the wire or out of storage, so this is the
        # normal shape, not the exotic one.
        object.__setattr__(self, "provenance", Provenance(self.provenance))
        object.__setattr__(self, "dimension", Dimension(self.dimension))
        if (self.range_min is not None and self.range_max is not None
                and self.range_min > self.range_max):
            raise ValueError(
                f"range inverted: {self.range_min} > {self.range_max}")
        for name in ("amount", "grams", "milliliters", "count", "uncertainty"):
            v = getattr(self, name)
            if v is not None and v < 0:
                raise ValueError(f"{name} is negative: {v}")
        # The trench-coat check: a MASS quantity may not carry a volume as its
        # resolved value, and vice versa. Both may be present only when a real
        # density conversion produced them, which sets both deliberately.
        if self.dimension is Dimension.MASS and self.milliliters is not None \
                and self.grams is None:
            raise ValueError(
                "mass quantity resolved only to millilitres — "
                "the dimension and the resolved value disagree")
        if self.dimension is Dimension.VOLUME and self.grams is not None \
                and self.milliliters is None:
            raise ValueError(
                "volume quantity resolved only to grams — "
                "the dimension and the resolved value disagree")

    @property
    def is_estimated(self) -> bool:
        return not self.provenance.is_users_own

    @property
    def is_range(self) -> bool:
        return self.range_min is not None and self.range_max is not None

    _DECIMAL_FIELDS = ("amount", "range_min", "range_max", "grams",
                       "milliliters", "count", "uncertainty")

    def to_payload(self) -> dict:
        data = {n: _dec_out(getattr(self, n)) for n in self._DECIMAL_FIELDS}
        data.update(unit_id=self.unit_id, dimension=self.dimension.value,
                    count_entity_id=self.count_entity_id,
                    provenance=self.provenance.value,
                    confidence=self.confidence.to_payload(),
                    surface_text=self.surface_text)
        return data

    @classmethod
    def from_payload(cls, data: Optional[dict]) -> Optional["CanonicalQuantity"]:
        if data is None:
            return None
        kw = {n: _dec_in(data.get(n)) for n in cls._DECIMAL_FIELDS}
        return cls(unit_id=data.get("unit_id") or "",
                   dimension=Dimension(data.get("dimension")
                                       or Dimension.DIMENSIONLESS),
                   count_entity_id=data.get("count_entity_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   confidence=Confidence.from_payload(data.get("confidence")),
                   surface_text=data.get("surface_text") or "", **kw)


# ── references and events ────────────────────────────────────────────────────

@dataclass(frozen=True)
class EventReference:
    """A pointer to something already recorded — "that", "the same as
    yesterday", "make it two", "undo that".

    THIS IS WHAT CORRECTIONS MUST BIND TO. Today a correction binds to the
    closest STRING, which is why a token-subset match can retarget the wrong
    row; `_undeferred`'s fuzzy claim loop is the measured worst case, and its
    own comment says it can delete a row the user reported.

    `surface_text` and `resolution_status` travel together so an unresolved
    reference stays unresolved instead of silently picking a nearest match.
    """
    surface_text: str = ""
    event_id: Optional[str] = None
    entity_id: Optional[str] = None
    ordinal: Optional[int] = None
    relative_day: Optional[int] = None
    resolution_status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    confidence: Confidence = field(default_factory=Confidence)

    @property
    def is_bound(self) -> bool:
        return bool(self.event_id) and self.resolution_status.is_actionable


@dataclass(frozen=True)
class CanonicalEvent:
    """One thing that happened, in any domain, with a stable id.

    `domain` and `entity_id` rather than a food name: identity is an ID, and a
    string is evidence for one.
    """
    id: str
    domain: str
    entity_id: Optional[str] = None
    entity_type: str = "unknown"
    surface_text: str = ""
    quantity: Optional[CanonicalQuantity] = None
    attributes: dict = field(default_factory=dict)
    occurred_at: Optional[str] = None
    resolution_status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    confidence: Confidence = field(default_factory=Confidence)
    provenance: Provenance = Provenance.UNKNOWN
    references: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "provenance", Provenance(self.provenance))
        object.__setattr__(self, "resolution_status",
                           ResolutionStatus(self.resolution_status))


# ── clarification ────────────────────────────────────────────────────────────
#
# B-0b (chip directive, 2026-08-05): the typed layer the four legacy producers
# migrate ONTO. `ClarificationAttribute`/`ResponseType`/`ClarificationStatus`
# close what were free strings; `SemanticPatch` makes every answer — chip tap
# or typed text — a validated, applicable change instead of a string the
# answer turn re-interprets. Cross-domain by construction: food supplies food
# patches, workouts will supply theirs, and the application boundary is shared.


class ClarificationAttribute(str, Enum):
    """WHAT a field asks about. A closed set, because `attribute="prepration"`
    (a typo) was representable and silently unanswerable — the adapter today
    infers this from rendered PROSE, which is the reversal the whole migration
    exists to undo."""
    # food
    QUANTITY = "quantity"
    CONSUMED_FRACTION = "consumed_fraction"
    FOOD_IDENTITY = "food_identity"
    PRODUCT_VARIANT = "product_variant"
    PACKAGE_SIZE = "package_size"
    PREPARATION = "preparation"
    SERVING_BASIS = "serving_basis"
    # workout (Phase O; defined so the shared layer never needs a food edit)
    EXERCISE_IDENTITY = "exercise_identity"
    SET_COUNT = "set_count"
    REP_COUNT = "rep_count"
    EXTERNAL_LOAD = "external_load"
    DURATION = "duration"
    DISTANCE = "distance"
    EQUIPMENT = "equipment"
    EFFORT = "effort"


class ResponseType(str, Enum):
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    FREE_TEXT = "free_text"
    #: A select whose options could not be generated. C15: this must become
    #: free text EXPLICITLY, repair, or fail closed — never a blank row the
    #: client "fixes" by parsing prose.
    FREE_TEXT_FALLBACK = "free_text_fallback"


class ClarificationStatus(str, Enum):
    UNRESOLVED = "unresolved"
    ANSWERED = "answered"
    SKIPPED = "skipped"
    ESTIMATED = "estimated"          # user said "estimate it"
    EXPIRED = "expired"


class CandidateSource(str, Enum):
    """WHERE a candidate value came from — the evidence hierarchy, as data.

    Order here mirrors the resolution directive's authority ladder; the
    weighting lives in the selector, not in this enum, but the NAMES are closed
    so telemetry can group and a selector cannot be handed a source it has no
    policy for.
    """
    USER_HISTORY = "user_history"
    CATALOG = "catalog"              # OFF / USDA / product data
    WEB_EVIDENCE = "web_evidence"
    ONTOLOGY = "ontology"
    MODEL_PROPOSAL = "model_proposal"
    MODE_DEFAULT = "mode_default"
    #: HealthKit / Whoop / Oura — a recorded measurement, not an inference.
    #: Pre-provisioned like the workout attributes above so the shared layer
    #: never needs a food edit: it is the PRIMARY candidate source for workout
    #: DURATION and DISTANCE, and this enum is closed, so its absence made a
    #: device-sourced candidate unconstructable. B-1's food candidate rules
    #: exclude it, so no selector policy is owed yet (docs/WORKOUT_CONTRACTS).
    DEVICE = "device"


# ── semantic patches ─────────────────────────────────────────────────────────
#
# THE PATCH IS THE MEANING; the label is only presentation (C10/C11 targets).
# A chip tap submits (operation, revision, field, option) and the SERVER loads
# the stored patch; a typed answer parses into the SAME patch type. Both then
# cross one application boundary. No dict merges: every patch names the event
# and field it changes, and the domain validates it before it applies.

#: Bumped when a patch's stored shape changes in a way older code would
#: misread. Read on load and failed closed, never guessed at.
PATCH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SemanticPatch:
    """Base of every typed answer. Domain subclasses add the value.

    A PATCH IS STORED AND RELOADED, so it carries a discriminator. B-1's wire
    contract is that a tap submits only ids and the server loads the stored
    patch — which means the stored form must say which patch it IS. Without
    `patch_type` the server would recover meaning by sniffing which keys are
    present, i.e. re-inferring semantics from shape: the same defect as
    parsing chips out of prose, relocated server-side.
    """
    event_id: str
    field_id: str
    provenance: Provenance = Provenance.UNKNOWN

    #: The stored discriminator. A ClassVar, not a field, so it cannot be
    #: overridden per instance — the type declares what it is.
    patch_type: ClassVar[str] = ""

    def __post_init__(self):
        if not self.event_id:
            raise ValueError(f"{type(self).__name__} needs the event it "
                             f"changes — a patch with no target is a guess")
        if not self.field_id:
            raise ValueError(f"{type(self).__name__} needs the field it "
                             f"answers — C9's lesson is that unowned answers "
                             f"get re-parsed from prose")
        # Symmetric with UnresolvedField.attribute and CandidateValue.source:
        # coerce at the boundary so every internal value is an enum instance.
        object.__setattr__(self, "provenance", Provenance(self.provenance))

    # ── storage ──────────────────────────────────────────────────────────
    def _value_payload(self) -> dict:
        """Subclass values. The base carries only target and provenance."""
        return {}

    def to_payload(self) -> dict:
        if not self.patch_type:
            raise ValueError(
                f"{type(self).__name__} has no patch_type — an unregistered "
                f"patch cannot be stored, because nothing could load it back")
        data = {"patch_type": self.patch_type,
                "schema_version": PATCH_SCHEMA_VERSION,
                "event_id": self.event_id, "field_id": self.field_id,
                "provenance": self.provenance.value}
        data.update(self._value_payload())
        return data

    @classmethod
    def _from_values(cls, data: dict) -> "SemanticPatch":
        """Subclass hook: build from a payload. Validation re-runs via
        `__post_init__`, so a corrupted row fails on load, not at apply."""
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN))


@dataclass(frozen=True)
class SetQuantity(SemanticPatch):
    """The user's answer to "how much" — a CanonicalQuantity, so dimensional
    validity is enforced where the patch is BUILT, not where it lands."""
    quantity: Optional[CanonicalQuantity] = None

    patch_type: ClassVar[str] = "set_quantity"

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.quantity, CanonicalQuantity):
            raise ValueError("SetQuantity carries a CanonicalQuantity — a bare "
                             "number cannot say what dimension it is")

    def _value_payload(self) -> dict:
        return {"quantity": self.quantity.to_payload()}

    @classmethod
    def _from_values(cls, data: dict) -> "SetQuantity":
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   quantity=CanonicalQuantity.from_payload(
                       data.get("quantity")))


@dataclass(frozen=True)
class SetConsumedFraction(SemanticPatch):
    """How much of the thing was actually eaten (0 < fraction <= 1]."""
    fraction: Optional[Decimal] = None

    patch_type: ClassVar[str] = "set_consumed_fraction"

    def __post_init__(self):
        super().__post_init__()
        f = self.fraction
        if f is None or not (Decimal("0") < Decimal(f) <= Decimal("1")):
            raise ValueError(f"consumed fraction must be in (0, 1], got {f!r}")
        object.__setattr__(self, "fraction", Decimal(f))

    def _value_payload(self) -> dict:
        return {"fraction": _dec_out(self.fraction)}

    @classmethod
    def _from_values(cls, data: dict) -> "SetConsumedFraction":
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   fraction=_dec_in(data.get("fraction")))


@dataclass(frozen=True)
class SelectEntity(SemanticPatch):
    """Resolve WHICH entity this event is — an entity id, never a fuzzy label.

    DOMAIN-NEUTRAL ON PURPOSE. It writes `CanonicalEvent.entity_id`, which
    every domain has, so `EXERCISE_IDENTITY` is answerable without a second
    byte-identical patch class and a second arm at the shared application
    boundary. Renamed from `SelectFoodEntity` while zero producers existed:
    once B-1 stores patches, `patch_type` is wire data and a rename is a
    migration.
    """
    entity_id: str = ""

    patch_type: ClassVar[str] = "select_entity"

    def __post_init__(self):
        super().__post_init__()
        if not self.entity_id:
            raise ValueError("SelectEntity without an entity_id is the "
                             "string-matching defect this type replaces")

    def _value_payload(self) -> dict:
        return {"entity_id": self.entity_id}

    @classmethod
    def _from_values(cls, data: dict) -> "SelectEntity":
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   entity_id=data.get("entity_id") or "")


@dataclass(frozen=True)
class SelectProductVariant(SemanticPatch):
    """Which catalog product/serving — stable ids, e.g. off:3017620422003."""
    entity_id: str = ""
    serving_id: str = ""

    patch_type: ClassVar[str] = "select_product_variant"

    def __post_init__(self):
        super().__post_init__()
        if not self.entity_id:
            raise ValueError("SelectProductVariant needs the product's id")

    def _value_payload(self) -> dict:
        return {"entity_id": self.entity_id, "serving_id": self.serving_id}

    @classmethod
    def _from_values(cls, data: dict) -> "SelectProductVariant":
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   entity_id=data.get("entity_id") or "",
                   serving_id=data.get("serving_id") or "")


@dataclass(frozen=True)
class SetPreparation(SemanticPatch):
    """Grilled / fried / … — an ontology preparation id, not free text."""
    preparation_id: str = ""

    patch_type: ClassVar[str] = "set_preparation"

    def __post_init__(self):
        super().__post_init__()
        if not self.preparation_id:
            raise ValueError("SetPreparation needs a preparation id")

    def _value_payload(self) -> dict:
        return {"preparation_id": self.preparation_id}

    @classmethod
    def _from_values(cls, data: dict) -> "SetPreparation":
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   preparation_id=data.get("preparation_id") or "")


@dataclass(frozen=True)
class SetServingBasis(SemanticPatch):
    """Which label basis the numbers are per (per-container, per-serving…)."""
    basis_id: str = ""

    patch_type: ClassVar[str] = "set_serving_basis"

    def __post_init__(self):
        super().__post_init__()
        if not self.basis_id:
            raise ValueError("SetServingBasis needs a basis id")

    def _value_payload(self) -> dict:
        return {"basis_id": self.basis_id}

    @classmethod
    def _from_values(cls, data: dict) -> "SetServingBasis":
        return cls(event_id=data.get("event_id") or "",
                   field_id=data.get("field_id") or "",
                   provenance=Provenance(data.get("provenance")
                                         or Provenance.UNKNOWN),
                   basis_id=data.get("basis_id") or "")


#: THE CLOSED REGISTRY. An explicit dict rather than a subclass walk: a patch
#: type is stored data, so which strings are loadable must be a decision
#: someone made, not a consequence of what happens to be imported.
PATCH_TYPES = {cls.patch_type: cls for cls in (
    SetQuantity, SetConsumedFraction, SelectEntity, SelectProductVariant,
    SetPreparation, SetServingBasis)}


class UnknownPatchType(ValueError):
    """A stored patch this build cannot interpret. Fails closed — guessing
    which patch a payload meant is the re-inference the type system removes."""


def patch_from_payload(data: Optional[dict]) -> SemanticPatch:
    """Load a stored patch back as its CONCRETE type.

    `SetQuantity -> JSON -> SetQuantity`, never `-> dict`. Every subclass's
    `__post_init__` re-runs, so a payload that has been corrupted, truncated
    or hand-edited fails here rather than at the application boundary where
    the transaction is already open.
    """
    if not isinstance(data, dict):
        raise UnknownPatchType(
            f"a stored patch is an object, got {type(data).__name__}")
    kind = data.get("patch_type") or ""
    cls = PATCH_TYPES.get(kind)
    if cls is None:
        raise UnknownPatchType(
            f"unknown patch_type {kind!r} — this build cannot apply it, and "
            f"guessing from the keys present is exactly what the "
            f"discriminator exists to prevent")
    version = data.get("schema_version")
    if version is None or int(version) > PATCH_SCHEMA_VERSION:
        raise UnknownPatchType(
            f"patch {kind!r} has schema_version {version!r}, newer than this "
            f"build's {PATCH_SCHEMA_VERSION}")
    return cls._from_values(data)


# ── candidate space (Phases D–F feed on these) ───────────────────────────────

@dataclass(frozen=True)
class ClarificationOption:
    """One offered answer, and what it MEANS.

    `label` is for the human, `value` is what the system records. Keeping them
    separate is what allows a chip to read "Medium piece" while recording 113 g
    — measured on 2026-08-04, where only number-first labels could be priced at
    all, so every human-readable option was unusable.
    """
    label: str
    value: Any = None
    option_id: str = ""
    field_id: str = ""
    confidence: Confidence = field(default_factory=Confidence)
    #: THE AUTHORITATIVE MEANING (C10 target). Canonical producers attach the
    #: typed patch a tap applies; the measurement adapter leaves None because
    #: the legacy shapes it reads never carried one — which is exactly the gap
    #: being closed.
    patch: Optional[SemanticPatch] = None
    source: Optional[CandidateSource] = None
    #: THE ENFORCEMENT KEY FOR C10. "patch=None is allowed only for the
    #: measurement adapter" was a comment with nothing to key on — `source` is
    #: independently optional, so no predicate could tell an adapter-built
    #: option from a canonical producer that forgot its patch. Set True at the
    #: adapter's construction sites only; at Phase H the promised check becomes
    #: writable here as `patch is None and not adapter_built -> raise`.
    adapter_built: bool = False
    #: THE CANDIDATE THIS OPTION WAS RENDERED FROM. Empty on adapter-built and
    #: legacy options; set by canonical producers from commit 4 on. It is the
    #: first link of `option_id -> candidate_id -> candidate_set_id -> the
    #: exact revision shown`, without which a tap cannot be traced back to the
    #: evidence that justified offering it.
    candidate_id: str = ""
    #: The candidate set that option belongs to.
    candidate_set_id: str = ""
    #: THE TYPED CANDIDATE, in memory only. Deliberately absent from the wire
    #: form: a client receives identifiers and labels, never semantics it
    #: could reinterpret. A consumer that needs the candidate after a round
    #: trip resolves `candidate_id` against the persisted universe rather
    #: than trusting a copy that travelled.
    candidate: Optional[Any] = None

    def __post_init__(self):
        if self.source is not None:
            object.__setattr__(self, "source", CandidateSource(self.source))
        if self.patch is not None and not isinstance(self.patch, SemanticPatch):
            raise ValueError(
                "ClarificationOption.patch must be a SemanticPatch — a dict "
                "here is the unvalidated answer the patch type replaces")

    @property
    def send_value(self) -> str:
        """What a channel without a value channel (Telegram, iMessage) sends
        back. The server resolves it against the stored options."""
        return self.label if self.value is None else str(self.value)

    def to_payload(self) -> dict:
        return {"label": self.label,
                "value": self.value,
                "option_id": self.option_id,
                "field_id": self.field_id,
                "confidence": self.confidence.to_payload(),
                "patch": None if self.patch is None else self.patch.to_payload(),
                "source": None if self.source is None else self.source.value,
                "adapter_built": bool(self.adapter_built),
                "candidate_id": self.candidate_id,
                "candidate_set_id": self.candidate_set_id}

    @classmethod
    def from_payload(cls, data: dict) -> "ClarificationOption":
        raw = data.get("source")
        return cls(label=data.get("label") or "",
                   value=data.get("value"),
                   option_id=data.get("option_id") or "",
                   field_id=data.get("field_id") or "",
                   confidence=Confidence.from_payload(data.get("confidence")),
                   patch=(patch_from_payload(data["patch"])
                          if data.get("patch") else None),
                   source=None if raw is None else CandidateSource(raw),
                   adapter_built=bool(data.get("adapter_built", False)),
                   candidate_id=data.get("candidate_id") or "",
                   candidate_set_id=data.get("candidate_set_id") or "")


@dataclass(frozen=True)
class UncertaintyEvidence:
    """WHY a field is unresolved, carried as data so the ambiguity engine and
    the selector reason from the same facts: the value range the uncertainty
    spans, and the consequence of guessing wrong in the domain's materiality
    currency.

    `impact_spread` is a `CanonicalQuantity`, not a bare calorie number. Food
    supplies `Dimension.ENERGY`; a 60-100 kg squat's consequence is training
    load, and naming the shared field `calorie_spread` would have forced
    workouts either to leave it None forever — scoring every workout field as
    zero-consequence in a shared stakes ranking — or to put kilograms in a
    field named calories, the silent unit lie `CanonicalQuantity`'s trench-coat
    check exists to reject.
    """
    low: Optional[Decimal] = None
    high: Optional[Decimal] = None
    unit_id: str = ""
    impact_spread: Optional[CanonicalQuantity] = None
    basis: str = ""

    def to_payload(self) -> dict:
        return {"low": _dec_out(self.low), "high": _dec_out(self.high),
                "unit_id": self.unit_id, "basis": self.basis,
                "impact_spread": (None if self.impact_spread is None
                                  else self.impact_spread.to_payload())}

    @classmethod
    def from_payload(cls, data: Optional[dict]) -> "UncertaintyEvidence":
        if not data:
            return cls()
        return cls(low=_dec_in(data.get("low")), high=_dec_in(data.get("high")),
                   unit_id=data.get("unit_id") or "",
                   basis=data.get("basis") or "",
                   impact_spread=CanonicalQuantity.from_payload(
                       data.get("impact_spread")))


@dataclass(frozen=True)
class UnresolvedField:
    """One unresolved semantic field, identified by SEMANTICS — operation,
    event, attribute, revision — never by list position or display text.
    (The adapter's position+text ids are measurement-only and die with it.)

    THE FIELD OWNS ITS OPTIONS. Deriving one from the other is the defect this
    whole migration removes: the server generated prose and re-parsed it for
    chips, then the client did it again. A selectable field with no options is
    refused here rather than shipped as a blank row a client "fixes" — C15.
    """
    operation_id: str
    revision: int
    event_id: str
    attribute: ClarificationAttribute
    allowed_dimensions: tuple = ()
    allowed_units: tuple = ()
    materiality: Optional[float] = None
    uncertainty: UncertaintyEvidence = field(default_factory=UncertaintyEvidence)
    response_type: ResponseType = ResponseType.FREE_TEXT
    options: tuple = ()

    def __post_init__(self):
        if not self.operation_id or not self.event_id:
            raise ValueError("field identity is operation/event/attribute/"
                             "revision — all of them")
        object.__setattr__(self, "attribute",
                           ClarificationAttribute(self.attribute))
        object.__setattr__(self, "response_type",
                           ResponseType(self.response_type))
        object.__setattr__(self, "options", tuple(self.options or ()))
        selectable = self.response_type in (ResponseType.SINGLE_SELECT,
                                            ResponseType.MULTI_SELECT)
        if selectable and not self.options:
            raise ValueError(
                f"{self.field_id} is a {self.response_type.value} with no "
                f"options — a select that cannot be selected from must say so "
                f"as FREE_TEXT_FALLBACK, not ship blank (C15)")
        if self.options and not selectable:
            raise ValueError(
                f"{self.field_id} is {self.response_type.value} but carries "
                f"options — a field with options IS a select")
        seen = set()
        for o in self.options:
            if not o.option_id:
                raise ValueError(
                    f"an option on {self.field_id} has no option_id — the "
                    f"wire submits ids, so an unidentified option is "
                    f"unanswerable except by its label (C11)")
            if o.option_id in seen:
                raise ValueError(f"duplicate option_id {o.option_id!r} on "
                                 f"{self.field_id}")
            seen.add(o.option_id)
            if o.field_id != self.field_id:
                raise ValueError(
                    f"option {o.option_id!r} answers {o.field_id!r} but sits "
                    f"on {self.field_id!r} — an option that patches another "
                    f"field is the mixed chip row, one level down")

    @property
    def field_id(self) -> str:
        """Derived, stable, and content-addressed — reordering a list or
        rewording a question cannot change it."""
        return (f"{self.operation_id}:{self.event_id}:"
                f"{self.attribute.value}:{self.revision}")

    def option(self, option_id: str) -> ClarificationOption:
        """Resolve a submitted option id against the STORED options, or fail.

        This is the server side of the wire contract: a tap sends ids, and the
        meaning comes from here — never from the label that came back.
        """
        for o in self.options:
            if o.option_id == option_id:
                return o
        raise KeyError(
            f"{option_id!r} is not an option on {self.field_id} — a tap whose "
            f"option cannot be found is refused, not re-interpreted")

    def to_payload(self) -> dict:
        return {"operation_id": self.operation_id, "revision": self.revision,
                "event_id": self.event_id, "attribute": self.attribute.value,
                "allowed_dimensions": [str(d) for d in self.allowed_dimensions],
                "allowed_units": [str(u) for u in self.allowed_units],
                "materiality": (None if self.materiality is None
                                else float(self.materiality)),
                "uncertainty": self.uncertainty.to_payload(),
                "response_type": self.response_type.value,
                "options": [o.to_payload() for o in self.options]}

    @classmethod
    def from_payload(cls, data: dict) -> "UnresolvedField":
        return cls(
            operation_id=data.get("operation_id") or "",
            revision=int(data.get("revision") or 0),
            event_id=data.get("event_id") or "",
            attribute=ClarificationAttribute(data.get("attribute")),
            allowed_dimensions=tuple(data.get("allowed_dimensions") or ()),
            allowed_units=tuple(data.get("allowed_units") or ()),
            materiality=(None if data.get("materiality") is None
                         else float(data["materiality"])),
            uncertainty=UncertaintyEvidence.from_payload(
                data.get("uncertainty")),
            response_type=ResponseType(data.get("response_type")
                                       or ResponseType.FREE_TEXT),
            options=tuple(ClarificationOption.from_payload(o)
                          for o in (data.get("options") or ())))


@dataclass(frozen=True)
class CandidateValue:
    """One possible answer, with its evidence. Candidates are SEMANTIC — the
    selector picks among them and only then are labels rendered."""
    candidate_id: str
    semantic_value: Any
    source: CandidateSource
    probability: float = 0.0
    confidence: float = 0.0
    evidence_ids: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "source", CandidateSource(self.source))
        if not self.candidate_id:
            raise ValueError("a candidate needs an id")
        for name in ("probability", "confidence"):
            v = getattr(self, name)
            if not 0.0 <= float(v) <= 1.0:
                raise ValueError(f"{name} out of range: {v}")


@dataclass(frozen=True)
class ClarificationGroup:
    """One event's fields, grouped — the structure that makes a mixed chip row
    (Elite / Core Power / Whole thing / About half) unconstructable.

    THE DOCSTRING USED TO BE THE WHOLE ENFORCEMENT. Without these checks a
    group could hold another event's field, so the canonical defect was
    representable one level down and a tap would patch an event the group's
    label never named.
    """
    event_id: str
    label: str = ""
    fields: tuple = ()

    def __post_init__(self):
        if not self.event_id:
            raise ValueError("a group is addressed by its event")
        object.__setattr__(self, "fields", tuple(self.fields or ()))
        if not self.fields:
            raise ValueError(f"group {self.event_id!r} has no fields — an "
                             f"empty group renders a label with nothing to "
                             f"answer")
        seen = set()
        for f in self.fields:
            if f.event_id != self.event_id:
                raise ValueError(
                    f"group {self.event_id!r} cannot hold a field of "
                    f"{f.event_id!r} — the mixed chip row stays "
                    f"unconstructable")
            # field_id is operation:event:attribute:revision, so this is also
            # the "no duplicate attribute for the same event/revision" check.
            if f.field_id in seen:
                raise ValueError(
                    f"duplicate field {f.field_id!r} in group "
                    f"{self.event_id!r} — two answers would race for one slot")
            seen.add(f.field_id)

    def to_payload(self) -> dict:
        return {"event_id": self.event_id, "label": self.label,
                "fields": [f.to_payload() for f in self.fields]}

    @classmethod
    def from_payload(cls, data: dict) -> "ClarificationGroup":
        return cls(event_id=data.get("event_id") or "",
                   label=data.get("label") or "",
                   fields=tuple(UnresolvedField.from_payload(f)
                                for f in (data.get("fields") or ())))


@dataclass(frozen=True)
class ClarificationInteraction:
    """One clarification exchange: a voice introduction plus grouped fields.

    Replaces question-as-container (C8's producers): the sentence stops being
    the vessel of semantics and becomes presentation over typed fields.

    ONE OPERATION, ONE REVISION, THROUGHOUT. Every field it carries must name
    the same pair, because a field's identity embeds them: an interaction
    holding an `op_2` field would render a chip whose tap patches a different
    operation than the one being answered.
    """
    interaction_id: str
    operation_id: str
    revision: int
    introduction: str = ""
    groups: tuple = ()

    #: Bumped when the stored interaction's shape changes.
    SCHEMA_VERSION: ClassVar[int] = 1

    def __post_init__(self):
        if not self.interaction_id or not self.operation_id:
            raise ValueError("an interaction is addressed by operation and id")
        object.__setattr__(self, "groups", tuple(self.groups or ()))
        events, fields = set(), set()
        for g in self.groups:
            if g.event_id in events:
                raise ValueError(
                    f"interaction {self.interaction_id} has two groups for "
                    f"{g.event_id!r} — one event, one group, or the same food "
                    f"is asked about twice in one turn")
            events.add(g.event_id)
            for f in g.fields:
                if (f.operation_id, f.revision) != (self.operation_id,
                                                    self.revision):
                    raise ValueError(
                        f"interaction {self.operation_id}:{self.revision} "
                        f"cannot carry field {f.field_id} — mixed operation "
                        f"ownership means a tap patches the wrong operation")
                if f.field_id in fields:
                    raise ValueError(
                        f"duplicate field {f.field_id!r} across groups")
                fields.add(f.field_id)

    def field(self, field_id: str) -> UnresolvedField:
        for g in self.groups:
            for f in g.fields:
                if f.field_id == field_id:
                    return f
        raise KeyError(
            f"{field_id!r} is not a field of interaction "
            f"{self.interaction_id} — an answer to an unknown field is "
            f"refused, not re-interpreted")

    def patch_for(self, field_id: str, option_id: str) -> SemanticPatch:
        """THE WIRE CONTRACT, server side. A tap submits
        (operation, revision, field, option) and the meaning is loaded from
        here — the label never travels back as semantics (C11).
        """
        option = self.field(field_id).option(option_id)
        if option.patch is None:
            raise ValueError(
                f"option {option_id!r} on {field_id} carries no patch — a "
                f"canonical option's meaning is its patch, and re-deriving it "
                f"from {option.label!r} is the defect being removed")
        return option.patch

    def to_payload(self) -> dict:
        return {"schema_version": self.SCHEMA_VERSION,
                "interaction_id": self.interaction_id,
                "operation_id": self.operation_id, "revision": self.revision,
                "introduction": self.introduction,
                "groups": [g.to_payload() for g in self.groups]}

    @classmethod
    def from_payload(cls, data: dict) -> "ClarificationInteraction":
        """Fails closed on a version this build cannot read — an interaction
        loaded as an empty one looks like "nothing was pending", which is how
        a held meal disappears."""
        if not isinstance(data, dict):
            raise ValueError("a stored interaction is an object, got "
                             f"{type(data).__name__}")
        version = data.get("schema_version")
        if version is None or int(version) > cls.SCHEMA_VERSION:
            raise ValueError(
                f"interaction schema_version {version!r} is newer than this "
                f"build's {cls.SCHEMA_VERSION}")
        return cls(interaction_id=data.get("interaction_id") or "",
                   operation_id=data.get("operation_id") or "",
                   revision=int(data.get("revision") or 0),
                   introduction=data.get("introduction") or "",
                   groups=tuple(ClarificationGroup.from_payload(g)
                                for g in (data.get("groups") or ())))


@dataclass(frozen=True)
class ClarificationField:
    """One unresolved thing, with the question AND its options.

    They live on one object because deriving one from the other is the defect:
    food generated prose and then re-parsed it to recover chips, on the server
    and again on the client. A question whose options are not attached is a
    question every client has to guess at.
    """
    id: str
    event_id: str
    attribute: str
    question: str
    options: tuple = ()
    response_type: str = "single_select"
    required_by_modes: frozenset = frozenset()
    materiality: Optional[float] = None
    status: str = "unresolved"
    helper_text: str = ""

    def required_for(self, mode: str) -> bool:
        return mode in self.required_by_modes


# ── pending lifecycle ────────────────────────────────────────────────────────

class PendingStatus(str, Enum):
    """The OPERATION lifecycle, cross-domain.

    ⚠ A SECOND `PendingStatus` EXISTS, and this one nearly became the mistake
    the module's own docstring forbids. `skills/nutrition/pending_store.py`
    defines ACTIVE / CONSUMED / CANCELLED / EXPIRED — the STORAGE lifecycle of
    one row. They are not competing definitions of one idea; they are two
    scopes, and `_STORAGE_STATUS` below maps between them so the relationship
    is code rather than folklore.

    That module is 355 lines, fully tested, and has ZERO production importers —
    measured 2026-08-04. It also contains `claim()`: a real DB-level atomic
    guard (`UPDATE ... WHERE answered_at IS NULL`, exactly one caller sees
    rowcount 1), which is precisely the idempotency the acceptance gate is
    failing for. It is prior art to ADOPT, not to duplicate, and step 4 is
    therefore an adoption rather than a build.
    """
    RESOLVING = "resolving"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    READY_TO_COMMIT = "ready_to_commit"
    COMMITTING = "committing"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    #: TWO FAILURE STATES, because one was a contradiction. `FAILED` was
    #: terminal AND mapped to a claimable row, which says the operation is over
    #: and may continue. A failed operation would have been reloaded as open on
    #: the next turn and processed again with no explicit retry transition.
    #:
    #: Split rather than picked, because both models are real: a transient
    #: write error should be retried, and a rejected commit should not be.
    RETRYABLE_FAILURE = "retryable_failure"   # transient; the row stays open
    FAILED = "failed"                         # terminal; needs a new operation

    @property
    def is_terminal(self) -> bool:
        return self in (PendingStatus.COMMITTED, PendingStatus.CANCELLED,
                        PendingStatus.EXPIRED, PendingStatus.FAILED)


#: A LOSSY, ONE-WAY PROJECTION onto the row lifecycle. Not the persisted
#: operation state, and the distinction is load-bearing.
#:
#: Five operation states project onto "active". A restart reading only the row
#: therefore learns that something is open and CANNOT learn whether it was
#: waiting on the user, ready to commit, already committing, or a failure worth
#: retrying. Those need different next actions, so the operation status must be
#: persisted alongside the row rather than reconstructed from it.
#:
#: `FAILED` projects to "cancelled" because the storage lifecycle has no failed
#: state at all — a real gap, recorded here rather than smoothed over, and one
#: the adoption has to close.
_STORAGE_PROJECTION = {
    PendingStatus.RESOLVING: "active",
    PendingStatus.AWAITING_CLARIFICATION: "active",
    PendingStatus.READY_TO_COMMIT: "active",
    PendingStatus.COMMITTING: "active",
    PendingStatus.RETRYABLE_FAILURE: "active",
    PendingStatus.COMMITTED: "consumed",
    PendingStatus.CANCELLED: "cancelled",
    PendingStatus.EXPIRED: "expired",
    PendingStatus.FAILED: "cancelled",
}


def storage_projection(status: "PendingStatus") -> str:
    """The row status this operation state projects onto.

    ONE-WAY. There is no inverse and there must not be one: five states share
    "active", so reconstructing an operation status from a row status is
    guessing. Persist both.
    """
    return _STORAGE_PROJECTION.get(status, "active")


class InvalidPendingTransition(ValueError):
    """A lifecycle change the model does not permit."""

    def __init__(self, current, target, why: str = ""):
        msg = f"{current.value} -> {target.value} is not allowed"
        super().__init__(f"{msg}: {why}" if why else msg)
        self.current, self.target, self.why = current, target, why


class TransitionCause(str, Enum):
    """WHY a failure state is being entered, supplied by the method that owns
    the accounting for it.

    A raw caller has none, which is the point: the primitive refuses a failure
    target without a cause, so "record_failure is the only way in" stops being
    a convention and becomes a check. It was a convention, and it was false for
    FAILED — `_transition_unchecked(FAILED, terminal_reason="x")` reached a
    terminal failure with attempt_count=0 and no error.
    """
    FAILURE_RECORDED = "failure_recorded"       # an attempt failed
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"   # the last attempt failed
    PERMANENT_FAILURE = "permanent_failure"     # will not be retried


#: FAILURE IS ENTERED BY RECORDING ONE, never by asking for the state. The
#: bound on retries lives in `record_failure`, so a caller reaching
#: `transition_to(RETRYABLE_FAILURE)` directly entered a failure state with no
#: attempt counted and no error — and could then self-transition forever,
#: because `max_attempts` was never consulted. "Bounded by max_attempts" was
#: not true of the public door.
_FAILURE_TARGETS = frozenset({PendingStatus.RETRYABLE_FAILURE,
                              PendingStatus.FAILED})

#: WHAT A TRANSITION MAY CHANGE. `**changes` reached `replace()` unfiltered, so
#: a lifecycle move could rewrite `user_id` and `domain` — verified, not
#: hypothesised. A transition changes lifecycle state; semantic payload belongs
#: to methods that revise the operation.
_LIFECYCLE_FIELDS = frozenset({
    "attempt_count", "last_error", "terminal_reason", "commit_key",
    "answer_claim_key", "version", "expires_at",
})

#: THE ONLY LEGAL MOVES. Preventing invalid state SHAPES is not the same as
#: preventing invalid TRANSITIONS, and the model did the first while permitting
#: `committed.record_failure()`, `failed.cancel()` and
#: `cancelled.record_failure()` — a committed meal could be reopened.
#:
#: The terminal states have EMPTY sets, which is the property that matters: a
#: meal that committed is done, and nothing may move it.
_ALLOWED_TRANSITIONS = {
    PendingStatus.RESOLVING: {
        PendingStatus.AWAITING_CLARIFICATION, PendingStatus.READY_TO_COMMIT,
        PendingStatus.CANCELLED, PendingStatus.RETRYABLE_FAILURE,
        PendingStatus.FAILED, PendingStatus.EXPIRED},
    PendingStatus.AWAITING_CLARIFICATION: {
        PendingStatus.READY_TO_COMMIT, PendingStatus.CANCELLED,
        PendingStatus.EXPIRED, PendingStatus.RETRYABLE_FAILURE,
        PendingStatus.FAILED},
    PendingStatus.READY_TO_COMMIT: {
        PendingStatus.COMMITTING, PendingStatus.CANCELLED,
        PendingStatus.RETRYABLE_FAILURE, PendingStatus.FAILED},
    PendingStatus.COMMITTING: {
        PendingStatus.COMMITTED, PendingStatus.RETRYABLE_FAILURE,
        PendingStatus.FAILED},
    PendingStatus.RETRYABLE_FAILURE: {
        # SELF-TRANSITION IS REQUIRED, and was missing. A second failed attempt
        # is retryable -> retryable, and forbidding it made `record_failure`
        # raise on the second call — the table was stricter than the lifecycle
        # it describes. Bounded by `max_attempts`, which the construction
        # invariant enforces, so it cannot loop.
        PendingStatus.RETRYABLE_FAILURE,
        PendingStatus.RESOLVING, PendingStatus.COMMITTING,
        PendingStatus.FAILED, PendingStatus.CANCELLED},
    PendingStatus.COMMITTED: set(),
    PendingStatus.CANCELLED: set(),
    PendingStatus.EXPIRED: set(),
    PendingStatus.FAILED: set(),
}


@dataclass(frozen=True)
class PendingOperation:
    """One in-flight, multi-turn operation, in any domain.

    ONE OWNER. Food has THREE live — `conversation.payload_json` (20 refs),
    `deferred_calls` (18) and `staged_items` (14) — which is why a held food
    could commit with no card and a clarification answer could fall to legacy
    while its state stayed behind.

    A FOURTH IS BUILT AND UNUSED. `skills/nutrition/pending_store.py` has zero
    production importers and no table of its own, yet implements the lifecycle
    with versioning, expiry and an atomic claim. Counting it as a competing
    owner overstates the problem; ignoring it wastes the answer. It is listed
    separately for that reason, and step 4 adopts it rather than adding a
    fifth.

    `idempotency_key` is derived from the operation and its resolved payload,
    NOT from the message: food's existing key is
    `turn_idempotency_key(user_id, message, tool_calls)` over an in-process
    dict, which dedupes a repeated message rather than a repeated commit and
    survives neither a restart nor a second worker.
    """
    id: str
    user_id: str
    domain: str
    status: PendingStatus = PendingStatus.RESOLVING
    events: tuple = ()
    unresolved_fields: tuple = ()
    resolved_fields: dict = field(default_factory=dict)
    assumptions: tuple = ()
    mode: str = ""
    source_turn_id: str = ""
    #: TWO GUARANTEES, NOT ONE, and conflating them is how a meal commits
    #: twice. `pending_store.claim()` proves exactly one caller CONSUMED the
    #: answer; it says nothing about the ledger write that follows. A worker
    #: can claim, commit food, crash before marking the operation consumed, and
    #: a retry can commit again.
    #:
    #: `answer_claim_key`  — one consumer of the clarification answer
    #: `commit_key`        — one ledger mutation, enforced by a UNIQUE
    #:                       constraint on (operation, revision)
    answer_claim_key: str = ""
    commit_key: str = ""
    attempt_count: int = 0
    max_attempts: int = 3
    last_error: str = ""
    #: WHY a terminal operation ended. The storage lifecycle cannot tell a user
    #: cancellation from a permanent validation failure from exhausted retries
    #: — all three project onto "cancelled" — so support and recovery tooling
    #: would read an infrastructure failure as somebody changing their mind.
    #: Persisted with the operation, never inferred from the row.
    terminal_reason: str = ""
    version: int = 0
    expires_at: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return not self.status.is_terminal

    def __post_init__(self):
        # THE STATE THAT MUST NOT EXIST. An exhausted RETRYABLE_FAILURE is open,
        # stored active, and forbidden to retry — the same "over and yet
        # continuing" ambiguity that `FAILED` had, one level down. Rejected at
        # construction so no code path can produce it, rather than described in
        # a comment and left reachable.
        if (self.status is PendingStatus.RETRYABLE_FAILURE
                and self.attempt_count >= self.max_attempts):
            raise ValueError(
                f"retryable failure with {self.attempt_count}/"
                f"{self.max_attempts} attempts used is not retryable — "
                "record_failure() transitions it to FAILED")
        # A TERMINAL OPERATION MUST SAY WHY IT ENDED, however it was built. The
        # property held only for callers using `cancel()`/`record_failure()`,
        # so direct construction could still produce a terminal row with no
        # reason — and recovery tooling reads that as a user cancellation.
        if self.status in (PendingStatus.FAILED, PendingStatus.CANCELLED,
                           PendingStatus.EXPIRED) and not self.terminal_reason:
            raise ValueError(
                f"{self.status.value} requires a terminal_reason")
        # COMMITTED needs a RESULT REFERENCE, not a failure reason: "it ended"
        # is not the interesting fact about a commit, "which write" is.
        if self.status is PendingStatus.COMMITTED and not self.commit_key:
            raise ValueError("a committed operation requires a commit_key")

    @property
    def may_retry(self) -> bool:
        """A retryable failure with attempts left. Terminal failure never
        retries — that is the whole reason the two states are separate."""
        return (self.status is PendingStatus.RETRYABLE_FAILURE
                and self.attempt_count < self.max_attempts)

    def transition_to(self, target: "PendingStatus",
                      **changes) -> "PendingOperation":
        """THE SINGLE LIFECYCLE AUTHORITY. Every status change goes through it.

        `record_failure` and `cancel` used to replace the status independently,
        which is why a committed operation could be failed and a cancelled one
        retried. One boundary means one place to be right, and one place to add
        the next rule.
        """
        if target in _FAILURE_TARGETS:
            raise InvalidPendingTransition(
                self.status, target,
                "failure states are entered by record_failure(), which counts "
                "the attempt and records the error")
        return self._transition_unchecked(target, **changes)

    def _transition_unchecked(self, target: "PendingStatus",
                              _cause: "TransitionCause" = None,
                              **changes) -> "PendingOperation":
        """The primitive. Enforces the table, the field allowlist, AND the
        failure-accounting invariants.

        "Unchecked" names one thing only: it does not refuse failure TARGETS,
        because it is how `record_failure` reaches them. It is otherwise the
        strictest path in the model, and deliberately so — a private door that
        is safe only when called correctly is the same bypass one underscore
        further in, and this one had it: `_transition_unchecked(
        RETRYABLE_FAILURE)` produced attempts=0 and retried forever.
        """
        if target not in _ALLOWED_TRANSITIONS.get(self.status, set()):
            raise InvalidPendingTransition(self.status, target)
        forbidden = set(changes) - _LIFECYCLE_FIELDS
        if forbidden:
            raise InvalidPendingTransition(
                self.status, target,
                f"a transition may not change {sorted(forbidden)} — "
                "lifecycle moves do not rewrite semantic payload")
        # ENTERING A FAILURE MEANS RECORDING ONE, and the cause says which
        # method is doing it. Three shapes are valid and nothing else is.
        if target in _FAILURE_TARGETS:
            if _cause is None:
                raise InvalidPendingTransition(
                    self.status, target,
                    "use record_failure() or fail_permanently() — a failure "
                    "state may not be entered without one")
            if not changes.get("last_error"):
                raise InvalidPendingTransition(
                    self.status, target, "a failure must carry its error")

        if target is PendingStatus.RETRYABLE_FAILURE:
            if _cause is not TransitionCause.FAILURE_RECORDED:
                raise InvalidPendingTransition(
                    self.status, target,
                    f"{_cause.value} does not produce a retryable failure")
            if changes.get("attempt_count") != self.attempt_count + 1:
                raise InvalidPendingTransition(
                    self.status, target,
                    "entering a retryable failure must increment "
                    f"attempt_count to {self.attempt_count + 1}")

        if target is PendingStatus.FAILED:
            if not (changes.get("terminal_reason") or self.terminal_reason):
                raise InvalidPendingTransition(
                    self.status, target, "a terminal failure must say why")
            if _cause is TransitionCause.ATTEMPTS_EXHAUSTED and \
                    changes.get("attempt_count") != self.attempt_count + 1:
                raise InvalidPendingTransition(
                    self.status, target,
                    "exhaustion is reached by recording the final attempt")
            if _cause is TransitionCause.FAILURE_RECORDED:
                raise InvalidPendingTransition(
                    self.status, target,
                    "a recorded failure is retryable until attempts run out")
        return replace(self, status=target, **changes)

    def record_failure(self, error: str) -> "PendingOperation":
        """Count an attempt and land in the RIGHT state, in one step.

        The transition to FAILED happens HERE, when the attempt is recorded,
        not in a later cleanup pass. A sweeper would leave a window in which
        the operation is open, stored active, and unable to retry — which is
        the ambiguity being removed, reintroduced as a race.
        """
        attempts = self.attempt_count + 1
        exhausted = attempts >= self.max_attempts
        return self._transition_unchecked(
            PendingStatus.FAILED if exhausted
            else PendingStatus.RETRYABLE_FAILURE,
            _cause=(TransitionCause.ATTEMPTS_EXHAUSTED if exhausted
                    else TransitionCause.FAILURE_RECORDED),
            attempt_count=attempts,
            last_error=error,
            terminal_reason=("attempts_exhausted" if exhausted
                             else self.terminal_reason))

    def fail_permanently(self, reason: str, error: str) -> "PendingOperation":
        """Terminal without retrying — a rejection, not an outage.

        Separate from `record_failure` because the two are different events. A
        validation rejection is not worth three attempts, and burning the retry
        budget on it would delay the terminal state without changing it.
        """
        if not reason or not error:
            raise ValueError("a permanent failure needs a reason and an error")
        return self._transition_unchecked(
            PendingStatus.FAILED,
            _cause=TransitionCause.PERMANENT_FAILURE,
            last_error=error, terminal_reason=reason)

    def cancel(self, reason: str = "user_cancelled") -> "PendingOperation":
        """Terminal by the USER's decision, and distinguishable from failure."""
        return self.transition_to(PendingStatus.CANCELLED,
                                  terminal_reason=reason)

    def required_unresolved(self, mode: str) -> tuple:
        return tuple(f for f in self.unresolved_fields
                     if f.status == "unresolved" and f.required_for(mode))

    def may_commit(self, mode: str) -> bool:
        """Strict cannot commit past a required unresolved field. This is the
        gate `undercount=True` never had — it was passive telemetry that
        coexisted with a commit."""
        return not self.required_unresolved(mode)


# ── the turn envelope ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CanonicalIntent:
    """What the turn is DOING.

    An open value rather than a closed Enum, deliberately. The taxonomy is
    still being learned from production, and freezing it early is precisely how
    `reason=question` became a routing decision: one coarse label, applied to
    a food report, a plan, a challenge and a genuine question alike, that sent
    all four to the legacy path. An unknown intent should be recordable as
    unknown, not forced into the nearest member.
    """
    name: str = "unknown"
    confidence: Confidence = field(default_factory=Confidence)


@dataclass(frozen=True)
class SemanticTurn:
    """One user message, interpreted once.

    The envelope every domain shares, carrying the things that were previously
    re-derived per domain and per channel: language, locale, the raw text, and
    the events the message reports.

    `language` and `locale` are here because they were nowhere: the food gate's
    shape rules are ASCII, and 98 of 301 real food logs it turned away were
    rejected for their alphabet rather than their content.
    """
    turn_id: str
    user_id: str
    raw_text: str
    channel: str = ""
    language: str = ""
    locale: str = ""
    intent: Optional[CanonicalIntent] = None
    events: tuple = ()
    references: tuple = ()
    interpretation_version: str = ""

    @property
    def is_multilingual_blindspot(self) -> bool:
        """A message whose script the ASCII shape rules cannot read. Not a
        decline — a statement that the rules do not apply."""
        return bool(self.raw_text) and not any(
            c.isascii() and c.isalpha() for c in self.raw_text)


# ── what the adoption must enforce, as checkable requirements ────────────────
#
# `answer_claim_key` and `commit_key` are FIELDS. Fields are not guarantees,
# and the gap between them is where a meal commits twice. These constants
# record what the adoption has to build so the requirement is importable and
# testable rather than sitting in a commit message.

#: The claim already exists, unwired: `pending_store.claim()` is a conditional
#: UPDATE where exactly one caller sees rowcount 1.
ANSWER_CLAIM_ENFORCEMENT = "pending_store.claim(): UPDATE ... WHERE answered_at IS NULL"

#: The commit boundary does NOT exist. An application-level
#: `if not already_committed(key)` is insufficient under concurrent workers:
#: both read "not committed", both write. Only the database can arbitrate.
COMMIT_KEY_ENFORCEMENT = "UNIQUE (pending_operation_id, revision)"

#: And a duplicate must RETURN THE FIRST RESULT, not skip silently. A caller
#: that gets nothing back cannot tell "already done" from "nothing happened",
#: and will either re-report or report a commit that did not occur on this
#: turn — which is the phantom-log failure in a new costume.
COMMIT_DUPLICATE_BEHAVIOUR = "return the original MealCommitResult"


def adoption_requirements() -> dict:
    """What is enforced today versus what the adoption must add.

    `enforced` is measured, not asserted: the claim is enforced because a
    conditional UPDATE exists; the commit is not, because no constraint does.
    """
    return {
        "answer_consumption": {
            "mechanism": ANSWER_CLAIM_ENFORCEMENT,
            "enforced": True,
            "note": "built in pending_store, currently unwired",
        },
        "ledger_mutation": {
            "mechanism": COMMIT_KEY_ENFORCEMENT,
            "enforced": False,
            "note": "no constraint exists; a worker can claim, commit, crash "
                    "before marking consumed, and a retry commits again",
        },
        "duplicate_commit": {
            "mechanism": COMMIT_DUPLICATE_BEHAVIOUR,
            "enforced": False,
            "note": "skipping silently is indistinguishable from doing nothing",
        },
    }

# ── B-1.9 commit 2: typed quantity-candidate evidence ────────────────────────
#
# WHY THESE EXIST. A candidate carried a `CandidateSource` and nothing else, so
# "may this evidence authorise an assumption?" was answered by matching source
# NAMES against a frozenset — `{"user_history", "catalog"}`. That worked only
# because those sources happen to be entity-specific today, and it drifts the
# moment one is added whose name says nothing about what its evidence is ABOUT.
#
# The question was never "what is this source called". It is "what is this
# evidence about, and can it speak for THIS person eating THIS thing". So the
# contract states that, and every consumer reads it instead of inferring.

EVIDENCE_SCHEMA_VERSION = 1


class ServingBasis(str, Enum):
    """The unit a portion is NATURALLY expressed in for this evidence.

    Measured 2026-08-06: a honey question offered `30g / 80g / 200g` to a user
    who logs tablespoons, and they typed "1 tbsp" — below the lowest option.
    The candidates were not wrong about the food; they were expressed in a
    basis the person does not think in. Basis is therefore a property of the
    evidence, carried to the point of rendering, never re-derived from a label.
    """
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"
    PIECE = "piece"
    PACKAGE = "package"
    FRACTION_OF_PACKAGE = "fraction_of_package"
    FRACTION_OF_ENTITY = "fraction_of_entity"
    STANDARD_SERVING = "standard_serving"


class EvidenceScope(str, Enum):
    """WHO OR WHAT the evidence is about. The load-bearing field.

    An ontology distribution is a true statement about people in general and a
    false basis for asserting what one person ate. That distinction is the
    whole of the estimate-sufficiency rule, and it is a property of the
    evidence rather than of the name of the lane that produced it.
    """
    #: This user's own record. `subject_user_id` REQUIRED.
    THIS_USER = "this_user"
    #: A QUANTITY-BEARING record for a specific variant — a package size, a
    #: declared serving. `product_variant_id` REQUIRED, and the basis must
    #: actually denote an amount.
    #:
    #: NAMED FOR THE QUANTITY, NOT THE PRODUCT. `THIS_PRODUCT` was too broad:
    #: knowing a jar is Brand X honey does not establish that three
    #: tablespoons were eaten. Identity is not consumption, and a scope that
    #: conflates them would let future product metadata authorise a default
    #: merely by recognising the item.
    THIS_PRODUCT_QUANTITY = "this_product_quantity"
    #: People in general. Legitimate for OFFERING choices; never sufficient to
    #: assert a portion on someone's behalf.
    POPULATION = "population"


class ExclusionReason(str, Enum):
    """WHY a generated candidate did not become an option.

    Typed, and deliberately one member per place the selector actually drops
    something — not a free string. A reason field that accepts prose becomes a
    second vocabulary nobody maintains: the same cause arrives spelled four
    ways and the population cannot be counted. Adding a drop site to the
    selector must mean adding a member here, which is the point.

    THERE IS NO GENERIC MEMBER. "Not selected" restates the fact already
    recorded by appearing in this list and answers nothing; every exclusion
    names the policy branch that produced it, because the question analysis
    has to answer is why the user's expected candidate disappeared.

    NONE OF THESE MEAN THE USER REJECTED THE CANDIDATE. Rejection is an event
    on the answer turn, recorded against an option that WAS shown. Keeping the
    two vocabularies apart is what lets "we never offered it" be separated
    from "we offered it and they typed something else".

    Inputs that could not form a candidate at all are NOT here — those are
    generation failures, not selection decisions. See
    `GenerationRejectionReason`.
    """
    #: Quantity-equivalent to an already-accepted candidate, independently of
    #: how either would be worded. The selector's accept rule is information
    #: gain, and this one added none.
    SEMANTIC_DUPLICATE = "semantic_duplicate"
    #: DISTINCT IN MEANING, COLLIDING IN WORDS. Its rendered label read back
    #: to the same mass as a neighbour's — `5 oz` and `6 oz` are two chips and
    #: one choice.
    #:
    #: NAMED AS A RENDERING OUTCOME, NOT A SEMANTIC ONE, because that is what
    #: it is: a judgement about wording, under one renderer, in one locale.
    #: Calling it a duplicate would assert the candidates meant the same
    #: thing when they demonstrably did not, and would hide that another
    #: locale may not collide at all. Reproducible only against the
    #: `renderer_contract_version` in the selection context, which is why that
    #: field is not optional.
    RENDER_COLLISION = "render_collision"
    #: Survived deduplication, but the display limit was already full when it
    #: was reached.
    SELECTION_CAP = "selection_cap"


@dataclass(frozen=True)
class EvidenceContext:
    """WHO is answering, about WHAT. The other half of applicability.

    Evidence naming *a* user is not evidence about *this* user, and the two
    were indistinguishable while authorisation read only the scope. The stored
    subject ids existed and were never compared to anything.
    """
    user_id: Optional[int]
    canonical_entity_id: str
    product_variant_id: Optional[str] = None


#: Bases that actually denote an amount of a product. A record scoped
#: THIS_PRODUCT_QUANTITY must speak in one of these, or it identifies the
#: product without saying how much of it.
_QUANTITY_BEARING_BASES = frozenset({
    "package", "standard_serving", "fraction_of_package",
})

#: WHICH FIELD OF A CANONICAL QUANTITY CARRIES THE AMOUNT, per basis.
#:
#: Without this every comparison silently defaulted to `.grams`, so two volume
#: quantities compared `None == None` and agreed. A 240 ml observation
#: "supported" a 500 ml candidate because neither carried a mass. The same
#: hole existed for count, piece, package and fraction.
_BASIS_MEASURE = {
    ServingBasis.MASS: "grams",
    ServingBasis.VOLUME: "milliliters",
    ServingBasis.COUNT: "count",
    ServingBasis.PIECE: "count",
    ServingBasis.PACKAGE: "amount",
    ServingBasis.FRACTION_OF_PACKAGE: "amount",
    ServingBasis.FRACTION_OF_ENTITY: "amount",
    ServingBasis.STANDARD_SERVING: "amount",
}


class RoundingMode(str, Enum):
    """HOW A DECLARED ROUNDING ROUNDS, persisted with the record that does it.

    `Decimal.quantize()` reads the ambient decimal context when no mode is
    given, so a stored conversion could produce 182 in one process and 181 in
    another after any library anywhere called `getcontext().rounding = ...`.
    A persisted conversion whose result depends on process-wide state is not
    reproducible, which is the whole point of persisting it.

    Passed explicitly at every call site. Never defaulted to the context.
    """
    HALF_UP = "half_up"
    HALF_EVEN = "half_even"
    DOWN = "down"
    UP = "up"

    @property
    def decimal_mode(self) -> str:
        from decimal import (ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP,
                             ROUND_UP)
        return {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN,
                "down": ROUND_DOWN, "up": ROUND_UP}[self.value]


def measure_on(quantity, basis: "ServingBasis") -> Optional[Decimal]:
    """The number this quantity states ON THIS BASIS, or None.

    Basis-aware by construction: asking a volume for its mass returns None
    rather than a coincidence, and a caller that needs the mass must convert
    through evidence that licenses it.
    """
    field_name = _BASIS_MEASURE[ServingBasis(basis)]
    raw = getattr(quantity, field_name, None)
    return None if raw is None else Decimal(str(raw))


@dataclass(frozen=True, kw_only=True)
class ConversionEvidence:
    """How a quantity crossed bases, on whose authority, AND WITH WHAT RESULT.

    UNSUPPORTED CONVERSIONS CANNOT BE CONSTRUCTED. "1 cup of chicken is 140 g"
    is a real claim requiring a real source; inventing a density to make a
    number comparable is how a portion the user never gave becomes a portion
    they are told they ate.

    EXECUTABLE, NOT DECORATIVE. The earlier version checked that a factor
    existed, was positive, and joined the expected bases — and never applied
    it. `240 ml x 0.758 g/ml -> 435 g` passed every check while being false by
    a factor of 2.4. A conversion now carries its input and its output, and
    the arithmetic must hold: a record that does not produce its own stated
    result is not evidence of anything.

    ROUNDING IS DECLARED, NEVER TOLERATED. There is no epsilon here. A
    producer that must round says so with `quantize_exponent` under a named
    `policy_version`, which makes the rounding a versioned decision that can
    be audited and changed — rather than a tolerance that quietly absorbs
    real errors alongside representation noise.
    """
    from_basis: ServingBasis
    to_basis: ServingBasis
    #: What licensed it — a USDA density row, a package panel, a piece weight.
    #: Required whenever the basis actually changes. VERSIONED: a density
    #: record can be corrected while keeping its key, and a conversion citing
    #: only the key would present two different factors as one authority.
    source: Optional["SourceReference"] = None
    factor: Optional[Decimal] = None
    input_quantity: Optional["CanonicalQuantity"] = None
    output_quantity: Optional["CanonicalQuantity"] = None
    #: Which conversion policy performed this. Required to declare rounding.
    policy_version: str = ""
    #: An explicit Decimal exponent, e.g. "0.01". Empty means exact.
    quantize_exponent: str = ""
    #: HOW that exponent rounds. Persisted, and passed to every quantize()
    #: call, so the stored result cannot change because some other library
    #: mutated the process-wide decimal context.
    rounding_mode: RoundingMode = RoundingMode.HALF_UP

    def __post_init__(self):
        object.__setattr__(self, "from_basis", ServingBasis(self.from_basis))
        object.__setattr__(self, "to_basis", ServingBasis(self.to_basis))
        object.__setattr__(self, "factor", _dec_in(self.factor))
        object.__setattr__(self, "rounding_mode",
                           RoundingMode(self.rounding_mode))
        if self.from_basis is not self.to_basis:
            if self.source is None:
                raise ValueError(
                    f"a conversion from {self.from_basis.value} to "
                    f"{self.to_basis.value} needs a source that licenses it — "
                    f"an unsourced factor is an invented density, and the "
                    f"portion it produces is one the user never gave")
            # AN AUTHORITY WITHOUT A VALUE IS NOT EXECUTABLE EVIDENCE. Citing
            # a density row and carrying no number cannot convert anything;
            # whatever performed the conversion did so on its own authority.
            if self.factor is None or self.factor <= 0:
                raise ValueError(
                    f"a conversion from {self.from_basis.value} to "
                    f"{self.to_basis.value} cites "
                    f"{getattr(self.source, 'record_key', None)!r} but "
                    f"carries factor={self.factor!r} — an authority with no "
                    f"positive value converts nothing")
        elif self.factor is not None and self.factor != 1:
            raise ValueError(
                f"a same-basis conversion carries factor={self.factor} — "
                f"nothing changed, so any factor but 1 is a silent rescale")
        if self.quantize_exponent and not str(self.policy_version or "").strip():
            raise ValueError(
                "rounding must be attributable: quantize_exponent without a "
                "policy_version is an undeclared adjustment")
        self._check_arithmetic()

    def _check_arithmetic(self):
        """THE STEP THAT WAS MISSING. Apply the factor; demand the result."""
        if self.input_quantity is None or self.output_quantity is None:
            return
        seen = measure_on(self.input_quantity, self.from_basis)
        got = measure_on(self.output_quantity, self.to_basis)
        if seen is None or got is None:
            raise ValueError(
                f"a conversion from {self.from_basis.value} to "
                f"{self.to_basis.value} must state both amounts on their own "
                f"bases; got input={seen!r} output={got!r}")
        expected = seen * (self.factor if self.factor is not None
                           else Decimal(1))
        if self.quantize_exponent:
            expected = expected.quantize(Decimal(self.quantize_exponent),
                                         rounding=self.rounding_mode.decimal_mode)
        if expected != got:
            raise ValueError(
                f"{seen} {self.from_basis.value} x {self.factor} yields "
                f"{expected}, but this conversion claims {got} "
                f"{self.to_basis.value} — a conversion that does not produce "
                f"its own stated result is not evidence of anything")

    def apply_to(self, amount: Decimal) -> Decimal:
        """Convert a measure on `from_basis` to one on `to_basis`."""
        out = Decimal(str(amount)) * (self.factor if self.factor is not None
                                      else Decimal(1))
        return (out.quantize(Decimal(self.quantize_exponent),
                             rounding=self.rounding_mode.decimal_mode)
                if self.quantize_exponent else out)

    def to_payload(self) -> dict:
        return {"from_basis": self.from_basis.value,
                "to_basis": self.to_basis.value,
                "source": self.source.to_payload() if self.source else None,
                "factor": _dec_out(self.factor),
                "input_quantity": (self.input_quantity.to_payload()
                                   if self.input_quantity else None),
                "output_quantity": (self.output_quantity.to_payload()
                                    if self.output_quantity else None),
                "policy_version": self.policy_version,
                "quantize_exponent": self.quantize_exponent,
                "rounding_mode": self.rounding_mode.value}

    @classmethod
    def from_payload(cls, d: dict) -> "ConversionEvidence":
        src, qin, qout = (d.get("source"), d.get("input_quantity"),
                          d.get("output_quantity"))
        return cls(from_basis=ServingBasis(d["from_basis"]),
                   to_basis=ServingBasis(d["to_basis"]),
                   source=SourceReference.from_payload(src) if src else None,
                   factor=_dec_in(d.get("factor")),
                   input_quantity=(CanonicalQuantity.from_payload(qin)
                                   if qin else None),
                   output_quantity=(CanonicalQuantity.from_payload(qout)
                                    if qout else None),
                   policy_version=d.get("policy_version", ""),
                   quantize_exponent=d.get("quantize_exponent", ""),
                   rounding_mode=RoundingMode(
                       d.get("rounding_mode", RoundingMode.HALF_UP.value)))


@dataclass(frozen=True, kw_only=True)
class SourceReference:
    """WHICH RECORD, IN WHICH VERSION OF WHICH DATASET.

    A bare key is not a durable identity when the thing it names can change.
    `portion:chicken_breast:large` can mean 174 g today and 190 g after an
    ontology refresh, and evidence citing only the key would present two
    incomparable claims as one. The same applies to a mutable row: a
    `food_entries` id points at whatever that row says NOW, which is not
    necessarily what it said when the candidate was generated.
    """
    dataset_id: str
    dataset_version: str
    record_key: str
    #: A content hash, row version, or — best — an immutable event id.
    record_version: str = ""
    #: THE ONLY WAY TO OMIT A RECORD VERSION, and it is a claim being made:
    #: this dataset never changes a record in place within a version, so the
    #: key plus the dataset version already identifies exact content. A
    #: mutable source (a `food_entries` row, which correction rewrites) may
    #: not set this, because its id points at whatever the row says now.
    immutable_within_version: bool = False

    def __post_init__(self):
        for name in ("dataset_id", "dataset_version", "record_key"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"a source reference needs its {name} — an unauditable "
                    f"justification is not one")
        if not str(self.record_version or "").strip() and not (
                self.immutable_within_version):
            raise ValueError(
                f"{self.dataset_id}:{self.record_key} carries no "
                f"record_version and does not declare itself immutable within "
                f"its dataset version — so it names a row whose value may "
                f"already have changed, and the evidence citing it cannot be "
                f"reproduced")

    def to_payload(self) -> dict:
        return {"dataset_id": self.dataset_id,
                "dataset_version": self.dataset_version,
                "record_key": self.record_key,
                "record_version": self.record_version,
                "immutable_within_version": self.immutable_within_version}

    @classmethod
    def from_payload(cls, d: dict) -> "SourceReference":
        return cls(dataset_id=d["dataset_id"],
                   dataset_version=d["dataset_version"],
                   record_key=d["record_key"],
                   record_version=d.get("record_version", ""),
                   immutable_within_version=bool(
                       d.get("immutable_within_version", False)))


@dataclass(frozen=True, kw_only=True)
class ServingExpression:
    """HOW THE OPTION IS SAID, and what licenses saying it that way.

    A basis enum alone cannot render an option. `21 g + VOLUME` does not say
    whether the chip reads `1 tbsp`, `15 ml` or `3 tsp`; `182 g + PIECE` does
    not say `1 breast` or `½ large breast`. Leaving that to the renderer is
    exactly the honey failure — options offered in `30g / 80g / 200g` to a
    user who logs tablespoons, because the basis reached rendering and the
    EXPRESSION did not.

    So the candidate owns both: what would be committed canonically, and what
    the user is actually being offered. Evidence owns what the source
    observed. Three different questions, three owners.
    """
    amount: Decimal
    unit_id: str
    basis: ServingBasis
    #: What this expression resolves to. Must be the candidate's own quantity.
    normalized: "CanonicalQuantity"
    #: Required when the expression's basis is not the basis its canonical
    #: mass is stated on — saying "1 tbsp" for something committed as 21 g is
    #: a density claim, and it needs the same authority as any other.
    conversion_evidence: Optional[ConversionEvidence] = None
    #: A declared rounding from the unit's exact value to the stated one.
    #: 1 tbsp is 14.787 ml; an expression that wants to say 15 ml declares
    #: that rounding rather than being allowed a tolerance.
    quantize_exponent: str = ""
    rounding_mode: RoundingMode = RoundingMode.HALF_UP
    policy_version: str = ""

    def __post_init__(self):
        object.__setattr__(self, "basis", ServingBasis(self.basis))
        object.__setattr__(self, "amount", _dec_in(self.amount))
        object.__setattr__(self, "rounding_mode",
                           RoundingMode(self.rounding_mode))
        if self.amount is None or self.amount <= 0:
            raise ValueError(
                f"a serving expression states an amount; got {self.amount!r}")
        if not str(self.unit_id or "").strip():
            raise ValueError(
                "a serving expression needs the unit it is said in — without "
                "one the renderer must guess, which is the defect this "
                "removes")
        if self.quantize_exponent and not str(self.policy_version or "").strip():
            raise ValueError(
                "rounding must be attributable: quantize_exponent without a "
                "policy_version is an undeclared adjustment")
        stated = measure_on(self.normalized, self.basis)
        if stated is None:
            raise ValueError(
                f"this expression is said in {self.basis.value} but its "
                f"normalized quantity states no amount on that basis, so it "
                f"cannot be rendered without inventing one")
        self._check_unit_produces(stated)
        self._check_conversion(stated)

    def _check_unit_produces(self, stated: Decimal):
        """`amount` OF `unit_id` MUST BE `stated`, via the registry.

        Without this the displayed serving and the committed quantity were
        independent fields that merely sat next to each other: `99 tbsp`
        alongside a normalized 15 ml constructed cleanly, and the user would
        read ninety-nine tablespoons and commit one. The registry decides what
        a tablespoon is — never a food name, never the renderer.
        """
        from core import unit_registry

        try:
            definition = unit_registry.resolve(self.unit_id)
        except unit_registry.UnknownUnit as exc:
            raise ValueError(str(exc)) from None
        want = {ServingBasis.MASS: unit_registry.MASS,
                ServingBasis.VOLUME: unit_registry.VOLUME}.get(
                    self.basis, unit_registry.COUNT)
        if definition.dimension != want:
            raise ValueError(
                f"{self.unit_id!r} is a {definition.dimension} unit but this "
                f"expression is said on the {self.basis.value} basis — the "
                f"chip would be read in one dimension and priced in another")
        produced = unit_registry.canonical_amount(self.amount, self.unit_id)
        if self.quantize_exponent:
            produced = produced.quantize(
                Decimal(self.quantize_exponent),
                rounding=self.rounding_mode.decimal_mode)
        if produced != stated:
            raise ValueError(
                f"{self.amount} {self.unit_id} is {produced} on the "
                f"{self.basis.value} basis, but this expression states "
                f"{stated} — the serving shown and the quantity committed "
                f"would be different amounts")

    def _check_conversion(self, stated: Decimal):
        """The conversion must be about THIS expression's own values.

        An internally valid conversion for an unrelated quantity —
        `100 ml -> 140 g` attached to a 15 ml expression — proves nothing
        about what this chip commits, while looking fully sourced.
        """
        mass = getattr(self.normalized, "grams", None)
        conv = self.conversion_evidence
        if mass is not None and self.basis is not ServingBasis.MASS:
            if conv is None:
                raise ValueError(
                    f"an expression in {self.basis.value} resolving to "
                    f"{mass} g crosses bases on nobody's authority — the "
                    f"density or piece weight that licenses it must be cited")
            if (conv.from_basis is not self.basis
                    or conv.to_basis is not ServingBasis.MASS):
                raise ValueError(
                    f"this expression is said in {self.basis.value} and "
                    f"commits mass, but its conversion runs "
                    f"{conv.from_basis.value} -> {conv.to_basis.value}")
            got_in = (measure_on(conv.input_quantity, conv.from_basis)
                      if conv.input_quantity is not None else None)
            got_out = (measure_on(conv.output_quantity, conv.to_basis)
                       if conv.output_quantity is not None else None)
            if got_in is None or got_out is None:
                raise ValueError(
                    "a conversion attached to a serving expression must state "
                    "the amounts it ran on, or it cannot be shown to be about "
                    "this serving")
            if got_in != stated or got_out != Decimal(str(mass)):
                raise ValueError(
                    f"this expression is {stated} {self.basis.value} "
                    f"committing {mass} g, but its conversion runs {got_in} "
                    f"-> {got_out} — a conversion about another quantity "
                    f"licenses nothing about this one")

    def to_payload(self) -> dict:
        return {"amount": _dec_out(self.amount), "unit_id": self.unit_id,
                "basis": self.basis.value,
                "normalized": self.normalized.to_payload(),
                "quantize_exponent": self.quantize_exponent,
                "rounding_mode": self.rounding_mode.value,
                "policy_version": self.policy_version,
                "conversion_evidence": (self.conversion_evidence.to_payload()
                                        if self.conversion_evidence else None)}

    @classmethod
    def from_payload(cls, d: dict) -> "ServingExpression":
        conv = d.get("conversion_evidence")
        return cls(amount=_dec_in(d["amount"]), unit_id=d["unit_id"],
                   basis=ServingBasis(d["basis"]),
                   normalized=CanonicalQuantity.from_payload(d["normalized"]),
                   quantize_exponent=d.get("quantize_exponent", ""),
                   rounding_mode=RoundingMode(
                       d.get("rounding_mode", RoundingMode.HALF_UP.value)),
                   policy_version=d.get("policy_version", ""),
                   conversion_evidence=(ConversionEvidence.from_payload(conv)
                                        if conv else None))


@dataclass(frozen=True, kw_only=True)
class QuantityCandidateEvidence:
    """One reason a candidate exists, AND what the source actually said.

    NOT the candidate. A statement of the form "this source, about this
    subject, observed this amount on this basis, which supports the quantity
    its candidate names". The offered amount belongs to the candidate; what
    was OBSERVED belongs here. Without that split both objects could claim a
    quantity — candidate 21 g, evidence 30 g — with no defined authority
    between them.

    It is also a SNAPSHOT. A source id alone cannot explain a candidate after
    the row behind it is corrected or deleted; the observed value is recorded
    here so the system can still say "candidate X existed because event Y
    contained 182 g at the time".

    `applies_to` asks only about the SUBJECT — whether this record is about
    the person or variant at hand. The entity match lives on the candidate,
    because that is where the entity lives.
    """
    source_type: CandidateSource
    source: SourceReference
    #: WHAT THE SOURCE SAID, as it said it. Not the offered value.
    observed_quantity: "CanonicalQuantity"
    observed_basis: ServingBasis
    subject_scope: EvidenceScope
    observed_at: Optional[Any] = None
    subject_user_id: Optional[int] = None
    product_variant_id: Optional[str] = None
    #: How `observed_basis` reached the candidate's basis. Required whenever
    #: the two differ.
    conversion_evidence: Optional[ConversionEvidence] = None
    confidence: Optional[Decimal] = None
    uncertainty_g: Optional[Decimal] = None
    #: WHICH SCHEMA READS THIS PAYLOAD. Distinct from the generator version,
    #: the selection policy version, and the version of the source data — four
    #: different questions, and collapsing them makes it impossible to say
    #: which one changed.
    evidence_version: int = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self):
        # FAIL SHUT on an unknown source, basis, scope or version. A value we
        # cannot interpret must not travel as if we could.
        object.__setattr__(self, "source_type", CandidateSource(self.source_type))
        object.__setattr__(self, "observed_basis", ServingBasis(self.observed_basis))
        object.__setattr__(self, "subject_scope", EvidenceScope(self.subject_scope))
        object.__setattr__(self, "confidence", _dec_in(self.confidence))
        object.__setattr__(self, "uncertainty_g", _dec_in(self.uncertainty_g))
        if int(self.evidence_version) != EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"evidence_version {self.evidence_version} is not "
                f"{EVIDENCE_SCHEMA_VERSION}; a record written under another "
                f"contract must be migrated, not guessed at")
        if not isinstance(self.source, SourceReference):
            raise ValueError(
                f"source must be a SourceReference, got "
                f"{type(self.source).__name__} — a bare key cannot say which "
                f"version of the record was read")
        # RANGES, NOT COMMENTS. A confidence of 7.5 and an uncertainty of -40
        # were both constructible, and both would have travelled into ranking
        # and into a disclosure sentence.
        if self.confidence is not None and not (
                Decimal(0) <= self.confidence <= Decimal(1)):
            raise ValueError(
                f"confidence={self.confidence} is outside [0,1]; a number "
                f"that is not a probability must not be ranked as one")
        if self.uncertainty_g is not None and self.uncertainty_g < 0:
            raise ValueError(
                f"uncertainty_g={self.uncertainty_g} is negative — an "
                f"uncertainty narrower than certainty is not a measurement")
        # A NAIVE TIMESTAMP IS AN AMBIGUOUS ONE. This programme has already
        # paid for a clock read in the wrong frame; observation times feed
        # recency ranking and cross-day windows.
        if self.observed_at is not None:
            if not isinstance(self.observed_at, datetime):
                raise ValueError(
                    f"observed_at must be a datetime, got "
                    f"{type(self.observed_at).__name__} — anything else "
                    f"serialises to null and the observation loses its time")
            if self.observed_at.tzinfo is None:
                raise ValueError(
                    "observed_at must be timezone-aware; a naive source time "
                    "cannot be compared across a rollover boundary")
        if self.conversion_evidence is not None and not isinstance(
                self.conversion_evidence, ConversionEvidence):
            raise ValueError("conversion_evidence must be ConversionEvidence")
        # THE SUBJECT MUST BE NAMED, not implied by the scope.
        if self.subject_scope is EvidenceScope.THIS_USER and not self.subject_user_id:
            raise ValueError(
                "THIS_USER evidence must name the user it is about — a scope "
                "without a subject is a claim without a claimant")
        if (self.subject_scope is EvidenceScope.THIS_PRODUCT_QUANTITY
                and not str(self.product_variant_id or "").strip()):
            raise ValueError(
                "THIS_PRODUCT_QUANTITY evidence must name the variant it is "
                "about")

    def applies_to(self, context: "EvidenceContext") -> bool:
        """Is this record about the SUBJECT currently being asked about?

        Subject only. The entity is checked by the candidate that owns this
        evidence, so that a candidate cannot be partly about salmon.
        """
        if self.subject_scope is EvidenceScope.THIS_USER:
            return (self.subject_user_id is not None
                    and self.subject_user_id == context.user_id)
        if self.subject_scope is EvidenceScope.THIS_PRODUCT_QUANTITY:
            return bool(self.product_variant_id
                        and self.product_variant_id == context.product_variant_id)
        return True          # population evidence applies to anyone

    def to_payload(self) -> dict:
        return {
            "evidence_version": self.evidence_version,
            "source_type": self.source_type.value,
            "source": self.source.to_payload(),
            "observed_quantity": self.observed_quantity.to_payload(),
            "observed_basis": self.observed_basis.value,
            "observed_at": (self.observed_at.isoformat()
                            if hasattr(self.observed_at, "isoformat") else None),
            "subject_scope": self.subject_scope.value,
            "subject_user_id": self.subject_user_id,
            "product_variant_id": self.product_variant_id,
            "conversion_evidence": (self.conversion_evidence.to_payload()
                                    if self.conversion_evidence else None),
            "confidence": _dec_out(self.confidence),
            "uncertainty_g": _dec_out(self.uncertainty_g),
        }

    @classmethod
    def from_payload(cls, d: dict) -> "QuantityCandidateEvidence":
        from datetime import datetime as _dt

        conv = d.get("conversion_evidence")
        seen = d.get("observed_at")
        return cls(
            source_type=CandidateSource(d["source_type"]),
            source=SourceReference.from_payload(d["source"]),
            observed_quantity=CanonicalQuantity.from_payload(
                d["observed_quantity"]),
            observed_basis=ServingBasis(d["observed_basis"]),
            observed_at=(_dt.fromisoformat(seen) if seen else None),
            subject_scope=EvidenceScope(d["subject_scope"]),
            subject_user_id=d.get("subject_user_id"),
            product_variant_id=d.get("product_variant_id"),
            conversion_evidence=(ConversionEvidence.from_payload(conv)
                                 if conv else None),
            confidence=_dec_in(d.get("confidence")),
            uncertainty_g=_dec_in(d.get("uncertainty_g")),
            evidence_version=int(d.get("evidence_version",
                                       EVIDENCE_SCHEMA_VERSION)))


@dataclass(frozen=True, kw_only=True)
class QuantityCandidate:
    """ONE POSSIBLE ANSWER, above the one or more records that support it.

    The candidate owns the identity and the claim: this much of this entity,
    normalized, expressed on this basis. Its evidence says why, and what each
    source observed. Two sources that agree on an amount merge into one
    candidate holding two evidence records, and no provenance is lost.

    `candidate_id` IS OPAQUE. It is not built from the user, the food name,
    the label, the confidence or the evidence ordering — an id that encodes
    those leaks them wherever it travels and changes meaning when they do.
    `semantic_hash` carries the deduplication identity instead, separately,
    where it can be compared without being an address.
    """
    candidate_id: str
    canonical_entity_id: str
    #: THE NORMALIZED AMOUNT BEING OFFERED. The single authority on what this
    #: candidate means; evidence carries what was observed.
    quantity: "CanonicalQuantity"
    serving_basis: ServingBasis
    #: WHAT THE USER IS ACTUALLY OFFERED. Required, because a basis enum plus
    #: a mass cannot be rendered without the renderer reinventing the serving
    #: — which is the honey defect. A candidate that cannot be said is a
    #: candidate that must not be constructed.
    offered: "ServingExpression"
    evidence: tuple = ()
    #: Content identity for merge/integrity checks. Never an address.
    semantic_hash: str = ""
    #: THE GENERATOR'S PRIOR — how likely this candidate is, before any
    #: selection rule runs. A RANKING FEATURE, persisted with the candidate
    #: because "every inclusion and exclusion explainable from persisted
    #: features" is not true if the features themselves are recomputed. The
    #: selector reads it; the generator owns it.
    prior: Optional[Decimal] = None

    def __post_init__(self):
        object.__setattr__(self, "serving_basis", ServingBasis(self.serving_basis))
        object.__setattr__(self, "evidence", tuple(self.evidence or ()))
        bad = [type(e).__name__ for e in self.evidence
               if not isinstance(e, QuantityCandidateEvidence)]
        if bad:
            raise ValueError(
                f"candidate {self.candidate_id!r} carries {bad} in its "
                f"evidence — an untyped element passes every check by having "
                f"no fields to check")
        object.__setattr__(self, "prior", _dec_in(self.prior))
        if self.prior is not None and not (
                Decimal(0) <= self.prior <= Decimal(1)):
            raise ValueError(
                f"prior={self.prior} is outside [0,1]; a number that is not a "
                f"probability must not be ranked as one")
        if not isinstance(self.offered, ServingExpression):
            raise ValueError(
                f"offered must be a ServingExpression, got "
                f"{type(self.offered).__name__}")
        if self.offered.basis is not ServingBasis(self.serving_basis):
            raise ValueError(
                f"candidate {self.candidate_id!r} is expressed in "
                f"{ServingBasis(self.serving_basis).value} but offered as "
                f"{self.offered.basis.value} — the option shown would mean "
                f"something the candidate does not")
        if self.offered.normalized != self.quantity:
            raise ValueError(
                f"candidate {self.candidate_id!r} would commit "
                f"{self.quantity} and offer {self.offered.normalized} — two "
                f"values for one fact, and the user is shown the one that is "
                f"not written")
        if not str(self.candidate_id or "").strip():
            raise ValueError(
                "a candidate needs an id — an unnamed candidate cannot be "
                "referenced by the option it becomes, so the option's "
                "justification could never be looked up")
        if not str(self.canonical_entity_id or "").strip():
            raise ValueError("a candidate with no canonical entity cannot be "
                             "matched to anything")
        if not self.evidence:
            raise ValueError(
                f"candidate {self.candidate_id!r} has no evidence — a "
                f"quantity offered for no recorded reason is the thing this "
                f"whole record exists to make impossible")
        for ev in self.evidence:
            # THE BASIS MUST BEAR A QUANTITY when a record claims to be about
            # this specific product's amount. Identity is not consumption:
            # knowing a jar is Brand X honey does not establish that three
            # tablespoons were eaten.
            if (ev.subject_scope is EvidenceScope.THIS_PRODUCT_QUANTITY
                    and self.serving_basis.value not in _QUANTITY_BEARING_BASES):
                raise ValueError(
                    f"candidate {self.candidate_id!r} carries "
                    f"THIS_PRODUCT_QUANTITY evidence but is expressed in "
                    f"{self.serving_basis.value}, which identifies the product "
                    f"without stating an amount of it")
            conv = ev.conversion_evidence
            # A CONVERSION MUST LAND ON THIS CANDIDATE'S OWN BASIS. Otherwise
            # a volume candidate could carry an unrelated piece-to-mass row and
            # pass construction while proving nothing about itself.
            if conv is not None and conv.to_basis is not self.serving_basis:
                raise ValueError(
                    f"conversion ends in {conv.to_basis.value} but candidate "
                    f"{self.candidate_id!r} is expressed in "
                    f"{self.serving_basis.value}; a conversion that does not "
                    f"land on this candidate's basis licenses nothing about it")
            if ev.observed_basis is not self.serving_basis:
                # CROSSING BASES REQUIRES AUTHORITY. Evidence observed in
                # millilitres cannot support a mass candidate on its own; a
                # sourced conversion is exactly what makes it able to.
                if conv is None:
                    raise ValueError(
                        f"evidence observed in {ev.observed_basis.value} "
                        f"supports candidate {self.candidate_id!r} expressed "
                        f"in {self.serving_basis.value} with no conversion — "
                        f"the basis changed on nobody's authority")
                if conv.from_basis is not ev.observed_basis:
                    raise ValueError(
                        f"the conversion starts from {conv.from_basis.value} "
                        f"but the evidence observed "
                        f"{ev.observed_basis.value}; it converts something "
                        f"this record did not see")
            self._check_support(ev)

    def _check_support(self, ev):
        """THE EVIDENCE MUST ARRIVE AT THIS CANDIDATE'S OWN NUMBER.

        Every prior check was structural — a source exists, a factor is
        positive, the bases join up. None of them applied the factor, so

            240 ml x 0.758 g/ml -> 435 g

        satisfied all of them while being false by a factor of 2.4. And the
        same-basis check read `.grams` only, so two volume quantities compared
        `None == None` and a 240 ml observation "supported" a 500 ml
        candidate. Count, piece, package and fraction had the identical hole.

        Basis-aware, and exact. No tolerance: a producer that must round
        declares it on the conversion, under a policy version.
        """
        seen = measure_on(ev.observed_quantity, ev.observed_basis)
        offered = measure_on(self.quantity, self.serving_basis)
        if seen is None or offered is None:
            # Nothing to compare is not the same as agreeing. A candidate that
            # states no amount on its own basis cannot be shown to be right.
            raise ValueError(
                f"candidate {self.candidate_id!r} states "
                f"{offered!r} on {self.serving_basis.value} and its evidence "
                f"states {seen!r} on {ev.observed_basis.value} — an amount "
                f"missing on its own basis cannot be supported by anything")
        supported = (ev.conversion_evidence.apply_to(seen)
                     if ev.conversion_evidence is not None else seen)
        if supported != offered:
            raise ValueError(
                f"candidate {self.candidate_id!r} offers {offered} "
                f"{self.serving_basis.value} but its evidence supports "
                f"{supported} — evidence that does not produce the quantity "
                f"being offered proves only that some record was consulted")

    def applies_to(self, context: "EvidenceContext") -> bool:
        """Is this candidate about the thing currently being asked about?

        The entity must match in every case — a candidate about rice says
        nothing about salmon however well-sourced it is — and at least one of
        its evidence records must be about this subject.
        """
        if self.canonical_entity_id != (context.canonical_entity_id or ""):
            return False
        return any(ev.applies_to(context) for ev in self.evidence)

    def authorizes_assumption(self, context: "EvidenceContext") -> bool:
        """May we assert this portion on someone's behalf when they say "not
        sure"?

        CONTEXTUAL, and that was the hole. Scope alone proves the evidence
        names *a* user or *a* product; it does not prove it describes THIS
        user eating THIS entity. The subject ids were stored and never
        compared, so evidence about user 123 would have authorised an
        assumption for user 456 — structurally valid and semantically wrong,
        which is the precise thing CF-1 exists to prevent.

        ONE SUFFICIENT RECORD IS ENOUGH, and it must be sufficient alone: a
        population record beside a matching user record does not weaken it,
        and two population records do not add up to one. Population evidence
        can never authorise, at any confidence, however it is named.
        """
        if self.canonical_entity_id != (context.canonical_entity_id or ""):
            return False
        return any(ev.applies_to(context)
                   and ev.subject_scope in (EvidenceScope.THIS_USER,
                                            EvidenceScope.THIS_PRODUCT_QUANTITY)
                   for ev in self.evidence)

    def to_payload(self) -> dict:
        return {"candidate_id": self.candidate_id,
                "canonical_entity_id": self.canonical_entity_id,
                "quantity": self.quantity.to_payload(),
                "serving_basis": self.serving_basis.value,
                "offered": self.offered.to_payload(),
                "semantic_hash": self.semantic_hash,
                "prior": _dec_out(self.prior),
                "evidence": [e.to_payload() for e in self.evidence]}

    @classmethod
    def from_payload(cls, d: dict) -> "QuantityCandidate":
        return cls(candidate_id=d["candidate_id"],
                   canonical_entity_id=d["canonical_entity_id"],
                   quantity=CanonicalQuantity.from_payload(d["quantity"]),
                   serving_basis=ServingBasis(d["serving_basis"]),
                   offered=ServingExpression.from_payload(d["offered"]),
                   semantic_hash=d.get("semantic_hash", ""),
                   prior=_dec_in(d.get("prior")),
                   evidence=tuple(QuantityCandidateEvidence.from_payload(e)
                                  for e in d.get("evidence", ())))


class GenerationRejectionReason(str, Enum):
    """WHY A PRODUCER'S RAW MATERIAL NEVER BECAME A CANDIDATE.

    Kept apart from `ExclusionReason` on purpose. An exclusion is a decision
    about a VALID candidate; these are inputs that could not form one. Forcing
    them into the universe would mean constructing invalid candidates just to
    mark them excluded — which defeats the construction-time gates and
    corrupts the denominator of every selection metric.
    """
    #: The source carried no mass, so no candidate could express it.
    NO_QUANTITY = "no_quantity"
    #: A basis the contract does not know. Fails shut rather than travelling.
    UNKNOWN_BASIS = "unknown_basis"
    #: The bases differ and nothing licenses crossing them.
    UNSUPPORTED_CONVERSION = "unsupported_conversion"
    #: Scope claimed a subject the record did not name.
    MISSING_SUBJECT = "missing_subject"
    #: The quantity itself would not construct.
    MALFORMED_QUANTITY = "malformed_quantity"


@dataclass(frozen=True, kw_only=True)
class CandidateGenerationRejection:
    """A producer's input that could not become a candidate, and why.

    Diagnostics, not universe membership. This is what makes "the matcher
    found a history row and it was unusable" distinguishable from "the matcher
    found nothing" — both of which otherwise present as an absent candidate.
    """
    producer: CandidateSource
    #: VERSIONED, like any other source citation. "History row 9 was
    #: unusable" is only reproducible if we can say which version of row 9.
    source: SourceReference
    reason: GenerationRejectionReason
    generator_version: str
    detail: str = ""

    def __post_init__(self):
        object.__setattr__(self, "producer", CandidateSource(self.producer))
        object.__setattr__(self, "reason",
                           GenerationRejectionReason(self.reason))
        if not isinstance(self.source, SourceReference):
            raise ValueError(
                f"a rejection cites a SourceReference, got "
                f"{type(self.source).__name__}")
        if not str(self.generator_version or "").strip():
            raise ValueError("a rejection must name the generator version")

    def to_payload(self) -> dict:
        return {"producer": self.producer.value,
                "source": self.source.to_payload(),
                "reason": self.reason.value,
                "generator_version": self.generator_version,
                "detail": self.detail}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateGenerationRejection":
        return cls(producer=CandidateSource(d["producer"]),
                   source=SourceReference.from_payload(d["source"]),
                   reason=GenerationRejectionReason(d["reason"]),
                   generator_version=d["generator_version"],
                   detail=d.get("detail", ""))


@dataclass(frozen=True, kw_only=True)
class EstimateEvidence:
    """What licensed assuming a portion, when one was assumed.

    Separate from the candidate because the QUESTION is different: a candidate
    justifies being OFFERED, and this justifies being CHOSEN on the user's
    behalf. Committing the second while only holding the first is how "not
    sure" logged 435 g of chicken breast.
    """
    chosen: QuantityCandidate
    policy_version: str
    context: Optional[EvidenceContext] = None
    considered: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "considered", tuple(self.considered or ()))
        if not str(self.policy_version or "").strip():
            raise ValueError(
                "an assumption must name the policy that made it, or the rate "
                "it produces cannot be attributed to a rule")
        if self.context is None:
            raise ValueError(
                "an assumption must record WHO it was made for and about "
                "WHAT — without that it cannot be shown to have been about "
                "the person it was applied to")
        if not self.chosen.authorizes_assumption(self.context):
            raise ValueError(
                f"candidate {self.chosen.candidate_id!r} holds no evidence "
                f"that authorises an assumption for "
                f"user={self.context.user_id} "
                f"entity={self.context.canonical_entity_id!r} — nothing it "
                f"carries is about this person consuming this thing, and "
                f"asserting from it manufactures certainty")

    def to_payload(self) -> dict:
        return {"chosen": self.chosen.to_payload(),
                "policy_version": self.policy_version,
                "context": {"user_id": self.context.user_id,
                            "canonical_entity_id": self.context.canonical_entity_id,
                            "product_variant_id": self.context.product_variant_id},
                "considered": [c.to_payload() for c in self.considered]}

    @classmethod
    def from_payload(cls, d: dict) -> "EstimateEvidence":
        c = d.get("context") or {}
        return cls(chosen=QuantityCandidate.from_payload(d["chosen"]),
                   policy_version=d["policy_version"],
                   context=EvidenceContext(
                       user_id=c.get("user_id"),
                       canonical_entity_id=c.get("canonical_entity_id", ""),
                       product_variant_id=c.get("product_variant_id")),
                   considered=tuple(QuantityCandidate.from_payload(x)
                                    for x in d.get("considered", ())))


@dataclass(frozen=True, kw_only=True)
class CandidateSet:
    """EVERY candidate generated, not the handful that survived.

    Persisting only the shown options makes retrieval failure and selection
    failure indistinguishable — "history never appeared" reads the same
    whether the matcher found nothing or the selector dropped it. They are
    different engineering problems and the data must separate them.

    `user_id` IS PART OF THE RECORD, not merely of the operation it belongs
    to. Evidence here can quote one person's logging history, so the set must
    be bound to its owner at the durable boundary — a candidate set must never
    become retrievable just because someone supplied its id.
    """
    candidate_set_id: str
    operation_id: str
    user_id: int
    #: THE SUBJECT THIS WHOLE SET IS ABOUT. Every candidate and every scoped
    #: evidence record inside is checked against it at construction.
    #:
    #: `user_id` alone was not ownership. A set for user 26 could hold a
    #: salmon candidate on a chicken field, carrying THIS_USER evidence about
    #: user 99 — and because applicability is an `any()` over evidence, one
    #: population record beside the foreign one made the candidate look
    #: applicable while the foreign record was still persisted and still
    #: readable. Foreign evidence is now REFUSED, not out-voted.
    context: "EvidenceContext"
    interaction_revision: int
    field_id: str
    generator_version: str
    #: A DIGEST OF THE SEMANTIC INPUTS THIS SET WAS BUILT FROM. Its job is to
    #: expose nondeterminism: regenerating the same revision from different
    #: inputs must fail loudly rather than silently returning the old
    #: universe. Covers meaning, never incidental object representation.
    generation_input_fingerprint: str
    candidates: tuple = ()
    #: Inputs that could not form a candidate. Diagnostics, NOT universe
    #: members — see `CandidateGenerationRejection`.
    rejections: tuple = ()

    def __post_init__(self):
        # TUPLES, copied. A caller keeping the list it passed in could
        # otherwise mutate what we recorded after the fact.
        object.__setattr__(self, "candidates", tuple(self.candidates or ()))
        object.__setattr__(self, "rejections", tuple(self.rejections or ()))
        object.__setattr__(self, "interaction_revision",
                           int(self.interaction_revision))
        for name, want in (("candidates", QuantityCandidate),
                           ("rejections", CandidateGenerationRejection)):
            bad = [type(x).__name__ for x in getattr(self, name)
                   if not isinstance(x, want)]
            if bad:
                raise ValueError(
                    f"{name} must contain {want.__name__}; got {bad} — an "
                    f"untyped element passes every check by having no fields "
                    f"to check")
        for name in ("candidate_set_id", "operation_id", "field_id",
                     "generation_input_fingerprint"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"a candidate set needs its {name}")
        if self.interaction_revision < 0:
            raise ValueError(
                f"revision {self.interaction_revision} is not a revision")
        if not self.user_id:
            raise ValueError(
                "a candidate set must name the user it was generated for")
        self._check_ownership()
        if not str(self.generator_version or "").strip():
            # WHICH GENERATOR PRODUCED THIS UNIVERSE. Without it, sets built
            # under different rules are pooled and the difference between them
            # is read as a change in users.
            raise ValueError(
                "a candidate set must name the generator that produced it")
        ids = [c.candidate_id for c in self.candidates]
        if len(set(ids)) != len(ids):
            # TWO CANDIDATES SHARING AN ID IS AN UNRESOLVABLE REFERENCE. The
            # option would point at both, and every later question about it
            # ("what was this chip's evidence?") has two answers.
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(
                f"candidate ids must be unique within a set; repeated: "
                f"{dupes}")

    def _check_ownership(self):
        """EVERY CANDIDATE, AND EVERY SCOPED RECORD, IS ABOUT THIS SUBJECT.

        Checked here rather than left to `applies_to`, because that method
        answers "may this be used?" over the whole candidate and returns True
        as soon as ONE record matches. It cannot prevent a foreign record from
        being written down beside a matching one — and a persisted claim about
        another user is a durable disclosure regardless of whether a selector
        happened to read it.
        """
        if not isinstance(self.context, EvidenceContext):
            raise ValueError(
                f"a candidate set is bound to an EvidenceContext, got "
                f"{type(self.context).__name__}")
        if self.context.user_id != self.user_id:
            raise ValueError(
                f"the set is filed for user {self.user_id} but its context is "
                f"about user {self.context.user_id}")
        entity = self.context.canonical_entity_id or ""
        for c in self.candidates:
            if c.canonical_entity_id != entity:
                raise ValueError(
                    f"candidate {c.candidate_id!r} is about "
                    f"{c.canonical_entity_id!r} in a set about {entity!r} — a "
                    f"chip for another food would be offered as an answer to "
                    f"this one")
            for ev in c.evidence:
                if (ev.subject_scope is EvidenceScope.THIS_USER
                        and ev.subject_user_id != self.user_id):
                    raise ValueError(
                        f"candidate {c.candidate_id!r} carries THIS_USER "
                        f"evidence about user {ev.subject_user_id} in a set "
                        f"for user {self.user_id} — another person's logging "
                        f"history must not be persisted here at all")
                if (ev.subject_scope is EvidenceScope.THIS_PRODUCT_QUANTITY
                        and ev.product_variant_id != (
                            self.context.product_variant_id or "")):
                    raise ValueError(
                        f"candidate {c.candidate_id!r} carries evidence about "
                        f"variant {ev.product_variant_id!r} in a set about "
                        f"{self.context.product_variant_id!r}")

    @property
    def candidate_ids(self) -> frozenset:
        return frozenset(c.candidate_id for c in self.candidates)

    def candidate(self, candidate_id: str):
        for c in self.candidates:
            if c.candidate_id == candidate_id:
                return c
        return None

    def to_payload(self) -> dict:
        return {"candidate_set_id": self.candidate_set_id,
                "operation_id": self.operation_id,
                "user_id": self.user_id,
                "context": {
                    "user_id": self.context.user_id,
                    "canonical_entity_id": self.context.canonical_entity_id,
                    "product_variant_id": self.context.product_variant_id},
                "interaction_revision": self.interaction_revision,
                "field_id": self.field_id,
                "generator_version": self.generator_version,
                "generation_input_fingerprint": self.generation_input_fingerprint,
                "candidates": [c.to_payload() for c in self.candidates],
                "rejections": [r.to_payload() for r in self.rejections]}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateSet":
        c = d.get("context") or {}
        return cls(candidate_set_id=d["candidate_set_id"],
                   operation_id=d["operation_id"],
                   user_id=int(d["user_id"]),
                   context=EvidenceContext(
                       user_id=c.get("user_id"),
                       canonical_entity_id=c.get("canonical_entity_id", ""),
                       product_variant_id=c.get("product_variant_id")),
                   interaction_revision=int(d["interaction_revision"]),
                   field_id=d["field_id"],
                   generator_version=d.get("generator_version", ""),
                   generation_input_fingerprint=d[
                       "generation_input_fingerprint"],
                   candidates=tuple(QuantityCandidate.from_payload(c)
                                    for c in d.get("candidates", ())),
                   rejections=tuple(
                       CandidateGenerationRejection.from_payload(r)
                       for r in d.get("rejections", ())))


class SelectionSurface(str, Enum):
    """WHERE the options were going. Part of what determined the decision."""
    #: The sentence is the whole interface; options are words in it.
    LABEL_TEXT = "label_text"
    #: The client renders chips and answers by id.
    ID_ADDRESSED = "id_addressed"


@dataclass(frozen=True, kw_only=True)
class CandidateSelectionContext:
    """THE OTHER HALF OF REPRODUCIBILITY.

    A policy version alone does not determine the outcome: the same universe
    under the same policy yields three text options on Telegram and five
    structured ones on iOS, and can word them differently by locale. Without
    this, two decisions that legitimately differ look like a policy that
    changed underneath us.

    The claim this makes possible is the real one:

        candidate set + policy version + selection context = same decision
    """
    surface: SelectionSurface
    locale: str
    maximum_options: int
    #: Which renderer produced the labels the collapse pass compared. Load
    #: bearing because `RENDER_COLLISION` is a judgement about wording, so it
    #: is only reproducible against the renderer that did the wording.
    renderer_contract_version: str

    def __post_init__(self):
        object.__setattr__(self, "surface", SelectionSurface(self.surface))
        object.__setattr__(self, "maximum_options", int(self.maximum_options))
        if self.maximum_options < 1:
            raise ValueError(
                f"maximum_options={self.maximum_options} could never produce "
                f"an option")
        for name in ("locale", "renderer_contract_version"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"a selection context needs its {name}")

    def to_payload(self) -> dict:
        return {"surface": self.surface.value, "locale": self.locale,
                "maximum_options": self.maximum_options,
                "renderer_contract_version": self.renderer_contract_version}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateSelectionContext":
        return cls(surface=SelectionSurface(d["surface"]),
                   locale=d["locale"],
                   maximum_options=int(d["maximum_options"]),
                   renderer_contract_version=d["renderer_contract_version"])


@dataclass(frozen=True, kw_only=True)
class CandidateExclusion:
    """One candidate that did not become an option, and the closed reason why.

    A record rather than a pair in a parallel array: the id and its reason
    cannot drift out of alignment if they are the same object.
    """
    candidate_id: str
    reason: ExclusionReason

    def __post_init__(self):
        object.__setattr__(self, "reason", ExclusionReason(self.reason))
        if not str(self.candidate_id or "").strip():
            raise ValueError("an exclusion must name the candidate excluded")

    def to_payload(self) -> dict:
        return {"candidate_id": self.candidate_id, "reason": self.reason.value}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateExclusion":
        return cls(candidate_id=d["candidate_id"],
                   reason=ExclusionReason(d["reason"]))


@dataclass(frozen=True, kw_only=True)
class CandidateSelectionDecision:
    """What was offered, what was not, and why — explainable from features.

    Holds IDS, not copies of the candidates. A decision that embedded its own
    copy could disagree with the set it claims to describe, and then two
    persisted records would each be evidence for a different history.

    `selected_candidate_ids` IS ORDERED AND THE ORDER IS DATA. It decides
    which option appears first, and therefore prominence and selection rates.
    Recovering it from database insertion order would make the analysis depend
    on how rows happened to be written.
    """
    candidate_set_id: str
    selection_policy_version: str
    context: CandidateSelectionContext
    selected_candidate_ids: tuple = ()
    exclusions: tuple = ()

    def __post_init__(self):
        object.__setattr__(
            self, "selected_candidate_ids",
            tuple(str(i) for i in (self.selected_candidate_ids or ())))
        # COERCED, SO AN UNKNOWN REASON RAISES HERE rather than persisting as
        # prose. A free-text reason becomes a second vocabulary nobody
        # maintains: the same cause arrives spelled four ways and the
        # exclusion population cannot be counted.
        object.__setattr__(self, "exclusions", tuple(
            x if isinstance(x, CandidateExclusion)
            else CandidateExclusion(candidate_id=x[0], reason=x[1])
            for x in (self.exclusions or ())))
        if not str(self.candidate_set_id or "").strip():
            raise ValueError(
                "a decision must name the candidate set it reduced")
        if not str(self.selection_policy_version or "").strip():
            raise ValueError(
                "a selection decision must name its policy version, or two "
                "decisions made under different rules become one population")
        sel = list(self.selected_candidate_ids)
        exc = [x.candidate_id for x in self.exclusions]
        if len(set(sel)) != len(sel):
            raise ValueError(f"a candidate is selected twice: {sorted(sel)}")
        if len(set(exc)) != len(exc):
            raise ValueError(f"a candidate is excluded twice: {sorted(exc)}")
        both = set(sel) & set(exc)
        if both:
            raise ValueError(
                f"selected and excluded at once: {sorted(both)} — a candidate "
                f"has exactly one terminal status, and a record claiming both "
                f"makes the funnel add up to the wrong total")
        if len(sel) > self.context.maximum_options:
            raise ValueError(
                f"{len(sel)} options selected but the context allowed "
                f"{self.context.maximum_options}")

    @property
    def excluded_candidate_ids(self) -> frozenset:
        return frozenset(x.candidate_id for x in self.exclusions)

    def to_payload(self) -> dict:
        return {"candidate_set_id": self.candidate_set_id,
                "selection_policy_version": self.selection_policy_version,
                "context": self.context.to_payload(),
                "selected_candidate_ids": list(self.selected_candidate_ids),
                "exclusions": [x.to_payload() for x in self.exclusions]}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateSelectionDecision":
        return cls(
            candidate_set_id=d["candidate_set_id"],
            selection_policy_version=d.get("selection_policy_version", ""),
            context=CandidateSelectionContext.from_payload(d["context"]),
            selected_candidate_ids=tuple(d.get("selected_candidate_ids", ())),
            exclusions=tuple(CandidateExclusion.from_payload(x)
                             for x in d.get("exclusions", ())))


@dataclass(frozen=True, kw_only=True)
class PresentedCandidateOption:
    """THE OPTION AS SHOWN, bound to the candidate it came from.

    "Candidate c2 was selected" does not prove "c2 became option `opt_2`,
    labelled `6 oz`, second in the row, in revision 0". Without that binding
    the chain from a tap back to a justification has a gap in the middle, and
    a later generator version or a legitimately new candidate set can be
    mistaken for the options the user actually saw.

    THE RENDERED LABEL IS PERSISTED, not recomputed. It is what makes
    `RENDER_COLLISION` auditable after the fact: locale and renderer version
    alone do not capture every renderer input — a user's unit preference can
    change what two candidates look like, and re-rendering later would answer
    a question about today rather than about the turn in question.
    """
    option_id: str
    candidate_id: str
    candidate_set_id: str
    interaction_revision: int
    selected_position: int
    rendered_label: str
    renderer_contract_version: str

    def __post_init__(self):
        object.__setattr__(self, "interaction_revision",
                           int(self.interaction_revision))
        object.__setattr__(self, "selected_position",
                           int(self.selected_position))
        for name in ("option_id", "candidate_id", "candidate_set_id",
                     "rendered_label", "renderer_contract_version"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"a presented option needs its {name} — without it the "
                    f"chain from a tap back to its evidence breaks")
        if self.selected_position < 0:
            raise ValueError(
                f"selected_position={self.selected_position} is not a "
                f"position")

    def to_payload(self) -> dict:
        return {"option_id": self.option_id,
                "candidate_id": self.candidate_id,
                "candidate_set_id": self.candidate_set_id,
                "interaction_revision": self.interaction_revision,
                "selected_position": self.selected_position,
                "rendered_label": self.rendered_label,
                "renderer_contract_version": self.renderer_contract_version}

    @classmethod
    def from_payload(cls, d: dict) -> "PresentedCandidateOption":
        return cls(option_id=d["option_id"], candidate_id=d["candidate_id"],
                   candidate_set_id=d["candidate_set_id"],
                   interaction_revision=int(d["interaction_revision"]),
                   selected_position=int(d["selected_position"]),
                   rendered_label=d["rendered_label"],
                   renderer_contract_version=d["renderer_contract_version"])


@dataclass(frozen=True, kw_only=True)
class CandidateDecisionRecord:
    """One clarification's complete generated set AND the decision over it.

    Two records, kept separate because they answer different questions —
    "what could we have offered?" and "what did we offer, and why not the
    rest?" — but validated together, because only together can they be
    checked. The invariant below is what makes the whole commit worth
    anything:

        selected ∪ excluded == every candidate generated
        selected ∩ excluded == ∅

    With it, three failures that look identical in production become
    distinguishable from durable records alone:

      RETRIEVAL FAILURE   the candidate is absent from the set entirely — the
                          matcher never found it, or found something it could
                          not use (see the set's `rejections`).
      SELECTION FAILURE   present in the set and in `exclusions` with a typed
                          reason — we found it and dropped it.
      USER REJECTION      present in `selected_candidate_ids`, so it WAS
                          shown, and the answer turn recorded something else.
                          Not a property of this record at all, which is
                          precisely why it must never be inferred from one.

    Without the partition the first two are the same observation, and the
    third is guesswork over displayed options.
    """
    candidate_set: CandidateSet
    decision: CandidateSelectionDecision
    #: The options as actually shown. Empty is legitimate before rendering;
    #: non-empty must agree with the decision exactly.
    presented: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "presented", tuple(self.presented or ()))
        self._check_presented()
        if self.candidate_set.candidate_set_id != self.decision.candidate_set_id:
            raise ValueError(
                f"the decision reduces set "
                f"{self.decision.candidate_set_id!r} but is filed against "
                f"{self.candidate_set.candidate_set_id!r} — a decision about "
                f"another set's candidates explains nothing about this one")
        generated = self.candidate_set.candidate_ids
        decided = (frozenset(self.decision.selected_candidate_ids)
                   | self.decision.excluded_candidate_ids)
        vanished = generated - decided
        if vanished:
            raise ValueError(
                f"generated but neither selected nor excluded: "
                f"{sorted(vanished)} — a candidate that disappears between "
                f"generation and observation is the exact blind spot this "
                f"record exists to remove")
        invented = decided - generated
        if invented:
            raise ValueError(
                f"decided but never generated: {sorted(invented)} — an option "
                f"referencing a candidate the set does not contain has no "
                f"persisted justification behind it")

    def _check_presented(self):
        """EVERY SHOWN OPTION BINDS TO ONE SELECTED CANDIDATE, in its place.

        Not "some candidate": the one it was rendered from, at the position it
        occupied, in the revision that was shown. A binding that is merely
        plausible cannot answer "what did this person tap".
        """
        if not self.presented:
            return
        bad = [type(x).__name__ for x in self.presented
               if not isinstance(x, PresentedCandidateOption)]
        if bad:
            raise ValueError(
                f"presented must contain PresentedCandidateOption; got {bad}")
        option_ids = [p.option_id for p in self.presented]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError(
                f"two shown options share an id: {sorted(option_ids)} — a tap "
                f"would resolve to both")
        positions = sorted(p.selected_position for p in self.presented)
        if positions != list(range(len(self.presented))):
            # TWO OPTIONS AT 0, OR 7 AND 12, STILL MATCHED THE SELECTED ORDER.
            # "Position" then means only "earlier than", and the exact row the
            # user saw cannot be reconstructed from it.
            raise ValueError(
                f"presented positions are {positions} — they must be exactly "
                f"0..{len(self.presented) - 1}, or a position is an ordering "
                f"hint rather than the place the option occupied")
        selected = list(self.decision.selected_candidate_ids)
        by_position = sorted(self.presented, key=lambda p: p.selected_position)
        if [p.candidate_id for p in by_position] != selected:
            raise ValueError(
                f"the options shown were "
                f"{[p.candidate_id for p in by_position]} but the decision "
                f"selected {selected} — the row the user read is not the row "
                f"the record explains")
        for p in self.presented:
            if p.candidate_set_id != self.decision.candidate_set_id:
                raise ValueError(
                    f"option {p.option_id!r} cites set "
                    f"{p.candidate_set_id!r}, not "
                    f"{self.decision.candidate_set_id!r}")
            if p.interaction_revision != self.candidate_set.interaction_revision:
                raise ValueError(
                    f"option {p.option_id!r} was shown at revision "
                    f"{p.interaction_revision} but this set is revision "
                    f"{self.candidate_set.interaction_revision}")
            if (p.renderer_contract_version
                    != self.decision.context.renderer_contract_version):
                raise ValueError(
                    f"option {p.option_id!r} was rendered by "
                    f"{p.renderer_contract_version!r} but the decision was "
                    f"made under {self.decision.context.renderer_contract_version!r}"
                    f" — a collision judged by one renderer cannot be audited "
                    f"against another")

    def option_for(self, option_id: str):
        """The candidate behind a tapped option, or None."""
        for p in self.presented:
            if p.option_id == option_id:
                return self.candidate_set.candidate(p.candidate_id)
        return None

    @property
    def operation_id(self) -> str:
        return self.candidate_set.operation_id

    @property
    def user_id(self) -> int:
        return self.candidate_set.user_id

    @property
    def revision(self) -> int:
        return self.candidate_set.interaction_revision

    @property
    def selected(self) -> tuple:
        """The candidates shown, IN THE ORDER SHOWN — objects, not ids."""
        return tuple(self.candidate_set.candidate(i)
                     for i in self.decision.selected_candidate_ids)

    def to_payload(self) -> dict:
        return {"candidate_set": self.candidate_set.to_payload(),
                "decision": self.decision.to_payload(),
                "presented": [p.to_payload() for p in self.presented]}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateDecisionRecord":
        return cls(candidate_set=CandidateSet.from_payload(d["candidate_set"]),
                   decision=CandidateSelectionDecision.from_payload(
                       d["decision"]),
                   presented=tuple(PresentedCandidateOption.from_payload(p)
                                   for p in d.get("presented", ())))
