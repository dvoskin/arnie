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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select

from api.auth import (
    current_identity,
    issue_session_token,
    verify_provider_credential,
    verify_session_token,
)
from core.prompts.onboarding import GOAL_PHRASE_MAP, build_ios_landing_intro
from db.database import AsyncSessionLocal
from db.models import DailyLog, User
from db.queries import (
    apply_landing_profile_to_user,
    consume_link_code,
    consume_pre_registration,
    enable_check_ins,
    find_user_by_apple_sub,
    get_or_create_user,
    linking_enabled,
    log_conversation,
    pre_registration_exists,
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


# ── Pairing-code exchange (iOS-side landing-form handoff) ────────────────────

class PairingCodeRequest(BaseModel):
    code: str           # SETUP-XXXXXX from join.html success page
    provider: str       # "device" (dev) | "apple"
    credential: str     # device id, or Apple identity token

    @field_validator("code", "provider", "credential")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class WelcomePayload(BaseModel):
    name: Optional[str] = None
    primary_goal: Optional[str] = None
    goal_phrase: Optional[str] = None
    calorie_target: Optional[int] = None
    protein_target: Optional[int] = None
    carb_target: Optional[int] = None
    fat_target: Optional[int] = None


class PairingCodeResponse(BaseModel):
    token: str
    identity: str
    welcome: WelcomePayload


def _welcome_from_user(user) -> WelcomePayload:
    """Snapshot a user's current profile into the iOS welcome payload. Shared by
    the new-user (post-apply) and returning-user (welcome-back) branches."""
    prefs = user.preferences
    return WelcomePayload(
        name=user.name,
        primary_goal=user.primary_goal,
        goal_phrase=GOAL_PHRASE_MAP.get(user.primary_goal or ""),
        calorie_target=(prefs.calorie_target if prefs else None),
        protein_target=(prefs.protein_target if prefs else None),
        carb_target=(prefs.carb_target if prefs else None),
        fat_target=(prefs.fat_target if prefs else None),
    )


async def _resolve_setup_user(db, provider: str, verified_identity: str):
    """Resolve the user a SETUP code should land on — apple_sub-aware, mirroring
    `create_session`. For Apple this recognizes a returning user whose history
    lives on a *different* identity (e.g. a device row that later bound Apple), so
    the code never mints a duplicate `apple:<sub>` account. Falls back to the
    identity string (and records `apple_sub` on a freshly created Apple row so
    future cross-device lookups resolve via branch 1)."""
    if provider == "apple":
        _, _, sub = verified_identity.partition(":")
        if sub:
            existing = await find_user_by_apple_sub(db, sub)
            if existing:
                return existing
        user = await get_or_create_user(db, verified_identity)
        if sub:
            await set_apple_sub_for_user(db, user.id, sub)
        return user
    return await get_or_create_user(db, verified_identity)


@router.post("/exchange-pairing-code", response_model=PairingCodeResponse)
async def exchange_pairing_code(req: PairingCodeRequest) -> PairingCodeResponse:
    """iOS-side mirror of bot/telegram_handler.py SETUP-XXX consumption.

    Resolves the user (apple_sub-aware — see `_resolve_setup_user`), consumes the
    pre_registration code, applies the form's profile to the user row, sets
    onboarding_completed=True, and issues a session token. The returned welcome
    payload feeds the iOS welcome card.

    RETURNING USER ("I already have an account with Apple"): if the resolved user
    is already onboarded, we DON'T error or burn the code — we just hand back a
    session for their existing account (200, "welcome back"). This rescues the
    common trap of a returning Apple user tapping "Get started" instead of "Sign
    in", and — because resolution is apple_sub-aware — it lands on their real row
    even when their history lives on a device identity that later bound Apple,
    instead of minting an empty duplicate.

    Error codes (distinct from the Telegram path's text replies — iOS clients need
    structured failure signals):
      404 — code never existed (typo / bad input)
      410 — code expired or already consumed (one-time use enforced by
            consume_pre_registration)
      401 — provider credential is invalid (propagated from verify_provider_credential)
    """
    verified_identity = verify_provider_credential(req.provider, req.credential)
    code = req.code.upper()

    async with AsyncSessionLocal() as db:
        user = await _resolve_setup_user(db, req.provider, verified_identity)

        if user.onboarding_completed:
            # Returning user — leave the account untouched, don't burn the code,
            # and sign them straight back into their existing row.
            return PairingCodeResponse(
                token=issue_session_token(user.telegram_id),
                identity=user.telegram_id,
                welcome=_welcome_from_user(user),
            )

        # New user: consume FIRST (replay protection) — mirrors
        # bot/telegram_handler.py:757 — then apply the form profile.
        profile = await consume_pre_registration(db, code)

        if profile is None:
            # Distinguish "code never existed" (typo → 404, re-prompt for the
            # code) from "expired/already-used" (410, re-issue from the landing
            # page) so the iOS client can show the right remediation. A
            # non-consuming existence check settles which case this is.
            if not await pre_registration_exists(db, code):
                raise HTTPException(
                    status_code=404,
                    detail="Pairing code not found — check the code and try again.",
                )
            raise HTTPException(
                status_code=410,
                detail="Pairing code is expired or already used.",
            )

        await apply_landing_profile_to_user(db, user, profile)
        await db.commit()
        await enable_check_ins(db, user.id)

        welcome = _welcome_from_user(user)

        # Seed Arnie's iOS opening into the conversation log so the app renders a
        # warm, profile-aware welcome on first history load (chat/history splits the
        # turn on |||) and drives the first food/workout log — instead of the generic
        # empty state. iOS-only: the Telegram SETUP path seeds INTRO_BUBBLES_LANDING
        # in bot/telegram_handler.py. raw_message="[start]" so chat/history omits the
        # phantom user bubble (see api/chat.py _display_user_text).
        intro_bubbles = build_ios_landing_intro(
            name=user.name,
            primary_goal=user.primary_goal,
            current_weight_kg=user.current_weight_kg,
            goal_weight_kg=user.goal_weight_kg,
            calorie_target=(user.preferences.calorie_target if user.preferences else None),
            protein_target=(user.preferences.protein_target if user.preferences else None),
        )
        await log_conversation(
            db, user.id, "[start]", "|||".join(intro_bubbles),
            source_type="text", platform="ios",
        )

        logger.info(
            f"Pairing code {code} consumed for identity={verified_identity} user_id={user.id}"
        )

        return PairingCodeResponse(
            token=issue_session_token(user.telegram_id),
            identity=user.telegram_id,
            welcome=welcome,
        )


# ── Cross-platform account link (iOS ↔ Telegram) ─────────────────────────────

class LinkAccountRequest(BaseModel):
    code: str  # LINK-XXXX minted by Telegram /link

    @field_validator("code")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class LinkAccountResponse(BaseModel):
    canonical_identity: str
    canonical_name: Optional[str] = None


@router.post("/link", response_model=LinkAccountResponse)
async def link_account(
    req: LinkAccountRequest,
    identity: str = Depends(current_identity),
) -> LinkAccountResponse:
    """Weld the calling iOS user onto the canonical Telegram row identified by
    `code`. After success, every API call from this device still uses the same
    session token — but `resolve_user` follows `linked_to_user_id` to the
    canonical row, so the iOS app immediately sees the user's Telegram food /
    exercise / preferences / memory.

    The iOS user keeps its `apple_sub` binding. `find_user_by_apple_sub`
    returns the iOS row on future Apple sign-ins, and `resolve_user` follows
    the link to the canonical row — so cross-device Apple sign-in still lands
    on the right brain.

    Error codes (distinct from the Telegram /link reply text — iOS needs
    structured signals):
      403 — LINKING_ENABLED is off
      404 — code never existed
      410 — code is expired
      409 — code is the caller's own (self-link)
      422 — iOS row already has logs (data-migration territory; defer to #2)
    """
    if not linking_enabled():
        raise HTTPException(
            status_code=403, detail="Account linking is disabled on this server."
        )

    code = req.code.upper()

    async with AsyncSessionLocal() as db:
        # Find the canonical owner so we can give precise errors. This is the
        # pre-check; consume_link_code will re-load it under the same session.
        owner = (
            await db.execute(select(User).where(User.link_code == code))
        ).scalar_one_or_none()
        if owner is None:
            raise HTTPException(
                status_code=404,
                detail="That code is invalid or has already been used.",
            )
        if owner.link_code_expires and datetime.utcnow() > owner.link_code_expires:
            raise HTTPException(
                status_code=410,
                detail="That code has expired. Run /link in Telegram again for a fresh one.",
            )

        consumer = await get_or_create_user(db, identity)
        if consumer.id == owner.id:
            raise HTTPException(
                status_code=409,
                detail="That code was generated by this account — nothing to link.",
            )

        # Defer data migration to roadmap #2 — if the iOS row already has
        # logs, refuse rather than orphan them. consume_link_code repoints
        # the row but leaves the consumer's daily_logs/food_entries pointing
        # at consumer.id, so they'd vanish from the canonical view.
        log_count = (
            await db.execute(
                select(func.count(DailyLog.id)).where(DailyLog.user_id == consumer.id)
            )
        ).scalar_one()
        if log_count and consumer.id != owner.id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This device already has logged data. Merging accounts "
                    "with existing data isn't supported yet."
                ),
            )

        canonical = await consume_link_code(db, code, consumer)
        if canonical is None:
            # Race: someone else consumed the code between the pre-check and
            # the call (or the owner row was edited concurrently).
            raise HTTPException(
                status_code=409,
                detail="That code was just used. Generate a fresh one in Telegram.",
            )

        logger.info(
            f"Link code {code} consumed: consumer identity={identity} "
            f"user_id={consumer.id} → canonical user_id={canonical.id}"
        )
        return LinkAccountResponse(
            canonical_identity=canonical.telegram_id,
            canonical_name=canonical.name,
        )
