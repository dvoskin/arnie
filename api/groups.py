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

    # Beta Insiders is THE community room — every canonical, onboarded user
    # belongs by default (Telegram-era users never saw an iOS Join button, so
    # active people were invisible on the board: Danny, 2026-07-19). Idempotent:
    # only inserts the missing memberships.
    from db.models import User as _U
    _insiders = (await db.execute(
        select(Group).where(Group.name == "Beta Insiders"))).scalar_one_or_none()
    if _insiders is not None:
        _members = set((await db.execute(
            select(GroupMember.user_id)
            .where(GroupMember.group_id == _insiders.id))).scalars().all())
        _canonical = (await db.execute(
            select(_U.id).where(_U.linked_to_user_id.is_(None),
                                _U.onboarding_completed.is_(True)))).scalars().all()
        _missing = [uid for uid in _canonical if uid not in _members]
        for uid in _missing:
            db.add(GroupMember(group_id=_insiders.id, user_id=uid))
        if _missing:
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
    sender_avatar: Optional[str] = None
    sender_streak: int = 0
    text: str
    created_at: str
    mine: bool
    is_admin: bool
    reactions: List[ReactionOut] = []
    reply_to: Optional[ReplyRef] = None
    has_image: bool = False


class PostBody(BaseModel):
    text: str = Field("", max_length=2000)
    reply_to_id: Optional[int] = None
    image_b64: Optional[str] = Field(None, max_length=2_000_000)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and not self.image_b64


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


def _can_see_message(group, msg, user_id: int, admins: set) -> bool:
    """The feedback-visibility rule, in one place: in a feedback group a
    non-admin may only touch/see their OWN messages; everywhere else, anyone in
    the group sees everything. Applied to every path that reveals another
    message's content or existence — read, image, reply-quote, reaction — so a
    member can't iterate ids to read or probe the private feedback line."""
    if group.kind == "feedback" and user_id not in admins and msg.user_id != user_id:
        return False
    return True


async def _ensure_member(db, group_id: int, user_id: int) -> None:
    exists = (await db.execute(
        select(GroupMember.id).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )).first()
    if not exists:
        db.add(GroupMember(group_id=group_id, user_id=user_id))
        await db.commit()


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    name: str
    you: bool
    momentum: int
    log_days: int
    workout_days: int
    streak: int
    badges: int


async def compute_leaderboard(db, group_id: int, me_id: int,
                              window_days: int | None = 7) -> dict:
    """Effort-ranked board for a group — momentum is computed ON READ from the
    last 7 logging days (no score ledger to maintain or drift):

        momentum = 10·log_days + 15·workout_days + 5·streak + 2·badges

    Consistency outranks intensity by construction: a 7-day logger beats a
    two-workout hero. window_days: 7, 30, or None (all-time — cumulative
    board, same weights). Session-injected for testability; the route wraps
    it."""
    from datetime import date, timedelta
    from sqlalchemy import func as _f

    if True:  # keep the original indentation contract below
        group = await _get_group(db, group_id)
        member_rows = (await db.execute(
            select(GroupMember.user_id).where(GroupMember.group_id == group.id)
        )).scalars().all()
        if me_id not in member_rows:
            raise HTTPException(status_code=403, detail="not a member")

        from db.models import DailyLog, Achievement, User as _U

        # Fetch floor: the window itself (plus slack so the streak walk isn't
        # clipped); all-time fetches everything.
        _q = select(DailyLog.user_id, DailyLog.date,
                    DailyLog.total_calories, DailyLog.workout_completed) \
            .where(DailyLog.user_id.in_(member_rows))
        if window_days is not None:
            _q = _q.where(DailyLog.date
                          >= date.today() - timedelta(days=window_days + 60))
        logs = (await db.execute(_q)).all()
        week = (date.today() - timedelta(days=window_days - 1)
                if window_days is not None else date.min)
        badge_counts = dict((await db.execute(
            select(Achievement.user_id, _f.count(Achievement.id))
            .where(Achievement.user_id.in_(member_rows))
            .group_by(Achievement.user_id)
        )).all())
        names = dict((await db.execute(
            select(_U.id, _U.name).where(_U.id.in_(member_rows))
        )).all())

        by_user: dict = {}
        for uid, d, cals, wk in logs:
            by_user.setdefault(uid, {})[d] = ((cals or 0) > 0, bool(wk))

        entries = []
        for uid in member_rows:
            days = by_user.get(uid, {})
            log_days = sum(1 for d, (ate, _) in days.items()
                           if d >= week and ate)
            workout_days = sum(1 for d, (_, wk) in days.items()
                               if d >= week and wk)
            streak = 0
            probe = date.today()
            # today only counts toward the streak if already logged; an
            # unlogged today doesn't break yesterday's run.
            if not days.get(probe, (False, False))[0]:
                probe -= timedelta(days=1)
            while days.get(probe, (False, False))[0]:
                streak += 1
                probe -= timedelta(days=1)
            badges = int(badge_counts.get(uid, 0))
            momentum = 10 * log_days + 15 * workout_days + 5 * streak + 2 * badges
            entries.append({
                "user_id": uid,
                "name": (names.get(uid) or "Member").split(" ")[0],
                "you": uid == me_id,
                "momentum": momentum, "log_days": log_days,
                "workout_days": workout_days, "streak": streak,
                "badges": badges,
            })
        # Only people actually MOVING show (Danny: 'all non-zero users') —
        # zero-momentum rows (ghost/test accounts, dormant members) drop off;
        # the requester always sees their own row, even at zero.
        entries = [e for e in entries if e["momentum"] > 0 or e["you"]]
        entries.sort(key=lambda e: (-e["momentum"], e["name"]))
        out = [LeaderboardEntry(rank=i + 1, **e) for i, e in enumerate(entries)]
        return {"v": 1,
                "window": ("all" if window_days is None else f"{window_days}d"),
                "entries": [e.dict() for e in out]}


