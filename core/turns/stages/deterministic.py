"""Native deterministic stages (P0.2 Phase 3).

These are the turns that need no model at all — the answer is already in the
ledger or in the pending question. Legacy computes them inline inside
run_turn() as two of several short-circuits; here each is a stage with a
version tag, so a turn's route is a recorded decision instead of the position
of an `elif`.

  UndoPlanStage          "undo" / "bring back the fries" → the inverse of the
                         last ledger event (core.ledger_undo).
  ConfirmReplayPlanStage an affirmative answering an open confirm → the
                         stashed items replayed through the SAME call builder
                         the interpreter uses. No re-parse, no model.

Nothing here executes. Both stages produce a plan; the coordinator decides
whether it runs, and only in a lane explicitly enabled for new_execute.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.turns.models import TurnPlan
from core.turns.stages.food import FoodValidationStage

logger = logging.getLogger(__name__)

UNDO_PLANNER_VERSION = "undo_planner_v1"
REPLAY_PLANNER_VERSION = "confirm_replay_v1"

#: Provenance on replayed calls — a logged item must always say where it came
#: from, and "the user said yes to a confirm" is different from "the model
#: parsed this sentence".
REPLAY_SOURCE = "structured_food:confirm_replay"

#: Legacy caps the replay at 8 items; matching it keeps observe-mode honest.
_REPLAY_LIMIT = 8


def _lift(plan: Optional[dict], version: str) -> TurnPlan:
    """Interpreter-shaped dict → typed plan. An empty/None plan is a `pass`,
    which routes the turn back to the conversational lane."""
    if not plan or not plan.get("tool_calls"):
        return TurnPlan(operations=(), response_intent="pass",
                        planner_version=version)
    return TurnPlan(operations=tuple(plan.get("tool_calls") or ()),
                    response_intent=plan.get("action") or "",
                    narration_hint=str(plan.get("say") or ""),
                    planner_version=version)


class UndoPlanStage:
    """The inverse of the last ledger event, with zero model calls."""

    async def run(self, request, context=None, route=None) -> TurnPlan:
        meta = request.metadata or {}
        db, user = meta.get("db"), meta.get("user")
        if db is None or user is None:
            return TurnPlan(operations=(), response_intent="pass",
                            planner_version=UNDO_PLANNER_VERSION)
        # An undo mid-question means "cancel", which the ack path and pending
        # expiry already own — same guard the legacy lane applies.
        if meta.get("food_prior") is not None:
            return TurnPlan(operations=(), response_intent="pass",
                            planner_version=UNDO_PLANNER_VERSION)
        try:
            from core.ledger_undo import build_plan
            plan = await build_plan(db, user, request.text or "")
        except Exception as e:
            logger.warning(f"undo plan stage failed: {e}")
            plan = None
        return _lift(plan, UNDO_PLANNER_VERSION)


class ConfirmReplayPlanStage:
    """"yes" to an open confirm → log the stashed items verbatim.

    Returns None (not a pass-plan) when this is not a replay, so the caller
    can fall through to the interpreter — a non-affirmative reply to a confirm
    is a correction, and corrections still need parsing."""

    async def run(self, request, context=None, route=None) -> Optional[TurnPlan]:
        prior = (request.metadata or {}).get("food_prior")
        if not prior or prior.get("kind") != "confirm" or not prior.get("items"):
            return None
        try:
            from core.food_turn import _YES_RE, _log_call
        except Exception:
            return None
        if not _YES_RE.match((request.text or "").strip()):
            return None
        calls = [c for c in (_log_call(it, source=REPLAY_SOURCE)
                             for it in prior["items"][:_REPLAY_LIMIT])
                 if c is not None]
        return _lift({"action": "log", "tool_calls": calls},
                     REPLAY_PLANNER_VERSION)


class DeterministicValidationStage(FoodValidationStage):
    """Same disposition rule as the food lane — operations execute, nothing
    passes — under its own policy version so the two are distinguishable in
    the trace."""

    POLICY_VERSION = "deterministic_policy_v1"
