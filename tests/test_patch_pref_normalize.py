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


# ── Macro target bounds + auto-sync on PATCH ─────────────────────────────────

async def _seed_macro_user(db, **demographics):
    base = dict(current_weight_kg=80.0, height_cm=180.0, age=30, sex="male",
                primary_goal="maintain", training_experience="intermediate")
    base.update(demographics)
    u = User(telegram_id="patch-macro", name="Macro", onboarding_completed=True,
             webhook_token="tok-patch", **base)
    db.add(u)
    await db.flush()
    db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=True))
    await db.commit()
    return u


@pytest.mark.asyncio
async def test_patch_rejects_calorie_target_out_of_range(monkeypatch, db):
    """A 999999 typo in the calorie input must be rejected, not saved and
    then expanded by the sync into absurd downstream macros."""
    from fastapi import HTTPException
    u = await _seed_macro_user(db)
    with pytest.raises(HTTPException) as ei:
        await _patch(monkeypatch, db, "calorie_target", "999999")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_patch_calorie_target_in_range_syncs_all_macros(monkeypatch, db):
    u = await _seed_macro_user(db)
    await _patch(monkeypatch, db, "calorie_target", "2500")
    await db.refresh(u.preferences)
    p = u.preferences
    assert p.calorie_target == 2500
    # protein/carbs/fat now derived from goal+weight (maintain, 80kg)
    assert p.protein_target and p.carb_target and p.fat_target
    # macro sum honors the calorie target within rounding noise
    macro_sum = p.protein_target * 4 + p.carb_target * 4 + p.fat_target * 9
    assert abs(macro_sum - p.calorie_target) <= 10


@pytest.mark.asyncio
async def test_patch_protein_change_preserves_calories(monkeypatch, db):
    u = await _seed_macro_user(db)
    await _patch(monkeypatch, db, "calorie_target", "2500")
    await _patch(monkeypatch, db, "protein_target", "220")
    await db.refresh(u.preferences)
    p = u.preferences
    assert p.calorie_target == 2500 and p.protein_target == 220
    macro_sum = p.protein_target * 4 + p.carb_target * 4 + p.fat_target * 9
    assert abs(macro_sum - p.calorie_target) <= 10
