"""Deferred micro/fss estimation (FOOD_MICROS_DEFERRED, 0802 latency work).

The synchronous micro-estimate is a ~2.5s haiku call on the food-log critical
path whose output (vitamins + fiber/sugar/sodium) is not in the reply. When the
flag is on, the row commits with NULL micros and `_deferred_micro_fill` fills them
off the reply path — same numbers, same fiber/sugar<=carbs invariant, later.

HERMETIC: `_deferred_micro_fill` opens `db.database.AsyncSessionLocal`, so the
`isolated` fixture points that at THIS test's own in-memory engine. Nothing is
committed to the shared/app database — a test that wrote to the app global DB
would leak rows into every other test on the shared CI Postgres.
"""
import datetime
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from handlers.tool_executor import _deferred_micro_fill, micros_deferred_enabled


def test_flag_defaults_off_and_parses(monkeypatch):
    monkeypatch.delenv("FOOD_MICROS_DEFERRED", raising=False)
    assert micros_deferred_enabled() is False
    monkeypatch.setenv("FOOD_MICROS_DEFERRED", "true")
    assert micros_deferred_enabled() is True
    monkeypatch.setenv("FOOD_MICROS_DEFERRED", "nope")
    assert micros_deferred_enabled() is False


@pytest_asyncio.fixture
async def isolated(engine, monkeypatch):
    """Point the app's AsyncSessionLocal at this test's isolated engine, so the
    deferred fill and our setup share ONE in-memory DB and nothing leaks."""
    import db.database as dbmod
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", Session, raising=False)
    return Session


async def _make_entry(Session, **overrides):
    import db.models as m
    async with Session() as s:
        u = m.User(telegram_id=f"mfill-{uuid.uuid4().hex[:10]}", name="D",
                   onboarding_completed=True)
        s.add(u)
        await s.flush()
        dl = m.DailyLog(user_id=u.id, date=datetime.date(2026, 8, 2))
        s.add(dl)
        await s.flush()
        fields = dict(daily_log_id=dl.id, parsed_food_name="chicken shawarma bowl",
                      calories=800, protein=40, carbs=60, fats=35)
        fields.update(overrides)
        fe = m.FoodEntry(**fields)
        s.add(fe)
        await s.commit()
        return fe.id


@pytest.mark.asyncio
async def test_deferred_fill_populates_null_micros_and_caps_to_carbs(isolated, monkeypatch):
    eid = await _make_entry(isolated)

    async def fake(*a, **k):
        # fiber/sugar OVER carbs (60) on purpose — the invariant must cap them.
        return {"vitamin_c": 12.0, "fiber": 90.0, "sugar": 90.0, "sodium": 1200.0}
    monkeypatch.setattr("core.micro_estimator.estimate_micros", fake)

    await _deferred_micro_fill(eid, "chicken shawarma bowl", "1 bowl", 800, 40, 60, 35)

    import db.models as m
    async with isolated() as s:
        row = await s.get(m.FoodEntry, eid)
        assert row.micros_estimated is True
        assert "vitamin_c" in (row.micronutrients_json or "")
        assert json.loads(row.micronutrients_json).get("fiber") is None  # fss popped
        assert row.fiber == 60.0          # capped to carbs
        assert row.sugar == 60.0          # capped to carbs
        assert row.sodium == 1200.0


@pytest.mark.asyncio
async def test_deferred_fill_never_clobbers_existing_values(isolated, monkeypatch):
    eid = await _make_entry(isolated, sodium=333.0)

    async def fake(*a, **k):
        return {"vitamin_c": 5.0, "sodium": 999.0}
    monkeypatch.setattr("core.micro_estimator.estimate_micros", fake)

    await _deferred_micro_fill(eid, "x", "1", 800, 40, 60, 35)

    import db.models as m
    async with isolated() as s:
        row = await s.get(m.FoodEntry, eid)
        assert row.sodium == 333.0        # a real source's value is untouched


@pytest.mark.asyncio
async def test_deferred_fill_is_safe_when_row_is_gone(isolated, monkeypatch):
    async def fake(*a, **k):
        return {"vitamin_c": 5.0}
    monkeypatch.setattr("core.micro_estimator.estimate_micros", fake)
    # id that never existed — must not raise (row never appears; gives up quietly).
    await _deferred_micro_fill(999999, "x", "1", 100, 5, 5, 1)


@pytest.mark.asyncio
async def test_deferred_fill_no_estimate_is_a_noop(isolated, monkeypatch):
    eid = await _make_entry(isolated)

    async def fake(*a, **k):
        return None
    monkeypatch.setattr("core.micro_estimator.estimate_micros", fake)
    await _deferred_micro_fill(eid, "x", "1", 800, 40, 60, 35)

    import db.models as m
    async with isolated() as s:
        row = await s.get(m.FoodEntry, eid)
        assert row.micronutrients_json is None
