"""Snapshot for DELEGATED turns: wraps whatever the legacy pipeline produced
so the contract exists end to end, without claiming totals it did not read.

Native lanes use stages/snapshot_builder.CommittedSnapshotStage, which reads
committed state back per domain. This one is deleted with the legacy adapter.
"""
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
