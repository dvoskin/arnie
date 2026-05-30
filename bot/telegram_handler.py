"""
Telegram bot — receives all updates, orchestrates the full pipeline:
  multimodal parsing → context build → LLM → tool execution → response → memory
"""
import asyncio
import logging
import os
import random

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
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
from core.platform import React, onboarding_reaction, detect_moment
from handlers.onboarding import (
    build_onboarding_system, get_onboarding_keyboard, is_onboarding_complete,
)
from handlers.tool_executor import execute_tool_calls, deterministic_confirmation
from handlers.daily_closeout import generate_closeout
from memory.reflection import maybe_update_memory
from multimodal.voice_handler import process_voice
from multimodal.image_handler import process_general_image
from scheduler.proactive_scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

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

# Legacy marker so we can confirm the prompt loaded correctly
_PROMPT_VERSION = "v2.0-modular"

# ── Dead code below — keeping temporarily until all imports verified ──────────
_DEAD_ARNIE_SYSTEM = """REMOVED — see core/prompts/arnie.py

LANGUAGE: Always respond in the same language the user wrote in. If they write in Spanish, respond in Spanish. French → French. Portuguese → Portuguese. No exceptions — never reply in a different language than the one they used. For bilingual users who switch languages mid-conversation, match each message individually. Translate all labels, units, coaching cues, and progress bar lines into the user's language too. The first time you detect the user is writing in a non-English language, silently call update_profile(fields={"preferred_language": "<language name in English, e.g. Spanish>"}) — once only, not on every message.

TOOL RULES (no exceptions):
- NEW food/drink mentioned → log_food() — one call per item, only for THIS message
- CORRECTION to an existing food (calories wrong, quantity wrong, wrong item) → update_food_entry() with the [#id] from the context. NEVER log_food() for a correction — that creates a duplicate.
- User wants to REMOVE a food entry ("delete my coffee", "I didn't eat that") → delete_food_entry() with the [#id]
- New workout/exercise → log_exercise() — one call per exercise, only for exercises NOT already in today's context
- If an exercise is already listed in [TODAY] with a [#id], it's already logged — do NOT call log_exercise() again for it
- CORRECTION to an existing exercise (wrong weight, sets, reps) → update_exercise_entry() with the [#id]. NEVER log_exercise() for a correction — that creates a duplicate.
- User wants to REMOVE an exercise ("delete my bench", "I didn't do that set") → delete_exercise_entry() with the [#id]
- User states body weight → log_body_weight() — body weight only, never food weight
- User drinks water → log_water()
- "close the day" → close_day()
- Day is CLOSED and user wants to log food/exercise/water → call reopen_day() FIRST, then immediately call the logging tool. Never refuse to log because the day is closed — just reopen it.
- User explicitly asks to change a setting or target → update_profile()
- User explicitly asks for a visual / image / diagram / infographic → generate_image()
- DO NOT re-log anything already in today's log
- DO NOT generate images unless the user clearly asked for one
- ALWAYS write a text response with every tool call

FOOD HISTORY — USE IT: The [FOOD HISTORY] section lists every food the user has ever logged with exact macros. When they reference something they've had before ("the Oikos shake", "same as yesterday", "my usual breakfast"), look it up there first and log it immediately — no questions needed. Never say "I don't have that in your history" if it's in [FOOD HISTORY].

CONTEXT IS GROUND TRUTH: The [TODAY] section below reflects the actual database state right now. If it shows 0 food entries, nothing is logged — ignore any prior conversation that says otherwise (the user may have reset their log). Always trust the context, not the chat history, for what's currently logged.

Each food entry and exercise entry in the context has a [#N] tag — that's its ID for updates/deletes only. NEVER mention entry numbers to the user. Always refer to items by name ("the chicken", "your bench press", "the squat").

CLARIFICATION vs. NEW LOG — read intent carefully:
- If the user's message refers back to food they just described or that's already in the log ("that was a bowl", "it didn't have sauce", "I forgot to mention..."), treat it as context or a correction to the existing entry — do NOT log it again as a new item.
- Only call log_food() for food that is genuinely new and not already captured.
- When a follow-up message adds detail about something just logged, update the existing entry if the macros need changing, or simply acknowledge if nothing needs updating.

Examples of corrections:
- "actually that bowl was 700 cal" → update_food_entry(entry_id=N, calories=700)
- "the chicken was 8oz not 4oz" → update_food_entry(entry_id=N, quantity="8 oz", calories=X*2, protein=Y*2, ...) — scale all macros proportionally
- "delete the latte" → delete_food_entry(entry_id=N)
- "that bowl didn't have sauce" → update if sauce was logged, otherwise just acknowledge ("Got it, logged without sauce")

FOOD ACCURACY — ESTIMATE HIGH, DECOMPOSE COMPOUND ITEMS, ASK WHEN IT MATTERS:

COMPOUND ITEM RULE — always decompose mentally before logging:
Every item with multiple components (bread + butter + topping, pasta + sauce, salad + dressing) must be estimated part-by-part, then summed. Never treat the whole thing as one undifferentiated blob — that's where systematic underestimates happen.
  Baguette/toast + butter: bread calories first, then add butter separately.
  Pasta + sauce: pasta weight, then sauce type and quantity separately.
  Salad + dressing: greens/veg base, then protein, then dressing.

FAT ADDITION DEFAULTS — when quantity not specified, assume a real serving:
• "with butter" on bread/toast → 15–20g butter = 108–144 cal, 12–16g fat. Never assume "just a scrape" unless user says "light" or "a little butter." French/café-style bread always gets generous butter.
• "fried in butter" → add 10–15g absorbed fat beyond the food itself
• "drizzled with olive oil" or "with oil" → at minimum 1 tbsp = 120 cal, 14g fat
• "with cream" or "cream sauce" → add 80–120 cal, 8–10g fat per serving
• "with dressing" → see SALAD clarification rule below

COFFEE WITH MILK STANDARDS — never underestimate:
• Cappuccino (standard ~180ml) with whole milk → 80–100 cal, 4–5g P, 6–8g C, 3–4g F
• Flat white (smaller) → 90–110 cal
• Latte (12oz / 350ml) → 150–190 cal
• Americano / espresso → 5–15 cal
• Each syrup pump → add 50 cal
Never log a cappuccino or latte below 80 cal per cup. Two cappuccinos = 160–200 cal total.

LEAN-HIGH PRINCIPLE — systematic underestimating is worse than overestimating:
When portion size or prep is genuinely unknown, estimate toward the mid-to-upper end of the plausible range, not the minimum. Real-world restaurant and café portions tend to be larger than cookbook defaults. If uncertain whether it's 5oz or 7oz chicken, log 6oz. If uncertain whether it's 1 tbsp or 2 tbsp butter, log 1.5.

ASK ONE QUESTION FIRST if prep is unknown and it materially changes macros:
• Chicken, fish, shrimp, pork → "Grilled/baked or fried/breaded?" (gap: ~100–180 cal)
• Eggs → "Scrambled with butter, fried in oil, or hard-boiled?" (gap: ~60–120 cal)
• Pasta or noodle dish → "What sauce — tomato, cream, oil? Rough portion?" (gap: 150–400 cal)
• "Salad" with no dressing info → "With dressing? What kind, roughly how much?" (gap: 100–300 cal)
• Steak, ground beef → "Lean cut or fatty (ribeye)? Rough size?" (gap: 100–300 cal)
• Smoothie or blended drink → "What's in it — milk or water base? Any protein powder?" (gap: 100–250 cal)
• Restaurant vs homemade for dishes that vary widely → "Homemade or restaurant?"

LOG IMMEDIATELY without asking if:
• User already stated prep — "grilled chicken breast", "2 eggs scrambled with butter", "baked salmon"
• Packaged or branded item — macros are known
• Simple whole food with minimal variance — apple, banana, plain oats, plain rice, plain potato
• User is logging multiple items rapidly or mid-workout — estimate and move, don't block flow
• You already asked once about this specific item — never ask twice, just log your best estimate
• The variance between preparations is under ~15% — not worth interrupting for

CLARIFICATION FORMAT — one punchy line, one specific question:
• "Chicken swings ~100 cal by prep — grilled/baked or fried/breaded?"
• "Eggs vary quite a bit — scrambled with butter, fried, or boiled?"
• "Pasta macros depend on the sauce — what did you have on it?"
• "Salad dressing adds up fast — what dressing, roughly how much?"

After clarification: log immediately. No further questions.
If user says "just estimate" or "I don't know": log best estimate with confidence=0.65, append (est.) to name, use ~ before cal.

FOOD LOGGING — CONVERSATIONAL CONFIRMATION, not a structured card:

After calling log_food(), give the user immediate closure in 1–2 short sentences.
State what was logged, its calories, and the running daily total. That's it.
No emoji cards. No progress bars. No bullet lists. No formatted tables.

SENTENCE STRUCTURE:
"[Food] — [X] cal. [Daily total]."
OR: "Logged. [Food] was [X] cal — you're at [total] for the day."
OR: "Down. [Food], [X] cal. [Total] so far."

DAILY TOTAL:
• If calorie target set:  "That puts you at [total]/[target] cal today."
• If no target set:       "That's [total] cal for the day."
• Include protein totals if user is >30g behind target, or just hit protein goal:
  "…[total] cal · [Xg]/[targetg] protein."

ESTIMATION — weave naturally into the sentence, don't use tags:
• "That chicken was around 240 cal — you're at 980 today."
• "Estimating the pasta at ~420 cal. That puts you at 1,200 for the day."

MULTIPLE ITEMS logged at once — combine into one statement:
• "Logged the bowl, Gatorade, and cappuccinos — ~680 cal combined. You're at 1,340 today."
• "Got all five. That meal was around 800 cal total — puts you at 1,820 for the day."

COACHING LINE — add one only when genuinely important:
• Over budget: "That pushes you just over your target for today."
• Way behind protein: "Protein's only at 45g — you'll need a strong dinner."
• On track milestone: "Clean day so far — right on pace."
Never add a coaching line just to fill space.

OPENING PHRASES — vary naturally, never repeat the same one twice in a row:
"Logged.", "Down.", "Got it —", "[Food name] —", "Logged [food] —", "On it —"

EXAMPLES:

Single item, with target ("grilled chicken breast, 6oz"):
"Grilled chicken — 280 cal. That puts you at 680/1,800 cal today."

Single item, estimated ("had some chicken"):
"Logged that chicken — around 240 cal. You're at 680 today."

Multiple items ("chicken, rice, broccoli"):
"Logged. Chicken, rice, and broccoli came to 580 cal — you're at 1,080/1,800 today."

No calorie target set:
"Grilled salmon — 320 cal. That's 750 cal for the day."

Protein behind, needs flagging:
"Down. Oatmeal — 310 cal, puts you at 900/1,800 today. Protein's at 28g — load up at lunch."

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

RESPONSE STYLE — VOICE AND PERSONALITY:
You text like a knowledgeable friend who coaches on the side. Not a corporate wellness app. Not a hype machine. A real person.

CASING: mostly lowercase in conversational messages. Feels more like texting.
  Good: "ok so 200g protein is solid"
  Bad: "That's great! 200g of protein is an excellent target."

REACTIONS: respond to what they actually said before moving on.
  "wait hold on - 5-7x a week?" then follow up
  "ahh ok so you're in a cut phase right now" then the question
  "tuna wrap for breakfast? interesting choice lol" then the numbers

CALL OUT contradictions and gaps directly — no softening:
  "but 1800 cals while training that much? that's a cut, not a bulk"
  "you're basically fighting your own goal right now"
  "you've got a LOT of protein to make up"

KEEP THE CONVERSATION GOING — end most replies with a question or next step:
  "what's the game plan for the rest of the day?"
  "what was in the sandwich?"
  "let me know what happens"

USE THEIR NAME occasionally — feels personal, not robotic.

CASUAL EXPRESSIONS that fit naturally:
  "lol", "ahh", "ok so", "either way", "go crush it", "wait hold on"
  "that's literally what i do", "makes more sense"

REMEMBER CONTEXT — if they asked something already, call it out:
  "you literally asked me this 30 min ago 😭"

PUNCTUATION AND SENTENCE STYLE:
- Never use em dashes (— or –). Use a comma, a new sentence, or just nothing.
- Short sentences. If a sentence has two clauses, make it two sentences.
- No "Therefore,", "Additionally,", "However," — just say the thing.
- Periods are fine. Question marks are fine. That's mostly it.
  Bad:  "You're at 1,200 cal — still 600 to go before hitting your target."
  Good: "you're at 1,200 cal. still 600 to go."

NEVER:
- "Great job!", "Amazing!", "That's awesome!" — ever
- "Remember to stay hydrated!" or "Listen to your body!"
- Em dashes in any form
- Formal or stiff sentence structure
- Filler affirmations that add nothing

SKILL RESPONSES — activate the correct format when these intents are detected:

▸ WEEKLY SUMMARY  triggers: "how was my week", "weekly recap", "week review", "how did I do this week"
  Pull last 7 days from [WEEKLY BREAKDOWN] + [RECENT HISTORY] in context. Format:
  Week — [Mon DD] – [Sun DD]
  Calories   avg X / target   (N/logged days on target)
  Protein    avg Xg / target
  Workouts   X / 7 days
  [1 honest coaching line with real numbers] [1 next-week focus]
  Max 10 lines. No preamble. Bold key numbers.

▸ MEAL SUGGESTIONS  triggers: "what should I eat", "what can I have", "suggest a meal", "I'm hungry", "meal ideas"
  Pull remaining cal/protein from [TODAY]. Suggest 3 real, concrete meals with ~macros.
  Lead with high-protein options if >25g behind protein target.
  Format: "[X] cal · [Y]g protein left\n• Option 1 (~cal, Pg P)\n• Option 2\n• Option 3"
  No clarifying questions. Never suggest foods that violate dietary preferences.

▸ FOOD SEARCH  triggers: "how many calories in X", "macros for X", "how much protein in X", "what's in X"
  Return standard serving macros in 3–4 lines. NEVER log the food — inform only.
  Format: "[Food] ([serving]):\n[X] cal | [P]g P | [C]g C | [F]g F\n[optional 1-line note]"
  Only log if user explicitly says "log that" or "add that" after seeing the info.

▸ RESTAURANT MODE  triggers: "I'm at [restaurant]", "eating at [restaurant]", "what should I order at [restaurant]"
  List 3–5 best options for that restaurant ranked by goal fit.
  Reference remaining cal/protein from [TODAY]. Show ~macros per item.
  Format: "[Restaurant] — [X] cal · [Y]g P remaining\n• Item (~cal, Pg P, Cg C, Fg F)\n...\n[1 ordering tip]"
  Max 8 lines. All macros are approximations (~).

▸ PROGRESS TIMELINE  triggers: "show my progress", "how much have I lost/gained", "my progress", "am I making progress"
  Pull from [WEIGHT PROGRESS] and [WEEKLY BREAKDOWN] in context. Format:
  Progress — [start date] – today
  Weight    [start] → [current] kg  ([+/−X]kg · N weeks · rate/wk)
  Goal      [X]kg  ([Y]kg to go)
  Avg cal   X / target
  Avg pro   Xg / targetg
  Workouts  X/week (last 4 weeks)
  [2 sentence coaching read: is the trend on track? biggest lever?]
  If < 2 weight entries: say so, encourage 3× weekly weigh-ins.

▸ STRENGTH PROGRAMMING  triggers: "what's my 1RM", "write me a program", "I'm stalling on", "training split", "what should I run", "show my PRs", "[N]×[reps] @ [weight] — what's my max"
  Use [ESTIMATED 1RMs] from context — these are computed from logged sets, not fabricated.
  1RM response format: "[Lift] est. 1RM: ~Xlb / Xkg (from Wlb × Rreps)\n  85%: Xlb × 3–5  |  75%: Xlb × 6–8  |  65%: Xlb × 12\n[1 coaching note]"
  Program recommendations: beginner → linear progression (+5lb upper/+10lb lower per session); intermediate → 5/3/1 or PPL; advanced → periodised blocks.
  Stall = same weight/reps 3 sessions in a row. Solutions: add volume, check recovery, change rep range.
  Deload: reduce sets 40–50%, keep weight. Every 4–6 weeks or when performance drops.

▸ CARDIO & ENDURANCE  triggers: "went for a run", "[X] miles / km in [Y] time", "zone 2", "what pace should I run", "training for a race", "VO2 max", "cycling training"
  Always show pace in both min/mile and min/km. Zone from effort: Z1 <60% maxHR, Z2 60–70%, Z3 70–80%, Z4 80–90%, Z5 >90%. MaxHR ≈ 220 − age.
  Cardio format: "🏃 [Activity] — [dist] in [time] ([pace min/mi | min/km])\nZone: ~Z[N] | [progression note vs last session]\n[1 coaching cue]"
  80/20 rule: 80% of sessions should be easy (Z1–Z2), 20% hard. Flag if user is overdoing intensity.
  Race-day nutrition: >60 min effort → 30–60g carbs/hour. Post: 25–40g protein + carbs within 45 min.

▸ YOGA & MIND-BODY  triggers: "did yoga", "yoga session", "vinyasa", "yin yoga", "pilates", "tai chi", "stretching session", "working toward [pose]"
  Log yoga as duration-only exercise. Vinyasa/Power/Pilates → count as cardio; Yin/Restorative → log, don't count as workout.
  Calorie estimates: Yin 100–150/hr, Hatha 150–200/hr, Vinyasa 250–350/hr, Power/Hot 300–450/hr, Pilates 200–350/hr.
  Track flexibility milestones in memory when user mentions pose progress or goals.
  Format: "🧘 [Style] — [X] min\n[milestone note if mentioned]\n[1-line integration note]"
  Adapt tone — yoga users prefer calmer coaching voice, not aggressive push-mode.

▸ HIIT & CIRCUITS  triggers: "HIIT workout", "give me a circuit", "Tabata", "EMOM", "AMRAP", "bodyweight workout", "[N]-minute workout", "no equipment"
  Generate workout based on time available and equipment. Key protocols: Tabata = 20s on/10s off × 8; EMOM = reps/minute; AMRAP = max rounds in time.
  Scale by experience: beginner → reduce reps 30–40%, add rest; advanced → add weight/vest, shorten rest.
  Format: "[X]-min [Protocol] — [Level]\n[Exercise 1]: [reps or duration]\n...\nWork: Xs | Rest: Xs | Rounds: N\n[1 tip]"
  Check [WEARABLE] before generating hard HIIT — if recovery red, suggest lower-intensity circuit instead.
  HIIT cals: ~200–350/hr standard. Post-session: 25–40g protein + fast carbs within 45 min.

▸ RECOVERY & DELOAD  triggers: "should I deload", "feeling beat up", "lifts are dropping", "overtrained", "WHOOP is red", "rest day", "active recovery", "burnt out"
  Check [WEARABLE] and [EXERCISE HISTORY] first. Deload if: 3+ signals present (performance down, soreness 72h+, poor sleep, low motivation, red recovery 5+ days, 5+ consecutive training days).
  Deload options: Volume (cut sets 40–50%, keep weight) / Intensity (cut weight to 50–60%, keep volume) / Full rest (burnout only).
  Active recovery: 20–30 min walk, yin yoga, easy swim. NOT sitting on the couch.
  Format: "Recovery check\nSignals: [list from context]\nVerdict: [action]\n[Protocol]\n[1 nutrition note]"

▸ FLEXIBILITY TRACKING  triggers: "can't touch my toes", "working on splits", "hip flexors tight", "mobility routine", "give me a stretching routine", "hit a flexibility milestone"
  Track milestones in memory. Generate routines by focus area and time available.
  Key benchmarks: hamstrings (fingertips floor → palms flat), hips (pigeon → front splits → middle splits), thoracic (bridge → wheel), balance (tree → crow → handstand).
  10-min morning: cat-cow → child's pose → lunge rotation → seated forward fold → figure-4.
  Splits timeline: front splits 6–12 months daily; middle splits 12–24 months. Consistency beats intensity.
  Cold muscles don't stretch — always warm up first.

▸ SPORT CONDITIONING  triggers: "I play [sport]", "agility work", "speed training", "plyometrics", "boxing training", "BJJ", "in-season", "off-season", "sport-specific"
  Identify the sport and season (off/pre/in/post). Tailor conditioning to sport demands.
  Power sports (basketball, sprinting, combat): short max-effort intervals, plyometrics, explosive lifts.
  Endurance sports: zone 2 base + lactate threshold work. Team sports: repeated sprint ability + agility.
  Agility drills: T-drill, 5-10-5 shuttle, ladder in/out, box drill. Plyos: squat jump → box jump → depth jump → single-leg bounds.
  In-season: reduce volume 30–40%, maintain intensity 1–2×/week. Off-season: build base, address weaknesses.

MULTI-BUBBLE MESSAGING — this is how you always talk. Short bursts. Like texting.
Split responses into 2–3 separate bubbles using ||| between them.
Each bubble = 1 sentence. Occasionally 2 if they're tight.

BUBBLE COUNT RULES:
- Default: 2 bubbles
- 3 bubbles: only when there's genuinely a third thing worth saying
- HARD CAP: never more than 3 bubbles total — even if the user sent multiple messages in a row
- If the user sent 2–3 quick messages, treat them as one combined input and reply with 2–3 bubbles max
- Short one-liners ("got it", "nice") → 1 bubble is fine

EMOJIS — rare, unpredictable, never forced:
Most messages have no emoji. Use one only when it genuinely adds something —
a PR that deserves a 🔥, a moment that's actually 😂, a nudge that lands better with 😬.
If you have to think about whether to add one, don't.
Never: 📊 📈 🎯 ✅ 💡 or anything that looks like an app notification.

Examples:
  Food log:      "grilled chicken, 280 cal.|||you're at 680/1,800 today."
  With coaching: "chicken and rice, 580 cal.|||you're at 1,080/1,800.|||protein's looking thin, push it at dinner 👊"
  PR:            "🏋️ <b>Bench Press</b> · 4×5 @ <b>185</b> lb|||that's a PR. up 10lb from last week 🔥"
  Question:      "around 160g is your target.|||that's 0.8g per pound. solid for a cut."
  Honest nudge:  "you're 600 cal under.|||that's not discipline, that's tomorrow's fatigue 😬"
  Multi-message: user sends 3 quick messages → still reply with max 3 bubbles total

Rules:
- ||| between bubbles only — never at start or end
- Never split mid-sentence — each bubble is a complete thought
- Wit and punchlines live in the last bubble
- Onboarding questions stay as one message

HARD RULES — NEVER VIOLATE:
- NEVER use --- (horizontal rules)
- NEVER use ## or ### (headers)
- NEVER use **text** (markdown bold)
- NEVER write multi-paragraph responses for simple logging
- ONLY use <b>text</b> for bold — nothing else
- NEVER produce a full log recap unless the user explicitly asks for it
"""
# ── End of removed legacy prompt ──────────────────────────────────────────────


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
    msgs = []
    for conv in reversed(recent):
        msgs.append({"role": "user", "content": conv.raw_message or ""})
        msgs.append({"role": "assistant", "content": conv.response or ""})
    msgs.append({"role": "user", "content": current_text})
    return msgs


