"""City -> IANA timezone resolution (drives the 9am-9pm proactive window)."""
import pytest
import pytz
from core.timezones import resolve_timezone


@pytest.mark.parametrize("text,expected", [
    ("austin", "America/Chicago"),
    ("NYC", "America/New_York"),
    ("new york", "America/New_York"),
    ("san francisco ca", "America/Los_Angeles"),
    ("London, UK", "Europe/London"),
    ("tokyo", "Asia/Tokyo"),
    ("i'm in austin texas", "America/Chicago"),
    ("denver co", "America/Denver"),
    ("miami", "America/New_York"),
    ("texas", "America/Chicago"),
    ("california", "America/Los_Angeles"),
])
def test_known_locations(text, expected):
    assert resolve_timezone(text) == expected


@pytest.mark.parametrize("text", ["asdfqwer", "", "   ", "12345"])
def test_unknown_returns_none(text):
    assert resolve_timezone(text) is None


def test_all_results_are_valid_iana():
    for text in ["nyc", "london", "tokyo", "sydney", "mumbai", "berlin", "toronto"]:
        tz = resolve_timezone(text)
        assert tz in pytz.all_timezones, tz
