"""
Onboarding flow — tool-based architecture.
Arnie calls update_profile() as it collects answers.
System prompt is rebuilt after each turn so Claude always knows exactly
what's been collected and what to ask next.

Step order: name → sex → age → height/weight (+goal weight) → goal (skipped if
inferred from weights) → experience → timezone → targets

Diet/injuries NOT collected during onboarding.
Goal inference: if user provides goal_weight_kg with height/weight, primary_goal
is set automatically and the goal step is skipped entirely.
"""
from db.models import User

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie, an AI fitness coach onboarding a new client. You are in a STRICT SEQUENTIAL FLOW. Move fast. No filler.

LANGUAGE: Match the language of the user's first message throughout.

━━━ THE ONLY THING YOU DO EACH TURN ━━━
1. Call update_profile() to save the answer immediately.
2. Write ONE short sentence (reaction or acknowledgment).
3. Ask the NEXT QUESTION shown in ONBOARDING STATE below.
That is it. Nothing else. No extra questions. No follow-ups. No elaboration.

━━━ HARD RULES ━━━
- ONBOARDING STATE → Collected list is your source of truth. If a field is in Collected, it is DONE. Never ask about it again under any circumstances.
- NEXT QUESTION in ONBOARDING STATE is the ONLY question you may ask. Ask it exactly (you may rephrase it naturally but do not change what information you are collecting).
- Never ask two questions in the same message.
- Never ask a follow-up question after saving an answer. Save it → react in one sentence → ask the next question. Done.
- If user provides multiple fields at once, save ALL in one update_profile() call, then ask the single next uncollected question.
- Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
- If user says "I already told you" or "I wrote that above": scan back through the conversation, extract the value, save it, move on. If genuinely not found, ask once with zero apology — e.g. just "What's your age?"
- Do NOT say "Okay", "Got it" or any filler without also asking the next question in the same message.

━━━ REACTIONS (one sentence max, then immediately the NEXT QUESTION) ━━━
• After name: "Good to meet you, [Name]." → next question
• After height/weight with goal inferred cut: "Down [X]kg — let's get there." → ask experience
• After height/weight with goal inferred bulk: "Adding [X]kg — we'll do it clean." → ask experience
• After height/weight with goal inferred maintain: "Staying at [X]kg — consistency is the game." → ask experience
• All other steps: no reaction sentence needed — just ask the next question directly.

━━━ GOAL INFERENCE ━━━
When user provides goal_weight_kg alongside height/weight, set primary_goal automatically:
- goal_weight < current_weight by >2kg → primary_goal = "cut"
- goal_weight > current_weight by >2kg → primary_goal = "bulk"
- within 2kg → primary_goal = "maintain"
Save height_cm + current_weight_kg + goal_weight_kg + primary_goal in ONE update_profile() call.
Then ask the experience question directly — do NOT ask about goals separately.

━━━ BUTTON TAP HANDLING ━━━
- "Male" / "Female" → save as sex
- "Lose Weight" → primary_goal = "cut"
- "Gain Weight" → primary_goal = "bulk"
- "Maintain" → primary_goal = "maintain"
- "Beginner" / "Intermediate" / "Advanced" → save as training_experience
- "Calculate for me 🧮" → option 1 (calculate targets)
- "I have my numbers" → option 2 (user specifies)
- "Skip for now" → option 3 (skip targets)

━━━ FIELD NAMES ━━━
name, age, sex (male/female), height_cm, current_weight_kg, goal_weight_kg (optional), primary_goal (cut/bulk/maintain), training_experience (beginner/intermediate/advanced), timezone, calorie_target, protein_target.

━━━ TARGETS STEP ━━━
After all essentials are collected, present three options:

"Last thing — targets. Three ways to handle it:
1. <b>Calculate for me</b> — I'll run the math from your stats
2. <b>I have my numbers</b> — tell me what you want
3. <b>Skip for now</b> — we'll dial in once we see how you eat"

IF option 1 (calculate): Use Mifflin-St Jeor BMR:
- BMR male: 10×W_kg + 6.25×H_cm − 5×age + 5
- BMR female: 10×W_kg + 6.25×H_cm − 5×age − 161
- TDEE = BMR × 1.55 (moderately active lifter)
- Cut: TDEE − 450 | Maintain: TDEE | Bulk: TDEE + 300
- Protein: bodyweight_lbs × 0.9g (cut/maintain), × 0.8g (bulk)
Round calories to nearest 50, protein to nearest 5.
Show briefly — e.g. "TDEE ~2,600 → cut target: 2,150 cal, 178g protein" — then save with update_profile(calorie_target=X, protein_target=Y).

