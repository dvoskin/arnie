"""
Social circle REST endpoints for native clients (iOS today, web later).

Thin HTTP wrappers over the same friend-graph helpers the Telegram /invite,
/addfriend, and /circle commands use (`get_or_create_friend_code`,
`add_friend_by_code`, `remove_friend`) plus the `build_circle` aggregator — so a
friendship made in the app and one made in Telegram are the same edge, and both
clients render the identical board.

Auth + canonical resolution match every other /api/v1 router: a signed session
token → `current_identity` → `resolve_user` (which follows linked identities to
the one canonical brain the friend graph is keyed on).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from core.social import build_circle
from db.database import AsyncSessionLocal
from db.queries import (
    add_friend_by_code,
    get_or_create_friend_code,
    remove_friend,
    resolve_user,
)

router = APIRouter(prefix="/api/v1/social", tags=["social"])


class AddFriendBody(BaseModel):
    code: str = Field(min_length=4, max_length=12, description="A friend's circle code")


@router.get("/code")
async def my_friend_code(identity: str = Depends(current_identity)) -> dict:
    """Return (minting on first call) the caller's stable, shareable friend
    code. Fetching it is the opt-in: before this, the user owns no code and
    can't be added by anyone."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        code = await get_or_create_friend_code(db, user)
        return {
            "code": code,
            "share_text": (
                f"Add me on Arnie 💪 — open your Circle and enter my code: {code}"
            ),
        }


@router.get("/circle")
async def my_circle(identity: str = Depends(current_identity)) -> dict:
    """The ranked leaderboard for the caller's circle (self + friends). With no
    friends, returns just the caller at rank 1 so the client can show the empty
    state + invite CTA."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        return await build_circle(db, user)


@router.post("/add")
async def add_friend(
    payload: AddFriendBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Add the owner of `code` to the caller's circle (bidirectional). Idempotent
    — re-adding an existing friend returns status 'already'. 400 on a self-code,
    404 on an unknown code (the client maps these to friendly copy)."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        friend, status = await add_friend_by_code(db, user, payload.code)
        if status == "not_found":
            raise HTTPException(status_code=404, detail="No one owns that code.")
        if status == "self":
            raise HTTPException(status_code=400, detail="That's your own code.")
        return {
            "ok": True,
            "status": status,  # "ok" | "already"
            "friend": {"user_id": friend.id, "name": (friend.name or "Athlete").split()[0]},
        }


@router.delete("/friend/{friend_id}")
async def delete_friend(
    friend_id: int,
    identity: str = Depends(current_identity),
) -> dict:
    """Remove a friend from the circle (drops both edges). Returns ok even if
    they weren't a friend, so the client's remove button is always safe."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        removed = await remove_friend(db, user, friend_id)
        return {"ok": True, "removed": removed}
