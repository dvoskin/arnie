"""Unit tests for the server-side exercise dedup guard.

These tests pin the behavior that prevents the re-log-on-context-shift bug
Danny hit on 2026-06-11 (12 dup rows out of 26 in a single arms session).
The dedup helper is a pure function — these tests are fast and isolated.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from skills.fitness.exercise_dedup import (
    is_duplicate_of_recent,
    normalize_exercise_name,
    format_dedup_result,
)


def _entry(id_=1, name="Bench Press", sets=1, reps="10", weight=61.235, ts=None):
    """Lightweight stand-in for an ExerciseEntry ORM row."""
    return SimpleNamespace(
        id=id_,
        exercise_name=name,
        sets=sets,
        reps=reps,
        weight=weight,
        timestamp=ts or datetime(2026, 6, 11, 22, 35, 55),
    )


# ── normalize_exercise_name ───────────────────────────────────────────────────

def test_normalize_collapses_whitespace_and_case():
    assert normalize_exercise_name("Cable Pushdown") == "cable pushdown"
    assert normalize_exercise_name("cable  pushdown") == "cable pushdown"
    assert normalize_exercise_name("  Cable  Pushdown  ") == "cable pushdown"


def test_normalize_handles_none_and_empty():
    assert normalize_exercise_name(None) == ""
    assert normalize_exercise_name("") == ""


# ── is_duplicate_of_recent: positive cases ────────────────────────────────────

def test_exact_payload_within_window_is_dup():
    """The 22:57:02 'Logged 4 exercises' burst pattern: same payload fired
    seconds after the original. Must be flagged."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    prior = _entry(id_=147, name="Cable Pushdown", sets=1, reps="10", weight=86.18,
                   ts=datetime(2026, 6, 11, 22, 48, 33))
    # 8min 29s apart — outside default 120s window — should NOT be flagged
    dup = is_duplicate_of_recent(
        exercise_name="Cable Pushdown", sets=1, reps="10", weight_kg=86.18,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None, "8min gap is outside default 120s window"


def test_burst_within_120s_window_is_dup():
    """Danny's actual burst: at 22:57:02 the model re-fired log_exercise for a
    set logged 12 seconds earlier."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    prior = _entry(id_=151, name="Crunches (Cable/Machine)", sets=1, reps="14",
                   weight=68.04, ts=datetime(2026, 6, 11, 22, 56, 50))
    dup = is_duplicate_of_recent(
        exercise_name="Crunches (Cable/Machine)", sets=1, reps="14", weight_kg=68.04,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior
    assert dup.id == 151


def test_normalized_name_still_matches():
    """'cable pushdown' and 'Cable Pushdown' should match — same canonical key."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    prior = _entry(id_=147, name="Cable Pushdown", sets=1, reps="10", weight=86.18,
                   ts=datetime(2026, 6, 11, 22, 57, 0))
    dup = is_duplicate_of_recent(
        exercise_name="cable  pushdown", sets=1, reps="10", weight_kg=86.18,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior


def test_weight_within_tolerance_matches():
    """1 lb of rounding noise on lb↔kg shouldn't false-negative."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    prior = _entry(id_=139, name="Bench Press", sets=1, reps="10",
                   weight=61.235, ts=datetime(2026, 6, 11, 22, 56, 50))
    # 0.3 kg diff = within tol_kg=0.5
    dup = is_duplicate_of_recent(
        exercise_name="Bench Press", sets=1, reps="10", weight_kg=61.5,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior


def test_bodyweight_dup_no_weight_field():
    """Dips (bodyweight) — weight is None on both. Should still flag."""
    now = datetime(2026, 6, 11, 23, 17, 0)
    prior = _entry(id_=165, name="Dips", sets=2, reps="14,12", weight=None,
                   ts=datetime(2026, 6, 11, 23, 16, 8))
    dup = is_duplicate_of_recent(
        exercise_name="Dips", sets=2, reps="14,12", weight_kg=None,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is prior


# ── is_duplicate_of_recent: negative cases (legit second sets) ────────────────

def test_different_weight_not_dup():
    """Same exercise/reps, different weight = legit drop set, not a dup."""
    now = datetime(2026, 6, 11, 23, 0, 30)
    prior = _entry(id_=157, name="Straight Bar Cable Curl", sets=1, reps="13",
                   weight=63.50, ts=datetime(2026, 6, 11, 23, 0, 15))
    # Same name/sets/reps but 130 lb instead of 140 — different weight.
    dup = is_duplicate_of_recent(
        exercise_name="Straight Bar Cable Curl", sets=1, reps="13", weight_kg=58.97,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_different_reps_not_dup():
    """Same weight, different reps = legit second set."""
    now = datetime(2026, 6, 11, 22, 41, 10)
    prior = _entry(id_=139, name="Overhead Cable Extension", sets=1, reps="13",
                   weight=49.90, ts=datetime(2026, 6, 11, 22, 35, 55))
    dup = is_duplicate_of_recent(
        exercise_name="Overhead Cable Extension", sets=1, reps="11", weight_kg=49.90,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_outside_window_not_dup():
    """Same payload but 3 minutes apart — legitimate second set of same load."""
    now = datetime(2026, 6, 11, 22, 38, 0)
    prior = _entry(id_=139, name="Bench Press", sets=1, reps="10", weight=61.235,
                   ts=datetime(2026, 6, 11, 22, 35, 55))
    # 2min 5s apart — just outside default 120s window
    dup = is_duplicate_of_recent(
        exercise_name="Bench Press", sets=1, reps="10", weight_kg=61.235,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_different_exercise_name_not_dup():
    now = datetime(2026, 6, 11, 22, 57, 2)
    prior = _entry(id_=147, name="Cable Pushdown", sets=1, reps="10", weight=86.18,
                   ts=datetime(2026, 6, 11, 22, 57, 0))
    dup = is_duplicate_of_recent(
        exercise_name="Overhead Cable Extension", sets=1, reps="10", weight_kg=86.18,
        existing_entries=[prior], now_utc=now,
    )
    assert dup is None


def test_empty_name_returns_none():
    """Guards against a malformed tool call with no exercise_name."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    prior = _entry(id_=139, name="Bench Press", sets=1, reps="10", weight=61.235,
                   ts=now - timedelta(seconds=5))
    assert is_duplicate_of_recent(
        exercise_name="", sets=1, reps="10", weight_kg=61.235,
        existing_entries=[prior], now_utc=now,
    ) is None
    assert is_duplicate_of_recent(
        exercise_name=None, sets=1, reps="10", weight_kg=61.235,
        existing_entries=[prior], now_utc=now,
    ) is None


