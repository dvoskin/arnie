"""Open Food Facts (OFF) name-search enrichment for TYPED branded foods.

The iOS app already uses OFF for BARCODE scans; this is the backend counterpart
for text logs ("a Barebells bar", "Fairlife core power") where there's no
barcode — it searches OFF by name and returns a per-100g candidate in the SAME
shape the USDA path returns, so core.food_intelligence.analyze() can rank it.

Public API, NO key required:
  https://world.openfoodfacts.org/cgi/search.pl?search_terms=...&json=1

CONSERVATIVE BY DESIGN — a fuzzy name search over a crowd-sourced DB will happily
return the wrong flavor. A wrong match is WORSE than the LLM's own estimate, so
this returns None unless the best product's name overlaps the query strongly
(>=0.6 token overlap) AND its macros are present and plausible. Never raises;
any error/timeout/miss -> None and the caller falls through unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_asleep = asyncio.sleep

_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
# Search-a-licious — OFF's newer search service. The legacy cgi/search.pl above
# returns HTTP 503 intermittently even at a low request rate (measured
# 2026-07-22: bare "Barebells"/"David protein bar" resolved only 1-2 of 3 tries),
# which surfaces as a silent enrichment miss. This is the fallback when the
# legacy endpoint is down; it returns the SAME per-100g nutriment keys, so the
# scorer/gate below are shared — only the hit envelope differs (hits[] + brands
# as a list). Kept as FALLBACK (not primary) so the legacy ranking that already
# resolves Core Power/David correctly is preserved.
_SAL_URL = "https://search.openfoodfacts.org/search"
_FIELDS = "product_name,brands,nutriments,serving_size,quantity"
# OFF asks for a descriptive UA so they can contact abusers instead of blocking.
_UA = "Arnie/1.0 (nutrition coach; contact: support@tryarnie.com)"
# Transient statuses worth retrying: 503 (the observed flake), 502, 429 (rate cap).
_RETRY_STATUS = frozenset((502, 503, 429))

_http: Optional[httpx.AsyncClient] = None


def off_enabled() -> bool:
    """Kill switch. Default ON (public API, no key). OFF_ENRICH=false disables."""
    return os.getenv("OFF_ENRICH", "true").lower() in ("true", "1", "yes")


def off_fallback_enabled() -> bool:
    """Whether to fall back to Search-a-licious when the legacy endpoint fails.
    Default ON. OFF_FALLBACK_SEARCH=false pins behavior to the legacy endpoint."""
    return os.getenv("OFF_FALLBACK_SEARCH", "true").lower() in ("true", "1", "yes")


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=6.0, headers={"User-Agent": _UA})
    return _http


_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Connectors carry no brand/flavor identity, but a crowd-sourced `brands` field
# stuffed with flavor text ("Breyers Cookies and Cream") can match them and
# inflate overlap — enough to tie a real brand hit and win on list order (the
# Breyers-vs-Barebells collision, 2026-07-22). Drop them from the overlap math.
_STOPWORDS = frozenset((
    "and", "with", "the", "of", "for", "in", "to", "an", "on", "or",
))


def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((s or "").lower())
            if len(t) > 1 and t not in _STOPWORDS}


def _overlap(query: str, product: str, brands: str) -> float:
    """Fraction of the QUERY's tokens found in the product name + brands. Query-
    anchored (not Jaccard) so a long product title doesn't dilute a good match."""
    q = _tokens(query)
    if not q:
        return 0.0
    p = _tokens(product) | _tokens(brands)
    return len(q & p) / len(q)


def _anchor(query: str) -> Optional[str]:
    """The query's brand-ish anchor: the first significant token in order. OFF is
    only searched for branded items, so this is almost always the brand name
    ("barebells", "fairlife", "david"). Used on the fallback path to reject
    wrong-brand entries whose generic flavor words alone clear the overlap gate."""
    for t in _TOKEN_RE.findall((query or "").lower()):
        if len(t) >= 3 and t not in _STOPWORDS:
            return t
    return None


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None   # reject NaN
    except (TypeError, ValueError):
        return None


def _per100g(nutriments: dict) -> Optional[dict]:
    """Map OFF nutriments -> the per-100g shape analyze() expects. Requires the
    four macros to be present and calories plausible, else None (noise/empty)."""
    if not isinstance(nutriments, dict):
        return None
    cal = _num(nutriments.get("energy-kcal_100g"))
    if cal is None:
        kj = _num(nutriments.get("energy_100g")) or _num(nutriments.get("energy-kj_100g"))
        cal = round(kj / 4.184, 1) if kj else None
    protein = _num(nutriments.get("proteins_100g"))
    carbs = _num(nutriments.get("carbohydrates_100g"))
    fat = _num(nutriments.get("fat_100g"))
    # All four macros must be present — a product missing them is unusable noise.
    if None in (cal, protein, carbs, fat):
        return None
    # Plausibility: 100g of real food is ~10-900 kcal. Reject sentinels (0, 9999).
    if not (10 <= cal <= 900):
        return None
    out = {"calories": round(cal, 1), "protein": round(protein, 1),
           "carbs": round(carbs, 1), "fat": round(fat, 1)}
    fiber = _num(nutriments.get("fiber_100g"))
    sugar = _num(nutriments.get("sugars_100g"))
    if fiber is not None:
        out["fiber"] = round(fiber, 1)
    if sugar is not None:
        out["sugar"] = round(sugar, 1)
    # Sodium: OFF gives grams. Prefer sodium_100g; else salt/2.5. Store mg.
    sodium_g = _num(nutriments.get("sodium_100g"))
    if sodium_g is None:
        salt_g = _num(nutriments.get("salt_100g"))
        sodium_g = salt_g / 2.5 if salt_g is not None else None
    if sodium_g is not None:
        out["sodium"] = round(sodium_g * 1000)
    return out


