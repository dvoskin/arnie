"""
Reverse-geocode client (Google Geocoding) — turns lat/lng into a human city name.

Same shape as core/search.py and core/places.py: lazy httpx singleton, _key()
from env, small TTL cache, and ONE public async function `reverse()` that NEVER
raises. On a missing key / non-200 / exception it returns None, so a geocoding
outage just means "we keep the coordinates but don't know the city name yet" —
it never breaks a turn.

Reuses GOOGLE_PLACES_API_KEY (the Geocoding API must be enabled on that key in
Google Cloud — same project, no separate secret). Gated upstream by
location_enabled(); nothing imports this on the default path.

API: https://developers.google.com/maps/documentation/geocoding
"""
import os
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://maps.googleapis.com/maps/api/geocode/json"
_CACHE_TTL_SECONDS = 86400.0  # a coordinate's city doesn't change — cache a day
_cache: dict[str, tuple[float, Optional[str]]] = {}
_http: Optional[httpx.AsyncClient] = None


def _key() -> str:
    return os.getenv("GOOGLE_PLACES_API_KEY", "")


def _client_singleton() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=8.0)
    return _http


def reset_cache() -> None:
    _cache.clear()


def _pick_city(results: list) -> Optional[str]:
    """Pull the most human 'city' label from Geocoding address_components.
    Prefer locality; fall back to postal_town, then admin_area_2/1."""
    wanted = ("locality", "postal_town", "administrative_area_level_2",
              "administrative_area_level_1")
    best: dict[str, str] = {}
    for r in results:
        for comp in r.get("address_components", []):
            for t in comp.get("types", []):
                if t in wanted and t not in best:
                    best[t] = comp.get("long_name", "")
    for t in wanted:
        if best.get(t):
            return best[t]
    return None


async def reverse(lat: float, lng: float, *,
                  _client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """Return a city/town name for the coordinates, or None. NEVER raises.
    `_client` is the test seam (defaults to the module singleton)."""
    if lat is None or lng is None:
        return None
    norm = f"{round(float(lat), 3)},{round(float(lng), 3)}"
    now = time.monotonic()
    cached = _cache.get(norm)
    if cached and cached[0] > now:
        return cached[1]

    if not _key():
        return None

    params = {"latlng": f"{lat},{lng}", "key": _key(), "result_type":
              "locality|postal_town|administrative_area_level_2"}
    client = _client if _client is not None else _client_singleton()
    try:
        resp = await client.get(_BASE, params=params)
        if resp.status_code != 200:
            logger.warning(f"Geocode {resp.status_code}: {resp.text[:120]}")
            return None
        data = resp.json()
    except Exception as e:
        logger.warning(f"Geocode failed: {e}")
        return None

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    city = _pick_city(data.get("results") or [])
    _cache[norm] = (now + _CACHE_TTL_SECONDS, city)
    return city


# Separate cache for street-level lookups — same TTL semantics, different result
# shape ("116 Central Park S, New York, NY 10019"). Keeps the city cache
# untouched so existing callers that only need a city aren't affected.
_addr_cache: dict[str, tuple[float, Optional[str]]] = {}
_ADDR_CACHE_TTL_SECONDS = 6 * 3600.0  # 6h — addresses can shift block by block;
                                      # don't pin them as long as a city.


def reset_address_cache() -> None:
    _addr_cache.clear()


def _pick_street_address(results: list) -> Optional[str]:
    """Pull the most precise street-level formatted_address Google returned.
    Prefers a result tagged 'street_address' (an actual building/door); falls
    back to 'premise', 'subpremise', 'route' (street without a number), then
    'intersection'. Returns None if Google only gave a city-or-broader hit —
    we won't relay a city as if it were the user's exact spot."""
    PREFER = ("street_address", "premise", "subpremise", "route", "intersection")
    best_idx, best_rank = None, len(PREFER)
    for i, r in enumerate(results):
        for t in r.get("types", []):
            if t in PREFER:
                rank = PREFER.index(t)
                if rank < best_rank:
                    best_rank, best_idx = rank, i
                break
    if best_idx is None:
        return None
    addr = results[best_idx].get("formatted_address") or None
    if not addr:
        return None
    # Strip ", USA" / ", United Kingdom" country suffix so the model gets a
    # tidier line in context. Country is already implied by the city.
    for suffix in (", USA", ", United States", ", United Kingdom"):
        if addr.endswith(suffix):
            addr = addr[: -len(suffix)]
            break
    return addr.strip() or None


async def reverse_address(lat: float, lng: float, *,
                          _client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """Return a street-level address for the coordinates, or None. NEVER raises.
    Used by context_builder to surface 'Location: ON FILE (<street>, <city>)' so
    the model can answer 'where am I right now?' with precision instead of just
    a city. Returns None on a missing key / non-200 / no street-precise hit /
    exception — callers should fall back to the city-only `reverse()` result.
    `_client` is the test seam (defaults to the module singleton)."""
    if lat is None or lng is None:
        return None
    norm = f"{round(float(lat), 5)},{round(float(lng), 5)}"  # 5 decimals ≈ 1m
    now = time.monotonic()
    cached = _addr_cache.get(norm)
    if cached and cached[0] > now:
        return cached[1]

    if not _key():
        return None

    # NO result_type filter — we want the full result set so we can prefer a
    # street_address hit over the locality fallback. Google returns multiple
    # results per pin (street, neighborhood, city, county, country);
    # _pick_street_address selects the most precise one.
    params = {"latlng": f"{lat},{lng}", "key": _key()}
    client = _client if _client is not None else _client_singleton()
    try:
        resp = await client.get(_BASE, params=params)
        if resp.status_code != 200:
            logger.warning(f"Geocode (address) {resp.status_code}: {resp.text[:120]}")
            return None
        data = resp.json()
    except Exception as e:
        logger.warning(f"Geocode (address) failed: {e}")
        return None

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    addr = _pick_street_address(data.get("results") or [])
    _addr_cache[norm] = (now + _ADDR_CACHE_TTL_SECONDS, addr)
    return addr
