"""Unit tests for the [SESSION STATE] context block builder."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.session_state import (
    build_session_state,
    matches_program_exercise,
    pick_program_day,
)


def _e(id_=1, name="Cable Pushdown", sets=1, reps="10", weight=86.18,
       seconds_ago=600, duration_minutes=None):
    return SimpleNamespace(
        id=id_, exercise_name=name, sets=sets, reps=reps, weight=weight,
        duration_minutes=duration_minutes,
        timestamp=datetime(2026, 6, 11, 23, 0, 0) - timedelta(seconds=seconds_ago),
    )


# Danny's program day, as parsed from the user's free-text paste.
DANNYS_ARMS_DAY = {
    "name": "Arms + Core + Legs Maintenance",
    "exercises": [
        {"name": "Cable Curls", "category": "main"},
        {"name": "Pushdowns", "category": "main"},
        {"name": "Cable Crunches", "category": "accessory"},
        {"name": "Oblique Work", "category": "accessory"},
        {"name": "Hamstring Curls", "category": "accessory"},
        {"name": "Leg Press", "category": "accessory"},
        {"name": "Leg Extensions", "category": "accessory"},
    ],
}

DANNYS_PROGRAM = {
    "split_name": "Upper-Focus PPL with Arms/Core/Legs Maintenance",
    "focus": "Maximize upper body hypertrophy",
    "rotation": ["Day 1 - Chest", "Day 2 - Back", "Day 3 - Shoulders",
                 "Day 4 - Arms + Core + Legs Maintenance",
                 "Day 5 - Chest", "Day 6 - Back or Shoulders", "Day 7 - Rest"],
    "days": [DANNYS_ARMS_DAY],
}


# ── matches_program_exercise ─────────────────────────────────────────────────

def test_program_slot_matches_canonical_entry():
    """Program 'Pushdowns' (plural) matches stored 'Cable Pushdown'."""
    assert matches_program_exercise("Pushdowns", "Cable Pushdown") is True


def test_program_slot_matches_more_specific_entry():
    """Program 'Cable Curls' matches a logged 'Straight Bar Cable Curl' —
    user did a specific variant of a generic slot."""
    assert matches_program_exercise("Cable Curls", "Straight Bar Cable Curl") is True


def test_specific_program_does_not_match_generic_entry():
    """The reverse direction is NOT accepted — picking a less-specific
    variant could mean a different movement entirely."""
    # 'Straight Bar Cable Curl' program does NOT get credited by a generic
    # 'Cable Curl' entry. We accept program-as-substring only.
    assert matches_program_exercise(
        "Straight Bar Cable Curl", "Cable Curl"
    ) is False


def test_different_exercises_dont_match():
    assert matches_program_exercise("Pushdowns", "Cable Pulldown") is False
    assert matches_program_exercise("Bench Press", "Squat") is False


def test_empty_inputs_dont_match():
    assert matches_program_exercise("", "Bench Press") is False
    assert matches_program_exercise("Bench Press", "") is False
    assert matches_program_exercise(None, "Bench Press") is False


# ── build_session_state ──────────────────────────────────────────────────────

def test_empty_log_returns_empty_string():
    today_log = SimpleNamespace(exercise_entries=[])
    out = build_session_state(today_log, DANNYS_PROGRAM,
                              now_dt=datetime(2026, 6, 11, 23, 18))
    assert out == ""


def test_in_session_no_program_still_summarizes():
    """When the user has no WorkoutProgram, the block still shows what's
    been done. Half-coverage is better than silence."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Bench Press", reps="8", weight=61.235, seconds_ago=1200),
    ])
    out = build_session_state(today_log, program_json=None,
                              now_dt=datetime(2026, 6, 11, 23, 0, 0))
    assert "[SESSION STATE]" in out
    assert "In session: 20 min" in out
    assert "Bench Press" in out


def test_no_program_path_includes_muscle_coverage_and_meta():
    """Freeform path (no program) must still surface catalog metadata —
    primary muscle, equipment — so the model can give actionable coaching
    ('triceps already 3 sets, pair with biceps next')."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(id_=1, name="Cable Pushdown", sets=1, reps="10",
           weight=86.18, seconds_ago=600),
        _e(id_=2, name="Cable Pushdown", sets=1, reps="9",
           weight=86.18, seconds_ago=300),
        _e(id_=3, name="Cable Crunch", sets=1, reps="14",
           weight=63.50, seconds_ago=90),
    ])
    out = build_session_state(today_log, program_json=None,
                              now_dt=datetime(2026, 6, 11, 23, 0, 0))
    # Catalog metadata decorations on movements
    assert "(triceps · cable)" in out, out
    assert "(abs · cable)" in out, out
    # Muscle coverage rollup ALWAYS present when entries exist
    assert "Muscle coverage so far:" in out
    assert "triceps" in out and "abs" in out
    # Movement order is shown via 'Done this session (in order)'
    assert "Done this session (in order):" in out


def test_no_program_path_surfaces_rest_window_for_last_set():
    """When a logged movement has catalog rest metadata, the block shows
    'Last set: Ns ago · typical rest for X is L-Hs' — concrete pacing data
    the model uses to coach 'push for next set' vs 'still resting'."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Cable Pushdown", reps="10", weight=86.18, seconds_ago=45),
    ])
    out = build_session_state(today_log, program_json=None,
                              now_dt=datetime(2026, 6, 11, 23, 0, 0))
    assert "Last set: 45s ago" in out
    assert "typical rest for Cable Pushdown is 60-90s" in out


