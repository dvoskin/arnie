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

_REFERENCE_PATTERNS = {
    "i just sent", "i already told", "i mentioned", "i said that", "i told you",
    "check what i sent", "i already said", "scroll up", "i sent you", "see what i",
    "i just told", "already sent", "i sent that", "look at what i", "i wrote that",
}

def _needs_extended_history(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _REFERENCE_PATTERNS)

async def _build_messages(db, user_id: int, current_text: str,
                          extended: bool = False) -> list:
    """Build conversation history + current message for the LLM.
    If extended=True, loads 25 messages so Arnie can find what was referenced."""
    limit = 25 if extended else 6
    recent = await get_recent_conversations(db, user_id, limit=limit)
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


# ── Natural language command detection ────────────────────────────────────────
# iMessage has no slash commands — these patterns catch intent from plain text

_RESET_PATTERNS = {
    "reset my data", "reset everything", "delete my data", "delete everything",
    "start over", "start fresh", "wipe my data", "clear my data",
    "reset all", "delete my account", "remove my data",
}

_REMIND_ON_PATTERNS = {
    "turn on reminders", "enable reminders", "turn on check-ins",
    "enable check-ins", "start check-ins", "send me reminders",
    "i want reminders", "turn notifications on",
}

_REMIND_OFF_PATTERNS = {
    "turn off reminders", "disable reminders", "turn off check-ins",
    "stop reminders", "no more check-ins", "stop check-ins",
    "no more reminders", "turn notifications off", "stop messaging me",
}

_DASH_PATTERNS = {
    "show my dashboard", "open dashboard", "my dashboard",
    "show dashboard", "view dashboard", "my stats",
}

_WHOOP_PATTERNS = {
    "connect my whoop", "connect whoop", "link whoop", "setup whoop",
    "whoop integration", "add whoop",
}


def _match_intent(text: str, patterns: set) -> bool:
    t = text.strip().lower()
    return any(p in t for p in patterns)


async def _handle_im_reset(chat_guid: str, user, db) -> bool:
    """Full account wipe — returns True so pipeline skips normal processing."""
    from db.queries import reset_all_user_data
    from memory.memory_manager import write_memory
    telegram_id = user.telegram_id  # save before reset — object goes stale after commit
    user_id = user.id
    await reset_all_user_data(db, user_id)
    await db.commit()
    await write_memory(telegram_id, "")  # clear memory file
    bubbles = [
        "done. everything's wiped.",
        "fresh start.",
        "what's your first name?",
    ]
    for i, b in enumerate(bubbles):
        await bb_send_text(chat_guid, b)
        if i < len(bubbles) - 1:
            await asyncio.sleep(0.35)
    return True


async def _handle_im_remind_toggle(chat_guid: str, user, db, enable: bool) -> bool:
    prefs = user.preferences
    if prefs:
        prefs.proactive_messaging_enabled = enable
        await db.commit()
    status = "on" if enable else "off"
    msg = f"check-ins are {status}." if enable else f"got it. no more check-ins."
    await bb_send_text(chat_guid, msg)
    return True


async def _handle_im_dashboard(chat_guid: str, user, db) -> bool:
    from db.queries import get_or_create_webhook_token
    import os
    token = await get_or_create_webhook_token(db, user.id)
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://arnie.onrender.com").rstrip("/")
    url = f"{base_url}/dashboard/{token}"
    await bb_send_text(chat_guid, f"your dashboard: {url}")
    return True


async def _handle_im_whoop(chat_guid: str, user, db) -> bool:
    from db.queries import get_or_create_webhook_token
    import os
    token = await get_or_create_webhook_token(db, user.id)
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://arnie.onrender.com").rstrip("/")
    auth_url = f"{base_url}/whoop/callback?state={token}"
    # Generate the actual Whoop auth URL
    from api.whoop import AUTH_URL, WHOOP_CLIENT_ID
    redirect = f"{base_url}/whoop/callback"
    whoop_url = (
        f"{AUTH_URL}?client_id={WHOOP_CLIENT_ID}"
        f"&redirect_uri={redirect}"
        f"&response_type=code&scope=read:recovery read:sleep read:workout read:profile"
        f"&state={token}"
    )
    await bb_send_text(chat_guid, "tap this link on your phone to connect Whoop:")
    await asyncio.sleep(0.3)
    await bb_send_text(chat_guid, whoop_url)
    return True

