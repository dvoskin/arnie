"""
Sign-in endpoint for the native app.

POST /api/v1/auth/session — exchange a verified provider credential for an Arnie
session token. This is the ONLY unauthenticated /api/v1 route; everything else
requires the session token it returns.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from api.auth import verify_provider_credential, issue_session_token

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


@router.post("/session", response_model=SessionResponse)
async def create_session(req: SessionRequest) -> SessionResponse:
    """Verify the credential, then issue a signed session token for that identity."""
    identity = verify_provider_credential(req.provider, req.credential)
    return SessionResponse(token=issue_session_token(identity), identity=identity)
