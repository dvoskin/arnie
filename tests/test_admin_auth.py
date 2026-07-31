"""The admin gate, exercised through the real HTTP stack (B7, 2026-07-31).

Rewritten from calling `_require_admin(token)` — which no longer exists — to
driving the endpoints with a TestClient, because the properties that matter now
live in the request/response, not a helper: a token in the URL must become a
cookie and a clean redirect, a forged cookie must fail, and the rate limiter
must front the token check so a brute-forcer is throttled whether or not any
guess is right.

Every auth outcome asserted here (401/403/503/429/303) is decided in the
`require_admin` dependency BEFORE the handler's DB work, so these need no
database — except the one HTML-render test, which builds the app's tables to
prove the dashboard emits no `?token=` links.
"""
import hmac
import os

import pytest
from starlette.testclient import TestClient

import api.app as app_mod
from api.auth import issue_admin_cookie, ADMIN_COOKIE_NAME, _sign
from core import ratelimit

ADMIN = "s3cret-admin-token"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    ratelimit._reset_for_tests()
    yield
    ratelimit._reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app_mod.app)


# ── Fail closed ───────────────────────────────────────────────────────────────

def test_admin_disabled_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    # Even presenting a token: with no ADMIN_TOKEN configured, admin is OFF.
    r = client.get("/admin?token=anything")
    assert r.status_code == 503


def test_no_credentials_is_401(client):
    r = client.get("/admin/flagged")  # no header, no cookie, no query
    assert r.status_code == 401


def test_wrong_token_is_403(client):
    assert client.get("/admin/flagged",
                      headers={"X-Admin-Token": "wrong"}).status_code == 403
    # Trailing space / case: the old `!=` and a loose compare both let these slip.
    assert client.get(f"/admin/flagged?token={ADMIN} ").status_code == 403
    assert client.get("/admin/flagged?token=S3CRET-ADMIN-TOKEN").status_code == 403


# ── Credential no longer rides in the URL ────────────────────────────────────

def test_query_bootstrap_redirects_to_clean_url_and_sets_cookie(client):
    r = client.get(f"/admin?token={ADMIN}", follow_redirects=False)
    assert r.status_code == 303
    # The redirect target is tokenless — the browser's next hit and any copied
    # link carry no secret.
    assert r.headers["location"] == "/admin"
    assert "token" not in r.headers["location"]
    cookie = r.headers.get("set-cookie", "")
    assert ADMIN_COOKIE_NAME in cookie
    assert "httponly" in cookie.lower()


def test_cookie_opens_the_gate_and_forged_cookie_does_not(client):
    good = issue_admin_cookie()
    # A route that answers without a DB once the gate passes: run-reminders with
    # proactive globally off returns 409. Reaching 409 proves auth succeeded.
    r = client.post("/admin/run-reminders",
                    cookies={ADMIN_COOKIE_NAME: good})
    assert r.status_code == 409

    # Tamper the signature → not authenticated → falls through to 401.
    body = good.rsplit(".", 1)[0]
    forged = f"{body}.{'A' * 43}"
    assert client.post("/admin/run-reminders",
                       cookies={ADMIN_COOKIE_NAME: forged}).status_code == 401


def test_expired_cookie_is_rejected(client):
    # exp in the past, correctly signed → still rejected on expiry.
    body = "admin.1"
    expired = f"{body}.{_sign(body)}"
    assert client.post("/admin/run-reminders",
                       cookies={ADMIN_COOKIE_NAME: expired}).status_code == 401


def test_header_opens_the_gate(client):
    r = client.post("/admin/run-reminders", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 409  # gate passed, proactive off


# ── Rate limit fronts the token check ────────────────────────────────────────

def test_brute_force_is_throttled(client):
    # Every guess is wrong (403), but the limiter runs first, so the flood trips
    # 429 regardless — the point being that guesses are bounded per window.
    seen_403 = seen_429 = False
    for _ in range(75):
        code = client.get("/admin/flagged",
                          headers={"X-Admin-Token": "wrong"}).status_code
        seen_403 |= code == 403
        seen_429 |= code == 429
    assert seen_403 and seen_429


# ── run-reminders safety gates (unchanged invariants, new call path) ─────────

def test_run_reminders_409_when_proactive_off(client, monkeypatch):
    monkeypatch.delenv("PROACTIVE_MESSAGING_ENABLED", raising=False)
    r = client.post("/admin/run-reminders", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 409


def test_run_reminders_test_mode_refuses_without_allowlist(client, monkeypatch):
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    r = client.post("/admin/run-reminders?test=1", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 400


# ── The dashboard HTML emits no token-bearing links ──────────────────────────

@pytest.mark.asyncio
async def test_dashboard_html_has_no_token_in_links(client):
    # Build the app's real tables and seed one user, so the per-user convo link
    # (the worst old offender: /admin/user/{id}?token=…) actually renders.
    from db.database import engine, Base, AsyncSessionLocal
    import db.models as models  # noqa: F401  (registers tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        db.add(models.User(telegram_id="7777", name="Linktest", onboarding_completed=True))
        await db.commit()

    r = client.get("/admin", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 200
    # The per-user link is present…
    assert "/admin/user/" in r.text
    # …and nothing in the page carries the secret, in any link or form action.
    assert "token=" not in r.text
    assert "?token=" not in r.text
    # And viewing it plants the cookie for subsequent tokenless clicks.
    assert ADMIN_COOKIE_NAME in r.headers.get("set-cookie", "")
