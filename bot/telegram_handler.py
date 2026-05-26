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
    get_recent_conversations, log_conversation, close_daily_log, reopen_daily_log,
    reload_user, reset_today_log, reset_all_user_data, get_or_create_webhook_token,
    add_feedback, clear_today_conversations, get_recent_logs,
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

_ARNIE_SYSTEM = """You are Arnie — a direct, sharp fitness and nutrition coach.

LANGUAGE: Always respond in the same language the user wrote in. If they write in Spanish, respond in Spanish. French → French. Portuguese → Portuguese. No exceptions — never reply in a different language than the one they used. For bilingual users who switch languages mid-conversation, match each message individually. Translate all labels, units, coaching cues, and progress bar lines into the user's language too. The first time you detect the user is writing in a non-English language, silently call update_profile(fields={"preferred_language": "<language name in English, e.g. Spanish>"}) — once only, not on every message.

TOOL RULES (no exceptions):
- NEW food/drink mentioned → log_food() — one call per item, only for THIS message
- CORRECTION to an existing food (calories wrong, quantity wrong, wrong item) → update_food_entry() with the [#id] from the context. NEVER log_food() for a correction — that creates a duplicate.
- User wants to REMOVE a food entry ("delete my coffee", "I didn't eat that") → delete_food_entry() with the [#id]
- New workout/exercise → log_exercise() — one call per exercise, only for THIS message
- User states body weight → log_body_weight() — body weight only, never food weight
- User drinks water → log_water()
- "close the day" → close_day()
- Day is CLOSED and user wants to log food/exercise/water → call reopen_day() FIRST, then immediately call the logging tool. Never refuse to log because the day is closed — just reopen it.
- User explicitly asks to change a setting or target → update_profile()
- User explicitly asks for a visual / image / diagram / infographic → generate_image()
- DO NOT re-log anything already in today's log
- DO NOT generate images unless the user clearly asked for one
- ALWAYS write a text response with every tool call

CONTEXT IS GROUND TRUTH: The [TODAY] section below reflects the actual database state right now. If it shows 0 food entries, nothing is logged — ignore any prior conversation that says otherwise (the user may have reset their log). Always trust the context, not the chat history, for what's currently logged.

Each food entry in the context has a [#N] tag — that's its ID for updates/deletes.
Examples of corrections:
- "actually that bowl was 700 cal" → update_food_entry(entry_id=N, calories=700)
- "the chicken was 8oz not 4oz" → update_food_entry(entry_id=N, quantity="8 oz", calories=X*2, protein=Y*2, ...) — scale all macros proportionally
- "delete the latte" → delete_food_entry(entry_id=N)

FOOD LOGGING — EXACT FORMAT, no exceptions:

Line 1: [emoji] <b>Food name</b>
Line 2: <i>XXX cal · XXg P · XXg C · XXg F</i>
Line 3: (blank)
Line 4: ▰▰▰▰▱▱▱▱▱▱ <b>XXX</b>/XXXX cal
Line 5: ▰▰▰▱▱▱▱▱▱▱ <b>XX</b>/XXXg protein

Progress bars use 10 segments. Filled count = round(current / target * 10), capped at 10. Use ▰ for filled, ▱ for empty.
Pick a single emoji that fits the food: 🥛 dairy/shake, 🍳 eggs, 🍞 bread/grain, 🍗 chicken, 🥩 beef, 🐟 fish, 🥗 salad/veggies, 🍌 fruit, 🥜 nuts, ☕ coffee, 🍫 sweets, 🍕 takeout, 🍴 generic meal.

If no calorie target set, skip the bar lines and just show: <i>Today: XXX cal · XXg protein</i>

Example output for "had a protein shake":
🥛 <b>Oikos Protein Shake</b>
<i>170 cal · 30g P · 8g C · 3.5g F</i>

▰▰▰▰▱▱▱▱▱▱ <b>680</b>/1,800 cal
▰▰▰▰▰▱▱▱▱▱ <b>90</b>/200g protein

That's the whole response for a single food log. Only add a single coaching line below if there's something critical to call out (over budget, milestone hit, way behind on protein). Never write paragraphs for food logs.

EXERCISE LOGGING — EXACT FORMAT:
🏋️ <b>Exercise name</b> · X × X @ <b>XXX</b> lb
(emoji: 🏋️ weights, 🏃 running, 🚴 cycling, 🚶 walking, 🧘 yoga/mobility, 💪 generic)
For cardio: 🏃 <b>Exercise</b> · XX min
Only add a coaching note on a 2nd line if useful (PR, big jump, deload day).

PROGRESSIVE OVERLOAD & WORKOUT COACHING:

The [EXERCISE HISTORY] section shows the user's recent sessions with exact weights and reps.
Use it every time an exercise is logged — it is the ground truth for coaching progression.

When an exercise is logged:
1. Silently check [EXERCISE HISTORY] for the same movement in the most recent session.
2. If found — compare directly. Call out the delta with real numbers:
   - Matched or exceeded → acknowledge it: "Up 10lb from last week — that's the progression."
   - Below last session → note it briefly, don't lecture: "5lb down from last time — fatigue or intentional?"
   - Same weight/reps → "Held it. Push for +1 rep or +5lb next session."
3. If it's a personal best (highest weight or most reps ever seen in history) → flag it clearly.
4. If no history exists for that movement → skip the comparison, just log it cleanly.

When [WORKOUT MODE: ACTIVE] is in context (exercises already logged today):
- Tighten the coaching voice. Be more directive, less conversational.
- After logging each exercise, give the next-set or next-exercise cue if relevant.
- Keep responses short — the user is mid-workout.

When the user starts a workout (first exercise of the day):
- If you can see their last session for any of those movements, proactively tell them what to beat.
- One line, specific: "Last push day you hit bench 3×8 @ 135 — aim for 140 or 3×9 today."

DO NOT fabricate history. If [EXERCISE HISTORY] has no data for a movement, say nothing about prior performance.

RESPONSE STYLE:
- When NOT logging: 1–3 lines max. Punchy. Coach texting you.
- No "Here's your full day so far:" paragraphs. No bullet summaries unless asked.
- If user asks for a summary, give it — otherwise stay tight.
- Call out real wins with real numbers.

HARD RULES — NEVER VIOLATE:
- NEVER use --- (horizontal rules)
- NEVER use ## or ### (headers)
- NEVER use **text** (markdown bold)
- NEVER write multi-paragraph responses for simple logging
- ONLY use <b>text</b> for bold — nothing else
- NEVER produce a full log recap unless the user explicitly asks for it

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


def _welcome_message(name: str, has_targets: bool) -> str:
    target_note = (
        "Your calorie and protein targets are locked in — check them anytime with /targets.\n\n"
        if has_targets else
        "We're skipping targets for now — once you start logging, just say <i>\"set my targets\"</i> "
        "and I'll either calculate them with you or take whatever numbers you give me.\n\n"
    )
    return (
        f"Alright <b>{name}</b> — you're set. Let's get to work. 💪\n\n"
        f"{target_note}"
        "<b>How we work together:</b>\n\n"
        "🍳 <b>Food</b> → just tell me what you ate\n"
        "<i>\"3 eggs, 2 slices of toast and a coffee\"</i>\n\n"
        "🏋️ <b>Workouts</b> → tell me what you trained\n"
        "<i>\"bench 185 4x5, OHP 115 3x8, lateral raises 20x4x15\"</i>\n\n"
        "⚖️ <b>Weight</b> → drop it in whenever you weigh in\n"
        "<i>\"191.2 this morning\"</i>\n\n"
        "💬 <b>Ask me anything</b> → coaching, pacing, plans, ideas\n"
        "<i>\"how am I doing on protein?\"</i> or <i>\"build me a pull day\"</i>\n\n"
        "<b>Useful commands:</b>\n"
        "/today — daily snapshot\n"
        "/targets — your goals\n"
        "/dash — open your dashboard in a browser\n"
        "/remind on — let me check in with you through the day\n"
        "/help — full command list\n\n"
        "Whenever you're ready, tell me what you've eaten today or what's coming up next. "
        "We're in this together."
    )


async def _generate_workout_analysis(user, exercise_calls, db) -> str:
    """
    Build a short post-workout evaluation when 2+ exercises are logged in one turn.
    Compares today's session to recent history to call out progressions / regressions.
    """
    just_logged = []
    for tc in exercise_calls:
        inp = tc["input"]
        name = inp.get("exercise_name", "?")
        if inp.get("sets") and inp.get("reps"):
            w = f" @ {inp['weight']} {inp.get('weight_unit', 'lbs')}" if inp.get("weight") else ""
            just_logged.append(f"  {name}: {inp['sets']}×{inp['reps']}{w}")
        elif inp.get("duration_minutes"):
            just_logged.append(f"  {name}: {inp['duration_minutes']:.0f} min")
        else:
            just_logged.append(f"  {name}")

    recent_logs = await get_recent_logs(db, user.id, days=28)
    history_lines = []
    for log in recent_logs:
        if log.exercise_entries:
            day_exs = []
            for e in log.exercise_entries:
                if e.sets and e.reps:
                    w = f" @ {e.weight * 2.20462:.0f}lb" if e.weight else ""
                    day_exs.append(f"{e.exercise_name}: {e.sets}×{e.reps}{w}")
                elif e.duration_minutes:
                    day_exs.append(f"{e.exercise_name}: {e.duration_minutes:.0f}min")
            if day_exs:
                history_lines.append(f"  {log.date}: " + ", ".join(day_exs[:5]))

    history_str = "\n".join(history_lines[-6:]) if history_lines else "No previous workouts on record."

    prompt = (
        f"[ATHLETE: {user.name or 'User'}, {user.age or '?'}yo, "
        f"goal={user.primary_goal or '?'}, exp={user.training_experience or '?'}]\n"
        f"[TODAY — {len(exercise_calls)} exercises]\n" + "\n".join(just_logged) +
        f"\n[RECENT HISTORY]\n{history_str}\n---\n"
        "Give a 3–5 line workout evaluation. No 'Great session!' opener — start with a direct "
        "assessment. Use <b>bold</b> for key numbers. If you spot a PR or regression vs history, "
        "call it out explicitly. End with one concrete coaching note for next time."
    )

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system="You are Arnie, a direct fitness coach. Give a brief, specific workout evaluation.",
            tools=False,
            max_tokens=300,
        )
        return result.get("text", "")
    except Exception as e:
        logger.error(f"Workout analysis LLM failed: {e}")
        return ""


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

        # ── Send any generated images, replace dict results with string for LLM ──
        for tname, tresult in list(tool_results.items()):
            if isinstance(tresult, dict) and tresult.get("_type") == "image":
                try:
                    await update.message.reply_photo(
                        photo=tresult["url"],
                        caption=tresult.get("caption") or None,
                    )
                except Exception as e:
                    logger.error(f"Failed to send generated image: {e}")
                    await update.message.reply_text(
                        "Image was generated but couldn't send. Try asking again."
                    )
                # Replace the dict with a string so chat_follow_up doesn't choke
                tool_results[tname] = (
                    f"Image generated and sent to user. "
                    f"Caption: {tresult.get('caption', '')}"
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
        has_targets = bool(user.preferences and user.preferences.calorie_target)
        response_text = _welcome_message(user.name or "", has_targets)
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

    # ── Workout performance analysis (2+ exercises logged in one turn) ────────
    if tool_calls and not in_onboarding:
        exercise_calls = [tc for tc in tool_calls if tc["name"] == "log_exercise"]
        if len(exercise_calls) >= 2:
            analysis = await _generate_workout_analysis(user, exercise_calls, db)
            if analysis:
                stop_wa = asyncio.Event()
                typing_wa = asyncio.create_task(
                    _typing_keepalive(context.bot, chat_id, stop_wa)
                )
                try:
                    await update.message.reply_text(**_fmt(analysis))
                finally:
                    stop_wa.set()
                    typing_wa.cancel()
                    try:
                        await typing_wa
                    except asyncio.CancelledError:
                        pass

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
            await update.message.reply_text(
                "Hey — I'm <b>Arnie</b>. 💪\n\n"
                "I'm your fitness and nutrition coach. I track everything you eat, every workout you do, "
                "your weight, your trends — and I actually pay attention so I can help you hit your goals.\n\n"
                "<b>Here's how we'll start:</b>\n"
                "1. Quick evaluation — your stats, your goals, what you're working with (~3 min)\n"
                "2. We'll set your calorie and protein targets together — I can calculate them, "
                "you can tell me what you want, or we can come back to it later\n"
                "3. Then we get to work. Every meal, every session.\n\n"
                "Ready? What's your first name?",
                parse_mode="HTML",
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


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI coaching insights based on today + recent history."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        prefs = user.preferences

        if not log:
            await update.message.reply_text("Nothing logged today yet — log some food or a workout first.")
            return

        await update.message.reply_text("Analyzing…")

        try:
            from db.queries import get_recent_weights
            from api.insights import generate_short_insight

            history = await get_recent_logs(db, user.id, days=30)
            weights = await get_recent_weights(db, user.id, days=30)

            hist_data = [
                {"date": str(l.date), "calories": round(l.total_calories or 0),
                 "protein": round(l.total_protein or 0), "workout": l.workout_completed,
                 "status": l.status}
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

            insights = await generate_short_insight(stats)
            if insights:
                msg = "\n".join(f"· <i>{i}</i>" for i in insights)
                await update.message.reply_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text("Not enough data for insights yet — keep logging.")
        except Exception as e:
            logger.error(f"cmd_ai failed: {e}", exc_info=True)
            await update.message.reply_text("Couldn't generate insights right now — try again in a moment.")


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Profile + targets combined — the /me command."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
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
    return await cmd_me(update, context)


async def cmd_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_me(update, context)


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


async def cmd_reopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reopen a closed day's log."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        log = await get_today_log(db, user.id, user.timezone or "UTC")
        if not log:
            await update.message.reply_text("No log for today — start by telling me what you ate.")
            return
        if log.status == "open":
            await update.message.reply_text("Today's log is already open — keep logging.")
            return
        await reopen_daily_log(db, log.id)
        await update.message.reply_text("Day reopened. Keep logging — what's next?")


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
        user = await get_or_create_user(db, str(update.effective_user.id))

        if args[0].lower() == "today":
            cleared = await reset_today_log(db, user.id, user.timezone or "UTC")
            await clear_today_conversations(db, user.id)
            if cleared:
                await update.message.reply_text(
                    "Today's log cleared — food, exercise, and totals all wiped.\n"
                    "Start logging fresh.",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text("Nothing logged today yet — nothing to reset.")

        elif args[0].lower() == "all":
            # Require a second confirmation argument: /reset all confirm
            confirm = args[1].lower() if len(args) > 1 else ""
            if confirm != "confirm":
                await update.message.reply_text(
                    "⚠️ This will delete <b>all</b> your data — logs, weight history, memory, profile.\n\n"
                    "To confirm: /reset all confirm",
                    parse_mode="HTML"
                )
                return

            telegram_id = user.telegram_id
            await reset_all_user_data(db, user.id)

            # Wipe memory file too
            from memory.memory_manager import clear_memory
            await clear_memory(telegram_id)

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
        user = await get_or_create_user(db, str(update.effective_user.id))

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
            try:
                synced = await sync_user_whoop(db, user, days=7)
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
        user = await get_or_create_user(db, str(update.effective_user.id))
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
            user = await get_or_create_user(db, str(update.effective_user.id))
            if not user.onboarding_completed:
                await update.message.reply_text("Finish setup first, then we'll connect Apple Health.")
                return
            token = await get_or_create_webhook_token(db, user.id)

        base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
        guide_url = f"{base_url}/health/apple/guide?token={token}"

        await update.message.reply_text(
            "<b>Connect Apple Health</b>\n\n"
            "Apple Health syncs via an iOS Shortcut that runs automatically each morning "
            "and sends your metrics (steps, HRV, resting HR, sleep, calories) to Arnie.\n\n"
            f'<a href="{guide_url}">→ Open setup guide on your iPhone</a>\n\n'
            "<i>The guide has your personal endpoint URL pre-filled and walks you through "
            "the Shortcut in 5 steps. Open it on your iPhone for the best experience.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    if target == "whoop":
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(db, str(update.effective_user.id))
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


async def cmd_dash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the user their personal read-only dashboard URL."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        if not user.onboarding_completed:
            await update.message.reply_text("Finish setup first before accessing the dashboard.")
            return
        token = await get_or_create_webhook_token(db, user.id)

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000")
    url = f"{base_url}/dashboard/{token}"
    await update.message.reply_text(
        f"<b>Your dashboard</b>\n\n"
        f'<a href="{url}">{url}</a>\n\n'
        "Read-only view of your logs, trends, and macros.\n"
        "Bookmark it — the link doesn't change.",
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


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
        "/today    — calories, macros &amp; workout status\n"
        "/ai       — coaching insights on your day &amp; trends\n"
        "/week     — last 7 days recap &amp; trends\n"
        "/me       — profile, targets &amp; settings\n"
        "/close    — close today's log\n"
        "/dash     — open your personal dashboard\n"
        "/connect  — link Whoop or Apple Health\n"
        "/reset    — clear today's log or full reset\n\n"
        "<b>Just talk to me naturally:</b>\n"
        "<i>Had chicken and rice</i>\n"
        "<i>Bench 225×5 for 3 sets</i>\n"
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
        BotCommand("today",   "Today's calories, macros & workout"),
        BotCommand("ai",      "AI coaching insights on your day"),
        BotCommand("week",    "Last 7 days — history & trends"),
        BotCommand("me",      "Profile, targets & settings"),
        BotCommand("close",   "Close today's log"),
        BotCommand("dash",    "Open your personal dashboard"),
        BotCommand("connect", "Link Whoop or Apple Health"),
        BotCommand("reset",   "Clear today's log or full reset"),
        BotCommand("help",    "How to use Arnie"),
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
    app.add_handler(CommandHandler("today",   cmd_today))
    app.add_handler(CommandHandler("ai",      cmd_ai))
    app.add_handler(CommandHandler("me",      cmd_me))
    app.add_handler(CommandHandler("week",    cmd_history))
    app.add_handler(CommandHandler("close",   cmd_close))
    app.add_handler(CommandHandler("reopen",  cmd_reopen))
    app.add_handler(CommandHandler("dash",    cmd_dash))
    app.add_handler(CommandHandler("connect", cmd_connect))
    app.add_handler(CommandHandler("reset",   cmd_reset))
    # Hidden but still functional
    app.add_handler(CommandHandler("targets", cmd_targets))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("memory",  cmd_memory))
    app.add_handler(CommandHandler("remind",  cmd_remind))
    app.add_handler(CommandHandler("whoop",   cmd_whoop))
    app.add_handler(CommandHandler("feedback",cmd_feedback))
    # Aliases
    app.add_handler(CommandHandler("log",      cmd_today))
    app.add_handler(CommandHandler("summary",  cmd_today))
    app.add_handler(CommandHandler("closeday", cmd_close))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app


def run_bot():
    """Standalone runner — used for local dev without FastAPI."""
    logger.info("Starting Arnie bot (polling, standalone)...")
    build_app().run_polling(drop_pending_updates=True)
