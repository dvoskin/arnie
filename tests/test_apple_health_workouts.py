"""
Apple Health workout ingestion tests — the NATIVE iOS snapshot path.

The native iOS client reads completed `HKWorkout`s and sends them in the
`/api/v1/health/snapshot` body as `workouts`. The endpoint hands them to the
same `_process_apple_workouts` the legacy Shortcuts webhook uses — each workout
lands on the logging day of its OWN start time (user tz + 4am rollover),
per-day replace-on-sync into `apple_health` ExerciseEntry rows. These pin:

  1. Workouts land as apple_health exercise entries with the right fields,
     on the day of their own start time.
  2. Re-syncing the same day REPLACES (never duplicates) — the batch is the
     day's source of truth.
  3. The endpoint calls _process_apple_workouts with its CURRENT signature
     (db, user, workouts) — the 2026-07-24 regression sent (db, user.id, day,
     workouts) and 500'd every native sync that included a workout.
  4. The native body model accepts BOTH senders' field names (Shortcut's
     name/start_time/active_calories AND the app's type/start/energy_kcal/uuid)
     and excludes workouts from the snapshot upsert kwargs.
"""
from datetime import date

from sqlalchemy import select

from api.app import _process_apple_workouts
from api.health_sync import AppleWorkoutBody, HealthSnapshotBody
from db.models import ExerciseEntry
from db.queries import get_or_create_log_for_date, _user_today


async def _entries(db, user_id, d):
    log = await get_or_create_log_for_date(db, user_id, d)
    return (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.daily_log_id == log.id)
    )).scalars().all()


async def test_apple_workouts_persist_as_exercise_entries(make_user, db):
    u = await make_user(telegram_id="applewk-1", name="Wrist")
    workouts = [
        AppleWorkoutBody(name="Running", duration_minutes=32.0,
                         active_calories=310.0, distance_km=5.1,
                         start_time="2026-07-22T07:00:00Z"),
        AppleWorkoutBody(name="Strength Training", duration_minutes=45.0,
                         active_calories=220.0, start_time="2026-07-22T18:00:00Z"),
    ]

    await _process_apple_workouts(db, u, workouts)

    # Each workout lands on the logging day of its OWN start (UTC user here).
    entries = await _entries(db, u.id, date(2026, 7, 22))
    assert len(entries) == 2
    by_name = {e.exercise_name: e for e in entries}
    assert set(by_name) == {"Running", "Strength Training"}
    run = by_name["Running"]
    assert run.source_type == "apple_health"
    assert run.cardio_type == "apple_health"          # marks the day cardio_completed
    assert run.duration_minutes == 32.0
    assert run.calories_burned_estimate == 310.0


async def test_apple_workouts_replace_on_resync(make_user, db):
    """A second sync for the same day replaces the first — no double-count."""
    u = await make_user(telegram_id="applewk-2", name="Wrist")
    today = _user_today("UTC")   # start-less workouts land on the user's logging day

    await _process_apple_workouts(db, u, [
        AppleWorkoutBody(name="Running", duration_minutes=30.0, active_calories=300.0),
        AppleWorkoutBody(name="Yoga", duration_minutes=20.0, active_calories=60.0),
    ])
    assert len(await _entries(db, u.id, today)) == 2

    # Re-sync the SAME day with a corrected single workout (watch finished it).
    await _process_apple_workouts(db, u, [
        AppleWorkoutBody(name="Running", duration_minutes=42.0, active_calories=430.0),
    ])
    entries = await _entries(db, u.id, today)
    assert len(entries) == 1                            # replaced, not appended
    assert entries[0].exercise_name == "Running"
    assert entries[0].duration_minutes == 42.0
    assert entries[0].calories_burned_estimate == 430.0


async def test_apple_workouts_name_falls_back_to_workout_type(make_user, db):
    u = await make_user(telegram_id="applewk-3", name="Wrist")
    await _process_apple_workouts(db, u, [
        AppleWorkoutBody(workout_type="hk_type_37", duration_minutes=15.0),
    ])
    entries = await _entries(db, u.id, _user_today("UTC"))
    assert len(entries) == 1
    assert entries[0].exercise_name == "hk_type_37"     # name absent → workout_type


async def test_native_snapshot_call_matches_ingest_signature(make_user, db):
    """The endpoint must call _process_apple_workouts(db, user, workouts).
    The old call passed (db, user.id, day, [w]) — TypeError, HTTP 500, and the
    user 'still not seeing Apple Health workouts' after the ingest rewrite."""
    u = await make_user(telegram_id="applewk-4", name="Wrist",
                        timezone="America/New_York")
    body = HealthSnapshotBody(
        workouts=[{"type": "Walking", "start": "2026-07-23T00:00:00Z",
                   "end": "2026-07-23T00:25:00Z", "duration_minutes": 25,
                   "energy_kcal": 96, "uuid": "JUSTIN-1"}],
    )
    # Same shape post_snapshot uses — user object, no day arg.
    await _process_apple_workouts(db, u, body.workouts)

    # 8pm-ET start (= 00:00 UTC Jul 23) buckets to the ET day, Jul 22.
    entries = await _entries(db, u.id, date(2026, 7, 22))
    assert len(entries) == 1
    e = entries[0]
    assert e.exercise_name == "Walking"                 # native `type` survives
    assert e.calories_burned_estimate == 96             # native `energy_kcal` survives
    assert e.source_ref == "apple_health:JUSTIN-1"      # uuid → idempotency ref


def test_native_body_parses_workouts_and_excludes_from_snapshot_kwargs():
    """The snapshot upsert must never receive `workouts` as a kwarg, and BOTH
    senders' field names must survive AppleWorkoutBody parsing — the app's
    type/start/energy_kcal/uuid were previously dropped silently."""
    body = HealthSnapshotBody(
        steps=8000,
        workouts=[{"name": "Cycling", "duration_minutes": 50, "active_calories": 400,
                   "distance_km": 18.2, "start_time": "2026-07-22T06:00:00Z"},
                  {"type": "Walking", "start": "2026-07-22T20:00:00Z",
                   "end": "2026-07-22T20:25:00Z", "duration_minutes": 25,
                   "energy_kcal": 96, "uuid": "ABC-123"}],
    )
    data = body.model_dump(exclude={"date", "workouts"}, exclude_none=True)
    assert "workouts" not in data and data["steps"] == 8000

    shortcut = body.workouts[0].model_dump(exclude_none=True)
    assert shortcut["name"] == "Cycling"
    assert shortcut["active_calories"] == 400.0
    assert shortcut["duration_minutes"] == 50.0

    native = body.workouts[1].model_dump(exclude_none=True)
    assert native["type"] == "Walking"
    assert native["energy_kcal"] == 96.0
    assert native["uuid"] == "ABC-123"
    assert native["start"] == "2026-07-22T20:00:00Z"
