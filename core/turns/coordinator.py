"""The turn coordinator (P0.2, architecture review 2026-07-25).

Runs ABOVE the existing system, not instead of it: the coordinator owns
progress, contracts and the trace, while unmigrated lanes delegate to
run_turn() through the legacy adapter. Lanes migrate one at a time; the
adapter is deleted last.

Phase advancement is the coordinator's alone, and only along legal edges —
which structurally prevents the failure classes the review named: rendering
before commit, executing twice, finalizing an unrendered response, cards
built from an uncommitted plan.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from core.turns.models import TurnPhase, TurnLane, TurnRequest, TurnState
from core.turns.trace import TurnTrace

logger = logging.getLogger(__name__)


class InvalidTurnTransition(RuntimeError):
    """A phase edge that must never happen — a bug in stage wiring, not a
    user-facing condition."""


_ALLOWED_TRANSITIONS = {
    TurnPhase.RECEIVED: {TurnPhase.CONTEXT_READY, TurnPhase.FAILED},
    TurnPhase.CONTEXT_READY: {TurnPhase.ROUTED, TurnPhase.FAILED},
    TurnPhase.ROUTED: {TurnPhase.PLANNED, TurnPhase.FAILED},
    TurnPhase.PLANNED: {TurnPhase.VALIDATED, TurnPhase.FAILED},
    TurnPhase.VALIDATED: {TurnPhase.EXECUTED, TurnPhase.RENDERED,
                          TurnPhase.FAILED},
    TurnPhase.EXECUTED: {TurnPhase.SNAPSHOT_READY, TurnPhase.FAILED},
    TurnPhase.SNAPSHOT_READY: {TurnPhase.RENDERED, TurnPhase.FAILED},
    TurnPhase.RENDERED: {TurnPhase.FINALIZED, TurnPhase.FAILED},
    TurnPhase.FINALIZED: set(),
    TurnPhase.FAILED: set(),
}


def transition(state: TurnState, next_phase: TurnPhase) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(state.phase, set())
    if next_phase not in allowed:
        raise InvalidTurnTransition(
            f"{state.phase.value} cannot transition to {next_phase.value}")
    state.phase = next_phase


# ── rollout modes ─────────────────────────────────────────────────────────────
# legacy_only  — production today: the coordinator does not run at all.
# new_observe  — the coordinator runs its SAFE stages only (request, route,
#                plan, validate) and records what it WOULD have done. It must
#                never execute tools, write rows, send messages or schedule
#                jobs; the legacy path executes normally alongside.
# new_execute  — the coordinator owns execution for explicitly enabled lanes.
MODE_LEGACY_ONLY = "legacy_only"
MODE_NEW_OBSERVE = "new_observe"
MODE_NEW_EXECUTE = "new_execute"


def coordinator_mode() -> str:
    m = (os.getenv("TURN_COORDINATOR_MODE", MODE_LEGACY_ONLY) or "").strip().lower()
    return m if m in (MODE_LEGACY_ONLY, MODE_NEW_OBSERVE, MODE_NEW_EXECUTE) \
        else MODE_LEGACY_ONLY


def _enabled_lanes() -> set:
    raw = os.getenv("TURN_COORDINATOR_LANES", "") or ""
    return {p.strip() for p in raw.split(",") if p.strip()}


def _allowlist() -> set:
    raw = os.getenv("TURN_COORDINATOR_ALLOWLIST", "") or ""
    out = set()
    for p in raw.split(","):
        p = p.strip()
        if p.isdigit():
            out.add(int(p))
    return out


def lane_executes_natively(lane, user_id=None) -> bool:
    """True only when the coordinator should OWN this turn's execution:
    new_execute mode, the lane explicitly enabled, and (if an allowlist is
    set) this user included. Everything else delegates to legacy."""
    if coordinator_mode() != MODE_NEW_EXECUTE:
        return False
    lane_v = getattr(lane, "value", str(lane))
    if lane_v not in _enabled_lanes():
        return False
    allow = _allowlist()
    return (not allow) or (user_id in allow)


class TurnCoordinator:
    """Stages in, typed state out. Each stage receives what it needs and
    returns ONE result; the coordinator assigns it and advances the phase."""

    def __init__(self, context_stage, route_stage, plan_stage,
                 validation_stage, execution_stage, snapshot_stage,
                 render_stage, finalizer, trace: Optional[TurnTrace] = None):
        self.context_stage = context_stage
        self.route_stage = route_stage
        self.plan_stage = plan_stage
        self.validation_stage = validation_stage
        self.execution_stage = execution_stage
        self.snapshot_stage = snapshot_stage
        self.render_stage = render_stage
        self.finalizer = finalizer
        self.trace = trace or TurnTrace()

    async def run(self, request: TurnRequest) -> TurnState:
        state = TurnState(request=request)
        try:
            state.context = await self.context_stage.run(request)
            transition(state, TurnPhase.CONTEXT_READY)
            self.trace.transition(state)

            state.route = await self.route_stage.run(
                request=request, context=state.context)
            transition(state, TurnPhase.ROUTED)
            self.trace.transition(state)

            state.plan = await self.plan_stage.run(
                request=request, context=state.context, route=state.route)
            transition(state, TurnPhase.PLANNED)
            self.trace.transition(state)

            state.validation = await self.validation_stage.run(
                request=request, context=state.context,
                route=state.route, plan=state.plan)
            transition(state, TurnPhase.VALIDATED)
            self.trace.transition(state)

            # WHAT WAS APPROVED IS WHAT RUNS. Gating solely on the string
            # "execute" meant an ASK could never commit anything, so the
            # partial-commit contract was unreachable natively however the
            # policy had decided (audit A1). The disposition says what to SAY;
            # `approved_operations` says what may be WRITTEN, and a clarifying
            # turn legitimately does both. Still explicit rather than "any ops":
            # a `pass` or `reject` carrying operations is a bug, not a licence.
            _approved = tuple(state.validation.approved_operations or ())
            if state.validation.disposition == "execute" or (
                    state.validation.disposition == "ask" and _approved):
                state.execution = await self.execution_stage.run(
                    request=request, route=state.route,
                    validation=state.validation)
                transition(state, TurnPhase.EXECUTED)
                self.trace.transition(state)

                state.snapshot = await self.snapshot_stage.run(
                    request=request, execution=state.execution)
                transition(state, TurnPhase.SNAPSHOT_READY)
                self.trace.transition(state)

            state.response = await self.render_stage.run(
                request=request, context=state.context, route=state.route,
                plan=state.plan, validation=state.validation,
                snapshot=state.snapshot)
            transition(state, TurnPhase.RENDERED)
            self.trace.transition(state)

            await self.finalizer.run(state)
            transition(state, TurnPhase.FINALIZED)
            self.trace.transition(state)
            return state
        except Exception as exc:
            state.error = exc
            state.phase = TurnPhase.FAILED      # terminal: always reachable
            self.trace.transition(state)
            logger.warning(
                f"event=turn_failed turn={request.turn_id} "
                f"phase={state.phase.value} err={type(exc).__name__}: {exc}")
            state.response = await self.finalizer.recover(state)
            return state
