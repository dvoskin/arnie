"""Native structured-food stages (P0.2 Phase 2).

The food lane already has the coordinator's shape internally — interpret →
validate → execute → snapshot → render — so it migrates first. These stages
call the SAME functions the legacy lane calls (core.food_turn.run, the
deterministic policy engine), which is what makes observe-mode comparison
meaningful: any divergence is a wiring bug, not two different opinions.

Nothing here executes. Execution stays with the legacy lane until a lane is
explicitly enabled via TURN_COORDINATOR_MODE=new_execute.
"""
from __future__ import annotations

import logging

from core.turns.models import TurnPlan, ValidationResult

logger = logging.getLogger(__name__)

FOOD_PLANNER_VERSION = "food_planner_v1"


class FoodPlanStage:
    """Runs the interpreter and lifts its result into a typed plan. The
    interpreter's own ask/confirm decisions arrive as ambiguities so the
    validation stage — not the planner — decides the disposition."""

    def __init__(self, interpreter=None):
        self._interpreter = interpreter

    async def run(self, request, context=None, route=None) -> TurnPlan:
        # A "yes" answering an open confirm is already decided (P0.2 Phase 3):
        # replay the stashed items rather than paying for a re-parse. Anything
        # else answering a confirm is a correction, and falls through.
        from core.turns.stages.deterministic import ConfirmReplayPlanStage
        replay = await ConfirmReplayPlanStage().run(request, context, route)
        if replay is not None:
            return replay
        run_interpreter = self._interpreter
        if run_interpreter is None:
            from core.food_turn import run as run_interpreter
        meta = request.metadata or {}
        try:
            out = await run_interpreter(
                request.text, meta.get("user"),
                prior=meta.get("food_prior"),
                day_line=meta.get("day_line", ""),
                board=meta.get("board"),
                last_assistant=meta.get("last_assistant", ""),
                regulars=meta.get("regulars"),
                thread_active=bool(meta.get("thread_active")))
        except Exception as e:
            logger.warning(f"food plan stage failed: {e}")
            out = None
        if not out:
            return TurnPlan(operations=(), response_intent="pass",
                            planner_version=FOOD_PLANNER_VERSION)
        action = out.get("action")
        if action == "ask":
            return TurnPlan(
                operations=(),
                response_intent=("confirm" if out.get("kind") == "confirm"
                                 else "ask"),
                ambiguities=(out,),
                planner_version=FOOD_PLANNER_VERSION)
        return TurnPlan(
            operations=tuple(out.get("tool_calls") or ()),
            response_intent=action or "",
            ambiguities=(),
            narration_hint=str(out.get("say") or ""),
            planner_version=FOOD_PLANNER_VERSION)


class FoodValidationStage:
    """Disposition is the SYSTEM's call, never the interpreter's: a plan with
    operations executes; an ask/confirm holds the write; anything else passes
    to the conversational lane."""

    POLICY_VERSION = "food_policy_v1"

    async def run(self, request, context=None, route=None, plan=None) -> ValidationResult:
        intent = getattr(plan, "response_intent", "") or ""
        ops = tuple(getattr(plan, "operations", ()) or ())
        if intent in ("ask", "confirm"):
            return ValidationResult(
                disposition="ask",
                clarification=(plan.ambiguities[0] if plan.ambiguities else None),
                policy_version=self.POLICY_VERSION)
        if ops:
            return ValidationResult(disposition="execute",
                                    approved_operations=ops,
                                    policy_version=self.POLICY_VERSION)
        return ValidationResult(disposition="pass",
                                policy_version=self.POLICY_VERSION)