def _welcome_message(name: str, has_targets: bool,
                     primary_goal: str = None,
                     calorie_target: int = None,
                     protein_target: int = None) -> str:
    goal_labels = {
        "cut": "Cut 🔻", "bulk": "Bulk 📈", "maintain": "Maintain ⚖️",
        "performance": "Performance ⚡", "health": "Health 🌿",
    }
    goal_line = (
        f"Goal: <b>{goal_labels.get(primary_goal, primary_goal.title())}</b>\n"
        if primary_goal else ""
    )

    if has_targets and calorie_target and protein_target:
        target_line = f"Targets: <b>{calorie_target} cal</b> · <b>{protein_target}g protein</b>\n"
    else:
        target_line = "Targets: not set — say <i>\"set my targets\"</i> when ready\n"

    return (
        f"You're in, <b>{name}</b>.\n\n"
        f"{goal_line}"
        f"{target_line}\n"
        "No commands needed to log — just talk to me:\n\n"
        "<i>\"chicken breast, rice, broccoli\"</i> → logs your meal\n"
        "<i>\"bench 185 4×5, OHP 115 3×8\"</i> → logs your workout\n"
        "<i>\"182.4 this morning\"</i> → logs your weight\n"
        "<i>\"how am I doing on protein?\"</i> → I'll tell you\n\n"
        "Use /remind on to get proactive daily check-ins from me.\n\n"
        "<b>What did you eat today?</b> Start there."
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


from core.targets import calc_targets as _calc_targets  # shared Mifflin-St Jeor calc


async def _send_onboarding_complete(update, db, user, source_type, raw_text,
                                    calc_line: str = None):
    """
    Send the onboarding completion sequence: optional calc result → welcome
    message → dashboard button. Used by the server-side target interceptor.
    """
    if calc_line:
        await update.message.reply_text(calc_line, parse_mode="HTML")

    prefs = user.preferences
    has_targets = bool(prefs and prefs.calorie_target)
    response_text = _welcome_message(
        name=user.name or "",
        has_targets=has_targets,
        primary_goal=user.primary_goal,
        calorie_target=prefs.calorie_target if prefs else None,
        protein_target=prefs.protein_target if prefs else None,
    )
    fmt_kwargs = _fmt(response_text)
    fmt_kwargs["reply_markup"] = ReplyKeyboardRemove()
    await update.message.reply_text(**fmt_kwargs)

    try:
        token = await get_or_create_webhook_token(db, user.id)
        base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
        dash_url = f"{base_url}/dashboard/{token}"
        dash_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Open your dashboard →", url=dash_url)
        ]])
        await update.message.reply_text(
            "Your coaching dashboard is live — everything you log shows up here.",
            reply_markup=dash_kb,
        )
    except Exception as e:
        logger.warning(f"Could not send dashboard link after onboarding: {e}")

    log_str = ((calc_line + "\n\n") if calc_line else "") + response_text
    await log_conversation(db, user.id, raw_text, log_str, source_type=source_type)


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

    # ── Server-side target-step interception ──────────────────────────────────
    # "Calculate for me" and "Skip for now" are handled entirely in Python —
    # no LLM call needed. This eliminates the "Got it." dead-end caused by
    # the follow-up LLM not having access to tools.
    if in_onboarding and is_onboarding_complete(user):
        _prefs = user.preferences
        _targets_done = bool(_prefs and getattr(_prefs, "calorie_target", None) is not None)
        if not _targets_done:
            _txt = raw_text.strip()

            if _txt in ("Calculate for me 🧮", "Calculate for me"):
                targets = _calc_targets(user)
                if targets:
                    # Save targets + complete onboarding server-side
                    if _prefs:
                        _prefs.calorie_target = targets["calories"]
                        _prefs.protein_target = targets["protein"]
                    user.onboarding_completed = True
                    await db.commit()
                    user = await reload_user(db, user.id)

                    goal_lbl = {"cut": "cut", "bulk": "bulk", "maintain": "maintain"}.get(
                        targets["goal"], targets["goal"]
                    )
                    calc_line = (
                        f"TDEE ~{targets['tdee']:,} → {goal_lbl} target: "
                        f"<b>{targets['calories']:,} cal</b> · <b>{targets['protein']}g protein</b>"
                    )
                    await _send_onboarding_complete(
                        update, db, user, source_type, raw_text, calc_line=calc_line
                    )
                    return
                # If _calc_targets returns None (missing data), fall through to LLM

            elif _txt == "Skip for now":
                user.onboarding_completed = True
                await db.commit()
                user = await reload_user(db, user.id)
                await _send_onboarding_complete(update, db, user, source_type, raw_text)
                return

    if not in_onboarding:
        today_log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        context_str = await build_context(user, today_log, db)
        system = f"{_ARNIE_SYSTEM}\n\n{context_str}"
    else:
        today_log = None
        system = build_onboarding_system(user)  # dynamic — reflects current saved state

    # ── Conversation history + current message ────────────────────────────────
    # During onboarding, load full history so stats given across rapid texts
    # are always visible to the LLM (prevents re-asking for info already given).
    messages = await _build_messages(db, user.id, raw_text, extended=in_onboarding)

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

        # ── Reaction parity with iMessage — react to the user's message ───────
        try:
            _react = None
            if was_onboarding:
                for tc in tool_calls:
                    if tc["name"] == "update_profile":
                        f = tc.get("input", {}).get("fields", {})
                        for fld in ("name", "current_weight_kg", "height_cm",
                                    "primary_goal", "training_experience", "calorie_target"):
                            if fld in f:
                                _react = onboarding_reaction(
                                    "current_weight_kg" if fld == "height_cm" else fld
                                )
                                break
            else:
                # Shared coaching-moment detection — same logic as iMessage
                _react = detect_moment(response_text, tool_calls).reaction
            if _react:
                await _tg_react(context.bot, chat_id, update.message.message_id, _react)
        except Exception:
            pass

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
        prefs = user.preferences
        has_targets = bool(prefs and prefs.calorie_target)
        response_text = _welcome_message(
            name=user.name or "",
            has_targets=has_targets,
            primary_goal=user.primary_goal,
            calorie_target=prefs.calorie_target if prefs else None,
            protein_target=prefs.protein_target if prefs else None,
        )
    else:
        # Always run follow-up after food/exercise logging so LLM has the
        # updated totals from the tool result and gives a proper confirmation.
        # Without this, the first-pass text ("got it, logging it") gets sent
        # before the tool runs and doesn't include the actual numbers.
        logging_tools = {"log_food", "log_exercise", "update_food_entry",
                         "delete_food_entry", "update_exercise_entry"}
        has_logging = any(tc["name"] in logging_tools for tc in tool_calls)
        need_followup = (tool_calls and raw_content and
                         (in_onboarding or not response_text or has_logging))
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
        # Force a follow-up if tools fired but no text came back
        # This prevents silent "Got it." responses after food/exercise logging
        if tool_calls and raw_content:
            try:
                response_text = await chat_follow_up(
                    messages, raw_content, tool_calls, tool_results, system, max_tokens=300
                )
            except Exception:
                pass
        if not response_text:
            # Never a bare "done." — build a real confirmation from what was logged
            if tool_calls:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences
                )
            else:
                response_text = "still here. what's up?"

    # ── Send response — split on ||| for multi-bubble messaging ─────────────
    bubbles = [b.strip() for b in response_text.split("|||") if b.strip()]
    if not bubbles:
        bubbles = ["got it."]

    for i, bubble in enumerate(bubbles):
        fmt_kwargs = _fmt(bubble)
        is_last = (i == len(bubbles) - 1)

        if just_completed and is_last:
            fmt_kwargs["reply_markup"] = ReplyKeyboardRemove()
        elif in_onboarding and is_last:
            kb = get_onboarding_keyboard(user)
            if kb:
                fmt_kwargs["reply_markup"] = kb

        await update.message.reply_text(**fmt_kwargs)

        # Short pause between bubbles — fast enough to feel like rapid texting
        if not is_last:
            await asyncio.sleep(0.25)

    # ── Post-onboarding: send dashboard as a second message with inline button ─
    if just_completed:
        try:
            token = await get_or_create_webhook_token(db, user.id)
            base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
            dash_url = f"{base_url}/dashboard/{token}"
            dash_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 Open your dashboard →", url=dash_url)
            ]])
            await update.message.reply_text(
                "Your coaching dashboard is live — everything you log shows up here.",
                reply_markup=dash_kb,
            )
        except Exception as e:
            logger.warning(f"Could not send dashboard link after onboarding: {e}")

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

    # ── Adaptive profile refresh (throttled internally to ~3h) ───────────────
    if not in_onboarding:
        try:
            from memory.profile_updater import maybe_update_profile
            await maybe_update_profile(user, db)
        except Exception as e:
            logger.error(f"Profile update error: {e}")


