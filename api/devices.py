"""
Device-token registration endpoints for push notifications.

When the iOS app calls `UIApplication.shared.registerForRemoteNotifications()`
and the APNs delegate fires `application(_:didRegisterForRemoteNotificationsWithDeviceToken:)`,
the app POSTs the resulting token here. The token is upserted in
`db.device_tokens` so the proactive scheduler (slice 2c) can dispatch nudges
to it via the APNs HTTP/2 sender (slice 2b).

DELETE marks a token revoked — called on iOS sign-out, or when the app learns
that APNs rejected the token (the sender will mark it on HTTP 410, but the
client can also explicitly disown a token it knows is dead).

This endpoint is intentionally tiny. The sender that actually fires pushes
(`notifications/apns_client.py`, future slice) lives elsewhere — keeping
registration narrow lets either side evolve independently.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import (
    resolve_user,
    revoke_device_token,
    upsert_device_token,
)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


class APNSTokenBody(BaseModel):
    """Payload for POST /apns-token. iOS sends the hex token from
    `Data → String` (no spaces, no angle brackets), plus the environment that
    matches the build's aps-environment entitlement so the sender routes to
    the right APNs host."""
    token: str
    platform: Literal["apns"] = "apns"
    environment: Literal["production", "sandbox"] = "production"

    @field_validator("token")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("token must not be empty")
        return v


@router.post("/apns-token")
async def post_apns_token(
    payload: APNSTokenBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Register (or refresh) an APNs push token for the authenticated user.

    Idempotent — safe to call on every app launch. Handles token rotation
    (APNs may issue a new token at any time), environment switches (Debug ↔
    TestFlight ↔ App Store), and device handoff (same physical device, new
    user account) via `upsert_device_token`'s three-case logic.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await upsert_device_token(
            db,
            user_id=user.id,
            token=payload.token,
            platform=payload.platform,
            environment=payload.environment,
        )
        return {"status": "ok"}


@router.delete("/apns-token/{token}")
async def delete_apns_token(
    token: str,
    identity: str = Depends(current_identity),
) -> dict:
    """Mark an APNs token revoked for the authenticated user.

    Only the OWNING user can revoke their token. An attempt to revoke a
    token registered under a different user returns 404 (defensive — a leaked
    bearer must not silently revoke an arbitrary device). Calling DELETE on
    a token that doesn't exist also returns 404.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        revoked = await revoke_device_token(db, user.id, token)
        if not revoked:
            raise HTTPException(status_code=404, detail="token not found for this user")
        return {"status": "revoked"}
