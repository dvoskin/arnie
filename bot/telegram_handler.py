"""
Telegram bot — receives all updates, orchestrates the full pipeline:
  multimodal parsing → context build → LLM → tool execution → response → memory
"""
import asyncio
import logging
import os
import time
import random

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, Defaults, filters,
)

from db.database import AsyncSessionLocal, init_db
from db.queries import (
    get_or_create_user, resolve_user, get_or_create_today_log, get_today_log,
    get_recent_conversations, log_conversation,
    reload_user, get_or_create_webhook_token,
    add_feedback, get_recent_logs,
)
from core.reset import reset_today as _reset_today, reset_all as _reset_all
from core.context_builder import build_context, fmt_log
from core.platform import React
from handlers.onboarding import (
    build_onboarding_system, get_onboarding_keyboard, is_onboarding_complete,
)
from memory.reflection import maybe_update_memory
from multimodal.voice_handler import process_voice
from multimodal.image_handler import process_general_image
from scheduler.proactive_scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Pending location-gated requests. When a "what's near me" turn fires
# find_nearby_places with no location on file, we stash the user's original text
# here keyed by tg user id. The moment they tap "share location", handle_location
# pops it and finishes the original request automatically — so the share itself
# completes the flow, no re-typing. TTL-bounded so a stale tap doesn't replay an
# hour-old request.
_LOCATION_PENDING: dict[str, tuple[str, float]] = {}
_LOCATION_PENDING_TTL = 600  # seconds

# Deterministic "near me" intent — a safety net so the share button shows even when
# the model talks about location WITHOUT actually calling find_nearby_places (models
# don't always emit the tool call). Multilingual: EN / RU / UA near-me phrasings.
import re as _re
_LOCATION_INTENT_RE = _re.compile(
    r"near\s*me|nearby|near\s*by|around\s*me|close\s*to\s*me|closest"
    r"|возле\s*меня|около\s*меня|рядом|рядом\s*со\s*мной|поблизост|вокруг\s*меня|недалеко|ближайш|поделиться\s*локац"
    r"|біля\s*мене|поряд|поблизу|навколо\s*мене|найближч",
    _re.IGNORECASE | _re.UNICODE,
)


def _looks_like_location_request(text: str) -> bool:
    return bool(text and _LOCATION_INTENT_RE.search(text))

# Semantic reaction → Telegram emoji (Bot API 7.0+; best-effort)
_TG_REACTION_EMOJI = {
    React.LOVE: "❤️", React.LIKE: "👍", React.LAUGH: "😂", React.EMPHASIZE: "🔥",
}

