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

# Import the system prompt and helpers from the Telegram handler so we share
# the exact same coaching logic — no duplication.
from bot.telegram_handler import _ARNIE_SYSTEM, _welcome_message, _calc_targets


async def run_imessage_pipeline(address: str, chat_guid: str, raw_text: str):
    """
    Full Arnie pipeline for an incoming iMessage.

    address   — sender phone/email, e.g. "+15551234567"
    chat_guid — BlueBubbles chat GUID, e.g. "iMessage;-;+15551234567"
    raw_text  — message text
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
            # Inject iMessage context hint so LLM knows no HTML/markdown
            im_hint = "\n\n[PLATFORM: iMessage — plain text only. No HTML tags, no markdown, no emoji-heavy formatting.]"
            system = f"{_ARNIE_SYSTEM}\n\n{context_str}{im_hint}"
        else:
            today_log = None
            system = build_onboarding_system(user)
            # Append iMessage note to onboarding too
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

        # ── Send reply ────────────────────────────────────────────────────────
        plain = _to_plain(response_text)
        await bb_send_text(chat_guid, plain)

        # ── Persist conversation ───────────────────────────────────────────────
        await log_conversation(db, user.id, raw_text, response_text, source_type="imessage")

        # ── Background memory reflection ───────────────────────────────────────
        if not in_onboarding and random.random() < 0.10:
            await maybe_update_memory(user, raw_text, response_text, db)
