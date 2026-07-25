"""Planning. Phase 1: the general/legacy lanes declare a delegation plan —
the real work still happens inside run_turn(). Native planners land per lane
(structured food first)."""
from __future__ import annotations

from core.turns.models import TurnPlan


class LegacyPlanStage:
    async def run(self, request, context=None, route=None) -> TurnPlan:
        return TurnPlan(operations=(), response_intent="delegate_legacy",
                        planner_version="legacy-adapter-v1")
