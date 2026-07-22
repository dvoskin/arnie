"""
Apple Health workout ingestion tests.

The native iOS client reads completed `HKWorkout`s and sends them in the
`/api/v1/health/snapshot` body as `workouts`. The endpoint hands them to the
same `_process_apple_workouts` the legacy Shortcuts webhook uses — per-day
replace-on-sync into `apple_health` ExerciseEntry rows. These pin:

  1. Workouts land as apple_health exercise entries with the right fields.
  2. Re-syncing the same day REPLACES (never duplicates) — the batch is the
     day's source of truth.
  3. The native body model parses workouts and excludes them from the snapshot
     upsert kwargs (so a workout never leaks into upsert_health_snapshot()).
"""
from datetime import date

from sqlalchemy import select

from api.app import _process_apple_workouts
from api.health_sync import (
    AppleWorkoutBody, HealthSnapshotBody, _bucket_workouts_by_local_day,
)
from db.models import ExerciseEntry
from db.queries import get_or_create_log_for_date


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

    await _process_apple_workouts(db, u.id, date.today(), workouts)

    entries = await _entries(db, u.id, date.today())
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

    await _process_apple_workouts(db, u.id, date.today(), [
        AppleWorkoutBody(name="Running", duration_minutes=30.0, active_calories=300.0),
        AppleWorkoutBody(name="Yoga", duration_minutes=20.0, active_calories=60.0),
    ])
    assert len(await _entries(db, u.id, date.today())) == 2

    # Re-sync the SAME day with a corrected single workout (watch finished it).
    await _process_apple_workouts(db, u.id, date.today(), [
        AppleWorkoutBody(name="Running", duration_minutes=42.0, active_calories=430.0),
    ])
    entries = await _entries(db, u.id, date.today())
    assert len(entries) == 1                            # replaced, not appended
    assert entries[0].exercise_name == "Running"
    assert entries[0].duration_minutes == 42.0
    assert entries[0].calories_burned_estimate == 430.0


async def test_apple_workouts_name_falls_back_to_workout_type(make_user, db):
    u = await make_user(telegram_id="applewk-3", name="Wrist")
    await _process_apple_workouts(db, u.id, date.today(), [
        AppleWorkoutBody(workout_type="hk_type_37", duration_minutes=15.0),
    ])
    entries = await _entries(db, u.id, date.today())
    assert len(entries) == 1
    assert entries[0].exercise_name == "hk_type_37"     # name absent → workout_type


def test_workouts_bucket_by_local_day_not_utc():
    """An 8pm-ET workout (= 00:00 UTC next day) must bucket to the ET calendar
    day, NOT the UTC day — the fix for the replace-on-sync double-count."""
    from datetime import date
    w = AppleWorkoutBody(name="Racquetball", start_time="2026-07-23T00:00:00Z")
    buckets = _bucket_workouts_by_local_day([w], "America/New_York", date(2026, 7, 23))
    assert list(buckets.keys()) == [date(2026, 7, 22)]      # ET day, not UTC Jul 23


def test_workouts_missing_start_time_fall_back_to_snapshot_day():
    from datetime import date
    fb = date(2026, 7, 22)
    buckets = _bucket_workouts_by_local_day([AppleWorkoutBody(name="Workout")], "UTC", fb)
    assert list(buckets.keys()) == [fb]


def test_native_body_parses_workouts_and_excludes_from_snapshot_kwargs():
    """The snapshot upsert must never receive `workouts` as a kwarg, and the
    parsed workout must expose the snake_case keys _process_apple_workouts reads."""
    body = HealthSnapshotBody(
        steps=8000,
        workouts=[{"name": "Cycling", "duration_minutes": 50, "active_calories": 400,
                   "distance_km": 18.2, "start_time": "2026-07-22T06:00:00Z"}],
    )
    data = body.model_dump(exclude={"date", "workouts"}, exclude_none=True)
    assert "workouts" not in data and data["steps"] == 8000

    w = body.workouts[0].model_dump(exclude_none=True)
    assert w["name"] == "Cycling"
    assert w["active_calories"] == 400.0
    assert w["duration_minutes"] == 50.0