# ── First-contact intro ────────────────────────────────────────────────────────

_INTRO_BUBBLES = [
    "hey 👋",
    "i'm arnie.",
    "your AI fitness and nutrition coach. no app, no spreadsheets, just texts.",
    "i track what you eat, how you train, and how your body's responding.",
    "let's get you set up. takes 2 minutes.",
    "what's your first name?",
]


async def _send_first_contact_intro(chat_guid: str) -> None:
    """
    Send Arnie's intro sequence to a brand new iMessage user.
    Rapid-fire bubbles — feels like a real person introducing themselves.
    """
    for i, bubble in enumerate(_INTRO_BUBBLES):
        if i == 0:
            # First bubble gets a Loud effect — makes an entrance
            await bb_send_text_with_effect(chat_guid, bubble, Effect.LOUD)
        else:
            await bb_send_text(chat_guid, bubble)
        if i < len(_INTRO_BUBBLES) - 1:
            await asyncio.sleep(0.4)


async def _send_onboarding_reaction(message_guid: str, field_updated: str) -> None:
    """Fire a tapback reaction based on what the user just told us during onboarding."""
    if not message_guid:
        return
    reactions = {
        "name":                Tapback.LOVE,    # ❤️ when they give their name
        "current_weight_kg":   Tapback.LIKE,    # 👍 height/weight
        "primary_goal":        Tapback.LIKE,    # 👍 goal
        "training_experience": Tapback.LIKE,    # 👍 experience
        "calorie_target":      Tapback.LOVE,    # ❤️ targets set — big moment
    }
    tapback = reactions.get(field_updated)
    if tapback:
        await bb_send_reaction(message_guid, tapback)


# Per-user async locks — prevents two pipelines running simultaneously for the
# same user (fixes duplicate question bug when two webhooks arrive before first DB commit)
_user_pipeline_locks: dict[str, asyncio.Lock] = {}


