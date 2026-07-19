"""
Oura REST endpoints for the iOS native app.

Mirrors api/whoop_api.py: the OAuth flow itself goes through the
`/oura/callback` handler in `api/app.py` (which expects
`state = user.webhook_token`). This module just:
  - mints the auth URL with the caller's existing webhook_token as state,
    so iOS can hand it to SFSafariViewController;
  - exposes a connection-status read for the Settings row;
  - and a one-shot disconnect that clears the saved tokens.
"""
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import current_identity
from api.oura import build_auth_url
from db.database import AsyncSessionLocal
from db.models import WearableDevice
from db.queries import (
    clear_oura_tokens,
    get_or_create_webhook_token,
    resolve_user,
)

router = APIRouter(prefix="/api/v1/oura", tags=["oura"])


class ConnectURLResponse(BaseModel):
    auth_url: str


class StatusResponse(BaseModel):
    connected: bool
    last_sync_at: Optional[str] = None


class DisconnectAck(BaseModel):
    ok: bool


@router.get("/connect-url", response_model=ConnectURLResponse)
async def get_connect_url(identity: str = Depends(current_identity)):
    """Return the Oura OAuth authorize URL the client should open in a
    web view. State = caller's webhook_token so the /oura/callback handler
    resolves the user the same way the Whoop flow does."""
    if not os.getenv("OURA_CLIENT_ID") or not os.getenv("OURA_CLIENT_SECRET"):
        raise HTTPException(503, "Oura integration not configured on server")

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        token = await get_or_create_webhook_token(db, user.id)

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    redirect_uri = f"{base_url}/oura/callback"
    return ConnectURLResponse(auth_url=build_auth_url(redirect_uri, token))


@router.get("/status", response_model=StatusResponse)
async def get_status(identity: str = Depends(current_identity)):
    """Read connection + last-sync state for the Settings row."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        connected = bool(user.oura_access_token or user.oura_refresh_token)
        last_sync_iso: Optional[str] = None
        if connected:
            row = await db.execute(
                select(WearableDevice.last_sync_at)
                .where(WearableDevice.user_id == user.id,
                       WearableDevice.device_type == "oura")
                .order_by(WearableDevice.last_sync_at.desc())
                .limit(1)
            )
            ts: Optional[datetime] = row.scalar_one_or_none()
            if ts is not None:
                last_sync_iso = ts.isoformat()
    return StatusResponse(connected=connected, last_sync_at=last_sync_iso)


@router.post("/disconnect", response_model=DisconnectAck)
async def disconnect(identity: str = Depends(current_identity)):
    """Clear stored Oura tokens. Snapshots stay (historical record); only
    the auth credentials are wiped."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await clear_oura_tokens(db, user.id)
    return DisconnectAck(ok=True)
