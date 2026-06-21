"""
Transport-agnostic chat service.

The single entry point for "a user said something → Arnie coaches back", with no
knowledge of HOW the message arrived (Telegram, iMessage, or the iOS app's native
chat) or how the reply will be rendered.

WHY THIS EXISTS
  bot/telegram_handler.py predates this module and still owns its own rich
  orchestration (typing keepalives, streamed bubbles, onboarding keyboards,
  button-driven target calc). That is fine — it is the Telegram *delivery* layer.
  This module is the clean coaching core the iOS API is built on, and the seam
  telegram_handler can migrate onto incrementally. Keeping the brain in one place
  is the same discipline core/platform.py applies to rendering: one core, many
  surfaces, so behavior can never silently drift between platforms.

WHAT LIVES HERE (shared, platform-neutral)
  • resolve onboarding state → system prompt (+ context for the active turn)
  • build the message history the model sees
  • run_turn — the coaching brain
  • persist the conversation
  • kick off background profile / reflection jobs

WHAT DOES NOT LIVE HERE (stays in the handler / adapter)
  • rendering a Response (PlatformAdapter / serialize_response)
  • input parsing (voice transcription, photo analysis, button payloads)
  • delivery niceties (typing indicators, per-bubble streaming wiring)
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from db.queries import (
    get_or_create_today_log,
    get_recent_conversations,
    log_conversation,
)
from core.background_jobs import schedule_post_turn_jobs
from core.context_builder import build_context
from core.conversation import TurnResult, run_turn
from core.history import conversations_to_messages
from core.platform import Response
from core.prompts.arnie import build_arnie_system
from core.reset import parse_reset_command, reset_today, reset_all
from handlers.onboarding import build_onboarding_system

logger = logging.getLogger(__name__)

# History depth. A few turns is enough for normal coaching; onboarding loads more
# so stats given across rapid messages stay visible and aren't re-asked. Mirrors
# the bot's _build_messages (without its reference-pattern heuristic, which can be
# lifted here later if the app shows the same "what did I say earlier" misses).
_HISTORY_NORMAL = 6
_HISTORY_ONBOARDING = 25


async def run_chat_turn(
    db,
    user,
    text: str,
    *,
    platform: str,
    source_type: Optional[str] = None,
    on_text_bubble: Optional[Callable[[str], Awaitable[None]]] = None,
    on_image: Optional[Callable[[str, str], Awaitable[None]]] = None,
    on_interim: Optional[Callable[[str], Awaitable[None]]] = None,
    on_tool_start: Optional[Callable[[list], Awaitable[None]]] = None,
    schedule_background: bool = True,
) -> TurnResult:
    """Run one coaching turn for an already-resolved user and return the TurnResult.

    The caller owns identity resolution (which user) and delivery (how to render
    turn.response). This function owns everything in between.

    platform           — "ios" | "telegram" | "imessage"; flows to the prompt /
                          context builders and run_turn's telemetry tag.
    source_type        — tool-execution source label; defaults to `platform`.
    on_text_bubble     — optional async per-bubble callback for streaming surfaces;
                          omit for one-shot REST.
    schedule_background — kick off profile/reflection jobs. Tests pass False to keep
                          the turn synchronous and free of detached-session tasks.
    """
    _source = source_type or platform

    # ── Slash-command interception (pre-LLM) ──────────────────────────────────
    # /reset today and /reset all confirm bypass the coaching brain entirely.
    # Lives here so iOS / iMessage / web get the same behavior Telegram has —
    # the LLM has no way to wipe data and would refuse the user otherwise.
    _reset_action, _reset_confirmed = parse_reset_command(text)
    if _reset_action is not None:
        if _reset_action == "help":
            bubbles = [
                "Reset options:",
                "/reset today — clear today's food, exercise, totals + chat",
                "/reset all confirm — wipe everything. cannot be undone.",
            ]
        elif _reset_action == "today":
            cleared = await reset_today(db, user)
            bubbles = (
                ["Today's log cleared — food, exercise, totals, chat all wiped.",
                 "Start logging fresh."]
                if cleared
                else ["Nothing logged today yet — nothing to reset."]
            )
        else:  # "all"
            if not _reset_confirmed:
                bubbles = [
                    "⚠️ This wipes ALL your data — logs, weight history, memory, profile.",
                    "To confirm: /reset all confirm",
                ]
            else:
                await reset_all(db, user)
                bubbles = [
                    "All data wiped. Fresh start.",
                    "Send any message to begin setup again.",
                ]
        await log_conversation(
            db, user.id, text, "|||".join(bubbles),
            source_type=_source, platform=platform,
        )
        return TurnResult(
            response=Response(bubbles=bubbles),
            tool_calls=[], just_completed=False,
            in_onboarding=not bool(getattr(user, "onboarding_completed", False)),
            onboarding_field_saved=None, today_log=None, user=user,
        )

    # ── Onboarding state ──────────────────────────────────────────────────────
    # `was_onboarding` is the state BEFORE the turn; run_turn may complete
    # onboarding via tools, flipping in_onboarding to False → just_completed.
    in_onboarding = not bool(getattr(user, "onboarding_completed", False))
    was_onboarding = in_onboarding

    # ── System prompt (+ live context for active coaching) ────────────────────
    if not in_onboarding:
        today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        context_str = await build_context(
            user, today_log, db, platform=platform, user_message=text
        )
        system = f"{build_arnie_system(platform=platform)}\n\n{context_str}"
    else:
        today_log = None
        system = build_onboarding_system(user)  # dynamic — reflects saved state

    # ── Message history + current message ─────────────────────────────────────
    limit = _HISTORY_ONBOARDING if in_onboarding else _HISTORY_NORMAL
    recent = await get_recent_conversations(db, user.id, limit=limit)
    messages = conversations_to_messages(recent)  # reversed internally → chrono
    messages.append({"role": "user", "content": text})

    # ── Coaching brain ────────────────────────────────────────────────────────
    turn = await run_turn(
        user, db, messages, system, platform=platform,
        in_onboarding=in_onboarding, was_onboarding=was_onboarding,
        today_log=today_log, source_type=_source,
        on_image=on_image, on_interim=on_interim,
        on_text_bubble=on_text_bubble, on_tool_start=on_tool_start,
    )

    # ── Persist the conversation ──────────────────────────────────────────────
    # Store the reply as the |||-joined bubbles (same on-disk shape every surface
    # uses) and stash turn-health flags on parsed_intent for the admin audit view.
    log_text = "|||".join(turn.response.bubbles)
    await log_conversation(
        db, user.id, text, log_text, source_type=_source,
        parsed_intent=(",".join(turn.health_flags) or None),
        platform=platform,
        # Persist the turn's typed cards so native clients can rehydrate them on
        # history restore (otherwise the transcript reloads text-only and cards
        # vanish). Empty for chat-bot / text-only turns → stored as null.
        cards=(turn.response.cards or None),
    )

    # ── Background profile synthesis + reflection ─────────────────────────────
    if schedule_background and not turn.in_onboarding:
        schedule_post_turn_jobs(turn.user.id, text, turn.response.bubbles)

    return turn
