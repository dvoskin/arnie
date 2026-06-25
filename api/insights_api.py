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

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await _build_stats_for_user(db, user)
        briefing = await get_briefing(user.id, stats, force=force)
    return {"v": 1, **briefing}


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
