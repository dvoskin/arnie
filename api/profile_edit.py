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
  PATCH  /api/v1/profile               — User columns (name, age, sex, height,
                                          weights, goal, training experience,
                                          diet, injuries).
  PATCH  /api/v1/targets               — UserPreferences calorie / macro targets.
  POST   /api/v1/onboarding/complete   — Mark the user fully onboarded; the
                                          proactive scheduler ignores rows where
                                          this is False.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import current_identity
from core.prompts.onboarding import build_ios_landing_intro
from db.database import AsyncSessionLocal
from db.queries import resolve_user, log_conversation

logger = logging.getLogger(__name__)

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
    brain_dump: Optional[str] = Field(None, max_length=8000)  # free-form onboarding dump
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

    skipped: list[str] = []
    if "timezone" in updates:
        # Intake gate: users.timezone feeds pytz on every chat turn — junk here
        # ("Naples, USA" typed into the onboarding field) used to 500 the user's
        # every message. Store only a normalized IANA zone; drop anything else
        # and let the proactive city-ask recover it conversationally.
        from core.timezones import normalize_timezone
        tz_norm = normalize_timezone(updates["timezone"])
        if tz_norm is None:
            updates.pop("timezone")
            skipped.append("timezone")
        else:
            updates["timezone"] = tz_norm

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        applied: list[str] = []
        for field, value in updates.items():
            setattr(user, field, value)
            applied.append(field)
        # Server-side completion: the iOS submit's completeOnboarding() call is
        # fire-and-forget (`try?`) — when it silently failed, the user landed in
        # chat half-onboarded with no greeting and invisible to the proactive
        # scheduler until some later save. The profile save that completes the
        # required set now flips the bit itself, so completion never depends on
        # a separate client call arriving.
        completion = await _complete_if_ready(db, user)
        await db.commit()
        resp = {
            "ok": True,
            "updated_fields": applied,
            "onboarding_completed": completion["onboarding_completed"],
        }
        if skipped:
            resp["skipped_fields"] = skipped
        return resp


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


@router.post("/auto-targets")
async def auto_compute_targets(
    identity: str = Depends(current_identity),
) -> dict:
    """Recompute calorie + macro targets from the user's current stats
    (weight, height, age, sex, primary_goal) and persist them on
    user_preferences. Mirrors the legacy `/api/profile/{token}/auto-targets`
    web route but bearer-authed.

    Returns the newly computed targets so the iOS Targets sheet can
    update its display without a re-fetch. 422 if essentials are missing
    (e.g. weight or height not set yet)."""
    from core.targets import compute_macro_targets
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if user.preferences is None:
            raise HTTPException(status_code=404, detail="user has no preferences row")
        computed = compute_macro_targets(user)
        if computed is None:
            raise HTTPException(
                status_code=422,
                detail="missing stats — need current weight, height, age, and sex",
            )
        user.preferences.calorie_target = computed["calorie_target"]
        user.preferences.protein_target = computed["protein_target"]
        user.preferences.carb_target = computed["carb_target"]
        user.preferences.fat_target = computed["fat_target"]
        await db.commit()
        return {
            "ok": True,
            "calorie_target": computed["calorie_target"],
            "protein_target": computed["protein_target"],
            "carb_target": computed["carb_target"],
            "fat_target": computed["fat_target"],
        }


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


# ── Onboarding completion ───────────────────────────────────────────────────

# Mirrors the iOS `ProfileCompletionBanner` criteria. The banner stays up
# until the same five fields are filled in the user's row, so the client
# and server agree on what "complete" means.
REQUIRED_ONBOARDING_FIELDS = (
    "age", "sex", "height_cm", "current_weight_kg", "primary_goal",
)


