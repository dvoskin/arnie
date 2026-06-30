"""
Whoop v2 sync parsing tests.

These pin the fix for the regression where connected users got recovery, HRV,
resting HR, and all sleep metrics stored as NULL while strain/avg_hr/calories
synced fine: the daily sync was hitting the deprecated Whoop API **v1**
endpoints, whose /v1/recovery and /v1/activity/sleep stopped returning scored
data after Whoop sunset v1. The sync now calls **v2** and gates the nested
`score` object behind `score_state == "SCORED"`.

We can't reach the live Whoop API from CI, so we drive the *real*
`sync_user_whoop` (real DB upsert, real aggregation) and monkeypatch only the
HTTP layer (`_whoop_get`) to return synthetic v2 payloads, then assert what
actually landed in HealthSnapshot.
"""
import logging
from datetime import datetime, timedelta, timezone, date

import pytest

import api.whoop as whoop
from db.queries import get_recent_health_snapshots


def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()


def _ts(date_iso, hh="08:00:00"):
    return f"{date_iso}T{hh}.000Z"


def _v2_recovery(date_iso, *, score_state="SCORED", scored=True):
    rec = {
        "cycle_id": 100,
        "sleep_id": "11111111-1111-1111-1111-111111111111",
        "user_id": 1,
        "created_at": _ts(date_iso, "08:00:00"),
        "updated_at": _ts(date_iso, "09:00:00"),
        "score_state": score_state,
    }
    if scored:
        rec["score"] = {
            "user_calibrating": False,
            "recovery_score": 66,
            "resting_heart_rate": 52,
            "hrv_rmssd_milli": 45.5,
            "spo2_percentage": 96.0,
            "skin_temp_celsius": 33.2,
        }
    return {"records": [rec]}


def _v2_sleep(date_iso, *, nap=False, score_state="SCORED", scored=True):
    rec = {
        "id": "22222222-2222-2222-2222-222222222222",
        "cycle_id": 100,
        "user_id": 1,
        "created_at": _ts(date_iso, "07:00:00"),
        "start": _ts(date_iso, "23:00:00"),  # exact start doesn't matter; end drives the date
        "end": _ts(date_iso, "07:00:00"),
        "timezone_offset": "-05:00",
        "nap": nap,
        "score_state": score_state,
    }
    if scored:
        rec["score"] = {
            "stage_summary": {
                "total_in_bed_time_milli": 28_800_000,        # 8.00 h
                "total_awake_time_milli": 1_800_000,
                "total_no_data_time_milli": 0,
                "total_light_sleep_time_milli": 14_400_000,   # 4.00 h
                "total_slow_wave_sleep_time_milli": 7_200_000,  # 2.00 h
                "total_rem_sleep_time_milli": 5_400_000,      # 1.50 h
                "sleep_cycle_count": 5,
                "disturbance_count": 3,
            },
            "sleep_needed": {"baseline_milli": 27_000_000},
            "respiratory_rate": 14.5,
            "sleep_performance_percentage": 88,
            "sleep_consistency_percentage": 75,
            "sleep_efficiency_percentage": 93.0,
        }
    return {"records": [rec]}


def _v2_cycle(date_iso, *, score_state="SCORED"):
    return {"records": [{
        "id": 100,
        "user_id": 1,
        "created_at": _ts(date_iso, "08:00:00"),
        "updated_at": _ts(date_iso, "08:30:00"),
        "start": _ts(date_iso, "08:00:00"),
        "end": _ts(date_iso, "08:00:00"),
        "timezone_offset": "-05:00",
        "score_state": score_state,
        "score": {
            "strain": 12.3,
            "kilojoule": 8000.0,
            "average_heart_rate": 70,
            "max_heart_rate": 150,
        },
    }]}


def _v2_workout(date_iso):
    return {"records": [{
        "id": "33333333-3333-3333-3333-333333333333",
        "user_id": 1,
        "created_at": _ts(date_iso, "18:00:00"),
        "start": _ts(date_iso, "17:00:00"),
        "end": _ts(date_iso, "18:00:00"),
        "timezone_offset": "-05:00",
        "sport_id": 45,
        "sport_name": "weightlifting",  # v2 adds the human-readable name
        "score_state": "SCORED",
        "score": {
            "strain": 8.1,
            "average_heart_rate": 120,
            "max_heart_rate": 160,
            "kilojoule": 1500.0,
        },
    }]}


def _patch_endpoints(monkeypatch, payloads):
    """Replace the HTTP layer; route by path so unspecified endpoints return empty."""
    async def fake_get(token, path, params=None):
        return payloads.get(path, {"records": []})
    monkeypatch.setattr(whoop, "_whoop_get", fake_get)


async def _connected_user(make_user):
    """A user with a Whoop access token fresh enough to skip the refresh path."""
    return await make_user(
        telegram_id="whoop-user",
        whoop_access_token="access-tok",
        whoop_refresh_token="refresh-tok",
        whoop_token_expires_at=datetime.utcnow() + timedelta(hours=2),
    )


