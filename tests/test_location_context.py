"""Pin the new street-precision wiring in context_builder.

Validates that when reverse_address resolves to a street, the LOCATION line
the model sees contains it. Stubs the geocoder so we don't need a Google key
or the network.

The test uses the same fresh-session-per-call pattern as simulate_ios_fixes
because context_builder accesses several lazy-loaded relationships that trip
the SQLAlchemy async-greenlet guard if the session has been kept open.
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from db.database import Base, _migrate
from db import models  # noqa: F401
from db.models import User, UserPreferences
from db.queries import (
    save_user_location, get_or_create_today_log, reload_user,
)
from core import context_builder, geocode


async def _seed_user(Maker) -> int:
    """Create the test user once; return its id. Subsequent calls use a fresh
    session and reload_user (matches the production chat path)."""
    async with Maker() as db:
        u = User(
            telegram_id="loctest:1", name="Danny", age=33, sex="male",
            height_cm=178.0, current_weight_kg=78.0, goal_weight_kg=74.0,
            primary_goal="cut", training_experience="intermediate",
            timezone="America/New_York", onboarding_completed=True, city="New York",
        )
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2000, protein_target=180))
        await db.flush()
        uid = u.id
        await save_user_location(db, user_id=uid, lat=40.7747, lng=-73.9906,
                                  city="New York")
        await db.commit()
        return uid


async def _build_fresh(Maker, uid: int) -> str:
    async with Maker() as db:
        fresh = await reload_user(db, uid)
        today = await get_or_create_today_log(db, fresh.id, fresh.timezone)
        return await context_builder.build_context(
            fresh, today, db, platform="ios", user_message="where am i?",
        )


@pytest.fixture
async def maker(monkeypatch):
    monkeypatch.setenv("LOCATION_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "stub-key")
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        yield Session
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_context_surfaces_street_when_reverse_address_resolves(
    maker, monkeypatch
):
    """When the geocoder returns a street, the LOCATION line includes it
    AND tells the model to relay it directly."""
    uid = await _seed_user(maker)

    async def _stub(lat, lng):
        return "116 Central Park S, New York, NY 10019"

    monkeypatch.setattr(geocode, "reverse_address", _stub)

    ctx = await _build_fresh(maker, uid)
    assert "116 Central Park S, New York, NY 10019" in ctx, (
        "street address should appear in the LOCATION line"
    )
    assert "exact shared spot" in ctx, (
        "the prompt directive that triggers street-readback should be present"
    )


@pytest.mark.asyncio
async def test_context_falls_back_to_city_when_street_unknown(
    maker, monkeypatch
):
    """If reverse_address returns None, the prior city-only line is preserved."""
    uid = await _seed_user(maker)

    async def _stub(lat, lng):
        return None

    monkeypatch.setattr(geocode, "reverse_address", _stub)

    ctx = await _build_fresh(maker, uid)
    assert "Location: ON FILE (New York)" in ctx, (
        "city fallback line should be used when street is unknown"
    )
    assert "exact shared spot" not in ctx, (
        "street-precision directive must NOT fire when only the city is known"
    )


@pytest.mark.asyncio
async def test_context_omits_location_when_flag_off(maker, monkeypatch):
    """The whole block is gated on LOCATION_ENABLED."""
    uid = await _seed_user(maker)
    monkeypatch.setenv("LOCATION_ENABLED", "false")
    ctx = await _build_fresh(maker, uid)
    assert "Location:" not in ctx
