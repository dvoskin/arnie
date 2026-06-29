"""Daily-Log data fixes (native_data):

1. The 'today' wearable picker must surface a snapshot that CARRIES a recovery
   score, even when a passive Apple Health sync has written a newer (or
   UTC-day-ahead), recovery-less row that would otherwise shadow it. This is the
   exact prod regression: Whoop recovery 34 hidden behind an empty apple_health
   row dated a day ahead.

2. The weight block, when viewing a PAST day, headlines THAT day's weigh-in
   rather than the global latest — so a past Daily Log isn't blank/wrong.
"""
import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import api.native_data as nd


def _fake_db_with_ids(ids):
    """A db whose `execute(select(User.id)...)` resolves to `ids` (the linked set)."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = ids
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _snap(date, source, recovery):
    return SimpleNamespace(date=date, source=source, recovery_score=recovery)


def test_today_picker_prefers_recovery_over_newer_empty_snapshot(monkeypatch):
    # Newest row (apple_health, a day ahead) has NO recovery; older Whoop row does.
    snaps = [
        _snap(dt.date(2026, 6, 29), "apple_health", None),
        _snap(dt.date(2026, 6, 28), "whoop", 34),
        _snap(dt.date(2026, 6, 27), "whoop", 62),
    ]
    monkeypatch.setattr(nd, "get_recent_health_snapshots", AsyncMock(return_value=snaps))
    db = _fake_db_with_ids([26])
    user = SimpleNamespace(id=26, linked_to_user_id=None)

    picked = asyncio.run(nd._today_health_snapshot_linked(db, user))
    assert picked.source == "whoop"
    assert picked.recovery_score == 34   # the most-recent WITH recovery, not the empty newer one


def test_today_picker_falls_back_to_latest_when_none_have_recovery(monkeypatch):
    snaps = [
        _snap(dt.date(2026, 6, 29), "apple_health", None),
        _snap(dt.date(2026, 6, 28), "apple_health", None),
    ]
    monkeypatch.setattr(nd, "get_recent_health_snapshots", AsyncMock(return_value=snaps))
    db = _fake_db_with_ids([26])
    user = SimpleNamespace(id=26, linked_to_user_id=None)

    picked = asyncio.run(nd._today_health_snapshot_linked(db, user))
    assert picked.date == dt.date(2026, 6, 29)   # newest overall when nothing has recovery


def _w(day, kg, source="manual"):
    return SimpleNamespace(timestamp=dt.datetime(2026, 6, day, 8, 0), weight_kg=kg, source=source)


def test_weight_block_past_day_headlines_that_days_weighin():
    weights = [_w(28, 85.9), _w(26, 84.9), _w(24, 85.1)]
    block = nd._weight_block(weights, SimpleNamespace(goal_weight_kg=None), as_of_date=dt.date(2026, 6, 26))
    assert block["latest"]["kg"] == 84.9   # the 26th's weigh-in, not the 28th's


def test_weight_block_today_unchanged_is_global_latest():
    weights = [_w(28, 85.9), _w(26, 84.9)]
    block = nd._weight_block(weights, SimpleNamespace(goal_weight_kg=None), as_of_date=None)
    assert block["latest"]["kg"] == 85.9   # global latest when not scoped to a past day
