"""Typed turn model (P0.2, architecture review 2026-07-25).

run_turn() is a ~2000-line procedural coordinator whose progress lives in
mutable locals: whether text streamed, whether tools fired, whether a rescue
re-entered execution. Every reliability fix has to reason about that whole
implicit state machine at once.

This module makes progress EXPLICIT — without rewriting run_turn in place.
The shape is deliberately hybrid: the coordinator owns one mutable TurnState,
but every payload assigned to it is frozen. A fully immutable state copied at
each transition creates friction; a mutable bag reproduces today's problem.

Stages never reach into TurnState — each takes what it needs and returns ONE
typed result, which the coordinator assigns. Only the coordinator advances
the phase, and only along legal edges (see coordinator._ALLOWED_TRANSITIONS).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class TurnPhase(str, Enum):
    RECEIVED = "received"
    CONTEXT_READY = "context_ready"
    ROUTED = "routed"
    PLANNED = "planned"
    VALIDATED = "validated"
    EXECUTED = "executed"
    SNAPSHOT_READY = "snapshot_ready"
    RENDERED = "rendered"
    FINALIZED = "finalized"
    FAILED = "failed"


class TurnLane(str, Enum):
    STRUCTURED_FOOD = "structured_food"
    LEDGER_UNDO = "ledger_undo"
    ONBOARDING = "onboarding"
    GENERAL = "general"
    DETERMINISTIC = "deterministic"


@dataclass(frozen=True)
class TurnRequest:
    """One inbound message, transport-independent. turn_id is the canonical
    identity from core/turn_identity — the same id the ledger stamps."""
    turn_id: str
    user_id: int
    platform: str
    source_type: str
    text: str
    client_message_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextManifest:
    """What the turn was given to think with — and what it was NOT. The
    omitted list is the seed of per-turn token budgeting (P1)."""
    system_prompt: str
    messages: tuple = ()
    user_timezone: str = "UTC"
    included_sections: tuple = ()
    omitted_sections: tuple = ()

    @property
    def token_estimate(self) -> int:
        """~4 characters per token — an estimate, never a measurement.

        A property rather than a field because it was computed eagerly on
        EVERY turn, walking the system prompt and the whole thread, and read by
        nothing. The budgeting this feeds is still ahead of us; when it lands
        it can ask, and until then nobody pays.
        """
        return (len(self.system_prompt)
                + sum(len(str(m.get("content", "")))
                      for m in self.messages if isinstance(m, dict))) // 4


@dataclass(frozen=True)
class RouteDecision:
    lane: TurnLane
    reason_code: str
    confidence: float = 1.0
    contract_version: str = ""


@dataclass(frozen=True)
class FoodSubject:
    """⛔ CF5c — ONE FOOD THIS TURN IS ABOUT, whatever the producer did with
    it. A plan names its foods in as many as five places — the ready writes,
    the deferred writes, the asked question labels, the staged material and
    the raw interpretation — and no single one of them is complete: the
    validation stage approves only the READY items of an ask, the deferred
    ones ride a different key, the asked ones ride only a label. A gate that
    counted any ONE of those views could bind a scan to a two-food turn, or
    read a one-food ask as no food at all.

    So the producer's COMPLETE interpretation is normalised ONCE, here, into a
    typed list — and the scan authority reads only this. `role` says where the
    subject came from; `open_fields` says which questions are still open on
    it (empty for a write that is ready)."""
    name: str
    role: str                     # ready | held | asked | staged | interpreted
    open_fields: tuple = ()       # e.g. ("quantity",) — the fields still asked
    key: str = ""                 # the occurrence key (see food_subjects_of)
    # ⛔ CF5c-B2 — DID THE USER SAY THEY ATE IT? A quantity ask whose answer
    # LOGS food is only legitimate for a food the user asserted consuming; a
    # scanned or named product with no consumption statement ("scanned a
    # bar", "got some Barebells") must not open a quantity-to-log operation.
    # A ready or held WRITE is a consumption assertion (the interpreter
    # decided to log it); a label-only subject inherits the message's
    # `consumption_state` and is asserted only when that says CONSUMED.
    consumed: bool = False


@dataclass(frozen=True)
class TurnPlan:
    operations: tuple = ()
    response_intent: str = ""
    ambiguities: tuple = ()
    # The model's PROPOSED sentence. A hint, never the reply: it is subject to
    # say-safety (a database-dependent claim is replaced by the deterministic
    # line) and its numbers are tokens filled from the committed snapshot.
    narration_hint: str = ""
    planner_version: str = ""
    # ⛔ CF5c — THE COMPLETE SET OF FOODS THIS TURN IS ABOUT, deduplicated by
    # normalised name, with the fields still open on each. Populated by
    # `plan_from_interpretation` from the producer's whole output; read by
    # `core.scan_authority` and by nothing that would re-derive it. Empty for a
    # plan that is not about food (undo, deterministic, pass).
    food_subjects: tuple = ()
    # The union of open fields across the subjects — "what is still being
    # asked" — so a consumer can tell "quantity is the only unknown" without
    # walking the subjects itself.
    open_fields: tuple = ()
    # ⛔ CF5c-B4 — the interpreter's RAW output, carried so the post-decision
    # bind step can transform the plan (answer an identity question, lift an
    # implicit correction, restore the user's unit) from the same facts the
    # planner saw — AFTER the authority has said BOUND, never before. The
    # planner itself is attachment-blind. Not read by anything else.
    source: Any = None


@dataclass(frozen=True)
class ValidationResult:
    disposition: str                 # execute | ask | pass | reject
    approved_operations: tuple = ()
    clarification: Optional[Any] = None
    policy_version: str = ""
    # ⛔ CF5c — the plan this validation was made from, so execution can read
    # the TYPED food subjects (`plan.food_subjects`) without reaching back into
    # the interpreter's dict. `approved_operations` is a SUBSET of the plan
    # (an ask approves only the ready writes); the subjects are the whole.
    plan: Optional[Any] = None


@dataclass(frozen=True)
class TurnSnapshot:
    """The committed result every renderer reads from. Domain-general by
    design: food is the first consumer, exercise/water/weight follow."""
    turn_id: str
    execution: Any = None
    affected_entities: tuple = ()
    ledger_event_ids: tuple = ()
    day_revision: Optional[int] = None
    day_totals: Optional[Mapping[str, float]] = None
    remaining_targets: Optional[Mapping[str, float]] = None
    snapshot_version: str = "turn_snapshot_v1"


@dataclass
class TurnState:
    """Coordinator-owned. Mutable container, frozen contents."""
    request: TurnRequest
    phase: TurnPhase = TurnPhase.RECEIVED
    context: Optional[ContextManifest] = None
    route: Optional[RouteDecision] = None
    plan: Optional[TurnPlan] = None
    validation: Optional[ValidationResult] = None
    execution: Optional[Any] = None
    snapshot: Optional[TurnSnapshot] = None
    response: Optional[Any] = None
    health_flags: set = field(default_factory=set)
    timings_ms: dict = field(default_factory=dict)
    error: Optional[BaseException] = None
