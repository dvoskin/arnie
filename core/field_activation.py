"""B-1.6 — ACTIVATION AS A STATE TRANSITION, NOT A DEPENDENCY LOOKUP.

    previous_active  ->  patch  ->  resolved_state  ->  desired_active
                                 ->  RECONCILE

The reconciliation is the whole point, and it is why this is not simply
"evaluate the predicates and take the union". Three sets come out, and the one
that matters is the third:

    still_active     asked before, asked still
    newly_active     a dependency became true
    newly_inactive   a dependency became FALSE — and its ANSWER MUST DIE

DROPPING A FIELD FROM THE SCREEN IS NOT RETRACTING IT. If the user says "a
tablespoon of oil" and then "actually, no oil", hiding the amount chip while
`added_fat_amount=1 tbsp` stays in `answered` prices a meal with oil the user
just said was not there. That is a silent nutrition corruption, not a
presentation bug, and it is the specific failure this module exists to make
impossible: retraction removes the value from settlement AND records that it
was invalidated rather than never asked.

PURE BY CONSTRUCTION, NOT BY CONVENTION. A predicate is handed an
`ActivationState` and nothing else. It cannot reach a provider, the raw user
message, interpreter prose or the materiality pass, because none of those are
in the object it receives — `derive_unresolved` remains the one-shot
materiality question, and this is the recomputed dependency question. Two
passes, two jobs, one owner each.

ACTIVATION GENERATION IS THE OPERATION REVISION. `UnresolvedField.field_id` is
already `operation:event:attribute:revision`, so a field that closes and later
reopens at a new revision gets a NEW id, and a stale tap carrying the old one
resolves to nothing. That is what stops "yes -> 1 tbsp -> no -> yes" from
silently reviving the first tablespoon. `hold_answer` deliberately does not
move the revision — the other chips are on screen — so the rule is precise:
THE REVISION MOVES WHEN THE ACTIVE SET CHANGES, and only then.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field as _dc_field
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


class Rule:
    """A DECLARATIVE activation condition. The engine evaluates; the rule
    only describes.

    ⭐ THIS REPLACED A CALLABLE, and the reason is the whole point of the
    slice. `active_when: Callable` plus `depends_on: tuple` is a contract at
    one end and an assumption at the other — the same shape as every
    instrument in this codebase that lied by silence. A synchronous closure is
    not pure: it can capture a provider, read a module global, consult a
    cache. And a declared `depends_on` is a CLAIM about what the closure
    reads, so a predicate could say `depends_on=(present,)` while secretly
    reading another attribute, leaving the cycle check formally green and
    semantically false.

    Refusing `async def` does not fix either problem. It narrows one door in a
    room with several.

    A rule cannot lie about its dependencies because it HAS no dependencies
    beyond the attributes it names in its own structure — `attributes()` is
    derived by walking the tree, not declared beside it. And it cannot reach a
    provider because there is nowhere in `Equals`, `All` or `Not` to put one.
    Truthful by construction rather than by review.
    """
    __slots__ = ()

    def evaluate(self, state: "ActivationState") -> bool:
        raise NotImplementedError

    def attributes(self) -> frozenset:
        """Every attribute this rule reads. THE DEPENDENCY EDGES, derived."""
        raise NotImplementedError

    def describe(self) -> str:
        return type(self).__name__.lower()


@dataclass(frozen=True)
class Present(Rule):
    """The attribute has any resolved answer at all."""
    attribute: str

    def evaluate(self, state): return state.has(self.attribute)
    def attributes(self): return frozenset({_name(self.attribute)})
    def describe(self): return f"present({_name(self.attribute)})"


@dataclass(frozen=True)
class IsTrue(Rule):
    """A resolved BOOLEAN answer is true.

    Unresolved reads FALSE, deliberately — a dependent field may not open on
    the strength of a question nobody has answered. "We have not asked whether
    there was oil" is not "there was oil".
    """
    attribute: str

    def evaluate(self, state): return state.is_true(self.attribute)
    def attributes(self): return frozenset({_name(self.attribute)})
    def describe(self): return f"is_true({_name(self.attribute)})"


@dataclass(frozen=True)
class Equals(Rule):
    """A resolved answer equals a literal value."""
    attribute: str
    value: Any

    def evaluate(self, state):
        return state.has(self.attribute) and state.value(self.attribute) == self.value

    def attributes(self): return frozenset({_name(self.attribute)})
    def describe(self): return f"{_name(self.attribute)}=={self.value!r}"


@dataclass(frozen=True)
class All(Rule):
    rules: tuple = ()

    def evaluate(self, state):
        return all(r.evaluate(state) for r in self.rules)

    def attributes(self):
        return frozenset().union(*(r.attributes() for r in self.rules)) \
            if self.rules else frozenset()

    def describe(self): return "all(" + ", ".join(
        r.describe() for r in self.rules) + ")"


@dataclass(frozen=True)
class Any_(Rule):
    rules: tuple = ()

    def evaluate(self, state):
        return any(r.evaluate(state) for r in self.rules)

    def attributes(self):
        return frozenset().union(*(r.attributes() for r in self.rules)) \
            if self.rules else frozenset()

    def describe(self): return "any(" + ", ".join(
        r.describe() for r in self.rules) + ")"


@dataclass(frozen=True)
class Not(Rule):
    rule: Optional[Rule] = None

    def evaluate(self, state): return not self.rule.evaluate(state)
    def attributes(self): return self.rule.attributes()
    def describe(self): return f"not({self.rule.describe()})"


class ActivationCycle(Exception):
    """A dependency graph that cannot be evaluated.

    Raised at INSTALL time. Two fields each waiting for the other is not a
    runtime condition to handle; it is a registry that cannot be resolved, and
    it must break the process rather than pick an order and hope.
    """


@dataclass(frozen=True)
class ActivationState:
    """EVERYTHING A PREDICATE MAY SEE, AND NOTHING ELSE.

    The restriction is the design. `active_when` receives canonical item state
    and resolved semantic patches; raw text, prose, providers and materiality
    are absent from this object, so a predicate cannot consult them by
    accident or by expedience. Enforcing purity by review would last exactly
    until the first field that "just needs the message".
    """
    item: Mapping = _dc_field(default_factory=dict)
    #: attribute value -> the typed patch that resolved it
    resolved: Mapping = _dc_field(default_factory=dict)

    def has(self, attribute) -> bool:
        """Is this attribute resolved at all?"""
        return _name(attribute) in (self.resolved or {})

    def patch(self, attribute) -> Optional[Any]:
        return (self.resolved or {}).get(_name(attribute))

    def is_true(self, attribute) -> bool:
        """A resolved BOOLEAN answer, read without knowing the patch shape.

        Unresolved is FALSE, deliberately: a dependent field may not open on
        the strength of a question nobody has answered yet. "We have not asked
        whether there was oil" is not "there was oil".
        """
        patch = self.patch(attribute)
        if patch is None:
            return False
        for attr in ("value", "present", "answer"):
            if hasattr(patch, attr):
                return _truthy(getattr(patch, attr))
        return _truthy(patch)

    def value(self, attribute, default=None):
        patch = self.patch(attribute)
        return default if patch is None else getattr(patch, "value", patch)


def _name(attribute) -> str:
    return str(getattr(attribute, "value", attribute))


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "y", "1", "present")
    return bool(value)


@dataclass(frozen=True)
class Reconciliation:
    """The transition, as data the caller cannot misread.

    `retracted` carries the PATCHES, not just the names, because the operation
    has to record what was invalidated. "Unanswered because never active" and
    "answered and then invalidated" are different histories, and B-1.8's
    correction analysis cannot be written on top of a state that conflated
    them.
    """
    still_active: tuple = ()
    newly_active: tuple = ()
    newly_inactive: tuple = ()
    #: field_id -> patch, removed from settlement
    retracted: Mapping = _dc_field(default_factory=dict)

    @property
    def active(self) -> tuple:
        return tuple(sorted(set(self.still_active) | set(self.newly_active)))

    @property
    def changed(self) -> bool:
        """Did the SHAPE of the interaction change?

        The caller moves the operation revision on exactly this, which is what
        gives a reopened field a new identity and refuses a stale tap against
        the old one.
        """
        return bool(self.newly_active or self.newly_inactive)


def active_attributes(state: ActivationState, *, baseline=()) -> frozenset:
    """THE ONE AUTHORITATIVE CALCULATION of what is active right now.

    Pure, synchronous, and a function of `state` alone — so the same resolved
    state yields the same set no matter how it got there. B-1.5 paid for that
    lesson on the answer path: a value that arrived by chip, by typing, or in
    the original utterance must be the same value, and here it must produce
    the same TOPOLOGY too.

    Unconditional fields are active by definition; a CONDITIONAL field is
    active exactly when its declared predicate holds. A predicate that raises
    does NOT activate — the same rule `derive_unresolved` follows, for the same
    reason: an activation we could not evaluate is not evidence that a
    question is needed.
    """
    from core.semantic_fields import Activation, registered

    specs = registered() or {}
    # ⭐ UNCONDITIONAL MEMBERSHIP IS NOT THIS PASS'S TO DECIDE. `baseline` is
    # the set of WHEN_RAISED fields the operation is ACTUALLY asking about,
    # settled by the ask producer's materiality pass. Treating every
    # registered field as active would spontaneously "activate" preparation
    # and added-fat presence on an operation that only asked about quantity —
    # measured while writing the B-1.6b gates, where a plain value change
    # reported `newly_active=(preparation,)` and would have bumped the
    # revision, invalidating the chips on screen for no reason at all.
    out = {n for n in (_name(b) for b in (baseline or ()))
           if n in specs and specs[n].activation is not Activation.CONDITIONAL}
    for key, spec in specs.items():
        if spec.activation is not Activation.CONDITIONAL:
            continue
        try:
            if spec.active_when.evaluate(state):
                out.add(key)
        except Exception:
            logger.warning("event=activation_predicate_failed attribute=%s "
                           "active=false", key, exc_info=True)
    return frozenset(out)


def reconcile(*, previously_active, state: ActivationState,
              answered_by_field: Optional[Mapping] = None,
              attribute_of_field=None) -> Reconciliation:
    """previous -> desired, as three sets and the answers that must die.

    `attribute_of_field` maps a held field_id to its attribute; the caller owns
    that because field identity is the caller's (operation, event, revision),
    not this module's. Everything here is expressed in ATTRIBUTES, which are
    stable across revisions — the point of separating the two.
    """
    previous = {_name(a) for a in (previously_active or ())}
    desired = set(active_attributes(state, baseline=previous))

    still = tuple(sorted(previous & desired))
    fresh = tuple(sorted(desired - previous))
    gone = tuple(sorted(previous - desired))

    retracted = {}
    for field_id, patch in (answered_by_field or {}).items():
        attribute = (attribute_of_field(field_id, patch)
                     if attribute_of_field else None)
        if attribute and _name(attribute) in gone:
            retracted[field_id] = patch

    if fresh or gone:
        logger.info("event=field_reconciliation still=%s newly_active=%s "
                    "newly_inactive=%s retracted=%d",
                    ",".join(still) or "-", ",".join(fresh) or "-",
                    ",".join(gone) or "-", len(retracted))
    return Reconciliation(still_active=still, newly_active=fresh,
                          newly_inactive=gone, retracted=retracted)


def attribute_of_field_id(field_id: str, patch=None) -> str:
    """The ATTRIBUTE a field id answers.

    `UnresolvedField.field_id` is `operation:event:attribute:revision`, and the
    operation id itself contains colons — so this splits from the RIGHT.
    Prefers the patch's own `patch_type` when one is available, because a
    stored patch knows what it is and a string is only a convention.
    """
    if patch is not None:
        from core.semantic_fields import registered

        kind = str(getattr(patch, "patch_type", "") or "")
        for key, spec in (registered() or {}).items():
            if spec.patch_type == kind:
                return key
    parts = str(field_id or "").rsplit(":", 2)
    return parts[1] if len(parts) == 3 else ""


def state_from(item: Mapping, answered: Mapping) -> ActivationState:
    """Build the predicate's view from held answers, keyed by ATTRIBUTE.

    Held answers are keyed by field_id, which carries a revision. Activation
    is expressed in attributes precisely because they survive a revision
    change: a field that closes and reopens is the same question, and its
    predicate must not care which generation answered it.
    """
    resolved = {}
    for field_id, patch in (answered or {}).items():
        attribute = attribute_of_field_id(field_id, patch)
        if attribute:
            resolved[attribute] = patch
    return ActivationState(item=dict(item or {}), resolved=resolved)


def assert_settlement_is_consistent(*, item: Mapping, answered: Mapping,
                                    required=None) -> None:
    """THE COMMIT BOUNDARY RECHECKS, because reconciliation is not a promise.

    The answer path already reconciles. This asserts the RESULT independently
    at the point of no return, so an alternate caller, a future repair path or
    a replayed operation cannot commit a payload B-1.6 would never have
    produced. It derives nothing and decides nothing — a second policy here
    would be the two-owners defect wearing a safety vest.

    Two ways a payload can be wrong:

        an INACTIVE conditional still carries a value  -> nutrition the user
                                                          retracted
        an ACTIVE required field is unresolved         -> committing a
                                                          question as a fact
    """
    from core.semantic_fields import Activation, registered

    state = state_from(item, answered)
    specs = registered() or {}
    active = active_attributes(state, baseline=state.resolved.keys())

    # ONLY CONDITIONALS ARE POLICED. An unconditional field's answer is always
    # legitimate — it was asked because the ask producer judged it material,
    # and this boundary has no business re-litigating that. What it forbids is
    # a CONDITIONAL value surviving its dependency going false.
    for field_id, patch in (answered or {}).items():
        attribute = attribute_of_field_id(field_id, patch)
        conditional = (attribute in specs
                       and specs[attribute].activation is Activation.CONDITIONAL)
        if conditional and attribute not in active:
            raise InactiveValueAtSettlement(
                f"{attribute!r} is not active for this item and still carries "
                f"an answer ({field_id}) — settling it would price a value "
                f"whose dependency the user turned off")

    for attribute in (required or ()):
        name = _name(attribute)
        if name in active and name not in state.resolved:
            raise UnresolvedActiveField(
                f"{name!r} is active and unresolved — committing now would "
                f"turn an open question into a fact by omission")


class InactiveValueAtSettlement(Exception):
    """A retracted answer reached the commit boundary."""


class UnresolvedActiveField(Exception):
    """An active required field had no answer at the commit boundary."""


def assert_acyclic() -> None:
    """THE GRAPH MUST BE RESOLVABLE, checked once at install.

    Two fields declared with only two fields registered is easy to hold in the
    head. Sauce amount, milk type, alcohol mixer and workout load are coming,
    and a cycle among them would present as a field that never opens rather
    than as an error — which is the failure mode this whole registry exists to
    stop being possible.

    Checked over DECLARED `depends_on`, not by inspecting the callables: a
    predicate is opaque, so a field that reads an attribute it did not declare
    is a contract violation caught by `assert_declares_its_dependencies`.
    """
    from core.semantic_fields import registered

    specs = registered() or {}
    colour: dict = {}

    def visit(key: str, path: tuple) -> None:
        state = colour.get(key)
        if state == "done":
            return
        if state == "open":
            cycle = " -> ".join(path[path.index(key):] + (key,))
            raise ActivationCycle(
                f"activation cycle: {cycle}. A field waiting on a field that "
                f"waits on it never opens, and would present as a question "
                f"that silently never gets asked")
        colour[key] = "open"
        for dep in (specs[key].depends_on if key in specs else ()):
            if _name(dep) in specs:
                visit(_name(dep), path + (key,))
        colour[key] = "done"

    for key in specs:
        visit(key, ())


def assert_declares_its_dependencies() -> None:
    """Every dependency must NAME A REGISTERED FIELD.

    Derived from the rule, so it cannot disagree with what activation reads —
    but it can still point at nothing. A dependency on an unregistered
    attribute is a field that can never activate, which presents as a question
    that silently never gets asked rather than as an error.
    """
    from core.semantic_fields import Activation, registered

    specs = registered() or {}
    for key, spec in specs.items():
        if spec.activation is not Activation.CONDITIONAL:
            continue
        if not spec.depends_on:
            raise ActivationCycle(
                f"{key} is conditional and its rule reads no attribute — a "
                f"condition over nothing is a constant")
        if key in spec.depends_on:
            raise ActivationCycle(
                f"{key} depends on itself, so it could never open to be "
                f"answered")
        for dep in spec.depends_on:
            if _name(dep) not in specs:
                raise ActivationCycle(
                    f"{key} depends on {_name(dep)!r}, which is not a "
                    f"registered field — a dependency on nothing is a field "
                    f"that can never activate")


def activation_order() -> tuple:
    """Attributes in DETERMINISTIC topological order — dependencies first.

    ⭐ NOT `sorted(_REGISTRY)` AND NOT ITERATION ORDER. `active_attributes`
    returns a set, and a set has no order; if the interaction were built by
    walking it, field order in the iOS payload would eventually depend on
    registry insertion or hash iteration. That is a rendering difference with
    no semantic cause, and it would be diagnosed as a client bug.

    Ties are broken by `spec.order` then by name, so the sequence is a pure
    function of the registry contents rather than of how they got there.
    """
    from core.semantic_fields import registered

    specs = registered() or {}
    out, placed = [], set()

    def visit(key: str) -> None:
        if key in placed or key not in specs:
            return
        placed.add(key)
        for dep in sorted(specs[key].depends_on,
                          key=lambda d: (specs[_name(d)].order, _name(d))
                          if _name(d) in specs else (0, _name(d))):
            visit(_name(dep))
        out.append(key)

    for key in sorted(specs, key=lambda k: (specs[k].order, k)):
        visit(key)
    return tuple(out)
