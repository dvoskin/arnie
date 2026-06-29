"""Unit tests for the muscle-group recovery model (skills/fitness/muscle_recovery).

Deterministic, pure — no DB, no API. Asserts the status transitions, cardio
HR-zone behavior, unknown-exercise fallback, and the wearable modifier.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from skills.fitness.muscle_recovery import compute_recovery, MUSCLES


NOW = datetime(2026, 6, 28, 18, 0, 0)


def _by_id(result):
    return {m["id"]: m for m in result["muscles"]}


def _squat(hours_ago: float):
    """A hard barbell squat session some hours in the past."""
    return {
        "name": "Back Squat",
        "sets": 4,
        "reps": "5,5,5,5",
        "weight": 140.0,   # kg
        "rir": 1,
        "occurred_at": NOW - timedelta(hours=hours_ago),
    }


def test_fresh_heavy_squat_just_hit():
    res = compute_recovery([_squat(2)], None, {"age": 33}, NOW)
    quads = _by_id(res)["quads"]
    assert quads["status"] == "just_hit"
    assert quads["recovery_pct"] < 40
    # secondary movers picked up too
    assert _by_id(res)["glutes"]["fatigue"] > 0
    # the movement is attributed back to the muscle
    assert any(m["name"] == "Back Squat" for m in quads["movements"])


def test_squat_recovering_after_two_days():
    res = compute_recovery([_squat(48)], None, {"age": 33}, NOW)
    quads = _by_id(res)["quads"]
    assert quads["status"] in ("recovering", "strained")
    assert "ago" in quads["last_trained_label"]


def test_squat_ready_after_four_days():
    res = compute_recovery([_squat(96)], None, {"age": 33}, NOW)
    quads = _by_id(res)["quads"]
    assert quads["status"] == "ready"
    assert quads["recovery_pct"] >= 78


def _overhead_press(hours_ago: float):
    """A hard overhead press session (shoulders — a SMALL muscle group)."""
    return {
        "name": "Overhead Press",
        "sets": 5, "reps": "8,8,8,8,8", "weight": 55.0, "rir": 1,
        "occurred_at": NOW - timedelta(hours=hours_ago),
    }


def _curl(hours_ago: float):
    """A hard biceps curl session (arms — a SMALL muscle group)."""
    return {
        "name": "Barbell Curl",
        "sets": 5, "reps": "10,10,10,10,10", "weight": 40.0, "rir": 0,
        "occurred_at": NOW - timedelta(hours=hours_ago),
    }


def test_small_muscle_hit_3d_ago_reads_more_recovered_than_arms_1d_ago():
    """Danny's report: shoulders (trained 3 days ago) showed LESS recovered than
    arms (trained yesterday) — backwards. A small muscle 72 h out must read more
    recovered than one 24 h out. Regression on the tau recalibration."""
    res = compute_recovery([_overhead_press(72), _curl(24)], None, {"age": 33}, NOW)
    shoulders = _by_id(res)["shoulders"]
    biceps = _by_id(res)["biceps"]
    assert shoulders["recovery_pct"] > biceps["recovery_pct"]
    # a small muscle 3 days out is essentially recovered
    assert shoulders["recovery_pct"] >= 80
    assert shoulders["status"] == "ready"


def test_shoulders_recover_inside_the_small_muscle_window():
    """Shoulders are a small muscle (~24-48 h window), not a 54 h slow-recoverer —
    ready by ~48 h after a hard session."""
    res = compute_recovery([_overhead_press(48)], None, {"age": 33}, NOW)
    assert _by_id(res)["shoulders"]["status"] == "ready"


def test_untrained_muscle_is_ready():
    res = compute_recovery([_squat(2)], None, {"age": 33}, NOW)
    biceps = _by_id(res)["biceps"]
    assert biceps["status"] == "ready"
    assert biceps["recovery_pct"] == 100
    assert biceps["last_trained_label"] == "—"


def test_no_training_everything_ready():
    res = compute_recovery([], None, {"age": 33}, NOW)
    assert all(m["status"] == "ready" for m in res["muscles"])
    assert res["summary"]["ready"]
    assert "recovered" in res["summary"]["headline"].lower()


def test_zone4_run_loads_legs_and_systemic():
    run = {
        "name": "Running",
        "cardio_type": "run",
        "duration_minutes": 45,
        "avg_hr": 168,   # ~90% of max for a 33yo -> Zone 4
        "occurred_at": NOW - timedelta(hours=3),
    }
    res = compute_recovery([run], None, {"age": 33}, NOW)
    by = _by_id(res)
    # legs take the brunt
    assert by["calves"]["fatigue"] > by["chest"]["fatigue"]
    assert by["quads"]["fatigue"] > 0
    # systemic full-body effect: even chest registers something
    assert by["chest"]["fatigue"] > 0


def test_easy_walk_is_minimal():
    walk = {
        "name": "Walking",
        "cardio_type": "walk",
        "duration_minutes": 30,
        "avg_hr": 95,    # easy, Zone 1
        "occurred_at": NOW - timedelta(hours=2),
    }
    res = compute_recovery([walk], None, {"age": 33}, NOW)
    by = _by_id(res)
    # a walk never fries anything
    assert all(m["status"] in ("ready", "recovering") for m in res["muscles"])
    assert by["calves"]["fatigue"] < 0.5


def test_zone_intensity_scales_load():
    """Same run, harder HR -> more leg fatigue."""
    def run(hr):
        return [{
            "name": "Running", "cardio_type": "run", "duration_minutes": 40,
            "avg_hr": hr, "occurred_at": NOW - timedelta(hours=2),
        }]
    easy = _by_id(compute_recovery(run(110), None, {"age": 33}, NOW))["quads"]["fatigue"]
    hard = _by_id(compute_recovery(run(175), None, {"age": 33}, NOW))["quads"]["fatigue"]
    assert hard > easy


def test_unknown_exercise_falls_back_to_primary():
    # not in INVOLVEMENT, but catalog knows Leg Extension -> quads
    res = compute_recovery([{
        "name": "leg extensions", "sets": 4, "reps": "12", "weight": 60.0,
        "rir": 0, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    assert _by_id(res)["quads"]["fatigue"] > 0


def test_fully_unknown_exercise_does_not_crash():
    res = compute_recovery([{
        "name": "Zercher Zottman Thing", "sets": 3, "reps": "10", "weight": 20.0,
        "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    # no muscle attribution, but a valid full board comes back
    assert len(res["muscles"]) == len(MUSCLES)


def test_low_recovery_lingers_longer():
    """Same training, but poor WHOOP recovery keeps fatigue higher."""
    entry = [_squat(40)]
    good = compute_recovery(entry, {"recovery_score": 95, "sleep_hours": 8}, {"age": 33}, NOW)
    poor = compute_recovery(entry, {"recovery_score": 25, "sleep_hours": 5}, {"age": 33}, NOW)
    fg = _by_id(good)["quads"]["fatigue"]
    fp = _by_id(poor)["quads"]["fatigue"]
    assert fp > fg
    assert poor["whole_body"]["factor"] > good["whole_body"]["factor"]


def test_per_set_weights_csv_parsed():
    res = compute_recovery([{
        "name": "Bench Press", "sets": 3, "reps": "8,8,7",
        "weights": "100,105,105", "rir": 1,
        "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["chest"]["status"] in ("just_hit", "strained")
    # triceps get partial credit as a synergist
    assert 0 < by["triceps"]["fatigue"] < by["chest"]["fatigue"]


def test_bodyweight_movement_registers():
    res = compute_recovery([{
        "name": "Pull-Up", "sets": 5, "reps": "10",
        "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    assert _by_id(res)["back"]["fatigue"] > 0


def test_wire_shape_contract():
    res = compute_recovery([_squat(2)], {"recovery_score": 60, "strain": 12.0, "sleep_hours": 7}, {"age": 33}, NOW)
    assert res["v"] == 1
    assert "generated_at" in res
    assert set(res["whole_body"].keys()) == {"recovery_score", "strain", "sleep_hours", "factor"}
    m = res["muscles"][0]
    assert set(m.keys()) >= {"id", "name", "group", "status", "fatigue",
                             "recovery_pct", "last_trained_label", "movements"}
    assert set(res["summary"].keys()) == {"ready", "recovering", "headline"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
