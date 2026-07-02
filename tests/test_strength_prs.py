"""Tests for the exercise PR tracker compute layer (core/strength_prs.py)."""
import types
from datetime import date, timedelta

from core.strength_prs import compute_strength_prs
from core import strength_standards


def _entry(name, weight=None, reps=None, weights=None, cardio=None):
    return types.SimpleNamespace(
        exercise_name=name, weight=weight, reps=reps, weights=weights,
        sets=None, cardio_type=cardio,
    )


def _log(d, entries):
    return types.SimpleNamespace(date=d, exercise_entries=entries)


def test_ranks_by_estimated_1rm_and_folds_names():
    today = date.today()
    logs = [
        # "bench" and "barbell bench press" are the same canonical lift; keep best e1rm.
        _log(today, [_entry("bench", weight=100, reps="5,5,5")]),        # e1rm 116.7kg
        _log(today - timedelta(days=40), [_entry("barbell bench press", weight=102, reps="3")]),  # 112.2kg
        _log(today - timedelta(days=200), [_entry("deadlift", weight=180, reps="2")]),  # 192kg
    ]
    prs = compute_strength_prs(logs, bodyweight_kg=95.0, sex="male")
    names = [p["name"] for p in prs]
    assert names[0] == "Deadlift"           # highest e1rm ranks first
    assert "Bench Press" in names
    bench = next(p for p in prs if p["name"] == "Bench Press")
    assert bench["top_reps"] == 5           # 100x5 beat 102x3 on e1rm


def test_per_set_weights_picks_best_single_in_pyramid():
    today = date.today()
    logs = [_log(today, [_entry("back squat", weights="140,150,160", reps="5,3,1")])]
    prs = compute_strength_prs(logs, bodyweight_kg=95.0, sex="male")
    squat = next(p for p in prs if p["name"] == "Back Squat")
    # 160x1 -> e1rm 165.3kg beats 150x3 (165.0) and 140x5 (163.3)
    assert squat["top_reps"] == 1
    assert round(squat["top_weight_lbs"]) == round(160 * 2.20462)


def test_cardio_and_unloaded_are_excluded():
    today = date.today()
    logs = [_log(today, [
        _entry("running", cardio="running"),          # cardio
        _entry("pull ups", reps="10"),                # no weight
        _entry("plank", weight=0, reps="1"),          # zero weight
    ])]
    assert compute_strength_prs(logs, bodyweight_kg=95.0, sex="male") == []


def test_recent_flag_within_window():
    today = date.today()
    logs = [
        _log(today - timedelta(days=3), [_entry("deadlift", weight=180, reps="3")]),
        _log(today - timedelta(days=90), [_entry("bench", weight=100, reps="5")]),
    ]
    prs = {p["name"]: p for p in compute_strength_prs(logs, bodyweight_kg=95.0, sex="male")}
    assert prs["Deadlift"]["is_recent"] is True
    assert prs["Bench Press"]["is_recent"] is False


def test_reps_out_of_epley_range_ignored():
    today = date.today()
    logs = [_log(today, [_entry("bench", weight=60, reps="30")])]  # 30 reps > cap
    assert compute_strength_prs(logs, bodyweight_kg=95.0, sex="male") == []


def test_standard_classification_scales_with_bodyweight():
    today = date.today()
    logs = [_log(today, [_entry("bench", weight=110, reps="3")])]  # e1rm ~121kg
    # Light lifter: 121kg e1rm is ~2x bodyweight -> advanced.
    light = compute_strength_prs(logs, bodyweight_kg=60.0, sex="male")[0]
    # Heavy lifter: same lift is a smaller multiple -> lower tier.
    heavy = compute_strength_prs(logs, bodyweight_kg=120.0, sex="male")[0]
    assert light["standard"]["level"] == "advanced"
    assert heavy["standard"]["level"] in {"beginner", "novice", "intermediate"}


def test_isolation_excluded_from_board():
    # Small-muscle isolation (a curl) is left off the board entirely — it's neither a
    # large-muscle movement nor weighted calisthenics, so it never earns a row.
    today = date.today()
    logs = [_log(today, [_entry("dumbbell curl", weight=20, reps="10")])]
    assert compute_strength_prs(logs, bodyweight_kg=95.0, sex="male") == []


def test_no_standard_for_unbenchmarked_board_lift():
    # A large-muscle movement without a bodyweight benchmark (a cable pulldown) still
    # appears on the board, just with no strength tier.
    today = date.today()
    logs = [_log(today, [_entry("lat pulldown", weight=60, reps="10")])]
    prs = compute_strength_prs(logs, bodyweight_kg=95.0, sex="male")
    assert prs and prs[0]["standard"] is None


def test_missing_bodyweight_yields_no_standard():
    today = date.today()
    logs = [_log(today, [_entry("bench", weight=100, reps="5")])]
    prs = compute_strength_prs(logs, bodyweight_kg=None, sex="male")
    assert prs and prs[0]["standard"] is None


def test_standards_classify_boundaries():
    # At exactly the intermediate threshold -> intermediate.
    std = strength_standards.classify("Bench Press", e1rm_kg=95.0 * 1.25,
                                      bodyweight_kg=95.0, sex="male")
    assert std["level"] == "intermediate"
    assert std["next_level"] == "advanced"


def test_empty_logs():
    assert compute_strength_prs([], bodyweight_kg=95.0, sex="male") == []


def test_recent_sets_last_three_newest_first():
    # The PR row expands into the last 3 logged working sets, newest first —
    # a compact frame of reference, not a chart.
    d1, d2 = date.today() - timedelta(days=7), date.today()
    logs = [
        _log(d1, [_entry("bench", weight=100, reps="5,5"),
                  _entry("bench", weight=95, reps="8")]),
        _log(d2, [_entry("bench", weight=105, reps="5")]),
    ]
    prs = compute_strength_prs(logs, bodyweight_kg=90.0, sex="male")
    assert prs, "bench must make the board"
    rs = prs[0]["recent_sets"]
    assert len(rs) == 3
    assert rs[0]["date"] == str(d2)              # newest first
    assert rs[0]["reps"] == 5
    assert abs(rs[0]["weight_lbs"] - 105 * 2.20462) < 0.1
    assert {r["date"] for r in rs[1:]} == {str(d1)}