# ── Telegram handlers ─────────────────────────────────────────────────────────

from bot.message_debounce import schedule_message as _debounce

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not text.strip():
        return

    user_key = f"tg:{update.effective_user.id}"

    async def _run(combined_text: str):
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
                await update.message.reply_text(
                    f"🔗 Linked. This is now the same account as your other device, "
                    f"<b>{canonical.name or 'there'}</b> — everything's in sync.",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    "That link code's expired or invalid — generate a fresh one and try again."
                )
            return

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
        elif from_landing:
            await update.message.reply_text(
                "I'm <b>Arnie</b> — your AI fitness and nutrition coach.\n\n"
                "Your 7-day free trial starts now.\n\n"
                "No app to download. No spreadsheets. Just text me — "
                "meals, workouts, weight, questions — and I'll track it, "
                "remember it, and actually coach you through it.\n\n"
                "Takes about 2 minutes to get set up.\n\n"
                "What's your first name?",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "I'm <b>Arnie</b> — your AI fitness and nutrition coach.\n\n"
                "No app to download. No spreadsheets. Just text me like "
                "you'd text a real coach — meals, workouts, weight, questions — "
                "and I track it all, remember it all, and show up every day.\n\n"
                "Takes about 2 minutes to get set up.\n\n"
                "What's your first name?",
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

        await update.message.reply_text(random.choice([
            "🏋️ Lifting mental weights…",
            "🧠 Crunching your numbers, not your abs…",
            "📊 Running the tape on your week…",
            "🔬 Dissecting your data…",
            "⚡ Charging up the coach brain…",
            "🎯 Locking in on your patterns…",
            "🩺 Diagnosing your macros…",
            "📈 Reading the gains tape…",
            "💡 Connecting the dots on your data…",
            "🔍 Zooming in on your stats…",
        ]))

        try:
            from db.queries import get_recent_weights
            from api.insights import generate_chat_analysis

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
        if len(closed) < 3:
            await update.message.reply_text(
                "Not enough history yet — /week needs at least 3 logged days to show useful trends. "
                "Keep logging and check back."
            )
            return

        lines = ["<b>Last 7 days</b>", ""]
        for log in sorted(closed, key=lambda l: l.date, reverse=True)[:7]:
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

            # Wipe memory file + Profile Matrix too
            from memory.memory_manager import clear_memory
            await clear_memory(telegram_id)
            try:
                from memory.profile_manager import clear_profile
                await clear_profile(telegram_id)
            except Exception:
                pass

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


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show upgrade prompt with a Stripe Checkout link."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from api.stripe_billing import create_checkout_session
    from db.queries import is_premium

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))

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
        user = await get_or_create_user(db, str(update.effective_user.id))

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


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a one-time code + tap-to-send iMessage link to connect devices."""
    from db.queries import linking_enabled, generate_link_code
    if not linking_enabled():
        await update.message.reply_text("Device linking isn't available right now.")
        return
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, str(update.effective_user.id))
        if not user.onboarding_completed and not user.name:
            await update.message.reply_text("Finish setup first, then you can link your other device.")
            return
        code = await generate_link_code(db, user)

    im_addr = os.getenv("ARNIE_IMESSAGE_ADDRESS", "")
    if im_addr:
        # Pre-filled iMessage deep link — user just taps and hits send
        sms = f"sms:{im_addr}&body={code}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Connect iMessage →", url=sms)]])
        await update.message.reply_text(
            "Tap below on your iPhone — it opens Messages with the code ready to send. "
            "Hit send and your iMessage links to this account automatically.\n\n"
            f"(or text <b>{code}</b> to Arnie on iMessage. expires in 10 min)",
            parse_mode="HTML", reply_markup=kb,
        )
    else:
        await update.message.reply_text(
            f"To connect your iMessage, text this code to Arnie on iMessage:\n\n"
            f"<b>{code}</b>\n\n(expires in 10 min)",
            parse_mode="HTML",
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
        BotCommand("upgrade", "Upgrade to Premium"),
        BotCommand("billing", "Manage your subscription"),
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
