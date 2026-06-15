"""parse_natural_period must resolve time-of-day qualifiers to the right DAY, so
the model never has to compute calendar dates itself (the wrong-day narration bug).
"""
from datetime import date

from db.queries import parse_natural_period

# Monday 2026-06-15 → Sun=06-14, Sat=06-13, Fri=06-12
MON = date(2026, 6, 15)


def _day(period):
    r = parse_natural_period(period, MON)
    return r[0] if r else None


def test_time_of_day_qualifiers_resolve_to_the_day():
    assert _day("last friday night") == date(2026, 6, 12)   # was None before (3 words)
    assert _day("friday night") == date(2026, 6, 12)
    assert _day("last friday") == date(2026, 6, 12)
    assert _day("yesterday evening") == date(2026, 6, 14)
    assert _day("yesterday morning") == date(2026, 6, 14)
    assert _day("sunday afternoon") == date(2026, 6, 14)


def test_last_night_is_yesterday():
    assert _day("last night") == date(2026, 6, 14)


def test_tonight_and_this_morning_are_today():
    assert _day("tonight") == MON
    assert _day("this morning") == MON
    assert _day("this evening") == MON


def test_plain_periods_still_work():
    assert _day("yesterday") == date(2026, 6, 14)
    assert _day("friday") == date(2026, 6, 12)
    assert _day("today") == MON
    assert _day("2026-06-12") == date(2026, 6, 12)
