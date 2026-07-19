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

import json
import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from db.queries import (
    get_conversation_by_idempotency_key,
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

# History depth. Normal coaching loads enough recent turns that the reply feels
# aware of the actual conversation (continuity is a trust signal — too few turns and
# Arnie loses the thread or re-asks). Onboarding loads more so stats given across
# rapid messages stay visible and aren't re-asked. Mirrors the bot's _build_messages
# (without its reference-pattern heuristic, which can be lifted here later).
_HISTORY_NORMAL = 10
_HISTORY_ONBOARDING = 25

# Idempotency window for collapsing a double-fired identical message (double-tap /
# client retry). The iOS per-identity lock serializes same-user requests, so the
# repeat lands just after the first turn committed — a short window catches it.
_DEDUP_WINDOW_SEC = 20
# Tighter window + min length for collapsing a repeat that FIRED TOOLS (a re-run
# would double-write a log). Only a substantial phrase within this window is taken
# as a client retry; a deliberately repeated short set-entry ("130x12", "again")
# falls through to the per-tool dedup guard. Closes the gap that let an identical
# resend double-log a multi-set block (shrugs 3×14,14,15 written twice, 2026-06-25).
_DEDUP_TOOL_WINDOW_SEC = 10
_DEDUP_MIN_PHRASE_LEN = 22
# A prior reply matching one of these recovery signatures means the turn ERRORED —
# never collapse onto it, or a resend-after-error loops on the canned apology
# instead of actually retrying.
_RECOVERY_SIGS = (
    "wires crossed", "hit a snag", "went sideways", "didn't go through",
    "hiccupped saving", "didn't save right", "got a bit confused",
    "didn't quite land", "lost the thread", "still here. what's the move",
)


def _coach_home_block(briefing: dict) -> str:
    """Render the cached Coach-home briefing into a compact context block so the
    chat turn sees exactly what's on the user's home screen right now. Kept short
    (headline + body + focus + card titles) — enough to keep chat coherent with
    the dashboard without dumping every story verbatim into every prompt."""
    hero = briefing.get("hero") or {}
    focus = briefing.get("focus") or {}
    cards = briefing.get("cards") or []
    lines: list[str] = []
    headline = (hero.get("headline") or "").strip()
    body = (hero.get("body") or "").strip()
    if headline:
        lines.append(f"  hero: {headline}")
    if body:
        lines.append(f"  hero body: {body}")
    foc_title = (focus.get("title") or "").strip()
    foc_body = (focus.get("body") or "").strip()
    if foc_title or foc_body:
        lines.append(f"  focus: {foc_title}{' — ' if foc_title and foc_body else ''}{foc_body}")
    card_titles = [str(c.get("title") or "").strip() for c in cards if c.get("title")]
    if card_titles:
        lines.append(f"  insight cards: {'; '.join(card_titles[:4])}")
    if not lines:
        return ""
    header = (
        "[COACH HOME — what they're looking at right now on the Coach feed. "
        "Stay coherent with this read: don't contradict the hero or the focus, "
        "and pick up the same thread if they ask 'why' or 'what should I do']"
    )
    return header + "\n" + "\n".join(lines)


def _is_error_reply(response_text: str) -> bool:
    """True when a stored reply is a recovery/error bubble — never replay onto it,
    so a resend after an errored turn actually retries."""
    return any(s in (response_text or "").lower() for s in _RECOVERY_SIGS)


def _replay_from_row(row) -> Optional[Response]:
    """Reconstruct the Response to replay for an idempotent retry, or None when the
    stored turn shouldn't be replayed (it errored). Shared by the keyed-idempotency
    path and the text-window fallback."""
    resp_text = getattr(row, "response", "") or ""
    if _is_error_reply(resp_text):
        return None
    bubbles = [b for b in resp_text.split("|||") if b.strip()]
    if not bubbles:
        return None
    cards = []
    if getattr(row, "cards_json", None):
        try:
            cards = json.loads(row.cards_json) or []
        except Exception:
            cards = []
    return Response(bubbles=bubbles, cards=cards)


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
    idempotency_key: Optional[str] = None,
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
    idempotency_key    — stable per-send id (client UUID / native message id). When
                          supplied, a retry of the SAME send replays the prior reply
                          deterministically instead of re-running (and double-logging).
                          Falls back to the text-window heuristic when omitted.
    """
    _source = source_type or platform

    # ── Deterministic idempotency (preferred over the text-window heuristic) ──
    # A keyed retry replays the already-persisted reply verbatim — no re-run, no
    # double-write — UNLESS the stored reply was an error (then the resend must
    # actually retry). The caller serializes same-user turns (per-identity lock),
    # so the first turn has committed before any retry reaches here.
    if idempotency_key:
        try:
            _hit = await get_conversation_by_idempotency_key(db, user.id, idempotency_key)
            if _hit is not None:
                _replay = _replay_from_row(_hit)
                if _replay is not None:
                    logger.info(
                        f"idempotency: replayed turn for user {user.id} "
                        f"key={idempotency_key[:24]} — no re-run"
                    )
                    return TurnResult(
                        response=_replay, tool_calls=[], just_completed=False,
                        in_onboarding=not bool(getattr(user, "onboarding_completed", False)),
                        onboarding_field_saved=None, today_log=None, user=user,
                        log_id=getattr(_hit, "id", None),
                    )
        except Exception as _e:
            logger.debug(f"idempotency check skipped for user {getattr(user,'id','?')}: {_e}")

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
        _reset_row = await log_conversation(
            db, user.id, text, "|||".join(bubbles),
            source_type=_source, platform=platform,
        )
        return TurnResult(
            response=Response(bubbles=bubbles),
            tool_calls=[], just_completed=False,
            in_onboarding=not bool(getattr(user, "onboarding_completed", False)),
            onboarding_field_saved=None, today_log=None, user=user,
            log_id=getattr(_reset_row, "id", None),
        )

    # ── Onboarding state ──────────────────────────────────────────────────────
    # `was_onboarding` is the state BEFORE the turn; run_turn may complete
    # onboarding via tools, flipping in_onboarding to False → just_completed.
    in_onboarding = not bool(getattr(user, "onboarding_completed", False))
    was_onboarding = in_onboarding

    # ── Idempotency: collapse a double-fired identical message ────────────────
    # A double-tap / client retry of the SAME text arrives just after the first
    # turn committed (the caller's per-identity lock serializes them). Return the
    # prior reply instead of regenerating, in two cases:
    #   (1) prior turn fired NO tools — a pure informational reply, e.g. a coach-feed
    #       "Tell me more" drill-down (the double-fire that produced two near-
    #       duplicate essays). Collapse within the full window.
    #   (2) prior turn DID fire tools — a log. A re-run would DOUBLE-WRITE the entry,
    #       and the per-tool dedup guard misses some shapes (a resent multi-set block
    #       lands on a different reps signature and slips through). Collapse only a
    #       *substantial phrase* ("Got 15, doing upright rows now") within a TIGHT
    #       window — a clear client retry. A deliberately repeated short set-entry
    #       ("130x12", "again") stays below the length bar and logs normally.
    # Never collapse onto a recovery/error reply — a resend-after-error must retry.
    # Fully wrapped: any failure falls through to a normal turn.
    try:
        _prev = await get_recent_conversations(db, user.id, limit=1)
        if _prev:
            _p = _prev[0]
            _age = ((datetime.utcnow() - _p.timestamp).total_seconds()
                    if _p.timestamp else 1e9)
            _same = (_p.raw_message or "") == text
            _fired_tools = bool((_p.skills_fired or "").strip())
            _prev_resp = _p.response or ""
            _was_error = any(s in _prev_resp.lower() for s in _RECOVERY_SIGS)
            _t = text.strip()
            _coalesce = False
            if _same and not _was_error and 0 <= _age <= _DEDUP_WINDOW_SEC:
                if not _fired_tools:
                    _coalesce = True
                elif (_age <= _DEDUP_TOOL_WINDOW_SEC
                      and len(_t) >= _DEDUP_MIN_PHRASE_LEN and " " in _t):
                    _coalesce = True
            if _coalesce:
                _bubbles = [b for b in _prev_resp.split("|||") if b.strip()]
                _cards = []
                if getattr(_p, "cards_json", None):
                    try:
                        _cards = json.loads(_p.cards_json) or []
                    except Exception:
                        _cards = []
                if _bubbles:
                    logger.info(
                        f"dedup: collapsed repeat message for user {user.id} "
                        f"(age={_age:.1f}s, fired_tools={_fired_tools}) — "
                        f"returning prior reply, no re-run"
                    )
                    return TurnResult(
                        response=Response(bubbles=_bubbles, cards=_cards),
                        tool_calls=[], just_completed=False,
                        in_onboarding=in_onboarding, onboarding_field_saved=None,
                        today_log=None, user=user,
                    )
    except Exception as _e:
        logger.debug(f"dedup check skipped for user {getattr(user, 'id', '?')}: {_e}")

    # ── System prompt (+ live context for active coaching) ────────────────────
    if not in_onboarding:
        today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        context_str = await build_context(
            user, today_log, db, platform=platform, user_message=text
        )
        # Coach-home sync: if there's a CACHED briefing for this user (the same
        # one their iOS Coach feed is rendering right now), append it so chat
        # speaks coherently with what's on their screen — Arnie won't tell them
        # to "train upper" in chat while the Coach hero says "Lock in protein."
        # Cache-only read (no LLM regen), best-effort, silent on miss.
        try:
            from api.insights import _CACHE as _briefing_cache
            cached = _briefing_cache.get((user.id, "__briefing__"))
            if cached and cached[1]:
                context_str = f"{context_str}\n\n{_coach_home_block(cached[1])}"
        except Exception as _e:
            logger.debug(f"coach-home sync block skipped: {_e}")
        system = f"{build_arnie_system(platform=platform)}\n\n{context_str}"
    else:
        today_log = None
        system = build_onboarding_system(user)  # dynamic — reflects saved state

    # ── Message history + current message ─────────────────────────────────────
    limit = _HISTORY_ONBOARDING if in_onboarding else _HISTORY_NORMAL
    recent = await get_recent_conversations(db, user.id, limit=limit)
    messages = conversations_to_messages(  # reversed internally → chrono
        recent, user_timezone=getattr(user, "timezone", None) or "UTC")
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
    _conv_row = await log_conversation(
        db, user.id, text, log_text, source_type=_source,
        parsed_intent=(",".join(turn.health_flags) or None),
        skills_fired=turn.skills_fired,
        platform=platform,
        # Persist the turn's typed cards so native clients can rehydrate them on
        # history restore (otherwise the transcript reloads text-only and cards
        # vanish). Empty for chat-bot / text-only turns → stored as null.
        cards=(turn.response.cards or None),
        # Stamp the per-send id so a later retry of this exact send replays this
        # row instead of re-running (deterministic dedup).
        idempotency_key=idempotency_key,
        # Persist the reasoning receipt so "Arnie's Thoughts" survives reloads.
        reasoning=(getattr(turn.response, "reasoning", None) or None),
    )
    # The row id is this turn's stable identity — clients stamp it on the live
    # bubbles so a later history reload recognizes them by id, not by text.
    turn.log_id = getattr(_conv_row, "id", None)

    # ── Background profile synthesis + reflection ─────────────────────────────
    if schedule_background and not turn.in_onboarding:
        schedule_post_turn_jobs(turn.user.id, text, turn.response.bubbles)

    return turn