async def _get_json(url: str, params: dict, *, attempts: int = 3,
                    timeout: float = 5.0) -> Optional[dict]:
    """GET url?params and return parsed JSON, retrying transient failures.

    The legacy OFF search endpoint 503s intermittently (and instantly), so one
    shot silently drops the enrichment. Retry on _RETRY_STATUS and on network
    blips/timeouts with a short backoff. Timeouts are retried at most once (they
    already cost `timeout` seconds — piling on more would balloon a multi-item
    paste's latency). Returns None when every attempt fails. Never raises."""
    backoff = (0.3, 0.7, 1.2)
    timeout_used = False
    for i in range(attempts):
        try:
            r = await _client().get(url, params=params, timeout=timeout)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if isinstance(e, httpx.TimeoutException):
                if timeout_used:
                    return None
                timeout_used = True
            if i == attempts - 1:
                logger.warning("OFF GET %s failed (transport): %s", url, e)
                return None
            await _asleep(backoff[min(i, len(backoff) - 1)])
            continue
        except Exception as e:
            logger.warning("OFF GET %s errored: %s: %s", url, type(e).__name__, e)
            return None
        if r.status_code == 200:
            try:
                return r.json() or {}
            except Exception:
                return None
        if r.status_code in _RETRY_STATUS and i < attempts - 1:
            # Honor Retry-After when present, but cap it — a multi-second stall
            # here would serialize behind the concurrent USDA lookup for nothing.
            ra = _num(r.headers.get("retry-after"))
            await _asleep(min(ra, 1.5) if ra else backoff[min(i, len(backoff) - 1)])
            continue
        return None
    return None


def _best_candidate(name: str, products: list,
                    require_anchor: bool = False) -> Optional[tuple]:
    """Pick the best strongly-matching product from a normalized products list
    (each: {product_name, brands(str), nutriments}). Returns (product, per100g,
    overlap) or None. Shared by the legacy and Search-a-licious paths.

    require_anchor (fallback path only): skip any candidate that does NOT contain
    the query's brand anchor unless its overlap is near-exact (>=0.85). This kills
    wrong-brand entries ("Breyers Cookies and Cream" for a Barebells query) that
    only clear the gate on shared generic flavor words. The legacy path leaves
    this off so its memory-validated selection is untouched."""
    anchor = _anchor(name) if require_anchor else None
    best = None
    best_ov = 0.0
    for p in products:
        pname = (p.get("product_name") or "").strip()
        if not pname:
            continue
        ov = _overlap(name, pname, p.get("brands") or "")
        if anchor is not None and ov < 0.85:
            ptoks = _tokens(pname) | _tokens(p.get("brands") or "")
            if anchor not in ptoks:
                continue   # wrong brand riding on generic flavor words — skip
        if ov > best_ov:
            per100 = _per100g(p.get("nutriments") or {})
            if per100 is not None:
                best, best_ov = (p, per100), ov
    # Conservative gate: only trust a strong name match (else the LLM estimate wins).
    if best is None or best_ov < 0.6:
        return None
    p, per100 = best
    return p, per100, best_ov


async def _search_legacy(name: str, page_size: int) -> Optional[list]:
    """Query the legacy cgi/search.pl endpoint. Products already carry `brands`
    as a comma string. Returns the products list (possibly empty) or None on a
    hard failure (so the caller knows to try the fallback)."""
    params = {
        "search_terms": name, "search_simple": 1, "action": "process",
        "json": 1, "page_size": page_size, "fields": _FIELDS,
    }
    body = await _get_json(_SEARCH_URL, params)
    if body is None:
        return None
    return body.get("products") or []


async def _search_sal(name: str, page_size: int) -> Optional[list]:
    """Query Search-a-licious. Its hits carry `brands` as a LIST — normalize to
    the comma string the scorer/`brand` extraction expect. Returns products or
    None on hard failure."""
    params = {"q": name, "page_size": page_size, "fields": _FIELDS}
    body = await _get_json(_SAL_URL, params)
    if body is None:
        return None
    hits = body.get("hits") or []
    out = []
    for h in hits:
        b = h.get("brands")
        if isinstance(b, (list, tuple)):
            b = ", ".join(str(x) for x in b if x)
        out.append({
            "product_name": h.get("product_name"),
            "brands": b or "",
            "nutriments": h.get("nutriments") or {},
        })
    return out


async def search(name: str, page_size: int = 8) -> Optional[dict]:
    """Search OFF by name; return a candidate {per100g, _match, name, brand} for
    the best strongly-matching product, or None. Never raises.

    Tries the legacy endpoint (retried) first; only if it fails hard or yields
    no gated match does it fall back to Search-a-licious. Keeping legacy primary
    preserves the ranking that already resolves Core Power/David correctly, while
    the fallback rescues the ~1/3 of calls the legacy endpoint 503s away."""
    if not off_enabled() or not (name or "").strip():
        return None

    products = await _search_legacy(name, page_size)
    picked = _best_candidate(name, products) if products else None
    used = "legacy"

    if picked is None and off_fallback_enabled():
        sal = await _search_sal(name, page_size)
        alt = _best_candidate(name, sal, require_anchor=True) if sal else None
        if alt is not None:
            picked, used = alt, "sal"

    if picked is None:
        return None
    p, per100, best_ov = picked
    logger.info("OFF hit via %s for %r: %r (ov=%.2f)",
                used, name, (p.get("product_name") or "").strip(), best_ov)
    return {
        "per100g": per100,
        "_match": "exact" if best_ov >= 0.85 else "likely",
        "name": (p.get("product_name") or "").strip(),
        "brand": (p.get("brands") or "").split(",")[0].strip() or None,
        "source": "off",
    }
