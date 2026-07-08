"""
Persistence + lifecycle for the memory-graph open-loop nodes (user_threads).

The spine of "Arnie holds the arc of your life and follows through." Kept out of
the already-large db/queries.py. Everything here is small and self-committing,
matching the convention elsewhere.

The two behaviors that decide whether this stays useful or rots into noise:
  • DEDUP/MERGE ON WRITE — the same commitment mentioned twice is ONE thread
    updated, never two (the exact "planned the Hamptons trip twice" bug). See
    upsert_thread.
  • BOUNDED, RANKED READ — the per-turn context only ever pulls the top-N open
    threads by salience x proximity, so context stays cheap and the model isn't
    buried in stale loops. See get_open_threads.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import UserThread

logger = logging.getLogger(__name__)

# A thread with no activity for this long is presumed stale and won't surface
# (a safety net on top of explicit resolution / expiry).
_STALE_DAYS = 60


# Glue words stripped before comparing — they dilute similarity and carry no
# identity ("Hamptons trip with the family" ≈ "Hamptons trip, want good spots").
_STOP = {
    "a", "an", "the", "and", "or", "with", "for", "to", "of", "my", "our",
    "want", "wants", "wanna", "need", "needs", "some", "good", "great", "nice",
    "this", "that", "at", "in", "on", "is", "are", "be", "i", "im", "it", "its",
    "about", "just", "really", "like", "gonna", "so", "we", "im",
}


def _content(s: str) -> set:
    """Content-word set: lowercased tokens minus glue words. These carry the
    identity of a commitment (place names, the noun, distinctive words)."""
    return {
        w for w in re.findall(r"[a-z0-9]+", (s or "").lower())
        if w not in _STOP and len(w) > 1
    }


def _similar(a: str, b: str) -> bool:
    """True when two summaries are the same commitment restated. Uses the OVERLAP
    COEFFICIENT (intersection / smaller set) over content words, so a restatement
    that ADDS words ('...for the family') still matches — Jaccard punished that
    and let duplicates through. A substring shortcut catches verbatim repeats."""
    la, lb = (a or "").lower().strip(), (b or "").lower().strip()
    if not la or not lb:
        return False
    if la in lb or lb in la:
        return True
    ca, cb = _content(a), _content(b)
    if len(ca) < 2 or len(cb) < 2:
        return False
    return len(ca & cb) / min(len(ca), len(cb)) >= 0.5


async def upsert_thread(
    db: AsyncSession,
    user_id: int,
    kind: str,
    summary: str,
    *,
    salience: int = 3,
    source: str = "stated",
    details: Optional[str] = None,
    start_at: Optional[datetime] = None,
    due_at: Optional[datetime] = None,
    next_touch_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    origin_platform: Optional[str] = None,
    provenance_log_id: Optional[int] = None,
) -> tuple[UserThread, bool]:
    """Create a thread, OR update the matching open one if this is a restatement
    of something already tracked. Returns (thread, created). Commits.

    Match rule: same user, still open, same kind, and a similar summary. On a
    match we MERGE — take the newer summary/details, keep the highest salience,
    fill in any dates the new mention supplied — instead of spawning a duplicate.
    """
    summary = (summary or "").strip()
    if not summary:
        raise ValueError("thread summary is required")
    kind = (kind or "other").strip().lower()
    salience = max(1, min(5, int(salience or 3)))

    # Look for an open thread of the same kind to merge into.
    existing = (await db.execute(
        select(UserThread).where(
            UserThread.user_id == user_id,
            UserThread.status == "open",
            UserThread.kind == kind,
        ).order_by(UserThread.updated_at.desc())
    )).scalars().all()

    match = next((t for t in existing if _similar(t.summary, summary)), None)
    now = datetime.utcnow()

    if match is not None:
        match.summary = summary
        if details:
            match.details = details
        match.salience = max(int(match.salience or 3), salience)
        if start_at is not None:
            match.start_at = start_at
        if due_at is not None:
            match.due_at = due_at
        if next_touch_at is not None:
            match.next_touch_at = next_touch_at
        if expires_at is not None:
            match.expires_at = expires_at
        match.last_referenced_at = now
        await db.commit()
        await db.refresh(match)
        logger.info(f"event=thread_merged user_id={user_id} thread_id={match.id} kind={kind}")
        return match, False

    thread = UserThread(
        user_id=user_id, kind=kind, summary=summary, details=details,
        status="open", salience=salience, source=source,
        origin_platform=origin_platform, provenance_log_id=provenance_log_id,
        start_at=start_at, due_at=due_at, next_touch_at=next_touch_at,
        expires_at=expires_at, last_referenced_at=now,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    logger.info(
        f"event=thread_created user_id={user_id} thread_id={thread.id} "
        f"kind={kind} salience={salience} start={start_at}"
    )
    return thread, True


def _rank_key(t: UserThread, today: datetime):
    """Sort key for the per-turn read: imminent + salient + fresh float up.
    Lower tuple sorts first."""
    when = t.start_at or t.due_at or t.next_touch_at
    if when is not None:
        days_out = (when - today).total_seconds() / 86400.0
        # Imminent (0-7 days, incl. slightly overdue) is the most coaching-relevant.
        proximity = 0 if -2 <= days_out <= 7 else (1 if days_out < -2 else 2)
    else:
        proximity = 1  # undated loops sit between imminent and far-future
    created = t.created_at or today
    return (proximity, -(t.salience or 3), -created.timestamp())


async def get_open_threads(
    db: AsyncSession, user_id: int, *, limit: int = 6,
) -> list[UserThread]:
    """The bounded, ranked working set for context injection. Open threads only,
    stale ones dropped, sorted by proximity x salience x recency, capped."""
    rows = (await db.execute(
        select(UserThread).where(
            UserThread.user_id == user_id,
            UserThread.status == "open",
        )
    )).scalars().all()

    now = datetime.utcnow()
    stale_before = now - timedelta(days=_STALE_DAYS)
    fresh = [
        t for t in rows
        if (t.last_referenced_at or t.created_at or now) >= stale_before
        and not (t.expires_at and t.expires_at < now)
    ]
    fresh.sort(key=lambda t: _rank_key(t, now))
    return fresh[:limit]


async def get_thread(db: AsyncSession, thread_id: int, user_id: int) -> Optional[UserThread]:
    return (await db.execute(
        select(UserThread).where(
            UserThread.id == thread_id, UserThread.user_id == user_id,
        )
    )).scalar_one_or_none()


async def resolve_thread(
    db: AsyncSession, thread_id: int, user_id: int, *, status: str = "done",
) -> Optional[UserThread]:
    """Close a loop (done|dropped|expired). Commits. Returns the row or None if
    it doesn't belong to this user."""
    if status not in ("done", "dropped", "expired"):
        status = "done"
    t = await get_thread(db, thread_id, user_id)
    if t is None:
        return None
    t.status = status
    t.last_referenced_at = datetime.utcnow()
    await db.commit()
    await db.refresh(t)
    logger.info(f"event=thread_resolved user_id={user_id} thread_id={thread_id} status={status}")
    return t


async def edit_thread(
    db: AsyncSession, thread_id: int, user_id: int, **fields,
) -> Optional[UserThread]:
    """Update mutable fields (summary/details/salience/dates) on an existing
    thread. Commits. Returns the row or None."""
    t = await get_thread(db, thread_id, user_id)
    if t is None:
        return None
    for k in ("summary", "details", "kind", "start_at", "due_at",
              "next_touch_at", "expires_at"):
        if k in fields and fields[k] is not None:
            setattr(t, k, fields[k])
    if "salience" in fields and fields["salience"] is not None:
        t.salience = max(1, min(5, int(fields["salience"])))
    t.last_referenced_at = datetime.utcnow()
    await db.commit()
    await db.refresh(t)
    return t
