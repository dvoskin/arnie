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
              • proactive_hook — user has gone silent on several check-ins; the
                scheduler consolidates the slot nudges into one re-ask (resolved
                here too, the moment any inbound turn breaks the silence)

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

# Directive stored when the scheduler consolidates a silence streak into a single
# proactive_hook. It lives here (not in the scheduler) because it is prompt copy —
# content-ownership rule: prose visible to users belongs in lifecycle.py / prompts/,
# never in orchestration files. Imported by proactive_scheduler for use in the
# gate_decision "consolidate" branch.
_SILENCE_HOOK_DIRECTIVE = (
    "you've gone quiet for a bit — reach back out warm "
    "with one easy, genuine question."
)

# Minimum characters for a hook question to be worth tracking (filters out
# trivial "ok?" or "right?" fragments that aren't real open loops).
_MIN_HOOK_LEN = 15

# Two distinct ending classes — semantically different re-ask templates.
# A *question* ending earns "Earlier you asked them this" framing.
# An *engagement* ending earns "You ended on X — re-engage naturally" framing.
# Keeping them separate prevents non-questions being voiced as if they were asked.
_HOOK_QUESTION_ENDINGS = re.compile(
    r"(\?|what'?s next|what do you think|how'?d (it|that) (go|feel)|"
    r"what'?re you (eating|having|thinking)|"
    r"how are you (feeling|doing)|what did you (eat|have|train))\s*$",
    re.IGNORECASE,
)
_HOOK_ENGAGEMENT_ENDINGS = re.compile(
    r"(you (there|good|ok)|still with me|let me know)\s*$",
    re.IGNORECASE,
)


def _extract_hook(response_text: str) -> tuple[str, str] | None:
    """
    Return (last_bubble, hook_style) if the last bubble looks like an open loop
    worth following up on, or None if no hook detected.

    hook_style is one of:
      "question"   — ends with a genuine question (re-ask framing: "Earlier you asked…")
      "engagement" — ends with an engagement phrase like "let me know" or "still with me"
                     (re-ask framing: "You ended on X — re-engage naturally")

    Logic: split on |||, take the last non-empty bubble, check against the two
    distinct regex classes. Filter out very short fragments.
    """
    if not response_text:
        return None
    bubbles = [b.strip() for b in response_text.split("|||") if b.strip()]
    if not bubbles:
        return None
    last = bubbles[-1]
    if len(last) < _MIN_HOOK_LEN:
        return None
    if _HOOK_QUESTION_ENDINGS.search(last):
        return (last, "question")
    if _HOOK_ENGAGEMENT_ENDINGS.search(last):
        return (last, "engagement")
    return None


async def sync_pending_questions(db, user, llm_reply_text: str = "") -> None:
    """
    Reconcile open questions for `user` against current state. Best-effort: never
    raises into the turn (a follow-up bookkeeping error must not break a reply).

    llm_reply_text: the RAW LLM reply string (pre-dashboard-append) used to detect
    hooks. Must NOT be a string rebuilt from resp.bubbles after URL injection —
    see the INVARIANT comment in core/conversation.py above the run_turn call.
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

        # ── Conversation / proactive hook loops ───────────────────────────────
        # Any inbound message from the user closes an open hook — they responded.
        # proactive_hook is the silence-consolidation loop (scheduler opens it when
        # a user has ignored several check-ins); a reply ends the quiet stretch and
        # clears it just like a conversation hook.
        await resolve_pending_questions(
            db, user.id, kinds=["conversation_hook", "proactive_hook"]
        )

        # If Arnie's new response ends on a question or engagement phrase, open a
        # new hook loop. Store the hook_style so _llm_followup can pick the right
        # re-ask template (question → "Earlier you asked…" / engagement → re-engage).
        if llm_reply_text:
            hook_result = _extract_hook(llm_reply_text)
            if hook_result:
                hook_text, hook_style = hook_result
                await record_pending_question(
                    db, user.id, kind="conversation_hook",
                    question=hook_text, tier="conversation_hook",
                    hook_style=hook_style,
                )

    except Exception as e:
        logger.error(f"sync_pending_questions failed for user {getattr(user, 'id', '?')}: {e}")