async def _tg_react(bot, chat_id: int, message_id: int, semantic: str) -> None:
    """Apply a Telegram message reaction. No-ops on older API versions."""
    emoji = _TG_REACTION_EMOJI.get(semantic)
    if not emoji:
        return
    try:
        from telegram import ReactionTypeEmoji
        await bot.set_message_reaction(
            chat_id=chat_id, message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass  # older python-telegram-bot or not permitted — skip


def _fmt(text: str) -> dict:
    """
    Prepare LLM output for Telegram HTML mode.
    1. Strip markdown noise (headers, tables, rules)
    2. Convert **bold** → <b>bold</b>
    3. HTML-escape all plain text while leaving <b>/<i> tags intact
    Always returns parse_mode="HTML" explicitly — don't rely on Defaults alone.
    """
    import re
    import html as _html

    # Strip markdown headers, rules, tables
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^-{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\|.+\|$\n?', '', text, flags=re.MULTILINE)
    # Convert **bold** to <b>bold</b> before escaping
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    # Convert * bullets
    text = re.sub(r'^\* ', '• ', text, flags=re.MULTILINE)
    # Collapse 3+ blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Escape plain text segments, preserving allowed HTML tags
    _TAG = re.compile(r'(</?(?:b|i|u|s|code|pre)>)', re.IGNORECASE)
    parts = _TAG.split(text)
    escaped = ''.join(
        part if _TAG.fullmatch(part) else _html.escape(part)
        for part in parts
    )

    return {"text": escaped.strip(), "parse_mode": "HTML"}

# ── Arnie's core system prompt — assembled from core/prompts/ ─────────────────

from core.prompts import build_arnie_system as _build_arnie_system

_ARNIE_SYSTEM = _build_arnie_system(platform="telegram")

# ── Typing indicator keepalive ─────────────────────────────────────────────────

async def _typing_keepalive(bot, chat_id: int, stop_event: asyncio.Event):
    """Send typing action every 4s until stop_event is set."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=4.0)
        except asyncio.TimeoutError:
            pass
          
def _telegram_streaming_eligible(in_onboarding: bool, was_onboarding: bool,
                                 raw_text: str) -> bool:
    """True when Telegram can safely stream LLM bubbles before turn finalization."""
    from core.turn_health import user_is_signing_off
    return (
        (not in_onboarding)
        and (not was_onboarding)
        and (not user_is_signing_off(raw_text))
    )

# ── Helpers ───────────────────────────────────────────────────────────────────

_REFERENCE_PATTERNS = {
    "i just sent", "i already told", "i mentioned", "i said that", "i told you",
    "check what i sent", "i already said", "scroll up", "i sent you",
    "i just told", "already sent", "i sent that", "look at what i",
    "just texted", "just gave", "already gave", "i did already", "i just said",
    "look up", "read up", "i literally just", "told you already",
}

async def _build_messages(db, user_id: int, current_text: str, extended: bool = False):
    """Build the messages list: recent history + current message.
    Loads 25 messages when extended, or when user references something they sent."""
    t = current_text.lower()
    if not extended:
        extended = any(p in t for p in _REFERENCE_PATTERNS)
    limit = 25 if extended else 6
    recent = await get_recent_conversations(db, user_id, limit=limit)
    from core.history import conversations_to_messages
    msgs = conversations_to_messages(recent)  # history.py reverses internally
    msgs.append({"role": "user", "content": current_text})
    return msgs


def _welcome_message(name: str, has_targets: bool,
                     primary_goal: str = None,
                     calorie_target: int = None,
                     protein_target: int = None) -> str:
    """Static, voiced last-resort welcome — only used as run_turn's on_completion
    fallback when the LLM reflection comes back empty. Returns a |||-split
    multi-bubble string in Arnie's lowercase bubble voice (no em dash, HTML-safe,
    ends on a concrete action)."""
    open_bubble = f"you're in{', ' + name if name else ''}."

    if has_targets and calorie_target and protein_target:
        target_bubble = (
            f"locked your targets at <b>{calorie_target} cal</b> and "
            f"<b>{protein_target}g protein</b> a day."
        )
    else:
        target_bubble = "no targets yet, we'll dial them in once i see how you eat."

    return (
        f"{open_bubble}|||"
        f"{target_bubble}|||"
        "no forms, just text me. food, a workout, your weight, whatever.|||"
        "what did you eat today? start there."
    )


from core.targets import calc_targets as _calc_targets  # shared Mifflin-St Jeor calc


async def _send_intro_and_log(update: Update, db, user_id: int, raw_text: str,
                              source_type: str, from_landing: bool = False) -> None:
    """
    Send the canonical multi-bubble intro, then log it as the first conversation
    turn. Logging matters for two reasons: (1) it stops the intro from re-firing on
    the user's next message, and (2) it gives the LLM context so it knows the name
    question was already asked. Shared by cmd_start and the first-contact path in
    _run_pipeline so both stay in sync.
    """
    from core.prompts.onboarding import INTRO_BUBBLES
    bubbles = list(INTRO_BUBBLES)
    if from_landing:
        bubbles.insert(1, "your 7-day free trial starts now.")
    for i, bubble in enumerate(bubbles):
        await update.message.reply_text(bubble)
        if i < len(bubbles) - 1:
            await asyncio.sleep(0.3)
    await log_conversation(db, user_id, raw_text or "[start]",
                           "|||".join(bubbles), source_type=source_type)


async def _run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        raw_text: str, source_type: str, db):
    """Core pipeline shared by all message types."""
    chat_id = update.effective_chat.id
    tg_user = update.effective_user
    from db.queries import resolve_user
    user = await resolve_user(db, str(tg_user.id))

    # ── Onboarding ────────────────────────────────────────────────────────────
    in_onboarding = not user.onboarding_completed
    was_onboarding = in_onboarding  # remember before tools run

    # First-ever contact, or first message after a full reset: send the intro
    # BEFORE treating anything as the user's name. Without this, a post-reset
    # message gets read as the name (the GET_NAME prompt assumes the intro was
    # already shown). Mirrors the iMessage handler. /start logs the intro too,
    # so a normal new-user flow won't double-fire it.
    if in_onboarding and not user.name:
        prior = await get_recent_conversations(db, user.id, limit=1)
        if not prior:
            await _send_intro_and_log(update, db, user.id, raw_text, source_type)
            return  # wait for the user to reply with their name

    # ── Server-side target-step interception ──────────────────────────────────
    # "Calculate for me" and "Skip for now" are stale onboarding buttons. We still
    # match their exact strings (live keyboards may carry them), but instead of
    # emitting a canned HTML card we persist the result, complete onboarding, and
    # FALL THROUGH into the normal run_turn pipeline so the just_completed
    # reflection is voiced by Arnie — no LLM text bypasses run_turn's voicing.
    completion_facts: dict | None = None
    if in_onboarding and is_onboarding_complete(user):
        _prefs = user.preferences
        _targets_done = bool(_prefs and getattr(_prefs, "calorie_target", None) is not None)
        if not _targets_done:
            _txt = raw_text.strip()

            if _txt in ("Calculate for me 🧮", "Calculate for me"):
                targets = _calc_targets(user)
                if targets:
                    # Save targets + complete onboarding server-side, then fall through.
                    if _prefs:
                        _prefs.calorie_target = targets["calories"]
                        _prefs.protein_target = targets["protein"]
                        # Auto-derive carb/fat split from goal-specific ratios
                        from api.app import compute_macro_split
                        _c, _f = compute_macro_split(
                            targets["calories"], targets["protein"],
                            user.primary_goal or "maintain"
                        )
                        if _c:
                            _prefs.carb_target = _c
                        if _f:
                            _prefs.fat_target = _f
                    user.onboarding_completed = True
                    await db.commit()
                    user = await reload_user(db, user.id)
                    # Native check-in enable on completion (idempotent; fires once
                    # here on the fall-through path). The global
                    # PROACTIVE_MESSAGING_ENABLED switch still gates real sends.
                    from db.queries import enable_check_ins
                    await enable_check_ins(db, user.id)
                    user = await reload_user(db, user.id)
                    in_onboarding = False  # was_onboarding stays True → just_completed
                    completion_facts = {"tdee": targets["tdee"], "goal": targets["goal"]}
                # If _calc_targets returns None (missing data), fall through to LLM
                # in onboarding (no facts, still asks for what's missing).

            elif _txt == "Skip for now":
                user.onboarding_completed = True
                await db.commit()
                user = await reload_user(db, user.id)
                from db.queries import enable_check_ins
                await enable_check_ins(db, user.id)
                user = await reload_user(db, user.id)
                in_onboarding = False  # was_onboarding stays True → just_completed
                # completion_facts stays None — no TDEE to weave in on the skip path.

    if not in_onboarding:
        today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        context_str = await build_context(user, today_log, db, platform="telegram",
                                          user_message=raw_text)
        system = f"{_ARNIE_SYSTEM}\n\n{context_str}"
    else:
        today_log = None
        system = build_onboarding_system(user)  # dynamic — reflects current saved state

    # ── Conversation history + current message ────────────────────────────────
    # During onboarding, load full history so stats given across rapid texts
    # are always visible to the LLM (prevents re-asking for info already given).
    messages = await _build_messages(db, user.id, raw_text, extended=in_onboarding)

    # ── Telegram image callback: reply_photo (with text fallback) ────────────
    async def _on_image(url: str, caption: str) -> None:
        try:
            await update.message.reply_photo(photo=url, caption=caption or None)
        except Exception as e:
            logger.error(f"Failed to send generated image: {e}")
            await update.message.reply_text(
                "Image was generated but couldn't send. Try asking again."
            )

    # ── Telegram interim heads-up: send the "looking that up" bubble NOW ──────
    # Fires mid-turn (slow tools — see NEEDS_HEADS_UP_TOOLS) so the user sees an
    # immediate reply while the slow tool + re-voice run. Uses the SAME ||| send
    # path as normal replies. Mirrors _on_image. Also covers iMessage callbacks
    # that flow through the same shared core. Inside streaming mode (Telegram
    # post-T2.1), run_turn skips on_interim entirely — the heads-up streams as a
    # normal bubble via on_text_bubble instead, so there's never a double-send.
    async def _on_interim(text: str) -> None:
        bubbles = [b for b in (text or "").split("|||") if b.strip()]
        for j, bubble in enumerate(bubbles):
            await update.message.reply_text(**_fmt(bubble))
            if j < len(bubbles) - 1:
                await asyncio.sleep(0.25)

    # ── Telegram streaming bubble: emit each ||| chunk as it completes ────────
    # T2.1 — the LLM stream pipes bubbles through run_turn → _BubbleStreamer →
    # this callback, which sends each bubble as a separate Telegram message
    # the moment its closing ||| arrives. iMessage stays buffered (BlueBubbles
    # can't truly stream). Onboarding stays buffered too because the LAST
    # bubble carries a reply_markup keyboard — streaming would attach it to
    # whichever bubble streams last (which can't be predicted mid-stream).
    # When this callback is wired, run_turn populates streamed_bubble_count
    # and the post-turn send loop only handles bubbles that DIDN'T stream
    # (dashboard link, onboarding completion extras).
    async def _on_text_bubble(text: str) -> None:
        if not (text and text.strip()):
            return
        try:
            await update.message.reply_text(**_fmt(text))
        except Exception as e:
            logger.warning(f"Streaming bubble send failed (continuing): {e}")

    # ── Completion text for Telegram: rich HTML welcome with targets ──────────
    def _tg_completion(u) -> str:
        prefs = u.preferences
        has_targets = bool(prefs and prefs.calorie_target)
        return _welcome_message(
            name=u.name or "",
            has_targets=has_targets,
            primary_goal=u.primary_goal,
            calorie_target=prefs.calorie_target if prefs else None,
            protein_target=prefs.protein_target if prefs else None,
        )

    # ── Typing keepalive wraps the shared pipeline core ───────────────────────
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_keepalive(context.bot, chat_id, stop_typing)
    )
    from core.conversation import run_turn
    # Stream only when: not in onboarding AND not the just-completed transition.
    # Both keyboard-bearing paths need the LAST bubble identifiable for
    # reply_markup attachment, which streaming can't promise mid-flight.
    # Sign-off turns stay buffered too. If the model emits text plus a tool call,
    # the first pass is only a draft; streaming it would send "Sleep well" before
    # the post-tool follow-up and duplicate the closeout.
    _streaming_eligible = _telegram_streaming_eligible(
        in_onboarding, was_onboarding, raw_text
    )
    _on_text_bubble_arg = _on_text_bubble if _streaming_eligible else None
    turn = None
    try:
        turn = await run_turn(
            user, db, messages, system, platform="telegram",
            in_onboarding=in_onboarding, was_onboarding=was_onboarding,
            today_log=today_log, source_type=source_type,
            on_image=_on_image, on_interim=_on_interim,
            on_completion=_tg_completion,
            completion_facts=completion_facts,
            on_text_bubble=_on_text_bubble_arg,
        )
    except Exception as e:
        logger.error(f"run_turn failed (chat {chat_id}): {e}", exc_info=True)
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    if turn is None:
        try:
            await update.message.reply_text("Something went wrong on my end. Try again?")
        except Exception:
            pass
        return

    # ── Apply Telegram reaction to the user's message ─────────────────────────
    try:
        if turn.response.reaction:
            await _tg_react(
                context.bot, chat_id, update.message.message_id, turn.response.reaction
            )
    except Exception as e:
        logger.debug(f"Telegram reaction failed (non-fatal): {e}")

    # ── Send response bubbles ─────────────────────────────────────────────────
    # Skip bubbles already streamed via _on_text_bubble (T2.1). The remainder
    # is normally either: nothing (everything streamed), OR the dashboard-link
    # extras appended in run_turn AFTER streaming, OR ALL bubbles when this
    # turn wasn't streaming-eligible (onboarding / just-completed paths).
    _already_streamed = getattr(turn, "streamed_bubble_count", 0) or 0
    _remaining = list(turn.response.bubbles[_already_streamed:])
    for i, bubble in enumerate(_remaining):
        fmt_kwargs = _fmt(bubble)
        is_last = (i == len(_remaining) - 1)

        if turn.just_completed and is_last:
            fmt_kwargs["reply_markup"] = ReplyKeyboardRemove()
        elif turn.in_onboarding and is_last:
            kb = get_onboarding_keyboard(turn.user)
            if kb:
                fmt_kwargs["reply_markup"] = kb

        await update.message.reply_text(**fmt_kwargs)

        if not is_last:
            await asyncio.sleep(0.25)

    # ── Nearby request with no location on file → one-tap share button ────────
    # Two triggers (either is enough):
    #   1. run_turn set needs_location_share (the model DID call find_nearby_places
    #      and it came back without a usable location), OR
    #   2. deterministic fallback — the user's message is a "near me" request and we
    #      have no coords on file, even if the model only TALKED about location
    #      without emitting the tool call (models skip it sometimes). This is what
    #      makes the button reliable instead of dependent on the model's tool use.
    # Sent as a fresh message so it works even when the reply streamed. The original
    # request is stashed so the tap finishes it automatically (see handle_location).
    try:
        from db.queries import location_enabled
        _no_coords = (
    getattr(turn.user, "lat", None) is None
    or getattr(turn.user, "lng", None) is None
)
        _wants_share = getattr(turn, "needs_location_share", False) or (
            _no_coords and _looks_like_location_request(raw_text)
        )
        if _wants_share and location_enabled():
            _LOCATION_PENDING[str(tg_user.id)] = (raw_text, time.time())
            await update.message.reply_text(
                "📍 Tap to share your location and I'll find spots right around you.",
                reply_markup=_share_location_keyboard(),
            )
    except Exception as e:
        logger.debug(f"location-share prompt failed (non-fatal): {e}")

    # ── Post-onboarding: dashboard as an inline button (Telegram-specific) ────
    if turn.just_completed:
        try:
            from core.urls import dashboard_url
            token = await get_or_create_webhook_token(db, turn.user.id)
            dash_url = dashboard_url(token)
            dash_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 Open your dashboard →", url=dash_url)
            ]])
            await update.message.reply_text(
                "Your coaching dashboard is live — everything you log shows up here.",
                reply_markup=dash_kb,
            )
        except Exception as e:
            logger.warning(f"Could not send dashboard link after onboarding: {e}")

    # ── Persist conversation (+ turn-health flags on parsed_intent) ────────────
    log_text = "|||".join(turn.response.bubbles)
    await log_conversation(db, user.id, raw_text, log_text, source_type=source_type,
                           parsed_intent=(",".join(turn.health_flags) or None))

    # ── Adaptive profile refresh + reflection (both fire in background) ─────
    # CRITICAL: the request-scoped `db` session closes when this function returns
    # (the `async with AsyncSessionLocal()` in _run exits). Background tasks must
    # therefore open their OWN session and re-fetch the user by id — never close
    # over `db` or `turn.user`, which would be detached/closed by run time.
    if not turn.in_onboarding:
        _uid = turn.user.id

        # Profile synthesis — throttled to ~3h internally; background so it never
        # adds latency to the user's response.
        async def _bg_profile(uid=_uid):
            try:
                async with AsyncSessionLocal() as bg_db:
                    from db.queries import reload_user
                    u = await reload_user(bg_db, uid)
                    if u:
                        from memory.profile_updater import maybe_update_profile
                        await maybe_update_profile(u, bg_db)
            except Exception as e:
                logger.error(f"Profile update error: {e}")

        asyncio.create_task(_bg_profile())

        # Reflection — capture durable behavioral notes at 25% probability.
        # (Was imported but never called — now wired.)
        if random.random() < 0.25 and raw_text and len(raw_text) > 20:
            _resp_text = "|||".join(turn.response.bubbles)
            async def _bg_reflect(uid=_uid, msg=raw_text, resp=_resp_text):
                try:
                    async with AsyncSessionLocal() as bg_db:
                        from db.queries import reload_user
                        u = await reload_user(bg_db, uid)
                        if u:
                            await maybe_update_memory(u, msg, resp, bg_db)
                except Exception as e:
                    logger.error(f"Reflection error: {e}")
            asyncio.create_task(_bg_reflect())


# ── Telegram handlers ─────────────────────────────────────────────────────────

from bot.message_debounce import schedule_message as _debounce

# Per-user pipeline lock — parity with the iMessage handler. The debounce coalesces
# rapid texts; this guarantees two runs for the same user can never overlap (the
# duplicate-log / duplicate-onboarding-question bug class).
_tg_pipeline_locks: dict[str, asyncio.Lock] = {}


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not text.strip():
        return

    user_key = f"tg:{update.effective_user.id}"
    lock = _tg_pipeline_locks.setdefault(user_key, asyncio.Lock())

    async def _run(combined_text: str):
        async with lock:
            async with AsyncSessionLocal() as db:
                await _run_pipeline(update, context, combined_text, "text", db)

    await _debounce(user_key, text, _run, delay=1.5)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        voice_file = await update.message.voice.get_file()
        audio_data = bytes(await voice_file.download_as_bytearray())
        transcript = await process_voice(audio_data, "voice.ogg")

        if not transcript:
            await update.message.reply_text(
                "Couldn't transcribe that. "
                "Make sure OPENAI_API_KEY is set for voice support."
            )
            return

        # Prepend [Voice note]: so the LLM applies voice-specific rules (multi-item
        # parsing, filler-word tolerance). Mirrors [Food photo]: for photos.
        # Arnie still coaches naturally — the prefix is invisible plumbing, never echoed.
        await _run_pipeline(update, context, f"[Voice note]: {transcript}", "voice", db)


def _share_location_keyboard() -> ReplyKeyboardMarkup:
    """One-tap 'share my location' button. request_location asks Telegram to send
    the user's current coordinates ONCE when tapped — Telegram never streams
    location to a bot without this explicit tap (privacy model). resize + one-time
    so it doesn't linger in the keyboard after use."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Share my location", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


async def cmd_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/location — surface the share-location button so the user can set where they
    are. Inert unless LOCATION_ENABLED (otherwise we'd offer a dead feature)."""
    from db.queries import location_enabled
    if not location_enabled():
        await update.message.reply_text(
            "Location features aren't switched on yet. Tell me your city and I'll "
            "work with that."
        )
        return
    await update.message.reply_text(
        "Tap below and I'll find spots around you. One tap, that's it.",
        reply_markup=_share_location_keyboard(),
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive a shared location — both a one-time share and live-location updates
    (live arrives as edited_message, so we read effective_message). Saves coords,
    best-effort reverse-geocodes a city, and routes a normal turn so Arnie reacts
    in voice instead of going silent."""
    from db.queries import location_enabled
    msg = update.effective_message
    loc = getattr(msg, "location", None) if msg else None
    if loc is None:
        return
    if not location_enabled():
        # Feature off — acknowledge gracefully, don't store, don't go silent.
        await msg.reply_text(
            "Got your location, but the nearby-places feature isn't on yet. "
            "I'll just use your city for now.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    lat, lng = loc.latitude, loc.longitude
    is_live = bool(getattr(loc, "live_period", None))

    async with AsyncSessionLocal() as db:
        from db.queries import resolve_user
        user = await resolve_user(db, str(update.effective_user.id))
        # Reverse-geocode is best-effort; coords are saved either way.
        city = None
        try:
            from core.geocode import reverse as _reverse
            city = await _reverse(lat, lng)
        except Exception as e:
            logger.warning(f"reverse geocode failed: {e}")
        from db.queries import save_user_location
        await save_user_location(db, user.id, lat, lng, city=city)

        # Was a request waiting on this location? Finish it now, with coords on file.
        pend = _LOCATION_PENDING.pop(str(update.effective_user.id), None)
        if pend:
            _text, _ts = pend
            if (time.time() - _ts) <= _LOCATION_PENDING_TTL and _text and _text.strip():
                await msg.reply_text(
                    f"Got it{(' near ' + city) if city else ''} 📍 finding it now.",
                    reply_markup=ReplyKeyboardRemove(),
                )
                await _run_pipeline(update, context, _text, "text", db)
                return

        # Live-location edits stream in silently — store and stop (no reply per tick,
        # that'd be spam). Only the FIRST share / a one-time share gets a reply.
        if is_live and update.edited_message is not None:
            return

        where = f" near {city}" if city else ""
        await msg.reply_text(
            f"Locked in your spot{where} 📍 ask me what's around you anytime.",
            reply_markup=ReplyKeyboardRemove(),
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Show typing immediately — image download + Vision API run before the pipeline
    # starts, so without this the user sees nothing for several seconds.
    chat_id = update.effective_chat.id
    _stop_pre = asyncio.Event()
    _pre_typing = asyncio.create_task(_typing_keepalive(context.bot, chat_id, _stop_pre))

    combined = None
    try:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        photo_data = bytes(await photo_file.download_as_bytearray())
        caption = update.message.caption or ""

        # Smart preprocessor classifies + extracts. Emits a TAGGED block
        # ([FOOD_LOG], [MENU_DECISION], [WORKOUT_LOG], [METRICS], etc.) the
        # main LLM routes on via the PHOTO PIPELINE rules in the system prompt.
        from multimodal.image_handler import process_photo
        analysis = await process_photo(photo_data, caption)
        if analysis:
            caption_part = f" Caption: {caption}" if caption else ""
            combined = (
                f"[Photo received]{caption_part}\n\n"
                f"{analysis}"
            )
    finally:
        _stop_pre.set()
        _pre_typing.cancel()
        try:
            await _pre_typing
        except asyncio.CancelledError:
            pass

    if not combined:
        await update.message.reply_text(
            "Couldn't analyse the image. "
            "Make sure ANTHROPIC_API_KEY is set for image support."
        )
        return

    # Acquire per-user lock before pipeline — prevents concurrent pipelines for the
    # same user (e.g. rapid photo + text arriving together).
    user_key = f"tg:{update.effective_user.id}"
    lock = _tg_pipeline_locks.setdefault(user_key, asyncio.Lock())
    async with lock:
        async with AsyncSessionLocal() as db:
            await _run_pipeline(update, context, combined, "image", db)


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Deep-link parameter from landing page: /start freetrial
    raw_arg = (context.args[0] if context.args else "")
    source = raw_arg.lower()
    from_landing = source == "freetrial"

    async with AsyncSessionLocal() as db:
        # Cross-platform link deep-link: /start LINK-XXXX (from iMessage)
        from db.queries import linking_enabled, consume_link_code
        if linking_enabled() and raw_arg.upper().startswith("LINK-"):
            channel_user = await get_or_create_user(db, str(update.effective_user.id))
            canonical = await consume_link_code(db, raw_arg, channel_user)
            if canonical:
                # They linked INTO Telegram (this is the canonical) → default
                # reminders here, but let them switch to iMessage.
                if not canonical.channel_preference:
                    canonical.channel_preference = "telegram"
                    await db.commit()
                await update.message.reply_text(
                    f"🔗 Linked. This is now the same account as your other device, "
                    f"<b>{canonical.name or 'there'}</b> — everything's in sync.",
                    parse_mode="HTML",
                )
                await update.message.reply_text(
                    "quick one — where do you want my check-ins and reminders? "
                    "i'll only send them on one so you're not double-pinged. "
                    "reply <b>telegram</b> or <b>imessage</b> (telegram for now).",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    "That link code's expired or invalid — generate a fresh one and try again."
                )
            return

        # Web onboarding pre-registration: /start SETUP-XXXXXX
        # Profile was collected on the landing page — consume it and skip conversational onboarding.
        # Guard: ONLY apply to brand-new users (onboarding_completed=False).
        # An existing user clicking a SETUP link (e.g. while testing) must never have their
        # real profile overwritten — consume the code so it can't be replayed, but leave
        # their account untouched and send a safe "you're already set up" reply.
        if raw_arg.upper().startswith("SETUP-"):
            user = await get_or_create_user(db, str(update.effective_user.id))
            from db.queries import consume_pre_registration, enable_check_ins, get_or_create_webhook_token
            profile = await consume_pre_registration(db, raw_arg.upper())

            # Existing onboarded user — protect their account
            if user.onboarding_completed:
                first_name = (user.name or "").split()[0] if user.name else "there"
                await update.message.reply_text(
                    f"hey {first_name} — you're already fully set up. "
                    "your profile and history are all intact."
                )
                return

            if profile:
                # Brand-new user — apply the pre-filled profile and skip conversational onboarding
                user.name                = profile.get("name") or user.name
                user.age                 = profile.get("age") or user.age
                user.sex                 = profile.get("sex") or user.sex
                user.height_cm           = profile.get("height_cm") or user.height_cm
                user.current_weight_kg   = profile.get("weight_kg") or user.current_weight_kg
                user.primary_goal        = profile.get("primary_goal") or user.primary_goal
                user.training_experience = profile.get("training_experience") or user.training_experience
                if profile.get("dietary_preferences"):
                    user.dietary_preferences = profile["dietary_preferences"]
                if profile.get("timezone"):
                    user.timezone = profile["timezone"]
                if profile.get("goal_weight_lbs"):
                    user.goal_weight_kg = round(profile["goal_weight_lbs"] / 2.20462, 2)
                user.onboarding_completed = True

                # Persist macro targets (Step 5 of /join). All four fields are
                # optional — older /join builds won't include them, in which
                # case the targets_unset nudge will fire on the user's first
                # message exactly like before.
                if any(profile.get(k) is not None for k in
                       ("calorie_target", "protein_target", "carb_target", "fat_target")):
                    from db.models import UserPreferences
                    prefs = user.preferences
                    if not prefs:
                        prefs = UserPreferences(user_id=user.id)
                        db.add(prefs)
                    if profile.get("calorie_target") is not None:
                        prefs.calorie_target = int(profile["calorie_target"])
                    if profile.get("protein_target") is not None:
                        prefs.protein_target = int(profile["protein_target"])
                    if profile.get("carb_target") is not None:
                        prefs.carb_target = int(profile["carb_target"])
                    if profile.get("fat_target") is not None:
                        prefs.fat_target = int(profile["fat_target"])
                    logger.info(
                        f"SETUP-XXX targets applied for user {user.id}: "
                        f"cals={prefs.calorie_target} P={prefs.protein_target}g "
                        f"C={prefs.carb_target}g F={prefs.fat_target}g"
                    )

                await db.commit()

                # Enable check-ins and ensure webhook token exists
                await enable_check_ins(db, user.id)
                await get_or_create_webhook_token(db, user.id)

                # Personalised greeting — feels like a coach who was already briefed
                first_name = (user.name or "").split()[0] if user.name else "there"
                exp_str = (user.training_experience or "").lower()
                weight_lbs = (
                    round(user.current_weight_kg * 2.20462)
                    if user.current_weight_kg else None
                )

                # Build a crisp profile line: "advanced lifter · 185 lbs · here to cut"
                _goal_phrase = {
                    "cut":         "here to cut",
                    "bulk":        "here to build",
                    "maintain":    "here to stay lean",
                    "performance": "here for performance",
                    "health":      "here for health",
                }
                goal_phrase = _goal_phrase.get(
                    user.primary_goal or "", f"goal: {user.primary_goal}"
                )
                profile_parts = []
                if exp_str:
                    profile_parts.append(f"{exp_str} lifter")
                if weight_lbs:
                    profile_parts.append(f"{weight_lbs} lbs")
                profile_parts.append(goal_phrase)
                if user.dietary_preferences:
                    profile_parts.append(user.dietary_preferences)
                profile_line = " · ".join(profile_parts)

                # Goal-specific first action — no generic "what to track" question
                _goal_cta = {
                    "cut": (
                        "log what you've eaten today and i'll calculate exactly where your deficit sits."
                    ),
                    "bulk": (
                        "log your meals today — i'll track your surplus and make sure protein's where it needs to be."
                    ),
                    "maintain": (
                        "log your meals today and i'll start watching the trend."
                    ),
                    "performance": (
                        "tell me about today's session or what you've eaten — we'll build from there."
                    ),
                    "health": (
                        "log what you ate today and i'll start finding your patterns."
                    ),
                }
                cta = _goal_cta.get(
                    user.primary_goal or "",
                    "tell me what you've eaten or trained today and we'll get started."
                )

                await update.message.reply_text(
                    f"hey {first_name} — already read through your profile, so we skip all the setup. 💪"
                )
                await update.message.reply_text(profile_line + ".")
                await update.message.reply_text(
                    "here's how we work: text me your meals and training as you go — voice "
                    "notes and food photos both land, rough is totally fine. i do the math "
                    "and learn your patterns as we go. (type /howto anytime for the full rundown.)"
                )
                await update.message.reply_text(cta)
            else:
                # Code expired, already used, or not found — start normal flow
                await update.message.reply_text(
                    "that setup link has expired or already been used. no worries — i'll walk you through it now."
                )
                await _send_intro_and_log(update, db, user.id, "[start]", "text", from_landing=False)
            return

        # Welcome-back branch: resolve to canonical so a Telegram user
        # whose brain lives on iMessage sees their real name, not the
        # blank shim row's empty name field.
        user = await resolve_user(db, str(update.effective_user.id))
        if user.onboarding_completed:
            today_log = await get_today_log(db, user.id, user.timezone or "UTC")
            msg = (
                f"Welcome back, <b>{user.name}</b>. 💪\n\n"
                + ("Nothing logged today yet — what's first up?"
                   if not today_log else fmt_log(today_log))
            )
            await update.message.reply_text(**_fmt(msg))
        elif user.name:
            # Mid-onboarding — pick up where they left off
            await update.message.reply_text(
                f"Hey {user.name}, we're mid-setup. Just keep going — answer the last question I asked, "
                "or type anything and I'll guide us back."
            )
        else:
            # Brand-new user → the canonical multi-bubble intro, the same on every
            # channel. Logged (via the helper) so it won't re-fire on their first
            # real message. Landing-page signups get a trial line.
            await _send_intro_and_log(
                update, db, user.id, "[start]", "text", from_landing=from_landing
            )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Today's calories, protein, water, and workout status."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        prefs = user.preferences

        if not log:
            await update.message.reply_text("Nothing logged today yet. Start by telling me what you ate.")
            return

        def _bar(val, target, width=10):
            if not target:
                return ""
            filled = min(int(val / target * width), width)
            return "▓" * filled + "░" * (width - filled)

        cal = log.total_calories
        pro = log.total_protein
        carb = log.total_carbs
        fat = log.total_fats
        water = log.total_water_ml
        cal_t = prefs.calorie_target if prefs else None
        pro_t = prefs.protein_target if prefs else None

        cal_line = f"<b>Calories</b>  {cal:.0f}"
        if cal_t:
            rem = cal_t - cal
            cal_line += f" / {cal_t}  ({rem:+.0f})\n{_bar(cal, cal_t)}"

        pro_line = f"<b>Protein</b>   {pro:.0f}g"
        if pro_t:
            rem_p = pro_t - pro
            pro_line += f" / {pro_t}g  ({rem_p:+.0f}g)\n{_bar(pro, pro_t)}"

        workout_icon = "✅" if log.workout_completed else "⬜"
        cardio_icon  = "✅" if log.cardio_completed  else "⬜"
        water_line = f"{water:.0f}ml" if water else "none logged"

        lines = [
            f"<b>Today — {log.date}</b>",
            "",
            cal_line,
            "",
            pro_line,
            "",
            f"<b>Carbs</b>     {carb:.0f}g   <b>Fats</b> {fat:.0f}g",
            f"<b>Water</b>     {water_line}",
            "",
            f"{workout_icon} Workout   {cardio_icon} Cardio",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI coaching insights based on today + recent history."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        prefs = user.preferences

        if not log:
            await update.message.reply_text("Nothing logged today yet — log some food or a workout first.")
            return

        await update.message.reply_text(random.choice([
            "🏋️ lifting some mental weights…",
            "🧠 crunching your numbers, not your abs…",
            "📊 running the tape on your week…",
            "🔬 digging through your data…",
            "⚡ spinning up the coach brain…",
            "🎯 locking in on your patterns…",
            "🩺 reading your macros…",
            "📈 reading the gains tape…",
            "💡 connecting the dots…",
            "🔍 zooming in on your stats…",
        ]))

        try:
            from db.queries import get_recent_weights
            from api.insights import generate_chat_analysis

            history = await get_recent_logs(db, user.id, days=30)
            weights = await get_recent_weights(db, user.id, days=30)

            hist_data = [
                {"date": str(l.date), "calories": round(l.total_calories or 0),
                 "protein": round(l.total_protein or 0), "workout": l.workout_completed}
                for l in sorted(history, key=lambda x: x.date)
            ]
            weight_data = [
                {"date": w.timestamp.strftime("%Y-%m-%d"),
                 "lbs": round(w.weight_kg * 2.20462, 1)}
                for w in sorted(weights, key=lambda w: w.timestamp)
            ]

            cal_t = prefs.calorie_target if prefs else None
            pro_t = prefs.protein_target if prefs else None

            stats = {
                "user": {
                    "name": user.name,
                    "goal": user.primary_goal,
                    "current_weight_lbs": round(user.current_weight_kg * 2.20462, 1) if user.current_weight_kg else None,
                    "goal_weight_lbs": round(user.goal_weight_kg * 2.20462, 1) if user.goal_weight_kg else None,
                },
                "targets": {"calories": cal_t, "protein": pro_t},
                "today": {
                    "calories": round(log.total_calories or 0),
                    "protein": round(log.total_protein or 0),
                    "carbs": round(log.total_carbs or 0),
                    "fats": round(log.total_fats or 0),
                    "workout_completed": log.workout_completed,
                    "cardio_completed": log.cardio_completed,
                },
                "history": hist_data,
                "weights": weight_data,
            }

            insights = await generate_chat_analysis(stats)
            if insights:
                msg = "\n\n".join(f"· {i}" for i in insights)
                await update.message.reply_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text("Not enough data for insights yet — keep logging.")
        except Exception as e:
            logger.error(f"cmd_ai failed: {e}", exc_info=True)
            await update.message.reply_text("Couldn't generate insights right now — try again in a moment.")


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Profile + targets combined — the /me command."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        p = user.preferences

        def _v(val, unit="", fallback="not set"):
            return f"{val}{unit}" if val is not None else fallback

        w_lbs = f"{user.current_weight_kg * 2.20462:.1f} lbs" if user.current_weight_kg else "not set"
        g_lbs = f"{user.goal_weight_kg * 2.20462:.1f} lbs" if user.goal_weight_kg else "not set"
        h_ft = ""
        if user.height_cm:
            inches_total = user.height_cm / 2.54
            h_ft = f"{int(inches_total // 12)}'{int(inches_total % 12)}\"  ({user.height_cm:.0f}cm)"

        lines = [
            f"<b>{user.name or 'Your'} profile</b>",
            "",
            f"Age          {_v(user.age)}",
            f"Sex          {_v(user.sex)}",
            f"Height       {h_ft or 'not set'}",
            f"Weight       {w_lbs}",
            f"Goal weight  {g_lbs}  ({_v(user.primary_goal)})",
            f"Experience   {_v(user.training_experience)}",
            f"Diet         {user.dietary_preferences or 'none'}",
            f"Injuries     {user.injuries or 'none'}",
        ]

        lines += ["", "<b>Targets</b>"]
        if p and (p.calorie_target or p.protein_target):
            if p.calorie_target:
                lines.append(f"Calories   <b>{p.calorie_target} kcal/day</b>")
            if p.protein_target:
                lines.append(f"Protein    <b>{p.protein_target}g/day</b>")
            if p.calorie_target and p.protein_target:
                fat_g = round(p.calorie_target * 0.25 / 9)
                carb_g = round((p.calorie_target - p.protein_target * 4 - fat_g * 9) / 4)
                if carb_g > 0:
                    lines.append(f"Carbs      ~{carb_g}g/day")
                    lines.append(f"Fats       ~{fat_g}g/day")
        else:
            lines.append("No targets set — tell me your calorie and protein goals to set them.")

        whoop = bool(user.whoop_access_token or user.whoop_refresh_token)
        lines += ["", f"<b>Wearable</b>  {'Whoop ✅' if whoop else '⚠️ None connected — use /connect'}"]

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# Keep /profile and /targets as aliases for /me
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /profile — Arnie's accumulated understanding of the user.
    Delivers the AI-generated bio in chat + link to the full dashboard profile tab.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        if not user.onboarding_completed:
            await update.message.reply_text("Finish setup first — then I'll have a real picture of you.")
            return

        from memory.bio_generator import get_bio_for_chat
        from db.queries import get_or_create_webhook_token

        bio = await get_bio_for_chat(user, db)
        token = await get_or_create_webhook_token(db, user)
        dashboard_url = f"https://app.tryarnie.com/dashboard/{token}"

        if bio:
            await update.message.reply_text(bio)
            await update.message.reply_text(
                f"That's the overview. Full breakdown — everything I've tracked organized by category — is on your dashboard:\n{dashboard_url}"
            )
        else:
            await update.message.reply_text(
                f"Still building your profile — keep logging and I'll know more soon.\n\nDashboard: {dashboard_url}"
            )


async def cmd_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_me(update, context)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Last 7 days recap."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        from db.queries import get_recent_logs, get_recent_weights
        logs = await get_recent_logs(db, user.id, days=7)
        weights = await get_recent_weights(db, user.id, days=7)
        prefs = user.preferences

        # Past days are always "finalized" — there's no open/closed state.
        # Filter out today (which is still in progress) for the weekly summary.
        from datetime import date as _date
        today_d = _date.today()
        past = [l for l in logs if l.date < today_d]
        if len(past) < 3:
            await update.message.reply_text(
                "Not enough history yet — /week needs at least 3 logged days to show useful trends. "
                "Keep logging and check back."
            )
            return

        lines = ["<b>Last 7 days</b>", ""]
        for log in sorted(past, key=lambda l: l.date, reverse=True)[:7]:
            wo = "💪" if log.workout_completed else "  "
            cal_str = f"{log.total_calories:.0f}"
            if prefs and prefs.calorie_target:
                diff = log.total_calories - prefs.calorie_target
                cal_str += f" ({diff:+.0f})"
            pro_str = f"{log.total_protein:.0f}g"
            lines.append(f"{wo} <b>{log.date}</b>   {cal_str} kcal  {pro_str} protein")

        if weights:
            # Deduplicate: keep only the latest entry per calendar date
            seen_dates = {}
            for w in sorted(weights, key=lambda w: w.timestamp):
                seen_dates[w.timestamp.date()] = w
            unique_weights = sorted(seen_dates.values(), key=lambda w: w.timestamp, reverse=True)[:5]
            if unique_weights:
                lines += ["", "<b>Weight</b>"]
                for w in unique_weights:
                    lbs = w.weight_kg * 2.20462
                    lines.append(f"  {w.timestamp.strftime('%b %d')}   {lbs:.1f} lbs  ({w.weight_kg:.1f}kg)")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """What Arnie knows about habits and tendencies."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        from memory.memory_manager import read_memory
        mem = await read_memory(user.telegram_id)
        if not mem or mem.strip() == "":
            await update.message.reply_text(
                "nothing stored yet. my memory builds up as we talk. "
                "the more you log, the sharper i get. tell me what you ate today."
            )
            return
        # Telegram message limit is 4096 chars
        text = mem[:3800]
        await update.message.reply_text(f"<pre>{text}</pre>", parse_mode="HTML")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset today's log or wipe the full account."""
    args = context.args

    if not args:
        await update.message.reply_text(
            "<b>Reset options</b>\n\n"
            "/reset today — clear today's food &amp; exercise log\n"
            "/reset all — wipe everything and start from scratch\n\n"
            "⚠️ Cannot be undone.",
            parse_mode="HTML"
        )
        return

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))

        if args[0].lower() == "today":
            cleared = await _reset_today(db, user)
            if cleared:
                await update.message.reply_text(
                    "Today's log cleared — food, exercise, and totals all wiped.\n"
                    "Start logging fresh.",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text("Nothing logged today yet — nothing to reset.")

        elif args[0].lower() == "all":
            confirm = args[1].lower() if len(args) > 1 else ""
            if confirm != "confirm":
                await update.message.reply_text(
                    "⚠️ This will delete <b>all</b> your data — logs, weight history, memory, profile.\n\n"
                    "To confirm: /reset all confirm",
                    parse_mode="HTML"
                )
                return

            await _reset_all(db, user)
            await update.message.reply_text(
                "All data wiped. Fresh start.\n\nSend any message to begin setup again."
            )

        else:
            await update.message.reply_text(
                "Usage: /reset today  or  /reset all confirm",
                parse_mode="HTML"
            )


async def cmd_whoop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnostic + manual control for the Whoop integration."""
    args = context.args
    action = args[0].lower() if args else "status"

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))

        if action in ("status", "info", ""):
            # A user counts as connected if they have ANY token saved.
            # A missing refresh_token is a degraded state we surface separately.
            connected = bool(user.whoop_refresh_token or user.whoop_access_token)
            if not connected:
                await update.message.reply_text(
                    "<b>Whoop: not connected</b>\n\n"
                    "Run /connect whoop to link your account.",
                    parse_mode="HTML",
                )
                return

            from db.queries import get_recent_health_snapshots
            snaps = await get_recent_health_snapshots(db, user.id, days=7)
            whoop_snaps = [s for s in snaps if s.source == "whoop"]

            expires_str = "unknown"
            if user.whoop_token_expires_at:
                from datetime import datetime
                delta = user.whoop_token_expires_at - datetime.utcnow()
                mins = int(delta.total_seconds() / 60)
                expires_str = f"in {mins} min" if mins > 0 else f"{-mins} min ago (will auto-refresh)"

            latest_line = "no data synced yet"
            if whoop_snaps:
                s = whoop_snaps[0]
                bits = []
                if s.recovery_score is not None:
                    bits.append(f"Recovery {s.recovery_score}%")
                if s.strain is not None:
                    bits.append(f"Strain {s.strain:.1f}")
                if s.sleep_hours is not None:
                    bits.append(f"Sleep {s.sleep_hours:.1f}h")
                if s.hrv is not None:
                    bits.append(f"HRV {s.hrv:.0f}ms")
                latest_line = f"<b>{s.date}</b>: " + " · ".join(bits)

            refresh_status = "✅" if user.whoop_refresh_token else "⚠️ missing (run /whoop disconnect then /connect whoop)"
            await update.message.reply_text(
                f"<b>Whoop status</b>\n\n"
                f"Connected: ✅\n"
                f"Refresh token: {refresh_status}\n"
                f"Access token expires: {expires_str}\n"
                f"Days synced (last 7): {len(whoop_snaps)}\n\n"
                f"Latest: {latest_line}\n\n"
                f"/whoop sync — pull latest data now\n"
                f"/whoop disconnect — clear tokens and reconnect",
                parse_mode="HTML",
            )
            return

        if action == "sync":
            if not (user.whoop_access_token or user.whoop_refresh_token):
                await update.message.reply_text("Not connected. Run /connect whoop first.")
                return
            await update.message.reply_text("Syncing Whoop data…")
            from api.whoop import sync_user_whoop
            from db.queries import resolve_user as _resolve_tg
            try:
                canonical = await _resolve_tg(db, str(update.effective_user.id))
                synced = await sync_user_whoop(db, user, days=7,
                                               snapshot_user_id=canonical.id)
                if synced > 0:
                    await update.message.reply_text(
                        f"✓ Synced <b>{synced} days</b> of Whoop data.\n\n"
                        f"Run /whoop to see the latest snapshot.",
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(
                        "Sync returned 0 days. Either Whoop doesn't have data for the last week yet, "
                        "or the access token expired and we don't have a refresh token to renew it.\n\n"
                        "If your access token is showing as expired in /whoop, run /whoop disconnect and try /connect whoop again.",
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"Sync failed: <code>{str(e)[:300]}</code>\n\n"
                    "Try /whoop disconnect then /connect whoop to refresh the link.",
                    parse_mode="HTML",
                )
            return

        if action in ("disconnect", "logout", "unlink"):
            from db.queries import clear_whoop_tokens
            await clear_whoop_tokens(db, user.id)
            await update.message.reply_text(
                "Whoop disconnected. Use /connect whoop to link again."
            )
            return

        await update.message.reply_text(
            "/whoop — connection status\n"
            "/whoop sync — pull latest data\n"
            "/whoop disconnect — clear and reconnect"
        )


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Submit a bug report or feature suggestion."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "<b>Send feedback</b>\n\n"
            "/feedback bug [what went wrong]\n"
            "/feedback feature [what you'd like]\n"
            "/feedback [anything else]\n\n"
            "Examples:\n"
            "<i>/feedback bug photos crash with multi-item meals</i>\n"
            "<i>/feedback feature add a meal template system</i>",
            parse_mode="HTML",
        )
        return

    kind_arg = args[0].lower()
    if kind_arg in ("bug", "bugs", "issue"):
        kind, text_parts = "bug", args[1:]
    elif kind_arg in ("feature", "suggestion", "idea"):
        kind, text_parts = "feature", args[1:]
    else:
        kind, text_parts = "other", args

    text = " ".join(text_parts).strip()
    if not text:
        await update.message.reply_text(
            "Need a bit more — tell me what the bug is or what feature you'd like.\n\n"
            "<i>Example: /feedback bug photo upload fails on multi-item meals</i>",
            parse_mode="HTML",
        )
        return

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))
        entry = await add_feedback(db, user.id, kind, text)

    icon = "🐛" if kind == "bug" else "💡" if kind == "feature" else "📝"
    await update.message.reply_text(
        f"{icon} <b>Got it.</b>\n\n"
        f"Logged as <b>{kind}</b> (#{entry.id}). Thanks — this kind of feedback is how I get sharper.",
        parse_mode="HTML",
    )


async def cmd_connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Connect a wearable. Supports: whoop, apple."""
    args = context.args
    target = args[0].lower() if args else ""

    if target in ("apple", "applehealth", "health"):
        async with AsyncSessionLocal() as db:
            user = await resolve_user(db, str(update.effective_user.id))
            if not user.onboarding_completed:
                await update.message.reply_text("Finish setup first, then we'll connect Apple Health.")
                return
            token = await get_or_create_webhook_token(db, user.id)

        base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
        guide_url = f"{base_url}/health/apple/guide?token={token}"

        await update.message.reply_text(
            "<b>Connect Apple Health</b>\n\n"
            "Open this setup link on your iPhone in Safari:\n\n"
            f'<a href="{guide_url}">→ Set up Apple Health sync</a>\n\n'
            "Setup takes about 2 minutes:\n"
            "1. Copy your sync URL\n"
            "2. Download the Arnie Health Shortcut\n"
            "3. Paste the URL when iOS asks\n"
            "4. Run it once and allow Health access\n"
            "5. Add a daily automation\n\n"
            "<i>You never need to share your Apple ID, iCloud, or Health password.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    if target == "whoop":
        async with AsyncSessionLocal() as db:
            # resolve_user returns the canonical account for linked identities so
            # Whoop tokens are always written to the same row that build_context
            # and the dashboard read from. Using get_or_create_user here caused
            # tokens to land on the linked (non-canonical) row → Arnie saw no tokens.
            from db.queries import resolve_user
            user = await resolve_user(db, str(update.effective_user.id))
            if not user.onboarding_completed:
                await update.message.reply_text("Finish setup first, then we'll connect Whoop.")
                return
            token = await get_or_create_webhook_token(db, user.id)

        from api.whoop import build_auth_url
        base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
        redirect_uri = f"{base_url}/whoop/callback"
        auth_url = build_auth_url(redirect_uri, state=token)

        await update.message.reply_text(
            "<b>Connect your Whoop</b>\n\n"
            "Tap the link below to authorize. After you approve, your recovery, sleep, "
            "HRV, and strain will sync automatically every morning.\n\n"
            f'<a href="{auth_url}">→ Authorize Whoop access</a>\n\n'
            "<i>This is a one-time setup. You can revoke access anytime from your Whoop account settings.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    # Default: show options
    await update.message.reply_text(
        "<b>Connect a wearable</b>\n\n"
        "/connect whoop — Whoop band (recovery, sleep, HRV, strain)\n"
        "/connect apple — Apple Health via iOS Shortcut (steps, HR, sleep, calories)",
        parse_mode="HTML",
    )


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show upgrade prompt with a Stripe Checkout link."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from api.stripe_billing import create_checkout_session
    from db.queries import is_premium

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))

        if user.subscription_status == "active":
            await update.message.reply_text(
                "You're already on <b>Arnie Premium</b> ✅\n\n"
                "Use /billing to manage your subscription.",
            )
            return

    try:
        url = create_checkout_session(str(update.effective_user.id))
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        await update.message.reply_text(
            "Couldn't generate a payment link right now — try again in a moment."
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Upgrade to Premium →", url=url)
    ]])
    await update.message.reply_text(
        "<b>Arnie Premium</b> — $9.99/month\n\n"
        "• Unlimited coaching & memory\n"
        "• Proactive daily check-ins\n"
        "• Nutrition + training tracking\n"
        "• Cancel anytime\n\n"
        "Tap below to complete payment on Stripe:",
        reply_markup=keyboard,
    )