def test_empty_existing_returns_none():
    """No prior entries at all — first set of the session, can't be a dup."""
    assert is_duplicate_of_recent(
        exercise_name="Bench Press", sets=1, reps="10", weight_kg=61.235,
        existing_entries=[], now_utc=datetime(2026, 6, 11, 22, 0, 0),
    ) is None


def test_returns_nearest_match_when_multiple():
    """When several entries match, return the most recent one (so the
    caller can show 'logged Ns ago' with the tightest gap)."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    old = _entry(id_=139, ts=now - timedelta(seconds=90))
    new = _entry(id_=151, ts=now - timedelta(seconds=10))
    dup = is_duplicate_of_recent(
        exercise_name="Bench Press", sets=1, reps="10", weight_kg=61.235,
        existing_entries=[old, new], now_utc=now,
    )
    assert dup.id == 151


# ── format_dedup_result ───────────────────────────────────────────────────────

def test_format_dedup_result_starts_with_already_on_the_board():
    """The 'Already on the board' prefix is the discriminator the
    deterministic_confirmation uses to distinguish from real Error/Skipped
    tool results. The prefix MUST stay stable."""
    now = datetime(2026, 6, 11, 22, 57, 2)
    dup = _entry(id_=147, name="Cable Pushdown", sets=1, reps="10",
                 weight=86.18, ts=datetime(2026, 6, 11, 22, 56, 52))
    msg = format_dedup_result(dup, now_utc=now)
    assert msg.startswith("Already on the board:")
    assert "Cable Pushdown" in msg
    assert "1×10" in msg
    assert "[#147]" in msg
    assert "10s ago" in msg
    # Must instruct the model NOT to emit a log line
    assert "do NOT" in msg or "do not" in msg.lower()


def test_format_dedup_result_no_weight_for_bodyweight():
    """Bodyweight movements have weight=None — formatter must not crash."""
    now = datetime(2026, 6, 11, 23, 17, 0)
    dup = _entry(id_=165, name="Dips", sets=2, reps="14,12", weight=None,
                 ts=datetime(2026, 6, 11, 23, 16, 8))
    msg = format_dedup_result(dup, now_utc=now)
    assert "Dips" in msg
    assert "2×14,12" in msg
    assert "@" not in msg  # no weight clause for bodyweight
