"""The workout the iOS app sends is the workout the server stores.

Two defects, both on the native `/api/v1/health/snapshot` path, both invisible
because the request that carried them also carried steps and sleep.

FIRST, the call was wrong. `api/health_sync` invoked
`_process_apple_workouts(db, user.id, day, workouts)` — four arguments against
a three-argument function, and an int where a User row is required (the helper
reads `user.timezone`). Every native snapshot containing a workout raised
TypeError. Steps and sleep landed; workouts never did. A partial sync is worse
than a failed one: the coaching looks confidently wrong rather than absent.

SECOND, the schema discarded the payload. `_norm_apple_workout` was written to
accept either sender's vocabulary — `d.get("name") or d.get("workout_type") or
d.get("type")`, `start_time or start`, `active_calories or energy_kcal` — but
`AppleWorkoutBody` declared only the legacy Shortcuts names, so pydantic
dropped `type`, `start`, `energy_kcal` and `uuid` at parse time. `model_dump()`
cannot emit what the schema already threw away, so a native workout reached the
normalizer holding its duration and nothing else.

The JSON below is copied from the iOS client's own encoder
(`HealthSnapshot.WorkoutSample`), not invented for the test — a fixture that
agrees with the server rather than the client would have passed throughout.
"""
import pytest

from api.health_sync import AppleWorkoutBody

#: EXACTLY what `HealthSnapshot.WorkoutSample` encodes. Its CodingKeys are
#: `type, start, end, uuid`, `durationMinutes -> duration_minutes`,
#: `energyKcal -> energy_kcal`.
IOS_WORKOUT = {
    "type": "Walk",
    "start": "2026-07-31T13:05:00Z",
    "end": "2026-07-31T13:47:00Z",
    "duration_minutes": 42,
    "energy_kcal": 210,
    "uuid": "8B0F0F5E-1C2D-4A9B-9E77-2A1F3C4D5E6F",
}


# ── the schema keeps what the client sent ────────────────────────────────────


def test_the_schema_accepts_the_fields_ios_actually_sends():
    body = AppleWorkoutBody(**IOS_WORKOUT)
    assert body.type == "Walk"
    assert body.start == "2026-07-31T13:05:00Z"
    assert body.energy_kcal == 210
    assert body.uuid == IOS_WORKOUT["uuid"]


def test_the_dump_still_carries_them_to_the_normalizer():
    """`_process_apple_workouts` normalizes `w.model_dump(exclude_none=True)`.
    Fields the schema dropped can never appear there, which is precisely how
    they were lost."""
    dumped = AppleWorkoutBody(**IOS_WORKOUT).model_dump(exclude_none=True)
    for key in ("type", "start", "energy_kcal", "uuid"):
        assert key in dumped, f"{key} was discarded before the normalizer saw it"


def test_the_normalizer_resolves_the_native_shape():
    """The normalizer always knew both vocabularies. This proves the schema is
    now feeding it, rather than re-testing the normalizer."""
    from api.app import _norm_apple_workout

    n = _norm_apple_workout(
        AppleWorkoutBody(**IOS_WORKOUT).model_dump(exclude_none=True))

    assert n is not None
    assert n["name"] == "Walk", "the label was lost — every workout became 'Workout'"
    assert n["duration"] == 42
    assert n["kcal"] == 210
    assert n["start_utc"] is not None, "no start time means the wrong logging day"
    assert n["ref"] == f"apple_health:{IOS_WORKOUT['uuid']}", (
        "without the uuid ref a workout the user DELETED returns on every sync"
    )


def test_the_legacy_shortcuts_shape_still_works():
    """The Shortcuts webhook sends the other vocabulary and must keep working —
    this is an addition, not a migration."""
    from api.app import _norm_apple_workout

    n = _norm_apple_workout(AppleWorkoutBody(
        name="Running", duration_minutes=30, active_calories=300,
        start_time="2026-07-31T13:05:00Z").model_dump(exclude_none=True))

    assert n["name"] == "Running"
    assert n["kcal"] == 300
    assert n["start_utc"] is not None


# ── the call itself ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_snapshot_endpoint_stores_the_workout(engine, make_user,
                                                        monkeypatch):
    """The TypeError, pinned end to end.

    The endpoint is driven with the real iOS body. Before the fix this raised
    `TypeError: _process_apple_workouts() takes 3 positional arguments but 4
    were given` — while steps still landed, which is what made it a silent
    partial sync rather than a visible failure.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import api.health_sync as HS
    from db.models import ExerciseEntry

    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(HS, "AsyncSessionLocal", factory)
    async with factory() as setup:
        setup.add(_user_row())
        await setup.commit()

    body = HS.HealthSnapshotBody(steps=4000,
                                 workouts=[AppleWorkoutBody(**IOS_WORKOUT)])
    resp = await HS.post_snapshot(body, identity="ios:hk-endpoint")
    assert resp["status"] == "ok"

    async with factory() as check:
        rows = (await check.execute(select(ExerciseEntry))).scalars().all()
    assert len(rows) == 1, (
        "the workout never landed — steps synced and exercise silently did not"
    )
    assert "walk" in (rows[0].exercise_name or "").lower()


def _user_row():
    from db.models import User
    return User(telegram_id="ios:hk-endpoint", timezone="America/New_York")