async def cmd_billing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the Stripe Customer Portal to manage or cancel the subscription."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from api.stripe_billing import create_billing_portal

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, str(update.effective_user.id))

        if not user.stripe_customer_id:
            await update.message.reply_text(
                "No active subscription found.\n\nUse /upgrade to get started."
            )
            return

    try:
        url = create_billing_portal(user.stripe_customer_id)
    except Exception as e:
        logger.error(f"Stripe portal error: {e}")
        await update.message.reply_text(
            "Couldn't open billing portal right now — try again in a moment."
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Manage Subscription →", url=url)
    ]])
    await update.message.reply_text(
        "Manage your subscription, update payment, or cancel:",
        reply_markup=keyboard,
    )


async def cmd_dash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the user their personal read-only dashboard URL."""
    async with AsyncSessionLocal() as db:
        # resolve_user follows linked_to_user_id to the canonical row.
        # Without this, a Telegram user whose canonical brain lives on
        # iMessage (e.g. Gi: Telegram shim row #9 → canonical row #5)
        # gets "Finish setup first" because the shim has
        # onboarding_completed=False even though their iMessage profile
        # is fully set up. Discovered live 2026-06-12.
        user = await resolve_user(db, str(update.effective_user.id))
        if not user.onboarding_completed:
            await update.message.reply_text("Finish setup first before accessing the dashboard.")
            return
        token = await get_or_create_webhook_token(db, user.id)

    from core.urls import dashboard_url
    url = dashboard_url(token)
    from core.blurbs import dashboard_line
    line = await dashboard_line(user.name or "")
    await update.message.reply_text(line)
    # link in its own message so it's clean to tap and bookmark
    await update.message.reply_text(url, disable_web_page_preview=False)


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a one-time code + tap-to-send iMessage link to connect devices."""
    from db.queries import linking_enabled, generate_link_code
    if not linking_enabled():
        await update.message.reply_text("Device linking isn't available right now.")
        return
    async with AsyncSessionLocal() as db:
        # Resolve to the canonical account. If this Telegram identity is already
        # linked into another platform's account, the raw channel row has no
        # name / onboarding_completed=False — checking it would wrongly block
        # /link ("Finish setup first") and would mint the code on a SECONDARY
        # row. Minting on the canonical keeps a third device (iMessage + iOS +
        # Telegram) linking onto the same brain.
        user = await resolve_user(db, str(update.effective_user.id))
        if not user.onboarding_completed and not user.name:
            await update.message.reply_text("Finish setup first, then you can link your other device.")
            return
        code = await generate_link_code(db, user)

    im_addr = os.getenv("ARNIE_IMESSAGE_ADDRESS", "")
    if im_addr:
        # NOTE: do NOT put an sms:/tel: link in an InlineKeyboardButton — the
        # Telegram Bot API only accepts http/https/tg URLs in inline buttons and
        # rejects anything else with BUTTON_URL_INVALID, which made the whole
        # /link reply throw and the user saw NOTHING. Send the address + code as
        # plain, copyable text instead (always works, on every client).
        await update.message.reply_text(
            "to connect iMessage, open Messages on your iPhone and text the code "
            f"below to Arnie at <code>{im_addr}</code>.\n\n"
            "it links automatically. expires in 10 min.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "to connect your iMessage, copy the code below and text it to Arnie "
            "on iMessage. expires in 10 min."
        )
    # code as its own bubble — easy to long-press and copy/paste
    await update.message.reply_text(f"<code>{code}</code>", parse_mode="HTML")


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle proactive reminders on or off."""
    async with AsyncSessionLocal() as db:
        # Resolve to canonical — proactive reminder pref lives on the
        # canonical user_preferences row, not the platform-linked shim.
        user = await resolve_user(db, str(update.effective_user.id))
        prefs = user.preferences
        if not prefs:
            await update.message.reply_text("Finish setup first — tell me your name to get started.")
            return

        args = context.args
        if args and args[0].lower() in ("off", "stop", "disable", "0"):
            prefs.proactive_messaging_enabled = False
            await db.commit()
            await update.message.reply_text(
                "reminders off. i'll only chime in when you text me.",
                parse_mode="HTML"
            )
        elif args and args[0].lower() in ("on", "start", "enable", "1"):
            prefs.proactive_messaging_enabled = True
            await db.commit()
            await update.message.reply_text(
                "<b>reminders on.</b>\n\n"
                "i'll check in through the day:\n"
                "• morning, weight &amp; breakfast\n"
                "• midday, protein pacing\n"
                "• afternoon, workout nudge\n"
                "• evening, dinner &amp; calories left\n"
                "• night, closeout nudge\n\n"
                "all inside your wake/sleep window. say /remind off anytime to stop.",
                parse_mode="HTML"
            )
        else:
            status = "on" if prefs.proactive_messaging_enabled else "off"
            await update.message.reply_text(
                f"reminders are <b>{status}</b> right now.\n\n"
                "/remind on to turn check-ins on\n"
                "/remind off to turn them off",
                parse_mode="HTML"
            )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>arnie commands</b>\n\n"
        "/today    calories, macros &amp; workout status\n"
        "/ai       coaching insights on your day &amp; trends\n"
        "/week     last 7 days recap &amp; trends\n"
        "/me       profile, targets &amp; settings\n"
        "/dash     open your personal dashboard\n"
        "/remind   turn daily check-ins on or off\n"
        "/connect  link Whoop or Apple Health\n"
        "/reset    clear today's log or full reset\n\n"
        "<b>or just talk to me naturally:</b>\n"
        "<i>had chicken and rice</i>\n"
        "<i>bench 225x5 for 3 sets</i>\n"
        "<i>weight 191.4 this morning</i>\n"
        "<i>30 min incline walk</i>\n\n"
        "voice notes and food photos work too.\n\n"
        "new here? /howto walks you through getting the most out of me.",
        parse_mode="HTML"
    )


async def cmd_howto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """How to get the most out of Arnie — sent on /howto or /guide.

    Deterministic, in-voice copy (not LLM): this is the one place a new user can
    pull up the full 'how we work together' rundown on demand. The throughline is
    that Arnie gets sharper the more, and the more specifically, they log."""
    await update.message.reply_text(
        "<b>how to get the most out of me</b>\n\n"
        "i get sharper the more you feed me. that's the whole game. the basics:\n\n"
        "<b>1. log as it happens.</b> meals, workouts, weight, water — just text me in the "
        "moment. <i>had a chicken bowl</i>, <i>bench 185x5x3</i>, <i>191 this morning</i>. "
        "rough is fine, i do the math.\n\n"
        "<b>2. be specific when it counts.</b> portions, brands, how it was cooked — "
        "<i>6oz grilled</i> beats <i>some chicken</i>. but never stress it, i fill the gaps "
        "and ask only if it'll move the numbers.\n\n"
        "<b>3. talk, don't fill out forms.</b> voice notes and food photos both work. snap "
        "the plate or ramble the day and i'll sort it.\n\n"
        "<b>4. correct me.</b> if i call a portion or a number wrong, just say so — "
        "<i>no, that was a double</i>. i remember the fix and won't miss it next time.\n\n"
        "<b>5. tell me how you like to be coached.</b> blunt, gentle, more detail, less chat — "
        "say the word and i adjust.\n\n"
        "the more you log, the better i read your patterns and the sharper the coaching gets.\n\n"
        "check in anytime: /today  ·  /week  ·  /dash",
        parse_mode="HTML"
    )


# ── Bot entry point ───────────────────────────────────────────────────────────

async def _post_init(app: Application):
    await init_db()
    start_scheduler()

    # Register commands so Telegram shows the menu when user types "/".
    # Slimmed 12 → 5 (2026-06-12): only the daily-driver actions get a slot
    # in the "/"-popup. All other CommandHandlers below stay registered so
    # power-users typing /upgrade, /billing, /reset, /remind, /week, /ai
    # still get the response — we just stop advertising the long list. The
    # bot itself is the AI, so /ai as a separate menu item read as
    # redundant; /close was already dead (T1.1 removed the day-close state
    # but left the menu entry); /reset is destructive and doesn't belong
    # in the discovery menu.
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("today",   "Today's calories, macros & workout"),
        BotCommand("dash",    "Open your personal dashboard"),
        BotCommand("me",      "Profile, targets & settings"),
        BotCommand("connect", "Link Whoop or Apple Health"),
        BotCommand("link",    "Connect iMessage / iOS to this account"),
        BotCommand("howto",   "Get the most out of Arnie"),
        BotCommand("help",    "Commands & quick reference"),
    ])
    logger.info("Arnie is ready.")


async def _post_shutdown(app: Application):
    stop_scheduler()


def build_app() -> Application:
    """Build and configure the PTB Application without starting it.
    Note: _post_init / _post_shutdown are NOT registered here. main.py drives
    them explicitly so the same lifecycle works for both webhook and polling modes.
    """
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in your .env")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("howto",   cmd_howto))
    app.add_handler(CommandHandler("guide",   cmd_howto))
    app.add_handler(CommandHandler("today",   cmd_today))
    app.add_handler(CommandHandler("ai",      cmd_ai))
    app.add_handler(CommandHandler("me",      cmd_me))
    app.add_handler(CommandHandler("week",    cmd_history))
    app.add_handler(CommandHandler("dash",    cmd_dash))
    app.add_handler(CommandHandler("link",    cmd_link))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CommandHandler("billing", cmd_billing))
    app.add_handler(CommandHandler("connect", cmd_connect))
    app.add_handler(CommandHandler("reset",   cmd_reset))
    # Hidden but still functional
    app.add_handler(CommandHandler("targets", cmd_targets))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("memory",  cmd_memory))
    app.add_handler(CommandHandler("remind",  cmd_remind))
    app.add_handler(CommandHandler("whoop",   cmd_whoop))
    app.add_handler(CommandHandler("location", cmd_location))
    app.add_handler(CommandHandler("feedback",cmd_feedback))
    # Aliases
    app.add_handler(CommandHandler("log",      cmd_today))
    app.add_handler(CommandHandler("summary",  cmd_today))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    # Shared location — one-time share AND live-location updates (the latter arrive
    # as edited_message, so register that update type too). Both route to
    # handle_location, which reads update.effective_message.
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(
        filters.UpdateType.EDITED_MESSAGE & filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app


def run_bot():
    """Standalone runner — used for local dev without FastAPI."""
    logger.info("Starting Arnie bot (polling, standalone)...")
    build_app().run_polling(drop_pending_updates=True)
