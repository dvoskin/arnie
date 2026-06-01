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
from core.context_builder import build_context
from core.platform import Response, React, FX, IMessageAdapter
from handlers.onboarding import build_onboarding_system, is_onboarding_complete

logger = logging.getLogger(__name__)

from bot.message_debounce import schedule_message as _debounce
from multimodal.audio import transcribe_audio_message

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


async def bb_send_reaction(chat_guid: str, message_guid: str, reaction: str,
                           message_text: str = "") -> bool:
    """
    React to a message with a tapback via the BlueBubbles Private API.
    POST /api/v1/message/react
    Body: {chatGuid, selectedMessageGuid, reaction, partIndex} — reaction is a string:
          "love" | "like" | "dislike" | "laugh" | "emphasize" | "question"
    Requires Private API enabled (SIP disabled). Verbose logging so failures are
    diagnosable from Render logs.
    """
    if not _BB_URL or not _BB_PASSWORD or not message_guid or not chat_guid:
        logger.warning(f"reaction skipped — missing field (guid={bool(message_guid)} chat={bool(chat_guid)})")
        return False
    payload = {
        "chatGuid": chat_guid,
        "selectedMessageGuid": message_guid,
        "reaction": reaction,
        "partIndex": 0,
    }
    try:
        resp = await _get_http().post(
            f"{_BB_URL}/api/v1/message/react",
            params={"password": _BB_PASSWORD},
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201):
            logger.warning(
                f"REACTION FAILED [{resp.status_code}] reaction='{reaction}' "
                f"guid={message_guid[:12]} body={resp.text[:300]}"
            )
            return False
        logger.info(f"REACTION OK '{reaction}' on {message_guid[:12]}")
        return True
    except Exception as e:
        logger.warning(f"REACTION ERROR '{reaction}': {e}")
        return False


async def bb_set_typing(chat_guid: str, typing: bool) -> bool:
    """
    Show/hide the 'Arnie is typing…' indicator in the iMessage thread.
    POST   /api/v1/chat/{guid}/typing  → start
    DELETE /api/v1/chat/{guid}/typing  → stop
    Requires Private API. Best-effort — never blocks the pipeline.
    """
    if not _BB_URL or not _BB_PASSWORD or not chat_guid:
        return False
    import urllib.parse
    guid_enc = urllib.parse.quote(chat_guid, safe="")
    try:
        method = "POST" if typing else "DELETE"
        resp = await _get_http().request(
            method,
            f"{_BB_URL}/api/v1/chat/{guid_enc}/typing",
            params={"password": _BB_PASSWORD},
        )
        if resp.status_code not in (200, 201):
            logger.info(f"typing {'on' if typing else 'off'} → {resp.status_code} {resp.text[:120]}")
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.warning(f"typing indicator error: {e}")
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


async def bb_download_attachment(attachment_guid: str) -> Optional[bytes]:
    """
    Download an attachment's raw bytes from BlueBubbles.
    GET /api/v1/attachment/{guid}/download?password=…
    Returns the bytes, or None if not configured / the fetch fails. Used to pull
    iMessage voice-note audio for transcription. Larger timeout than the default
    client since audio can be a few MB.
    """
    if not _BB_URL or not _BB_PASSWORD or not attachment_guid:
        logger.warning("attachment download skipped — BB not configured or no guid")
        return None
    try:
        resp = await _get_http().get(
            f"{_BB_URL}/api/v1/attachment/{attachment_guid}/download",
            params={"password": _BB_PASSWORD},
            timeout=30.0,
        )
        if resp.status_code != 200:
            logger.warning(
                f"attachment download failed [{resp.status_code}] "
                f"guid={attachment_guid[:12]} body={resp.text[:200]}"
            )
            return None
        data = resp.content
        logger.info(f"attachment downloaded: guid={attachment_guid[:12]} bytes={len(data)}")
        return data
    except Exception as e:
        logger.error(f"attachment download error guid={attachment_guid[:12]}: {e}")
        return None


# Audio file extensions an iMessage voice note might arrive as (we transcode
# whatever it is, so this is just for detection, not a hard accept-list).
_AUDIO_EXTS = (".caf", ".m4a", ".amr", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".aiff")


