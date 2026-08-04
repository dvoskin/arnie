"""A host we already know is down is not worth asking again.

`off.search` consults the legacy cgi/search.pl endpoint first and falls back to
Search-a-licious; its own docstring puts the legacy 503 rate at ~1/3 of calls.
Measured on prod 2026-08-03 (the Cali Roll turn), one lookup against a degraded
legacy endpoint spent 2.1 s — three 503s and ~1.0 s of backoff sleep — to reach
a fallback that answered on its first try. The next food in the same paste paid
it again, because nothing remembered.

These pin the remembering. Not the timings (a clock assertion is a flake); the
COUNT of requests to the dead host, which is the thing that costs the seconds.
"""
import asyncio

import pytest

import skills.nutrition.off as off


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = {}

    def json(self):
        return self._payload


class _Client:
    """Counts requests per host. Legacy always 503s; SAL always answers."""

    def __init__(self):
        self.legacy = 0
        self.sal = 0

    async def get(self, url, params=None, timeout=None):
        if url == off._SEARCH_URL:
            self.legacy += 1
            return _Resp(503)
        self.sal += 1
        return _Resp(200, {"hits": [{
            "product_name": "Cali Roll", "brands": ["Sushi Daily"],
            "nutriments": {"energy-kcal_100g": 149, "proteins_100g": 4,
                           "carbohydrates_100g": 28, "fat_100g": 2},
        }]})


@pytest.fixture
def client(monkeypatch):
    c = _Client()
    monkeypatch.setattr(off, "_client", lambda: c)
    # The backoff is the expensive part; a test must not actually sleep it.
    async def _no_sleep(_s):
        return None
    monkeypatch.setattr(off, "_asleep", _no_sleep)
    monkeypatch.setenv("OFF_ENABLED", "true")
    monkeypatch.setenv("OFF_FALLBACK_ENABLED", "true")
    return c


def test_the_second_lookup_does_not_re_ask_a_dead_host(client):
    """The whole point: lookup #1 discovers legacy is down, #2 skips it.

    Before the breaker every lookup in a multi-item paste paid three 503s and
    the backoff between them, independently.
    """
    asyncio.run(off.search("Cali Roll"))
    first = client.legacy
    assert first >= 1, "the first lookup should try legacy at all"

    asyncio.run(off.search("Miso soup"))
    assert client.legacy == first, (
        f"legacy was asked again after it was known down "
        f"({client.legacy} total vs {first} after the first lookup)")
    assert client.sal >= 2, "both lookups must still be answered by the fallback"


def test_the_answer_is_unchanged_while_the_breaker_is_open(client):
    """Skipping legacy may not change what the user gets. Legacy is consulted
    first only for its ranking, and a hard failure carries no ranking."""
    a = asyncio.run(off.search("Cali Roll"))
    b = asyncio.run(off.search("Cali Roll"))
    assert a is not None and b is not None
    assert a["name"] == b["name"] == "Cali Roll"
    assert a["per100g"] == b["per100g"]
    assert a["source"] == b["source"] == "off"


def test_one_success_closes_it(client, monkeypatch):
    """A recovered host must be used again — a breaker that never closes is an
    outage of our own making."""
    asyncio.run(off.search("Cali Roll"))
    assert off._legacy_is_down(), "two hard failures should open it"

    async def _ok(url, params=None, timeout=None):
        client.legacy += 1
        return _Resp(200, {"products": [{
            "product_name": "Cali Roll", "brands": "Sushi Daily",
            "nutriments": {"energy-kcal_100g": 149, "proteins_100g": 4,
                           "carbohydrates_100g": 28, "fat_100g": 2},
        }]})
    monkeypatch.setattr(client, "get", _ok)
    off._BREAKER.clear()                    # cooldown elapsed
    asyncio.run(off.search("Cali Roll"))
    assert not off._legacy_is_down(), "a success must close the breaker"


def test_a_single_503_is_not_enough_to_trip_it(client):
    """The breaker keys on a HARD failure, not on one refused request.

    `_get_json` retries three times with backoff before `_search_legacy`
    reports failure, so by the time the breaker hears anything the host has
    already refused three times over ~1 s. That is the unit that should open
    it — and it is why a trip threshold of 1 is not twitchy. A transient blip
    that the retries absorb never reaches `_note_legacy` at all.
    """
    off._BREAKER.clear()
    asyncio.run(off.search("Cali Roll"))
    assert client.legacy >= 3, (
        f"a hard failure should mean the retries were exhausted first, "
        f"saw {client.legacy} request(s)")
    assert off._legacy_is_down(), "one exhausted lookup should open it"


# ── the breaker must key on the HOST, not on the answer ──────────────────────

def test_an_exhausted_turn_budget_does_not_open_it(client, monkeypatch):
    """`_get_json` returns None on the budget path BEFORE any request, and
    `_search_legacy` counted that as a hard failure — so a turn that ran out of
    time opened a process-global 120s breaker having made ZERO HTTP requests,
    for every other concurrent user. "No answer" has causes that say nothing
    about the host."""
    from core import deadline

    off._BREAKER.clear()
    with deadline.budget(0.001):
        asyncio.run(off.search("Cali Roll"))
    assert client.legacy == 0, "a request was made despite no budget"
    assert not off._legacy_is_down(), (
        "the breaker opened without ever asking the host")


def test_a_genuine_refusal_still_opens_it(client):
    """The signal it exists for: retries exhausted against 502/503/429."""
    off._BREAKER.clear()
    asyncio.run(off.search("Cali Roll"))
    assert client.legacy >= 3
    assert off._legacy_is_down()
