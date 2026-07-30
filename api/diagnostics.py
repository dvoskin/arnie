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
            "food_pipeline": _food_pipeline(user.id),
            "env_gates": {
                "LOCATION_ENABLED": location_enabled(),
                "SEARCH_ENABLED": os.getenv("SEARCH_ENABLED", "false").lower() in ("true", "1", "yes"),
                "WHOOP_CLIENT_ID_set": bool(os.getenv("WHOOP_CLIENT_ID")),
                "GOOGLE_PLACES_API_KEY_set": bool(os.getenv("GOOGLE_PLACES_API_KEY")),
                "DEV_AUTH_ENABLED": os.getenv("DEV_AUTH_ENABLED", "false").lower() in ("true", "1", "yes"),
                # Deep-research + model wiring — the three things that decide
                # whether smart turns actually work post-deploy. If a deep turn
                # gives a generic no-specifics plan, check these first.
                "DEFAULT_MODEL": _default_model(),
                "TAVILY_API_KEY_set": bool(os.getenv("TAVILY_API_KEY")),
                "DEEP_RESEARCH_MODEL": os.getenv("DEEP_RESEARCH_MODEL", "claude-sonnet-5"),
                "DEEP_RESEARCH_DAILY_CAP": os.getenv("DEEP_RESEARCH_DAILY_CAP", "8"),
            },
        }


def _flag(name: str, effective) -> dict:
    """One rollout flag, reported so DEFAULTED is distinguishable from SET.

    `effective` is resolved by the caller through the SAME accessor the
    runtime uses — the only value that answers "what is production actually
    doing". The raw env reading rides alongside because the two answer
    different questions: a var that never loaded and a var deliberately set
    to its own default produce identical behaviour and need opposite fixes
    (fix the deploy vs. change the value). Reporting only the effective mode
    cannot tell those apart, which is the entire reason this block exists.
    """
    raw = os.getenv(name)
    return {"effective": effective, "env_set": raw is not None, "env_raw": raw}


def _food_pipeline(user_id: Optional[int] = None) -> dict:
    """Which food pipeline a turn actually takes, resolved at runtime.

    Every flag here has a CODE default that differs from what render.yaml
    declares, so repo state cannot answer "what is deployed": an env var that
    silently failed to load runs a different pipeline than the config file
    describes, with no error anywhere. Specifically, unset means
    coordinator=legacy_only, resolver=shadow, composer=off — while
    render.yaml declares new_observe / live / true.

    Resolved through the real accessors rather than re-read from the
    environment here, so this block cannot drift from the behaviour it
    reports. Each entry is independently guarded: a diagnostic that 500s on
    one bad import is useless exactly when it is needed most.
    """
    out: dict = {}

    try:
        from core.turns.coordinator import coordinator_mode
        out["TURN_COORDINATOR_MODE"] = _flag(
            "TURN_COORDINATOR_MODE", coordinator_mode())
    except Exception as e:                           # pragma: no cover
        out["TURN_COORDINATOR_MODE"] = {"error": str(e)}

    # A FLAG NOBODY CAN SEE IS A DECISION NOBODY MAKES. The master audit's own
    # finding was flags parked in shadow with no owner and no review date
    # (`FOOD_FAST_PATH_SHADOW`, "shadow since 07-29, no decision date"). This
    # one ships OFF with a written enable condition, and reporting it here is
    # what turns "remember to switch it on" into something visible from
    # outside the container, for free, on every deploy check.
    try:
        from core.food_pipeline import identity_ask_enabled
        out["FOOD_IDENTITY_ASK"] = _flag(
            "FOOD_IDENTITY_ASK", identity_ask_enabled())
    except Exception as e:                           # pragma: no cover
        out["FOOD_IDENTITY_ASK"] = {"error": str(e)}

    try:
        from skills.nutrition.promotion import (owns_committed_values,
                                                resolver_mode)
        out["NUTRITION_RESOLVER_MODE"] = _flag(
            "NUTRITION_RESOLVER_MODE", resolver_mode())
        # The mode alone does not decide the resolver's authority: live mode
        # still filters through the canary cohort (allowlist / percentage /
        # halt flag). This is the value that actually decides whether the
        # resolver owns THIS user's committed numbers — and, because the
        # promotion telemetry sits behind the same call, whether their turns
        # emit `event=nutrition_promotion` lines at all.
        out["resolver_owns_committed_values"] = owns_committed_values(user_id)
    except Exception as e:                           # pragma: no cover
        out["NUTRITION_RESOLVER_MODE"] = {"error": str(e)}

    try:
        from core.food_response import _composer_model, composer_enabled
        out["FOOD_COMPOSER"] = _flag("FOOD_COMPOSER", composer_enabled())
        out["FOOD_COMPOSER_MODEL"] = _composer_model()
    except Exception as e:                           # pragma: no cover
        out["FOOD_COMPOSER"] = {"error": str(e)}

    return out


def public_pipeline_summary() -> dict:
    """The same effective modes, shaped for an UNAUTHENTICATED endpoint.

    `/health` is the only way to check a deployed container without holding a
    user token, and "did the env var take" is exactly the question it already
    exists to answer for the log voice. The modes are not secret — they are
    the same strings render.yaml documents in the clear.

    What is deliberately dropped is `env_raw`. Echoing arbitrary environment
    content on a public endpoint is a habit worth not starting, even for
    values that only ever hold mode names today; a typo puts whatever was
    actually typed into the response. `env_set` keeps the distinction that
    matters — defaulted vs. deliberately set — without echoing the content.
    """
    out: dict = {}
    for key, entry in _food_pipeline().items():
        if not isinstance(entry, dict):
            out[key] = entry
        elif "error" in entry:
            out[key] = {"error": entry["error"]}
        else:
            out[key] = {"effective": entry.get("effective"),
                        "env_set": entry.get("env_set")}
    return out


def _default_model() -> str:
    """The model the chat path actually resolves — so a deploy can confirm the
    Sonnet 5 bump took (a Render DEFAULT_MODEL env var OVERRIDES the code
    fallback, so this is the source of truth, not the code default)."""
    try:
        from core.llm import DEFAULT_MODEL
        return DEFAULT_MODEL()
    except Exception:
        return os.getenv("DEFAULT_MODEL", "unknown")
