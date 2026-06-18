"""
Tests for /api/v1/profile and /api/v1/targets PATCH (slice 7 — profile +
macro-target edit REST endpoints).

Confirms the canonical iOS write-paths land in the same users /
user_preferences columns the chat-side update_profile / set_macro_targets
tools write to, with strict Pydantic validation on input ranges so a
client unit-bug can't push impossible values.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.profile_edit import (
    ProfileEditBody,
    TargetsEditBody,
    patch_profile,
    patch_targets,
)
from db.models import User, UserPreferences


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import profile_edit
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(profile_edit, "AsyncSessionLocal", factory)
    return factory


# ── Profile PATCH ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_profile_updates_only_present_fields(
    patched_session_local, db, make_user,
):
    """Field NOT in the body must not be touched. Lets iOS update one
    field without re-sending the rest of the profile."""
    user = await make_user(
        telegram_id="ios:profile-patch",
        name="Old Name",
        age=30,
        primary_goal="maintain",
    )

    resp = await patch_profile(
        ProfileEditBody(name="New Name", age=31),
        identity="ios:profile-patch",
    )

    assert resp["ok"] is True
    assert set(resp["updated_fields"]) == {"name", "age"}

    # The route committed in its own session — refresh the cached object in
    # this test's session so SQLAlchemy's identity map doesn't return stale data.
    await db.refresh(user)
    assert user.name == "New Name"
    assert user.age == 31
    # primary_goal NOT in the body → unchanged.
    assert user.primary_goal == "maintain"


@pytest.mark.asyncio
async def test_patch_profile_empty_body_is_quiet_noop(
    patched_session_local, db, make_user,
):
    """An empty patch returns ok with an empty updated list — no DB
    writes. Useful when the iOS form is submitted unchanged."""
    user = await make_user(telegram_id="ios:empty-patch", name="Same")
    resp = await patch_profile(ProfileEditBody(), identity="ios:empty-patch")
    assert resp == {"ok": True, "updated_fields": []}

    refreshed = (await db.execute(
        select(User).where(User.id == user.id)
    )).scalar_one()
    assert refreshed.name == "Same"


@pytest.mark.asyncio
async def test_patch_profile_validates_age_range():
    """Pydantic ge=10 le=120 rejects garbage age values before the route
    handler runs."""
    with pytest.raises(Exception):
        ProfileEditBody(age=5)
    with pytest.raises(Exception):
        ProfileEditBody(age=200)


@pytest.mark.asyncio
async def test_patch_profile_validates_weight_range():
    """A unit-conversion bug (kg ↔ lb) won't push impossible values into
    the row."""
    with pytest.raises(Exception):
        ProfileEditBody(current_weight_kg=10)   # under 20kg
    with pytest.raises(Exception):
        ProfileEditBody(current_weight_kg=500)  # over 400kg


@pytest.mark.asyncio
async def test_patch_profile_writes_height_and_weights(
    patched_session_local, db, make_user,
):
    """Height + current + goal weights round-trip through the patch."""
    user = await make_user(telegram_id="ios:body-stats")

    resp = await patch_profile(
        ProfileEditBody(
            height_cm=180.0,
            current_weight_kg=85.5,
            goal_weight_kg=80.0,
            primary_goal="cut",
        ),
        identity="ios:body-stats",
    )

    assert set(resp["updated_fields"]) == {
        "height_cm", "current_weight_kg", "goal_weight_kg", "primary_goal",
    }
    refreshed = (await db.execute(
        select(User).where(User.id == user.id)
    )).scalar_one()
    assert refreshed.height_cm == 180.0
    assert refreshed.current_weight_kg == 85.5
    assert refreshed.goal_weight_kg == 80.0
    assert refreshed.primary_goal == "cut"


# ── Targets PATCH ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_targets_writes_to_user_preferences(
    patched_session_local, db, make_user,
):
    """Targets land on the user_preferences row, not the users row."""
    user = await make_user(telegram_id="ios:targets")

    resp = await patch_targets(
        TargetsEditBody(
            calorie_target=2400, protein_target=180, carb_target=250, fat_target=80,
        ),
        identity="ios:targets",
    )

    assert resp["ok"] is True
    assert set(resp["updated_fields"]) == {
        "calorie_target", "protein_target", "carb_target", "fat_target",
    }
    prefs = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )).scalar_one()
    assert prefs.calorie_target == 2400
    assert prefs.protein_target == 180
    assert prefs.carb_target == 250
    assert prefs.fat_target == 80


@pytest.mark.asyncio
async def test_patch_targets_updates_only_present_fields(
    patched_session_local, db, make_user,
):
    """One macro at a time — common iOS pattern (slider for protein only,
    keep calories the same)."""
    user = await make_user(telegram_id="ios:single-target")
    # Seed full set first.
    await patch_targets(
        TargetsEditBody(calorie_target=2200, protein_target=150,
                        carb_target=220, fat_target=70),
        identity="ios:single-target",
    )

    # Now bump only protein.
    resp = await patch_targets(
        TargetsEditBody(protein_target=200),
        identity="ios:single-target",
    )

    assert resp["updated_fields"] == ["protein_target"]
    prefs = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )).scalar_one()
    assert prefs.protein_target == 200
    # The rest stayed.
    assert prefs.calorie_target == 2200
    assert prefs.carb_target == 220
    assert prefs.fat_target == 70


@pytest.mark.asyncio
async def test_patch_targets_validates_calorie_range():
    """Below 800 or above 8000 is almost certainly a typo."""
    with pytest.raises(Exception):
        TargetsEditBody(calorie_target=400)
    with pytest.raises(Exception):
        TargetsEditBody(calorie_target=10_000)


@pytest.mark.asyncio
async def test_patch_targets_validates_macro_ranges():
    """0–600 protein, 0–1500 carbs, 0–400 fat — bounds wide enough for
    any realistic athlete but rejects unit bugs."""
    with pytest.raises(Exception):
        TargetsEditBody(protein_target=700)
    with pytest.raises(Exception):
        TargetsEditBody(carb_target=2000)
    with pytest.raises(Exception):
        TargetsEditBody(fat_target=500)


@pytest.mark.asyncio
async def test_patch_targets_empty_body_is_quiet_noop(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:empty-targets")
    resp = await patch_targets(TargetsEditBody(), identity="ios:empty-targets")
    assert resp == {"ok": True, "updated_fields": []}
