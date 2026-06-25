"""
APNs HTTP/2 sender — slice 2b of the iOS push-notification work.

Sends a single alert to a single device token by POSTing to Apple's HTTP/2
APNs endpoint with an ES256-signed JWT. The .p8 ECDSA private key, key id,
team id, and bundle id are all read from environment variables; the JWT is
generated on demand and cached for 50 minutes (Apple's documented max is
60).

INERT WHEN UNCONFIGURED. `send_push` returns `{"ok": False, "error":
"not_configured"}` if any of the four required env vars is missing, so a
deploy without the .p8 in place is harmless (no crashes, just a logged
warning). This lets us land the sender + the scheduler hookup before
provisioning the credentials.

Out of scope here (handled in slice 2c — the scheduler hookup):
  - Fanning a notification out to every active device for a user
    (`active_device_tokens_for_user` + per-token send + 410 → revoke).
  - Choosing message text and timing.
This module deliberately exposes ONE primitive (`send_push`) so the
integration layer can compose freely.

Required env vars (set on Render dashboard before sending real pushes):
  APNS_KEY_ID         — 10-char key id from developer.apple.com
  APNS_TEAM_ID        — 10-char team id (matches DEVELOPMENT_TEAM in iOS
                         project.yml)
  APNS_BUNDLE_ID      — com.tryarnie.app
  APNS_AUTH_KEY_P8    — full PEM contents of the .p8 file (BEGIN PRIVATE
                         KEY…END PRIVATE KEY), multiline — Render's env-var
                         input accepts newlines.
  APNS_ENVIRONMENT    — optional default ("production" or "sandbox"); when
                         omitted defaults to "production". Per-call
                         `environment` arg overrides — required so a token
                         registered under sandbox routes to the sandbox
                         host even on a production-deployed backend.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx
import jwt

logger = logging.getLogger(__name__)

# Apple's HTTP/2 endpoints. Production is sticky to live-ID-signed tokens;
# sandbox is for Debug-built dev devices and TestFlight in some edge cases.
_APNS_HOST_PROD = "https://api.push.apple.com"
_APNS_HOST_SANDBOX = "https://api.sandbox.push.apple.com"

# Apple's published JWT lifetime is up to 60 minutes; refresh at 50 to leave
# a comfortable safety margin (clock skew, in-flight requests at expiry).
_JWT_TTL_SECONDS = 50 * 60

# Single-process JWT cache. Acceptable singleton because each worker has its
# own process and JWTs are cheap to re-mint per process. Tests can reset via
# `reset_jwt_cache()`.
_jwt_cache: Optional[tuple[str, float]] = None  # (token, expires_at_unix)


def is_configured() -> bool:
    """True iff every env var needed to send a push is set. Callers (the
    scheduler hookup, an /admin debug endpoint, etc.) should gate on this
    before attempting `send_push` so missing credentials surface as a
    skipped-with-warning rather than a per-call no-op surprise."""
    return all(
        os.getenv(k)
        for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID", "APNS_AUTH_KEY_P8")
    )


def _normalize_pem(value: str) -> str:
    """Defensive normalization for the .p8 PEM as it comes out of an env var.

    Strategy: if the value contains `-----BEGIN` and `-----END` markers,
    extract the base64 body BY STRIPPING EVERY NON-BASE64 CHARACTER, then
    re-flow at 64-char lines with proper header/footer. This handles every
    common env-var mangle path uniformly:

      - Real newlines (untouched PEM) — strip+reflow round-trips it.
      - Literal `\\n` escapes (JSON-serialized envs, shell-escaped exports).
      - Whitespace conversion (newlines turned into spaces or tabs by a
        textarea) — the common Render failure mode.
      - CRLF / CR line endings.
      - Random control chars or extra whitespace introduced by paste.

    Without this, `cryptography` raises `ValueError: MalformedFraming` at
    JWT-sign time, which surfaces as an opaque 500.
    """
    s = (value or "").strip()
    if "-----BEGIN" not in s or "-----END" not in s:
        # Not a PEM — pass through. Either the env var is something else, or
        # the caller has bigger problems we can't recover from here.
        return s

    # Unescape literal `\n` BEFORE the base64-filter pass — otherwise the `n`
    # in `\n` survives the filter (it's alphanumeric) and gets jammed into
    # the body where a newline used to be.
    if "\\n" in s:
        s = s.replace("\\n", "\n")

    # Reconstruct the header/footer cleanly. We KNOW it's a private key
    # because that's what APNs uses; the header type is well-defined.
    header = "-----BEGIN PRIVATE KEY-----"
    footer = "-----END PRIVATE KEY-----"

    # Find the body between the markers and aggressively strip everything
    # that isn't a valid base64 character. Base64 alphabet = A-Z a-z 0-9 + /
    # plus `=` for padding. This collapses newlines, spaces, tabs, CRs, and
    # any stray control chars.
    header_end = s.find("-----", s.find("-----") + 5) + 5
    footer_start = s.find("-----END")
    raw_body = s[header_end:footer_start]
    body = "".join(c for c in raw_body if c.isalnum() or c in "+/=")

    wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"{header}\n{wrapped}\n{footer}"


def diagnose_pem(value: str) -> dict:
    """Non-secret diagnostic about an APNs PEM env-var value. Returns counts
    and shape signals so /admin/debug/send-push can surface them on failure
    without leaking the key. Never returns any byte of the key body itself."""
    s = value or ""
    body_chars = s
    if "-----BEGIN" in s and "-----END" in s:
        header_end = s.find("-----", s.find("-----") + 5) + 5
        footer_start = s.find("-----END")
        body_chars = s[header_end:footer_start]
    base64_chars = sum(1 for c in body_chars if c.isalnum() or c in "+/=")
    return {
        "length": len(s),
        "newlines": s.count("\n"),
        "literal_backslash_n": s.count("\\n"),
        "spaces": s.count(" "),
        "carriage_returns": s.count("\r"),
        "has_begin_marker": "-----BEGIN" in s,
        "has_end_marker": "-----END" in s,
        "base64_chars_in_body": base64_chars,
        "non_base64_chars_in_body": len(body_chars) - base64_chars,
    }


def _build_jwt(now: float) -> str:
    """Sign a fresh APNs JWT. `iss` = team id, `iat` = now; `kid` = key id in
    the header (Apple looks it up against the public half of the .p8). The
    PEM is normalized first to survive env-var newline mangling."""
    return jwt.encode(
        {"iss": os.environ["APNS_TEAM_ID"], "iat": int(now)},
        _normalize_pem(os.environ["APNS_AUTH_KEY_P8"]),
        algorithm="ES256",
        headers={"kid": os.environ["APNS_KEY_ID"], "alg": "ES256"},
    )


def _get_jwt(*, now: Optional[float] = None) -> str:
    """Cached JWT, refreshing when within 60s of expiry. The injectable
    `now` lets tests advance the clock past TTL without sleeping."""
    global _jwt_cache
    current = now if now is not None else time.time()
    if _jwt_cache and _jwt_cache[1] > current + 60:
        return _jwt_cache[0]
    token = _build_jwt(current)
    _jwt_cache = (token, current + _JWT_TTL_SECONDS)
    return token


# 403 reasons that mean "the provider JWT is bad" (vs. a dead device token).
# These are recoverable by re-signing the JWT, so send_push refreshes + retries.
_AUTH_REJECT_REASONS = {"ExpiredProviderToken", "InvalidProviderToken"}


def reset_jwt_cache() -> None:
    """Force the next `_get_jwt` call to re-sign. Called on a 403 auth-reject
    in send_push (and by tests) so the next sign produces a fresh token."""
    global _jwt_cache
    _jwt_cache = None


def _host_for(environment: str) -> str:
    return _APNS_HOST_SANDBOX if environment.lower() == "sandbox" else _APNS_HOST_PROD


async def send_push(
    device_token: str,
    title: str,
    body: str,
    *,
    environment: Optional[str] = None,
    payload_extra: Optional[dict] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Send one push to one device.

    Args:
        device_token: hex device token from `db.device_tokens.token` (the
            string the iOS client POSTed to /devices/apns-token).
        title, body: alert text shown in the system banner / lock-screen
            notification.
        environment: "production" or "sandbox"; overrides APNS_ENVIRONMENT.
            Pass the value from the device-token row so sandbox-registered
            tokens always reach the sandbox host.
        payload_extra: optional dict merged into the top-level payload
            alongside `aps`. Reserved keys are anything Apple defines under
            `aps`; everything else is custom-data passthrough the iOS client
            can read in `didReceiveRemoteNotification`.
        client: injectable httpx.AsyncClient for tests (so an `httpx.MockTransport`
            can canned-respond without real network). When omitted, the
            function owns its client.

    Returns:
        `{"ok": True}` on 200.
        `{"ok": False, "status": <int>, "reason": <str>}` on a 4xx/5xx —
            `reason` is Apple's documented error code (e.g.
            "BadDeviceToken", "Unregistered", "ExpiredProviderToken"). The
            scheduler hookup should map "BadDeviceToken" / "Unregistered" to
            `revoke_device_token` so dead tokens fall out of the active set.
        `{"ok": False, "error": "not_configured"}` when env vars missing —
            no network attempted.
    """
    if not is_configured():
        logger.warning("apns: env vars not set, send_push is a no-op")
        return {"ok": False, "error": "not_configured"}

    env_label = environment or os.getenv("APNS_ENVIRONMENT", "production")
    host = _host_for(env_label)
    bundle_id = os.environ["APNS_BUNDLE_ID"]

    aps_payload: dict = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
        }
    }
    if payload_extra:
        # Merge OVER the top level, but never trample `aps` (Apple-reserved).
        for k, v in payload_extra.items():
            if k != "aps":
                aps_payload[k] = v

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(http2=True, timeout=10.0)

    # Apple rejects a stale provider token with 403 before our local TTL lapses
    # (clock skew / early staleness). Without dropping the cached JWT, every
    # subsequent push reuses the dead token until the ~50-min TTL rolls over —
    # all pushes silently fail in the meantime. On an auth-class 403, re-sign
    # once and retry. `_AUTH_REJECT_REASONS` is the set worth a refresh.
    def _headers() -> dict:
        return {
            "authorization": f"bearer {_get_jwt()}",
            "apns-topic": bundle_id,
            "apns-push-type": "alert",
        }

    try:
        retried = False
        while True:
            resp = await client.post(
                f"{host}/3/device/{device_token}",
                json=aps_payload,
                headers=_headers(),
            )
            if resp.status_code == 200:
                return {"ok": True}
            reason = "unknown"
            try:
                payload = resp.json()
                if isinstance(payload, dict):
                    reason = payload.get("reason", "unknown")
            except Exception:
                pass
            if (resp.status_code == 403 and reason in _AUTH_REJECT_REASONS
                    and not retried):
                logger.warning(
                    "apns auth-reject (%s); re-signing JWT and retrying once",
                    reason,
                )
                reset_jwt_cache()
                retried = True
                continue
            logger.warning(
                "apns rejected: status=%d reason=%s token=%s…",
                resp.status_code, reason, device_token[:8],
            )
            return {"ok": False, "status": resp.status_code, "reason": reason}
    finally:
        if own_client:
            await client.aclose()
