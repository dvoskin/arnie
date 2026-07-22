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
from datetime import date as _date, datetime as _datetime, timezone as _timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.models import BodyMetric
from db.queries import upsert_health_snapshot, resolve_user, _weighin_day_of

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class AppleWorkoutBody(BaseModel):
    """One completed HealthKit workout the native client read for the day.
    Mirrors the legacy webhook's `AppleWorkout` field-for-field so both ingest
    paths persist through the same `_process_apple_workouts` (per-day
    replace-on-sync) with one `apple_health` ExerciseEntry contract."""
    name: Optional[str] = None              # user-visible label, e.g. "Running"
    workout_type: Optional[str] = None      # raw HKWorkoutActivityType label; name fallback
    duration_minutes: Optional[float] = None
    active_calories: Optional[float] = None
    distance_km: Optional[float] = None     # display metadata; not used by persist
    start_time: Optional[str] = None        # ISO-8601 start instant; display metadata


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
    workouts: Optional[List[AppleWorkoutBody]] = None  # completed Apple Watch/HealthKit workouts


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

        data = payload.model_dump(exclude={"date", "workouts"}, exclude_none=True)
        data.setdefault("source", "apple_health")
        await upsert_health_snapshot(db, user.id, snap_date, **data)

        if payload.workouts:
            # Persist via the legacy webhook's per-day replace-on-sync (one
            # ExerciseEntry contract for native + Shortcuts; deletes the day's
            # apple_health entries, re-inserts the batch — idempotent). Lazy
            # import: api.app imports this router at startup, so a module-level
            # import would be circular; by request time api.app is fully loaded.
            #
            # TZ CORRECTNESS: bucket each workout under ITS OWN local day (user
            # timezone), NOT the request's UTC date. iOS reads workouts in the
            # DEVICE-LOCAL day window and re-sends the full set each sync, so a
            # UTC snap_date would file an evening-local workout on the next UTC
            # day AND re-insert it next sync — double-counted on two calendar
            # days (the review's confirmed bug). Keying on the workout's local
            # start day keeps replace-on-sync idempotent across the UTC boundary.
            from api.app import _process_apple_workouts
            tz = getattr(user, "timezone", None) or "UTC"
            for _wday, _ws in _bucket_workouts_by_local_day(
                    payload.workouts, tz, snap_date).items():
                await _process_apple_workouts(db, user.id, _wday, _ws)

        return {"status": "ok", "date": str(snap_date)}


def _parse_instant(s: str) -> Optional[_datetime]:
    """Parse an ISO-8601 instant (the HealthKit sample endDate the client sends)
    into a naive-UTC datetime, matching how BodyMetric.timestamp is stored."""
    try:
        dt = _datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(_timezone.utc).replace(tzinfo=None)
    return dt


def _bucket_workouts_by_local_day(workouts, tz: str, fallback_day):
    """Group workouts by the LOCAL day (user `tz`) of each one's start_time, so
    replace-on-sync keys on the same day the device windowed them by — not the
    request's UTC date. Workouts with no parseable start_time fall back to
    `fallback_day` (the snapshot day). Returns {date: [workout, ...]}."""
    by_day: dict = {}
    for w in workouts or []:
        st = getattr(w, "start_time", None)
        ts = _parse_instant(st) if st else None
        day = _weighin_day_of(ts, tz) if ts else fallback_day
        by_day.setdefault(day, []).append(w)
    return by_day


class WeightSample(BaseModel):
    date: str                                   # ISO-8601 instant (HK sample endDate)
    weight_kg: float = Field(gt=20, lt=400)


class WeightBackfillBody(BaseModel):
    """Apple Health body-weight history — one sample per day, oldest-first.
    Bounded so a runaway client can't submit an unbounded batch."""
    weights: List[WeightSample] = Field(default_factory=list, max_length=730)


@router.post("/weights")
async def backfill_weights(
    payload: WeightBackfillBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Bulk-ingest Apple Health weight history as `apple_health` weigh-ins so the
    user's logging history + weight trend fill in from their existing data. ONE
    row per local day (skipping days already covered by an apple_health row, so
    re-syncs are idempotent), committed in a single transaction. Historical only:
    never moves users.current_weight_kg — today's live reading owns the headline.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        tz = getattr(user, "timezone", None) or "UTC"

        existing = (await db.execute(
            select(BodyMetric.timestamp).where(
                BodyMetric.user_id == user.id,
                BodyMetric.source == "apple_health",
            )
        )).scalars().all()
        seen_days = {_weighin_day_of(t, tz) for t in existing if t is not None}

        added = 0
        for s in payload.weights:
            ts = _parse_instant(s.date)
            if ts is None:
                continue
            day = _weighin_day_of(ts, tz)
            if day in seen_days:
                continue
            seen_days.add(day)
            db.add(BodyMetric(user_id=user.id, weight_kg=s.weight_kg,
                              source="apple_health", timestamp=ts))
            added += 1

        if added:
            await db.commit()
        return {"status": "ok", "ingested": added}
