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
from typing import Any, Optional

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


# ── clarification ────────────────────────────────────────────────────────────

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

    @property
    def send_value(self) -> str:
        """What a channel without a value channel (Telegram, iMessage) sends
        back. The server resolves it against the stored options."""
        return self.label if self.value is None else str(self.value)


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
        # ENTERING A FAILURE MEANS RECORDING ONE. Enforced here rather than in
        # `record_failure` so the invariant holds for every caller, including
        # one that reaches for the primitive.
        if target is PendingStatus.RETRYABLE_FAILURE:
            if changes.get("attempt_count") != self.attempt_count + 1:
                raise InvalidPendingTransition(
                    self.status, target,
                    "entering a retryable failure must increment "
                    f"attempt_count to {self.attempt_count + 1}")
            if not changes.get("last_error"):
                raise InvalidPendingTransition(
                    self.status, target,
                    "a recorded failure must carry its error")
        if target is PendingStatus.FAILED and not (
                changes.get("terminal_reason") or self.terminal_reason):
            raise InvalidPendingTransition(
                self.status, target, "a terminal failure must say why")
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
            attempt_count=attempts,
            last_error=error,
            terminal_reason=("attempts_exhausted" if exhausted
                             else self.terminal_reason))

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
