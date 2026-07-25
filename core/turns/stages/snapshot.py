"""Snapshot. Phase 1: wraps whatever execution produced so the contract
exists end to end. The universal TurnSnapshot (day revision, affected rows,
totals, remaining targets) fills in as lanes migrate — food first."""
from __future__ import annotations

from core.turns.models import TurnSnapshot


class PassthroughSnapshotStage:
    async def run(self, request, execution=None) -> TurnSnapshot:
        event_ids = ()
        try:
            calls = getattr(execution, "calls", ())
            event_ids = tuple(c.event_id for c in calls
                              if getattr(c, "event_id", None) is not None)
        except Exception:
            event_ids = ()
        return TurnSnapshot(turn_id=request.turn_id, execution=execution,
                            ledger_event_ids=event_ids)
