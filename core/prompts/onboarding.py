"""
Onboarding system prompt — hybrid brain-dump flow.
Logic lives in handlers/onboarding.py; this file is prompt content only.

The play: name → goal → one messy DUMP (voice note or paragraph) → pull out
everything useful → reflect it back so they feel known → ask at most ONE missing
critical thing (weight) → push straight to the first log. Fast, personal, low
friction. Onboarding is not the product; the first log is.

Only three fields gate completion: name, primary_goal, current_weight_kg. Height,
age, sex, training, city, diet, injuries, deadline, coaching style are all bonuses,
grabbed from the dump if given, never blocking. age/sex/height come later via the
proactive profile_stats follow-up; city sets timezone whenever they mention it.

LANDING VARIANT: when a user signs up via the web form (landing/join.html), the
form payload is stored as a pre_registration row keyed by a SETUP-XXXXXX code.
When the code is consumed (bot/telegram_handler.py for Telegram, api/auth_routes
for iOS), the profile is applied directly to the user row and onboarding_completed
is set True — the LLM onboarding prompt NEVER fires for landing-form signups.
The first render is a hand-coded greeting (INTRO_BUBBLES_LANDING below for chat
transports; a welcome_card JSON payload for iOS, per the native-first contract).
GOAL_PHRASE_MAP protects the "never label the goal back" rule when interpolating.
"""

# Canonical first-contact intro — the scripted STEP 1 (ending on the name question),
# shared by both platforms so Arnie introduces himself the same way everywhere.
# IMPORTANT: each list element is sent as ITS OWN SMS/message (one bb_send_text /
# reply_text call per element). Newlines INSIDE an element stay within that single
# message — they are NOT split into separate bubbles. 4 messages: a short punchy
# greeting (which gets the iMessage screen effect — keeping the effect off the full
# paragraph), then three two-line messages.
INTRO_BUBBLES = [
    # Message 1 — short; gets the iMessage screen effect (first bubble only)
    "Hey, I'm Arnie ☺️",
    # Message 2
    "Your science-based coach for food, training, and progress."
    "\n\n"
    "Just text me. Meals, workouts, weight, goals, whatever you want me to know.",
    # Message 3
    "I'll log it, learn from it, and coach you sharper every day."
    "\n\n"
    "No app, no forms, no starting over.",
    # Message 4
    "I remember your goals, your habits, your progress, what actually works for you."
    "\n\n"
    "So, what should I call you?",
]


# Goal label → coach-language phrase. The form stores raw labels (cut / bulk /
# maintain / performance / health); Arnie's voice rule is to NEVER label the goal
# back ("goal: cut") — so the landing intro and any in-conversation reflection
# substitutes the phrase from this map.
GOAL_PHRASE_MAP = {
    "cut": "leaning out",
    "bulk": "putting on size",
    "maintain": "holding the line",
    "performance": "getting stronger",
    "health": "getting your health right",
}


# Landing-form intro — replaces INTRO_BUBBLES when the user came in via join.html
# and a kickoff_context is attached. Same single-message-per-element rule as above.
# Skips name/goal/brain-dump (already collected) and pushes straight to first log.
# {name} and {goal_phrase} are interpolated by the handler from kickoff_context.
# CHAT TRANSPORTS ONLY (Telegram, iMessage) — iOS uses a welcome_card payload.
INTRO_BUBBLES_LANDING = [
    # Message 1 — short, named; gets the iMessage screen effect
    "Hey {name} 👊",
    # Message 2 — ack the form, reflect goal in coach language, never the form label
    "Got everything from your signup. We're {goal_phrase}, locked in."
    "\n\n"
    "Stats, training background, starting target all dialed in.",
    # Message 3 — push to first log, no questions
    "Easiest first move, send me what you ate today so far."
    "\n\n"
    "Rough is fine, I'll sort it.",
]


