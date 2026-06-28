"""Past-day wearable surfacing — the 'wearable data disappears for previous days'
fix. day_data dropped the health block for any non-today date; now the snapshot
FOR the requested date is returned (across linked identities)."""
import datetime

import pytest
from sqlalchemy import select

from db.models import User, HealthSnapshot
from api.native_data import _health_snapshot_for_date_linked

pytestmark = pytest.mark.asyncio


async def test_returns_snapshot_for_a_past_date(db, make_user):
    user = await make_user(timezone="UTC")
    today = datetime.date.today()
    past = today - datetime.timedelta(days=4)
    db.add(HealthSnapshot(user_id=user.id, date=past, recovery_score=62,
                          sleep_hours=7.2, hrv=58, resting_hr=51, strain=11.0))
    db.add(HealthSnapshot(user_id=user.id, date=today, recovery_score=80, sleep_hours=8.0))
    await db.commit()

    snap = await _health_snapshot_for_date_linked(db, user, past)
    assert snap is not None
    assert snap.date == past
    assert snap.recovery_score == 62          # the PAST day's value, not today's


async def test_returns_none_for_a_date_with_no_snapshot(db, make_user):
    user = await make_user(timezone="UTC")
    missing = datetime.date.today() - datetime.timedelta(days=30)
    assert await _health_snapshot_for_date_linked(db, user, missing) is None


async def test_finds_snapshot_on_a_linked_identity(db, make_user):
    """A snapshot synced under a linked identity still surfaces for the canonical
    user's past-day view."""
    canonical = await make_user(telegram_id="canon", timezone="UTC")
    linked = await make_user(telegram_id="linked", timezone="UTC")
    linked.linked_to_user_id = canonical.id
    past = datetime.date.today() - datetime.timedelta(days=3)
    db.add(HealthSnapshot(user_id=linked.id, date=past, recovery_score=55, hrv=44))
    await db.commit()

    snap = await _health_snapshot_for_date_linked(db, canonical, past)
    assert snap is not None and snap.recovery_score == 55
