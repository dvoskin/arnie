"""
Read-only diagnostics for the authenticated user. No write paths; no PII
beyond what the user already sees in their Profile sheet. Designed for
debugging "Arnie can't see my X" complaints — surfaces the exact rows +
env-gate state the chat path reads, so we don't have to guess whether a
field is set or whether an env var actually loaded.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import resolve_user, location_enabled, get_or_create_user

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get("/me")
async def get_me(identity: str = Depends(current_identity)) -> dict:
    """The exact user row the chat path operates on, plus the env gates
    that decide which tools the LLM sees. Use this to confirm Location
    coords/city/timezone, food_logging_mode, primary platform identity,
    and whether features are environmentally enabled — without piecing
    it together from /profile + /preferences."""
    async with AsyncSessionLocal() as db:
        raw = await get_or_create_user(db, identity)
        user = await resolve_user(db, identity)  # follows linked_to_user_id
        prefs = user.preferences
        return {
            "identity_sent": identity,
            "raw_user": {
                "id": raw.id,
                "telegram_id": raw.telegram_id,
                "linked_to_user_id": raw.linked_to_user_id,
            },
            "canonical_user": {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "name": user.name,
            },
            "location": {
                "lat": user.lat,
                "lng": user.lng,
                "city": user.city,
                "timezone": user.timezone,
                "location_updated_at": user.location_updated_at.isoformat()
                    if user.location_updated_at else None,
            },
            "preferences": {
                "food_logging_mode": getattr(prefs, "food_logging_mode", None) if prefs else None,
                "coaching_style": getattr(prefs, "coaching_style", None) if prefs else None,
                "accountability_level": getattr(prefs, "accountability_level", None) if prefs else None,
                "reminder_frequency": getattr(prefs, "reminder_frequency", None) if prefs else None,
                "preferred_response_length": getattr(prefs, "preferred_response_length", None) if prefs else None,
            },
            "env_gates": {
                "LOCATION_ENABLED": location_enabled(),
                "SEARCH_ENABLED": os.getenv("SEARCH_ENABLED", "false").lower() in ("true", "1", "yes"),
                "WHOOP_CLIENT_ID_set": bool(os.getenv("WHOOP_CLIENT_ID")),
                "GOOGLE_PLACES_API_KEY_set": bool(os.getenv("GOOGLE_PLACES_API_KEY")),
                "DEV_AUTH_ENABLED": os.getenv("DEV_AUTH_ENABLED", "false").lower() in ("true", "1", "yes"),
            },
        }
