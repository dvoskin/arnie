"""
iMessage handler via BlueBubbles relay.

Mirrors telegram_handler._run_pipeline() but:
  - Sends replies via the BlueBubbles REST API (bb_send_text)
  - Identifies users with "im:{address}" as their telegram_id
  - Strips HTML tags → plain text before sending (iMessage has no HTML renderer)
  - No typing indicators, no inline keyboards, no ReplyKeyboards

BlueBubbles REST API:
  Base URL:  BLUEBUBBLES_URL  (e.g. http://your-mac.trycloudflare.com)
  Auth:      ?password=BLUEBUBBLES_PASSWORD  (query-param on every call)
  Send text: POST /api/v1/message/text  { chatGuid, message }

Webhook (incoming):
  POST /imessage  (registered in api/app.py)
  Payload field:  data.handle.address, data.text, data.isFromMe
  Signature:      HMAC-SHA256 of raw body, key=BLUEBUBBLES_WEBHOOK_SECRET,
                  delivered in header X-Bluebubbles-Signature
"""
import asyncio
import logging
import os
import random
import re
import hashlib
import hmac
from typing import Optional

import uuid

import httpx

from db.database import AsyncSessionLocal
from db.queries import (
    get_or_create_user, get_or_create_today_log,
    get_recent_conversations, log_conversation,
    reload_user, get_or_create_webhook_token,
)
from core.llm import chat, chat_follow_up
from core.context_builder import build_context, fmt_log
from handlers.onboarding import build_onboarding_system, is_onboarding_complete
from handlers.tool_executor import execute_tool_calls
from memory.reflection import maybe_update_memory

logger = logging.getLogger(__name__)

from bot.message_debounce import schedule_message as _debounce

# ── BlueBubbles client ─────────────────────────────────────────────────────────

_BB_URL      = os.getenv("BLUEBUBBLES_URL", "").rstrip("/")
_BB_PASSWORD = os.getenv("BLUEBUBBLES_PASSWORD", "")
_BB_SECRET   = os.getenv("BLUEBUBBLES_WEBHOOK_SECRET", "")

_http: Optional[httpx.AsyncClient] = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=15.0)
    return _http


# ── iMessage effect identifiers ───────────────────────────────────────────────
# Pass as effectId in the message payload. Requires BlueBubbles Private API
# mode OR works without it on some macOS versions — degrade gracefully if not.

class Effect:
    SLAM       = "com.apple.MobileSMS.expressivesend.impact"
    LOUD       = "com.apple.MobileSMS.expressivesend.loud"
    GENTLE     = "com.apple.MobileSMS.expressivesend.gentle"
    INVISIBLE  = "com.apple.MobileSMS.expressivesend.invisibleink"
    ECHO       = "com.apple.MobileSMS.expressivesend.echo"       # confetti
    BALLOONS   = "com.apple.MobileSMS.expressivesend.balloons"
    FIREWORKS  = "com.apple.MobileSMS.expressivesend.fireworks"
    HEART      = "com.apple.MobileSMS.expressivesend.heart"
    LASERS     = "com.apple.MobileSMS.expressivesend.lasers"
    SPOTLIGHT  = "com.apple.MobileSMS.expressivesend.spotlight"
    SHOOTING   = "com.apple.MobileSMS.expressivesend.shootingstar"


# ── Tapback reaction codes ─────────────────────────────────────────────────────
class Tapback:
    LOVE      = 2000   # ❤️
    LIKE      = 2001   # 👍
    DISLIKE   = 2002   # 👎
    LAUGH     = 2003   # 😂
    EMPHASIZE = 2004   # ‼️
    QUESTION  = 2005   # ❓


