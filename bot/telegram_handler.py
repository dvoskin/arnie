"""
Telegram bot — receives all updates, orchestrates the full pipeline:
  multimodal parsing → context build → LLM → tool execution → response → memory
"""
import asyncio
import logging
import os
import random

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

from db.database import AsyncSessionLocal, init_db
from db.queries import (
    get_or_create_user, get_or_create_today_log, get_today_log,
    get_recent_conversations, log_conversation, close_daily_log, reload_user,
)
from core.llm import chat, chat_follow_up
from core.context_builder import build_context, fmt_log
from handlers.onboarding import build_onboarding_system
from handlers.tool_executor import execute_tool_calls
from handlers.daily_closeout import generate_closeout
from memory.reflection import maybe_update_memory
from multimodal.voice_handler import process_voice
from multimodal.image_handler import process_general_image
from scheduler.proactive_scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def _fmt(text: str) -> dict:
    """Convert **markdown** bold to Telegram HTML. Returns kwargs for reply_text."""
    import re
    import html as _html
    parts = re.split(r'(\*\*(?:.|\n)*?\*\*)', text)
    result = []
    for part in parts:
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            result.append(f'<b>{_html.escape(part[2:-2])}</b>')
        else:
            result.append(_html.escape(part))
    return {"text": ''.join(result), "parse_mode": "HTML"}

# ── Arnie's core system prompt (normal coaching mode) ─────────────────────────

_ARNIE_SYSTEM = """You are Arnie — a sharp, engaged fitness and nutrition coach who genuinely cares about results. You have full memory and track everything the user logs.

TOOL USAGE RULES (follow exactly — no exceptions):
- User eats or drinks anything NEW → call log_food() — one call per food item, only for THIS message
- User reports a NEW workout or exercise → call log_exercise() — one call per exercise, only for THIS message
- User states their body weight → call log_body_weight() — ONLY for body weight, never food weight
- User drinks water → call log_water()
- User says "close the day" → call close_day()
- User explicitly asks to change a profile setting or target → call update_profile()
- DO NOT re-log food/exercise that already appears in today's log shown in the context.
- DO NOT call update_profile() for logging. DO NOT call log_body_weight() for food weights.
- ALWAYS write a text response alongside every tool call.

RESPONSE STYLE:
- 2–4 lines max unless user asked a big question. Tight and punchy.
- Warm but direct — like a good coach who's also in your corner. Not robotic, not a hype machine.
- When logging food/exercise: confirm it, then give one useful insight (pacing, progress, trend).
- Proactively call out progress: weight trending down, protein streak, good training week.
- Reference past data naturally: "you hit 178g protein yesterday", "that's 3 push days this week".
- If they're close to a goal or milestone, mention it — make them feel the progress.
- Ask a follow-up question occasionally to keep the conversation alive.

FORMATTING — use HTML tags, not markdown asterisks:
- Bold: <b>text</b>  (NOT **text**)
- Keep structure with line breaks and dashes, not headers.
- Never use markdown like **word** or _word_.

Context is below."""


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


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _build_messages(db, user_id: int, current_text: str):
    """Build the messages list: recent history + current message."""
    recent = await get_recent_conversations(db, user_id, limit=6)
    msgs = []
    for conv in reversed(recent):
        msgs.append({"role": "user", "content": conv.raw_message or ""})
        msgs.append({"role": "assistant", "content": conv.response or ""})
    msgs.append({"role": "user", "content": current_text})
    return msgs