def extract_audio_attachment(data: dict) -> Optional[dict]:
    """
    Find a voice-note / audio attachment in a BlueBubbles 'new-message' payload.
    Returns {'guid', 'transfer_name', 'mime'} for the first audio attachment, or
    None. Detection is permissive — mimeType 'audio/*', an audio file extension,
    or an audio UTI all count (BlueBubbles is inconsistent across iOS versions).
    Pure function (no IO) so it's unit-testable and keeps the webhook thin.
    """
    attachments = data.get("attachments") or []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        guid = att.get("guid")
        if not guid:
            continue
        mime = (att.get("mimeType") or "").lower()
        uti = (att.get("uti") or "").lower()
        name = att.get("transferName") or att.get("originalROWID") or ""
        name_l = str(name).lower()
        is_audio = (
            mime.startswith("audio/")
            or name_l.endswith(_AUDIO_EXTS)
            or "audio" in uti
            or uti == "com.apple.coreaudio-format"
        )
        if is_audio:
            return {
                "guid": guid,
                "transfer_name": str(name) or "audio.caf",
                "mime": mime,
            }
    return None


# Reaction/effect detection now lives in core.platform.detect_moment (shared
# across both platforms). See imports above.


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
    "just texted", "just gave", "already gave", "i did already", "i just said",
    "look up", "read up", "i literally just", "told you already",
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
from bot.telegram_handler import _calc_targets


# ── Natural language command detection ────────────────────────────────────────
# iMessage has no slash commands — these patterns catch intent from plain text

_RESET_PATTERNS = {
    "reset my data", "reset everything", "delete my data", "delete everything",
    "start over", "start fresh", "wipe my data", "clear my data",
    "reset all", "delete my account", "remove my data",
}

# Users who have been asked to confirm a reset. In-memory only, so it doesn't
# survive a redeploy — that's why the explicit "reset confirm" phrase is accepted
# without requiring a pending flag (see the confirmation handler).
_pending_resets: set[str] = set()

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

_LINK_PATTERNS = {
    "link my telegram", "connect my telegram", "link telegram", "add telegram",
    "link my other device", "connect my devices", "link my account",
    "use on telegram", "sync my accounts", "link accounts",
}


def _match_intent(text: str, patterns: set) -> bool:
    t = text.strip().lower()
    return any(p in t for p in patterns)


def _is_reset_confirmation(text: str, pending: bool) -> bool:
    """
    True if `text` confirms a full account wipe. Case-INSENSITIVE because iOS
    auto-capitalizes — users type "Reset confirm", not the literal "RESET confirm",
    and the old exact-match check silently failed (the message fell through to the
    LLM, which faked a reset while all data survived).

    The explicit two-word phrase always counts (so it works even after a redeploy
    drops the in-memory pending flag). A bare "confirm"/"yes" counts only when a
    reset is actually pending, so a stray "yes" can't trigger a surprise wipe.
    """
    norm = text.strip().lower().rstrip(" .!")
    if norm in ("reset confirm", "confirm reset"):
        return True
    return pending and norm in ("confirm", "yes")


