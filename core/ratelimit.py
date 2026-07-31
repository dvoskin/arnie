"""One in-process rate limiter, and one honest answer to "who is the client".

Before this, two endpoints (`/imessage/start`, `/api/preregister`) each carried
their own copy-pasted per-IP dict, and the admin gate and the session mint —
the two surfaces where a guessable secret is checked — had no limit at all. So
`ADMIN_TOKEN` could be brute-forced as fast as the network allowed, and the two
limiters that did exist keyed on `request.client.host`.

`request.client.host` behind Render is the PROXY, not the caller. Uvicorn is
started without `--proxy-headers` (see `main.py`), so every real user shares one
address from the app's point of view. That makes the old limiters simultaneously
too strict (one abuser trips the limit for everyone) and useless (they cannot
tell two callers apart). `client_ip` fixes the source; `check` centralises the
bucket.

This is a single-process, in-memory limiter. It is deliberately NOT Redis: the
service runs as one Render web process, an in-memory counter is exactly as
durable as the `app.state` dicts it replaces, and reaching for a datastore to
gate an admin page would be the wrong amount of machinery. If the service ever
scales horizontally, each process limits independently — worth a comment here so
that is a known property, not a surprise.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from fastapi import HTTPException, Request

#: bucket -> {key: [monotonic timestamps within the window]}. Guarded by _LOCK
#: because Starlette runs sync dependencies in a threadpool, so two admin hits
#: can land in `check` at once.
_HITS: dict[str, dict[str, list]] = {}
_LOCK = threading.Lock()


def _trust_proxy_headers() -> bool:
    """Whether `X-Forwarded-For` may be believed.

    Off by default: a forwarded header is caller-supplied and trivially spoofed,
    so trusting it without a proxy in front would let an attacker forge a fresh
    IP per request and defeat the limiter entirely. Render terminates TLS at its
    own proxy and appends the real client, so this is safe to turn ON in prod
    (`TRUST_PROXY_HEADERS=true`) and only there.
    """
    return os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    """The best available caller address.

    With `TRUST_PROXY_HEADERS` set, the FIRST entry of `X-Forwarded-For` — the
    original client, before the proxy chain. Without it, the direct peer. Never
    raises; an unknown caller collapses to a single `"?"` bucket, which fails
    safe (shared, therefore stricter) rather than open.
    """
    if _trust_proxy_headers():
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip() or "?"
    return request.client.host if request.client else "?"


def check(bucket: str, key: str, *, limit: int, window_seconds: float) -> None:
    """Record one hit for (bucket, key); raise 429 if it exceeds `limit` in the
    trailing `window_seconds`. The hit is counted even when it trips the limit,
    so a caller hammering the endpoint keeps the window open — the intended
    behaviour for a brute-force attempt, which should not be rewarded for
    stopping exactly at the boundary.
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        buck = _HITS.setdefault(bucket, {})
        hits = [t for t in buck.get(key, ()) if t > cutoff]
        hits.append(now)
        buck[key] = hits
        # Opportunistic eviction: drop other keys whose newest hit has aged out,
        # so an attacker cycling addresses can't grow the dict without bound.
        if len(buck) > 2048:
            for k in [k for k, v in buck.items() if not v or v[-1] <= cutoff]:
                buck.pop(k, None)
        count = len(hits)
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests — slow down and try again shortly.",
        )


def check_request(request: Request, bucket: str, *, limit: int,
                  window_seconds: float, key: Optional[str] = None) -> None:
    """`check` with the key defaulted to the caller's IP — the common case."""
    check(bucket, key or client_ip(request), limit=limit,
          window_seconds=window_seconds)


def _reset_for_tests() -> None:
    with _LOCK:
        _HITS.clear()
