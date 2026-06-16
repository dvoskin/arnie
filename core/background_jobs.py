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
import random

from db.database import AsyncSessionLocal
from db.queries import reload_user

logger = logging.getLogger(__name__)

# Reflection is sampled, not run every turn — durable notes only need the
# occasional substantive message, and it keeps LLM cost down.
_REFLECT_PROBABILITY = 0.25
_REFLECT_MIN_CHARS = 20


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


def schedule_post_turn_jobs(user_id: int, user_text: str, bubbles: list[str]) -> None:
    """Fire-and-forget the post-turn jobs as asyncio tasks.

    Profile synthesis runs every (non-onboarding) turn; reflection is sampled on
    substantive messages. Callers should skip this during onboarding.
    """
    asyncio.create_task(run_profile_update(user_id))

    if random.random() < _REFLECT_PROBABILITY and user_text and len(user_text) > _REFLECT_MIN_CHARS:
        response_text = "|||".join(bubbles)
        asyncio.create_task(run_reflection(user_id, user_text, response_text))
