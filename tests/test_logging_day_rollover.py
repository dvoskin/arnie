"""Logging-day rollover.

DEFAULT is MIDNIGHT (LOGGING_DAY_ROLLOVER_HOUR=0) — the new day's log becomes
available at 12am, matching the iOS app, which uses the device calendar date for
"today" everywhere. (Before, a 4am grace left the app showing yesterday's totals
between midnight and 4am — "the next day's log doesn't become available at 12am".)

The small-hours GRACE (late-night logs counting toward the PREVIOUS day) is still
supported and env-tunable via LOGGING_DAY_ROLLOVER_HOUR — it's just off by
default now; the rare late-night case is covered by retroactive logging instead.
Dedup/recall stay consistent at any value (all anchor on _user_today).
"""
from datetime import date

from freezegun import freeze_time

import db.queries as Q
from db.queries import _user_today

NY = "America/New_York"  # EDT (UTC-4) in June


def test_default_rollover_is_midnight():
    assert Q.LOGGING_DAY_ROLLOVER_HOUR == 0


@freeze_time("2026-06-23 04:02:00")  # 00:02 EDT Jun 23
def test_just_after_midnight_is_the_new_day_by_default():
    # Midnight rollover → 12:02am is already the new calendar day.
    assert _user_today(NY) == date(2026, 6, 23)


@freeze_time("2026-06-23 16:00:00")  # 12:00 EDT Jun 23
def test_daytime_counts_as_current_day():
    assert _user_today(NY) == date(2026, 6, 23)


# ── The grace window still works when explicitly configured (> 0) ─────────────

@freeze_time("2026-06-23 04:02:00")  # 00:02 EDT Jun 23 — before a 4am grace
def test_grace_counts_as_previous_day_when_enabled(monkeypatch):
    monkeypatch.setattr(Q, "LOGGING_DAY_ROLLOVER_HOUR", 4)
    assert _user_today(NY) == date(2026, 6, 22)


@freeze_time("2026-06-23 08:00:00")  # 04:00 EDT Jun 23 — at the configured rollover
def test_at_configured_rollover_counts_as_current_day(monkeypatch):
    monkeypatch.setattr(Q, "LOGGING_DAY_ROLLOVER_HOUR", 4)
    assert _user_today(NY) == date(2026, 6, 23)
