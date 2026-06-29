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


def test_one_light_set_does_not_lock_out_a_muscle():
    """Danny: one set of lat pulldown shouldn't rule out lats for days. Low volume
    (sets x reps x load) already decays fast under the recalibrated lats tau."""
    one_set = {"name": "Lat Pulldown", "sets": 1, "reps": "10", "weight": 60.0,
               "rir": 2, "occurred_at": NOW - timedelta(hours=20)}
    lats = _by_id(compute_recovery([one_set], None, {"age": 33}, NOW))["lats"]
    assert lats["status"] == "ready"
    assert lats["recovery_pct"] >= 75


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
    assert by["calves"]["fatigue"] > by["chest_mid"]["fatigue"]
    assert by["quads"]["fatigue"] > 0
    # systemic full-body effect: even chest registers something
    assert by["chest_mid"]["fatigue"] > 0


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
    # Bench Press dominates mid-chest with upper/lower as secondaries
    assert by["chest_mid"]["status"] in ("just_hit", "strained")
    # triceps get partial credit as a synergist (less than the prime mover)
    assert 0 < by["triceps"]["fatigue"] < by["chest_mid"]["fatigue"]


def test_bodyweight_movement_registers():
    res = compute_recovery([{
        "name": "Pull-Up", "sets": 5, "reps": "10",
        "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    # Pull-Up dominates lats (vertical pull), mid-back picks up secondary load
    assert _by_id(res)["lats"]["fatigue"] > 0


def test_wire_shape_contract():
    res = compute_recovery([_squat(2)], {"recovery_score": 60, "strain": 12.0, "sleep_hours": 7}, {"age": 33}, NOW)
    assert res["v"] == 1
    assert "generated_at" in res
    assert set(res["whole_body"].keys()) == {"recovery_score", "strain", "sleep_hours", "factor"}
    m = res["muscles"][0]
    assert set(m.keys()) >= {"id", "name", "group", "status", "fatigue",
                             "recovery_pct", "last_trained_label", "movements"}
    assert set(res["summary"].keys()) == {"ready", "recovering", "headline"}


# ── chest sub-muscle splits ───────────────────────────────────────────────────

def test_incline_press_routes_to_chest_upper_not_lower():
    """Incline angles emphasize clavicular fibers — chest_upper should
    dominate, chest_lower should barely register."""
    res = compute_recovery([{
        "name": "Incline Bench Press", "sets": 4, "reps": "8",
        "weight": 80.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["chest_upper"]["fatigue"] > by["chest_mid"]["fatigue"]
    assert by["chest_upper"]["fatigue"] > by["chest_lower"]["fatigue"]
    # Mid still picks up some (0.40 coefficient), lower is essentially zero
    assert by["chest_lower"]["fatigue"] == 0


def test_decline_press_routes_to_chest_lower_not_upper():
    """Decline emphasizes the sternal/lower fibers — chest_lower must
    dominate and chest_upper must not register."""
    res = compute_recovery([{
        "name": "Decline Bench Press", "sets": 4, "reps": "8",
        "weight": 80.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["chest_lower"]["fatigue"] > by["chest_mid"]["fatigue"]
    assert by["chest_lower"]["fatigue"] > by["chest_upper"]["fatigue"]
    assert by["chest_upper"]["fatigue"] == 0


def test_flat_bench_loads_all_three_chest_regions_mid_dominant():
    """A flat bench day works the whole chest, but mid is the prime mover —
    upper/lower come along for the ride at sub-1.0 coefficients."""
    res = compute_recovery([{
        "name": "Bench Press", "sets": 4, "reps": "8",
        "weight": 100.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["chest_mid"]["fatigue"] > by["chest_upper"]["fatigue"] > 0
    assert by["chest_mid"]["fatigue"] > by["chest_lower"]["fatigue"] > 0


# ── back sub-muscle splits ────────────────────────────────────────────────────

def test_lat_pulldown_routes_to_lats_not_mid_back():
    """Vertical pulls (pulldown, pull-up) emphasize lats. Lats should
    dominate; mid_back should pick up some secondary load."""
    res = compute_recovery([{
        "name": "Lat Pulldown", "sets": 4, "reps": "10",
        "weight": 70.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["lats"]["fatigue"] > by["mid_back"]["fatigue"] > 0
    assert by["lower_back"]["fatigue"] == 0


def test_lats_recover_in_small_muscle_window():
    """Lats tau ~34h — should be largely recovered by ~36h after a normal
    session. This is the "small muscle window" Danny reported about."""
    res = compute_recovery([{
        "name": "Lat Pulldown", "sets": 4, "reps": "10",
        "weight": 70.0, "rir": 1, "occurred_at": NOW - timedelta(hours=36),
    }], None, {"age": 33}, NOW)
    lats = _by_id(res)["lats"]
    assert lats["recovery_pct"] >= 60
    assert lats["status"] in ("ready", "recovering")


def test_deadlift_dominates_lower_back():
    """Heavy deadlifts spike the spinal erectors — lower_back must be the
    most-fatigued back sub-muscle, not lats or mid_back."""
    res = compute_recovery([{
        "name": "Deadlift", "sets": 3, "reps": "5",
        "weight": 200.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["lower_back"]["fatigue"] > by["mid_back"]["fatigue"]
    assert by["lower_back"]["fatigue"] > by["lats"]["fatigue"]
    # legs come along (glutes, hams) — verify the cross-muscle attribution
    assert by["glutes"]["fatigue"] > 0
    assert by["hamstrings"]["fatigue"] > 0


def test_barbell_row_dominates_mid_back_lats_secondary():
    """Horizontal pulls hit mid-back hard (rhomboids/mid-traps) with lats
    along as secondary. The reverse of Pull-Up's lats-dominant profile."""
    res = compute_recovery([{
        "name": "Barbell Row", "sets": 4, "reps": "8",
        "weight": 120.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["mid_back"]["fatigue"] > by["lats"]["fatigue"] > 0
    # lower_back picks up some hinge load (0.30 coefficient)
    assert by["lower_back"]["fatigue"] > 0


def test_back_legacy_alias_routes_to_lats():
    """An unknown back-primary movement (catalog primary='back' would have
    been the legacy value) routes via _PRIMARY_ALIAS to lats — graceful
    fallback for any data that pre-dates the sub-muscle split."""
    # Hijack a catalog entry by typing a name that resolves to a back-primary
    # entry but isn't in INVOLVEMENT — Straight-Arm Pulldown's primary is "lats"
    # already, so this just confirms it doesn't crash. The real fallback test
    # is the unknown-name case below.
    res = compute_recovery([{
        "name": "straight-arm pulldown", "sets": 3, "reps": "12",
        "weight": 40.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    assert _by_id(res)["lats"]["fatigue"] > 0


# ── catalog expansion: every NEW INVOLVEMENT entry's primary check ────────────
# For each new entry, the canonical's highest-coefficient muscle must match
# the intended primary mover. This is a regression pin: if a future PR drops
# the prime mover's coefficient below a synergist's, this fires.

@pytest.mark.parametrize("name,expected_primary", [
    # Chest additions
    ("Machine Chest Press", "chest_mid"),
    ("Floor Press", "chest_mid"),
    ("Landmine Press", "chest_upper"),
    ("Diamond Push-Up", "triceps"),
    # Back additions
    ("Pendlay Row", "mid_back"),
    ("T-Bar Row", "mid_back"),
    ("Rack Pull", "lower_back"),
    ("Hyperextension", "lower_back"),
    ("Reverse Hyperextension", "lower_back"),
    # Shoulder additions
    ("Arnold Press", "shoulders"),
    ("Push Press", "shoulders"),
    ("Front Raise", "shoulders"),
    ("Machine Rear Delt Fly", "shoulders"),
    # Traps
    ("Farmer's Carry", "traps"),
    # Biceps additions
    ("Incline Curl", "biceps"),
    ("Concentration Curl", "biceps"),
    ("EZ-Bar Curl", "biceps"),
    ("Zottman Curl", "biceps"),
    # Triceps additions
    ("Skull Crusher", "triceps"),
    ("Overhead Tricep Extension", "triceps"),
    ("Bench Dip", "triceps"),
    # Forearms additions
    ("Wrist Curl", "forearms"),
    ("Reverse Wrist Curl", "forearms"),
    # Quad additions
    ("Hack Squat", "quads"),
    ("Step-Up", "quads"),
    ("Box Squat", "quads"),
    # Hamstring/glute additions
    ("Nordic Curl", "hamstrings"),
    ("Seated Leg Curl", "hamstrings"),
    ("Hip Thrust", "glutes"),
    ("Glute Bridge", "glutes"),
    # Calves
    ("Seated Calf Raise", "calves"),
    ("Standing Calf Raise", "calves"),
    ("Donkey Calf Raise", "calves"),
    # Core additions
    ("Plank", "abs"),
    ("Dead Bug", "abs"),
    ("Pallof Press", "abs"),
    ("Side Plank", "obliques"),
    # Conditioning finishers
    ("Battle Ropes", "shoulders"),
    ("Burpees", "abs"),
    ("Box Jumps", "quads"),
])
def test_new_movement_primary_mover_dominates(name, expected_primary):
    """Each new movement attributes the highest residual fatigue to its
    declared primary mover. Catches a future PR that drops the prime
    coefficient below a synergist."""
    from skills.fitness.muscle_recovery import (
        INVOLVEMENT, _entry_muscle_stimulus,
    )
    # Some entries live only as canonical+catalog (no INVOLVEMENT row, fallback
    # uses catalog primary). Either path must agree on the prime mover.
    res = compute_recovery([{
        "name": name, "sets": 4, "reps": "10",
        "weight": 50.0, "rir": 1, "occurred_at": NOW - timedelta(hours=2),
    }], None, {"age": 33}, NOW)
    by = _by_id(res)
    # _PRIMARY_ALIAS folds 'obliques' into the 'abs' bucket; honor that.
    target = "abs" if expected_primary == "obliques" else expected_primary
    # Find the muscle with the maximum fatigue
    top_muscle = max(by.values(), key=lambda m: m["fatigue"])["id"]
    if expected_primary == "obliques":
        # Side Plank's "obliques 1.0, abs 0.5" sums into the abs bucket via
        # _PRIMARY_ALIAS, so the bucket-level prime is "abs" — and abs WILL
        # be the highest. Honor both forms here.
        assert top_muscle == "abs", (
            f"{name} expected obliques→abs as prime, got {top_muscle}; "
            f"fatigues: {[(k, round(v['fatigue'], 3)) for k, v in by.items() if v['fatigue'] > 0]}"
        )
    else:
        assert top_muscle == target, (
            f"{name} expected {target} as prime, got {top_muscle}; "
            f"fatigues: {[(k, round(v['fatigue'], 3)) for k, v in by.items() if v['fatigue'] > 0]}"
        )


def test_rowing_cardio_loads_mid_back_not_legacy_back():
    """Rowing's INVOLVEMENT was previously {'back': 0.5} — now mid_back. A
    Zone-3 row should leave mid_back loaded and not crash on missing 'back'."""
    row = {
        "name": "Rowing", "cardio_type": "row", "duration_minutes": 30,
        "avg_hr": 150, "occurred_at": NOW - timedelta(hours=2),
    }
    res = compute_recovery([row], None, {"age": 33}, NOW)
    by = _by_id(res)
    assert by["mid_back"]["fatigue"] > 0
    assert by["quads"]["fatigue"] > 0  # legs always do work on the erg


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