def test_no_program_suggests_next_step_with_rules_pointer():
    """Freeform path should point the model at the EXERCISE ORDER prompt
    rules rather than picking arbitrarily — model has more session context
    than the helper does."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Cable Pushdown", reps="10", weight=86.18, seconds_ago=300),
    ])
    out = build_session_state(today_log, program_json=None,
                              now_dt=datetime(2026, 6, 11, 23, 0, 0))
    assert "Suggested next:" in out
    assert ("EXERCISE ORDER" in out or "antagonist" in out)


def test_off_catalog_movement_falls_back_gracefully():
    """An exercise NOT in the catalog (rare phrasing, niche class) still
    renders without crashing — just no metadata decoration."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Some Exotic Movement", reps="10", weight=50, seconds_ago=600),
    ])
    out = build_session_state(today_log, program_json=None,
                              now_dt=datetime(2026, 6, 11, 23, 0, 0))
    assert "Some Exotic Movement" in out
    # 'other' bucket for unknown muscle
    assert "other" in out.lower() or "Muscle coverage" in out
    # No "typical rest for" line when catalog has no entry
    assert "typical rest for Some Exotic" not in out


def test_session_total_set_and_movement_counts_in_header():
    """Header shows 'N sets across M movements' so the model can pace —
    e.g. 'you're 12 sets in, that's a full session'."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(id_=1, name="Cable Pushdown", sets=3, reps="10,9,8", weight=86.18,
           seconds_ago=1200),
        _e(id_=2, name="Cable Crunch", sets=2, reps="14,14", weight=63.50,
           seconds_ago=600),
    ])
    out = build_session_state(today_log, program_json=None,
                              now_dt=datetime(2026, 6, 11, 23, 0, 0))
    # 3 + 2 = 5 sets, 2 movements
    assert "5 sets across 2 movements" in out


def test_program_done_and_notdone_render():
    """Danny's actual session: 3 program slots done, 4 remaining."""
    # Logged entries matching the program slots
    today_log = SimpleNamespace(exercise_entries=[
        _e(id_=157, name="Straight Bar Cable Curl",
           reps="13", weight=63.50, seconds_ago=1080),  # matches 'Cable Curls'
        _e(id_=146, name="Cable Pushdown",
           reps="11", weight=86.18, seconds_ago=1980),  # matches 'Pushdowns'
        _e(id_=150, name="Cable Crunch",
           reps="14", weight=63.50, seconds_ago=1380),  # matches 'Cable Crunches'
    ])
    out = build_session_state(
        today_log, DANNYS_PROGRAM,
        now_dt=datetime(2026, 6, 11, 23, 0, 0),
        todays_program_day_name="Arms + Core + Legs Maintenance",
    )
    assert "[SESSION STATE]" in out
    assert "Arms + Core + Legs Maintenance" in out
    assert "Done on program:" in out
    # Each done slot should appear with its match
    assert "Cable Curls" in out
    assert "Straight Bar Cable Curl" in out
    assert "Pushdowns" in out
    assert "Cable Crunches" in out
    # Still on program
    assert "Still on program:" in out
    assert "Oblique Work" in out
    assert "Hamstring Curls" in out
    assert "Leg Press" in out
    assert "Leg Extensions" in out


def test_suggested_next_picks_first_uncovered_main():
    """When mains exist that aren't covered, suggested next is one of them
    (main category beats accessory in priority)."""
    today_log = SimpleNamespace(exercise_entries=[
        # Only Cable Crunches done — no mains yet
        _e(name="Cable Crunch", reps="14", weight=63.50, seconds_ago=300),
    ])
    out = build_session_state(
        today_log, DANNYS_PROGRAM,
        now_dt=datetime(2026, 6, 11, 23, 0, 0),
        todays_program_day_name="Arms + Core + Legs Maintenance",
    )
    # Suggested next should be a MAIN (Cable Curls or Pushdowns) since neither done
    assert "Suggested next:" in out
    assert ("Cable Curls (main)" in out or "Pushdowns (main)" in out), out


