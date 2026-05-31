"""Pure-logic gates that guard proactive outreach (overnight-spam prevention)."""
import os
import importlib
from types import SimpleNamespace

import scheduler.proactive_scheduler as sched


def test_in_window():
    assert sched._in_window("12:00", "09:00", "21:00") is True
    assert sched._in_window("08:59", "09:00", "21:00") is False
    assert sched._in_window("21:01", "09:00", "21:00") is False
    assert sched._in_window("09:00", "09:00", "21:00") is True  # inclusive edges
    assert sched._in_window("21:00", "09:00", "21:00") is True


def test_has_timezone():
    assert sched._has_timezone(SimpleNamespace(timezone="America/New_York")) is True
    assert sched._has_timezone(SimpleNamespace(timezone="UTC")) is False  # unknown default
    assert sched._has_timezone(SimpleNamespace(timezone=None)) is False
    assert sched._has_timezone(SimpleNamespace(timezone="")) is False


def test_proactive_enabled_defaults_off(monkeypatch):
    monkeypatch.delenv("PROACTIVE_MESSAGING_ENABLED", raising=False)
    importlib.reload(sched)
    assert sched.proactive_enabled() is False
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    assert sched.proactive_enabled() is True
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "false")
    assert sched.proactive_enabled() is False
