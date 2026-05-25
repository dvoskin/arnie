"""
Telegram bot — receives all updates, orchestrates the full pipeline:
  multimodal parsing → context build → LLM → tool execution → response → memory
"""
import asyncio
import logging
import os
import random

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, Defaults, filters,
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

# ── Arnie's core system prompt (normal coaching mode) ─────────────────────────

_ARNIE_SYSTEM = """You are Arnie — a direct, sharp fitness and nutrition coach. You track everything and actually give a damn about results.

TOOL RULES (no exceptions):
- New food/drink mentioned → log_food() — one call per item, only for THIS message
- New workout/exercise → log_exercise() — one call per exercise, only for THIS message
- User states body weight → log_body_weight() — body weight only, never food weight
- User drinks water → log_water()
- "close the day" → close_day()
- User explicitly asks to change a setting or target → update_profile()
- DO NOT re-log anything already in today's log in the context
- ALWAYS write a text response with every tool call

RESPONSE STYLE — think "coach texting you," not ChatGPT essay:
- 1–3 short lines max for simple messages. Be punchy.
- When logging: confirm it + one useful data point (calories left, protein %, trend)
- Call out wins: weight dropping, protein streak, strong training week
- Reference real numbers: "you're 40g short on protein", "3rd push day this week"
- End with a short follow-up question sometimes — keep it alive
- No filler phrases, no "Great job!", no walls of text

FORMATTING — Telegram HTML only, never markdown:
- Bold: <b>text</b>  NOT **text**
- Line breaks for spacing, not headers or horizontal rules
- Short bullet points with • when listing multiple items
- Never use ##, ###, ***, ---, or markdown tables

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


def _welcome_message(name: str) -> str:
    return (
        f"You're all set, <b>{name}</b>. Let's get to work.\n\n"
        "Here's how to use me:\n"
        "• <b>Food</b> — just tell me what you ate: <i>\"had eggs and toast\"</i>\n"
        "• <b>Workouts</b> — <i>\"bench 185 4x5, OHP 115 3x8\"</i>\n"
        "• <b>Weight</b> — <i>\"191 lbs this morning\"</i>\n"
        "• <b>Questions</b> — <i>\"how am I doing on protein?\"</i>\n\n"
        "Use /today for a snapshot, /targets for your goals.\n\n"
        "Want me to check in on you throughout the day? Send /remind on."
    )


async def _run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        raw_text: str, source_type: str, db):
    """Core pipeline shared by all message types."""
    chat_id = update.effective_chat.id
    tg_user = update.effective_user
    user = await get_or_create_user(db, str(tg_user.id))

    # ── Onboarding ────────────────────────────────────────────────────────────
    in_onboarding = not user.onboarding_completed
    was_onboarding = in_onboarding  # remember before tools run

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

    # ── Detect onboarding just completed this turn ───────────────────────────
    just_completed = was_onboarding and not in_onboarding

    # ── Follow-up text after tool calls ──────────────────────────────────────
    # Onboarding just finished → send the welcome message, skip LLM follow-up
    # Still in onboarding → ALWAYS follow-up so next question is included
    # Normal mode → only follow-up when first pass had no text
    if just_completed:
        response_text = _welcome_message(user.name or "")
    else:
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


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Today's calories, protein, water, and workout status."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
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


async def cmd_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calorie and macro targets."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        p = user.preferences
        if not p or (not p.calorie_target and not p.protein_target):
            await update.message.reply_text(
                "No targets set yet. Tell me your calorie and protein goals and I'll lock them in.\n"
                'Example: "set my calorie target to 2400 and protein to 185g"'
            )
            return

        lines = ["<b>Your targets</b>", ""]
        if p.calorie_target:
            lines.append(f"Calories   <b>{p.calorie_target} kcal/day</b>")
        if p.protein_target:
            lines.append(f"Protein    <b>{p.protein_target}g/day</b>")

        # Derive carb/fat split from calories if both cal + protein known
        if p.calorie_target and p.protein_target:
            protein_cals = p.protein_target * 4
            remaining_cals = p.calorie_target - protein_cals
            fat_g = round(p.calorie_target * 0.25 / 9)
            carb_g = round((remaining_cals - fat_g * 9) / 4)
            if carb_g > 0:
                lines.append(f"Carbs      ~{carb_g}g/day  (implied)")
                lines.append(f"Fats       ~{fat_g}g/day  (implied)")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Age, weight, goal, experience."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))

        def _v(val, unit="", fallback="not set"):
            return f"{val}{unit}" if val is not None else fallback

        w_lbs = f"{user.current_weight_kg * 2.20462:.1f} lbs" if user.current_weight_kg else "not set"
        g_lbs = f"{user.goal_weight_kg * 2.20462:.1f} lbs" if user.goal_weight_kg else "not set"
        h_ft = ""
        if user.height_cm:
            inches_total = user.height_cm / 2.54
            h_ft = f"{int(inches_total // 12)}ft {int(inches_total % 12)}in  ({user.height_cm:.0f}cm)"

        lines = [
            f"<b>{user.name or 'Your'} profile</b>",
            "",
            f"Age        {_v(user.age)}",
            f"Sex        {_v(user.sex)}",
            f"Height     {h_ft or 'not set'}",
            f"Weight     {w_lbs}",
            f"Goal       {g_lbs}  ({_v(user.primary_goal)})",
            f"Experience {_v(user.training_experience)}",
            f"Diet       {user.dietary_preferences or 'none'}",
            f"Injuries   {user.injuries or 'none'}",
            f"Timezone   {_v(user.timezone)}",
        ]
        if user.preferences:
            p = user.preferences
            lines += [
                "",
                f"Coaching   {p.coaching_style or 'not set'}",
                f"Accountability  {p.accountability_level or 'not set'}",
            ]
            if p.wake_time and p.sleep_time:
                lines.append(f"Schedule   {p.wake_time} – {p.sleep_time}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Last 7 days recap."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        from db.queries import get_recent_logs, get_recent_weights
        logs = await get_recent_logs(db, user.id, days=7)
        weights = await get_recent_weights(db, user.id, days=7)
        prefs = user.preferences

        closed = [l for l in logs if l.status == "closed"]
        if not closed and not logs:
            await update.message.reply_text("No history yet — keep logging and it'll show up here.")
            return

        lines = ["<b>Last 7 days</b>", ""]
        for log in sorted((closed or logs), key=lambda l: l.date, reverse=True)[:7]:
            wo = "💪" if log.workout_completed else "  "
            cal_str = f"{log.total_calories:.0f}"
            if prefs and prefs.calorie_target:
                diff = log.total_calories - prefs.calorie_target
                cal_str += f" ({diff:+.0f})"
            pro_str = f"{log.total_protein:.0f}g"
            lines.append(f"{wo} <b>{log.date}</b>   {cal_str} kcal  {pro_str} protein")

        if weights:
            lines += ["", "<b>Weight</b>"]
            for w in sorted(weights, key=lambda w: w.timestamp, reverse=True)[:5]:
                lbs = w.weight_kg * 2.20462
                lines.append(f"  {w.timestamp.strftime('%b %d')}   {lbs:.1f} lbs  ({w.weight_kg:.1f}kg)")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """What Arnie knows about habits and tendencies."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        from memory.memory_manager import read_memory
        mem = await read_memory(user.telegram_id)
        if not mem or mem.strip() == "":
            await update.message.reply_text(
                "Nothing stored yet — memory builds up as we talk. "
                "The more you log, the sharper my coaching gets."
            )
            return
        # Telegram message limit is 4096 chars
        text = mem[:3800]
        await update.message.reply_text(f"<pre>{text}</pre>", parse_mode="HTML")


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close the day's log."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        if not log:
            await update.message.reply_text("Nothing to close — you haven't logged anything today.")
            return
        if log.status == "closed":
            await update.message.reply_text("Day's already closed.")
            return
        summary = await generate_closeout(user, log, db)
        await close_daily_log(db, log.id)
        await update.message.reply_text(**_fmt(summary))


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle proactive reminders on or off."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        prefs = user.preferences
        if not prefs:
            await update.message.reply_text("Finish setup first — tell me your name to get started.")
            return

        args = context.args
        if args and args[0].lower() in ("off", "stop", "disable", "0"):
            prefs.proactive_messaging_enabled = False
            await db.commit()
            await update.message.reply_text(
                "Reminders off. I'll only respond when you message me.",
                parse_mode="HTML"
            )
        elif args and args[0].lower() in ("on", "start", "enable", "1"):
            prefs.proactive_messaging_enabled = True
            await db.commit()
            await update.message.reply_text(
                "<b>Reminders on.</b>\n\n"
                "I'll check in at:\n"
                "• Morning — log your weight &amp; breakfast\n"
                "• Midday — protein pacing\n"
                "• Afternoon — workout nudge\n"
                "• Evening — dinner &amp; calories remaining\n"
                "• Night — closeout nudge\n\n"
                "All within your wake/sleep window. Turn off anytime with /remind off",
                parse_mode="HTML"
            )
        else:
            status = "on" if prefs.proactive_messaging_enabled else "off"
            await update.message.reply_text(
                f"Reminders are currently <b>{status}</b>.\n\n"
                "/remind on  — enable check-ins\n"
                "/remind off — disable",
                parse_mode="HTML"
            )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Arnie commands</b>\n\n"
        "/today    — calories, protein, water, workout\n"
        "/targets  — your calorie &amp; macro targets\n"
        "/profile  — age, weight, goal, experience\n"
        "/history  — last 7 days recap\n"
        "/memory   — what I know about your habits\n"
        "/close    — close today's log\n"
        "/remind   — toggle proactive check-ins\n\n"
        "<b>Just text naturally:</b>\n"
        "<i>Had chicken and rice</i>\n"
        "<i>Bench 225x5 for 3 sets</i>\n"
        "<i>Weight 191.4 this morning</i>\n"
        "<i>30 min incline walk</i>\n\n"
        "Voice notes and food photos work too.",
        parse_mode="HTML"
    )


