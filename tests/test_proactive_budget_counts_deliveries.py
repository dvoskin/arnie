"""The proactive cadence budget counts DELIVERIES, not conversation rows.

`DeliveryAttempt` was built to end an ambiguity its own docstring names: a
proactive `conversation_logs` row once meant "we reached the send function",
covering a delivered push and a total failure alike, and the 24h cadence budget
read that row — so a user whose pushes ALL FAILED was rate-limited into silence
as though they were being reached. The budget kept reading the wrong table; this
pins the fix, which was previously covered by no test at all (the delivery tests
monkeypatch the budget out).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

import scheduler.proactive_scheduler as PS
from db.models import ConversationLog, DeliveryAttempt


async def _add_attempt(db, user_id, status, *, minutes_ago):
    db.add(DeliveryAttempt(
        user_id=user_id, status=status, channel="ios", slot_key="morning_checkin",
        attempted_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        accepted_at=(datetime.utcnow() - timedelta(minutes=minutes_ago)
                     if status in ("accepted", "delivered") else None)))
    await db.commit()


@pytest.mark.asyncio
async def test_failed_deliveries_do_not_count_against_the_budget(db, make_user, monkeypatch):
    # The regression itself: every push failed, so the user was reached zero
    # times. The budget must let the next nudge through, not silence them.
    monkeypatch.delenv("PROACTIVE_MIN_GAP_MIN", raising=False)
    monkeypatch.delenv("PROACTIVE_DAILY_CAP", raising=False)
    user = await make_user(telegram_id="pb1")
    for _ in range(5):
        await _add_attempt(db, user.id, "failed", minutes_ago=3)
    assert await PS._within_proactive_budget(db, user.id, "morning_checkin") is True


@pytest.mark.asyncio
async def test_a_recent_accepted_delivery_trips_the_gap(db, make_user, monkeypatch):
    monkeypatch.delenv("PROACTIVE_MIN_GAP_MIN", raising=False)
    monkeypatch.delenv("PROACTIVE_DAILY_CAP", raising=False)
    user = await make_user(telegram_id="pb2")
    await _add_attempt(db, user.id, "accepted", minutes_ago=5)   # < 180-min gap
    assert await PS._within_proactive_budget(db, user.id, "morning_checkin") is False


@pytest.mark.asyncio
async def test_accepted_deliveries_reach_the_daily_cap(db, make_user, monkeypatch):
    monkeypatch.delenv("PROACTIVE_MIN_GAP_MIN", raising=False)
    monkeypatch.delenv("PROACTIVE_DAILY_CAP", raising=False)
    user = await make_user(telegram_id="pb3")
    # Three accepted deliveries, all past the 180-min gap but within 24h: the cap
    # (moderate = 3), not the gap, is what blocks the fourth.
    for h in (4, 6, 9):
        await _add_attempt(db, user.id, "accepted", minutes_ago=h * 60)
    assert await PS._within_proactive_budget(db, user.id, "morning_checkin") is False


@pytest.mark.asyncio
async def test_conversation_logs_no_longer_move_the_budget(db, make_user, monkeypatch):
    # Proactive history rows exist but NO delivery attempts: the budget must not
    # see them anymore. Otherwise the gate is still coupled to a write it should
    # not depend on.
    monkeypatch.delenv("PROACTIVE_MIN_GAP_MIN", raising=False)
    monkeypatch.delenv("PROACTIVE_DAILY_CAP", raising=False)
    user = await make_user(telegram_id="pb4")
    for _ in range(5):
        db.add(ConversationLog(user_id=user.id, raw_message="", response="hey",
                               source_type="proactive",
                               timestamp=datetime.utcnow() - timedelta(minutes=5)))
    await db.commit()
    assert await PS._within_proactive_budget(db, user.id, "morning_checkin") is True


@pytest.mark.asyncio
async def test_only_deliveries_inside_the_window_count(db, make_user, monkeypatch):
    # An accepted delivery from 30 hours ago is outside the rolling 24h and must
    # not count, so a user quiet for a day is reachable again.
    monkeypatch.delenv("PROACTIVE_MIN_GAP_MIN", raising=False)
    monkeypatch.delenv("PROACTIVE_DAILY_CAP", raising=False)
    user = await make_user(telegram_id="pb5")
    await _add_attempt(db, user.id, "accepted", minutes_ago=30 * 60)
    assert await PS._within_proactive_budget(db, user.id, "morning_checkin") is True
