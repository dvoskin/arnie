"""Admin gate must FAIL CLOSED — no admin access when ADMIN_TOKEN is unset, and an
empty token never satisfies the check (the old `!= getenv(..., "")` pattern did)."""
import pytest
from fastapi import HTTPException
import api.app as app_mod


def test_admin_disabled_when_token_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with pytest.raises(HTTPException) as e:
        app_mod._require_admin("anything")
    assert e.value.status_code == 503
    # the exact fail-open case from the audit: empty token + unset secret
    with pytest.raises(HTTPException):
        app_mod._require_admin("")


def test_admin_rejects_wrong_or_empty_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    for bad in ("wrong", "", "S3CRET", "s3cret "):
        with pytest.raises(HTTPException) as e:
            app_mod._require_admin(bad)
        assert e.value.status_code == 403, bad


def test_admin_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    assert app_mod._require_admin("s3cret") is None  # no raise = authorized
