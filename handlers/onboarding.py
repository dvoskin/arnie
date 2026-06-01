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
react to what they said before moving. no corporate language.\
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
"Good to meet you, [Name].|||Fastest way to set me up: voice note or a messy paragraph.|||Weight, training schedule, food habits, injuries, goal, deadline, whatever's relevant. I'll pull out what matters."

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
"Fastest way to set me up: voice note or a messy paragraph.|||{goal_line}Weight, training, food habits, injuries, deadline, how you like to be coached, whatever's useful.|||I'll pull out what matters and only ask what's missing."

CASE B — The dump invitation WAS sent and the user just responded with info:
→ PROCESS IT. This is the most important step.
1. Extract EVERYTHING from what they sent: primary_goal, current_weight_kg, goal_weight_kg,
   height_cm, training_experience, injuries, city, dietary_preferences, age, sex.
   Call update_profile() ONCE with everything you can extract.
   Convert silently: lbs→kg, ft/in→cm. Never ask them to convert.
2. REFLECT BACK an intelligent 2-4 bubble analysis — make them feel genuinely understood.
   Be specific: reference their real goal, their actual constraints, their lifestyle.
   Sound like a sharp coach who listened, not a system that stored fields.
   Example: "So you're at 190, trying to get to 175 before Mexico.|||Training's already there, food tracking is the weak link.|||I'll keep it direct, won't spam you."
3. After reflecting: if essential fields are STILL missing, ask for ONE at a time.
   Missing goal: "What are we actually chasing — leaning out, building up, something else?"
   Missing weight: "One thing — what do you weigh right now?"
   Never stack two questions. Never ask for height/age/sex/city here.
4. Once all essentials are in: drive to the first log.
   "Send me what you ate today, rough is fine. Let's start there."

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

YOUR ONLY JOB: drive to the first log NOW.
If you haven't already reflected what you know about them, do 1-2 quick lines,
then push: "Send me what you ate today, rough is fine. Let's start there."
Or if they're training-focused: "Send me your last workout — sets, reps, rough is fine."
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
