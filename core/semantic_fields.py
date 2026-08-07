"""THE SEMANTIC EXTENSION CONTRACT — the only way a field becomes canonical.

A new food behaviour enters as a REGISTERED FIELD or it does not enter. The
question asked of "fried", "with sauce", "half the package", "skin on" and
"brand variant" is the same one every time: *what semantic field is this?* An
implementation that begins `if "fried" in food_name` has already answered it
wrong.

WHY A REGISTRY RATHER THAN A CONVENTION. B-1.5 added preparation by following
the pattern quantity set, and it worked — but "followed the pattern" is
tribal knowledge, and the migration this codebase is undoing began as four
producers that each followed the pattern of the last. A convention that is
merely documented is one careless commit from a fifth. This module is the
place where following the pattern stops being optional.

    register(FieldSpec(...))  ->  the field may be produced, presented,
                                  answered, settled and priced
    no registration           ->  none of those are reachable

WHAT A SPEC MUST DECLARE, and why each one is load-bearing:

    attribute       the typed identity. Not a string a producer invented —
                    `ClarificationAttribute` is closed, because
                    `attribute="prepration"` was once representable and
                    silently unanswerable.
    value_space     what answers exist. A closed vocabulary or a measured
                    quantity; nothing else. This is what makes "unsupported
                    semantics cannot be emitted" checkable rather than hoped
                    for.
    patch_type      the stored discriminator, which must already exist in
                    `PATCH_TYPES`. A field whose answer cannot be persisted
                    as a typed patch is a field whose answer is a guess.
    settlement      how the answer reaches the commit — and every value here
                    goes through `ResolvedFields`. There is no member for
                    "its own writer".
    pricing         whether the answer can move a number, and by what
                    MECHANISM. `IDENTITY` composes the canonical name;
                    `NONE` cannot touch nutrition at all. There is
                    deliberately no `MULTIPLIER`.
    evidence        what must be true before the field may be OFFERED.
    activation      when the field is asked. `ALWAYS_WHEN_RAISED` today;
                    B-1.6's dependency engine registers conditional ones
                    HERE rather than writing `if fried: ask_oil()`.
    presentation    caption key and order. Metadata only — a renderer may
                    read it and nothing may derive semantics from it.

THE RULE OF THREE. Two fields can share an abstraction that is secretly
bespoke: quantity and preparation both resolve to a single scalar answer, so
an interface fitting exactly those two proves very little. Genericity is not
claimed here and must not be claimed elsewhere until a third, structurally
different family passes through unchanged —
`tests/test_the_rule_of_three_fields.py` is that proof, and it fails if a new
family requires the coordinator to learn anything about it.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Callable, Optional


class ValueSpace(str, Enum):
    """WHAT ANSWERS EXIST for a field."""
    #: A closed vocabulary of typed ids — preparation, product variant.
    ENUMERATED = "enumerated"
    #: A measured amount with a unit — quantity.
    MEASURED = "measured"


class Settlement(str, Enum):
    """HOW AN ANSWER REACHES THE COMMIT.

    ONE MEMBER, ON PURPOSE. `ResolvedFields` is the settlement boundary and
    the enum exists so that adding a second way is a visible, arguable change
    to this file rather than a new function someone writes beside it. There is
    no `OWN_WRITER`, and there must never be: a field that settles its own way
    is a second mutation authority, which is the defect the whole migration is
    removing.
    """
    RESOLVED_FIELDS = "resolved_fields"


class Pricing(str, Enum):
    """WHETHER AND HOW A FIELD MAY MOVE A NUMBER."""
    #: Cannot touch nutrition. The answer is recorded and priced by nothing.
    NONE = "none"
    #: Decides the AMOUNT. Exactly one field may hold this.
    AMOUNT = "amount"
    #: Changes the canonical food IDENTITY sent to the resolver, which then
    #: prices from its own evidence.
    #:
    #: THERE IS NO `MULTIPLIER` MEMBER, and its absence is the contract. A
    #: preparation factor applied to calories is a second opinion about
    #: nutrition held by an operation with no business holding one — the
    #: defect B-1.75 deleted on the quantity side. A field that wants to move
    #: a number changes what food we are asking about; the resolver decides
    #: whether that food's numbers differ.
    IDENTITY = "identity"


class Evidence(str, Enum):
    """WHAT MUST BE TRUE BEFORE THE FIELD MAY BE OFFERED."""
    #: Options come from a fixed table. True for everyone, always available.
    ONTOLOGY = "ontology"
    #: Options are generated per user and per food from real evidence, and the
    #: field is not offered when there is none.
    GENERATED = "generated"


class Activation(str, Enum):
    """WHEN THE FIELD IS ASKED."""
    #: Asked whenever the interpreter raises it as unresolved.
    WHEN_RAISED = "when_raised"
    #: Asked only when a predicate over OTHER RESOLVED FIELDS holds. B-1.6.
    #: The predicate lives on the spec; no field may summon another field.
    CONDITIONAL = "conditional"


class ContractViolation(Exception):
    """A field that cannot be registered.

    Raised at IMPORT TIME, deliberately. A malformed field must break the
    process rather than fail on the first user who happens to trigger it.
    """


@dataclass(frozen=True)
class FieldSpec:
    attribute: Any                       # ClarificationAttribute
    value_space: ValueSpace
    patch_type: str
    pricing: Pricing
    evidence: Evidence
    settlement: Settlement = Settlement.RESOLVED_FIELDS
    activation: Activation = Activation.WHEN_RAISED
    #: For CONDITIONAL fields (B-1.6): a predicate over resolved fields.
    #: Declared here so activation is DATA. `if fried: ask_oil()` written in a
    #: producer is the thing this field exists to make unnecessary.
    active_when: Optional[Callable] = None
    #: THE CLOSED VOCABULARY, for `ENUMERATED` fields.
    vocabulary: tuple = ()
    #: WHAT THE DOMAIN CAN ACTUALLY ACT ON — supplied by whoever registers,
    #: called by core, understood by neither.
    #:
    #: This module used to import `skills.nutrition.validators._PREPARATIONS`
    #: directly: generic core reaching into a domain's PRIVATE detail, which
    #: would make every future domain either a nutrition import or an
    #: exception. Core now enforces THAT an identity-pricing field declares
    #: how its vocabulary is validated; the domain supplies WHAT that means.
    #: A workout field registering `equipment` brings its own.
    supported_vocabulary: Optional[Callable] = None
    #: Renderer metadata. READ BY PRESENTATION, NEVER BY SEMANTICS.
    caption: str = ""
    order: int = 100

    @property
    def attribute_value(self) -> str:
        return str(getattr(self.attribute, "value", self.attribute))


_REGISTRY: dict = {}


def register(spec: FieldSpec) -> FieldSpec:
    """Admit a field to the canonical vocabulary, or refuse it.

    EVERY CHECK HERE IS A DEFECT THAT ALREADY HAPPENED OR ALMOST DID.
    """
    from core.semantics import PATCH_TYPES, ClarificationAttribute

    key = spec.attribute_value
    if key in _REGISTRY:
        raise ContractViolation(
            f"{key} is already registered — two specs for one attribute is "
            f"two owners of one field, which is the shape this registry "
            f"exists to prevent")
    try:
        ClarificationAttribute(spec.attribute)
    except ValueError:
        raise ContractViolation(
            f"{key!r} is not a ClarificationAttribute. The set is closed "
            f"because `attribute='prepration'` was once representable and "
            f"silently unanswerable") from None

    if spec.patch_type not in PATCH_TYPES:
        raise ContractViolation(
            f"{key} declares patch_type {spec.patch_type!r}, which is not in "
            f"PATCH_TYPES — an answer that cannot be stored as a typed patch "
            f"is an answer recovered later by sniffing which keys are present")

    if spec.value_space is ValueSpace.ENUMERATED and not spec.vocabulary:
        raise ContractViolation(
            f"{key} is enumerated and declares no vocabulary — 'the answers "
            f"are whatever a producer emits' is not a value space")

    if spec.activation is Activation.CONDITIONAL and spec.active_when is None:
        raise ContractViolation(
            f"{key} is conditional and declares no predicate. Activation must "
            f"be DATA on the spec; a producer that decides for itself when to "
            f"ask is `if fried: ask_oil()` with extra steps")

    if spec.pricing is Pricing.IDENTITY:
        _check_the_domain_can_consume(spec)

    if spec.pricing is Pricing.AMOUNT:
        holders = [s for s in _REGISTRY.values() if s.pricing is Pricing.AMOUNT]
        if holders:
            raise ContractViolation(
                f"{key} claims AMOUNT pricing, held by "
                f"{holders[0].attribute_value} — two fields deciding the "
                f"amount is two answers to how much food there was")

    _REGISTRY[key] = spec
    return spec


def _check_the_domain_can_consume(spec: FieldSpec) -> None:
    """UNSUPPORTED SEMANTICS CANNOT BE EMITTED.

    A field that claims to price by identity must speak words its domain acts
    on. In nutrition, `validators` extracts preparation tokens from the
    requested name and each candidate's and downgrades the mismatches; a token
    outside that table changes nothing, so the question would be asked, the
    answer stored, and no number moved — a chip whose usage rate looks like
    engagement and means nothing.

    MEASURED, NOT HYPOTHETICAL: `breaded` and `plain` were proposed for B-1.5
    and are exactly this, and `baked` was worse — the validator holds `baked`
    and `roasted` as disjoint tokens, so offering "Baked" would have DOWNGRADED
    the correct candidate for a food whose reference row says roasted.

    CORE ENFORCES THAT THE CHECK EXISTS; THE DOMAIN SUPPLIES WHAT IT CHECKS.
    Importing the nutrition table here made generic infrastructure depend on
    one domain's private detail.
    """
    if spec.value_space is not ValueSpace.ENUMERATED:
        return
    if spec.supported_vocabulary is None:
        raise ContractViolation(
            f"{spec.attribute_value} prices by identity but declares no "
            f"`supported_vocabulary` — a field that can move a number must "
            f"say how its values are known to be actionable, and core cannot "
            f"know that for a domain it does not import")

    supported = set(spec.supported_vocabulary())
    unknown = [v for v in spec.vocabulary if v and v not in supported]
    if unknown:
        raise ContractViolation(
            f"{spec.attribute_value} prices by identity but {sorted(unknown)} "
            f"are not semantics its domain acts on — the field would be "
            f"asked, answered, and change nothing")


def spec_for(attribute) -> FieldSpec:
    _ensure_installed()
    key = str(getattr(attribute, "value", attribute))
    try:
        return _REGISTRY[key]
    except KeyError:
        raise ContractViolation(
            f"{key!r} is not a registered semantic field. A field cannot be "
            f"presented, answered or settled until it declares what it is — "
            f"register a FieldSpec in core.semantic_fields") from None


def is_registered(attribute) -> bool:
    _ensure_installed()
    return str(getattr(attribute, "value", attribute)) in _REGISTRY


def registered() -> dict:
    _ensure_installed()
    return dict(_REGISTRY)


def _reset_for_tests() -> None:
    """Only the rule-of-three suite uses this, to register a probe family and
    put the registry back."""
    global _installed
    _REGISTRY.clear()
    _installed = False
    _ensure_installed()


#: DOMAINS THAT REGISTER FIELDS — the composition root, and the ONLY place
#: core names a domain.
#:
#: Registration lives with the domain that owns the semantics: nutrition knows
#: what a preparation is and what its resolver can act on, and core knows
#: neither. Phase-O workouts add a line here and change nothing else.
#:
#: Imported lazily on first use rather than at module import, because these
#: modules import back into `core.semantics` for the types they register with.
_DOMAIN_REGISTRARS = ("skills.nutrition.field_registration",)

_installed = False


def _ensure_installed() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    import importlib

    # CALL A FUNCTION, do not rely on import SIDE EFFECTS. `import_module` on
    # an already-imported module is a no-op, so a registry reset would never
    # repopulate — the tests went green-to-35-red on exactly that.
    for module in _DOMAIN_REGISTRARS:
        importlib.import_module(module).register_all()
