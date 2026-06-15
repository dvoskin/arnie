"""Behavioral signals (G) — turning logged data into inference fuel."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

from memory.behavioral_signals import (
    adherence_summary, strength_progression, meal_timing_summary,
    recovery_summary, build_behavioral_block,
)


def _log(d, cal, pro, workout, food=None, ex=None):
    return NS(date=d, total_calories=cal, total_protein=pro,
              workout_completed=workout, food_entries=food or [],
              exercise_entries=ex or [])


def _prefs(cal=2000, pro=180):
    return NS(calorie_target=cal, protein_target=pro)


def test_adherence_splits_train_vs_rest():
    mon = date(2026, 6, 1)  # Monday
    logs = []
    for i in range(8):
        d = mon + timedelta(days=i)
        workout = i % 2 == 0
        pro = 190 if workout else 120  # protein clearly slips on rest days
        logs.append(_log(d, 1900, pro, workout))
    out = adherence_summary(logs, _prefs())
    assert "training-day protein" in out and "rest-day" in out
    assert "adherence" in out


def test_adherence_empty_without_targets_or_data():
    assert adherence_summary([], _prefs()) == ""
    logs = [_log(date(2026, 6, 1), 1900, 180, True)]
    assert adherence_summary(logs, None) == ""


def test_strength_progression_detects_rising_lift():
    t0 = datetime(2026, 6, 1, 18)
    t1 = datetime(2026, 6, 20, 18)
    # bench e1rm clearly rises: 60kg x5 → 75kg x5
    ex0 = NS(exercise_name="Incline Bench", weight=60.0, reps="5", timestamp=t0)
    ex1 = NS(exercise_name="Incline Bench", weight=75.0, reps="5", timestamp=t1)
    logs = [_log(t0.date(), 1900, 180, True, ex=[ex0]),
            _log(t1.date(), 1900, 180, True, ex=[ex1])]
    out = strength_progression(logs)
    assert "Incline Bench" in out and "↑" in out


def test_strength_progression_needs_two_sessions():
    ex = NS(exercise_name="Squat", weight=100.0, reps="5",
            timestamp=datetime(2026, 6, 1, 18))
    assert strength_progression([_log(date(2026, 6, 1), 1900, 180, True, ex=[ex])]) == ""


def test_meal_timing_flags_late_night():
    logs = []
    for i in range(6):
        d = date(2026, 6, 1) + timedelta(days=i)
        late = NS(meal_time=datetime(d.year, d.month, d.day, 23, 30),
                  timestamp=None, meal_type="snack")
        lunch = NS(meal_time=datetime(d.year, d.month, d.day, 12, 0),
                   timestamp=None, meal_type="lunch")
        logs.append(_log(d, 1900, 180, False, food=[lunch, late]))
    out = meal_timing_summary(logs)
    assert "after 10pm on 6/6 days" in out and "meal split" in out


def test_recovery_summary_reports_averages_and_trend():
    base = date(2026, 6, 1)
    snaps = [NS(recovery_score=70 - i * 4, sleep_hours=7.0, hrv=65,
                date=base + timedelta(days=i), received_at=None) for i in range(6)]
    out = recovery_summary(snaps)
    assert "recovery avg" in out and "↓" in out  # declining recovery
    assert "sleep avg" in out


def test_build_block_empty_when_no_data():
    assert build_behavioral_block([], [], [], None, None) == ""
