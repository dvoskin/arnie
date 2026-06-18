"""
Settings + feedback + sign-out endpoints for the iOS native app.

Three thin REST surfaces grouped here because they all belong to the
Settings tab UX:

  POST /api/v1/preferences  — partial-patch UserPreferences (reminders
                              toggle, coaching style, accountability,
                              pacing, response length, wake/sleep,
                              proactive on/off, food logging mode).
  POST /api/v1/feedback     — user-submitted bug / feature / general
                              feedback. Wraps the same `add_feedback`
                              query the chat /feedback command uses.
  POST /api/v1/auth/signout — server-side acknowledgment of sign-out.
                              The session token itself is HMAC-signed
                              with no server-side revocation list yet
                              (deferred to a future slice — proper
                              token revocation needs a sessions table
                              + a check in current_identity), so for
                              now this just confirms the client should
                              clear its keychain. Documented so a future
                              breaking change to make this strictly
                              revocation-checked has a clear migration
                              path.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import add_feedback, resolve_user


# ── Preferences ─────────────────────────────────────────────────────────────


prefs_router = APIRouter(prefix="/api/v1", tags=["preferences"])


class PreferencesEditBody(BaseModel):
    """Partial-patch body for UserPreferences. Mirrors the model column
    names so iOS can present toggles and pickers directly. Every field is
    Optional with no default — `exclude_unset=True` distinguishes "leave
    it" from "set to null"."""
    coaching_style: Optional[Literal["strict", "balanced", "supportive"]] = None
    accountability_level: Optional[Literal["low", "medium", "high"]] = None
    pacing_enabled: Optional[bool] = None
    reminder_frequency: Optional[Literal["none", "light", "moderate", "heavy"]] = None
    preferred_response_length: Optional[Literal["short", "medium", "long"]] = None
    profanity_tolerance: Optional[bool] = None
    proactive_messaging_enabled: Optional[bool] = None
    wake_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    sleep_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    food_logging_mode: Optional[Literal["quick", "moderate", "strict"]] = None


@prefs_router.post("/preferences")
async def patch_preferences(
    payload: PreferencesEditBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Update one or more UserPreferences fields. Returns the updated key
    list so the iOS client can confirm the round-trip without a re-fetch.
    Quiet no-op on an empty body."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return {"ok": True, "updated_fields": []}
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if user.preferences is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="user has no preferences row")
        applied: list[str] = []
        for field, value in updates.items():
            setattr(user.preferences, field, value)
            applied.append(field)
        await db.commit()
        return {"ok": True, "updated_fields": applied}


# ── Feedback ────────────────────────────────────────────────────────────────


feedback_router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackBody(BaseModel):
    """Free-form text from the user, optionally categorized so triage
    can route it. The same `add_feedback` query the chat `/feedback`
    command uses lands the row, so iOS and TG feedback show up in the
    same /admin/flagged stream."""
    text: str = Field(min_length=1, max_length=10_000)
    kind: Literal["bug", "feature", "other"] = "other"


@feedback_router.post("/feedback")
async def post_feedback(
    payload: FeedbackBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Record a feedback entry tied to the authenticated user."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        entry = await add_feedback(db, user_id=user.id, kind=payload.kind, text=payload.text)
        return {"ok": True, "feedback_id": entry.id}


# ── Sign-out ────────────────────────────────────────────────────────────────


signout_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@signout_router.post("/signout")
async def signout(identity: str = Depends(current_identity)) -> dict:
    """Acknowledge a sign-out. The iOS client clears its keychain entries
    (session token + device identity) on receiving this response.

    SECURITY GAP (deferred, not addressed here): session tokens are
    HMAC-signed with the SESSION_SECRET env var and have no server-side
    revocation list. Until a sessions table + revoked_at check land in
    `current_identity`, a leaked token remains valid for its 90-day TTL
    even after the client signs out. This endpoint is a placeholder so
    the iOS UX can ship; a follow-up slice should add the actual
    revocation pipeline.
    """
    return {"ok": True, "identity": identity}
