"""
Conversation ↔ PendingQuestion bridge.

Called once per inbound turn (from core.conversation.run_turn) to keep the open-
question store in sync with reality:

  resolve — close any question the user has now effectively answered. Data-driven
            where possible (e.g. 'profile_stats' closes the moment age/sex/height
            are all present), so we never re-ask something already satisfied.
  record  — open a follow-up loop for a need we want chased down. Today that's
            profile stats for target calculation; the design generalizes by kind.

This runs regardless of PROACTIVE_MESSAGING_ENABLED — recording and resolving are
plain state updates, not outbound messages. The *re-asking* (which IS proactive)
lives in the scheduler and stays gated off. So the loop is fully exercised in the
app now; only the nudge itself waits on the flag.
"""
from __future__ import annotations

import logging

from core.targets import missing_profile_stats
from db.queries import (
    get_open_pending_question, record_pending_question, resolve_pending_questions,
)

logger = logging.getLogger(__name__)

# Canonical wording stored for the profile-stats loop; the follow-up generator
# re-voices it, so this is the seed, not the literal text the user sees.
_PROFILE_QUESTION = (
    "what's your age, sex, and height? lets me lock in your real calorie + protein targets."
)


async def sync_pending_questions(db, user) -> None:
    """
    Reconcile open questions for `user` against current state. Best-effort: never
    raises into the turn (a follow-up bookkeeping error must not break a reply).
    """
    if not getattr(user, "onboarding_completed", False):
        return  # don't open or resolve loops while still onboarding

    try:
        if missing_profile_stats(user):
            # Need stats → ensure a single open goal-critical loop is tracked.
            existing = await get_open_pending_question(db, user.id, "profile_stats")
            if existing is None:
                await record_pending_question(
                    db, user.id, kind="profile_stats",
                    question=_PROFILE_QUESTION, tier="goal_critical",
                )
        else:
            # Stats complete → close the loop so we stop following up.
            await resolve_pending_questions(db, user.id, kinds=["profile_stats"])
    except Exception as e:
        logger.error(f"sync_pending_questions failed for user {getattr(user, 'id', '?')}: {e}")
