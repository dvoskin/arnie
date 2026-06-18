"""
Location REST endpoint for the iOS native app.

iOS asks for CoreLocation permission, gets a one-shot reading, then POSTs
the coordinates here. We persist them on the user row via the same
`save_user_location` helper the Telegram location handler uses — so a
location shared from iOS and one shared from Telegram are indistinguishable
downstream (powers `find_nearby_places` + time-zone backfill).

Out of scope:
  - Live / continuous location streaming (one-shot only)
  - Reverse-geocoding to a city name (defer to existing helpers / let
    the user set `city` explicitly via the profile PATCH)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import resolve_user, save_user_location

router = APIRouter(prefix="/api/v1/location", tags=["location"])


class LocationBody(BaseModel):
    """One-shot lat/lng update. `city` is optional — when present we use
    it for time-zone backfill (matching the Telegram flow). Strict bounds
    so a stray 0/0 or units-mismatch doesn't land in the DB."""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    city: Optional[str] = Field(default=None, max_length=120)


class LocationAck(BaseModel):
    ok: bool
    lat: float
    lng: float
    city: Optional[str] = None


@router.post("", response_model=LocationAck)
async def post_location(
    payload: LocationBody,
    identity: str = Depends(current_identity),
):
    """Persist the user's current location. Coordinates are validated by
    pydantic's bounds above — invalid payloads 422 before we touch the DB.

    When the caller didn't supply a city (iOS CoreLocation only sends
    lat/lng), we reverse-geocode it via core.geocode so Arnie's context
    line "[LOCATION] ON FILE (City)" actually carries a city name —
    that's what lets him answer "where am I?" plainly without needing a
    separate tool call. Geocode failure is non-fatal (returns None);
    coords still save."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)

        # Reverse-geocode coords → city (only when client didn't pass one
        # AND user hasn't manually set one). Uses GOOGLE_PLACES_API_KEY +
        # day-long cache; never raises.
        city = payload.city
        if not city and not user.city:
            from core.geocode import reverse as _reverse_geocode
            city = await _reverse_geocode(payload.lat, payload.lng)

        await save_user_location(
            db,
            user_id=user.id,
            lat=payload.lat,
            lng=payload.lng,
            city=city,
        )
        # Re-read to confirm what landed (save_user_location won't clobber a
        # user-set city with a missing one, so the returned city may differ
        # from the request).
        await db.refresh(user)
        return LocationAck(ok=True, lat=user.lat, lng=user.lng, city=user.city)


@router.delete("", response_model=LocationAck)
async def clear_location(identity: str = Depends(current_identity)):
    """User-driven wipe — clears the stored location. Doesn't touch `city`
    (that's also editable from the profile and may be set independently of
    coordinates)."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        user.lat = None
        user.lng = None
        user.location_updated_at = None
        await db.commit()
        return LocationAck(ok=True, lat=0.0, lng=0.0, city=user.city)