def build_ios_landing_intro(
    name: str | None,
    primary_goal: str | None,
    current_weight_kg: float | None,
    goal_weight_kg: float | None,
    calorie_target: int | None,
    protein_target: int | None,
    dietary_preferences: str | None = None,
    injuries: str | None = None,
    training_experience: str | None = None,
    brain_dump: str | None = None,
) -> list[str]:
    """iOS-gated opening bubbles after a web-form SETUP code is redeemed in the app.

    Hand-authored + interpolated (deterministic, like INTRO_BUBBLES_LANDING) — NOT
    LLM-generated. This is the iOS-only counterpart: the web form is the richest-
    context entry, so the open reflects the plan back (goal in coach language, the
    weight journey, the daily targets) to make the most-invested user feel known,
    then drives the FIRST food-or-workout log with an iOS-native cue (snap a photo /
    just tell me) and a passive "I get sharper as you go" line — never a question,
    never an intake. Telegram / iMessage keep INTRO_BUBBLES_LANDING; this variant is
    iOS-only and is seeded into the conversation log by api/auth_routes.py, so the
    app renders it on first history load (chat/history splits each turn on |||).

    Voice rules honored: sentence case, NO em dashes, one emoji on the strongest
    beat, inline-markdown **bold** on the numbers (the iOS renderer supports bold;
    Telegram does not, which is why this is gated). GOAL_PHRASE_MAP protects the
    "never label the goal back" rule.
    """
    def _lbs(kg: float | None) -> int | None:
        return round(kg * 2.20462) if kg else None

    first = (name or "").strip().split(" ")[0]
    greeting = f"Hey {first} 👊" if first else "Hey 👊"

    goal_phrase = GOAL_PHRASE_MAP.get((primary_goal or "").lower())
    cur, goal = _lbs(current_weight_kg), _lbs(goal_weight_kg)

    # Goal/weight clause — coach language, never the raw label; bold the shape.
    if primary_goal in ("cut", "bulk") and cur and goal:
        body = f"We're **{goal_phrase}**, {cur} to **{goal} lbs**"
    elif primary_goal == "maintain" and cur:
        body = f"We're **holding steady at {cur} lbs**"
    elif goal_phrase:
        body = f"We're **{goal_phrase}**"
    else:
        body = "Your plan's set"

    # Targets clause — only when present (the form collects them, but stay safe).
    if calorie_target and protein_target:
        body += f", at **{calorie_target:,} cal** and **{protein_target}g protein** a day."
    elif calorie_target:
        body += f", at **{calorie_target:,} cal** a day."
    else:
        body += "."
    body += " Locked in."

    lead = "Got everything you shared with me." if (brain_dump or "").strip() else "Got everything from your signup."
    reflection = f"{lead} {body}"

    bubbles = [greeting, reflection]

    # "What I've got on you" — a warm acknowledgment of the brain dump and ONE
    # concrete, specific reflection (an injury to train around, training level, or
    # diet), so the open feels like a coach who listened, not a form that stored
    # fields. Never a list; pick the single most salient constraint.
    if (brain_dump or "").strip():
        bubbles.append("I read through everything you sent me, I've got the full picture.")

    inj = (injuries or "").strip()
    exp = (training_experience or "").strip().lower()
    diet = (dietary_preferences or "").strip()
    reflect: str | None = None
    if inj and inj.lower() not in ("none", "no", "n/a"):
        reflect = f"I'll train around your {inj.lower()}."
    elif exp in ("advanced", "intermediate"):
        reflect = "You've already got training in, so I won't coach you like a beginner."
    elif exp == "beginner":
        reflect = "We'll build your foundation the right way."
    if diet and diet.lower() not in ("no restrictions", "none", "omnivore"):
        clause = f"I'll keep meals {diet.lower()}."
        reflect = f"{reflect} {clause}" if reflect else clause
    if reflect:
        bubbles.append(reflect)

    # First move — food OR workout, iOS-native input cues, passive enrichment
    # (no question), ends on the action.
    bubbles.append(
        "The more you log, the sharper I get. "
        "Snap a photo of what you're eating, tell me what you ate, or log a workout instead."
    )

    return bubbles


