"""
Places client (Google Places API — NEW) — the lookup behind find_nearby_places.

Uses the NEW Places API Text Search (places.googleapis.com/v1/places:searchText)
rather than the legacy /maps/api/place/textsearch endpoint, because Google only
lets newly-created Cloud projects enable "Places API (New)" — the legacy Places
API can't be turned on for fresh projects. The new endpoint is a POST with the
key in a header and the returned fields chosen via a FieldMask header.

Deliberately mirrors core/search.py in shape: a lazy module-level httpx client, a
_key() reading the env, a small TTL cache, and ONE public async function `find()`
that NEVER raises. On a missing key / non-200 / exception it returns a graceful
EMPTY PlacesResult so a Places outage degrades to a normal tool failure.

Gated upstream by db.queries.location_enabled() (default OFF). Inert until
LOCATION_ENABLED=true.

Key: GOOGLE_PLACES_API_KEY env var (the "Places API (New)" must be enabled on it).
API: https://developers.google.com/maps/documentation/places/web-service/text-search
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

_BASE = "https://places.googleapis.com/v1/places:searchText"
_PROVIDER = "google_places_new"

# Only ask Google for the fields we actually use — a tight FieldMask keeps the
# request on the cheapest SKU tier and the payload small.
_FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.rating,"
    "places.userRatingCount,places.currentOpeningHours.openNow,"
    "places.priceLevel,places.id,places.googleMapsUri"
)

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
    price_level: Optional[str] = None
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


def _fallback_maps_url(name: str, address: str, place_id: str) -> str:
    """Used only if the API didn't return googleMapsUri (it almost always does)."""
    q = quote_plus(f"{name} {address}".strip())
    if place_id:
        return f"https://www.google.com/maps/search/?api=1&query={q}&query_place_id={place_id}"
    return f"https://www.google.com/maps/search/?api=1&query={q}"


async def find(query: str, *, lat: Optional[float] = None, lng: Optional[float] = None,
               radius_m: int = 2500, limit: int = 6,
               _client: Optional[httpx.AsyncClient] = None) -> PlacesResult:
    """
    Find real-world places matching `query`. Returns a PlacesResult; NEVER raises.

    lat/lng — optional. When both present they bias results toward that point
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

    body: dict[str, Any] = {"textQuery": q, "maxResultCount": max(1, min(limit, 20))}
    if has_coords:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": float(max(1, min(int(radius_m), 50000))),
            }
        }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _key(),
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    client = _client if _client is not None else _client_singleton()
    try:
        resp = await client.post(_BASE, json=body, headers=headers)
        if resp.status_code != 200:
            logger.warning(f"Places(new) {resp.status_code}: {resp.text[:160]}")
            return _empty(q, f"http {resp.status_code}")
        data = resp.json()
    except Exception as e:
        logger.warning(f"Places(new) search failed: {e}")
        return _empty(q, str(e))

    places: list[Place] = []
    for r in (data.get("places") or [])[:limit]:
        oh = r.get("currentOpeningHours") or {}
        dn = r.get("displayName") or {}
        name = dn.get("text", "") if isinstance(dn, dict) else (dn or "")
        maps_url = r.get("googleMapsUri") or _fallback_maps_url(
            name, r.get("formattedAddress", ""), r.get("id", ""))
        places.append(Place(
            name=name,
            address=r.get("formattedAddress", ""),
            rating=r.get("rating"),
            user_ratings=r.get("userRatingCount"),
            open_now=oh.get("openNow") if isinstance(oh, dict) else None,
            price_level=r.get("priceLevel"),
            maps_url=maps_url,
        ))

    result = PlacesResult(results=places, query=q, cache_hit=False,
                          provider=_PROVIDER, error=None)
    _cache[norm] = (now + _CACHE_TTL_SECONDS, result)
    return result
