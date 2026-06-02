"""
Context-aware follow-ups — given an unanswered question, decide whether to
re-ask now and with what tone.

This is the timing brain for the "you left my question hanging" loop. It replaces
blind slot-timer re-nudging with state-aware decisions over PendingQuestion rows:
each open question is re-asked on a tier-scaled cadence, a bounded number of
times, never on top of a live thread, and never to a user who's gone cold.

Pure logic — functions take a duck-typed question (anything exposing tier /
asked_at / last_asked_at / follow_up_count / answered_at) and a `now`, so they're
trivially unit-testable. No DB, no sending. The scheduler does the IO.

Tone tiers (audit §9 "follow-up tone tiers"):
  casual         — nice-to-know. Patient cadence, gives up quickly, soft phrasing.
  goal_critical  — matters for their goal (targets, weigh-ins). Tighter cadence,
                   one more attempt, direct-but-warm phrasing.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

from reminders.eligibility import is_in_live_conversation


@dataclasses.dataclass(frozen=True)
class FollowUpPolicy:
    first_delay_h: float    # wait this long after the first ask before re-asking
    spacing_h: float        # minimum gap between subsequent re-asks
    max_follow_ups: int     # stop re-asking after this many (0 = never follow up)


TIER_POLICY: dict[str, FollowUpPolicy] = {
    "casual":           FollowUpPolicy(first_delay_h=24.0, spacing_h=24.0, max_follow_ups=2),
    "goal_critical":    FollowUpPolicy(first_delay_h=8.0,  spacing_h=12.0, max_follow_ups=3),
    "conversation_hook": FollowUpPolicy(first_delay_h=2.0, spacing_h=3.0,  max_follow_ups=1),
}

# A user silent this long has effectively churned — stop following up so we don't
# nag a cold account into the void. (They re-engage → resolution clears the queue.)
COLD_USER_CUTOFF_DAYS = 14


def _utcnow(now: datetime | None) -> datetime:
    return now if now is not None else datetime.utcnow()


def _naive(dt: datetime | None) -> datetime | None:
    """Drop tzinfo so naive-UTC DB timestamps and an aware `now` compare cleanly."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _policy_for(pq) -> FollowUpPolicy:
    tier = getattr(pq, "tier", None) or "casual"
    return TIER_POLICY.get(tier, TIER_POLICY["casual"])


def should_follow_up(pq, now: datetime | None = None, *,
                     mins_since_last_exchange: float | None = None) -> bool:
    """
    Decide whether to re-ask `pq` right now.

    False when: already answered; hit the re-ask cap for its tier; the user is
    mid-conversation (don't interrupt); the user has gone cold; or not enough time
    has elapsed since the last ask (tier-scaled — longer before the first re-ask,
    `spacing_h` between subsequent ones).
    """
    if getattr(pq, "answered_at", None) is not None:
        return False

    policy = _policy_for(pq)
    count = getattr(pq, "follow_up_count", 0) or 0
    if count >= policy.max_follow_ups:
        return False

    # Don't fire on top of a live thread.
    if is_in_live_conversation(mins_since_last_exchange):
        return False

    # Don't nag a churned user.
    if (mins_since_last_exchange is not None
            and mins_since_last_exchange > COLD_USER_CUTOFF_DAYS * 24 * 60):
        return False

    now = _naive(_utcnow(now))
    ref = getattr(pq, "last_asked_at", None) or getattr(pq, "asked_at", None)
    ref = _naive(ref)
    if ref is None:
        return True  # asked, but no timestamp recorded — eligible

    required_gap_h = policy.first_delay_h if count == 0 else policy.spacing_h
    elapsed_h = (now - ref).total_seconds() / 3600.0
    return elapsed_h >= required_gap_h


def select_follow_up(pqs, now: datetime | None = None, *,
                     mins_since_last_exchange: float | None = None):
    """
    Pick the single highest-priority question to re-ask this tick (the one-per-tick
    frequency cap), or None. Goal-critical outranks casual; within a tier, the
    oldest unanswered question goes first.
    """
    eligible = [
        pq for pq in pqs
        if should_follow_up(pq, now, mins_since_last_exchange=mins_since_last_exchange)
    ]
    if not eligible:
        return None

    def _rank(pq):
        tier = getattr(pq, "tier", None) or "casual"
        tier_rank = 0 if tier == "goal_critical" else 1
        asked = _naive(getattr(pq, "asked_at", None)) or datetime.max
        return (tier_rank, asked)

    eligible.sort(key=_rank)
    return eligible[0]


def follow_up_tone(pq) -> str:
    """
    A phrasing hint for the LLM generating the re-ask, scaled by tier and how many
    times we've already asked. Keeps repeated nudges from feeling robotic or naggy.
    """
    tier = getattr(pq, "tier", None) or "casual"
    count = getattr(pq, "follow_up_count", 0) or 0
    if tier == "goal_critical":
        if count == 0:
            return "direct but warm — this matters for dialing in their goal. no guilt-trip."
        return "last real ask. quick and frictionless, one detail is enough. then let it go."
    # casual
    if count == 0:
        return "light, zero pressure. 'whenever you get a sec.'"
    return "very light final nudge — easy to answer in a word, then drop it for good."
