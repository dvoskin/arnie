"""
Web search client (Tavily) — the GENERIC lookup behind Arnie's web_search tool.

Mirrors api/usda.py: a lazy module-level httpx.AsyncClient singleton, a _key()
reading the env, and ONE public async function `search()` that NEVER raises to
the caller. On a missing key, a non-200, or any exception, it returns a graceful
EMPTY SearchResult (error set, results=[]) so a Tavily outage degrades to a normal
tool failure instead of breaking the turn.

Gated upstream by db.queries.search_enabled() (default OFF). This module is inert
until SEARCH_ENABLED=true — nothing imports it on the default path.

Key: TAVILY_API_KEY env var.
API: https://docs.tavily.com/

The `_client` param on search() is the TEST SEAM — inject a fake client so tests
never hit the network (Dependency-Inversion boundary, not an ABC). reset_cache()
clears the in-process TTL cache for test isolation.
"""
import os
import re
import time
import logging
import dataclasses
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.tavily.com"
_PROVIDER = "tavily"

# In-process TTL cache (KISS — no Redis / persistent store). Keyed on the
# normalized query → (expires_at, SearchResult).
_CACHE_TTL_SECONDS = 600.0
_cache: dict[str, tuple[float, "SearchResult"]] = {}

_http: Optional[httpx.AsyncClient] = None


@dataclasses.dataclass
class SearchResult:
    """One web-search outcome. On failure, `error` is set and `results` is empty;
    `answer` is the provider's synthesized answer (may be ""). `query` and
    `results` stay populated on success so a later lane (G4) could persist the
    facts — this module does NOT write them (YAGNI)."""
    answer: str = ""
    results: list = dataclasses.field(default_factory=list)
    query: str = ""
    cache_hit: bool = False
    provider: str = _PROVIDER
    error: Optional[str] = None


def _key() -> str:
    return os.getenv("TAVILY_API_KEY", "")


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=8.0)
    return _http


def _normalize(query: str) -> str:
    """Lowercase, trim, collapse internal whitespace — the cache key."""
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def reset_cache() -> None:
    """Clear the in-process cache. For test isolation."""
    _cache.clear()


def _empty(query: str, error: str) -> SearchResult:
    """A graceful empty result — never raised, always returned."""
    return SearchResult(answer="", results=[], query=query,
                        cache_hit=False, provider=_PROVIDER, error=error)


async def search(query: str, context: str = "", *,
                 _client: Optional[httpx.AsyncClient] = None) -> SearchResult:
    """
    Look something up on the open web. Returns a SearchResult; NEVER raises.

    `context` is folded into the query intent (e.g. logged injuries / profile
    bias) so the lookup is profile-aware. `_client` is the injectable test seam
    (defaults to the module httpx singleton) so tests never hit the network.

    Cache: identical normalized queries within the TTL return cache_hit=True.
    """
    q = (query or "").strip()
    if not q:
        return _empty(query, "empty query")

    norm = _normalize(q)
    now = time.monotonic()
    cached = _cache.get(norm)
    if cached and cached[0] > now:
        prev = cached[1]
        # Return a copy flagged as a cache hit — don't mutate the stored object.
        return dataclasses.replace(prev, cache_hit=True)

    if not _key():
        return _empty(q, "no api key")

    client = _client if _client is not None else globals()["_client"]()
    payload: dict[str, Any] = {
        "api_key": _key(),
        "query": q,
        "include_answer": True,
        "max_results": 5,
        "search_depth": "basic",
    }
    if context and context.strip():
        # Bias the lookup toward the user's situation (injuries, prefs, etc.).
        payload["query"] = f"{q} ({context.strip()})"

    try:
        resp = await client.post(f"{_BASE}/search", json=payload)
        if resp.status_code != 200:
            logger.warning(f"Tavily search {resp.status_code}: {resp.text[:120]}")
            return _empty(q, f"http {resp.status_code}")
        data = resp.json()
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return _empty(q, str(e))

    raw_results = []
    for r in (data.get("results") or []):
        raw_results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        })

    result = SearchResult(
        answer=(data.get("answer") or ""),
        results=raw_results,
        query=q,
        cache_hit=False,
        provider=_PROVIDER,
        error=None,
    )
    _cache[norm] = (now + _CACHE_TTL_SECONDS, result)
    return result
