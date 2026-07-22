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

import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
_FIELDS = "product_name,brands,nutriments,serving_size,quantity"
# OFF asks for a descriptive UA so they can contact abusers instead of blocking.
_UA = "Arnie/1.0 (nutrition coach; contact: support@tryarnie.com)"

_http: Optional[httpx.AsyncClient] = None


def off_enabled() -> bool:
    """Kill switch. Default ON (public API, no key). OFF_ENRICH=false disables."""
    return os.getenv("OFF_ENRICH", "true").lower() in ("true", "1", "yes")


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=6.0, headers={"User-Agent": _UA})
    return _http


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((s or "").lower()) if len(t) > 1}


def _overlap(query: str, product: str, brands: str) -> float:
    """Fraction of the QUERY's tokens found in the product name + brands. Query-
    anchored (not Jaccard) so a long product title doesn't dilute a good match."""
    q = _tokens(query)
    if not q:
        return 0.0
    p = _tokens(product) | _tokens(brands)
    return len(q & p) / len(q)


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


async def search(name: str, page_size: int = 8) -> Optional[dict]:
    """Search OFF by name; return a candidate {per100g, _match, name, brand} for
    the best strongly-matching product, or None. Never raises."""
    if not off_enabled() or not (name or "").strip():
        return None
    params = {
        "search_terms": name, "search_simple": 1, "action": "process",
        "json": 1, "page_size": page_size, "fields": _FIELDS,
    }
    try:
        r = await _client().get(_SEARCH_URL, params=params)
        if r.status_code != 200:
            return None
        products = (r.json() or {}).get("products") or []
    except Exception as e:
        logger.warning("OFF search failed for %r: %s: %s", name, type(e).__name__, e)
        return None

    best = None
    best_ov = 0.0
    for p in products:
        pname = (p.get("product_name") or "").strip()
        if not pname:
            continue
        ov = _overlap(name, pname, p.get("brands") or "")
        if ov > best_ov:
            per100 = _per100g(p.get("nutriments") or {})
            if per100 is not None:
                best, best_ov = (p, per100), ov

    # Conservative gate: only trust a strong name match (else the LLM estimate wins).
    if best is None or best_ov < 0.6:
        return None
    p, per100 = best
    return {
        "per100g": per100,
        "_match": "exact" if best_ov >= 0.85 else "likely",
        "name": (p.get("product_name") or "").strip(),
        "brand": (p.get("brands") or "").split(",")[0].strip() or None,
        "source": "off",
    }
