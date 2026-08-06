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
                "adapter_built": bool(self.adapter_built)}

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
                   adapter_built=bool(data.get("adapter_built", False)))


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
    #: A specific product/variant — a label, a package. `product_variant_id`
    #: REQUIRED.
    THIS_PRODUCT = "this_product"
    #: People in general. Legitimate for OFFERING choices; never sufficient to
    #: assert a portion on someone's behalf.
    POPULATION = "population"


@dataclass(frozen=True)
class ConversionEvidence:
    """How a quantity crossed bases, and on whose authority.

    UNSUPPORTED CONVERSIONS CANNOT BE CONSTRUCTED. "1 cup of chicken is 140 g"
    is a real claim requiring a real source; inventing a density to make a
    number comparable is how a portion the user never gave becomes a portion
    they are told they ate. A conversion with no basis change is expressible
    (`from_basis == to_basis`); one with a basis change and no source is not.
    """
    from_basis: ServingBasis
    to_basis: ServingBasis
    #: What licensed it — a USDA density row, a package panel, a piece weight.
    #: Required whenever the basis actually changes.
    source_record_id: str = ""
    factor: Optional[Decimal] = None

    def __post_init__(self):
        object.__setattr__(self, "from_basis", ServingBasis(self.from_basis))
        object.__setattr__(self, "to_basis", ServingBasis(self.to_basis))
        object.__setattr__(self, "factor", _dec_in(self.factor))
        if self.from_basis is not self.to_basis and not self.source_record_id:
            raise ValueError(
                f"a conversion from {self.from_basis.value} to "
                f"{self.to_basis.value} needs a source that licenses it — an "
                f"unsourced factor is an invented density, and the portion it "
                f"produces is one the user never gave")

    def to_payload(self) -> dict:
        return {"from_basis": self.from_basis.value,
                "to_basis": self.to_basis.value,
                "source_record_id": self.source_record_id,
                "factor": _dec_out(self.factor)}

    @classmethod
    def from_payload(cls, d: dict) -> "ConversionEvidence":
        return cls(from_basis=ServingBasis(d["from_basis"]),
                   to_basis=ServingBasis(d["to_basis"]),
                   source_record_id=d.get("source_record_id", ""),
                   factor=_dec_in(d.get("factor")))


@dataclass(frozen=True)
class QuantityCandidateEvidence:
    """One quantity we could offer, and everything that justifies it.

    `authorizes_assumption` is the CF-1 replacement: derived from the declared
    scope and its required subject id, not from the source's name. A lane
    added tomorrow is judged on what it says its evidence is about.
    """
    canonical_entity_id: str
    quantity: "CanonicalQuantity"
    serving_basis: ServingBasis
    source_type: CandidateSource
    source_record_id: str
    subject_scope: EvidenceScope
    subject_user_id: Optional[int] = None
    product_variant_id: Optional[str] = None
    conversion_evidence: Optional[ConversionEvidence] = None
    confidence: Optional[Decimal] = None
    uncertainty_g: Optional[Decimal] = None
    evidence_version: int = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self):
        # FAIL SHUT on an unknown basis, source, scope or version. A value we
        # cannot interpret must not travel as if we could.
        object.__setattr__(self, "serving_basis", ServingBasis(self.serving_basis))
        object.__setattr__(self, "source_type", CandidateSource(self.source_type))
        object.__setattr__(self, "subject_scope", EvidenceScope(self.subject_scope))
        object.__setattr__(self, "confidence", _dec_in(self.confidence))
        object.__setattr__(self, "uncertainty_g", _dec_in(self.uncertainty_g))
        if int(self.evidence_version) != EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"evidence_version {self.evidence_version} is not "
                f"{EVIDENCE_SCHEMA_VERSION}; a record written under another "
                f"contract must be migrated, not guessed at")
        if not str(self.canonical_entity_id or "").strip():
            raise ValueError("evidence with no canonical entity cannot be "
                             "matched to anything")
        if not str(self.source_record_id or "").strip():
            raise ValueError(
                f"{self.source_type.value} evidence with no source record "
                f"cannot be audited, and an unauditable justification is not "
                f"one")
        # THE SUBJECT MUST BE NAMED, not implied by the scope.
        if self.subject_scope is EvidenceScope.THIS_USER and not self.subject_user_id:
            raise ValueError(
                "THIS_USER evidence must name the user it is about — a scope "
                "without a subject is a claim without a claimant")
        if (self.subject_scope is EvidenceScope.THIS_PRODUCT
                and not str(self.product_variant_id or "").strip()):
            raise ValueError(
                "THIS_PRODUCT evidence must name the variant it is about")

    @property
    def authorizes_assumption(self) -> bool:
        """May we assert this portion on the user's behalf when they say "not
        sure"?

        READ FROM THE CONTRACT, never from the source's name. This replaces
        the frozenset of source strings that shipped as a stand-in: a lane
        added tomorrow is judged on what it declares its evidence is ABOUT,
        and a population prior can never authorise an assumption no matter
        what it is called or how confident it claims to be.
        """
        return self.subject_scope in (EvidenceScope.THIS_USER,
                                      EvidenceScope.THIS_PRODUCT)

    def to_payload(self) -> dict:
        return {
            "evidence_version": self.evidence_version,
            "canonical_entity_id": self.canonical_entity_id,
            "quantity": self.quantity.to_payload(),
            "serving_basis": self.serving_basis.value,
            "source_type": self.source_type.value,
            "source_record_id": self.source_record_id,
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
        conv = d.get("conversion_evidence")
        return cls(
            canonical_entity_id=d["canonical_entity_id"],
            quantity=CanonicalQuantity.from_payload(d["quantity"]),
            serving_basis=ServingBasis(d["serving_basis"]),
            source_type=CandidateSource(d["source_type"]),
            source_record_id=d["source_record_id"],
            subject_scope=EvidenceScope(d["subject_scope"]),
            subject_user_id=d.get("subject_user_id"),
            product_variant_id=d.get("product_variant_id"),
            conversion_evidence=(ConversionEvidence.from_payload(conv)
                                 if conv else None),
            confidence=_dec_in(d.get("confidence")),
            uncertainty_g=_dec_in(d.get("uncertainty_g")),
            evidence_version=int(d.get("evidence_version",
                                       EVIDENCE_SCHEMA_VERSION)))


@dataclass(frozen=True)
class EstimateEvidence:
    """What licensed assuming a portion, when one was assumed.

    Separate from the candidate because the QUESTION is different: a candidate
    justifies being OFFERED, and this justifies being CHOSEN on the user's
    behalf. Committing the second while only holding the first is how "not
    sure" logged 435 g of chicken breast.
    """
    chosen: QuantityCandidateEvidence
    policy_version: str
    considered: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "considered", tuple(self.considered or ()))
        if not str(self.policy_version or "").strip():
            raise ValueError(
                "an assumption must name the policy that made it, or the rate "
                "it produces cannot be attributed to a rule")
        if not self.chosen.authorizes_assumption:
            raise ValueError(
                f"{self.chosen.subject_scope.value} evidence cannot authorise "
                f"an assumption — it is not about this user or this product, "
                f"and asserting from it manufactures certainty")

    def to_payload(self) -> dict:
        return {"chosen": self.chosen.to_payload(),
                "policy_version": self.policy_version,
                "considered": [c.to_payload() for c in self.considered]}

    @classmethod
    def from_payload(cls, d: dict) -> "EstimateEvidence":
        return cls(chosen=QuantityCandidateEvidence.from_payload(d["chosen"]),
                   policy_version=d["policy_version"],
                   considered=tuple(QuantityCandidateEvidence.from_payload(c)
                                    for c in d.get("considered", ())))


