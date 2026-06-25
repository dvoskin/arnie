"""
Water-log REST endpoints for the iOS native app.

These wrap the same query helpers the chat-side `log_water_entry` tool
uses (`add_water_entry` / `update_water_entry` / `delete_water_entry` +
`recompute_water_total`), so a row logged via tap-the-glass UI is
indistinguishable from one logged via chat. The cached
`DailyLog.total_water_ml` aggregate stays in sync on every mutation.

Out of scope:
- Server-side oz/cup → ml conversion. iOS converts to ml before POSTing.
- Reading the day's water — that's already in /api/v1/day (via the
  `total_water_ml` field surfaced through `_build_stats_for_user`).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import (
    add_water_entry,
    delete_water_entry,
    get_or_create_today_log,
    recompute_water_total,
    resolve_user,
    update_water_entry,
)

router = APIRouter(prefix="/api/v1/water", tags=["water"])


class WaterLogBody(BaseModel):
    """Quick-log payload from the iOS Today tile. `amount_ml` is the SI
    canonical — iOS converts ounces / cups client-side. `context` is
    optional free-form ("after workout", "with lunch") — surfaced to the
    coach for timing-aware nudges."""
    amount_ml: float = Field(gt=0, le=5000, description="Quantity in milliliters")
    context: Optional[str] = None


class WaterUpdateBody(BaseModel):
    """PATCH payload — same shape as log but no context (edits only change
    the amount; context stays whatever was originally logged)."""
    amount_ml: float = Field(gt=0, le=5000)


@router.post("")
async def log_water(
    payload: WaterLogBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Add a single water entry for the authenticated user. Materializes
    today's `DailyLog` if it doesn't exist yet (first log of the day) and
    keeps `total_water_ml` in sync. Returns the new entry id, day-log id,
    and the post-write cached total so the client can update the tile
    without a re-fetch."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        entry = await add_water_entry(
            db,
            user_id=user.id,
            daily_log_id=log.id,
            amount_ml=payload.amount_ml,
            context=payload.context,
            source_type="ios",
        )
        total = await recompute_water_total(db, log.id)
        return {
            "ok": True,
            "entry_id": entry.id,
            "daily_log_id": log.id,
            "total_water_ml": total,
        }


@router.patch("/{entry_id}")
async def update_water(
    entry_id: int,
    payload: WaterUpdateBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Update a single water entry's amount. Scoped by user — a token can
    only touch its own rows. Returns 404 if the entry doesn't exist or
    belongs to another user (uniform shape so token leakage doesn't
    expose entry existence)."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="water entry not found")
        updated = await update_water_entry(
            db, entry_id=entry_id, user_id=user.id, amount_ml=payload.amount_ml,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="water entry not found")
        total = None
        if updated.daily_log_id:
            total = await recompute_water_total(db, updated.daily_log_id)
        return {
            "ok": True,
            "entry_id": updated.id,
            "daily_log_id": updated.daily_log_id,
            "total_water_ml": total,
        }


@router.delete("/{entry_id}")
async def delete_water(
    entry_id: int,
    identity: str = Depends(current_identity),
) -> dict:
    """Delete a water entry. Same ownership scoping as PATCH."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="water entry not found")
        removed = await delete_water_entry(db, entry_id=entry_id, user_id=user.id)
        if not removed:
            raise HTTPException(status_code=404, detail="water entry not found")
        return {"ok": True}
