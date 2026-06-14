"""
Integration tests for proactive frequency tiers — verifies the scheduler
actually respects the Client tab labels at the send level, not just in unit-
isolated frequency_allows() calls.

These tests stub the LLM and DB but exercise the real _run_reminders /
_run_conversation_hooks orchestration paths so that a "none" user really
receives only the morning_checkin send per day and not the warmup/hook/recap/
EOD pile.
"""
import pytest
import pytest_asyncio
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from db.database import Base, _migrate
from db import models  # noqa: F401


@pytest_asyncio.fixture
async def freq_env(monkeypatch):
    """Fresh in-memory DB + the scheduler module re-pointed at it. LLM nudges
    are stubbed to return a fixed string so we can count sends per slot."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import scheduler.proactive_scheduler as PS
    import db.database as _DB
    monkeypatch.setattr(_DB, "AsyncSessionLocal", Maker)
    monkeypatch.setattr(PS, "AsyncSessionLocal", Maker, raising=False)

    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)

    sends: list[tuple[str, str]] = []  # (slot_key, text)

    async def _fake_send_logged(db, user_id, send_id, text, slot_key):
        sends.append((slot_key, text))

    async def _fake_send_logged_voice(db, user_id, send_id, text, slot_key,
                                       name="", language="English"):
        sends.append((slot_key, text))

    async def _fake_llm_nudge(*a, **kw):
        return "fake nudge"

    async def _fake_morning_briefing(*a, **kw):
        return "morning briefing"

    async def _fake_new_user_nudge(user, log, prefs, slot, name, surface_howto=False):
        return f"warmup {slot}"

    async def _fake_followup(user, pq, name):
        return "followup ask"

    async def _fake_send_hook(telegram_id, text):
        # _run_conversation_hooks fires _send_hook (bypasses PROACTIVE gate)
        # then logs the send. Mirror its slot_key naming here.
        sends.append(("followup_conversation_hook", text))

    async def _fake_log_proactive(db, user_id, text, slot_key):
        return None

    monkeypatch.setattr(PS, "_send_logged", _fake_send_logged)
    monkeypatch.setattr(PS, "_send_logged_with_voice", _fake_send_logged_voice)
    monkeypatch.setattr(PS, "_send_hook", _fake_send_hook)
    monkeypatch.setattr(PS, "_log_proactive", _fake_log_proactive)
    monkeypatch.setattr(PS, "_llm_nudge", _fake_llm_nudge)
    monkeypatch.setattr(PS, "_llm_morning_briefing", _fake_morning_briefing)
    monkeypatch.setattr(PS, "_llm_new_user_nudge", _fake_new_user_nudge)
    monkeypatch.setattr(PS, "_llm_followup", _fake_followup)

    yield {"PS": PS, "Maker": Maker, "sends": sends}
    await engine.dispose()


async def _seed(Maker, *, telegram_id, freq, hours_in_age=200.0,
                  wake="09:00", sleep="21:00", tz="America/New_York"):
    """Seed an onboarded user with a given reminder_frequency and a fresh age
    in hours (controls whether the warmup burst is in play)."""
    from datetime import datetime, timezone, timedelta
    from db.models import User, UserPreferences
    async with Maker() as db:
        u = User(
            telegram_id=telegram_id, name="Test",
            onboarding_completed=True, current_weight_kg=80.0,
            primary_goal="cut", timezone=tz,
            created_at=datetime.now(timezone.utc) - timedelta(hours=hours_in_age),
        )
        db.add(u)
        await db.flush()
        db.add(UserPreferences(
            user_id=u.id, proactive_messaging_enabled=True,
            wake_time=wake, sleep_time=sleep,
            reminder_frequency=freq, calorie_target=2100, protein_target=180,
        ))
        await db.commit()
        return u


# ═══════════════════════════════════════════════════════════════════════════
# Slot map and the prefix collapses are unit-tested in test_reminders.py.
# These tests verify the SCHEDULER actually consults them at the right gates.
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_minimal_user_warmup_burst_does_not_fire(freq_env):
    """A new user (in warmup window) on reminder_frequency='none' must NOT
    receive any warmup_* nudges — the screenshot bug where 'Morning only'
    sent messages all day."""
    PS = freq_env["PS"]
    # Fresh user in warmup window (12h old), frequency=none.
    await _seed(freq_env["Maker"], telegram_id="im:+15550000001",
                freq="none", hours_in_age=12.0)

    # Run the reminder pass. We don't care about the exact local hour for this
    # check — warmup gating runs BEFORE slot windows and looks only at the
    # warmup category gate.
    await PS._run_reminders()

    warmup_sends = [s for s in freq_env["sends"] if s[0].startswith("warmup_")]
    assert warmup_sends == [], (
        f"'none' tier must not fire warmup_* nudges (sent: {warmup_sends})"
    )


@pytest.mark.asyncio
async def test_heavy_user_warmup_burst_fires(freq_env):
    """Same fresh user on 'heavy' frequency DOES get the warmup burst —
    confirms the gate is selective, not blanket-off."""
    PS = freq_env["PS"]
    await _seed(freq_env["Maker"], telegram_id="im:+15550000002",
                freq="heavy", hours_in_age=0.5)  # in warmup_15m window

    await PS._run_reminders()
    warmup_sends = [s for s in freq_env["sends"] if s[0].startswith("warmup_")]
    # Either warmup_15m or another warmup_* slot should fire (depending on the
    # exact uptime). At minimum, one warmup send for a heavy-tier fresh user.
    assert len(warmup_sends) >= 1, (
        f"'heavy' tier should fire a warmup nudge in the warmup window "
        f"(sent: {freq_env['sends']})"
    )


@pytest.mark.asyncio
async def test_minimal_user_conversation_hook_does_not_fire(freq_env):
    """A 'none' user with an open conversation_hook must NOT get a hook
    re-ask — they explicitly chose Morning only."""
    PS = freq_env["PS"]
    u = await _seed(freq_env["Maker"], telegram_id="im:+15550000003",
                    freq="none", hours_in_age=200.0)

    # Open a stale conversation_hook so the path has something to fire.
    from datetime import datetime, timedelta
    from db.models import PendingQuestion
    async with freq_env["Maker"]() as db:
        db.add(PendingQuestion(
            user_id=u.id, kind="conversation_hook",
            question="What's the plan for dinner tonight, ready to lock in?",
            tier="conversation_hook",
            asked_at=datetime.utcnow() - timedelta(hours=6),
            last_asked_at=datetime.utcnow() - timedelta(hours=6),
            follow_up_count=0,
        ))
        await db.commit()

    await PS._run_conversation_hooks()

    hook_sends = [s for s in freq_env["sends"]
                  if "followup_conversation_hook" in s[0]
                  or "conversation_hook" in s[0]]
    assert hook_sends == [], (
        f"'none' tier must not fire conversation_hook re-asks "
        f"(sent: {hook_sends})"
    )


@pytest.mark.asyncio
async def test_light_user_conversation_hook_does_not_fire(freq_env):
    """'light' = Morning & evening only. Hooks come in at 'moderate' and above."""
    PS = freq_env["PS"]
    u = await _seed(freq_env["Maker"], telegram_id="im:+15550000004",
                    freq="light", hours_in_age=200.0)

    from datetime import datetime, timedelta
    from db.models import PendingQuestion
    async with freq_env["Maker"]() as db:
        db.add(PendingQuestion(
            user_id=u.id, kind="conversation_hook",
            question="What's the plan for dinner tonight, ready to lock in?",
            tier="conversation_hook",
            asked_at=datetime.utcnow() - timedelta(hours=6),
            last_asked_at=datetime.utcnow() - timedelta(hours=6),
            follow_up_count=0,
        ))
        await db.commit()

    await PS._run_conversation_hooks()

    hook_sends = [s for s in freq_env["sends"] if "conversation_hook" in s[0]]
    assert hook_sends == [], (
        f"'light' tier must not fire conversation_hook re-asks (sent: {hook_sends})"
    )


@pytest.mark.asyncio
async def test_moderate_user_conversation_hook_fires(freq_env):
    """At 'moderate' and above, hook re-asks do fire — the gate is selective."""
    PS = freq_env["PS"]
    u = await _seed(freq_env["Maker"], telegram_id="im:+15550000005",
                    freq="moderate", hours_in_age=200.0)

    from datetime import datetime, timedelta
    from db.models import PendingQuestion
    async with freq_env["Maker"]() as db:
        db.add(PendingQuestion(
            user_id=u.id, kind="conversation_hook",
            question="What's the plan for dinner tonight, ready to lock in?",
            tier="conversation_hook",
            asked_at=datetime.utcnow() - timedelta(hours=6),
            last_asked_at=datetime.utcnow() - timedelta(hours=6),
            follow_up_count=0,
        ))
        await db.commit()

    await PS._run_conversation_hooks()

    hook_sends = [s for s in freq_env["sends"] if "conversation_hook" in s[0]]
    assert len(hook_sends) >= 1, (
        f"'moderate' tier should fire the conversation_hook re-ask "
        f"(sent: {freq_env['sends']})"
    )