async def _run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        raw_text: str, source_type: str, db):
    """Core pipeline shared by all message types."""
    chat_id = update.effective_chat.id
    tg_user = update.effective_user
    user = await get_or_create_user(db, str(tg_user.id))

    # ── Onboarding ────────────────────────────────────────────────────────────
    in_onboarding = not user.onboarding_completed

    if not in_onboarding:
        today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        context_str = await build_context(user, today_log, db)
        system = f"{_ARNIE_SYSTEM}\n\n{context_str}"
    else:
        today_log = None
        system = build_onboarding_system(user)  # dynamic — reflects current saved state

    # ── Conversation history + current message ────────────────────────────────
    messages = await _build_messages(db, user.id, raw_text)

    # ── LLM call with typing indicator ────────────────────────────────────────
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_keepalive(context.bot, chat_id, stop_typing)
    )
    try:
        result = await chat(messages, system, tools=True, max_tokens=1024)
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    response_text = result["text"]
    tool_calls = result["tool_calls"]
    raw_content = result["raw_content"]

    # ── Execute tools ─────────────────────────────────────────────────────────
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
            tool_calls, user, _log_for_tools, db, source_type
        )
        user = await reload_user(db, user.id)
        if today_log and hasattr(today_log, "id") and today_log.id:
            await db.refresh(today_log)

        # Rebuild system prompt with updated profile state
        in_onboarding = not user.onboarding_completed
        if in_onboarding:
            system = build_onboarding_system(user)

    # ── Follow-up text after tool calls ──────────────────────────────────────
    # During onboarding: ALWAYS do follow-up so the next question is included.
    # Normal mode: only when the first pass had no text at all.
    need_followup = (tool_calls and raw_content and
                     (in_onboarding or not response_text))
    if need_followup:
        stop_typing2 = asyncio.Event()
        typing_task2 = asyncio.create_task(
            _typing_keepalive(context.bot, chat_id, stop_typing2)
        )
        try:
            response_text = await chat_follow_up(
                messages, raw_content, tool_calls, tool_results, system, max_tokens=400
            )
        finally:
            stop_typing2.set()
            typing_task2.cancel()
            try:
                await typing_task2
            except asyncio.CancelledError:
                pass

    if not response_text:
        response_text = "Got it."

    # ── Send response ─────────────────────────────────────────────────────────
    await update.message.reply_text(**_fmt(response_text))

    # ── Persist conversation ──────────────────────────────────────────────────
    await log_conversation(db, user.id, raw_text, response_text, source_type=source_type)

    # ── Background memory reflection (~10% of turns) ─────────────────────────
    if not in_onboarding and random.random() < 0.10:
        await maybe_update_memory(user, raw_text, response_text, db)


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not text.strip():
        return
    async with AsyncSessionLocal() as db:
        await _run_pipeline(update, context, text, "text", db)


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

        await update.message.reply_text(f'🎙 "{transcript}"')
        await _run_pipeline(update, context, transcript, "voice", db)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        photo_data = bytes(await photo_file.download_as_bytearray())
        caption = update.message.caption or ""

        analysis = await process_general_image(photo_data, caption)
        if not analysis:
            await update.message.reply_text(
                "Couldn't analyse the image. "
                "Make sure ANTHROPIC_API_KEY is set for image support."
            )
            return

        combined = f"[Photo] {caption}\nImage content: {analysis}"
        await update.message.reply_text(f"🔍 I see: {analysis[:200]}...")
        await _run_pipeline(update, context, combined, "image", db)


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        if user.onboarding_completed:
            today_log = await get_today_log(db, user.id, user.timezone or "UTC")
            msg = (f"Hey {user.name}, welcome back.\n"
                   f"{'No log yet today — start typing.' if not today_log else fmt_log(today_log)}")
            await update.message.reply_text(**_fmt(msg))
        elif user.name:
            onb_sys = build_onboarding_system(user)
            for line in onb_sys.splitlines():
                if line.startswith('NEXT REQUIRED QUESTION:'):
                    q = line.split('"')[1] if '"' in line else "What's next?"
                    await update.message.reply_text(**_fmt(f"Hey {user.name}, still setting you up. {q}"))
                    break
        else:
            await update.message.reply_text(
                "Hey — I'm Arnie. Your no-BS fitness and nutrition coach.\n\n"
                "I'll remember what matters, track your food and training, "
                "and hold you accountable.\n\n"
                "Let's get you set up. What's your name?"
            )


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        await update.message.reply_text(**_fmt(fmt_log(log) if log else "No log today yet."))


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        if not log:
            await update.message.reply_text("Nothing logged today yet.")
            return
        prefs = user.preferences
        cal_str = f"{log.total_calories:.0f}"
        if prefs and prefs.calorie_target:
            rem = prefs.calorie_target - log.total_calories
            cal_str += f" / {prefs.calorie_target}  ({rem:+.0f})"
        pro_str = f"{log.total_protein:.0f}g"
        if prefs and prefs.protein_target:
            rem_p = prefs.protein_target - log.total_protein
            pro_str += f" / {prefs.protein_target}g  ({rem_p:+.0f}g)"
        lines = [
            f"<b>Today — {log.date}</b>",
            f"Calories:  {cal_str}",
            f"Protein:   {pro_str}",
            f"Carbs:     {log.total_carbs:.0f}g  |  Fats: {log.total_fats:.0f}g",
            f"Water:     {log.total_water_ml:.0f}ml",
            f"Workout: {'✓' if log.workout_completed else '✗'}   Cardio: {'✓' if log.cardio_completed else '✗'}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_closeday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        if not log:
            await update.message.reply_text("Nothing to close today.")
            return
        if log.status == "closed":
            await update.message.reply_text("Day already closed.")
            return
        summary = await generate_closeout(user, log, db)
        await close_daily_log(db, log.id)
        await update.message.reply_text(**_fmt(summary))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Arnie — fitness &amp; nutrition coach</b>\n\n"
        "Just text naturally:\n"
        "- <i>Had chicken and rice</i>\n"
        "- <i>Bench 225x5 for 3 sets</i>\n"
        "- <i>Weight 191.4 this morning</i>\n"
        "- <i>30 min incline walk</i>\n"
        "- <i>Close the day</i>\n\n"
        "<b>Commands:</b>\n"
        "/log — today's log\n"
        "/summary — macro summary\n"
        "/closeday — close out today\n\n"
        "Voice notes and food photos work too.",
        parse_mode="HTML"
    )


# ── Bot entry point ───────────────────────────────────────────────────────────

async def _post_init(app: Application):
    await init_db()
    start_scheduler()
    logger.info("Arnie is ready.")


async def _post_shutdown(app: Application):
    stop_scheduler()


def run_bot():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in your .env")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("closeday", cmd_closeday))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting Arnie bot (polling)...")
    app.run_polling(drop_pending_updates=True)
