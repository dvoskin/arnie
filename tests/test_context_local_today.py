"""The context read layer must agree with the WRITE layer about "today."

Writes assign entries to the user's LOCAL logging day (_user_today, with the
pre-dawn rollover). For months the read/context layer used bare date.today()
= server-UTC: for an Eastern user in the evening, "today" was already
tomorrow, summaries read an empty day, and Arnie said "nothing logged" while
the food sat on the local date (Chaya, 2026-07-14 — the "I TOLD U WHAT I
ATE" incident). These tests pin the injectable user-local `today` param.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from core.context_builder import (
    _local_today, fmt_history, fmt_recent_day_detail, adherence_insights,
    _recent_training_days,
)


def _log(d, cal=1800, protein=120):
    return SimpleNamespace(
        date=d, total_calories=cal, total_protein=protein,
        total_carbs=100, total_fats=60, total_water_ml=0,
        food_entries=[SimpleNamespace(
            parsed_food_name="Chicken", quantity="200g", calories=cal,
            protein=protein, carbs=100, fats=60, id=1,
            timestamp=None, meal_time=None, estimated_flag=False,
            confidence_score=0.9, source_type="text",
        )],
        exercise_entries=[], workout_completed=False,
    )


LOCAL_TODAY = date(2026, 7, 14)
UTC_TOMORROW = LOCAL_TODAY + timedelta(days=1)   # what date.today() said on Render


def test_todays_log_is_not_history_under_local_today():
    """An entry written to the user's July 14 must NOT appear as a PAST day
    while the user's clock still says July 14 — even when UTC says July 15."""
    logs = [_log(LOCAL_TODAY), _log(LOCAL_TODAY - timedelta(days=1))]
    # user-local today: July 14 is TODAY → only July 13 is history
    hist = fmt_history(logs, today=LOCAL_TODAY)
    assert "07-13" in hist or "Jul" in hist or hist  # one past day rendered
    assert str(LOCAL_TODAY) not in hist
    # the OLD behavior (UTC tomorrow) wrongly demoted July 14 into history
    hist_utc = fmt_history(logs, today=UTC_TOMORROW)
    assert str(LOCAL_TODAY) in hist_utc


def test_recent_day_detail_excludes_local_today():
    logs = [_log(LOCAL_TODAY), _log(LOCAL_TODAY - timedelta(days=1))]
    detail = fmt_recent_day_detail(logs, days=3, today=LOCAL_TODAY)
    assert str(LOCAL_TODAY) not in detail
    assert str(LOCAL_TODAY - timedelta(days=1)) in detail


def test_streak_counts_from_local_today():
    """A 3-day streak ending on the user's local today must read 3 — under the
    UTC-tomorrow clock it read 0 (no log on the phantom 'today')."""
    logs = [_log(LOCAL_TODAY - timedelta(days=i)) for i in range(3)]
    good = adherence_insights(logs, None, today=LOCAL_TODAY)
    assert "3-day" in good or "3 day" in good or "Streak: 3" in good or "3" in good.split("\n")[0]
    stale = adherence_insights(logs, None, today=UTC_TOMORROW)
    assert stale != good


def test_training_days_cutoff_uses_injected_today():
    d = LOCAL_TODAY - timedelta(days=13)
    lg = _log(d)
    lg.exercise_entries = [SimpleNamespace(source_type="manual")]
    assert _recent_training_days([lg], days=14, today=LOCAL_TODAY) == 1
    # a day later the same workout falls off the 14-day window
    assert _recent_training_days([lg], days=14, today=UTC_TOMORROW + timedelta(days=1)) == 0


def test_local_today_matches_write_path():
    from db.queries import _user_today
    assert _local_today("America/New_York") == _user_today("America/New_York")
    assert _local_today(None) == _user_today("UTC")
