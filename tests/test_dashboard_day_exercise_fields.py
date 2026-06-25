"""Regression: the /api/v1/day exercise serializer must preserve the full entry
shape the iOS row needs — especially `timestamp` (without it, workouts render
untimed + clustered at the end of the timeline) and `weights` (per-set load)."""
from api.dashboard_api import _normalize_exercise

_RAW = {
    "id": 7, "name": "Incline Bench", "sets": 1, "reps": "10",
    "weight": 205.0, "weights": "205", "duration_minutes": None,
    "is_cardio": False, "cardio_type": None, "rir": 1,
    "calories_burned": None, "notes": "strong",
    "timestamp": "2026-06-24T23:01:30.015339", "source": None,
}


def test_normalize_exercise_keeps_timestamp():
    out = _normalize_exercise(_RAW)
    assert out["timestamp"] == "2026-06-24T23:01:30.015339"


def test_normalize_exercise_keeps_full_shape():
    out = _normalize_exercise(_RAW)
    for key in ("weights", "rir", "calories_burned", "notes", "source", "timestamp"):
        assert key in out, f"_normalize_exercise dropped {key}"
    assert out["weights"] == "205"
    assert out["rir"] == 1


def test_normalize_exercise_cardio_timestamp():
    raw = {"id": 9, "name": "Run", "is_cardio": True, "cardio_type": "run",
           "duration_minutes": 30.0, "calories_burned": 300,
           "timestamp": "2026-06-24T14:08:00.540000"}
    out = _normalize_exercise(raw)
    assert out["timestamp"] == "2026-06-24T14:08:00.540000"
    assert out["duration_minutes"] == 30
