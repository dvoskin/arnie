"""
reminders_blocked_reason in the /api/stats profile payload (honesty field). The raw
reminders_on bool can read True while a DURABLE upstream scheduler gate silently
drops the user; this field surfaces the FIRST tripped durable gate so the dashboard
reflects deliverability, not just stored intent. Pins:
  • UTC-default user + reminders ON  → 'no_timezone'
  • reminders OFF                     → None (an off toggle is already honest)
  • real tz + allowlist excludes user → 'not_on_allowlist'
  • fully deliverable                 → None
Computed via the real scheduler gate fns (no gate logic reimplemented).
"""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.app import _build_stats_for_user
from db.models import User, UserPreferences


async def _seed(db, *, telegram_id, name, timezone, pref_on=True):
    u = User(telegram_id=telegram_id, name=name, onboarding_completed=True,
             timezone=timezone)
    db.add(u)
    await db.flush()
    db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=pref_on,
                           wake_time="09:00", sleep_time="21:00"))
    await db.commit()
    return u


async def _loaded(db, user_id):
    return (await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.preferences))
    )).scalar_one()


@pytest.mark.asyncio
async def test_utc_user_reminders_on_blocked_no_timezone(monkeypatch, db):
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    u = await _seed(db, telegram_id="utc1", name="Michelle", timezone="UTC")
    stats = await _build_stats_for_user(db, await _loaded(db, u.id))
    assert stats["profile"]["reminders_on"] is True
    assert stats["profile"]["reminders_blocked_reason"] == "no_timezone"


@pytest.mark.asyncio
async def test_reminders_off_has_no_reason(monkeypatch, db):
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    u = await _seed(db, telegram_id="off1", name="Off", timezone="UTC", pref_on=False)
    stats = await _build_stats_for_user(db, await _loaded(db, u.id))
    assert stats["profile"]["reminders_on"] is False
    # toggle is off → dashboard already honest → no blocked reason
    assert stats["profile"]["reminders_blocked_reason"] is None


@pytest.mark.asyncio
async def test_real_tz_excluded_by_allowlist(monkeypatch, db):
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.setenv("PROACTIVE_ALLOWLIST", "999999")
    u = await _seed(db, telegram_id="55", name="Jenny", timezone="America/New_York")
    stats = await _build_stats_for_user(db, await _loaded(db, u.id))
    assert stats["profile"]["reminders_blocked_reason"] == "not_on_allowlist"


@pytest.mark.asyncio
async def test_fully_deliverable_user_has_no_reason(monkeypatch, db):
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    u = await _seed(db, telegram_id="77", name="Danny", timezone="America/New_York")
    stats = await _build_stats_for_user(db, await _loaded(db, u.id))
    # durable gates all pass (global on, not linked, no allowlist, real tz)
    assert stats["profile"]["reminders_blocked_reason"] is None
