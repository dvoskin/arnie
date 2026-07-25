"""
Post-turn background jobs — profile synthesis + behavioral reflection.

These run AFTER a coaching turn is already delivered, so they never add latency to
the user's reply. Every surface (the iOS API via core/chat_service, the Telegram
bot, iMessage) should fire them the same way, so the logic lives here once instead
of being copy-pasted into each handler.

CRITICAL — session lifetime:
  The request-scoped db session closes when the handler returns. These tasks must
  therefore open their OWN AsyncSessionLocal and re-fetch the user by id. Never
  close over the request session or a live user instance — both are detached/closed
  by the time the task runs.
"""
from __future__ import annotations

import asyncio
import logging
import re

from db.database import AsyncSessionLocal
from db.queries import reload_user

logger = logging.getLogger(__name__)

_REFLECT_MIN_CHARS = 20

# DETERMINISTIC MEMORY GATING (P0.7, review: "sampling is acceptable for
# analytics, not for important user memory"). Reflection used to fire on a
# 25% coin flip, so two users revealing the same durable fact got different
# outcomes by luck. Now a turn is reflected when it CARRIES a memory signal:
# an explicit remember request, a stated preference or habit, a constraint,
# a commitment, or a correction of what Arnie believes. Everything else is
# skipped outright — cheaper than sampling AND never loses a real signal.
_MEMORY_SIGNAL_RE = re.compile(
    r"\b(remember|don'?t forget|note that|for future reference|"
    r"i (?:always|usually|normally|generally|never|prefer|like|hate|can'?t|"
    r"cannot|don'?t)\b|"
    r"my (?:usual|go[- ]?to|routine|schedule|goal|target|plan)\b|"
    r"i'?m (?:allergic|lactose|vegetarian|vegan|gluten|training for|trying to)\b|"
    r"from now on|going forward|starting (?:today|monday|tomorrow)|"
    r"switch(?:ed|ing)? to|stopped|quit|gave up|"
    r"actually,? (?:i|my)|that'?s (?:wrong|not right|incorrect)|no,? i\b)",
    re.I)


def turn_has_memory_signal(user_text: str) -> bool:
    """True when the turn carries something worth durably remembering."""
    t = (user_text or "").strip()
    if len(t) <= _REFLECT_MIN_CHARS:
        return False
    return bool(_MEMORY_SIGNAL_RE.search(t))


async def run_profile_update(user_id: int) -> None:
    """Re-synthesize the user's profile. Throttled (~3h) inside maybe_update_profile."""
    try:
        async with AsyncSessionLocal() as db:
            user = await reload_user(db, user_id)
            if user:
                from memory.profile_updater import maybe_update_profile
                await maybe_update_profile(user, db)
    except Exception as e:
        logger.error(f"Profile update error: {e}")


async def run_reflection(user_id: int, user_text: str, response_text: str) -> None:
    """Capture durable behavioral notes from this turn."""
    try:
        async with AsyncSessionLocal() as db:
            user = await reload_user(db, user_id)
            if user:
                from memory.reflection import maybe_update_memory
                await maybe_update_memory(user, user_text, response_text, db)
    except Exception as e:
        logger.error(f"Reflection error: {e}")


async def _enqueue(user_id: int, kind: str, payload: dict, dedup_key: str) -> None:
    """Durable row for the same work — the guarantee behind the fast task."""
    try:
        async with AsyncSessionLocal() as db:
            from db.queries import enqueue_background_job
            await enqueue_background_job(db, user_id, kind, payload=payload,
                                         dedup_key=dedup_key)
    except Exception as e:
        logger.warning(f"durable enqueue skipped ({kind}): {e}")


def schedule_post_turn_jobs(user_id: int, user_text: str, bubbles: list[str]) -> None:
    """Queue the post-turn jobs DURABLY, then run them in-process.

    The asyncio task is the fast path; the queued row is the guarantee — a
    deploy or crash mid-task leaves the row pending for the scheduler sweep
    instead of silently losing the work (P0.7). Both jobs are idempotent, so
    at-least-once is the right semantics: profile synthesis is throttled
    internally and reflection dedups its notes.

    Profile synthesis runs every (non-onboarding) turn; reflection runs when
    the turn carries a memory signal — deterministic, not sampled. Callers
    should skip this during onboarding.
    """
    asyncio.create_task(_enqueue(user_id, "profile_update", {},
                                 f"profile:{user_id}"))
    asyncio.create_task(run_profile_update(user_id))

    if turn_has_memory_signal(user_text):
        response_text = "|||".join(bubbles)
        asyncio.create_task(_enqueue(
            user_id, "reflection",
            {"user_text": user_text[:2000], "response_text": response_text[:2000]},
            f"reflect:{user_id}:{abs(hash(user_text[:120]))}"))
        asyncio.create_task(run_reflection(user_id, user_text, response_text))


async def sweep_background_jobs(limit: int = 20) -> int:
    """Run any durable job left pending — the safety net for tasks lost to a
    deploy, crash or shutdown. Called on the scheduler tick. Returns how many
    ran. Never raises."""
    ran = 0
    try:
        async with AsyncSessionLocal() as db:
            from db.queries import claim_due_background_jobs, finish_background_job
            import json as _json
            jobs = await claim_due_background_jobs(db, limit=limit)
            for job in jobs:
                payload = {}
                try:
                    payload = _json.loads(job.payload_json or "{}") or {}
                except Exception:
                    payload = {}
                ok, err = True, ""
                try:
                    if job.kind == "profile_update":
                        await run_profile_update(job.user_id)
                    elif job.kind == "reflection":
                        await run_reflection(job.user_id,
                                             payload.get("user_text", ""),
                                             payload.get("response_text", ""))
                    else:
                        ok = False
                        err = f"unknown job kind {job.kind!r}"
                except Exception as e:
                    ok, err = False, str(e)
                await finish_background_job(db, job.id, ok, err)
                ran += 1
        if ran:
            logger.info(f"event=bg_sweep ran={ran}")
    except Exception as e:
        logger.warning(f"background sweep failed: {e}")
    return ran