async def test_v2_sync_populates_recovery_sleep_and_strain(make_user, db, monkeypatch):
    """The core fix: recovery + sleep land alongside strain (no more NULLs)."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/v2/recovery": _v2_recovery(today),
        "/v2/activity/sleep": _v2_sleep(today),
        "/v2/cycle": _v2_cycle(today),
        "/v2/activity/workout": _v2_workout(today),
    })
    user = await _connected_user(make_user)

    synced = await whoop.sync_user_whoop(db, user, days=2)
    assert synced >= 1

    snaps = await get_recent_health_snapshots(db, user.id, days=2)
    row = next(s for s in snaps if s.date.isoformat() == today)

    # Previously NULL — must now be populated.
    assert row.recovery_score == 66
    assert row.hrv == 45.5
    assert row.resting_hr == 52
    assert row.sleep_hours == 8.0
    assert row.sleep_performance_pct == 88
    assert row.respiratory_rate == 14.5

    # Always worked — must still work.
    assert row.strain == 12.3
    assert row.avg_hr == 70
    assert row.active_calories == round(8000.0 * 0.239, 0)  # 1912

    # v2 sport_name flows through, title-cased.
    assert "Weightlifting" in (row.whoop_workouts or "")


async def test_unscored_records_are_gated(make_user, db, monkeypatch):
    """PENDING_SCORE recovery has no `score`; it must not write NULLs over columns."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/v2/recovery": _v2_recovery(today, score_state="PENDING_SCORE", scored=False),
        "/v2/cycle": _v2_cycle(today),
    })
    user = await _connected_user(make_user)

    await whoop.sync_user_whoop(db, user, days=2)

    snaps = await get_recent_health_snapshots(db, user.id, days=2)
    row = next(s for s in snaps if s.date.isoformat() == today)
    assert row.strain == 12.3          # cycle scored → present
    assert row.recovery_score is None  # recovery pending → gated out
    assert row.hrv is None


async def test_naps_do_not_overwrite_nightly_sleep(make_user, db, monkeypatch):
    """A nap record must not populate the day's sleep_hours."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/v2/recovery": _v2_recovery(today),          # gives us a row for `today`
        "/v2/activity/sleep": _v2_sleep(today, nap=True),
    })
    user = await _connected_user(make_user)

    await whoop.sync_user_whoop(db, user, days=2)

    snaps = await get_recent_health_snapshots(db, user.id, days=2)
    row = next(s for s in snaps if s.date.isoformat() == today)
    assert row.recovery_score == 66
    assert row.sleep_hours is None


async def test_strain_without_recovery_logs_warning(make_user, db, monkeypatch, caplog):
    """The regression that started this: strain syncs but recovery/sleep don't.

    Cycle scores, recovery is PENDING, sleep returns no records → we must log a
    WARNING with per-endpoint diagnostics so the failure isn't silent."""
    today = _today_iso()
    _patch_endpoints(monkeypatch, {
        "/v2/recovery": _v2_recovery(today, score_state="PENDING_SCORE", scored=False),
        "/v2/activity/sleep": {"records": []},
        "/v2/cycle": _v2_cycle(today),
    })
    user = await _connected_user(make_user)

    with caplog.at_level(logging.WARNING, logger="api.whoop"):
        await whoop.sync_user_whoop(db, user, days=2)

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("NO recovery and NO sleep" in m for m in warnings), warnings
    msg = next(m for m in warnings if "NO recovery and NO sleep" in m)
    assert "recovery=[1 record(s), 0 scored]" in msg
    assert "sleep=[0 record(s), 0 scored]" in msg


def test_workout_logging_day_uses_local_zone():
    """A WHOOP UTC start converts to the user's LOCAL logging day before bucketing.
    Regression: Danny's 8:10pm EDT walk (00:10 UTC next day) showed up tomorrow."""
    from api.whoop import _workout_logging_day
    # 00:10 UTC == 8:10pm EDT the prior day → local day is the prior day
    assert _workout_logging_day("2026-06-30T00:10:00.790Z", "America/New_York") == date(2026, 6, 29)
    # afternoon, same UTC day either way
    assert _workout_logging_day("2026-06-29T21:48:00Z", "America/New_York") == date(2026, 6, 29)
    # UTC user is unaffected; missing/garbage start → None
    assert _workout_logging_day("2026-06-30T00:10:00Z", "UTC") == date(2026, 6, 30)
    assert _workout_logging_day("", "America/New_York") is None
    assert _workout_logging_day("not-a-date", "America/New_York") is None


@pytest.mark.asyncio
async def test_evening_workout_buckets_to_local_day(make_user, db, monkeypatch):
    """End-to-end: an evening WHOOP workout lands on the user's local logging day,
    not the next UTC day. The exercise entry's daily_log carries the LOCAL date."""
    from sqlalchemy import select
    from db.models import DailyLog, ExerciseEntry
    user = await make_user(
        telegram_id="whoop-tz", timezone="America/New_York",
        whoop_access_token="t", whoop_refresh_token="r",
        whoop_token_expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    # 02:30 UTC Jan 15 == 9:30pm EST Jan 14 → must bucket to Jan 14, not Jan 15.
    wo = _v2_workout("2026-01-15")
    wo["records"][0]["start"] = "2026-01-15T02:30:00.000Z"
    wo["records"][0]["end"] = "2026-01-15T03:00:00.000Z"
    _patch_endpoints(monkeypatch, {"/v2/activity/workout": wo})
    await whoop.sync_user_whoop(db, user, days=2)

    log_dates = (await db.execute(
        select(DailyLog.date)
        .join(ExerciseEntry, ExerciseEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user.id)
    )).scalars().all()
    assert date(2026, 1, 14) in log_dates
    assert date(2026, 1, 15) not in log_dates
