"""
Bearer-auth health-snapshot ingest endpoint for the iOS native app.

The legacy `POST /health/apple?token=...` webhook accepts permissive iOS
Shortcuts payloads (newline-separated strings, missing fields, mixed types). The
iOS native client sends well-typed JSON via `HealthSnapshot.Encodable`, so this
endpoint takes a strict Pydantic body and skips the Shortcuts compatibility
layer entirely. Both paths converge on the same `health_snapshots` row via
`upsert_health_snapshot`.

Stays small on purpose: every device-side concern (which types to read, how
often to sync, background delivery) lives in the iOS HealthKitReader /
HealthSyncService. This endpoint just accepts whatever the client sends and
persists today's row.
"""
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import upsert_health_snapshot, resolve_user

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class HealthSnapshotBody(BaseModel):
    """The native iOS client's health snapshot body. Every field optional —
    the client populates only what HealthKit returned for the user."""
    date: Optional[str] = None              # YYYY-MM-DD; defaults to today server-side
    steps: Optional[int] = None
    active_calories: Optional[float] = None
    resting_calories: Optional[float] = None
    sleep_hours: Optional[float] = None
    sleep_deep_hours: Optional[float] = None
    sleep_rem_hours: Optional[float] = None
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hrv: Optional[float] = None
    stand_hours: Optional[int] = None
    exercise_minutes: Optional[int] = None


@router.post("/snapshot")
async def post_snapshot(
    payload: HealthSnapshotBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Upsert today's (or `payload.date`'s) HealthKit summary for the caller."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        snap_date = _date.today()
        if payload.date:
            try:
                snap_date = _date.fromisoformat(payload.date)
            except ValueError:
                raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

        data = payload.model_dump(exclude={"date"}, exclude_none=True)
        data.setdefault("source", "apple_health")
        await upsert_health_snapshot(db, user.id, snap_date, **data)

        return {"status": "ok", "date": str(snap_date)}