async def bb_send_reaction(message_guid: str, tapback: int) -> bool:
    """
    React to an incoming message with a tapback.
    message_guid — the guid of the MESSAGE to react to (from webhook payload data.guid)
    tapback      — one of the Tapback constants
    """
    if not _BB_URL or not _BB_PASSWORD or not message_guid:
        return False
    try:
        resp = await _get_http().post(
            f"{_BB_URL}/api/v1/message/{message_guid}/react",
            params={"password": _BB_PASSWORD},
            json={"tapback": tapback, "remove": False},
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201):
            logger.warning(f"BlueBubbles reaction failed: {resp.status_code} {resp.text[:120]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"BlueBubbles reaction error: {e}")
        return False


async def bb_send_text(chat_guid: str, text: str) -> bool:
    """
    Send a plain-text message to an iMessage chat via BlueBubbles.
    Returns True on success, False on failure.
    """
    if not _BB_URL or not _BB_PASSWORD:
        logger.warning("BlueBubbles not configured — BLUEBUBBLES_URL or BLUEBUBBLES_PASSWORD missing")
        return False

    # Split long messages (iMessage has a soft ~2000-char limit per bubble)
    chunks = _split_message(text, max_len=1800)
    success = True
    for chunk in chunks:
        try:
            resp = await _get_http().post(
                f"{_BB_URL}/api/v1/message/text",
                params={"password": _BB_PASSWORD},
                json={
                    "chatGuid": chat_guid,
                    "message": chunk,
                    "tempGuid": str(uuid.uuid4()),
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code not in (200, 201):
                logger.error(f"BlueBubbles send failed: {resp.status_code} {resp.text[:200]}")
                success = False
        except Exception as e:
            logger.error(f"BlueBubbles HTTP error: {e}")
            success = False
    return success


async def bb_send_text_with_effect(chat_guid: str, text: str, effect: str) -> bool:
    """
    Send a single message bubble with an iMessage screen/bubble effect.
    Falls back to plain send if BlueBubbles rejects the effect (e.g. Private API not active).
    """
    if not _BB_URL or not _BB_PASSWORD:
        return False
    try:
        resp = await _get_http().post(
            f"{_BB_URL}/api/v1/message/text",
            params={"password": _BB_PASSWORD},
            json={
                "chatGuid": chat_guid,
                "message": text,
                "tempGuid": str(uuid.uuid4()),
                "effectId": effect,
            },
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201):
            logger.warning(f"BlueBubbles effect send failed ({effect}): falling back to plain send")
            return await bb_send_text(chat_guid, text)
        return True
    except Exception as e:
        logger.warning(f"BlueBubbles effect error: {e} — falling back to plain send")
        return await bb_send_text(chat_guid, text)


# ── Reaction & effect detection ───────────────────────────────────────────────

_PR_SIGNALS = {"pr", "personal best", "personal record", "new max", "all-time", "🔥", "that's a pr"}
_WIN_SIGNALS = {"hit your goal", "hit your target", "you're there", "nailed it", "crushed it"}
_MOMENTUM_SIGNALS = {"clean day", "on track", "on pace", "solid", "locked in"}


def _detect_coaching_moment(response_text: str, tool_calls: list) -> dict:
    """
    Analyse the response and tool calls to decide if a reaction or effect is warranted.

    Returns:
        {
          "tapback":  int | None,    — tapback code to react to the user's message
          "effect":   str | None,    — effect to apply to the KEY response bubble
          "bubble_index": int,       — which bubble gets the effect (0 = first, -1 = last)
        }
    """
    text_lower = response_text.lower()
    has_exercise = any(tc["name"] == "log_exercise" for tc in tool_calls)

    # PR detected → ❤️ tapback + Slam effect on the PR bubble
    if has_exercise and any(s in text_lower for s in _PR_SIGNALS):
        return {"tapback": Tapback.LOVE, "effect": Effect.SLAM, "bubble_index": 0}

    # Goal / target hit → ❤️ tapback + Balloons
    if any(s in text_lower for s in _WIN_SIGNALS):
        return {"tapback": Tapback.LOVE, "effect": Effect.BALLOONS, "bubble_index": -1}

    # Consistent momentum acknowledgement → 👍 tapback, no effect
    if any(s in text_lower for s in _MOMENTUM_SIGNALS):
        return {"tapback": Tapback.LIKE, "effect": None, "bubble_index": 0}

    return {"tapback": None, "effect": None, "bubble_index": 0}


def _split_message(text: str, max_len: int = 1800) -> list[str]:
    """Split text at sentence/newline boundaries to stay under max_len."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline before max_len
        cut = text.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            # Fall back to last space
            cut = text.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


# ── Text formatting ────────────────────────────────────────────────────────────

def _to_plain(text: str) -> str:
    """
    Convert Arnie's HTML-tagged / markdown responses to iMessage plain text.
    Rules:
      <b>…</b>   → CAPS-WORD or leave as-is (we leave as-is — iMessage users don't need caps)
      <i>…</i>   → keep text, drop tags
      All other tags → strip
      **bold**   → strip stars
      ## headers → strip
      --- rules  → strip
    """
    # Strip markdown headers, rules
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^-{3,}\s*$', '', text, flags=re.MULTILINE)

    # Strip bold/italic stars
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)

    # Strip all HTML tags (keep the inner text)
    text = re.sub(r'<[^>]+>', '', text)

    # Collapse excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # HTML entities
    import html
    text = html.unescape(text)

    return text.strip()


# ── Signature verification ─────────────────────────────────────────────────────

def verify_bb_signature(raw_body: bytes, header_sig: str) -> bool:
    """
    Verify BlueBubbles HMAC-SHA256 webhook signature.
    Header format: sha256=<hex_digest>
    Returns True if secret is not configured (development mode).
    """
    if not _BB_SECRET:
        return True  # Signature checking disabled
    expected = "sha256=" + hmac.new(
        _BB_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header_sig or "")


# ── Pipeline helpers ───────────────────────────────────────────────────────────

async def _build_messages(db, user_id: int, current_text: str) -> list:
    """Build conversation history + current message for the LLM."""
    recent = await get_recent_conversations(db, user_id, limit=6)
    msgs = []
    for conv in reversed(recent):
        msgs.append({"role": "user", "content": conv.raw_message or ""})
        msgs.append({"role": "assistant", "content": conv.response or ""})
    msgs.append({"role": "user", "content": current_text})
    return msgs


def _im_user_id(address: str) -> str:
    """Convert a phone/email address to our internal telegram_id key."""
    return f"im:{address}"


# ── Core pipeline ──────────────────────────────────────────────────────────────

from core.prompts import build_arnie_system as _build_arnie_system
from bot.telegram_handler import _welcome_message, _calc_targets


async def handle_imessage(address: str, chat_guid: str, raw_text: str,
                          message_guid: str = "") -> None:
    """
    Debounced entry point — batches rapid back-to-back messages from the same
    sender into one pipeline call so replies don't multiply (2 msgs → 4-6 bubbles).
    message_guid is passed through for tapback reactions.
    """
    user_key = f"im:{address}"

    async def _run(combined_text: str):
        await run_imessage_pipeline(address, chat_guid, combined_text,
                                    message_guid=message_guid)

    await _debounce(user_key, raw_text, _run, delay=2.0)


async def run_imessage_pipeline(address: str, chat_guid: str, raw_text: str,
                                message_guid: str = ""):
    """
    Full Arnie pipeline for an incoming iMessage.

    address      — sender phone/email, e.g. "+15551234567"
    chat_guid    — BlueBubbles chat GUID, e.g. "iMessage;-;+15551234567"
    raw_text     — message text
    message_guid — BlueBubbles message GUID for tapback reactions (optional)
    """
    im_id = _im_user_id(address)

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, im_id)

        # ── Onboarding flag ───────────────────────────────────────────────────
        in_onboarding = not user.onboarding_completed
        was_onboarding = in_onboarding

        # ── Server-side target interceptor (mirrors Telegram handler) ─────────
        if in_onboarding and is_onboarding_complete(user):
            _prefs = user.preferences
            _targets_done = bool(_prefs and getattr(_prefs, "calorie_target", None) is not None)
            if not _targets_done:
                _txt = raw_text.strip().lower()
                if _txt in ("calculate for me", "calculate", "calculate for me 🧮"):
                    targets = _calc_targets(user)
                    if targets:
                        if _prefs:
                            _prefs.calorie_target = targets["calories"]
                            _prefs.protein_target = targets["protein"]
                        user.onboarding_completed = True
                        await db.commit()
                        user = await reload_user(db, user.id)

                        goal_lbl = targets["goal"]
                        calc_line = (
                            f"TDEE ~{targets['tdee']:,} → {goal_lbl} target: "
                            f"{targets['calories']:,} cal · {targets['protein']}g protein"
                        )
                        prefs = user.preferences
                        welcome = _welcome_message(
                            name=user.name or "",
                            has_targets=bool(prefs and prefs.calorie_target),
                            primary_goal=user.primary_goal,
                            calorie_target=prefs.calorie_target if prefs else None,
                            protein_target=prefs.protein_target if prefs else None,
                        )
                        full_msg = calc_line + "\n\n" + welcome
                        await bb_send_text(chat_guid, _to_plain(full_msg))
                        await log_conversation(db, user.id, raw_text, full_msg, source_type="imessage")
                        return

                elif _txt in ("skip", "skip for now"):
                    user.onboarding_completed = True
                    await db.commit()
                    user = await reload_user(db, user.id)
                    prefs = user.preferences
                    welcome = _welcome_message(
                        name=user.name or "",
                        has_targets=bool(prefs and prefs.calorie_target),
                        primary_goal=user.primary_goal,
                        calorie_target=prefs.calorie_target if prefs else None,
                        protein_target=prefs.protein_target if prefs else None,
                    )
                    await bb_send_text(chat_guid, _to_plain(welcome))
                    await log_conversation(db, user.id, raw_text, welcome, source_type="imessage")
                    return

        # ── Build system prompt + context ─────────────────────────────────────
        if not in_onboarding:
            today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
            context_str = await build_context(user, today_log, db)
            # Platform hint is already baked into the iMessage system prompt
            system = f"{_build_arnie_system(platform='imessage')}\n\n{context_str}"
        else:
            today_log = None
            system = build_onboarding_system(user)
            system += "\n\n[PLATFORM: iMessage — plain text responses only. No HTML. No keyboard buttons — just text options if needed.]"

        # ── Conversation history ───────────────────────────────────────────────
        messages = await _build_messages(db, user.id, raw_text)

        # ── LLM call ──────────────────────────────────────────────────────────
        try:
            result = await chat(messages, system, tools=True, max_tokens=1024)
        except Exception as e:
            logger.error(f"LLM call failed for iMessage user {im_id}: {e}")
            await bb_send_text(chat_guid, "Something went wrong on my end — try again in a moment.")
            return

        response_text = result["text"]
        tool_calls    = result["tool_calls"]
        raw_content   = result["raw_content"]

        # ── Execute tools ─────────────────────────────────────────────────────
        tool_results = {}
        if tool_calls:
            if today_log is None and not in_onboarding:
                today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")

            _log_for_tools = today_log
            if _log_for_tools is None:
                class _FakeLog:
                    id = None
                    total_calories = 0; total_protein = 0; total_carbs = 0
                    total_fats = 0; total_water_ml = 0
                    workout_completed = False; cardio_completed = False
                    food_entries = []; exercise_entries = []
                _log_for_tools = _FakeLog()

            tool_results = await execute_tool_calls(
                tool_calls, user, _log_for_tools, db, "imessage"
            )

            # Handle generated images — send as a text note (can't send photos via BlueBubbles text API)
            for tname, tresult in list(tool_results.items()):
                if isinstance(tresult, dict) and tresult.get("_type") == "image":
                    image_url = tresult.get("url", "")
                    caption = tresult.get("caption", "")
                    tool_results[tname] = (
                        f"Image generated. URL: {image_url}. Caption: {caption}"
                    )
                    if image_url:
                        await bb_send_text(chat_guid, f"Here's your image: {image_url}")

            user = await reload_user(db, user.id)
            if today_log and hasattr(today_log, "id") and today_log.id:
                await db.refresh(today_log)

            # Rebuild system after tools (onboarding state may have changed)
            in_onboarding = not user.onboarding_completed

        # ── Detect onboarding just completed ─────────────────────────────────
        just_completed = was_onboarding and not in_onboarding

        # ── Follow-up after tool calls ────────────────────────────────────────
        if just_completed:
            prefs = user.preferences
            response_text = _welcome_message(
                name=user.name or "",
                has_targets=bool(prefs and prefs.calorie_target),
                primary_goal=user.primary_goal,
                calorie_target=prefs.calorie_target if prefs else None,
                protein_target=prefs.protein_target if prefs else None,
            )
        else:
            need_followup = (tool_calls and raw_content and
                             (in_onboarding or not response_text))
            if need_followup:
                try:
                    response_text = await chat_follow_up(
                        messages, raw_content, tool_calls, tool_results, system, max_tokens=400
                    )
                except Exception as e:
                    logger.error(f"Follow-up LLM failed for {im_id}: {e}")

        if not response_text:
            response_text = "Got it."

        # ── Detect coaching moment (PR, goal, momentum) ───────────────────────
        coaching_moment = {"tapback": None, "effect": None, "bubble_index": 0}
        if not in_onboarding and tool_calls:
            coaching_moment = _detect_coaching_moment(response_text, tool_calls)

        # ── Tapback reaction on the user's incoming message ───────────────────
        if coaching_moment["tapback"] and message_guid:
            asyncio.create_task(
                bb_send_reaction(message_guid, coaching_moment["tapback"])
            )

        # ── Send reply — split on ||| for multi-bubble messaging ─────────────
        bubbles = [b.strip() for b in response_text.split("|||") if b.strip()]
        if not bubbles:
            bubbles = ["Got it."]

        effect = coaching_moment["effect"]
        effect_idx = coaching_moment["bubble_index"]
        # Normalise negative index
        if effect_idx < 0:
            effect_idx = len(bubbles) + effect_idx

        for i, bubble in enumerate(bubbles):
            plain = _to_plain(bubble)
            # Apply iMessage effect to the designated bubble only
            if effect and i == effect_idx:
                await bb_send_text_with_effect(chat_guid, plain, effect)
            else:
                await bb_send_text(chat_guid, plain)
            if i < len(bubbles) - 1:
                await asyncio.sleep(0.6)

        # ── Persist conversation ───────────────────────────────────────────────
        await log_conversation(db, user.id, raw_text, response_text, source_type="imessage")

        # ── Background memory reflection ───────────────────────────────────────
        if not in_onboarding and random.random() < 0.10:
            await maybe_update_memory(user, raw_text, response_text, db)