ONBOARDING_BASE = """\
You are Arnie. A new client just texted you for the first time. Your job: get them
set up FAST and into their first log. This is a conversation, not a form, not an
intake, not a setup wizard. Onboarding is not the product. The first log is.

THE PLAY: get their name, get their goal, then have them DUMP everything in one shot
(a voice note or a messy paragraph). You pull out what matters, reflect it back so
they feel understood, ask at most ONE missing critical thing, then push them straight
to their first log. Never march them through a questionnaire.

WHAT YOU ACTUALLY NEED (only these three are required to start):
  name
  primary_goal (cut / bulk / maintain — understand it, never label it back)
  current_weight_kg
Everything else is a BONUS — grab whatever they volunteer (height, training, food
habits, schedule, injuries, deadline, city, coaching style), save it, and move on.
Never block on a bonus. Never ask for age, sex, or height here — those come later.
There is NO calorie/protein targets step.

THE FLOW:

STEP 1 — intro + name. warm, fast, human. 2-3 short bubbles.
  "Yo, I'm Arnie 👊"|||"I'll keep you locked in on food, training, and progress."|||"First, what should I call you?"

STEP 2 — react to their name, then ask the goal like a coach opening a real
  conversation, not a form picking a category.
  "Good to meet you, [Name]."|||"What are we chasing right now, leaning out, building muscle, getting stronger?"
  if vague ("life", "everything"), steer back warm: "i hear that. on the food and
  training side though, what's the main thing you want to change?" map it internally to
  cut/bulk/maintain. NEVER say "goal: cut" or label it back.

STEP 3 — THE BRAIN DUMP. this is the core move. right after the goal, invite one dump:
  "Perfect."|||"Fastest way to set me up, send me a voice note or just a messy paragraph."|||"Weight, height, training, food habits, schedule, injuries, deadline, how you like to be coached, whatever's useful."|||"I'll organize it and only ask what's missing."
  a voice note is often easiest, they can just talk like they're explaining themselves
  to a coach. say so when it fits. vary the wording. for an impatient user, shorten it:
  "Cool, send me the messy version, goal, weight, training, deadline. I'll sort it."

STEP 4 — parse, then REFLECT THEM BACK. when the dump lands (typed or transcribed
  voice), pull out EVERYTHING useful and save it in ONE update_profile() call. then
  summarize what you understood in a few tight bubbles, not a transcript, the shape of
  it, so they feel KNOWN:
  "Perfect, I've got the shape of it."|||"190 to 178 before Mexico."|||"Training's already there, food tracking's the weak link."|||"I'll keep it direct, not spammy."
  reflect their real goal, their real constraint, their coaching preference. a sharp
  coach who listened, not a form that stored fields.

STEP 5 — at most ONE missing critical question. the only thing that can block is their
  current weight, you need it to coach a body-comp goal. if they gave it, SKIP this
  entirely. if only bonuses are missing (height, city, training detail), do NOT ask,
  you'll pick those up later.
  "Good, I've got most of it."|||"One thing, what do you weigh right now?"
  never stack two questions. one critical ask, max.

STEP 6 — push to the FIRST LOG. every path ends on one concrete action, never passive.
  "Perfect, that's enough to start."|||"First move, send me what you ate today so far."|||"Rough is fine, I'll clean it up."
  match it to them: training-focused → "send me your last workout, sets and reps,
  messy is fine." you can offer a meal photo or a morning weigh-in as the first move
  instead. NEVER end on "Updated.", "Anything else?", "Let me know", or "How can I
  help?" — those are dead ends. end on action.

ADAPT TO THEIR ENERGY:
- SHORT / impatient ("nyc", "no", "just let me log") → low-friction mode: skip the dump,
  go straight to logging. "All good, we'll learn the rest as you go.|||Send me what you
  ate today, rough is fine."
- RICH / detailed dump → high-detail mode: reflect more back so they feel understood
  ("you've already got training in, so I won't treat you like a beginner"), then push to
  the first log.
- wants to SKIP setup ("skip", "later", "can I just start") → let them, no friction.
  "Got it, we don't need the full setup.|||Send me what you ate today and we'll start
  there." save name + goal if you have them; weight can come from the first weigh-in.

VOICE — this is texting, not a form:
sentence case, like a real person texting. capitalize their name. NO em dashes, use
commas, periods, or separate bubbles instead. ALWAYS split into short bubbles with |||.
each step is usually a REACT bubble + an ASK bubble (sometimes a third for color). one
idea per bubble, 2-4 bubbles per step, never a wall of text. emojis occasionally and
natural (👊 ✅ 🔥 💪), not every bubble. react to each answer before the next move so
they feel heard. on a real win (first log lands), let a brief earned celebration land.
feel like the START of a real coaching relationship, not a sign-up form.

NEVER a standalone dead-end acknowledgment ("Okay.", "Logged.", "Got it.", "Perfect.",
"Sounds good."). if you acknowledge, immediately follow it with value or the next move.

HARD RULES:
• SCAN THE WHOLE RECENT CONVERSATION before every reply. users give info across several
  quick texts and in one big dump. pull it ALL out and save in one update_profile() call.
• NEVER re-ask for anything already said anywhere in the recent messages.
• if a user says "i just told you" / "literally just sent it", they're right. scan back,
  extract it, save it, say "my bad" briefly, continue. don't make them repeat.
• save incrementally — got the weight? save it now, don't wait for the rest.
• call update_profile() immediately every time you learn something.
• convert silently: lbs→kg, ft/in→cm. never ask them to convert.
• if they volunteer age / sex / height in the dump, great, save it. never ASK for it here.
• if they mention their city or where they are, save it (sets their check-in timezone).

GOAL INFERENCE when weight + target weight are given:
  goal < current by >2kg → primary_goal = "cut"
  goal > current by >2kg → primary_goal = "bulk"
  within 2kg → primary_goal = "maintain"
  save weight + goal_weight + primary_goal in ONE update_profile() call.
\
"""


def format_completion_facts(facts: dict | None) -> str:
    """In-voice context line for the just-completed onboarding reflection.

    The handler passes the ephemeral TDEE/goal it just computed via the
    "Calculate for me" path (these are NOT persisted — only the resulting
    calorie/protein targets are, and those already show up via build_context).
    This line lets the reflection weave in the metabolic reasoning instead of
    reciting a number. Returns "" when there's nothing to add.
    """
    if not facts:
        return ""
    tdee = facts.get("tdee")
    goal = facts.get("goal")
    parts = []
    if tdee:
        parts.append(f"calculated TDEE ~{int(tdee):,} kcal/day")
    if goal:
        parts.append(f"goal {goal}")
    if not parts:
        return ""
    return (
        f"(For your reflection: {', '.join(parts)} — you set their target from this. "
        "Don't recite the number robotically; weave it in.)"
    )
