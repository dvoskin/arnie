"""
Places client (Google Places) — the lookup behind Arnie's find_nearby_places tool.

Deliberately mirrors core/search.py so the two "external lookup" tools share one
shape: a lazy module-level httpx.AsyncClient singleton, a _key() reading the env,
a small TTL cache, and ONE public async function `find()` that NEVER raises to the
caller. On a missing key, a non-200, or any exception, it returns a graceful EMPTY
PlacesResult (error set, results=[]) so a Places outage degrades to a normal tool
failure instead of breaking the turn.

Gated upstream by db.queries.location_enabled() (default OFF). This module is inert
until LOCATION_ENABLED=true — nothing imports it on the default path.

Key: GOOGLE_PLACES_API_KEY env var.
API: Places Text Search (legacy) — https://developers.google.com/maps/documentation/places/web-service/search-text

Why Text Search and not Nearby Search: Text Search accepts a free-text query
("high protein restaurants in Brooklyn") and works WITHOUT exact GPS coordinates,
so v1 is usable from a city/area the user mentions in chat. When real lat/lng IS
available (e.g. a Telegram shared-location stored on the user), we pass it as a
location bias so results are genuinely "around them".

The `_client` param on find() is the TEST SEAM — inject a fake client so tests
never hit the network. reset_cache() clears the in-process TTL cache for test
isolation.
"""
import os
import re
import time
import logging
import dataclasses
from urllib.parse import quote_plus
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_PROVIDER = "google_places"

# In-process TTL cache (KISS — no Redis). Keyed on normalized query + coords.
_CACHE_TTL_SECONDS = 300.0
_cache: dict[str, tuple[float, "PlacesResult"]] = {}

_http: Optional[httpx.AsyncClient] = None


@dataclasses.dataclass
class Place:
    name: str = ""
    address: str = ""
    rating: Optional[float] = None
    user_ratings: Optional[int] = None
    open_now: Optional[bool] = None
    price_level: Optional[int] = None
    maps_url: str = ""


@dataclasses.dataclass
class PlacesResult:
    """One places lookup outcome. On failure, `error` is set and `results` is empty.
    `query` stays populated on success and failure so the caller can echo it."""
    results: list = dataclasses.field(default_factory=list)
    query: str = ""
    cache_hit: bool = False
    provider: str = _PROVIDER
    error: Optional[str] = None


def _key() -> str:
    return os.getenv("GOOGLE_PLACES_API_KEY", "")


def _client_singleton() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=8.0)
    return _http


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def reset_cache() -> None:
    """Clear the in-process cache. For test isolation."""
    _cache.clear()


def _empty(query: str, error: str) -> PlacesResult:
    """A graceful empty result — never raised, always returned."""
    return PlacesResult(results=[], query=query, cache_hit=False,
                        provider=_PROVIDER, error=error)


def _maps_url(name: str, address: str, place_id: str) -> str:
    """Deep link to the place on Google Maps. Using the documented /maps/search
    api=1 form with query_place_id is the most reliable — opens the exact place
    and lets the user tap Directions natively (no Directions API needed)."""
    q = quote_plus(f"{name} {address}".strip())
    if place_id:
        return f"https://www.google.com/maps/search/?api=1&query={q}&query_place_id={place_id}"
    return f"https://www.google.com/maps/search/?api=1&query={q}"


async def find(query: str, *, lat: Optional[float] = None, lng: Optional[float] = None,
               radius_m: int = 2500, limit: int = 6,
               _client: Optional[httpx.AsyncClient] = None) -> PlacesResult:
    """
    Find real-world places matching `query`. Returns a PlacesResult; NEVER raises.

    lat/lng — optional. When both are present they bias results toward that point
    (genuine "near me"). When absent, the free-text query carries the location
    intent ("ramen in Shoreditch"), which still works.
    `_client` is the injectable test seam (defaults to the module singleton).
    """
    q = (query or "").strip()
    if not q:
        return _empty(query, "empty query")

    has_coords = lat is not None and lng is not None
    norm = f"{_normalize(q)}|{lat},{lng}" if has_coords else _normalize(q)
    now = time.monotonic()
    cached = _cache.get(norm)
    if cached and cached[0] > now:
        return dataclasses.replace(cached[1], cache_hit=True)

    if not _key():
        return _empty(q, "no api key")

    params: dict[str, Any] = {"query": q, "key": _key()}
    if has_coords:
        params["location"] = f"{lat},{lng}"
        params["radius"] = max(100, min(int(radius_m), 50000))

    client = _client if _client is not None else _client_singleton()
    try:
        resp = await client.get(_BASE, params=params)
        if resp.status_code != 200:
            logger.warning(f"Places search {resp.status_code}: {resp.text[:120]}")
            return _empty(q, f"http {resp.status_code}")
        data = resp.json()
    except Exception as e:
        logger.warning(f"Places search failed: {e}")
        return _empty(q, str(e))

    status = data.get("status", "")
    # ZERO_RESULTS is a valid "nothing nearby" answer, not an error.
    if status not in ("OK", "ZERO_RESULTS"):
        return _empty(q, data.get("error_message") or status or "unknown error")

    places: list[Place] = []
    for r in (data.get("results") or [])[:limit]:
        oh = r.get("opening_hours") or {}
        places.append(Place(
            name=r.get("name", ""),
            address=r.get("formatted_address", "") or r.get("vicinity", ""),
            rating=r.get("rating"),
            user_ratings=r.get("user_ratings_total"),
            open_now=oh.get("open_now") if isinstance(oh, dict) else None,
            price_level=r.get("price_level"),
            maps_url=_maps_url(r.get("name", ""), r.get("formatted_address", ""),
                               r.get("place_id", "")),
        ))

    result = PlacesResult(results=places, query=q, cache_hit=False,
                          provider=_PROVIDER, error=None)
    _cache[norm] = (now + _CACHE_TTL_SECONDS, result)
    return result