async def _handle_im_reset(chat_guid: str, user, db) -> bool:
    """Full account wipe — returns True so pipeline skips normal processing."""
    from db.queries import reset_all_user_data
    from memory.memory_manager import write_memory
    telegram_id = user.telegram_id  # save before reset — object goes stale after commit
    user_id = user.id
    await reset_all_user_data(db, user_id)
    await db.commit()
    await write_memory(telegram_id, "")  # clear legacy memory file
    try:
        from memory.profile_manager import clear_profile
        await clear_profile(telegram_id)  # wipe the Profile Matrix too
    except Exception as e:
        logger.warning(f"clear_profile failed for {telegram_id}: {e}")
    # Don't log a conversation — keeps history empty so the next message
    # re-triggers the full first-contact intro sequence.
    bubbles = [
        "done. everything's wiped.",
        "fresh start 🌱",
        "hit me back when you're ready and we'll get going.",
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
    msg = f"Check-ins are {status}." if enable else f"Got it, no more check-ins."
    await bb_send_text(chat_guid, msg)
    return True


async def _handle_im_dashboard(chat_guid: str, user, db) -> bool:
    from db.queries import get_or_create_webhook_token
    from core.blurbs import dashboard_line
    import os
    token = await get_or_create_webhook_token(db, user.id)
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://arnie.onrender.com").rstrip("/")
    url = f"{base_url}/dashboard/{token}"
    line = await dashboard_line(user.name or "")
    await bb_send_text(chat_guid, line)
    await asyncio.sleep(0.35)
    await bb_send_text(chat_guid, url)  # link in its own bubble — easy to tap
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

# Shared canonical intro (same on Telegram) — one consistent Arnie across channels.
from core.prompts.onboarding import INTRO_BUBBLES as _INTRO_BUBBLES


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


# ── Landing-page outreach (user enters phone → Arnie texts first) ──────────────

# Landing-page outreach variant of the canonical intro: same science-based + memory
# positioning, but opens by acknowledging they signed up and closes on "2 min to get
# going". Each element is sent as ITS OWN SMS; newlines stay within that single
# message (not split into separate bubbles). First bubble is short so the iMessage
# screen effect punches on the greeting, not the whole paragraph. 4 messages.
_OUTREACH_INTRO = [
    # Message 1 — short; gets the iMessage screen effect (first bubble only)
    "Hey, I'm Arnie ☺️",
    # Message 2
    "You signed up on the site, so let's get you going."
    "\n\n"
    "I'm your science-based coach for food, training, and progress.",
    # Message 3
    "Text me meals, workouts, weight, goals, or anything you want me to know."
    "\n\n"
    "I'll help you log it, learn from it, and coach you better every day. No apps, no forms, no starting over.",
    # Message 4
    "I remember your goals, habits, progress, and what works for you."
    "\n\n"
    "Takes 2 min to get going. What should I call you?",
]


def _normalize_phone(raw: str) -> str | None:
    """Normalize a phone string to E.164. Defaults to US (+1) for 10-digit input."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if digits.startswith("+"):
        rest = re.sub(r"\D", "", digits[1:])
        return f"+{rest}" if 10 <= len(rest) <= 15 else None
    digits = re.sub(r"\D", "", digits)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


async def bb_imessage_available(address: str) -> bool | None:
    """
    Check if a number/address is reachable via iMessage (BlueBubbles).
    Returns True/False, or None if the check itself couldn't run (then proceed anyway).
    """
    if not _BB_URL or not _BB_PASSWORD:
        return None
    try:
        resp = await _get_http().get(
            f"{_BB_URL}/api/v1/handle/availability/imessage",
            params={"password": _BB_PASSWORD, "address": address},
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return bool(data.get("available"))
        return None
    except Exception as e:
        logger.warning(f"iMessage availability check failed: {e}")
        return None


async def start_imessage_outreach(raw_phone: str) -> dict:
    """
    Landing-page entry point. Validates the number, checks it's iMessage-capable,
    and sends Arnie's first outreach (ONCE). Their reply flows into onboarding.
    Returns {ok: bool, reason: str}.
    """
    phone = _normalize_phone(raw_phone)
    if not phone:
        return {"ok": False, "reason": "invalid_number"}

    im_id = _im_user_id(phone)
    chat_guid = f"iMessage;-;{phone}"

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, im_id)

        # Dedupe — never outreach the same number twice
        prior = await get_recent_conversations(db, user.id, limit=1)
        if prior or user.name or user.onboarding_completed:
            return {"ok": False, "reason": "already_started"}

        # Availability check — don't blast a non-iMessage number (SMS/ban risk)
        available = await bb_imessage_available(phone)
        if available is False:
            return {"ok": False, "reason": "not_imessage"}

        # Send the one-time outreach intro
        for i, bubble in enumerate(_OUTREACH_INTRO):
            if i == 0:
                await bb_send_text_with_effect(chat_guid, bubble, Effect.LOUD)
            else:
                await bb_send_text(chat_guid, bubble)
            if i < len(_OUTREACH_INTRO) - 1:
                await asyncio.sleep(0.4)

        # Log actual outreach text so the LLM has full context when the user replies
        await log_conversation(db, user.id, "[landing signup]",
                               "|||".join(_OUTREACH_INTRO), source_type="imessage")
        logger.info(f"iMessage outreach sent to {phone}")
        return {"ok": True, "reason": "sent"}


async def _dashboard_url(user, db) -> str:
    """Build the user's dashboard URL."""
    token = await get_or_create_webhook_token(db, user.id)
    base = os.getenv("RENDER_EXTERNAL_URL", "https://arnie.onrender.com").rstrip("/")
    return f"{base}/dashboard/{token}"


async def _complete_im_onboarding(chat_guid, user, db, raw_text, message_guid,
                                  lead: str = "") -> None:
    """
    Single completion path for ALL onboarding exits (calculate / skip / LLM tool).
    Sends the celebratory welcome + dashboard via the adapter so every user gets
    the same polished ending. lead = optional bubble(s) prepended (e.g. calc result).
    """
    dash_url = await _dashboard_url(user, db)
    body = await _build_completion_text(user, db, dash_url)
    full = f"{lead}|||{body}" if lead else body
    resp = Response.from_text(full)
    resp.effect = FX.CELEBRATE
    resp.effect_idx = 0
    resp.reaction = React.LOVE
    await IMessageAdapter(chat_guid, reply_to_guid=message_guid).send(resp)
    await log_conversation(db, user.id, raw_text, full, source_type="imessage")


async def _build_completion_text(user, db) -> str:
    """
    iMessage onboarding welcome — short and warm. 3 bubbles, no goal label,
    no targets line, no dashboard (the dashboard is sent after their first log).
    """
    name = user.name or ""
    return (
        f"You're in, {name}. 🎉|||"
        f"Just text me whatever you eat or train and I'll handle the rest.|||"
        f"What've you had today? Let's start there."
    )


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


async def handle_imessage_audio(address: str, chat_guid: str, attachment_guid: str,
                                message_guid: str = "",
                                transfer_name: str = "audio.caf") -> None:
    """
    Voice-note entry point: download the audio attachment, transcribe it, echo the
    transcript back (parity with Telegram), then run the normal pipeline on the
    transcript text. Serialized on the same per-user lock as text so a voice note
    and a text can't double-process. No debounce — voice notes arrive singly.
    """
    user_key = f"im:{address}"
    if user_key not in _user_pipeline_locks:
        _user_pipeline_locks[user_key] = asyncio.Lock()
    lock = _user_pipeline_locks[user_key]

    async with lock:
        await bb_set_typing(chat_guid, True)
        try:
            audio = await bb_download_attachment(attachment_guid)
            transcript = ""
            if audio:
                transcript = await transcribe_audio_message(audio, transfer_name)
        except Exception as e:
            logger.error(f"Voice-note handling failed for {address}: {e}")
            transcript = ""
        finally:
            await bb_set_typing(chat_guid, False)

        if not transcript:
            # Don't leave the user hanging — tell them why nothing happened.
            await bb_send_text(
                chat_guid,
                "I couldn't make out that voice note. Mind sending it as text?",
            )
            return

        # Process it like any other message — no transcript echo. Arnie just coaches
        # on what was said (a human coach doesn't parrot you back). Same lock so a
        # concurrent text can't interleave.
        await run_imessage_pipeline(address, chat_guid, transcript,
                                    message_guid=message_guid)


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
        channel_user = await get_or_create_user(db, im_id)

        # ── Cross-platform linking (gated by LINKING_ENABLED) ─────────────────
        from db.queries import linking_enabled, consume_link_code, generate_link_code
        if linking_enabled():
            # Consuming a code (sent via the pre-filled deep link from Telegram)
            if re.match(r"^\s*LINK-[A-Z0-9]{4,6}\s*$", raw_text.strip().upper()):
                canonical = await consume_link_code(db, raw_text.strip(), channel_user)
                if canonical:
                    nm = canonical.name or "there"
                    # They linked from iMessage → default reminders to iMessage,
                    # but let them switch to Telegram.
                    if not canonical.channel_preference:
                        canonical.channel_preference = "imessage"
                        await db.commit()
                    await bb_send_text(chat_guid, f"linked. 🔗")
                    await asyncio.sleep(0.3)
                    await bb_send_text(chat_guid, f"this is the same account as your other device now, {nm}. everything's in sync.")
                    await asyncio.sleep(0.3)
                    await bb_send_text(chat_guid, "quick one — where do you want my check-ins? i'll only send on one so you're not double-pinged.")
                    await asyncio.sleep(0.3)
                    await bb_send_text(chat_guid, "reply 'imessage' or 'telegram' (imessage for now).")
                else:
                    await bb_send_text(chat_guid, "that link code's expired or invalid — generate a fresh one and try again.")
                return
            # Requesting a link from iMessage → hand them a tap link to Telegram
            if _match_intent(raw_text, _LINK_PATTERNS):
                code = await generate_link_code(db, channel_user)
                bot = os.getenv("TELEGRAM_BOT_USERNAME", "Arnie_1026_Bot")
                await bb_send_text(chat_guid, "to connect your telegram, tap this on your phone:")
                await asyncio.sleep(0.3)
                await bb_send_text(chat_guid, f"https://t.me/{bot}?start={code}")
                await asyncio.sleep(0.3)
                await bb_send_text(chat_guid, "it links automatically. (expires in 10 min)")
                return

        # Resolve to the canonical account (follows a link if one exists)
        user = channel_user
        if linking_enabled() and channel_user.linked_to_user_id:
            user = await reload_user(db, channel_user.linked_to_user_id) or channel_user

        # ── Natural language command handling (iMessage has no slash commands) ──

        # Confirmed reset (case-insensitive — see _is_reset_confirmation).
        if _is_reset_confirmation(raw_text, im_id in _pending_resets):
            _pending_resets.discard(im_id)
            await _handle_im_reset(chat_guid, user, db)
            return
        # Pending but this message isn't a confirmation → cancel it, so a stray "yes"
        # later can't trigger a surprise wipe. Falls through to normal processing.
        _pending_resets.discard(im_id)

        # Reset intent detected — ask for confirmation first
        if _match_intent(raw_text, _RESET_PATTERNS):
            _pending_resets.add(im_id)
            await bb_send_text(chat_guid, "just to confirm — this wipes everything.")
            await asyncio.sleep(0.35)
            await bb_send_text(chat_guid, 'reply "confirm" to wipe everything (anything else cancels).')
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
                # Log the actual intro text so the LLM has full context when
                # the user replies (knows Arnie asked "First, what should I call you?")
                await log_conversation(
                    db, user.id, raw_text,
                    "|||".join(_INTRO_BUBBLES), source_type="imessage"
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
                        await _complete_im_onboarding(
                            chat_guid, user, db, raw_text, message_guid,
                            lead=f"ran the math 🧮|||~{targets['tdee']:,} tdee, so we're going "
                                 f"{targets['calories']:,} cal a day for the {targets['goal']}.",
                        )
                        return

                elif _txt in ("skip", "skip for now"):
                    user.onboarding_completed = True
                    await db.commit()
                    user = await reload_user(db, user.id)
                    await _complete_im_onboarding(
                        chat_guid, user, db, raw_text, message_guid,
                        lead="no targets for now, that's fine.|||we'll dial them in once i "
                             "see how you actually eat.",
                    )
                    return

        # ── Build system prompt + context ─────────────────────────────────────
        if not in_onboarding:
            today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
            context_str = await build_context(user, today_log, db, platform="imessage")
            # Platform hint is already baked into the iMessage system prompt
            system = f"{_build_arnie_system(platform='imessage')}\n\n{context_str}"
        else:
            today_log = None
            system = build_onboarding_system(user)

        # ── Conversation history ───────────────────────────────────────────────
        # During onboarding, ALWAYS load full history — users often give stats
        # across several rapid texts, and the LLM must see all of them to extract.
        messages = await _build_messages(
            db, user.id, raw_text,
            extended=(in_onboarding or _needs_extended_history(raw_text))
        )

        # ── Show "Arnie is typing…" while we think ────────────────────────────
        await bb_set_typing(chat_guid, True)

        # ── iMessage image callback: send as text URL (no photo upload support) ─
        async def _on_image(url: str, caption: str) -> None:
            if url:
                await bb_send_text(chat_guid, f"Here's your image: {url}")

        # ── Delegate to shared pipeline core ──────────────────────────────────
        from core.conversation import run_turn
        turn = await run_turn(
            user, db, messages, system, platform="imessage",
            in_onboarding=in_onboarding, was_onboarding=was_onboarding,
            today_log=today_log, source_type="imessage", on_image=_on_image,
        )

        # ── Stop typing, then send via the iMessage adapter ───────────────────
        await bb_set_typing(chat_guid, False)
        adapter = IMessageAdapter(chat_guid, reply_to_guid=message_guid)
        await adapter.send(turn.response)

        # ── Persist conversation ──────────────────────────────────────────────
        log_text = "|||".join(turn.response.bubbles)
        await log_conversation(db, user.id, raw_text, log_text, source_type="imessage")

        # ── Adaptive profile refresh (throttled internally to ~3h) ────────────
        if not turn.in_onboarding:
            try:
                from memory.profile_updater import maybe_update_profile
                await maybe_update_profile(turn.user, db)
            except Exception as e:
                logger.error(f"Profile update error for {im_id}: {e}")
