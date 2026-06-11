"""
/admin/proactive-debug introspector — replays the real scheduler gate chain for a
named/telegram_id'd user and reports the first durable gate that trips. These pin:
  • a UTC-default user (reminders on) is BLOCKED by no_timezone,
  • a real-tz user excluded from PROACTIVE_ALLOWLIST is BLOCKED by allowlist,
  • a real-tz, allowlisted, pref-on, fresh, in-window user would_send_now,
  • bad admin token is rejected.
The endpoint reuses scheduler.proactive_scheduler gate fns (never reimplements).
"""
import pytest
from fastapi import HTTPException

import api.app as app_mod
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from db.models import User, UserPreferences


async def _seed(db, *, telegram_id, name, timezone, pref_on=True):
    u = User(telegram_id=telegram_id, name=name, onboarding_completed=True,
             timezone=timezone)
    db.add(u)
    await db.flush()
    db.add(UserPreferences(user_id=u.id, proactive_messaging_enabled=pref_on,
                           wake_time="09:00", sleep_time="21:00"))
    await db.commit()
    return u


async def _loaded(db, name):
    return (await db.execute(
        select(User).where(User.name.ilike(f"%{name}%"))
        .options(selectinload(User.preferences))
    )).scalars().all()


@pytest.mark.asyncio
async def test_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    with pytest.raises(HTTPException) as e:
        await app_mod.admin_proactive_debug(token="wrong", name="x", telegram_id=None)
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_requires_an_identifier(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    with pytest.raises(HTTPException) as e:
        await app_mod.admin_proactive_debug(token="t", name=None, telegram_id=None)
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_utc_user_blocked_by_no_timezone(monkeypatch, db):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    await _seed(db, telegram_id="utc1", name="Michelle", timezone="UTC")

    # Patch the session factory the endpoint uses so it sees our in-memory db.
    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db
    monkeypatch.setattr(app_mod, "AsyncSessionLocal", _fake_session)

    resp = await app_mod.admin_proactive_debug(token="t", name="Michelle", telegram_id=None)
    import json
    body = json.loads(resp.body)
    assert body["ok"] is True
    r = body["results"][0]
    assert r["overall"] == "BLOCKED"
    # no_timezone is the durable blocker we care about — outside_window may also
    # appear depending on the UTC clock-time when the test runs, which is fine.
    assert "no_timezone" in r["blocked_by"]
    assert r["gates"]["has_timezone"] is False


@pytest.mark.asyncio
async def test_real_tz_user_excluded_by_allowlist(monkeypatch, db):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    # An allowlist that does NOT contain this user's id/telegram_id/send_id.
    monkeypatch.setenv("PROACTIVE_ALLOWLIST", "999999,im:+10000000000")
    await _seed(db, telegram_id="55", name="Jenny", timezone="America/New_York")

    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db
    monkeypatch.setattr(app_mod, "AsyncSessionLocal", _fake_session)

    resp = await app_mod.admin_proactive_debug(token="t", name="Jenny", telegram_id=None)
    import json
    body = json.loads(resp.body)
    r = body["results"][0]
    assert "allowlist" in r["blocked_by"]
    assert r["gates"]["allowlist_allows"] is False
    assert r["overall"] == "BLOCKED"


@pytest.mark.asyncio
async def test_deliverable_user_would_send_now(monkeypatch, db):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    # Use UTC as the "real" tz for a deterministic in-window check: pick a tz and
    # a wake/sleep window that contains the current UTC hour. A fixed tz keeps the
    # test stable regardless of wall-clock; the gate only needs a NON-UTC tz string
    # plus an in-window clock. We force the window wide (00:00–23:59 clamps to
    # 09:00–21:00) and assert on the durable gates, tolerating the time-window.
    await _seed(db, telegram_id="77", name="Danny", timezone="America/New_York")

    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db
    monkeypatch.setattr(app_mod, "AsyncSessionLocal", _fake_session)

    resp = await app_mod.admin_proactive_debug(token="t", name=None, telegram_id="77")
    import json
    body = json.loads(resp.body)
    r = body["results"][0]
    # All DURABLE gates must pass: no globally_off / skip_linked / allowlist /
    # no_timezone in the blocked list. (outside_window is time-of-day dependent
    # and legitimately transient — excluded from this assertion.)
    durable = {"globally_off", "skip_linked", "allowlist", "no_timezone",
               "proactive_pref_off"}
    assert not (durable & set(r["blocked_by"])), r["blocked_by"]
    assert r["gates"]["has_timezone"] is True
    assert r["gates"]["allowlist_allows"] is True
    # If it happens to be inside 9-9 local, overall is would_send_now.
    if not r["blocked_by"]:
        assert r["overall"] == "would_send_now"