@dataclass(frozen=True)
class CandidateSet:
    """EVERY candidate generated, not the handful that survived.

    Persisting only the shown options makes retrieval failure and selection
    failure indistinguishable — "history never appeared" reads the same
    whether the matcher found nothing or the selector dropped it. They are
    different engineering problems and the data must separate them.
    """
    field_id: str
    candidates: tuple = ()
    generator_version: str = ""

    def __post_init__(self):
        # A TUPLE, copied. A caller keeping the list it passed in could
        # otherwise mutate what we recorded after the fact.
        object.__setattr__(self, "candidates", tuple(self.candidates or ()))

    def to_payload(self) -> dict:
        return {"field_id": self.field_id,
                "generator_version": self.generator_version,
                "candidates": [c.to_payload() for c in self.candidates]}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateSet":
        return cls(field_id=d["field_id"],
                   generator_version=d.get("generator_version", ""),
                   candidates=tuple(QuantityCandidateEvidence.from_payload(c)
                                    for c in d.get("candidates", ())))


@dataclass(frozen=True)
class CandidateSelectionDecision:
    """What was offered, what was not, and why — explainable from features.

    Exclusions are recorded WITH REASONS because "why wasn't my usual portion
    there?" is a question the option pipeline has to be able to answer about
    itself. A decision that only records its winners cannot be debugged, only
    re-run and hoped at.
    """
    field_id: str
    selected: tuple = ()
    excluded: tuple = ()          # (evidence, reason) pairs
    policy_version: str = ""

    def __post_init__(self):
        object.__setattr__(self, "selected", tuple(self.selected or ()))
        object.__setattr__(self, "excluded", tuple(
            (e, str(r)) for e, r in (self.excluded or ())))
        if not str(self.policy_version or "").strip():
            raise ValueError(
                "a selection decision must name its policy version, or two "
                "decisions made under different rules become one population")

    def to_payload(self) -> dict:
        return {"field_id": self.field_id,
                "policy_version": self.policy_version,
                "selected": [c.to_payload() for c in self.selected],
                "excluded": [{"evidence": e.to_payload(), "reason": r}
                             for e, r in self.excluded]}

    @classmethod
    def from_payload(cls, d: dict) -> "CandidateSelectionDecision":
        return cls(
            field_id=d["field_id"],
            policy_version=d.get("policy_version", ""),
            selected=tuple(QuantityCandidateEvidence.from_payload(c)
                           for c in d.get("selected", ())),
            excluded=tuple((QuantityCandidateEvidence.from_payload(x["evidence"]),
                            x["reason"]) for x in d.get("excluded", ())))