@router.get("/{group_id}/leaderboard")
async def group_leaderboard(
    group_id: int, window: str = "7d",
    identity: str = Depends(current_identity)
) -> dict:
    """Names only (first names the group already sees); requester flagged
    `you`. window: 7d | 30d | all. See compute_leaderboard."""
    days = {"7d": 7, "30d": 30, "all": None}.get(window, 7)
    async with AsyncSessionLocal() as db:
        me = await resolve_user(db, identity)
        return await compute_leaderboard(db, group_id, me.id, window_days=days)


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

        # Explicit columns — NEVER select the whole entity: image_b64 is a
        # Text column holding up to ~2MB of base64 per photo, and the page only
        # needs a has_image boolean (the image loads lazily via /image). Pulling
        # the entity dragged every blob through Postgres → app → discard on every
        # poll (multi-MB per fetch at photo volume). This keeps the page in KB.
        q = (
            select(GroupMessage.id.label("id"),
                   GroupMessage.text.label("text"),
                   GroupMessage.reply_to_id.label("reply_to_id"),
                   GroupMessage.created_at.label("created_at"),
                   GroupMessage.image_b64.isnot(None).label("has_image"),
                   User.name.label("name"),
                   User.id.label("uid"),
                   User.avatar_emoji.label("avatar"))
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


async def _sender_streaks(db, user_ids: set) -> dict:
    """Logging streak per sender — same definition as the profile chip and the
    top-bar bolt (consecutive days walking back from the user's today with
    calories > 0 or a completed workout). One set query for the whole page."""
    from datetime import date as _date, timedelta as _td
    from db.models import DailyLog
    from db.queries import _user_today
    if not user_ids:
        return {}
    cutoff = _date.today() - _td(days=60)
    rows = (await db.execute(
        select(DailyLog.user_id, DailyLog.date, DailyLog.total_calories,
               DailyLog.workout_completed, User.timezone)
        .join(User, User.id == DailyLog.user_id)
        .where(DailyLog.user_id.in_(list(user_ids)), DailyLog.date >= cutoff)
    )).all()
    logged: dict = {}
    tz_by_user: dict = {}
    for uid, d, cal, workout, tz in rows:
        tz_by_user[uid] = tz
        if (cal or 0) > 0 or workout:
            logged.setdefault(uid, set()).add(d)
    out = {}
    for uid, days in logged.items():
        cur = _user_today(tz_by_user.get(uid) or "UTC")
        streak = 0
        while cur in days:
            streak += 1
            cur = cur - _td(days=1)
        out[uid] = streak
    return out


async def _hydrate(db, rows, viewer_id: int, admins: set) -> List[MessageOut]:
    """Attach reactions (emoji → count + mine), reply quotes, and sender
    streaks to a message page in THREE set queries — never per-message."""
    ids = [r.id for r in rows]
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

    streaks = await _sender_streaks(db, {r.uid for r in rows})

    reply_ids = [r.reply_to_id for r in rows if r.reply_to_id]
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
            id=r.id,
            sender_name=(r.name or "Member"),
            sender_avatar=r.avatar,
            sender_streak=streaks.get(r.uid, 0),
            text=r.text,
            has_image=bool(r.has_image),
            created_at=(r.created_at.isoformat() + "Z") if r.created_at else "",
            mine=(r.uid == viewer_id),
            is_admin=(r.uid in admins),
            reactions=[
                ReactionOut(emoji=e, count=a["count"], mine=a["mine"])
                for e, a in sorted(reactions.get(r.id, {}).items(),
                                   key=lambda kv: -kv[1]["count"])
            ],
            reply_to=replies.get(r.reply_to_id) if r.reply_to_id else None,
        )
        for r in rows
    ]


