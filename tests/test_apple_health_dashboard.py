"""
Apple Health dashboard panel tests.

Apple-Watch users push four metrics via the iOS Shortcut — steps, active
calories, resting calories, sleep. The dashboard's health panel used to be
Whoop-only (gated on whoop_connected AND source=='whoop'), so Apple users saw
none of their data. These tests pin the simplified behavior:

  1. /api/stats (via _build_stats_for_user) exposes the four Apple metrics +
     apple_health_connected, including the newly-serialized resting_calories.
  2. The dashboard ships a dedicated Apple Health panel renderer with a
     settable title.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.app import _build_stats_for_user
from api.templates import _dashboard_html
from db.models import User
from db.queries import upsert_health_snapshot


async def _loaded(db, user_id):
    """Re-fetch the user with preferences eager-loaded, like the prod query does."""
    return (await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.preferences))
    )).scalar_one()


async def test_stats_payload_exposes_apple_metrics(make_user, db):
    u = await make_user(telegram_id="apple-user", name="Wrist")
    await upsert_health_snapshot(
        db, u.id, date.today(),
        source="apple_health",
        steps=9123,
        active_calories=512.0,
        resting_calories=1680.0,
        sleep_hours=7.5,
    )
    user = await _loaded(db, u.id)

    stats = await _build_stats_for_user(db, user)

    # Connection flags reflect Apple, not Whoop.
    assert stats["profile"]["apple_health_connected"] is True
    assert stats["profile"]["whoop_connected"] is False

    today = date.today().isoformat()
    snap = next(h for h in stats["health"] if h["date"] == today)
    assert snap["source"] == "apple_health"
    assert snap["steps"] == 9123
    assert snap["active_calories"] == 512.0
    assert snap["resting_calories"] == 1680.0   # was missing from the payload before
    assert snap["sleep_hours"] == 7.5


async def test_dashboard_wires_apple_health_panel():
    """The dashboard JS must include the Apple panel renderer + settable title,
    and surface exactly the 4 simple metrics."""
    html = _dashboard_html("demo-token", "Wrist")
    assert "renderAppleHealthModule" in html
    assert 'id="health-mod-title"' in html
    assert "apple_health_connected" in html
    # The simple Apple panel labels — and NOT a dependency on Whoop-only stats.
    assert "Resting cal" in html and "Active cal" in html


def test_midnight_scale_sync_stays_on_previous_logging_day():
    """Danny 2026-07-19: manual weigh-in yesterday evening + a 12:03am scale
    sync = ONE logging day (4am rollover), never two adherence marks."""
    from types import SimpleNamespace as NS
    from datetime import datetime
    from api.native_data import _one_per_day_prefer_manual
    rows = [
        NS(weight_kg=89.1, source="manual",
           timestamp=datetime(2026, 7, 19, 1, 30)),    # 9:30pm ET Jul 18
        NS(weight_kg=89.3, source="apple_health",
           timestamp=datetime(2026, 7, 19, 4, 3)),     # 12:03am ET Jul 19 → still Jul 18
    ]
    out = _one_per_day_prefer_manual(rows, "America/New_York")
    assert len(out) == 1, "one logging day must yield one reading"
    assert out[0].source == "manual"