IF option 2: Save what they give you.
IF option 3: Call update_profile(onboarding_completed=true). Tell them they can say "set my targets" anytime.

━━━ COMPLETION ━━━
After targets are handled, call update_profile(onboarding_completed=true).
Write ONE sentence only — e.g. "You're all set, [Name]. Let's get to work."
DO NOT write a tutorial or list of commands."""


def build_onboarding_system(user: User) -> str:
    """
    Build a dynamic onboarding system prompt reflecting current saved state.
    The NEXT QUESTION is injected explicitly so the LLM has no ambiguity
    about what to ask — it cannot skip, re-ask, or deviate.
    """
    prefs = user.preferences

    def has(field):
        return getattr(user, field, None) is not None

    def pref_has(field):
        return prefs and getattr(prefs, field, None) is not None

    # Each step: (label, is_complete, question_to_ask_next)
    # NOTE: get_onboarding_keyboard() must mirror these checks exactly.
    steps = [
        ("name",
         has("name"),
         "What's your first name?"),

        ("sex",
         has("sex"),
         "Are you male or female?"),

        ("age",
         has("age"),
         "How old are you?"),

        # Inviting goal weight here means primary_goal is often inferred
        # automatically and the goal step below is skipped entirely.
        ("height & weight",
         has("height_cm") and has("current_weight_kg"),
         "What's your height and current weight? Add a target weight too if you have one — e.g. '180cm, 90kg, target 80kg'."),

        # Only reached if primary_goal was NOT inferred from weight comparison.
        ("goal",
         has("primary_goal"),
         "What's your goal — lose weight, gain weight, or maintain?"),

        ("training experience",
         has("training_experience"),
         "How experienced are you — beginner, intermediate, or advanced?"),

        ("timezone",
         has("timezone") and user.timezone != "UTC",
         "What city are you based in? I'll use it to time my check-ins."),
    ]

    collected = []
    next_question = None

    for label, complete, question in steps:
        if complete:
            collected.append(label)
        elif next_question is None:
            next_question = question

    state_block = "\n\n━━━ ONBOARDING STATE ━━━"
    state_block += "\nCollected so far: " + (", ".join(collected) if collected else "nothing yet")
    state_block += "\nDO NOT ask about anything in the Collected list — those are finished."

    if next_question:
        state_block += (
            f'\n\nNEXT QUESTION (ask this and ONLY this): "{next_question}"'
        )
    else:
        if pref_has("calorie_target"):
            state_block += (
                "\n\nAll essentials AND targets are set."
                "\nCall update_profile(onboarding_completed=true) and write ONE brief sentence. No tutorial."
            )
        else:
            state_block += (
                "\n\nALL ESSENTIALS COLLECTED — run the TARGETS STEP now."
                "\nPresent the 3 options. Handle the response, then call update_profile(onboarding_completed=true)."
            )

    return _ONBOARDING_BASE + state_block


def get_onboarding_keyboard(user: User):
    """
    Return a ReplyKeyboardMarkup for the current onboarding step, or None.
    Called after tool execution so user state is up to date.

    CRITICAL: field checks here must mirror build_onboarding_system() steps
    exactly — same fields, same order — so the keyboard always matches what
    the LLM is about to ask.
    """
    from telegram import ReplyKeyboardMarkup

    def has(field):
        return getattr(user, field, None) is not None

    prefs = user.preferences

    # Step 1: name — free text
    if not has("name"):
        return None

    # Step 2: sex — buttons
    if not has("sex"):
        return ReplyKeyboardMarkup(
            [["Male", "Female"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Step 3: age — free text
    if not has("age"):
        return None

    # Step 4: height & weight — free text
    if not (has("height_cm") and has("current_weight_kg")):
        return None

    # Step 5: goal — buttons (often skipped when primary_goal inferred from weights)
    if not has("primary_goal"):
        return ReplyKeyboardMarkup(
            [["Lose Weight", "Gain Weight", "Maintain"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Step 6: training experience — buttons
    if not has("training_experience"):
        return ReplyKeyboardMarkup(
            [["Beginner", "Intermediate", "Advanced"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Step 7: timezone — free text (city name)
    if not has("timezone") or user.timezone == "UTC":
        return None

    # Targets step — buttons
    if prefs and not getattr(prefs, "calorie_target", None):
        return ReplyKeyboardMarkup(
            [["Calculate for me 🧮"],
             ["I have my numbers"],
             ["Skip for now"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
