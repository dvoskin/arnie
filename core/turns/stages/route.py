"""Lane selection — the first NATIVE stage (P0.2 Phase 1).

Reuses the live gates rather than re-deciding: the same predicates
conversation.py routes on today, so observe-mode comparisons are meaningful
from day one instead of measuring a second opinion.
"""
from __future__ import annotations

import logging

from core.turns.models import RouteDecision, TurnLane

logger = logging.getLogger(__name__)

ROUTER_VERSION = "turn_router_v1"


class RouteStage:
    async def run(self, request, context=None) -> RouteDecision:
        text = request.text or ""
        meta = request.metadata or {}

        if meta.get("in_onboarding"):
            return RouteDecision(TurnLane.ONBOARDING, "onboarding_active",
                                 1.0, ROUTER_VERSION)
        try:
            from core.ledger_undo import detect as _undo_detect
            if _undo_detect(text) is not None:
                return RouteDecision(TurnLane.LEDGER_UNDO, "undo_shape",
                                     1.0, ROUTER_VERSION)
        except Exception:
            pass
        try:
            from core.food_turn import (structured_food_enabled, applies,
                                        applies_destructive)
            if structured_food_enabled():
                if meta.get("food_pending"):
                    return RouteDecision(TurnLane.STRUCTURED_FOOD,
                                         "pending_clarification", 1.0,
                                         ROUTER_VERSION)
                if applies(text):
                    return RouteDecision(TurnLane.STRUCTURED_FOOD,
                                         "cold_food_gate", 0.9, ROUTER_VERSION)
                if meta.get("has_board") and applies_destructive(text):
                    return RouteDecision(TurnLane.STRUCTURED_FOOD,
                                         "single_entry_delete", 0.9,
                                         ROUTER_VERSION)
        except Exception as e:
            logger.debug(f"route stage food gate skipped: {e}")
        return RouteDecision(TurnLane.GENERAL, "default", 0.5, ROUTER_VERSION)
