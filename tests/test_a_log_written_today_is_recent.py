"""A log the user is writing into right now counts as recent (streak bug).

Found 2026-07-31 00:26 UTC: `test_widget_endpoint` began failing — a user with
a 600-calorie meal already logged read `streak == 0`.

The cause is a date comparison between two different clocks. Every `DailyLog`
is dated by `_user_today(tz)`, the USER's logging day. `get_recent_logs`
bounded its window with `date.today()`, the SERVER's calendar date. When the
user's day is ahead of the server's, the query excluded the log they were
writing into — so the streak saw no logging today, and so did history, trends
and the dashboard's available dates.

Timezones run UTC-12..UTC+14, so against a UTC server everyone from Europe
eastward crosses midnight first and spends those hours invisible to this
function. It is not an exotic edge: it is most of the world, every day.

These tests do not depend on the wall clock — they date a log relative to the
server's own `date.today()`, so they fail the same way at any hour.
"""
from datetime import date, timedelta

import pytest

from db.models import DailyLog
from db.queries import get_recent_logs


async def _log_on(db, user_id, day, calories=600.0):
    log = DailyLog(user_id=user_id, date=day, total_calories=calories)
    db.add(log)
    await db.commit()
    return log


async def test_a_user_ahead_of_the_server_is_not_invisible(db, make_user):
    """The bug, deterministically: a log dated one day ahead of the server —
    which is simply 'today' for anyone east of it — must be returned."""
    user = await make_user(telegram_id="ios:ahead")
    await _log_on(db, user.id, date.today() + timedelta(days=1))

    logs = await get_recent_logs(db, user.id, days=7)
    assert logs, "the user's current day was excluded from their own history"


async def test_the_streak_sees_a_meal_logged_on_the_users_day(db, make_user):
    """The user-visible symptom: the flame goes out with a meal on the board."""
    from core.streaks import compute_streaks

    user = await make_user(telegram_id="ios:flame")
    user_day = date.today() + timedelta(days=1)
    await _log_on(db, user.id, user_day)

    logs = await get_recent_logs(db, user.id, days=90)
    streaks = compute_streaks(logs, user_day)
    assert streaks["logging"]["current"] >= 1


async def test_the_server_day_still_works(db, make_user):
    """The ordinary case — user and server on the same date — is unchanged."""
    user = await make_user(telegram_id="ios:same")
    await _log_on(db, user.id, date.today())
    assert await get_recent_logs(db, user.id, days=7)


async def test_a_genuinely_future_dated_log_is_still_excluded(db, make_user):
    """The guard keeps its job. It exists for the LLM date bug that wrote logs
    days and months out; one day of slack for real timezones does not reopen
    it."""
    user = await make_user(telegram_id="ios:future")
    await _log_on(db, user.id, date.today() + timedelta(days=30))
    assert not await get_recent_logs(db, user.id, days=7)