# ── Bot entry point ───────────────────────────────────────────────────────────

async def _post_init(app: Application):
    await init_db()
    start_scheduler()

    # Register commands so Telegram shows the menu when user types "/"
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("today",   "Today's calories, protein, water & workout"),
        BotCommand("targets", "Your calorie & macro targets"),
        BotCommand("profile", "Age, weight, goal & experience"),
        BotCommand("history", "Last 7 days recap"),
        BotCommand("memory",  "What I know about your habits"),
        BotCommand("close",   "Close today's log"),
        BotCommand("remind",  "Toggle proactive check-ins on/off"),
        BotCommand("help",    "How to use Arnie"),
    ])
    logger.info("Arnie is ready.")


async def _post_shutdown(app: Application):
    stop_scheduler()


def run_bot():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in your .env")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("today",   cmd_today))
    app.add_handler(CommandHandler("targets", cmd_targets))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("memory",  cmd_memory))
    app.add_handler(CommandHandler("close",   cmd_close))
    app.add_handler(CommandHandler("remind",  cmd_remind))
    # Keep old aliases so existing users aren't broken
    app.add_handler(CommandHandler("log",      cmd_today))
    app.add_handler(CommandHandler("summary",  cmd_today))
    app.add_handler(CommandHandler("closeday", cmd_close))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting Arnie bot (polling)...")
    app.run_polling(drop_pending_updates=True)
