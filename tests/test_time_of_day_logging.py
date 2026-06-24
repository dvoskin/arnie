"""Time-of-day logging: _combine_local_time turns a local calendar date + a
free-form clock time into a NAIVE UTC datetime (the storage + iOS-display
convention). Covers parsing variants and timezone conversion."""
from datetime import date, datetime

from handlers.tool_executor import _combine_local_time


def test_morning_time_eastern_converts_to_utc():
    # 8:30am on 2026-06-24 in New York (EDT, UTC-4) -> 12:30 UTC, naive.
    out = _combine_local_time(date(2026, 6, 24), "8:30am", "America/New_York")
    assert out == datetime(2026, 6, 24, 12, 30)
    assert out.tzinfo is None


def test_24h_and_pm_and_words():
    assert _combine_local_time(date(2026, 6, 24), "13:45", "UTC") == datetime(2026, 6, 24, 13, 45)
    assert _combine_local_time(date(2026, 6, 24), "7 pm", "UTC") == datetime(2026, 6, 24, 19, 0)
    assert _combine_local_time(date(2026, 6, 24), "noon", "UTC") == datetime(2026, 6, 24, 12, 0)
    assert _combine_local_time(date(2026, 6, 24), "midnight", "UTC") == datetime(2026, 6, 24, 0, 0)


def test_12am_and_12pm_edge():
    assert _combine_local_time(date(2026, 6, 24), "12am", "UTC") == datetime(2026, 6, 24, 0, 0)
    assert _combine_local_time(date(2026, 6, 24), "12pm", "UTC") == datetime(2026, 6, 24, 12, 0)


def test_unparseable_or_missing_returns_none():
    assert _combine_local_time(date(2026, 6, 24), "", "UTC") is None
    assert _combine_local_time(date(2026, 6, 24), None, "UTC") is None
    assert _combine_local_time(date(2026, 6, 24), "whenever", "UTC") is None
    assert _combine_local_time(date(2026, 6, 24), "99:99", "UTC") is None
    assert _combine_local_time(None, "8:30am", "UTC") is None


def test_bad_timezone_falls_back_gracefully():
    # An unknown tz must not raise — falls back to UTC.
    out = _combine_local_time(date(2026, 6, 24), "10:00", "Not/AZone")
    assert out == datetime(2026, 6, 24, 10, 0)
