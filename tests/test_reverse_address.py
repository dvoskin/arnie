"""Unit tests for core.geocode.reverse_address — the street-precision readback.

No network: a stub httpx client returns canned Geocoding API payloads so the
picker logic is exercised against the real shapes Google sends.
"""
import os
import pytest

from core import geocode


class _StubResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _StubClient:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status_code = status_code
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return _StubResp(self._status_code, self._payload)


_NYC_REAL_RESPONSE = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "116 Central Park S, New York, NY 10019, USA",
            "types": ["street_address"],
        },
        {
            "formatted_address": "Midtown, New York, NY, USA",
            "types": ["neighborhood", "political"],
        },
        {
            "formatted_address": "New York, NY, USA",
            "types": ["locality", "political"],
        },
        {
            "formatted_address": "United States",
            "types": ["country", "political"],
        },
    ],
}


@pytest.fixture(autouse=True)
def _key_and_cache_reset(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "stub-key")
    geocode.reset_address_cache()
    yield


@pytest.mark.asyncio
async def test_picks_street_address_over_city():
    stub = _StubClient(_NYC_REAL_RESPONSE)
    out = await geocode.reverse_address(40.7747, -73.9906, _client=stub)
    assert out == "116 Central Park S, New York, NY 10019"
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_falls_back_to_route_when_no_street_number():
    payload = {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Central Park S, New York, NY, USA",
                "types": ["route"],
            },
            {
                "formatted_address": "New York, NY, USA",
                "types": ["locality"],
            },
        ],
    }
    stub = _StubClient(payload)
    out = await geocode.reverse_address(40.7747, -73.9906, _client=stub)
    assert out == "Central Park S, New York, NY"


@pytest.mark.asyncio
async def test_returns_none_when_only_city_hit():
    payload = {
        "status": "OK",
        "results": [{
            "formatted_address": "New York, NY, USA",
            "types": ["locality", "political"],
        }],
    }
    stub = _StubClient(payload)
    out = await geocode.reverse_address(40.7747, -73.9906, _client=stub)
    assert out is None


@pytest.mark.asyncio
async def test_caches_subsequent_calls_at_same_pin():
    stub = _StubClient(_NYC_REAL_RESPONSE)
    a = await geocode.reverse_address(40.77470, -73.99060, _client=stub)
    b = await geocode.reverse_address(40.77470, -73.99060, _client=stub)
    assert a == b
    assert len(stub.calls) == 1, "second call should hit the cache"


@pytest.mark.asyncio
async def test_returns_none_on_missing_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    stub = _StubClient(_NYC_REAL_RESPONSE)
    out = await geocode.reverse_address(40.7747, -73.9906, _client=stub)
    assert out is None
    assert stub.calls == [], "must not call the API without a key"


@pytest.mark.asyncio
async def test_returns_none_on_http_error():
    stub = _StubClient({}, status_code=500)
    out = await geocode.reverse_address(40.7747, -73.9906, _client=stub)
    assert out is None


@pytest.mark.asyncio
async def test_returns_none_for_none_coords():
    stub = _StubClient(_NYC_REAL_RESPONSE)
    assert await geocode.reverse_address(None, None, _client=stub) is None
    assert stub.calls == []


@pytest.mark.asyncio
async def test_strips_country_suffix():
    payload = {
        "status": "OK",
        "results": [{
            "formatted_address": "10 Downing St, London SW1A 2AA, United Kingdom",
            "types": ["street_address"],
        }],
    }
    stub = _StubClient(payload)
    out = await geocode.reverse_address(51.5034, -0.1276, _client=stub)
    assert out == "10 Downing St, London SW1A 2AA"
