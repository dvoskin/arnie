"""Grace-window day rollover: late-night logging counts toward the PREVIOUS day.

Regression for Danny's 2026-06-23 incident — food logged at 12:02am EDT was
splitting across two days, which also blinded the dedup guard (it scopes to
"today's" log). _user_today now rolls the logging day over at
LOGGING_DAY_ROLLOVER_HOUR (4am local), not at midnight.
"""
from datetime import date

from freezegun import freeze_time

from db.queries import _user_today, LOGGING_DAY_ROLLOVER_HOUR

NY = "America/New_York"  # EDT (UTC-4) in June


def test_rollover_hour_is_four():
    assert LOGGING_DAY_ROLLOVER_HOUR == 4


@freeze_time("2026-06-23 04:02:00")  # 00:02 EDT Jun 23 — before rollover
def test_just_after_midnight_counts_as_previous_day():
    assert _user_today(NY) == date(2026, 6, 22)


@freeze_time("2026-06-23 07:59:00")  # 03:59 EDT Jun 23 — still before rollover
def test_pre_rollover_counts_as_previous_day():
    assert _user_today(NY) == date(2026, 6, 22)


@freeze_time("2026-06-23 08:00:00")  # 04:00 EDT Jun 23 — at the rollover
def test_at_rollover_counts_as_current_day():
    assert _user_today(NY) == date(2026, 6, 23)


@freeze_time("2026-06-23 16:00:00")  # 12:00 EDT Jun 23 — well past rollover
def test_daytime_counts_as_current_day():
    assert _user_today(NY) == date(2026, 6, 23)


@freeze_time("2026-06-23 02:30:00")  # 02:30 UTC — before 4am in UTC too
def test_rollover_applies_in_utc_default():
    assert _user_today("UTC") == date(2026, 6, 22)
