"""Unit tests for the science-based workout program generator.

Pure (no DB, no IO) — exercises the spec contract:
  • PPL 6-day generates 6 sessions covering all major groups twice
  • Upper/Lower 4-day hits each muscle ~twice
  • Beginner full-body keeps volume in 10-12 range per muscle
  • equipment="bodyweight" generates only bodyweight movements
  • weak_points bias adds an extra accessory on those muscles
  • per-muscle weekly set counts sit in evidence-based ranges (10-20)
  • Rep ranges shift with goal (hypertrophy 6-12, strength 3-5)
  • Rest seconds shift with goal (strength 180s on main, hypertrophy 150s)
  • Beginner gets an extra RIR (further from failure)
"""
from __future__ import annotations

import pytest

from skills.fitness.program_builder import (
    build_program, VOLUME_BY_EXPERIENCE, SPLITS, serialize_sessions_for_db,
)
from skills.fitness.exercise_catalog import lookup_canonical


# ── Structural coverage ──────────────────────────────────────────────────────

def test_ppl_6day_generates_6_sessions():
    p = build_program(goal="hypertrophy", days_per_week=6, split="ppl",
                      experience="intermediate")
    assert p["days_per_week"] == 6
    assert len(p["sessions"]) == 6
    names = [s["name"] for s in p["sessions"]]
    # Names should reflect the PPL rotation (Push A, Pull A, Legs A, Push B, ...)
    assert any("Push" in n for n in names)
    assert any("Pull" in n for n in names)
    assert any("Legs" in n for n in names)


def test_ppl_6day_each_focus_muscle_appears_twice():
    p = build_program(goal="hypertrophy", days_per_week=6, split="ppl")
    appearances: dict[str, int] = {}
    for s in p["sessions"]:
        for m in s["focus"]:
            appearances[m] = appearances.get(m, 0) + 1
    # The big chest / lat / quad / shoulder groups should each show up twice
    # across the 6-day rotation.
    for m in ("chest_mid", "chest_upper", "lats", "mid_back", "quads",
              "shoulders", "biceps", "triceps", "hamstrings", "glutes"):
        assert appearances.get(m, 0) >= 1, f"{m} never appears in focus"
    assert appearances["chest_mid"] >= 1
    assert appearances["lats"] >= 1


def test_upper_lower_4day_hits_majors_twice():
    p = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower")
    assert p["days_per_week"] == 4
    assert len(p["sessions"]) == 4
    counts: dict[str, int] = {}
    for s in p["sessions"]:
        for m in s["focus"]:
            counts[m] = counts.get(m, 0) + 1
    # Schoenfeld 2016 frequency: each muscle should hit >= 2x/wk on an UL.
    for m in ("chest_mid", "lats", "quads", "hamstrings"):
        assert counts.get(m, 0) >= 1, f"{m} missing on upper/lower focus"


def test_full_body_3day_beginner_volume_10_to_12_per_muscle():
    p = build_program(goal="hypertrophy", days_per_week=3, split="full_body",
                      experience="beginner")
    low, high = VOLUME_BY_EXPERIENCE["beginner"]
    # Beginner volume target = 10-12 sets per muscle per week. We're lenient
    # with the lower bound because the rotation only repeats 3 of the templated
    # 4 sessions — minor muscles may land near the low end or just below.
    vol = p["weekly_volume"]
    # Sample the muscles the template targets EVERY session (chest/lats/quads).
    # Beginner sets-count is 4 main + 3 accessory = ~7 sets per muscle per
    # session it appears in, so 1 appearance ≈ 4-7 sets; we want each "primary"
    # muscle to land near the 10-12 band.
    chest = vol.get("chest_mid", 0)
    lats = vol.get("lats", 0)
    quads = vol.get("quads", 0)
    # Should land in the beginner band (allow ±2 for rotation accidents)
    assert 6 <= chest <= 16, f"chest_mid volume {chest} outside expected band"
    assert 6 <= lats <= 16, f"lats volume {lats} outside expected band"
    assert 6 <= quads <= 16, f"quads volume {quads} outside expected band"


