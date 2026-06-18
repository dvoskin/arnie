"""
Sign-in endpoint for the native app.

POST /api/v1/auth/session — exchange a verified provider credential for an Arnie
session token. This is the ONLY unauthenticated /api/v1 route; everything else
requires the session token it returns.

For provider="apple", an OPTIONAL Authorization header is honored: when the
caller presents a valid existing session token (e.g. the device-identity
session the iOS app already holds in Keychain), the verified Apple sub is
BOUND to that user's row instead of producing a fresh empty apple:<sub> user.
This preserves the user's prior food/exercise/health history across the
Apple sign-in moment. The presented bearer is verified (HMAC-signed by the
same secret) so the binding cannot be hijacked by supplying an arbitrary
identity string.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

from api.auth import (
    issue_session_token,
    verify_provider_credential,
    verify_session_token,
)
from db.database import AsyncSessionLocal
from db.queries import (
    find_user_by_apple_sub,
    get_or_create_user,
    set_apple_sub_for_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class SessionRequest(BaseModel):
    provider: str       # "device" (dev) | "apple"
    credential: str     # device id, or Apple identity token

    @field_validator("provider", "credential")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class SessionResponse(BaseModel):
    token: str
    identity: str


def _current_identity_from_header(authorization: Optional[str]) -> Optional[str]:
    """Extract a verified identity from an Authorization header, returning None
    if the header is absent or its token is unverifiable. Distinct from the
    `current_identity` dependency in api/auth.py: that one RAISES 401 on
    missing/invalid bearer (the canonical authenticated-route behavior). Here
    a missing/invalid bearer is just "no existing session to bind onto" — we
    fall back to creating a fresh apple:<sub> user instead of failing."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        return verify_session_token(token)
    except HTTPException:
        return None


@router.post("/session", response_model=SessionResponse)
async def create_session(
    req: SessionRequest,
    authorization: Optional[str] = Header(default=None),
) -> SessionResponse:
    """Verify the credential, then issue a signed session token for that identity.

    For Apple sign-in, the routing is:
      1. If apple_sub is already bound to a user → return THAT user's identity
         (handles returning sign-ins from any device).
      2. Else if a valid existing session token is presented → bind apple_sub
         to the presenting user (the common iOS path: device-signed user taps
         Sign in with Apple in Profile, their history is preserved).
      3. Else → fresh `apple:<sub>` user (no prior account to inherit).
    Whichever branch fires, the response shape is unchanged (token + identity),
    so older TestFlight builds that don't pass the new Authorization header
    keep working — they just take branch (3) instead of (2).
    """
    verified_identity = verify_provider_credential(req.provider, req.credential)

    if req.provider != "apple":
        return SessionResponse(
            token=issue_session_token(verified_identity),
            identity=verified_identity,
        )

    # Apple branch: verified_identity is "apple:<sub>"; split off the sub.
    _, _, apple_sub = verified_identity.partition(":")
    if not apple_sub:
        # Defensive — verify_apple_identity_token already guarantees the prefix,
        # but never trust an upstream invariant when crossing a boundary.
        raise HTTPException(
            status_code=500, detail="Apple identity verification returned malformed sub"
        )

    async with AsyncSessionLocal() as db:
        # (1) apple_sub already bound? Return that user's identity.
        existing = await find_user_by_apple_sub(db, apple_sub)
        if existing:
            return SessionResponse(
                token=issue_session_token(existing.telegram_id),
                identity=existing.telegram_id,
            )

        # (2) Caller presented a valid existing session token? Bind to that user.
        binding_identity = _current_identity_from_header(authorization)
        if binding_identity:
            user = await get_or_create_user(db, binding_identity)
            await set_apple_sub_for_user(db, user.id, apple_sub)
            return SessionResponse(
                token=issue_session_token(user.telegram_id),
                identity=user.telegram_id,
            )

        # (3) Fresh Apple-first sign-in. Create the apple:<sub> user and record
        # apple_sub on the row so a future cross-device sign-in (same Apple ID
        # on a different physical device) lands back on this row via branch (1).
        new_user = await get_or_create_user(db, verified_identity)
        await set_apple_sub_for_user(db, new_user.id, apple_sub)
        return SessionResponse(
            token=issue_session_token(verified_identity),
            identity=verified_identity,
        )