async def _complete_if_ready(db, user) -> dict:
    """Flip `onboarding_completed` + seed the intro turn and first weigh-in once
    the required fields are present. Shared by POST /onboarding/complete (the
    explicit iOS signal) and PATCH /profile (server-side auto-flip), so
    completion can never be lost to a dropped client call.

    Idempotent: already-onboarded users return ok=True untouched; missing
    fields return ok=False without committing (the caller owns that commit)."""
    if user.onboarding_completed:
        return {"ok": True, "onboarding_completed": True, "missing_fields": []}
    missing = [f for f in REQUIRED_ONBOARDING_FIELDS if getattr(user, f) is None]
    if missing:
        return {
            "ok": False,
            "onboarding_completed": False,
            "missing_fields": missing,
        }
    # Build Arnie's opening turn from the in-memory user columns BEFORE the
    # commit (commit expires the instance; reading it after would async
    # lazy-load and trip MissingGreenlet). `resolve_user` eager-loads
    # preferences via selectinload, so reading the daily targets here
    # (pre-commit) is safe. The open now reflects EVERYTHING the user shared:
    # goal, weight journey, daily targets, diet, injuries, training level, and
    # their free-form brain dump.
    prefs = user.preferences
    cur_kg = user.current_weight_kg   # captured pre-commit for the weigh-in seed
    intro_bubbles = build_ios_landing_intro(
        name=user.name,
        primary_goal=user.primary_goal,
        current_weight_kg=user.current_weight_kg,
        goal_weight_kg=user.goal_weight_kg,
        calorie_target=prefs.calorie_target if prefs else None,
        protein_target=prefs.protein_target if prefs else None,
        dietary_preferences=user.dietary_preferences,
        injuries=user.injuries,
        training_experience=user.training_experience,
        brain_dump=user.brain_dump,
    )
    # Seed guard: if the user already started talking (the completion call
    # arrived LATE — after a silent client failure they typed first), a
    # greeting would land mid-conversation with a now-timestamp and read
    # broken ("got everything from your signup" under a food log). Flip the
    # bit but skip the seed.
    from db.queries import has_real_conversation
    seed_intro = not await has_real_conversation(db, user.id)

    user.onboarding_completed = True
    await db.commit()
    if seed_intro:
        # Seed it so a native-onboarded user lands in a warm, profile-aware chat
        # (matching the web SETUP path) instead of an empty thread. First flip only
        # (the early returns above guard against double-seeding). Non-fatal.
        try:
            await log_conversation(
                db, user.id, "[start]", "|||".join(intro_bubbles),
                source_type="text", platform="ios",
            )
        except Exception:
            logger.exception("native onboarding intro seed failed (non-fatal)")
    else:
        logger.info(
            f"onboarding intro seed skipped for user {user.id} — thread already live"
        )

    # Seed the entered weight as a real weigh-in so it shows in the log + weight
    # trend from day one — the no-Apple-Health fallback. Only when the user has
    # NO weigh-in yet, so a real HealthKit sync that already landed takes
    # precedence (cascade: real Health → onboarding seed). Non-fatal.
    try:
        if cur_kg:
            from sqlalchemy import func as _func
            from db.models import BodyMetric as _BodyMetric
            from db.queries import add_body_metric
            existing_ct = (await db.execute(
                select(_func.count(_BodyMetric.id)).where(_BodyMetric.user_id == user.id)
            )).scalar() or 0
            if existing_ct == 0:
                await add_body_metric(db, user.id, cur_kg, source="manual")
    except Exception:
        logger.exception("onboarding weigh-in seed failed (non-fatal)")

    return {"ok": True, "onboarding_completed": True, "missing_fields": []}


@router.post("/onboarding/complete")
async def complete_onboarding(
    identity: str = Depends(current_identity),
) -> dict:
    """Flip `users.onboarding_completed` to True for the authed iOS user.

    The chat-led Telegram path flips this inline once the bot finishes its
    onboarding walk; the SETUP-XXX pairing path flips it inside
    `apply_landing_profile_to_user`. The native iOS app has neither —
    profile data lands via PATCH /profile and PATCH /targets, neither of
    which can tell when the user has "finished" because PATCH semantics
    let them edit one field at a time. This endpoint is the explicit
    signal: iOS calls it after a profile save, the bit flips when the
    required fields are present, and the proactive scheduler starts
    treating the user as a real account (otherwise
    `get_all_active_users` filters them out and no nudge ever fires).

    Required fields mirror the iOS banner's criteria. If any are missing
    we return ok=False + missing_fields rather than an error code so
    iOS can fire-and-forget after every save — only the save that
    completes the set will flip the bit.

    Idempotent: an already-onboarded user just returns ok=True.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        result = await _complete_if_ready(db, user)
        if not result["ok"]:
            # Nothing flipped — leave the session clean for the caller.
            await db.rollback()
        return result


# ── Linked accounts ─────────────────────────────────────────────────────────


@router.get("/linked-accounts")
async def linked_accounts(identity: str = Depends(current_identity)) -> dict:
    """Which platform surfaces (iOS / Telegram / iMessage) resolve to this same
    account. Drives the Settings "Linked accounts" panel.

    Without this the iOS app only knew about a link it performed IN-SESSION
    (`SettingsView.linkedTo` is local @State), so an account linked elsewhere —
    a prior session, the Telegram bot, or an ops backfill — still showed the
    "Link Telegram account" prompt. This reads the live `linked_to_user_id`
    group so the panel reflects reality on every open.

    Platform is derived from each identity's `telegram_id` prefix: `im:` →
    iMessage, `ios:` → iOS app, otherwise a numeric Telegram id.
    """
    from sqlalchemy import select, or_
    from db.models import User
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)              # canonical (follows the link)
        canonical_id = user.linked_to_user_id or user.id
        members = (await db.execute(select(User).where(
            or_(User.id == canonical_id, User.linked_to_user_id == canonical_id)
        ))).scalars().all()

        def platform_of(tid) -> str:
            t = str(tid or "")
            if t.startswith("im:"):  return "imessage"
            if t.startswith("ios:"): return "ios"
            return "telegram"

        platforms = sorted({platform_of(m.telegram_id) for m in members})
        canonical_user = next((m for m in members if m.id == canonical_id), user)
        return {
            "platforms":        platforms,                   # e.g. ["imessage","ios","telegram"]
            "telegram_linked":  "telegram" in platforms,
            "imessage_linked":  "imessage" in platforms,
            "canonical_name":   canonical_user.name,
        }
