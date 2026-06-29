"""
Muscle-group recovery endpoint — the JSON behind the Coach page recovery board.

GET /api/v1/recovery returns, per muscle group, a readiness status
(ready / recovering / strained / just_hit), a recovery %, when it was last
trained, and the movements that drove that status. Derived from the user's
recently logged training + their latest wearable snapshot by the pure model in
`skills/fitness/muscle_recovery.compute_recovery`.

Follows the same identity → resolve_user → fetch pattern as the other /api/v1
dashboard endpoints (see api/dashboard_api.py).
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from db.database import AsyncSessionLocal
from db.queries import (
    resolve_user,
    get_recent_logs,
    get_recent_health_snapshots,
)
from api.auth import current_identity
from skills.fitness.muscle_recovery import compute_recovery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["recovery"])


def _entry_to_dict(e) -> dict:
    return {
        "name": e.exercise_name,
        "sets": e.sets,
        "reps": e.reps,
        "weight": e.weight,
        "weights": e.weights,
        "rir": e.rir,
        "duration_minutes": e.duration_minutes,
        "cardio_type": e.cardio_type,
        "avg_hr": e.avg_hr,
        "occurred_at": e.occurred_at,
        "timestamp": e.timestamp,
    }


def _latest_snapshot(snaps) -> dict | None:
    """Most recent wearable snapshot — prefer one carrying a recovery score, else
    the most recent with any signal (sleep). Mirrors the Daily-Log picker so a
    passive Apple Health row (sleep but no recovery) doesn't bury the Whoop score
    that's sitting one row behind it."""
    pick = None
    for s in snaps:  # get_recent_health_snapshots returns newest-first
        if s.recovery_score is not None:
            pick = s
            break
        if pick is None and s.sleep_hours is not None:
            pick = s   # remember newest sleep-only row, keep scanning for recovery
    if pick is None:
        return None
    return {
        "recovery_score": pick.recovery_score,
        "strain": pick.strain,
        "sleep_hours": pick.sleep_hours,
    }


@router.get("/recovery")
async def get_recovery(identity: str = Depends(current_identity)):
    """Per-muscle recovery board. 10-day training lookback, latest wearable
    snapshot for the whole-body modifier. Empty (all `ready`) for a user who
    hasn't logged training yet."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        logs = await get_recent_logs(db, user.id, days=10)
        snaps = await get_recent_health_snapshots(db, user.id, days=4)
        profile = {"age": user.age}

    entries: list[dict] = []
    for log in logs:
        for e in (log.exercise_entries or []):
            entries.append(_entry_to_dict(e))

    snapshot = _latest_snapshot(snaps)
    # Entry timestamps are naive UTC; decay against UTC now.
    return compute_recovery(entries, snapshot, profile, datetime.utcnow())
