"""
Profile + macro-target REST endpoints for the iOS native app.

These are DELIBERATELY simpler than the chat-side `update_profile` /
`set_macro_targets` tools — the LLM tools accept free-form fields, alias
variations, and stash attributes; the REST endpoints accept ONLY the
canonical, iOS-editable fields. Cleaner contract, no aliasing logic
required, and both call paths land in the same `users` / `user_preferences`
rows so a chat-edit and a UI-edit are indistinguishable.

PATCH semantics throughout — every field is optional in the body and only
the keys present in the request are written. Missing keys leave the
existing column alone (so iOS can update one field without re-sending the
rest of the profile).

Endpoints:
  PATCH  /api/v1/profile   — User columns (name, age, sex, height, weights,
                              goal, training experience, diet, injuries).
  PATCH  /api/v1/targets   — UserPreferences calorie / macro targets.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import resolve_user

router = APIRouter(prefix="/api/v1", tags=["profile"])


# ── Profile (users table) ───────────────────────────────────────────────────


class ProfileEditBody(BaseModel):
    """Patch body for the canonical iOS-editable subset of the `users`
    table. Every field is `Optional` with no default — Pydantic surfaces
    "field present in body" vs "field omitted" via `model_dump(exclude_unset=True)`,
    so we can distinguish "iOS sent name=None on purpose" (clear the field)
    from "iOS didn't send name at all" (leave it alone)."""
    name: Optional[str] = None
    age: Optional[int] = Field(None, ge=10, le=120)
    sex: Optional[str] = None             # "male" | "female" | "other"
    height_cm: Optional[float] = Field(None, gt=50, lt=275)
    current_weight_kg: Optional[float] = Field(None, gt=20, lt=400)
    goal_weight_kg: Optional[float] = Field(None, gt=20, lt=400)
    primary_goal: Optional[str] = None    # "cut" | "bulk" | "maintain" | "performance" | "health"
    training_experience: Optional[str] = None  # "beginner" | "intermediate" | "advanced"
    non_training_activity: Optional[str] = None
    dietary_preferences: Optional[str] = None
    injuries: Optional[str] = None
    timezone: Optional[str] = None
    city: Optional[str] = None
    channel_preference: Optional[str] = None   # "telegram" | "imessage" — for linked users


@router.patch("/profile")
async def patch_profile(
    payload: ProfileEditBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Update one or more profile fields on the authenticated user's row.

    Only keys PRESENT in the body are touched. Returns the list of fields
    actually updated so the client can confirm the round-trip without
    re-reading the full profile.
    """
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return {"ok": True, "updated_fields": []}

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        applied: list[str] = []
        for field, value in updates.items():
            setattr(user, field, value)
            applied.append(field)
        await db.commit()
        return {"ok": True, "updated_fields": applied}


# ── Targets (user_preferences table) ────────────────────────────────────────


class TargetsEditBody(BaseModel):
    """Patch body for daily calorie / macro targets. Stored on
    `user_preferences` (not the user row) because they're coaching
    parameters, not identity facts. Bounds reflect realistic adult ranges
    — anything outside is almost certainly a unit / typo bug."""
    calorie_target: Optional[int] = Field(None, ge=800, le=8000)
    protein_target: Optional[int] = Field(None, ge=0, le=600)
    carb_target: Optional[int] = Field(None, ge=0, le=1500)
    fat_target: Optional[int] = Field(None, ge=0, le=400)


@router.patch("/targets")
async def patch_targets(
    payload: TargetsEditBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Update one or more daily macro targets. Only keys PRESENT in the
    body are touched. 404s if the user has no UserPreferences row
    (shouldn't happen in practice — get_or_create_user materializes one
    on first contact — but the defensive check surfaces the bug rather
    than silently creating a half-populated row here)."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return {"ok": True, "updated_fields": []}

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if user.preferences is None:
            raise HTTPException(
                status_code=404, detail="user has no preferences row",
            )
        applied: list[str] = []
        for field, value in updates.items():
            setattr(user.preferences, field, value)
            applied.append(field)
        await db.commit()
        return {"ok": True, "updated_fields": applied}
