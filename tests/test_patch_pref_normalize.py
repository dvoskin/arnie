"""
PATCH /api/profile parity hardening — the tiered prefs (reminder_frequency,
food_logging_mode) are normalized onto their valid vocabulary before persisting, so
a non-slider caller sending a relative word ("less"/"more") can't store a literal
the read path then silently coerces. Mirrors the LLM update_profile path.
"""
import pytest

import api.app as app_mod
from db.models import User, UserPreferences


async def _seed(db, *, reminder_frequency="moderate", food_logging_mode="moderate"):
    u = User(telegram_id="patch-user", name="Patch", onboarding_completed=True,
             webhook_token="tok-patch")
    db.add(u)
    await db.flush()
    db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=True,
                           reminder_frequency=reminder_frequency,
                           food_logging_mode=food_logging_mode))
    await db.commit()
    return u


async def _patch(monkeypatch, db, field, value):
    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db
    monkeypatch.setattr(app_mod, "AsyncSessionLocal", _fake_session)
    patch = app_mod.ProfilePatch(field=field, value=value)
    return await app_mod.api_edit_profile(token="tok-patch", patch=patch)


@pytest.mark.asyncio
async def test_reminder_frequency_relative_less_steps_down(monkeypatch, db):
    u = await _seed(db, reminder_frequency="moderate")
    await _patch(monkeypatch, db, "reminder_frequency", "less")
    await db.refresh(u.preferences)
    # "less" from moderate → one step down the ladder → "light" (never the literal)
    assert u.preferences.reminder_frequency == "light"


@pytest.mark.asyncio
async def test_reminder_frequency_exact_tier_passes_through(monkeypatch, db):
    u = await _seed(db, reminder_frequency="moderate")
    await _patch(monkeypatch, db, "reminder_frequency", "heavy")
    await db.refresh(u.preferences)
    assert u.preferences.reminder_frequency == "heavy"


@pytest.mark.asyncio
async def test_food_logging_mode_relative_more_steps_up(monkeypatch, db):
    u = await _seed(db, food_logging_mode="moderate")
    await _patch(monkeypatch, db, "food_logging_mode", "more")
    await db.refresh(u.preferences)
    # "more" from moderate → stricter → "strict" (not the literal "more")
    assert u.preferences.food_logging_mode == "strict"


@pytest.mark.asyncio
async def test_food_logging_mode_exact_passes_through(monkeypatch, db):
    u = await _seed(db, food_logging_mode="moderate")
    await _patch(monkeypatch, db, "food_logging_mode", "quick")
    await db.refresh(u.preferences)
    assert u.preferences.food_logging_mode == "quick"
