"""The bridge that lets the coordinator ship before the lanes migrate
(P0.2 Phase 1).

Unmigrated lanes still run the existing run_turn() — the coordinator owns
progress and contracts; run_turn keeps doing the actual work. This is the
temporary organ transplant seam, deleted lane by lane.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LegacyTurnAdapter:
    """Wraps the existing pipeline behind one call. The kwargs mirror
    run_turn's signature so callers hand through their own callbacks and
    session, unchanged."""

    def __init__(self, run_turn=None):
        self._run_turn = run_turn

    async def run(self, **kwargs) -> Any:
        run_turn = self._run_turn
        if run_turn is None:
            from core.conversation import run_turn as _rt
            run_turn = _rt
        return await run_turn(**kwargs)
