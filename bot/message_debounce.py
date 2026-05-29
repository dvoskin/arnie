"""
Message debounce utility.

When a user sends multiple messages in rapid succession (common on iMessage
and Telegram), this batches them into a single pipeline call instead of
firing separate responses for each one.

Usage:
    await schedule_message(user_id, handler_key, text, callback, delay=2.0)

The callback receives the combined text of all messages that arrived within
the debounce window.
"""
import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Per-user pending tasks and message buffers
_pending_tasks: dict[str, asyncio.Task] = {}
_buffers: dict[str, list[str]] = {}


async def schedule_message(
    user_key: str,
    text: str,
    callback: Callable[[str], Awaitable[None]],
    delay: float = 2.0,
) -> None:
    """
    Buffer `text` for `user_key` and fire `callback(combined_text)` after
    `delay` seconds of silence. If another message arrives within the window,
    the timer resets and texts are concatenated.

    user_key  — unique key combining platform + user id, e.g. "tg:123456"
    text      — the incoming message text
    callback  — async function that takes the combined text string
    delay     — seconds to wait before processing (default 2.0)
    """
    # Add to buffer
    _buffers.setdefault(user_key, []).append(text)

    # Cancel any existing pending task for this user
    existing = _pending_tasks.get(user_key)
    if existing and not existing.done():
        existing.cancel()

    async def _fire():
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return  # Superseded by a newer message — exit silently

        texts = _buffers.pop(user_key, [])
        _pending_tasks.pop(user_key, None)

        if not texts:
            return

        combined = "\n".join(texts) if len(texts) > 1 else texts[0]
        if len(texts) > 1:
            logger.info(f"Debounce: batched {len(texts)} messages for {user_key}")

        try:
            await callback(combined)
        except Exception as e:
            import traceback
            logger.error(f"Debounce callback failed for {user_key}: {e}\n{traceback.format_exc()}")

    task = asyncio.create_task(_fire())
    _pending_tasks[user_key] = task
