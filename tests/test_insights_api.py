"""
Tests for /api/v1/insights and /api/v1/memory (slice 9 — insights +
memory REST endpoints for the iOS Brain / Profile surfaces).

The legacy `/api/insights/{token}` and per-user memory files are wrapped
behind bearer auth here. The downstream generators (`get_insights`,
`get_week_insights`, `read_memory`) are monkey-patched to canned values —
their internals are tested separately. This file covers the wiring:
auth → resolve_user → generator → response shape.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.insights_api import get_insights_for_ios, get_memory_for_ios


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import insights_api
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(insights_api, "AsyncSessionLocal", factory)
    return factory


# ── Insights ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_day_default_returns_day_bullets(
    patched_session_local, make_user, monkeypatch,
):
    """No `period` query param defaults to day-mode and calls
    `get_insights` (not `get_week_insights`)."""
    await make_user(telegram_id="ios:insights-day")

    async def fake_stats(db, user, target_date=None):
        return {"any": "stats"}
    async def fake_day(user_id, stats, force=False, date_key=""):
        return ["Day insight A", "Day insight B"]
    async def fake_week(*args, **kwargs):
        raise AssertionError("week generator must not run when period=day")

    monkeypatch.setattr("api.app._build_stats_for_user", fake_stats)
    monkeypatch.setattr("api.insights.get_insights", fake_day)
    monkeypatch.setattr("api.insights.get_week_insights", fake_week)

    resp = await get_insights_for_ios(identity="ios:insights-day")
    assert resp == {"insights": ["Day insight A", "Day insight B"], "period": "day"}


@pytest.mark.asyncio
async def test_insights_period_week_routes_to_week_generator(
    patched_session_local, make_user, monkeypatch,
):
    await make_user(telegram_id="ios:insights-week")

    async def fake_stats(db, user, target_date=None):
        return {}
    async def fake_day(*args, **kwargs):
        raise AssertionError("day generator must not run when period=week")
    async def fake_week(user_id, stats, force=False):
        return ["Week trend"]

    monkeypatch.setattr("api.app._build_stats_for_user", fake_stats)
    monkeypatch.setattr("api.insights.get_insights", fake_day)
    monkeypatch.setattr("api.insights.get_week_insights", fake_week)

    resp = await get_insights_for_ios(period="week", identity="ios:insights-week")
    assert resp == {"insights": ["Week trend"], "period": "week"}


# ── Memory ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_returns_file_contents(
    patched_session_local, make_user, monkeypatch,
):
    """The endpoint returns the raw memory file content tied to the
    authenticated user's telegram_id, plus the telegram_id itself so iOS
    can correlate."""
    await make_user(telegram_id="ios:memory-user")

    async def fake_read(telegram_id):
        assert telegram_id == "ios:memory-user"
        return "User prefers cold brew. Trains 4x/wk. Cutting."

    monkeypatch.setattr("memory.memory_manager.read_memory", fake_read)

    resp = await get_memory_for_ios(identity="ios:memory-user")
    assert resp["telegram_id"] == "ios:memory-user"
    assert "cold brew" in resp["content"]


@pytest.mark.asyncio
async def test_memory_empty_for_brand_new_user(
    patched_session_local, make_user, monkeypatch,
):
    """A user who hasn't completed onboarding has no memory file yet;
    `read_memory` returns "" and the endpoint surfaces that cleanly."""
    await make_user(telegram_id="ios:no-memory-yet")

    async def fake_read(telegram_id):
        return ""

    monkeypatch.setattr("memory.memory_manager.read_memory", fake_read)

    resp = await get_memory_for_ios(identity="ios:no-memory-yet")
    assert resp["content"] == ""
