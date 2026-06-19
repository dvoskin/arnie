"""Shared reset logic — single source of truth used by every surface
(Telegram slash-command handler, iOS chat-service interceptor, future iMessage).

Lives here so /reset today and /reset all behave identically across platforms
instead of only working on the surface that owns the command parser. Bug
discovered 2026-06-18: iOS users typing "/reset all confirm" or "Wipe my
chat" hit the LLM, which refused — because the slash handler lived only in
bot/telegram_handler.py.
"""
from __future__ import annotations

import logging
from typing import Tuple

from db.queries import (
    clear_today_conversations,
    reset_all_user_data,
    reset_today_log,
)

logger = logging.getLogger(__name__)


async def reset_today(db, user) -> bool:
    """Clear today's food/exercise log + today's conversation history.
    Returns True if anything was actually cleared."""
    tz = user.timezone or "UTC"
    cleared = await reset_today_log(db, user.id, tz)
    await clear_today_conversations(db, user.id, tz)
    return cleared


async def reset_all(db, user) -> None:
    """Full account wipe: all logs, weight history, conversations, memory file,
    profile matrix. Cannot be undone."""
    telegram_id = user.telegram_id
    await reset_all_user_data(db, user.id)

    try:
        from memory.memory_manager import clear_memory
        await clear_memory(telegram_id)
    except Exception as e:
        logger.warning(f"clear_memory failed for {telegram_id}: {e}")

    try:
        from memory.profile_manager import clear_profile
        await clear_profile(telegram_id)
    except Exception as e:
        logger.warning(f"clear_profile failed for {telegram_id}: {e}")


def parse_reset_command(text: str) -> Tuple[str, bool]:
    """Parse a /reset command. Returns (action, confirmed).
      action: "help" | "today" | "all" | None (not a reset command)
      confirmed: True only for "all" + "confirm" suffix.
    Case-insensitive; tolerates extra whitespace.
    """
    if not text:
        return (None, False)
    parts = text.strip().lower().split()
    if not parts or parts[0] != "/reset":
        return (None, False)
    if len(parts) == 1:
        return ("help", False)
    sub = parts[1]
    if sub == "today":
        return ("today", False)
    if sub == "all":
        return ("all", len(parts) > 2 and parts[2] == "confirm")
    return ("help", False)
