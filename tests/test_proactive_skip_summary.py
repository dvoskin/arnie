"""
Per-tick skip-summary observability in _run_reminders. The gate chain is otherwise
totally silent; this pins that exactly ONE 'proactive tick:' line is emitted per
run and that it counts the no-timezone skip and the total users evaluated. Pure
instrumentation — control flow is unchanged (verified by the rest of the suite).
"""
import logging
import pytest

import scheduler.proactive_scheduler as S
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


@pytest.mark.asyncio
async def test_one_summary_line_with_no_tz_count(monkeypatch, db, caplog):
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)

    # One user with no real timezone (UTC default → no_tz skip), one with a real
    # tz (proceeds past the durable gates; may or may not send depending on the
    # wall-clock slot, which is fine — we only assert on no_tz + users).
    await _seed(db, telegram_id="utc-user", name="NoTz", timezone="UTC")
    await _seed(db, telegram_id="real-user", name="RealTz", timezone="America/New_York")

    # _run_reminders imports AsyncSessionLocal from db.database at call time, so
    # patch it there to hand the loop our in-memory session.
    import contextlib
    import db.database as _dbmod

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db
    monkeypatch.setattr(_dbmod, "AsyncSessionLocal", _fake_session)

    with caplog.at_level(logging.INFO, logger="scheduler.proactive_scheduler"):
        await S._run_reminders()

    tick_lines = [r.getMessage() for r in caplog.records
                  if r.getMessage().startswith("proactive tick:")]
    assert len(tick_lines) == 1, tick_lines
    line = tick_lines[0]
    assert "users=2" in line
    assert "no_tz=1" in line
