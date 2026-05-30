"""
USDA FoodData Central API client.

Provides accurate nutrition data (calories, macros, fiber, sugar, sodium, key
micros) for foods, used to ground Arnie's logging in real numbers instead of
pure LLM estimates. Falls back gracefully when the API key is missing or a
food isn't found — Arnie's estimate is always the safety net.

API: https://fdc.nal.usda.gov/api-guide.html
Key: USDA_API_KEY env var.
"""
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.nal.usda.gov/fdc/v1"

# FDC nutrient numbers → our keys
_NUTRIENT_MAP = {
    "208": "calories",   # Energy (kcal)
    "203": "protein",
    "204": "fat",
    "205": "carbs",
    "291": "fiber",
    "269": "sugar",
    "307": "sodium",     # mg
    "301": "calcium",    # mg
    "303": "iron",       # mg
    "306": "potassium",  # mg
}

_http: Optional[httpx.AsyncClient] = None


def _key() -> str:
    return os.getenv("USDA_API_KEY", "")


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=8.0)
    return _http


def _extract_nutrients(food: dict) -> dict:
    """Pull our nutrient set out of an FDC food record (per 100g)."""
    out = {}
    for n in food.get("foodNutrients", []):
        # search results use nutrientNumber; detail uses nested nutrient.number
        num = str(n.get("nutrientNumber") or n.get("nutrient", {}).get("number") or "")
        val = n.get("value")
        if val is None:
            val = n.get("amount")
        if num in _NUTRIENT_MAP and val is not None:
            out[_NUTRIENT_MAP[num]] = val
    return out


async def _search(query: str, data_types: list[str], page_size: int) -> list[dict]:
    """One USDA search request restricted to the given data types."""
    try:
        resp = await _client().post(
            f"{_BASE}/foods/search",
            params={"api_key": _key()},
            json={"query": query.strip(), "pageSize": page_size, "dataType": data_types},
        )
        if resp.status_code != 200:
            logger.warning(f"USDA search {resp.status_code}: {resp.text[:120]}")
            return []
        out = []
        for f in resp.json().get("foods", []):
            per100 = _extract_nutrients(f)
            if not per100.get("calories"):
                continue
            out.append({
                "fdc_id": f.get("fdcId"),
                "description": f.get("description", ""),
                "brand": f.get("brandName") or f.get("brandOwner") or "",
                "data_type": f.get("dataType", ""),
                "per100g": per100,
            })
        return out
    except Exception as e:
        logger.warning(f"USDA search failed: {e}")
        return []


def _looks_branded(query: str) -> bool:
    """Query names a specific product/brand (capitalized token or long phrase)."""
    toks = query.split()
    return len(toks) >= 4 or any(t[:1].isupper() for t in toks)


async def search_food(query: str, page_size: int = 5) -> list[dict]:
    """
    Search USDA for a food. Two-pass: USDA's CURATED data (Foundation, SR Legacy)
    is clean and trustworthy, so it's preferred for generic foods. Branded is
    crowdsourced/noisy, used only as a fallback — or first when the query clearly
    names a brand. Nutrients are per 100g. Empty list on miss/no-key/error.
    """
    if not _key() or not query.strip():
        return []

    curated = ["Foundation", "SR Legacy"]
    branded = ["Branded"]

    if _looks_branded(query):
        order = [branded, curated]
    else:
        order = [curated, branded]

    for data_types in order:
        res = await _search(query, data_types, page_size)
        if res:
            return res
    return []
