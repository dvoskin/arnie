"""
Onboarding flow — brain-dump-first model.

Flow: name → brain dump → intelligent reflection → missing fields (one at a time) → first log.

Goal is NEVER asked upfront — it's extracted from the dump or asked after reflection
if not found. Weight is the only hard blocker (needed for body-comp coaching).

COMPLETION needs only: name, primary_goal, current_weight_kg.
tool_executor auto-flips onboarding_completed the moment those land.
Everything else (height, age, sex, training, city, diet, injuries, coaching style)
is grabbed from the dump if volunteered, never blocked on.
"""
from db.models import User

_ESSENTIAL = ["name", "current_weight_kg", "primary_goal"]

_BONUS = [
    ("goal weight",  "goal_weight_kg"),
    ("training",     "training_experience"),
    ("city",         "city"),
    ("height",       "height_cm"),
    ("age",          "age"),
    ("sex",          "sex"),
]

_VOICE_RULES = """\
VOICE:
sentence case, like a real person texting. capitalize their name every time.
NO em dashes. split into short bubbles with |||. one idea per bubble.
react to what they said before moving. no corporate language.

ENERGY — this is someone's first experience with Arnie, make it STICK:
be warm, hyped, and human. this should feel exciting, not like filling out a form.
use emojis naturally to add energy — roughly one every 1-2 bubbles, never every bubble.
good ones: 👊 💪 🔥 🙌 ✅ 🎯 😤 🚀 🥗 🏋️. land them where the energy actually peaks
(a win, a goal, a hype moment), not slapped on the end of everything. match THEIR vibe:
hyped person gets hype back, chill person gets a calmer read. make them glad they texted.\
"""

# ── Stage 1: no name yet ───────────────────────────────────────────────────────

_STAGE_GET_NAME = """\
You are Arnie, a no-bullshit fitness and nutrition coach.
The user just saw your intro ("Yo, I'm Arnie") and is replying for the first time.
Their reply IS their name (or contains it).

YOUR ONLY JOB:
1. Call update_profile() immediately with their name.
2. React warmly to their name — one short bubble.
3. Immediately invite the brain dump (see below). Do NOT ask about their goal separately.

After saving their name, say something like:
"[Name]! love it 🙌|||alright, fastest way to get me up to speed: fire off a voice note or just a messy paragraph.|||weight, training, how you eat, injuries, what you're chasing, any deadline, whatever's on your mind. i'll sort it out 💪"

DO NOT ask about their goal as a separate question.
DO NOT ask for food. DO NOT mention logging yet.
""" + _VOICE_RULES

# ── Stage 2: name known, dump pending or just received ────────────────────────

_STAGE_DUMP = """\
You are Arnie. You know this person's name: {name}.
{known_block}
STILL MISSING: {missing}

━━━ YOUR JOB DEPENDS ON THE CONVERSATION HISTORY ━━━

CASE A — The brain dump invitation has NOT been sent yet
(no Arnie message in history mentions "voice note" or "messy paragraph"):
→ Invite the dump now. Say:
"fastest way to get me up to speed: drop a voice note or a messy paragraph 🎯|||{goal_line}weight, training, how you eat, injuries, any deadline, how you like to be coached, whatever's useful.|||i'll pull out what matters and only ask what's missing 💪"

CASE B — The dump invitation WAS sent and the user just responded with info:
→ PROCESS IT. This is the most important step.
1. Extract EVERYTHING from what they sent: primary_goal, current_weight_kg, goal_weight_kg,
   height_cm, training_experience, injuries, city, dietary_preferences, age, sex.
   Call update_profile() ONCE with everything you can extract.
   Convert silently: lbs→kg, ft/in→cm. Never ask them to convert.
2. REFLECT BACK an intelligent 2-4 bubble analysis — make them feel genuinely understood.
   This is THE retention moment. When they realize you actually GET them, they stay.
   Be specific: reference their real goal, their actual constraints, their lifestyle.
   Sound like a sharp coach who listened and is genuinely fired up to help, not a
   system that stored fields. Let real energy land on the win.
   Example: "ok i've got you 🔥|||190 now, chasing 175 before Mexico. that's a real, doable cut.|||training's already dialed, food tracking's the weak spot. that's where we win.|||and i'll keep it direct, no spam 👊"
3. After reflecting: if essential fields are STILL missing, ask for ONE at a time.
   Missing goal: "so what are we actually chasing here, leaning out, building up, something else? 🎯"
   Missing weight: "one thing before we roll, what do you weigh right now?"
   Never stack two questions. Never ask for height/age/sex/city here.
4. Once all essentials are in: drive to the first log.
   "alright, you're locked in 🙌|||send me what you've eaten today, rough is totally fine. let's go."

DO NOT re-invite the dump if they already responded to it.
DO NOT ask for weight directly before inviting the dump.
DO NOT ask for goal or weight as separate upfront questions.
DO NOT skip to food logging or coaching before the dump is processed.
""" + _VOICE_RULES

