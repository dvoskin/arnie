"""
Conversation ↔ PendingQuestion bridge.

Called once per inbound turn (from core.conversation.run_turn) to keep the open-
question store in sync with reality:

  resolve — close any question the user has now effectively answered. Data-driven
            where possible (e.g. 'profile_stats' closes the moment age/sex/height
            are all present), so we never re-ask something already satisfied.
  record  — open a follow-up loop for a need we want chased down. Today that's:
              • profile_stats — age/sex/height for target calculation
              • conversation_hook — Arnie asked something and user went quiet

This runs regardless of PROACTIVE_MESSAGING_ENABLED — recording and resolving are
plain state updates, not outbound messages. The *re-asking* (which IS proactive)
lives in the scheduler and stays gated off.
"""
from __future__ import annotations

import logging
import re

from core.targets import missing_profile_stats
from db.queries import (
    get_open_pending_question, record_pending_question, resolve_pending_questions,
)

logger = logging.getLogger(__name__)

# Canonical wording stored for the profile-stats loop.
_PROFILE_QUESTION = (
    "what's your age, sex, and height? lets me lock in your real calorie + protein targets."
)

# Minimum characters for a hook question to be worth tracking (filters out
# trivial "ok?" or "right?" fragments that aren't real open loops).
_MIN_HOOK_LEN = 15

# Phrases that signal Arnie ended on a real question/hook worth following up on.
_HOOK_ENDINGS = re.compile(
    r"(\?|what'?s next|what do you think|how'?d (it|that) (go|feel)|"
    r"you (there|good|ok)|still with me|let me know|"
    r"what'?re you (eating|having|thinking)|"
    r"how are you (feeling|doing)|what did you (eat|have|train))\s*$",
    re.IGNORECASE,
)


def _extract_hook(response_text: str) -> str | None:
    """
    Return the last bubble of Arnie's response if it looks like an open question
    worth following up on. Returns None if no hook detected.

    Logic: split on |||, take the last non-empty bubble, check if it ends with
    a question mark or a hook phrase. Filter out very short fragments.
    """
    if not response_text:
        return None
    bubbles = [b.strip() for b in response_text.split("|||") if b.strip()]
    if not bubbles:
        return None
    last = bubbles[-1]
    if len(last) < _MIN_HOOK_LEN:
        return None
    if _HOOK_ENDINGS.search(last):
        return last
    return None


async def sync_pending_questions(db, user, arnie_response: str = "") -> None:
    """
    Reconcile open questions for `user` against current state. Best-effort: never
    raises into the turn (a follow-up bookkeeping error must not break a reply).

    arnie_response: the full response text Arnie just sent (used to detect hooks).
    """
    if not getattr(user, "onboarding_completed", False):
        return  # don't open or resolve loops while still onboarding

    try:
        # ── Profile stats loop ────────────────────────────────────────────────
        if missing_profile_stats(user):
            existing = await get_open_pending_question(db, user.id, "profile_stats")
            if existing is None:
                await record_pending_question(
                    db, user.id, kind="profile_stats",
                    question=_PROFILE_QUESTION, tier="goal_critical",
                )
        else:
            await resolve_pending_questions(db, user.id, kinds=["profile_stats"])

        # ── Conversation hook loop ────────────────────────────────────────────
        # Any inbound message from the user closes the open hook — they responded.
        await resolve_pending_questions(db, user.id, kinds=["conversation_hook"])

        # If Arnie's new response ends on a question, open a new hook loop.
        if arnie_response:
            hook = _extract_hook(arnie_response)
            if hook:
                await record_pending_question(
                    db, user.id, kind="conversation_hook",
                    question=hook, tier="conversation_hook",
                )

    except Exception as e:
        logger.error(f"sync_pending_questions failed for user {getattr(user, 'id', '?')}: {e}")