def test_suggested_next_when_all_program_done():
    """All slots covered → suggest wrap or off-program accessory."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Straight Bar Cable Curl", reps="13", weight=63.50, seconds_ago=1200),
        _e(name="Cable Pushdown", reps="11", weight=86.18, seconds_ago=1080),
        _e(name="Cable Crunch", reps="14", weight=63.50, seconds_ago=900),
        _e(name="Oblique Cable Crunch", reps="14", weight=45.36, seconds_ago=720),
        _e(name="Hamstring Curl", reps="12", weight=54.43, seconds_ago=600),
        _e(name="Leg Press", reps="10", weight=181.44, seconds_ago=420),
        _e(name="Leg Extension", reps="12", weight=72.57, seconds_ago=240),
    ])
    out = build_session_state(
        today_log, DANNYS_PROGRAM,
        now_dt=datetime(2026, 6, 11, 23, 0, 0),
        todays_program_day_name="Arms + Core + Legs Maintenance",
    )
    assert "Suggested next:" in out
    # Should reference wrap or "covered"
    assert ("wrap" in out.lower() or "covered" in out.lower())


def test_off_program_exercises_listed_separately():
    """When the user did things not in today's program day, they're
    surfaced in their own section so the model knows they happened."""
    today_log = SimpleNamespace(exercise_entries=[
        # Off-program: Overhead Cable Extension (triceps isolation,
        # not in Danny's arms-day program list)
        _e(name="Overhead Cable Extension", reps="13", weight=49.90, seconds_ago=2520),
        # Cable Pushdown is in the program (matches "Pushdowns")
        _e(name="Cable Pushdown", reps="11", weight=86.18, seconds_ago=1980),
    ])
    out = build_session_state(
        today_log, DANNYS_PROGRAM,
        now_dt=datetime(2026, 6, 11, 23, 0, 0),
        todays_program_day_name="Arms + Core + Legs Maintenance",
    )
    assert "Off-program done:" in out
    assert "Overhead Cable Extension" in out
    # The on-program one shouldn't ALSO appear under off-program
    assert out.count("Cable Pushdown") < 3, (
        f"Cable Pushdown should appear in Done on program, not duplicated\n{out}"
    )


def test_pick_program_day_finds_best_match():
    """Danny's session matches Day 4 (Arms + Core + Legs) with 3 program
    slots covered; no other day has any matches. Auto-pick must return
    Day 4's name."""
    entries = [
        SimpleNamespace(exercise_name="Cable Pushdown"),
        SimpleNamespace(exercise_name="Straight Bar Cable Curl"),
        SimpleNamespace(exercise_name="Cable Crunch"),
    ]
    # Pad the program with extra days that have NO overlap so the test
    # genuinely picks the best-matching day, not the first day.
    program = {
        "days": [
            {"name": "Chest Day",
             "exercises": [{"name": "Bench Press"}, {"name": "Flat DB Press"}]},
            DANNYS_ARMS_DAY,
            {"name": "Legs Day",
             "exercises": [{"name": "Back Squat"}, {"name": "Leg Press"}]},
        ],
    }
    picked = pick_program_day(program, entries)
    assert picked == "Arms + Core + Legs Maintenance"


def test_pick_program_day_returns_none_when_no_overlap():
    """User did a session that doesn't match any planned day (free-form
    work, traveling, etc.). Auto-pick returns None and build_session_state
    falls back to the no-program path."""
    entries = [
        SimpleNamespace(exercise_name="Some Niche Class Movement"),
    ]
    program = {"days": [{"name": "Chest Day",
                         "exercises": [{"name": "Bench Press"}]}]}
    assert pick_program_day(program, entries) is None


def test_build_session_state_auto_picks_day(monkeypatch):
    """When the caller doesn't pass todays_program_day_name, the helper
    should auto-discover it from logged entries. This is the production
    code path: context_builder doesn't know which rotation day the user
    is doing."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Cable Pushdown", reps="11", weight=86.18, seconds_ago=600),
        _e(name="Straight Bar Cable Curl",
           reps="13", weight=63.50, seconds_ago=300),
    ])
    # Note: NOT passing todays_program_day_name
    out = build_session_state(
        today_log, DANNYS_PROGRAM,
        now_dt=datetime(2026, 6, 11, 23, 0, 0),
    )
    assert "Arms + Core + Legs Maintenance" in out, out
    assert "Done on program:" in out


def test_program_day_lookup_case_insensitive():
    """The caller may pass the day name in slightly different case/
    whitespace than the program JSON stores. Match should still work."""
    today_log = SimpleNamespace(exercise_entries=[
        _e(name="Cable Pushdown", reps="11", weight=86.18, seconds_ago=600),
    ])
    out = build_session_state(
        today_log, DANNYS_PROGRAM,
        now_dt=datetime(2026, 6, 11, 23, 0, 0),
        todays_program_day_name="arms + core + legs maintenance",  # lowercased
    )
    assert "Done on program:" in out, out
