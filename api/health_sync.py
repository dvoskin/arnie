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

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import current_identity
from core.mutation_contract import client_key as _client_key, mutation_turn
from db.database import AsyncSessionLocal
from db.models import BodyMetric
from db.queries import upsert_health_snapshot, resolve_user, _weighin_day_of

CHANNEL = "healthkit"

#: The import routes are Class A but declare `natural` idempotency, not a
#: claim: every sample carries a stable identity the write upserts on (a
#: workout's `source_ref`, a weigh-in's (user, day, source)), and HealthKit
#: redelivers the same samples on every sync — duplicate delivery is the
#: NORMAL case here, not the exceptional one. A claim would deduplicate
#: deliveries the upsert already collapses, while doing nothing about the
#: property that actually matters: a user's delete surviving the next sync.
#: That is `HealthImportTombstone`, and it is what the tests pin.

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class AppleWorkoutBody(BaseModel):
    """One completed HealthKit workout the native client read for the day.
    Mirrors the legacy webhook's `AppleWorkout` field-for-field so both ingest
    paths persist through the same `_process_apple_workouts` (per-day
    replace-on-sync) with one `apple_health` ExerciseEntry contract."""
    # LEGACY (Shortcuts webhook) names.
    name: Optional[str] = None              # user-visible label, e.g. "Running"
    workout_type: Optional[str] = None      # raw HKWorkoutActivityType label; name fallback
    duration_minutes: Optional[float] = None
    active_calories: Optional[float] = None
    distance_km: Optional[float] = None     # display metadata; not used by persist
    start_time: Optional[str] = None        # ISO-8601 start instant; display metadata

    # NATIVE iOS names. `_norm_apple_workout` was always written to accept
    # either sender's vocabulary — `d.get("name") or d.get("workout_type") or
    # d.get("type")`, `start_time or start`, `active_calories or energy_kcal`.
    # It never saw them: this model did not declare the fields, so pydantic
    # dropped them at parse time and `model_dump()` could not emit what the
    # schema had already discarded. A native workout arrived carrying only its
    # duration — no label, no start time, no calories, no uuid.
    #
    # `uuid` is the load-bearing one. It becomes `apple_health:<uuid>`, the
    # import ref that tombstones match on, and it is what lets a workout the
    # user DELETED stay deleted instead of returning on the next sync.
    type: Optional[str] = None              # readable label, e.g. "Walk"
    start: Optional[str] = None             # ISO-8601 start instant
    end: Optional[str] = None
    energy_kcal: Optional[float] = None
    uuid: Optional[str] = None              # HKWorkout UUID — the idempotency ref


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
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
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

        async with mutation_turn(
            db, channel=CHANNEL, command="health_snapshot", user_id=user.id,
            client_key=_client_key(client_request_id),
            dedup=f"snapshot:{snap_date}", claim=False,
        ) as turn:
            return await _write_snapshot(db, user, payload, snap_date, turn)


async def _write_snapshot(db, user, payload, snap_date, turn) -> dict:
    """The committed half, so the handler above reads as identity → write."""
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
        # ONE call, the USER ROW, and no day bucketing here. This site
        # passed `(db, user.id, day, workouts)` — four arguments to a
        # three-argument function, and an int where a User is required
        # (the helper reads `user.timezone`). Every native snapshot
        # carrying a workout raised TypeError, so steps and sleep synced
        # while workouts silently never did.
        #
        # The bucketing loop is gone because `_process_apple_workouts` now
        # owns it: "each workout lands on the LOGGING DAY of its OWN start
        # time (user tz, 4am rollover)". Two implementations of the same
        # rule is how they drift apart.
        from api.app import _process_apple_workouts
        await _process_apple_workouts(db, user, payload.workouts)

    # ONE event per sync, not one per imported row: a 730-sample backfill would
    # otherwise bury a day's real logging under its own bookkeeping. This
    # records that a sync happened, on whose turn, and what it touched — which
    # is the question asked of an import later. Undo declines on this domain
    # (`ledger_undo._invert` has no case for it) and should: the inverse of an
    # import is deleting the user's rows, and a tombstone is how they do that
    # deliberately.
    await turn.audit(db, "created", domain="health_import",
                     payload={"date": str(snap_date), "source": "apple_health",
                              "workouts": len(payload.workouts or [])},
                     surface="healthkit:snapshot")
    turn.note(date=str(snap_date), workouts=len(payload.workouts or []))
    return {"status": "ok", "date": str(snap_date), "turn_id": turn.turn_id}


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
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
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

        # A CLAIM, unlike the snapshot route. The per-day dedup below is a
        # read-then-write with no constraint behind it, so two concurrent
        # deliveries both read an empty `seen_days` and both insert — proven,
        # not theorised (`test_two_concurrent_weight_backfills_...` failed with
        # two rows for one day). The claim closes the common case, a retried
        # sync. See the policy notes for the residual race and its root fix.
        async with mutation_turn(
            db, channel=CHANNEL, command="health_weights", user_id=user.id,
            client_key=_client_key(client_request_id), payload=payload,
            dedup=f"weights:{len(payload.weights)}", claim=True,
        ) as turn:
            if turn.replay:
                return {"status": "ok", "idempotent_replay": True,
                        "ingested": 0, "turn_id": turn.turn_id}
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
                # One row per local day, so a re-sync of the same history adds
                # nothing. This is the natural idempotency the policy declares
                # instead of a claim.
                if day in seen_days:
                    continue
                seen_days.add(day)
                db.add(BodyMetric(user_id=user.id, weight_kg=s.weight_kg,
                                  source="apple_health", timestamp=ts))
                added += 1

            if added:
                await db.commit()
            await turn.complete(db)
            # One event per sync — see `_write_snapshot` for why not one per row.
            await turn.audit(db, "created", domain="health_import",
                             payload={"ingested": added,
                                      "submitted": len(payload.weights),
                                      "source": "apple_health"},
                             surface="healthkit:weights")
            turn.note(ingested=added)
            return {"status": "ok", "ingested": added, "turn_id": turn.turn_id}
