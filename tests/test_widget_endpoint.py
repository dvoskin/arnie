"""
The lean iOS-widget data path — `native_data.widget_data` + `GET /api/v1/widget`.

`widget_data` is the compact "today at a glance" a WidgetKit timeline provider
reloads against: targets, today's totals + remaining-to-target, the logging
streak, latest weight, and a small wearable glance. It reuses the same fetchers
as `day_data`, so the widget's numbers can never drift from the Today screen.

These tests pin: the remaining-to-target math, the null-target (pre-onboarding)
teaser state, that a logged day lights the streak + weight blocks, and that the
route wraps it in the versioned envelope.
"""
import pytest
from sqlalchemy import select

from db.models import UserPreferences
from db.queries import (
    add_body_metric,
    add_food_entry,
    get_or_create_today_log,
    resolve_user,
)
from api.native_data import widget_data

pytestmark = pytest.mark.asyncio


async def _set_targets(db, user_id, *, cal, protein, carbs, fats):
    prefs = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )).scalar_one()
    prefs.calorie_target = cal
    prefs.protein_target = protein
    prefs.carb_target = carbs
    prefs.fat_target = fats
    await db.commit()


async def test_widget_data_totals_remaining_streak_and_weight(db, make_user):
    """A user with targets + one logged meal + a weigh-in: totals reflect the
    meal, remaining = target − consumed (per macro), the flame lights, and the
    weight block carries latest + goal."""
    row = await make_user(telegram_id="ios:wtest", timezone="UTC", goal_weight_kg=80.0)
    await _set_targets(db, row.id, cal=2000, protein=180, carbs=200, fats=60)
    # Fresh instance with preferences eager-loaded (matches the endpoint path).
    user = await resolve_user(db, "ios:wtest")

    log = await get_or_create_today_log(db, user.id, "UTC")
    await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Chicken & rice",
        calories=600, protein=50, carbs=40, fats=20,
    )
    await add_body_metric(db, user.id, 82.0, source="manual")

    data = await widget_data(db, user)

    assert data["targets"] == {"calories": 2000, "protein": 180, "carbs": 200, "fats": 60}
    assert data["totals"]["calories"] == 600
    assert data["totals"]["protein"] == 50
    # remaining = target − consumed
    assert data["remaining"] == {"calories": 1400, "protein": 130, "carbs": 160, "fats": 40}
    # Logging today (calories > 0) lights the flame.
    assert data["streak"] >= 1
    assert data["streaks"]["logging"]["current"] >= 1
    # Weight block: latest reading + the user's goal, in both units.
    assert data["weight"]["latest"]["kg"] == 82.0
    assert data["weight"]["goal"]["kg"] == 80.0
    assert data["timezone"] == "UTC"
    assert data["date"]


async def test_widget_data_remaining_goes_negative_when_over(db, make_user):
    """Remaining is NOT clamped at zero — going over target is meaningful and
    the client styles the negative ('120 over')."""
    row = await make_user(telegram_id="ios:over", timezone="UTC")
    await _set_targets(db, row.id, cal=1500, protein=150, carbs=150, fats=50)
    user = await resolve_user(db, "ios:over")

    log = await get_or_create_today_log(db, user.id, "UTC")
    await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Big day",
        calories=1620, protein=160, carbs=150, fats=50,
    )

    data = await widget_data(db, user)
    assert data["remaining"]["calories"] == -120
    assert data["remaining"]["protein"] == -10


async def test_widget_data_null_targets_pre_onboarding(db, make_user):
    """A user who hasn't set targets yet: targets + remaining are null-valued
    (the widget renders a teaser), but totals still populate from what's logged."""
    await make_user(telegram_id="ios:noob", timezone="UTC")
    user = await resolve_user(db, "ios:noob")

    log = await get_or_create_today_log(db, user.id, "UTC")
    await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Toast",
        calories=200, protein=8, carbs=30, fats=4,
    )

    data = await widget_data(db, user)
    assert data["targets"]["calories"] is None
    assert data["remaining"]["protein"] is None       # no target → no remaining
    assert data["totals"]["protein"] == 8             # totals still populated
    assert data["weight"] is None                     # nothing weighed in yet
    assert data["health"] is None                     # no wearable snapshot


async def test_widget_route_wraps_payload_in_versioned_envelope(db, make_user, monkeypatch, engine):
    """`GET /api/v1/widget` returns the widget payload under the wire-version
    envelope. Calls the route function directly, pointing its own session at the
    test engine (mirrors the auth-route tests)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from api import dashboard_api

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dashboard_api, "AsyncSessionLocal", session_factory)

    await make_user(telegram_id="ios:route", timezone="UTC")

    # identity passed directly, bypassing the Depends(current_identity) header dep.
    resp = await dashboard_api.get_widget(identity="ios:route")

    assert resp["v"] == dashboard_api.WIRE_VERSION
    assert resp["timezone"] == "UTC"
    for key in ("date", "targets", "totals", "remaining", "streak", "streaks"):
        assert key in resp
