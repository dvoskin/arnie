"""
Groups v1 (2026-07-06) — lightweight community spaces for the iOS app.

Launch set (seeded idempotently):
  • Beta Insiders — open group chat for the beta crew.
  • Feedback — a private line to the team. Members see ONLY their own
    messages; admins (GROUP_ADMIN_USER_IDS, default Danny=26) see everything.
    Deliberately group-shaped rather than a DM so it can open up later.

Kept deliberately small: list / join / leave / read / post. No reactions,
threads, or websockets — the iOS client polls on appear and after send.
All identity goes through resolve_user, so linked platforms share membership.
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.models import (
    Group, GroupMember, GroupMessage, GroupMessageReaction, User,
)
from db.queries import resolve_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])

_DEFAULT_GROUPS = (
    {
        "name": "Beta Insiders",
        "emoji": "🚀",
        "kind": "open",
        "description": "The founding crew. What's working, what you're testing, wins worth sharing.",
    },
    {
        "name": "Feedback",
        "emoji": "📮",
        "kind": "feedback",
        "description": "A direct line to the team — bugs, ideas, anything. Your messages come straight to us.",
    },
)


def _admin_ids() -> set:
    raw = os.getenv("GROUP_ADMIN_USER_IDS", "26")
    out = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


async def ensure_default_groups(db) -> None:
    """Idempotent launch-group seed — lives here (not in the migration) so
    SQLite test DBs built from models get the same rows the moment the API
    is exercised."""
    existing = set((await db.execute(select(Group.name))).scalars().all())
    dirty = False
    for g in _DEFAULT_GROUPS:
        if g["name"] not in existing:
            db.add(Group(**g))
            dirty = True
    if dirty:
        await db.commit()


# ── Wire shapes ──────────────────────────────────────────────────────────────

class GroupOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    emoji: Optional[str] = None
    kind: str
    member_count: int
    joined: bool


class ReactionOut(BaseModel):
    emoji: str
    count: int
    mine: bool


class ReplyRef(BaseModel):
    id: int
    sender_name: str
    excerpt: str


class MessageOut(BaseModel):
    id: int
    sender_name: str
    text: str
    created_at: str
    mine: bool
    is_admin: bool
    reactions: List[ReactionOut] = []
    reply_to: Optional[ReplyRef] = None


class PostBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    reply_to_id: Optional[int] = None


class ReactBody(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=8)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_groups(identity: str = Depends(current_identity)) -> List[GroupOut]:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await ensure_default_groups(db)
        groups = (await db.execute(select(Group).order_by(Group.id))).scalars().all()
        counts = dict((await db.execute(
            select(GroupMember.group_id, func.count(GroupMember.id))
            .group_by(GroupMember.group_id)
        )).all())
        mine = set((await db.execute(
            select(GroupMember.group_id).where(GroupMember.user_id == user.id)
        )).scalars().all())
        return [
            GroupOut(
                id=g.id, name=g.name, description=g.description, emoji=g.emoji,
                kind=g.kind, member_count=counts.get(g.id, 0), joined=g.id in mine,
            )
            for g in groups
        ]


async def _get_group(db, group_id: int) -> Group:
    g = (await db.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


async def _ensure_member(db, group_id: int, user_id: int) -> None:
    exists = (await db.execute(
        select(GroupMember.id).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )).first()
    if not exists:
        db.add(GroupMember(group_id=group_id, user_id=user_id))
        await db.commit()


@router.post("/{group_id}/join")
async def join_group(group_id: int, identity: str = Depends(current_identity)) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await _get_group(db, group_id)
        await _ensure_member(db, group_id, user.id)
        return {"ok": True}


@router.post("/{group_id}/leave")
async def leave_group(group_id: int, identity: str = Depends(current_identity)) -> dict:
    from sqlalchemy import delete as _delete
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await db.execute(_delete(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user.id))
        await db.commit()
        return {"ok": True}


@router.get("/{group_id}/messages")
async def get_messages(
    group_id: int,
    identity: str = Depends(current_identity),
    limit: int = 100,
) -> List[MessageOut]:
    limit = max(1, min(limit, 200))
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        group = await _get_group(db, group_id)
        admins = _admin_ids()

        q = (
            select(GroupMessage, User.name, User.id)
            .join(User, User.id == GroupMessage.user_id)
            .where(GroupMessage.group_id == group_id)
        )
        # THE feedback rule: a member's view of the Feedback group is their own
        # thread only. Admins read the whole room. This is what makes Feedback
        # a safe direct line rather than a public wall.
        if group.kind == "feedback" and user.id not in admins:
            q = q.where(GroupMessage.user_id == user.id)
        q = q.order_by(GroupMessage.id.desc()).limit(limit)

        rows = (await db.execute(q)).all()
        rows.reverse()   # wire order: oldest → newest
        return await _hydrate(db, rows, viewer_id=user.id, admins=admins)


async def _hydrate(db, rows, viewer_id: int, admins: set) -> List[MessageOut]:
    """Attach reactions (emoji → count + mine) and reply quotes to a message
    page in TWO set queries — never per-message."""
    ids = [m.id for m, _, _ in rows]
    reactions: dict = {}
    if ids:
        for mid, emoji, uid in (await db.execute(
            select(GroupMessageReaction.message_id, GroupMessageReaction.emoji,
                   GroupMessageReaction.user_id)
            .where(GroupMessageReaction.message_id.in_(ids))
        )).all():
            slot = reactions.setdefault(mid, {})
            agg = slot.setdefault(emoji, {"count": 0, "mine": False})
            agg["count"] += 1
            if uid == viewer_id:
                agg["mine"] = True

    reply_ids = [m.reply_to_id for m, _, _ in rows if m.reply_to_id]
    replies: dict = {}
    if reply_ids:
        for rid, rtext, rname in (await db.execute(
            select(GroupMessage.id, GroupMessage.text, User.name)
            .join(User, User.id == GroupMessage.user_id)
            .where(GroupMessage.id.in_(reply_ids))
        )).all():
            excerpt = rtext if len(rtext) <= 90 else rtext[:87].rstrip() + "…"
            replies[rid] = ReplyRef(id=rid, sender_name=rname or "Member", excerpt=excerpt)

    return [
        MessageOut(
            id=m.id,
            sender_name=(name or "Member"),
            text=m.text,
            created_at=(m.created_at.isoformat() + "Z") if m.created_at else "",
            mine=(uid == viewer_id),
            is_admin=(uid in admins),
            reactions=[
                ReactionOut(emoji=e, count=a["count"], mine=a["mine"])
                for e, a in sorted(reactions.get(m.id, {}).items(),
                                   key=lambda kv: -kv[1]["count"])
            ],
            reply_to=replies.get(m.reply_to_id) if m.reply_to_id else None,
        )
        for m, name, uid in rows
    ]


@router.post("/{group_id}/messages")
async def post_message(
    group_id: int,
    body: PostBody,
    identity: str = Depends(current_identity),
) -> MessageOut:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await _get_group(db, group_id)
        # Posting implies membership — auto-join keeps the flow one-tap smooth.
        await _ensure_member(db, group_id, user.id)
        reply_to = None
        if body.reply_to_id:
            reply_to = (await db.execute(
                select(GroupMessage).where(
                    GroupMessage.id == body.reply_to_id,
                    GroupMessage.group_id == group_id)
            )).scalar_one_or_none()
            if not reply_to:
                raise HTTPException(status_code=404, detail="Replied-to message not found")
        msg = GroupMessage(group_id=group_id, user_id=user.id,
                           text=body.text.strip(),
                           reply_to_id=reply_to.id if reply_to else None)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        rref = None
        if reply_to:
            rname = (await db.execute(
                select(User.name).where(User.id == reply_to.user_id))).scalar()
            ex = reply_to.text if len(reply_to.text) <= 90 else reply_to.text[:87].rstrip() + "…"
            rref = ReplyRef(id=reply_to.id, sender_name=rname or "Member", excerpt=ex)
        return MessageOut(
            id=msg.id,
            sender_name=user.name or "Member",
            text=msg.text,
            created_at=(msg.created_at.isoformat() + "Z") if msg.created_at else "",
            mine=True,
            is_admin=(user.id in _admin_ids()),
            reactions=[],
            reply_to=rref,
        )


@router.post("/{group_id}/messages/{message_id}/react")
async def toggle_reaction(
    group_id: int,
    message_id: int,
    body: ReactBody,
    identity: str = Depends(current_identity),
) -> dict:
    """Tap-to-toggle: add the (user, emoji) reaction if absent, remove if present."""
    from sqlalchemy import delete as _delete
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        msg = (await db.execute(
            select(GroupMessage).where(
                GroupMessage.id == message_id, GroupMessage.group_id == group_id)
        )).scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        existing = (await db.execute(
            select(GroupMessageReaction.id).where(
                GroupMessageReaction.message_id == message_id,
                GroupMessageReaction.user_id == user.id,
                GroupMessageReaction.emoji == body.emoji)
        )).scalar_one_or_none()
        if existing:
            await db.execute(_delete(GroupMessageReaction)
                             .where(GroupMessageReaction.id == existing))
            await db.commit()
            return {"ok": True, "reacted": False}
        db.add(GroupMessageReaction(message_id=message_id, user_id=user.id,
                                    emoji=body.emoji))
        await db.commit()
        return {"ok": True, "reacted": True}
