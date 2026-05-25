"""
Lightweight reflection loop — decides whether a conversation exchange contains
something worth persisting to the user's memory file.
Runs at ~10% frequency to keep token costs low.
"""
import logging
from db.models import User, MemoryUpdate
from memory.memory_manager import read_memory, append_memory_update
from core.llm import chat

logger = logging.getLogger(__name__)

_SYSTEM = """You are Arnie's memory filter. Decide if this conversation exchange contains anything worth permanently remembering about the user.

Worth storing: behavioral patterns, persistent preferences, recurring struggles, successful coaching interventions, motivational triggers, dietary tendencies, training tendencies.

NOT worth storing: individual meals, single workouts, one-off moods, generic exchanges.

If there is something durable and coaching-relevant: respond with a concise markdown note (2-5 lines max).
If not: respond with exactly "NO".

Be very selective. Only flag genuinely useful, durable insights."""


async def maybe_update_memory(user: User, message: str, response: str, db):
    """Run reflection. Called with ~10% probability per message turn."""
    try:
        existing = await read_memory(user.telegram_id)

        prompt = (
            f"Existing memory (excerpt):\n{existing[:1000] if existing else 'None'}\n\n"
            f"User said: {message}\n"
            f"Arnie replied: {response}\n\n"
            "Is there anything worth remembering from this exchange?"
        )

        result = await chat(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            tools=False,
            max_tokens=256,
        )
        text = result["text"].strip()

        if text and text.upper() != "NO" and len(text) > 15:
            reasoning = "Durable pattern/preference detected"
            await append_memory_update(user.telegram_id, text, reasoning)
            db.add(MemoryUpdate(
                user_id=user.id,
                update_summary=text[:500],
                reasoning=reasoning,
            ))
            await db.commit()
            logger.info(f"Memory updated for user {user.telegram_id}")
    except Exception as e:
        logger.error(f"Reflection error for {user.telegram_id}: {e}")