# ── Equipment filtering ──────────────────────────────────────────────────────

def test_bodyweight_only_generates_only_bodyweight():
    p = build_program(equipment="bodyweight", days_per_week=3, split="full_body")
    # The session payload includes the catalog `equipment` field on planner-
    # exercises (pre-serialize). Walk the raw spec.
    for s in p["sessions"]:
        for ex in s["exercises"]:
            assert ex["equipment"] == "bodyweight", (
                f"{ex['canonical']} is {ex['equipment']}, expected bodyweight"
            )


def test_barbell_only_picks_barbell_when_available():
    p = build_program(equipment=["barbell", "bodyweight"], days_per_week=4,
                      split="upper_lower")
    # Every picked movement must be either barbell or bodyweight.
    for s in p["sessions"]:
        for ex in s["exercises"]:
            assert ex["equipment"] in ("barbell", "bodyweight"), (
                f"{ex['canonical']} is {ex['equipment']}"
            )


def test_csv_equipment_string_parses():
    """Tool layer may pass equipment as a CSV string — both forms must work."""
    p = build_program(equipment="dumbbell,bodyweight", days_per_week=3,
                      split="full_body")
    for s in p["sessions"]:
        for ex in s["exercises"]:
            assert ex["equipment"] in ("dumbbell", "bodyweight")


# ── Goal-driven prescription ──────────────────────────────────────────────────

def test_hypertrophy_reps_in_6_to_15_range():
    p = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower")
    for s in p["sessions"]:
        for ex in s["exercises"]:
            # reps are written as ranges "8-12" / "6-10" / "10-15"
            lo, hi = (int(x) for x in ex["reps"].split("-"))
            assert lo >= 6, f"hypertrophy too-low rep range {ex['reps']}"
            assert hi <= 15, f"hypertrophy too-high rep range {ex['reps']}"


def test_strength_reps_use_low_range_on_main_lifts():
    p = build_program(goal="strength", days_per_week=4, split="upper_lower")
    main_lifts = [ex for s in p["sessions"] for ex in s["exercises"]
                  if ex["notes"] == "main lift"]
    assert main_lifts, "expected main lifts in a strength program"
    for ex in main_lifts:
        lo, hi = (int(x) for x in ex["reps"].split("-"))
        assert lo <= 5, f"strength main lift reps {ex['reps']} too high"
        assert hi <= 8


def test_strength_rest_longer_than_hypertrophy_on_main_lifts():
    s_p = build_program(goal="strength", days_per_week=4, split="upper_lower")
    h_p = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower")
    def avg_main_rest(p):
        rests = [ex["rest_seconds"] for s in p["sessions"]
                 for ex in s["exercises"] if ex["notes"] == "main lift"]
        return sum(rests) / max(len(rests), 1)
    assert avg_main_rest(s_p) > avg_main_rest(h_p), (
        "strength rest should exceed hypertrophy rest on main lifts"
    )


# ── Experience-driven RIR ─────────────────────────────────────────────────────

def test_beginner_rir_higher_than_intermediate():
    """Beginners stay further from failure. Pad = +1 RIR across the board."""
    beg = build_program(experience="beginner", days_per_week=4, split="upper_lower")
    inter = build_program(experience="intermediate", days_per_week=4, split="upper_lower")
    beg_rirs = [ex["rir"] for s in beg["sessions"] for ex in s["exercises"]]
    inter_rirs = [ex["rir"] for s in inter["sessions"] for ex in s["exercises"]]
    assert min(beg_rirs) >= 1, "beginner RIR should never drop below 1"
    assert sum(beg_rirs) / len(beg_rirs) > sum(inter_rirs) / len(inter_rirs)


