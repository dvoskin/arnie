"""The shared limiter, and the client-IP resolution it depends on (B7).

The value here beyond "it counts" is the proxy case: behind Render the app's
peer is the proxy, so a limiter keyed on the peer buckets everyone together.
`client_ip` only believes X-Forwarded-For when TRUST_PROXY_HEADERS says a
trusted proxy is in front — otherwise a caller could forge a fresh IP per
request and never be limited at all.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core import ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit._reset_for_tests()
    yield
    ratelimit._reset_for_tests()


def _req(peer="1.2.3.4", xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_allows_up_to_limit_then_429():
    for _ in range(3):
        ratelimit.check("b", "k", limit=3, window_seconds=60)  # 3 allowed
    with pytest.raises(HTTPException) as e:
        ratelimit.check("b", "k", limit=3, window_seconds=60)  # 4th trips
    assert e.value.status_code == 429


def test_keys_are_independent():
    for _ in range(3):
        ratelimit.check("b", "alice", limit=3, window_seconds=60)
    # bob has his own bucket — alice exhausting hers doesn't limit him.
    ratelimit.check("b", "bob", limit=3, window_seconds=60)


def test_buckets_are_independent():
    for _ in range(3):
        ratelimit.check("bucketA", "k", limit=3, window_seconds=60)
    ratelimit.check("bucketB", "k", limit=3, window_seconds=60)  # different bucket


def test_window_evicts_old_hits():
    # window 0 → every prior hit is already outside it, so the count never grows.
    for _ in range(100):
        ratelimit.check("b", "k", limit=1, window_seconds=0)


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    # Spoofed XFF must be ignored, or the limiter is defeatable per request.
    assert ratelimit.client_ip(_req(peer="10.0.0.1", xff="9.9.9.9")) == "10.0.0.1"


def test_client_ip_trusts_forwarded_header_when_enabled(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    # First hop is the real client, before the proxy chain.
    assert ratelimit.client_ip(_req(peer="10.0.0.1", xff="9.9.9.9, 10.0.0.1")) == "9.9.9.9"


def test_check_request_keys_on_resolved_ip(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    a = _req(peer="10.0.0.1", xff="203.0.113.1")
    b = _req(peer="10.0.0.1", xff="203.0.113.2")
    # Same proxy peer, different real clients → different buckets, so one hitting
    # the limit doesn't lock out the other. This is the whole point of the fix.
    for _ in range(2):
        ratelimit.check_request(a, "t", limit=2, window_seconds=60)
    with pytest.raises(HTTPException):
        ratelimit.check_request(a, "t", limit=2, window_seconds=60)
    ratelimit.check_request(b, "t", limit=2, window_seconds=60)  # b unaffected
