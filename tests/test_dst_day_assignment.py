"""DST-boundary pins for the LOGGING-day-assignment helpers.

The day-assignment functions are DST-safe (they convert a UTC instant into the
user's zone via pytz before applying the rollover-hour grace), but that
behavior was previously UNPINNED. These tests freeze the clock at UTC instants
that straddle the two US DST transitions and assert the NY calendar day / log
day each helper returns — so a future refactor that breaks localization is
caught.

Targets (all default-rollover, LOGGING_DAY_ROLLOVER_HOUR=0):
  • db.queries._user_today(user_timezone)          — the user's current log day
  • db.queries._logging_day_of(dt_utc, user_tz)     — the log day a UTC ts belongs to
  • handlers.tool_executor._parse_log_date(s, tz)   — "yesterday"/ISO parsing

2026 US transitions (America/New_York):
  • Spring forward: 2026-03-08, 02:00 EST → 03:00 EDT (the 2am hour is skipped)
  • Fall back:      2026-11-01, 02:00 EDT → 01:00 EST (the 1am hour repeats — "fold")
"""
from datetime import date, datetime

from freezegun import freeze_time

import db.queries as Q
from db.queries import _user_today, _logging_day_of
from handlers.tool_executor import _parse_log_date

NY = "America/New_York"       # EST (UTC-5) winter, EDT (UTC-4) summer
PHOENIX = "America/Phoenix"   # UTC-7 all year — no DST (control)


# ── Sanity: the default rollover is midnight (import the real value) ──────────

def test_default_rollover_hour_is_midnight():
    """These pins assume the default (0). If someone flips the env default, this
    reminds them the DST expectations below were written for a midnight rollover."""
    assert Q.LOGGING_DAY_ROLLOVER_HOUR == 0


# ── Spring forward (2026-03-08, 02:00 EST → 03:00 EDT) ────────────────────────

@freeze_time("2026-03-08 06:30:00")  # 01:30 EST — just BEFORE the skip, still Mar 8
def test_user_today_spring_before_transition():
    assert _user_today(NY) == date(2026, 3, 8)


@freeze_time("2026-03-08 07:30:00")  # 03:30 EDT — just AFTER the skip, still Mar 8
def test_user_today_spring_after_transition():
    # The 02:00→03:00 skip does not change the calendar day — both sides are Mar 8.
    assert _user_today(NY) == date(2026, 3, 8)


def test_logging_day_of_spring_boundary_across_local_midnight():
    """A UTC timestamp near local midnight must land on the correct NY log day
    across the spring-forward day (localization, then rollover)."""
    # 04:30 UTC = 23:30 EST on Mar 7 (pre-midnight) → previous day
    assert _logging_day_of(datetime(2026, 3, 8, 4, 30), NY) == date(2026, 3, 7)
    # 05:30 UTC = 00:30 EST on Mar 8 (post-midnight) → the new day
    assert _logging_day_of(datetime(2026, 3, 8, 5, 30), NY) == date(2026, 3, 8)
    # 07:30 UTC = 03:30 EDT on Mar 8 (after the skip) → still Mar 8
    assert _logging_day_of(datetime(2026, 3, 8, 7, 30), NY) == date(2026, 3, 8)


# ── Fall back (2026-11-01, 02:00 EDT → 01:00 EST — the 01:xx hour repeats) ─────

@freeze_time("2026-11-01 05:30:00")  # 01:30 EDT — the FIRST pass through 01:30
def test_user_today_fall_first_pass():
    assert _user_today(NY) == date(2026, 11, 1)


@freeze_time("2026-11-01 06:30:00")  # 01:30 EST — the SECOND pass through 01:30
def test_user_today_fall_second_pass():
    # Both folds of the repeated 01:30 hour are still the same calendar day.
    assert _user_today(NY) == date(2026, 11, 1)


def test_logging_day_of_fall_both_folds_and_midnight_boundary():
    """The repeated 01:30 hour (both folds) maps to Nov 1, and the pre/post local
    midnight boundary picks the right day across the transition."""
    # Both passes through 01:30 local land on Nov 1.
    assert _logging_day_of(datetime(2026, 11, 1, 5, 30), NY) == date(2026, 11, 1)
    assert _logging_day_of(datetime(2026, 11, 1, 6, 30), NY) == date(2026, 11, 1)
    # 03:30 UTC = 23:30 EDT on Oct 31 (pre-midnight) → previous day
    assert _logging_day_of(datetime(2026, 11, 1, 3, 30), NY) == date(2026, 10, 31)
    # 04:30 UTC = 00:30 EDT on Nov 1 (post-midnight) → the new day
    assert _logging_day_of(datetime(2026, 11, 1, 4, 30), NY) == date(2026, 11, 1)


# ── Non-DST control (America/Phoenix, UTC-7 all year) ─────────────────────────

@freeze_time("2026-03-08 06:30:00")  # 23:30 MST on Mar 7 (no spring-forward in AZ)
def test_user_today_phoenix_control_ignores_dst():
    # Phoenix never shifts, so 06:30 UTC is 23:30 the PRIOR day — Mar 7 — on both
    # the spring and fall dates, unlike New York.
    assert _user_today(PHOENIX) == date(2026, 3, 7)


def test_logging_day_of_phoenix_control():
    # Fixed UTC-7 offset on both transition dates → no DST wobble.
    assert _logging_day_of(datetime(2026, 3, 8, 6, 30), PHOENIX) == date(2026, 3, 7)
    assert _logging_day_of(datetime(2026, 11, 1, 6, 30), PHOENIX) == date(2026, 10, 31)


# ── _parse_log_date anchors relative offsets on the DST-aware logging day ──────

@freeze_time("2026-03-08 07:30:00")  # 03:30 EDT Mar 8 → logging_today = Mar 8
def test_parse_log_date_spring_relative_and_iso():
    assert _parse_log_date("yesterday", NY) == date(2026, 3, 7)
    assert _parse_log_date("2 days ago", NY) == date(2026, 3, 6)
    assert _parse_log_date("3 days ago", NY) == date(2026, 3, 5)
    # ISO equal to the current calendar day is accepted (not falsely "future").
    assert _parse_log_date("2026-03-08", NY) == date(2026, 3, 8)
    # A forward date is rejected.
    assert _parse_log_date("2026-03-09", NY) is None
    # None means "use today's log".
    assert _parse_log_date(None, NY) is None


@freeze_time("2026-11-01 06:30:00")  # 01:30 EST Nov 1 (second fold) → logging_today = Nov 1
def test_parse_log_date_fall_relative_and_iso():
    assert _parse_log_date("yesterday", NY) == date(2026, 10, 31)
    assert _parse_log_date("2026-11-01", NY) == date(2026, 11, 1)
