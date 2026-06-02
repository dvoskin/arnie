"""Check-ins are enabled natively when a user finishes onboarding."""
import pytest
from sqlalchemy import select
from db.models import User, UserPreferences
from db.queries import enable_check_ins


@pytest.mark.asyncio
async def test_enable_check_ins_turns_pref_on(make_user, db):
    # make_user seeds prefs with proactive_messaging_enabled=False
    u = await make_user(telegram_id="ci1")
    await enable_check_ins(db, u.id)
    p = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == u.id)
    )).scalar_one()
    assert p.proactive_messaging_enabled is True


@pytest.mark.asyncio
async def test_enable_check_ins_creates_prefs_if_missing(db):
    u = User(telegram_id="ci2", name="X", onboarding_completed=False)
    db.add(u)
    await db.flush()
    # no preferences row yet
    assert (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == u.id)
    )).scalar_one_or_none() is None

    await enable_check_ins(db, u.id)
    p = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == u.id)
    )).scalar_one()
    assert p.proactive_messaging_enabled is True
