"""fmt_today_weight — Arnie must know a weigh-in already happened TODAY.

Body weight lives in BodyMetric (user-scoped), so the [TODAY] block (fmt_log,
which only sees the DailyLog) never surfaced it. Without an explicit line Arnie
acted like he didn't know when the user said they'd already weighed in. These
pin the authoritative line, including the local-vs-UTC day boundary (BodyMetric
timestamps are naive UTC; "today" is the user's local day).
"""
from datetime import datetime, date
from types import SimpleNamespace

from core.context_builder import fmt_today_weight


def _w(weight_kg, ts):
    return SimpleNamespace(weight_kg=weight_kg, timestamp=ts)


# Anchor "today" deterministically via today_log.date so the test never depends
# on the wall clock. 2026-06-29 is EDT (UTC-4).
_TODAY_LOG = SimpleNamespace(date=date(2026, 6, 29))
_NY_USER = SimpleNamespace(timezone="America/New_York")


def test_logged_today_surfaces_value_and_time():
    # 2026-06-29 12:00 UTC == 08:00 EDT, same local day → logged today.
    weights = [_w(84.0, datetime(2026, 6, 29, 12, 0))]
    out = fmt_today_weight(weights, _TODAY_LOG, _NY_USER)
    assert "logged today" in out and "✓" in out, out
    assert "185.2 lb" in out, out          # 84.0 kg → 185.2 lb
    assert "84.0 kg" in out, out
    assert "8:00 AM" in out, out           # local clock, not UTC


def test_no_weighins_says_not_logged():
    assert fmt_today_weight([], _TODAY_LOG, _NY_USER) == "Weight: not logged today."


def test_only_past_weighin_says_not_logged():
    weights = [_w(84.0, datetime(2026, 6, 27, 12, 0))]
    assert fmt_today_weight(weights, _TODAY_LOG, _NY_USER) == "Weight: not logged today."


def test_utc_today_but_local_yesterday_is_not_today():
    # 2026-06-29 01:00 UTC == 2026-06-28 21:00 EDT → still YESTERDAY locally,
    # even though the UTC date reads 06-29. Must not be counted as today.
    weights = [_w(84.0, datetime(2026, 6, 29, 1, 0))]
    assert fmt_today_weight(weights, _TODAY_LOG, _NY_USER) == "Weight: not logged today."


def test_utc_next_day_but_local_today_counts():
    # 2026-06-30 02:00 UTC == 2026-06-29 22:00 EDT → TODAY locally.
    weights = [_w(83.5, datetime(2026, 6, 30, 2, 0))]
    out = fmt_today_weight(weights, _TODAY_LOG, _NY_USER)
    assert "logged today" in out, out
    assert "10:00 PM" in out, out


def test_picks_latest_when_multiple_today():
    # weights arrive timestamp-DESC (as get_recent_weights returns them) — the
    # first local-today match is the latest weigh-in.
    weights = [
        _w(83.0, datetime(2026, 6, 29, 23, 0)),   # 19:00 EDT — latest
        _w(84.0, datetime(2026, 6, 29, 12, 0)),   # 08:00 EDT — earlier
    ]
    out = fmt_today_weight(weights, _TODAY_LOG, _NY_USER)
    assert "183.0 lb" in out, out             # 83.0 kg → 183.0, not 84.0's 185.2
    assert "7:00 PM" in out, out
