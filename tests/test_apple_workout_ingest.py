"""Apple Health workout ingest — normalization + cross-source dedup.

Danny's 2026-07-24 log: a Whoop 25-min Walking (occurred 21:29, correct day)
plus a nameless dateless apple_health 'Workout' 25 min on the WRONG day —
the same physical session, double-counted and mis-dated. These pin the rules
that make that impossible.
"""
from datetime import datetime

from api.app import _is_cross_source_dup, _norm_apple_workout


# ── normalization: both senders' field names land in one shape ───────────────

def test_native_app_fields_survive():
    n = _norm_apple_workout({"type": "Walking", "start": "2026-07-23T21:29:00Z",
                             "end": "2026-07-23T21:54:00Z",
                             "duration_minutes": 25, "energy_kcal": 96,
                             "uuid": "ABC-123"})
    assert n["name"] == "Walking"
    assert n["start_utc"] == datetime(2026, 7, 23, 21, 29)
    assert n["kcal"] == 96
    assert n["ref"] == "apple_health:ABC-123"


def test_shortcut_fields_survive():
    n = _norm_apple_workout({"name": "Running", "workout_type": "HKRunning",
                             "start_time": "2026-07-23T10:00:00+00:00",
                             "duration_minutes": 30, "active_calories": 210})
    assert n["name"] == "Running"
    assert n["kcal"] == 210
    assert n["ref"] == "apple_health:2026-07-23T10:00:00+00:00|30"


def test_no_duration_no_time_is_dropped():
    assert _norm_apple_workout({"type": "Yoga"}) is None


# ── cross-source dedup: one session, one row ─────────────────────────────────

WHOOP_START = datetime(2026, 7, 23, 21, 29)


def test_same_start_same_duration_is_dup():
    assert _is_cross_source_dup(datetime(2026, 7, 23, 21, 30), 25,
                                WHOOP_START, 25.0)


def test_close_start_similar_duration_is_dup():
    assert _is_cross_source_dup(datetime(2026, 7, 23, 21, 45), 28,
                                WHOOP_START, 25.0)


def test_far_apart_starts_are_not_dup():
    assert not _is_cross_source_dup(datetime(2026, 7, 23, 18, 0), 25,
                                    WHOOP_START, 25.0)


def test_overlapping_but_very_different_durations_not_dup():
    # A 5-min cooldown starting near a 60-min session is its own thing.
    assert not _is_cross_source_dup(datetime(2026, 7, 23, 21, 35), 5,
                                    WHOOP_START, 60.0)


def test_timestampless_same_day_same_duration_is_dup():
    # The exact prod pair: apple row had NO start; whoop had one. Falls back
    # to duration identity on the same day.
    assert _is_cross_source_dup(None, 25, WHOOP_START, 25.0)


def test_timestampless_different_duration_not_dup():
    assert not _is_cross_source_dup(None, 45, WHOOP_START, 25.0)
