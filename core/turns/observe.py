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
from typing import Optional

from core.turns.coordinator import (coordinator_mode, MODE_NEW_OBSERVE,
                                    MODE_NEW_EXECUTE)
from core.turns.models import TurnLane, TurnRequest
from core.turns.stages.route import RouteStage

logger = logging.getLogger(__name__)


def observing() -> bool:
    return coordinator_mode() in (MODE_NEW_OBSERVE, MODE_NEW_EXECUTE)


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
        if route.lane is TurnLane.STRUCTURED_FOOD:
            from core.turns.stages.food import FoodPlanStage, FoodValidationStage
            plan = await FoodPlanStage().run(request, route=route)
            validation = await FoodValidationStage().run(request, plan=plan)
            prediction["disposition"] = validation.disposition
            prediction["ops"] = len(validation.approved_operations)
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
