"""Stage-tiered model routing — premium first pass for new users only."""
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from core.llm import pick_model


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv("NEW_USER_MODEL", raising=False)
    u = NS(created_at=datetime.utcnow())
    assert pick_model(u) is None


def test_new_user_gets_premium(monkeypatch):
    monkeypatch.setenv("NEW_USER_MODEL", "claude-opus-4-8")
    monkeypatch.setenv("NEW_USER_WINDOW_DAYS", "14")
    fresh = NS(created_at=datetime.utcnow() - timedelta(days=3))
    veteran = NS(created_at=datetime.utcnow() - timedelta(days=40))
    assert pick_model(fresh) == "claude-opus-4-8"
    assert pick_model(veteran) is None


def test_missing_created_at_safe(monkeypatch):
    monkeypatch.setenv("NEW_USER_MODEL", "claude-opus-4-8")
    assert pick_model(NS(created_at=None)) is None
