"""Layer 4 — authoritative per-movement set count from the DB.

The set counter is sourced from truth and echoed on every log so an accumulation
miscount ("3 sets" reported but 2 stored — the 2026-06-25 upright-row drop) is
visible immediately instead of silently accepted. _movement_set_summary is the
pure readback the executor appends to every log_exercise result.
"""
from types import SimpleNamespace as NS
from handlers.tool_executor import _movement_set_summary


def _log(*entries):
    return NS(exercise_entries=list(entries))


def test_sums_single_set_rows_for_one_movement():
    log = _log(
        NS(id=1, exercise_name="Upright Row", sets=1, reps="15", weight=45.3592),
        NS(id=2, exercise_name="Upright Row", sets=1, reps="15", weight=45.3592),
        NS(id=3, exercise_name="Upright Row", sets=1, reps="15", weight=45.3592),
    )
    assert _movement_set_summary(log, "Upright Row") == "Upright Row: 3 sets (15,15,15) @ 100lb"


def test_multiset_row_counts_its_sets():
    log = _log(NS(id=1, exercise_name="Bench", sets=3, reps="8,8,7", weight=60.0))
    assert _movement_set_summary(log, "Bench") == "Bench: 3 sets (8,8,7) @ 132lb"


def test_scopes_to_the_named_movement_only():
    log = _log(
        NS(id=1, exercise_name="Shrugs", sets=3, reps="14,14,15", weight=86.18),
        NS(id=2, exercise_name="Upright Row", sets=2, reps="15,15", weight=45.36),
    )
    assert _movement_set_summary(log, "Shrugs").startswith("Shrugs: 3 sets")
    assert _movement_set_summary(log, "Upright Row").startswith("Upright Row: 2 sets")


def test_unlogged_movement_reads_zero():
    assert _movement_set_summary(_log(), "Squat") == "Squat: 0 sets"
    log = _log(NS(id=1, exercise_name="Bench", sets=1, reps="8", weight=60.0))
    assert _movement_set_summary(log, "Squat") == "Squat: 0 sets"


def test_singular_when_one_set():
    log = _log(NS(id=1, exercise_name="Deadlift", sets=1, reps="5", weight=140.0))
    assert "1 set " in _movement_set_summary(log, "Deadlift") + " "
    assert "1 sets" not in _movement_set_summary(log, "Deadlift")