@router.post("/{group_id}/messages")
async def post_message(
    group_id: int,
    body: PostBody,
    identity: str = Depends(current_identity),
) -> MessageOut:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        group = await _get_group(db, group_id)
        # Posting implies membership — auto-join keeps the flow one-tap smooth.
        await _ensure_member(db, group_id, user.id)
        if body.is_empty:
            raise HTTPException(status_code=422, detail="Message needs text or a photo")
        reply_to = None
        if body.reply_to_id:
            reply_to = (await db.execute(
                select(GroupMessage).where(
                    GroupMessage.id == body.reply_to_id,
                    GroupMessage.group_id == group_id)
            )).scalar_one_or_none()
            # A reply echoes the quoted text + sender back — so a member must
            # not be able to reply-to a message they can't see (else they'd
            # iterate reply_to_id to read others' private feedback). Same 404
            # as a missing message: don't confirm existence.
            if not reply_to or not _can_see_message(group, reply_to, user.id, _admin_ids()):
                raise HTTPException(status_code=404, detail="Replied-to message not found")
        msg = GroupMessage(group_id=group_id, user_id=user.id,
                           text=body.text.strip(),
                           reply_to_id=reply_to.id if reply_to else None,
                           image_b64=body.image_b64)
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
            sender_avatar=user.avatar_emoji,
            text=msg.text,
            has_image=bool(msg.image_b64),
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
        group = await _get_group(db, group_id)
        msg = (await db.execute(
            select(GroupMessage).where(
                GroupMessage.id == message_id, GroupMessage.group_id == group_id)
        )).scalar_one_or_none()
        # Reacting to a hidden feedback message would leak its existence (count/
        # mine deltas) — gate it by the same visibility rule.
        if not msg or not _can_see_message(group, msg, user.id, _admin_ids()):
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


@router.get("/{group_id}/messages/{message_id}/image")
async def get_message_image(
    group_id: int,
    message_id: int,
    identity: str = Depends(current_identity),
) -> dict:
    """The photo for one message, fetched lazily (never inlined in the page).
    Visibility mirrors the message rule: in a feedback group, a member can
    only fetch images on THEIR OWN messages; admins fetch any."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        group = await _get_group(db, group_id)
        msg = (await db.execute(
            select(GroupMessage).where(
                GroupMessage.id == message_id, GroupMessage.group_id == group_id)
        )).scalar_one_or_none()
        if not msg or not msg.image_b64 \
                or not _can_see_message(group, msg, user.id, _admin_ids()):
            raise HTTPException(status_code=404, detail="No image")
        return {"image_b64": msg.image_b64}


@router.delete("/{group_id}/messages/{message_id}")
async def unsend_message(
    group_id: int,
    message_id: int,
    identity: str = Depends(current_identity),
) -> dict:
    """Unsend — hard-delete the caller's own message (admins may remove any).
    Reactions go with it; replies that quoted it keep their text but lose the
    quote reference (reply_to_id nulled) instead of dangling."""
    from sqlalchemy import delete as _delete, update as _update
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        msg = (await db.execute(
            select(GroupMessage).where(
                GroupMessage.id == message_id, GroupMessage.group_id == group_id)
        )).scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        if msg.user_id != user.id and user.id not in _admin_ids():
            raise HTTPException(status_code=403, detail="Not your message")
        await db.execute(_update(GroupMessage)
                         .where(GroupMessage.reply_to_id == message_id)
                         .values(reply_to_id=None))
        await db.execute(_delete(GroupMessageReaction)
                         .where(GroupMessageReaction.message_id == message_id))
        await db.execute(_delete(GroupMessage).where(GroupMessage.id == message_id))
        await db.commit()
        return {"ok": True}
