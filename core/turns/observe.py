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

import contextvars
import logging
import os
from typing import Optional

from core.turns.coordinator import (coordinator_mode, MODE_NEW_OBSERVE,
                                    MODE_NEW_EXECUTE)
from core.turns.models import TurnLane, TurnRequest
from core.turns.stages.route import RouteStage

logger = logging.getLogger(__name__)

#: The route THIS turn actually took, published by the coordinator so nothing
#: downstream has to recompute it. Ambient rather than threaded through because
#: the observation happens deep inside run_turn(), and adding a parameter to
#: every frame between here and there is how the two copies diverged in the
#: first place.
#:
#: Always set — to None when no coordinator ran — so a previous turn's route can
#: never leak into one on a reused task.
CURRENT_ROUTE: contextvars.ContextVar = contextvars.ContextVar(
    "current_route_decision", default=None)


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


#: Fallback reasons that mean THE INTERPRETER RAN AND HANDED THE TURN BACK.
#:
#: A turn the food lane looked at and declined is not a turn the gate never
#: admitted, and `_turn_route` cannot tell them apart — both end as "legacy".
#: So every food-shaped question the lane is DESIGNED to hand back was scored
#: as a routing disagreement, and the observed rate was inflated by exactly the
#: class of turn that proves the design works.
#:
#: Gate declines — kill_switch, not_food_shaped, and whatever `decline_reason`
#: returns — stay GENERAL, which is correct: the lane never took them.
_INTERPRETER_RAN = frozenset({
    "interpreter_none", "interpreter_timeout", "pipeline_exception",
    "ask_stash_failed",
})


def legacy_lane(turn_route: str, legacy_reason: str = "") -> str:
    """Map what run_turn() actually did onto a lane, or "" when the route has
    no coordinator equivalent yet.

    `legacy_reason` distinguishes "the lane declined this" from "the lane never
    saw it" — see `_INTERPRETER_RAN`.
    """
    mapped = _LEGACY_LANES.get((turn_route or "").strip(), "")
    if mapped == TurnLane.GENERAL.value \
            and (legacy_reason or "").strip() in _INTERPRETER_RAN:
        return TurnLane.STRUCTURED_FOOD.value
    return mapped


def legacy_disposition(turn_route: str, legacy_reason: str = "") -> str:
    """What the legacy turn actually DID, in the validator's vocabulary.

    The caller used to report `"ask" if route == "structured_ask" else ""`, and
    `observe_turn` short-circuits `agree_disp` to True on an empty string — so
    every commit turn reported `actual_disposition=-` and disposition agreement
    has never once been compared. With TURN_COORDINATOR_OBSERVE_DEEP on, that
    is a second Sonnet call per food turn feeding a metric that measures
    nothing.
    """
    route = (turn_route or "").strip()
    if route == "structured_ask":
        return "ask"
    if route.startswith("structured_") or route == "confirm_replay":
        return "execute"
    if (legacy_reason or "").strip() in _INTERPRETER_RAN:
        return "pass"
    return ""


async def observe_turn(request: TurnRequest,
                       actual_route: str = "",
                       actual_disposition: str = "") -> Optional[dict]:
    """Run the read-only stages and log predicted-vs-actual. Returns the
    prediction (for tests) or None when not observing. NEVER raises, and
    never touches anything with a side effect."""
    if not observing():
        return None
    try:
        # ONE ROUTE PER TURN. This used to call RouteStage itself, which was
        # correct while the coordinator was a bystander — nobody else was
        # routing. Now the coordinator is the entrypoint and has already routed
        # for real, so recomputing here would be a second router whose answer
        # could differ from the one the turn actually took, and the agreement
        # line would then be comparing legacy against a route nothing ran.
        route = CURRENT_ROUTE.get() or await RouteStage().run(request)
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