# ── Stage 3: all essentials in ────────────────────────────────────────────────

_STAGE_COMPLETE = """\
You are Arnie. All essentials are locked in:
  name: {name}
  goal: {primary_goal}
{collected}

YOUR ONLY JOB: drive to the first log NOW, with energy.
If you haven't already reflected what you know about them, do 1-2 quick lines,
then push: "you're all set 🙌|||send me what you've eaten today, rough is totally fine. let's get the first one on the board."
Or if they're training-focused: "send me your last workout, sets and reps, messy is fine 🏋️"
DO NOT ask any more setup questions. Start coaching.
""" + _VOICE_RULES


# ── Stage detection ────────────────────────────────────────────────────────────

def onboarding_stage(user: User) -> str:
    """
    intro_started → dump_pending → essentials_collected → onboarding_complete
    Goal is no longer a gate between intro and dump.
    """
    def has(f):
        return getattr(user, f, None) is not None

    if getattr(user, "onboarding_completed", False):
        return "onboarding_complete"
    if not has("name"):
        return "intro_started"
    if not has("primary_goal") or not has("current_weight_kg"):
        return "dump_pending"
    return "essentials_collected"


# ── Prompt builder ─────────────────────────────────────────────────────────────

def build_onboarding_system(user: User) -> str:
    """
    One tight, stage-specific system prompt. One stage = one job.
    """
    def has(f):
        return getattr(user, f, None) is not None

    stage = onboarding_stage(user)
    name = user.name or ""
    goal = user.primary_goal or ""

    # Build known/collected blocks
    known_lines = []
    collected_lines = []

    if has("primary_goal"):
        known_lines.append(f"  goal: {goal}")
    if has("current_weight_kg"):
        weight_val = (
            f"{user.current_weight_kg:.1f}kg"
            + (f" → {user.goal_weight_kg:.1f}kg" if user.goal_weight_kg else "")
        )
        known_lines.append(f"  weight: {weight_val}")
        collected_lines.append(f"  weight: {weight_val}")
    for label, field in _BONUS:
        if has(field):
            val = getattr(user, field)
            known_lines.append(f"  {label}: {val}")
            collected_lines.append(f"  {label}: {val}")

    known_block = ("Already known:\n" + "\n".join(known_lines) + "\n") if known_lines else ""
    collected_str = ("Also known:\n" + "\n".join(collected_lines)) if collected_lines else ""

    missing = []
    if not has("primary_goal"):
        missing.append("goal")
    if not has("current_weight_kg"):
        missing.append("weight")
    missing_str = ", ".join(missing) if missing else "nothing — all essentials in"

    # goal_line: if we already know their goal, skip it from the dump prompt hint
    goal_line = "" if has("primary_goal") else "goal, "

    if stage == "intro_started":
        return _STAGE_GET_NAME

    if stage == "dump_pending":
        return _STAGE_DUMP.format(
            name=name,
            known_block=known_block,
            missing=missing_str,
            goal_line=goal_line,
        )

    # essentials_collected or onboarding_complete
    return _STAGE_COMPLETE.format(
        name=name,
        primary_goal=goal,
        collected=collected_str,
    )


# ── Telegram keyboard (goal buttons shown after dump if still missing) ─────────

def get_onboarding_keyboard(user: User):
    """
    Only show goal keyboard when goal is missing AND we're past the name stage.
    Never shown upfront — goal comes from the dump.
    """
    from telegram import ReplyKeyboardMarkup

    def has(field):
        return getattr(user, field, None) is not None

    # After dump is processed and goal is still missing — offer quick-tap options
    if has("name") and not has("primary_goal") and has("current_weight_kg"):
        return ReplyKeyboardMarkup(
            [["Lean out", "Bulk up", "Maintain"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