async def handle_imessage(address: str, chat_guid: str, raw_text: str,
                          message_guid: str = "") -> None:
    """
    Debounced entry point — batches rapid back-to-back messages from the same
    sender into one pipeline call so replies don't multiply.
    Per-user lock ensures only one pipeline runs at a time per user.
    """
    user_key = f"im:{address}"

    if user_key not in _user_pipeline_locks:
        _user_pipeline_locks[user_key] = asyncio.Lock()
    lock = _user_pipeline_locks[user_key]

    async def _run(combined_text: str):
        async with lock:
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

        # ── Natural language command handling (iMessage has no slash commands) ──
        # Reset works at any point — including mid-onboarding
        if _match_intent(raw_text, _RESET_PATTERNS):
            await _handle_im_reset(chat_guid, user, db)
            return

        if user.onboarding_completed:
            if _match_intent(raw_text, _REMIND_ON_PATTERNS):
                await _handle_im_remind_toggle(chat_guid, user, db, enable=True)
                return
            if _match_intent(raw_text, _REMIND_OFF_PATTERNS):
                await _handle_im_remind_toggle(chat_guid, user, db, enable=False)
                return
            if _match_intent(raw_text, _DASH_PATTERNS):
                await _handle_im_dashboard(chat_guid, user, db)
                return
            if _match_intent(raw_text, _WHOOP_PATTERNS):
                await _handle_im_whoop(chat_guid, user, db)
                return

        # ── First-ever contact — send intro before onboarding starts ──────────
        # Detect: no name yet + no prior conversations = truly new user
        if not user.name and not user.onboarding_completed:
            prior = await get_recent_conversations(db, user.id, limit=1)
            if not prior:
                await _send_first_contact_intro(chat_guid)
                # Log this as the first conversation so intro doesn't re-fire
                await log_conversation(
                    db, user.id, raw_text,
                    "[intro sent]", source_type="imessage"
                )
                return  # Wait for user to reply with their name

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
            system += """

[iMessage — plain text only. No HTML tags. No bold. No buttons.]

MESSAGING STYLE — this is non-negotiable:
split every response into separate bubbles using ||| between them.
each bubble = one short sentence. sometimes a fragment. like rapid texts.
vary where emojis land — not always at the end, not always first bubble, sometimes none.
make it feel like a real person is typing, not a system running a script.
lowercase always. no em dashes. no corporate language.
capitalize their name every time you use it."""

        # ── Conversation history ───────────────────────────────────────────────
        messages = await _build_messages(
            db, user.id, raw_text,
            extended=_needs_extended_history(raw_text)
        )

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

            # ── Onboarding tapback reactions ──────────────────────────────────
            if was_onboarding and message_guid:
                for tc in tool_calls:
                    if tc["name"] == "update_profile":
                        fields = tc.get("input", {}).get("fields", {})
                        # height_cm also triggers the weight tapback
                        check_fields = ("name", "current_weight_kg", "height_cm",
                                        "primary_goal", "training_experience", "calorie_target")
                        for field in check_fields:
                            if field in fields:
                                react_field = "current_weight_kg" if field == "height_cm" else field
                                asyncio.create_task(
                                    _send_onboarding_reaction(message_guid, react_field)
                                )
                                break  # one tapback per message

            # Rebuild system after tools (onboarding state may have changed)
            in_onboarding = not user.onboarding_completed

        # ── Detect onboarding just completed ─────────────────────────────────
        just_completed = was_onboarding and not in_onboarding

        # ── Follow-up after tool calls ────────────────────────────────────────
        if just_completed:
            prefs = user.preferences
            name = user.name or ""
            goal = user.primary_goal or ""
            cal = prefs.calorie_target if prefs else None
            pro = prefs.protein_target if prefs else None
            # iMessage-native welcome — no HTML, casual tone
            goal_line = {"cut": "goal: cut 🔻", "bulk": "goal: bulk 📈",
                         "maintain": "goal: maintain ⚖️", "performance": "goal: performance ⚡",
                         "health": "goal: health 🌿"}.get(goal, f"goal: {goal}")
            if cal and pro:
                targets_line = f"targets: {cal} cal · {pro}g protein"
            else:
                targets_line = "targets: not set yet — say \"set my targets\" when ready"
            response_text = (
                f"you're in, {name}. 🎉|||"
                f"{goal_line}|||"
                f"{targets_line}|||"
                f"just text me like you'd text a friend. food, workouts, weight — all of it.|||"
                f"what did you eat today?"
            )
        else:
            logging_tools = {"log_food", "log_exercise", "update_food_entry",
                             "delete_food_entry", "update_exercise_entry"}
            has_logging = any(tc["name"] in logging_tools for tc in tool_calls)
            need_followup = (tool_calls and raw_content and
                             (in_onboarding or not response_text or has_logging))
            if need_followup:
                try:
                    response_text = await chat_follow_up(
                        messages, raw_content, tool_calls, tool_results, system, max_tokens=400
                    )
                except Exception as e:
                    logger.error(f"Follow-up LLM failed for {im_id}: {e}")

        if not response_text:
            if tool_calls and raw_content:
                try:
                    response_text = await chat_follow_up(
                        messages, raw_content, tool_calls, tool_results, system, max_tokens=300
                    )
                except Exception:
                    pass
            if not response_text:
                response_text = "done."

        # ── Onboarding completion — fire Balloons 🎉 ─────────────────────────
        if just_completed:
            coaching_moment = {"tapback": None, "effect": Effect.BALLOONS, "bubble_index": -1}
        else:
            coaching_moment = {"tapback": None, "effect": None, "bubble_index": 0}
            if not in_onboarding and tool_calls:
                coaching_moment = _detect_coaching_moment(response_text, tool_calls)

        # ── Tapback reaction on the user's incoming message ───────────────────
        if coaching_moment["tapback"] and message_guid:
            logger.info(f"Sending tapback {coaching_moment['tapback']} + effect {coaching_moment['effect']} to {message_guid[:8]}...")
            asyncio.create_task(
                bb_send_reaction(message_guid, coaching_moment["tapback"])
            )

        # ── Send reply — split on ||| for multi-bubble messaging ─────────────
        bubbles = [b.strip() for b in response_text.split("|||") if b.strip()]
        if not bubbles:
            bubbles = ["done."]

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
                await asyncio.sleep(0.35)  # fast enough to feel like rapid texting

        # ── Persist conversation ───────────────────────────────────────────────
        await log_conversation(db, user.id, raw_text, response_text, source_type="imessage")

        # ── Background memory reflection ───────────────────────────────────────
        if not in_onboarding and random.random() < 0.10:
            await maybe_update_memory(user, raw_text, response_text, db)
