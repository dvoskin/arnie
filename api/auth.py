"""
Auth for the native (/api/v1/*) API.

Two layers:

  1. SESSION TOKENS — every API request carries an Arnie-issued, HMAC-signed
     session token (NOT a raw identity string). The server verifies the signature,
     so identities can't be forged. `current_identity` checks this.

  2. PROVIDER VERIFICATION — at sign-in, a provider credential (a dev device id
     now, an Apple identity token later) is verified and exchanged for a session
     token via POST /api/v1/auth/session. New providers slot into
     `verify_provider_credential` with no change to any endpoint.

The session payload carries the same platform identity string used everywhere else
(`resolve_user`), so this layer sits cleanly on top of the existing user model —
no schema migration, and the production Telegram/iMessage bot is untouched.

PROD CHECKLIST: set SESSION_SECRET (strong random) and DEV_AUTH_ENABLED=false. With
device auth off, the only way to mint a session is a verified Apple identity token
— and session tokens can't be forged without SESSION_SECRET. Apple verification
uses Apple's public JWKS (no shared secret needed); audience defaults to the iOS
bundle id and can be overridden with APPLE_SIWA_CLIENT_ID.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 90 * 24 * 3600  # 90 days
_DEV_SECRET = "dev-insecure-session-secret"  # used only when SESSION_SECRET is unset


def _secret() -> bytes:
    s = os.getenv("SESSION_SECRET", "")
    if not s:
        logger.warning("SESSION_SECRET unset — using insecure dev secret. Set it in prod.")
        s = _DEV_SECRET
    return s.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    return _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


# ── Session tokens ───────────────────────────────────────────────────────────

def issue_session_token(identity: str, ttl: int = SESSION_TTL_SECONDS) -> str:
    """Mint a signed `<body>.<sig>` session token carrying the platform identity."""
    now = int(time.time())
    payload = {"sub": identity, "iat": now, "exp": now + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def verify_session_token(token: str) -> str:
    """Verify signature + expiry; return the identity (`sub`). Raises 401 otherwise."""
    try:
        body, sig = token.split(".")
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed session token")
    if not hmac.compare_digest(sig, _sign(body)):
        raise HTTPException(status_code=401, detail="Invalid session token")
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed session token")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Session missing subject")
    return sub


async def current_identity(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency → the verified caller identity from the session token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return verify_session_token(authorization[len("Bearer "):].strip())


# ── Provider verification (sign-in) ──────────────────────────────────────────

def _dev_auth_enabled() -> bool:
    return os.getenv("DEV_AUTH_ENABLED", "true").lower() in ("1", "true", "yes")


def verify_provider_credential(provider: str, credential: str) -> str:
    """Verify a sign-in credential and return the canonical platform identity."""
    if provider == "device":
        # DEV ONLY: the credential IS the device identity. Gated so prod can't use
        # it to mint arbitrary identities. Always namespaced `ios:` so it can never
        # collide with a Telegram/iMessage identity.
        if not _dev_auth_enabled():
            raise HTTPException(status_code=403, detail="Device auth is disabled")
        cred = (credential or "").strip()
        if not cred:
            raise HTTPException(status_code=400, detail="Empty device credential")
        return cred if cred.startswith("ios:") else f"ios:{cred}"

    if provider == "apple":
        return verify_apple_identity_token(credential)

    raise HTTPException(status_code=400, detail=f"Unknown auth provider: {provider}")


_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"
_DEFAULT_APPLE_CLIENT_ID = "com.tryarnie.app"
_apple_jwks_client: Optional[PyJWKClient] = None


def _apple_client_id() -> str:
    """The audience the iOS app's identity tokens are issued for. For native iOS,
    this IS the bundle id; for a web Sign in with Apple flow, it'd be the Services ID."""
    return os.getenv("APPLE_SIWA_CLIENT_ID", _DEFAULT_APPLE_CLIENT_ID)


def _get_apple_jwks_client() -> PyJWKClient:
    """Reusable JWKS client. PyJWKClient caches keys per `kid` internally, so we
    don't hit Apple on every verify — only when a token references an unseen key."""
    global _apple_jwks_client
    if _apple_jwks_client is None:
        _apple_jwks_client = PyJWKClient(_APPLE_JWKS_URL)
    return _apple_jwks_client


def verify_apple_identity_token(identity_token: str) -> str:
    """Verify an Apple identity token (RS256 JWT) and return `apple:<sub>`.

    Signature is verified against Apple's public JWKS; the standard claims
    (issuer, audience, expiry) are checked by PyJWT. Returns the namespaced
    platform identity (`apple:<apple-user-id>`) consumed by `resolve_user`.
    """
    if not identity_token or not identity_token.strip():
        raise HTTPException(status_code=400, detail="Empty Apple identity token")

    try:
        signing_key = _get_apple_jwks_client().get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_apple_client_id(),
            issuer=_APPLE_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Apple identity token expired")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Apple identity token has wrong audience")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Apple identity token has wrong issuer")
    except jwt.InvalidTokenError as e:
        logger.warning("Apple identity token invalid: %s", e)
        raise HTTPException(status_code=401, detail="Invalid Apple identity token")
    except Exception as e:
        # JWKS fetch failure (network blip, Apple outage). Surface 503 so the client
        # can retry; this is distinct from 401 (a token Apple would refuse forever).
        logger.error("Apple JWKS verification error: %s", e)
        raise HTTPException(status_code=503, detail="Apple identity verification temporarily unavailable")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Apple identity token missing subject")
    return f"apple:{sub}"
