"""Finalization — the single exit point. Phase 1 keeps persistence with the
legacy pipeline (which already logged the conversation) and owns only the
turn-lifecycle summary; the durable turn record lands here next."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Finalizer:
    async def run(self, state) -> None:
        try:
            lane = getattr(getattr(state.route, "lane", None), "value", "-")
            logger.info(
                f"event=turn_lifecycle turn={state.request.turn_id} "
                f"lane={lane} status=finalized "
                f"planner={getattr(state.plan, 'planner_version', '-')} "
                f"policy={getattr(state.validation, 'policy_version', '-')} "
                f"snapshot={getattr(state.snapshot, 'snapshot_version', '-')} "
                f"ms={sum(state.timings_ms.values())}")
        except Exception:
            pass

    async def recover(self, state):
        """A failed turn still answers. The legacy pipeline has its own
        recovery text; this is the coordinator's floor for a stage crash."""
        try:
            from handlers.tool_executor import recovery_message
            from core.platform import Response
            return Response.from_text(
                recovery_message("llm_error", seed=state.request.text))
        except Exception:
            return None
