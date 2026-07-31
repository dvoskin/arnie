"""Inbound webhooks must authenticate their sender (B7, 2026-07-31).

Two webhooks drive real side effects from an unauthenticated origin:

  * Telegram `/webhook/{token}` — the token is compared in constant time now,
    and a configured secret-token header is a required second factor.
  * BlueBubbles `/imessage` — verify_bb_signature FAILS CLOSED when no secret
    is set, reversing a default-open door that a live probe caught accepting
    unsigned posts in production.
"""
import hashlib
import hmac

import pytest
from starlette.testclient import TestClient

import api.app as app_mod
from bot.imessage_handler import verify_bb_signature
from core import ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit._reset_for_tests()
    yield
    ratelimit._reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app_mod.app)


# ── Telegram: constant-time token + secret-token header ──────────────────────

def test_telegram_wrong_path_token_forbidden(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "real-bot-token")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    assert client.post("/webhook/wrong-token", json={}).status_code == 403


def test_telegram_correct_token_passes_auth(client, monkeypatch):
    # No ptb_app wired in the test process, so a request that CLEARS auth reaches
    # the "Bot not ready" 503. That 503 (not 403) is the proof auth passed.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "real-bot-token")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    assert client.post("/webhook/real-bot-token", json={}).status_code == 503


def test_telegram_secret_header_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "real-bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hdr-secret")
    # Right path token, missing/wrong header → still 403.
    assert client.post("/webhook/real-bot-token", json={}).status_code == 403
    assert client.post("/webhook/real-bot-token", json={},
                       headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403
    # Right path token AND right header → auth passes (503 bot-not-ready).
    ok = client.post("/webhook/real-bot-token", json={},
                     headers={"X-Telegram-Bot-Api-Secret-Token": "hdr-secret"})
    assert ok.status_code == 503


# ── BlueBubbles: fail closed ─────────────────────────────────────────────────

def _sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_bb_fails_closed_when_secret_unset(monkeypatch):
    monkeypatch.delenv("BLUEBUBBLES_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("IMESSAGE_WEBHOOK_ALLOW_UNSIGNED", raising=False)
    # The exact production state a probe caught open on 2026-07-31 → now rejected.
    assert verify_bb_signature(b"{}", "") is False
    assert verify_bb_signature(b"{}", "sha256=deadbeef") is False


def test_bb_dev_escape_hatch(monkeypatch):
    monkeypatch.delenv("BLUEBUBBLES_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("IMESSAGE_WEBHOOK_ALLOW_UNSIGNED", "true")
    assert verify_bb_signature(b"{}", "") is True


def test_bb_verifies_when_secret_set(monkeypatch):
    monkeypatch.setenv("BLUEBUBBLES_WEBHOOK_SECRET", "shared")
    monkeypatch.delenv("IMESSAGE_WEBHOOK_ALLOW_UNSIGNED", raising=False)
    body = b'{"type":"new-message"}'
    assert verify_bb_signature(body, _sig(body, "shared")) is True
    assert verify_bb_signature(body, _sig(body, "wrong-secret")) is False
    assert verify_bb_signature(body, "") is False


def test_imessage_endpoint_rejects_unsigned(client, monkeypatch):
    monkeypatch.delenv("BLUEBUBBLES_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("IMESSAGE_WEBHOOK_ALLOW_UNSIGNED", raising=False)
    # End to end: an unsigned POST to the live route is now a 403, not a 200.
    r = client.post("/imessage", content=b'{"type":"new-message"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 403