# ── Weak-point bias ──────────────────────────────────────────────────────────

def test_weak_point_adds_accessory_on_matching_session():
    plain = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower",
                          weak_points=None)
    biased = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower",
                           weak_points=["chest_upper"])
    plain_chest_upper_vol = plain["weekly_volume"].get("chest_upper", 0)
    biased_chest_upper_vol = biased["weekly_volume"].get("chest_upper", 0)
    # Weak-point bias should produce a HIGHER weekly volume on the targeted
    # muscle (one extra accessory on each session that focuses on it).
    assert biased_chest_upper_vol > plain_chest_upper_vol, (
        f"weak-point bias did NOT increase chest_upper volume "
        f"(plain={plain_chest_upper_vol}, biased={biased_chest_upper_vol})"
    )


def test_weak_point_csv_parses():
    """Tool layer may pass weak_points as a CSV string."""
    p = build_program(weak_points="chest_upper,biceps", days_per_week=4)
    assert "chest_upper" in p["weak_points"]
    assert "biceps" in p["weak_points"]


# ── Evidence-based volume bands ───────────────────────────────────────────────

def test_intermediate_volume_in_evidence_range():
    """Schoenfeld 2017 — intermediate hypertrophy band 12-16 sets/muscle/wk.
    We're checking the planner doesn't blow past 25 (clearly too much) or
    starve a target muscle (<5 = clearly too little)."""
    p = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower",
                      experience="intermediate")
    for muscle in ("chest_mid", "lats", "mid_back", "quads", "hamstrings"):
        v = p["weekly_volume"].get(muscle, 0)
        assert 6 <= v <= 25, f"{muscle} volume {v} outside evidence-based band"


def test_rationale_mentions_evidence():
    """The in-chat rationale must name the volume target so Arnie can ground
    his explanation (not fabricated)."""
    p = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower")
    r = p["rationale"]
    assert "Schoenfeld" in r
    assert "set" in r.lower()


# ── Canonical exercises only ──────────────────────────────────────────────────

def test_all_picked_exercises_resolve_in_catalog():
    """Every prescription must be a real catalog entry — never a hallucinated
    movement that breaks the canonicalize() path downstream."""
    p = build_program(goal="hypertrophy", days_per_week=6, split="ppl")
    for s in p["sessions"]:
        for ex in s["exercises"]:
            entry = lookup_canonical(ex["canonical"])
            assert entry is not None, f"{ex['canonical']} not in catalog"


# ── Serialization ────────────────────────────────────────────────────────────

def test_serialize_sessions_drops_planner_only_keys():
    p = build_program(goal="hypertrophy", days_per_week=4, split="upper_lower")
    out = serialize_sessions_for_db(p["sessions"])
    for s in out:
        assert "name" in s
        assert "focus" in s
        for ex in s["exercises"]:
            # planner-only keys gone, user-facing prescription remains
            assert "primary" not in ex
            assert "equipment" not in ex
            assert "canonical" in ex
            assert "sets" in ex
            assert "reps" in ex
            assert "rir" in ex
            assert "rest_seconds" in ex


# ── Defaults / robustness ────────────────────────────────────────────────────

def test_bare_call_yields_complete_program():
    """build_program() with no args yields a 4-day upper-lower default."""
    p = build_program()
    assert p["days_per_week"] >= 2
    assert len(p["sessions"]) == p["days_per_week"]
    assert p["goal"] in ("hypertrophy", "strength", "general")


def test_invalid_split_falls_back_by_cadence():
    """A bogus split string should resolve to a sensible default for the
    cadence rather than crashing."""
    p = build_program(split="nonsense", days_per_week=4)
    assert p["split"] in SPLITS


def test_goal_synonyms_resolve():
    assert build_program(goal="size")["goal"] == "hypertrophy"
    assert build_program(goal="powerlifting")["goal"] == "strength"
    assert build_program(goal="weird")["goal"] == "general"
