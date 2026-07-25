"""Shadow observation (P0.2 Phase 2).

In new_observe mode the coordinator runs only the SAFE stages — request,
route, plan, validate — and records what it WOULD have done. It never
executes tools, writes rows, sends messages or schedules jobs; the legacy
path runs normally alongside and remains the only thing with side effects.

The output is one comparison line per turn: predicted lane and disposition
versus what legacy actually did. That is the evidence needed before any lane
is promoted to new_execute.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from core.turns.coordinator import (coordinator_mode, MODE_NEW_OBSERVE,
                                    MODE_NEW_EXECUTE)
from core.turns.models import TurnLane, TurnRequest
from core.turns.stages.route import RouteStage

logger = logging.getLogger(__name__)


def observing() -> bool:
    return coordinator_mode() in (MODE_NEW_OBSERVE, MODE_NEW_EXECUTE)


def deep_observing() -> bool:
    """Planning stages re-run the interpreter, which is a second model call on
    every food turn. Route agreement is the first thing worth measuring and
    costs nothing, so it is the default; disposition agreement is opt-in."""
    return (os.getenv("TURN_COORDINATOR_OBSERVE_DEEP", "") or "").strip().lower() \
        in ("1", "true", "yes")


#: legacy `_turn_route` values → coordinator lanes. Comparison is only
#: meaningful against a route the coordinator also models; anything absent
#: here (a duplicate claim, say) is reported without a verdict.
_LEGACY_LANES = {
    "ledger_undo": TurnLane.LEDGER_UNDO.value,
    "confirm_replay": TurnLane.STRUCTURED_FOOD.value,
    "structured_log": TurnLane.STRUCTURED_FOOD.value,
    "structured_update": TurnLane.STRUCTURED_FOOD.value,
    "structured_delete": TurnLane.STRUCTURED_FOOD.value,
    "structured_commit": TurnLane.STRUCTURED_FOOD.value,
    "structured_ask": TurnLane.STRUCTURED_FOOD.value,
    "legacy": TurnLane.GENERAL.value,
}


def legacy_lane(turn_route: str) -> str:
    """Map what run_turn() actually did onto a lane, or "" when the route has
    no coordinator equivalent yet."""
    return _LEGACY_LANES.get((turn_route or "").strip(), "")


async def observe_turn(request: TurnRequest,
                       actual_route: str = "",
                       actual_disposition: str = "") -> Optional[dict]:
    """Run the read-only stages and log predicted-vs-actual. Returns the
    prediction (for tests) or None when not observing. NEVER raises, and
    never touches anything with a side effect."""
    if not observing():
        return None
    try:
        route = await RouteStage().run(request)
        prediction = {"lane": route.lane.value, "reason": route.reason_code,
                      "disposition": ""}
        plan = validation = None
        if route.lane is TurnLane.STRUCTURED_FOOD and deep_observing():
            from core.turns.stages.food import FoodPlanStage, FoodValidationStage
            plan = await FoodPlanStage().run(request, route=route)
            validation = await FoodValidationStage().run(request, plan=plan)
        elif route.lane is TurnLane.LEDGER_UNDO:
            from core.turns.stages.deterministic import (
                UndoPlanStage, DeterministicValidationStage)
            plan = await UndoPlanStage().run(request, route=route)
            validation = await DeterministicValidationStage().run(
                request, plan=plan)
        if validation is not None:
            prediction["disposition"] = validation.disposition
            prediction["ops"] = len(validation.approved_operations)
            prediction["planner"] = plan.planner_version
        agree_lane = (not actual_route) or (actual_route == prediction["lane"])
        agree_disp = (not actual_disposition
                      or not prediction["disposition"]
                      or actual_disposition == prediction["disposition"])
        logger.info(
            f"event=turn_observe turn={request.turn_id} "
            f"predicted_lane={prediction['lane']} actual_lane={actual_route or '-'} "
            f"predicted_disposition={prediction['disposition'] or '-'} "
            f"actual_disposition={actual_disposition or '-'} "
            f"agree={'yes' if (agree_lane and agree_disp) else 'NO'}")
        return prediction
    except Exception as e:
        logger.warning(f"turn observation skipped: {e}")
        return None
