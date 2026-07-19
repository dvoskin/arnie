"""
Insights + memory REST endpoints for the iOS native app.

Wraps the same generators the web dashboard uses (`get_insights` /
`get_week_insights` in api.insights) and the per-user memory file in
`memory.memory_manager`, behind bearer auth via `current_identity` so
iOS doesn't need the legacy webhook-token URL.

Endpoints:
  GET /api/v1/insights?period=day|week — AI-generated coaching insights
  GET /api/v1/memory                   — the user's plain-text memory file

Memory note: the iOS app exposes this as a read-only "what Arnie remembers
about me" surface in the Brain / Profile area. Write/edit lands in a
later slice — surfacing the read alone is enough to make the brain tab
feel grounded without giving the user a way to corrupt their own state.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import resolve_user

router = APIRouter(prefix="/api/v1", tags=["insights"])


@router.get("/insights")
async def get_insights_for_ios(
    period: Literal["day", "week"] = "day",
    force: bool = False,
    identity: str = Depends(current_identity),
) -> dict:
    """Return the AI-generated coaching insights for the authenticated user.
    `period=day` (default) analyses today; `period=week` consolidates the
    last 7 days into trend bullets. `force=true` bypasses the cache so the
    insight regenerates against the latest logs (the app passes it right after
    a new entry). Wraps the same generators the legacy `/api/insights/{token}`
    route uses; result shape unchanged."""
    # Late import so api.insights_api can be loaded without pulling all of
    # api.app at module import time (circular: app includes this router).
    from api.app import _build_stats_for_user
    from api.insights import get_insights, get_week_insights

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await _build_stats_for_user(db, user)
        if period == "week":
            insights = await get_week_insights(user.id, stats, force=force)
        else:
            insights = await get_insights(user.id, stats, force=force, date_key="")
    return {"insights": insights, "period": period}


@router.get("/briefing")
async def get_briefing_for_ios(
    force: bool = False,
    identity: str = Depends(current_identity),
) -> dict:
    """The structured daily home briefing — hero status, one focus, prioritized
    narrative cards, and a conversation starter. The coach reviews everything and
    hands back what matters, already interpreted. `force=true` bypasses the cache."""
    from api.app import _build_stats_for_user
    from api.insights import get_briefing
    from db.queries import get_recent_conversations_linked

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await _build_stats_for_user(db, user)
        # The brief is otherwise blind to chat — feed it the last few turns so it
        # respects what the client JUST told Arnie (a stated plan, a rest day, a
        # competing commitment) instead of contradicting the live conversation.
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as _dt
            stats["local_hour"] = _dt.now(
                ZoneInfo(user.timezone or "UTC")).hour
        except Exception:
            pass
        convos = await get_recent_conversations_linked(db, user, limit=8)
        stats["recent_conversation"] = [
            {
                "when": (c.timestamp.isoformat(timespec="minutes") if c.timestamp else ""),
                "platform": c.platform or "",
                "user": (c.raw_message or "")[:240],
                "arnie": (c.response or "")[:240],
            }
            for c in reversed(convos)  # oldest → newest
        ]
        briefing = await get_briefing(user.id, stats, force=force)
    return {"v": 1, **briefing}


@router.get("/exercise_prs")
async def get_exercise_prs_for_ios(
    identity: str = Depends(current_identity),
) -> dict:
    """Per-movement strength PRs for the Coach page PR tracker.

    Derived (not stored) from the user's logged sets: the strongest set per lift
    all-time, ranked by estimated 1RM (Epley), each placed against bodyweight-
    scaled strength standards (novice / intermediate / advanced) where one exists.
    Aggregates across linked identities so a user's Telegram + iOS history counts
    as one training log. Cardio and unloaded movements are excluded."""
    from sqlalchemy import select as _sel

    from core.strength_prs import compute_strength_prs
    from db.models import User as _U
    from db.queries import get_recent_logs

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        prefs = user.preferences

        # One training log across all linked identities (canonical + children).
        user_ids = [user.id]
        linked = (await db.execute(
            _sel(_U).where(_U.linked_to_user_id == user.id)
        )).scalars().all()
        user_ids.extend(u.id for u in linked)

        logs = []
        for uid in user_ids:
            logs.extend(await get_recent_logs(db, uid, days=3650))  # ~all history

        # bodyweight + sex live on the USER row, not `preferences` — reading them off
        # `prefs` silently returned None, so the bodyweight-scaled tier never computed
        # (no novice/intermediate/advanced surfaced on the card).
        bodyweight_kg = user.current_weight_kg
        sex = user.sex
        level = getattr(prefs, "training_experience", None) if prefs else None

        prs = compute_strength_prs(logs, bodyweight_kg=bodyweight_kg, sex=sex)

    return {
        "v": 1,
        "window": "all",
        "bodyweight_lbs": round(bodyweight_kg * 2.20462, 1) if bodyweight_kg else None,
        "sex": sex,
        "level": level,
        "prs": prs,
    }


@router.get("/memory")
async def get_memory_for_ios(
    identity: str = Depends(current_identity),
) -> dict:
    """Return the plain-text memory file the LLM uses as long-term user
    context. Empty string if the file doesn't exist yet (new user, pre-
    onboarding init)."""
    from memory.memory_manager import read_memory

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
    content = await read_memory(user.telegram_id)
    return {"content": content, "telegram_id": user.telegram_id}
