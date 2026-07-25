"""Execution. Phase 1: hands the turn to the existing pipeline through the
legacy adapter, which returns the familiar TurnResult."""
from __future__ import annotations

from core.turns.legacy_adapter import LegacyTurnAdapter


class LegacyExecutionStage:
    def __init__(self, adapter: LegacyTurnAdapter = None, **legacy_kwargs):
        self.adapter = adapter or LegacyTurnAdapter()
        self.legacy_kwargs = legacy_kwargs

    async def run(self, request, route=None, validation=None):
        return await self.adapter.run(**self.legacy_kwargs)
