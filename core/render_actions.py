"""Dispatch post-commit actions returned by canonical writers.

The writer returns what must happen AFTER the transaction as data
(`MealCommitResult.render_actions`) — running it inside would let a concurrent
reader repopulate caches from pre-write state, and the work would outlive a
rollback. The quick_log promotion inlined a one-action handler; the second
endpoint would have copied it, and the third would have diverged from both.
This is the one dispatcher instead.

NOT THE OUTBOX. These are BEST-EFFORT and IN-PROCESS: losing one costs a stale
read that self-heals on the next request. Work that must NOT be lost — memory
updates, analytics, coaching analysis — belongs in `MealCommitResult.
outbox_events`, which the coordinator writes to `background_jobs` inside the
mutation's transaction and the scheduler sweeps. Putting durable work here
would make it survive only as long as this process does; putting cache
invalidation in the outbox would make a stale cache a database row.

RULES. Actions run AFTER the caller's commit, never inside it. Unknown actions
are logged and skipped — a new writer emitting a new action must not break an
old endpoint that predates it (forward compatibility is the point of actions
being data). Failures are contained per action: post-commit work must never
turn a committed mutation into a user-facing error.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _invalidate_briefing(action: dict) -> None:
    from db.queries import _invalidate_briefing_for_log

    _invalidate_briefing_for_log(int(action["user_id"]), by_user=True)


_HANDLERS = {
    "invalidate_briefing": _invalidate_briefing,
}


def dispatch(render_actions) -> int:
    """Run each action; return how many ran. Call AFTER db.commit()."""
    ran = 0
    for action in render_actions or ():
        name = (action or {}).get("action", "")
        handler = _HANDLERS.get(name)
        if handler is None:
            logger.warning("event=render_action outcome=unknown action=%r — "
                           "skipped; a newer writer may have emitted it", name)
            continue
        try:
            handler(action)
            ran += 1
        except Exception:
            logger.exception(
                "event=render_action outcome=error action=%r — the commit "
                "stands; only this post-commit step failed", name)
    return ran
