"""Coordinator assembly (P0.2 Phase 5).

One place that answers "which stages handle this turn?", so promoting a lane
is a configuration change rather than an edit spread across call sites.

The rule is deliberately conservative: a lane runs natively only when
lane_executes_natively() says so — new_execute mode, the lane explicitly
enabled, and the user allowlisted if an allowlist is set. Everything else
gets the legacy stages, which delegate to run_turn(). There is never a state
where both paths execute: the caller runs the coordinator OR the legacy
pipeline, and the coordinator's own execution stage is native or delegating,
never both.
"""
from __future__ import annotations

import logging

from core.turns.coordinator import TurnCoordinator, lane_executes_natively
from core.turns.models import TurnLane
from core.turns.stages.route import RouteStage

logger = logging.getLogger(__name__)


def native_stages_for(lane: TurnLane):
    """(plan, validate) for a lane the coordinator can plan itself, or None
    when the lane still belongs to run_turn()."""
    if lane is TurnLane.STRUCTURED_FOOD:
        from core.turns.stages.food import FoodPlanStage, FoodValidationStage
        return FoodPlanStage(), FoodValidationStage()
    if lane is TurnLane.LEDGER_UNDO:
        from core.turns.stages.deterministic import (UndoPlanStage,
                                                     DeterministicValidationStage)
        return UndoPlanStage(), DeterministicValidationStage()
    return None


async def build_coordinator(request, **legacy_kwargs) -> TurnCoordinator:
    """Route first, then assemble. Routing is free and side-effect-free, so
    deciding the shape of the turn before building it costs nothing and keeps
    the native/legacy choice in one expression."""
    from core.turns.stages.context import LegacyContextStage
    from core.turns.stages.plan import LegacyPlanStage
    from core.turns.stages.validate import LegacyValidationStage
    from core.turns.stages.execute import LegacyExecutionStage
    from core.turns.stages.snapshot import PassthroughSnapshotStage
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    from core.turns.stages.render import PassthroughRenderStage
    from core.turns.stages.finalize import Finalizer

    route = await RouteStage().run(request)
    native = native_stages_for(route.lane)
    go_native = native is not None and lane_executes_natively(
        route.lane, getattr(request, "user_id", None))

    if go_native:
        from core.turns.stages.execute_native import NativeExecutionStage
        plan_stage, validation_stage = native
        execution_stage = NativeExecutionStage()
        snapshot_stage = CommittedSnapshotStage()
        logger.info(f"event=turn_native turn={request.turn_id} "
                    f"lane={route.lane.value} reason={route.reason_code}")
    else:
        plan_stage = LegacyPlanStage()
        validation_stage = LegacyValidationStage()
        execution_stage = LegacyExecutionStage(**legacy_kwargs)
        snapshot_stage = PassthroughSnapshotStage()

    return TurnCoordinator(
        context_stage=LegacyContextStage(**legacy_kwargs),
        route_stage=_Fixed(route),
        plan_stage=plan_stage,
        validation_stage=validation_stage,
        execution_stage=execution_stage,
        snapshot_stage=snapshot_stage,
        render_stage=PassthroughRenderStage(),
        finalizer=Finalizer())


class _Fixed:
    """Replays the route decision the factory already made, so routing runs
    exactly once per turn — a second call could disagree if the board or a
    pending question moved underneath it."""

    def __init__(self, decision):
        self.decision = decision

    async def run(self, *a, **k):
        return self.decision
