"""Resolution memoization (PR #30).

People eat the same things. "My usual shake" resolves identically fifty times a
week, and every one of those resolutions re-runs candidate scoring, identity
validation, bounds checking and scaling to reach the number it reached last
time. None of that is expensive on its own; all of it is on the critical path
of a turn the user is waiting through.

So: a small in-process memo, keyed on the resolution's INPUTS.

The key is the whole safety argument. `resolve()` is a pure function of
(request, candidates) — it reads no clock, no database and no environment, so
two calls with the same inputs must produce the same output, and caching it
cannot change an answer. That property is load-bearing, and there is a test
that fails if it stops holding.

What is deliberately NOT cached:

**Candidate fetching.** The candidates are part of the key, not the value. A
cache that remembered what USDA said would keep serving a stale product after a
correction, and the whole point of the resolver is that the label wins.

**Anything user-specific, implicitly.** A user's saved regulars and label values
arrive as candidates, so they are in the key already. Nothing here needs to
know about users, which means nothing here can leak between them — the
strongest form of that guarantee is not having the concept.

Bounded by entries and by age. An unbounded memo in a long-lived process is a
leak with a delay, and a memo with no TTL is a way to serve a deployment-old
answer after the scoring code has changed underneath it.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Optional

#: Bumped when the KEY changes meaning, so entries written under the old
#: scheme can never be read under the new one.
CACHE_VERSION = "resolution_cache_v2"

#: Entries. Small on purpose: this is a working-set cache for the foods a
#: process is currently seeing, not a store. The tail of the distribution is
#: exactly the part that should NOT be cached — a food logged once is a food
#: whose entry would only ever be evicted unused.
DEFAULT_MAX_ENTRIES = 512

#: Seconds. Short enough that a deploy which changes scoring cannot serve a
#: pre-deploy answer for long, long enough to cover a meal being logged item by
#: item across a few turns.
DEFAULT_TTL_S = 900.0


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> Optional[float]:
        """None rather than 0.0 when nothing was looked up.

        A hit rate of zero and no traffic are different facts, and a dashboard
        that cannot tell them apart reports a cold process as a broken cache.
        """
        return round(self.hits / self.lookups, 4) if self.lookups else None

    def log_line(self) -> str:
        rate = "-" if self.hit_rate is None else f"{self.hit_rate:.3f}"
        return (f"event=resolution_cache hits={self.hits} misses={self.misses} "
                f"rate={rate} evictions={self.evictions} "
                f"expirations={self.expirations}")


class ResolutionCache:
    """A bounded, expiring, thread-safe memo.

    Thread-safe because the process serves concurrent turns and a torn
    OrderedDict is a crash in a code path whose entire justification is that it
    is free.
    """

    def __init__(self, *, max_entries: int = DEFAULT_MAX_ENTRIES,
                 ttl_s: float = DEFAULT_TTL_S):
        self._entries: "OrderedDict[str, tuple]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self.ttl_s = ttl_s
        self.stats = CacheStats()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.stats = CacheStats()

    def get(self, key: str, *, now: Optional[float] = None) -> Optional[Any]:
        now = time.monotonic() if now is None else now
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            value, stored_at = entry
            if now - stored_at > self.ttl_s:
                del self._entries[key]
                self.stats.expirations += 1
                self.stats.misses += 1
                return None
            self._entries.move_to_end(key)
            self.stats.hits += 1
            return value

    def put(self, key: str, value: Any, *,
            now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._entries[key] = (value, now)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self.stats.evictions += 1

    def __len__(self) -> int:
        return len(self._entries)


#: The process-wide cache. One rather than per-caller: the working set is the
#: foods the PROCESS is seeing, and splitting it per module would just make
#: each copy colder.
CACHE = ResolutionCache()


def caching_enabled() -> bool:
    """Default OFF (review fix, PR #30).

    The safety argument for this cache is that `resolve()` is a pure function of
    (request, candidates), so a correct key cannot change an answer. That argument
    is sound and the key was not: it omitted the serving-basis numbers, so two
    candidates with different totals shared an entry. A cache whose key was wrong
    once ships off and earns its way on — limited canary first, hit rate and
    correction rate watched, then widened.

    `NUTRITION_RESOLUTION_CACHE=on` opts in.
    """
    raw = (os.getenv("NUTRITION_RESOLUTION_CACHE", "false") or "").strip().lower()
    return raw in ("1", "true", "on", "yes")


def _fingerprint(value, depth: int = 0) -> str:
    """Stable text for anything the resolver reads.

    Recursive and structural rather than a list of field names, because a
    hand-listed subset is a correctness bug waiting for the next field. The
    candidate side of the key WAS such a list, and it named the basis's TYPE
    ("per_serving") without any of the basis's own numbers — so a 30 g serving
    and a 60 g serving of the same product, with the same panel, shared a cache
    key and the second one got the first one's answer, wrong by 2x.

    Type names are included because the type is part of the meaning: PerServing()
    and PerUnit() are both empty of fields and are not the same basis. `basis` is
    a class attribute rather than a dataclass field, so a field walk alone cannot
    tell them apart.

    Nothing here may use `hash()` or `id()`: keys have to be identical across
    processes and restarts, and PYTHONHASHSEED makes `hash()` neither.
    """
    if depth > 6:                       # cycles, or a shape we should not cache
        raise ValueError("fingerprint too deep")
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return repr(value)

    # A NutrientProfile: a mapping of name → NutrientValue.
    #
    # The whole NutrientValue, not just its number. `resolver.score()` reads the
    # calories value's `confidence`, and the resolution carries source, basis and
    # `estimated` through to the user — so two candidates identical in value and
    # different in confidence are NOT the same input, and keying on the number
    # alone let the second lookup reuse the first's answer, with stale provenance
    # or, where candidates compete, a different winner entirely.
    values = getattr(value, "values", None)
    if values is not None and hasattr(values, "items"):
        return "profile(" + ",".join(
            f"{k}={_fingerprint(v, depth + 1)}"
            for k, v in sorted(values.items(), key=lambda kv: str(kv[0]))
        ) + ")"

    fields = getattr(value, "__dataclass_fields__", None)
    if fields:
        return f"{type(value).__name__}(" + ",".join(
            f"{name}={_fingerprint(getattr(value, name, None), depth + 1)}"
            for name in sorted(fields)
        ) + ")"

    if hasattr(value, "items"):
        return "{" + ",".join(
            f"{k!r}:{_fingerprint(v, depth + 1)}"
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        ) + "}"

    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_fingerprint(v, depth + 1) for v in value) + "]"

    return repr(value)


def key_for(request, candidates) -> Optional[str]:
    """A stable key over everything `resolve` reads, or None if it cannot be
    built.

    None means "do not cache this one" and is returned rather than raised: a
    request shape the key builder does not understand is a reason to skip the
    cache, never a reason to fail the turn.

    Every field that can change the answer is in the digest. A field that is NOT
    in it and does change the answer is a correctness bug, so both sides are
    walked structurally — see `_fingerprint`.
    """
    try:
        parts = [CACHE_VERSION, _fingerprint(request)]
        parts.extend(_fingerprint(candidate)
                     for candidate in (candidates or ()))
        return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
    except Exception:
        return None


def memoize(request, candidates, compute: Callable[[], Any]) -> Any:
    """Return the cached resolution for these inputs, or compute and store it.

    Falls through to `compute()` on any cache trouble at all. The cache is an
    optimization, and an optimization that can fail a turn is not one.
    """
    if not caching_enabled():
        return compute()
    key = key_for(request, candidates)
    if key is None:
        return compute()
    hit = CACHE.get(key)
    if hit is not None:
        return hit
    value = compute()
    CACHE.put(key, value)
    return value


def stats() -> CacheStats:
    return CACHE.stats
