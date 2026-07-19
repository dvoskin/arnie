"""
Oura v2 sync parsing tests.

Same approach as test_whoop_sync.py: we can't reach the live Oura API from CI,
so we drive the *real* `sync_user_oura` (real DB upsert, real aggregation) and
monkeypatch only the HTTP layer (`_oura_get`) to return synthetic v2 payloads,
then assert what actually landed in HealthSnapshot / ExerciseEntry.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import api.oura as oura
from db.models import ExerciseEntry
from db.queries import get_recent_health_snapshots


def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()


def _readiness(day):
    return [{
        "id": "r1",
        "day": day,
        "score": 82,
        "temperature_deviation": -0.1,
        "contributors": {"hrv_balance": 90, "resting_heart_rate": 80},
    }]


def _daily_sleep(day):
    return [{"id": "ds1", "day": day, "score": 76, "contributors": {}}]


def _sleep(day, *, type_="long_sleep"):
    return [{
        "id": "s1",
        "day": day,
        "type": type_,
        "bedtime_start": f"{day}T23:00:00-05:00",
        "bedtime_end": f"{day}T07:00:00-05:00",
        "time_in_bed": 28_800,             # 8.00 h
        "total_sleep_duration": 26_100,
        "deep_sleep_duration": 7_200,      # 2.00 h
        "rem_sleep_duration": 5_400,       # 1.50 h
        "light_sleep_duration": 13_500,
        "awake_time": 2_700,
        "efficiency": 91,
        "average_hrv": 48,
        "average_heart_rate": 55.0,
        "lowest_heart_rate": 47,
        "average_breath": 13.5,
    }]


def _activity(day):
    return [{
        "id": "a1",
        "day": day,
        "score": 85,
        "active_calories": 620,
        "total_calories": 2900,
        "steps": 11_432,
    }]


def _spo2(day):
    return [{"id": "o1", "day": day, "spo2_percentage": {"average": 97.2}}]


def _workout(day):
    return [{
        "id": "w1",
        "day": day,
        "activity": "strength_training",
        "calories": 350,
        "intensity": "moderate",
        "label": None,
        "source": "manual",
        "start_datetime": f"{day}T17:00:00-05:00",
        "end_datetime": f"{day}T17:45:00-05:00",
    }]


def _patch_endpoints(monkeypatch, payloads):
    """Replace the HTTP layer; route by path so unspecified endpoints return empty."""
    async def fake_get(token, path, params=None):
        return payloads.get(path, [])
    monkeypatch.setattr(oura, "_oura_get", fake_get)


async def _connected_user(make_user):
    """A user with an Oura access token fresh enough to skip the refresh path."""
    return await make_user(
        telegram_id="oura-user",
        oura_access_token="access-tok",
        oura_refresh_token="refresh-tok",
        oura_token_expires_at=datetime.utcnow() + timedelta(hours=12),
    )


async def test_sync_populates_readiness_sleep_activity(make_user, db, monkeypatch):
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/daily_readiness": _readiness(today),
        "/daily_sleep": _daily_sleep(today),
        "/sleep": _sleep(today),
        "/daily_activity": _activity(today),
        "/daily_spo2": _spo2(today),
        "/workout": _workout(today),
    })
    user = await _connected_user(make_user)

    synced = await oura.sync_user_oura(db, user, days=2)
    assert synced >= 1

    snaps = await get_recent_health_snapshots(db, user.id, days=2)
    row = next(s for s in snaps if s.date.isoformat() == today)

    assert row.recovery_score == 82          # readiness → recovery slot
    assert row.sleep_hours == 8.0            # time_in_bed
    assert row.sleep_deep_hours == 2.0
    assert row.sleep_rem_hours == 1.5
    assert row.hrv == 48
    assert row.resting_hr == 47              # nightly lowest HR
    assert row.respiratory_rate == 13.5
    assert row.sleep_efficiency_pct == 91
    assert row.sleep_performance_pct == 76   # daily_sleep score
    assert row.active_calories == 620
    assert row.steps == 11_432
    assert row.spo2_percentage == 97.2
    assert row.source == "oura"


async def test_naps_do_not_overwrite_nightly_sleep(make_user, db, monkeypatch):
    """A nap record must not populate the day's sleep_hours."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/daily_readiness": _readiness(today),   # gives us a row for `today`
        "/sleep": _sleep(today, type_="nap"),
    })
    user = await _connected_user(make_user)

    await oura.sync_user_oura(db, user, days=2)

    snaps = await get_recent_health_snapshots(db, user.id, days=2)
    row = next(s for s in snaps if s.date.isoformat() == today)
    assert row.recovery_score == 82
    assert row.sleep_hours is None


async def test_workouts_autolog_and_dedup(make_user, db, monkeypatch):
    """Workouts land as ExerciseEntry rows keyed by source_ref; re-sync upserts."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {"/workout": _workout(today)})
    user = await _connected_user(make_user)

    await oura.sync_user_oura(db, user, days=2)
    await oura.sync_user_oura(db, user, days=2)  # second sync must not duplicate

    rows = (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.source_ref == "oura:w1")
    )).scalars().all()
    assert len(rows) == 1
    entry = rows[0]
    assert entry.exercise_name == "Strength Training"
    assert entry.duration_minutes == 45
    assert entry.calories_burned_estimate == 350
    assert entry.source_type == "oura"


async def test_endpoint_error_does_not_wipe_fields(make_user, db, monkeypatch):
    """A failed endpoint (None) is 'no data', never a crash or NULL overwrite."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/daily_readiness": _readiness(today),
        "/sleep": None,  # endpoint error
    })
    user = await _connected_user(make_user)

    synced = await oura.sync_user_oura(db, user, days=2)
    assert synced == 1

    snaps = await get_recent_health_snapshots(db, user.id, days=2)
    row = next(s for s in snaps if s.date.isoformat() == today)
    assert row.recovery_score == 82
    assert row.sleep_hours is None
