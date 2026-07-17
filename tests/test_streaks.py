"""Streak engine (core/streaks.py) — forgiving consistency chains.

The contract under test:
  * A day counts for `logging` on any food or workout; for `full_day` at ≥1000 kcal.
  * ONE missed day per rolling 7 is bridged; a second inside the window breaks.
  * Today is pending — an empty today neither breaks nor consumes forgiveness.
  * `today` is the user-local logging day supplied by the caller; future-dated
    rows (old LLM date bugs) never count.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from core.streaks import compute_streaks, streaks_context_line, MILESTONES

TODAY = date(2026, 7, 17)


def _log(d, cal=1800, workout=False):
    return SimpleNamespace(date=d, total_calories=cal, workout_completed=workout)


def _days_back(*offsets, cal=1800):
    """Logs at the given day-offsets from TODAY (0 = today)."""
    return [_log(TODAY - timedelta(days=o), cal=cal) for o in offsets]


def test_simple_unbroken_streak():
    s = compute_streaks(_days_back(0, 1, 2, 3), TODAY)
    assert s["logging"]["current"] == 4
    assert s["logging"]["today_done"] is True
    assert s["logging"]["at_risk"] is False


def test_empty_today_is_pending_not_a_miss():
    s = compute_streaks(_days_back(1, 2, 3), TODAY)
    assert s["logging"]["current"] == 3          # chain intact through yesterday
    assert s["logging"]["today_done"] is False
    assert s["logging"]["at_risk"] is True       # ≥3 and unfed today


def test_one_missed_day_is_bridged():
    # Logged 1,2,3 days ago, missed day-4, logged 5,6 — one gap is forgiven.
    s = compute_streaks(_days_back(1, 2, 3, 5, 6), TODAY)
    assert s["logging"]["current"] == 5          # forgiven day contributes nothing


def test_two_misses_in_seven_days_break_the_chain():
    # Gaps at day-2 and day-4 — the second miss inside the rolling week breaks.
    s = compute_streaks(_days_back(1, 3, 5, 6), TODAY)
    assert s["logging"]["current"] == 2          # day-1 + day-3 (one bridge), stop at day-4


def test_misses_far_apart_are_each_forgiven():
    # Gaps at day-3 and day-11: 8 days apart, so each has its own budget.
    offsets = [o for o in range(1, 15) if o not in (3, 11)]
    s = compute_streaks(_days_back(*offsets), TODAY)
    assert s["logging"]["current"] == 12         # whole run holds, both gaps bridged


def test_full_day_requires_qualifying_calories():
    logs = [
        _log(TODAY - timedelta(days=1), cal=2200),
        _log(TODAY - timedelta(days=2), cal=999),    # logged, but not a full day
        _log(TODAY - timedelta(days=3), cal=1500),
    ]
    s = compute_streaks(logs, TODAY)
    assert s["logging"]["current"] == 3
    # 999-kcal day is a full_day GAP — bridged by forgiveness, not counted.
    assert s["full_day"]["current"] == 2
    assert s["full_day"]["kcal"] == 1000


def test_workout_counts_for_logging_not_full_day():
    logs = [_log(TODAY - timedelta(days=1), cal=0, workout=True)]
    s = compute_streaks(logs, TODAY)
    assert s["logging"]["current"] == 1
    assert s["full_day"]["current"] == 0


def test_future_dated_rows_never_count():
    logs = _days_back(0, 1) + [_log(TODAY + timedelta(days=1), cal=3000)]
    s = compute_streaks(logs, TODAY)
    assert s["logging"]["current"] == 2
    assert s["logging"]["best"] == 2


def test_best_survives_a_broken_chain():
    # A 6-day run two weeks ago, hard-broken (3 consecutive misses), then 2 fresh days.
    old = [o for o in range(10, 16)]
    s = compute_streaks(_days_back(0, 1, *old), TODAY)
    assert s["logging"]["current"] == 2
    assert s["logging"]["best"] >= 6


def test_empty_history():
    s = compute_streaks([], TODAY)
    for chain in (s["logging"], s["full_day"]):
        assert chain["current"] == 0 and chain["best"] == 0
        assert chain["at_risk"] is False


def test_context_line_thresholds():
    # Short quiet streak → no token spend.
    assert streaks_context_line(compute_streaks(_days_back(0, 1), TODAY)) is None
    # Established chain → present.
    line = streaks_context_line(compute_streaks(_days_back(0, 1, 2, 3, 4), TODAY))
    assert line and "[STREAK]" in line and "5d" in line
    # At-risk chain → flags the nudge.
    risk = streaks_context_line(compute_streaks(_days_back(1, 2, 3, 4), TODAY))
    assert risk and "AT RISK" in risk


def test_milestone_flagged_in_context():
    line = streaks_context_line(compute_streaks(_days_back(0, 1, 2, 3, 4, 5, 6), TODAY))
    assert line and "7-day milestone" in line
    assert 7 in MILESTONES
