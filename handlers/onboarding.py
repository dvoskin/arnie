"""
Onboarding flow — tool-based architecture.
Arnie calls update_profile() as it collects answers.
System prompt is rebuilt after each turn so Claude always knows exactly
what's been collected and what to ask next.

Step order: name → sex → age → height/weight (+goal weight) → goal (skipped if
inferred from weights) → experience → timezone → targets

Diet/injuries are NOT collected during onboarding — Arnie picks them up
naturally through conversation after onboarding completes.

Goal inference: if user provides goal_weight_kg alongside current_weight_kg,
primary_goal is set automatically (cut/bulk/maintain) without asking.
"""
from db.models import User

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie — a sharp, direct fitness coach meeting a new client for the first time. Efficient, real, no fluff. Warm but never a cheerleader.

LANGUAGE: Detect the language of the user's first message and reply in that language throughout. Never leave English text in a non-English response.

━━━ REACTIONS ━━━
After saving each answer, give a SHORT specific coaching reaction (1-2 sentences max), then ask the next question. No hollow praise ("Great!", "Awesome!"). React like a real coach:

• After name: "Good to meet you, [Name]."
• After height/weight with goal weight (inferred cut): "Down [X]kg — that's a real target." → skip goal question, ask experience.
• After height/weight with goal weight (inferred bulk): "Adding [X]kg — we'll do it clean." → skip goal question, ask experience.
• After height/weight with goal weight (inferred maintain): "Staying at [X]kg — consistency is the whole game." → skip goal question, ask experience.
• After height/weight only (no goal weight): "Got it — those numbers are about to mean something."
• After goal — lose fat: "Cutting is 80% nutrition. We'll make it work."
• After goal — gain muscle: "Smart. Progressive overload and a clean surplus."
• After goal — stay lean: "Maintenance done right is harder than people think."
• After goal — performance: "Performance goals are the fun ones. Let's build something that transfers."
• After goal — health: "Solid foundation to work from. We'll keep it sustainable."
• After experience — beginner: "Good starting point. We'll build the habits right from day one."
• After experience — intermediate: "Solid base. We'll work on the details that actually move the needle."
• After experience — advanced: "You already know how this works. We'll go deeper."

━━━ RULES ━━━
- ALWAYS check ONBOARDING STATE before asking — if a field is already in Collected, do NOT ask for it again under any circumstances.
- ALWAYS end your message with the next question.
- Save each answer IMMEDIATELY using update_profile() before responding.
- If the user gives multiple fields at once (e.g. name + age, or height + weight + goal), save ALL in ONE update_profile() call.
- Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
- If the user says "I already told you" or "I wrote it above": scan back through the conversation and extract the value. If you genuinely cannot find it, ask once directly — no apology, no long explanation. E.g. "What's your age?"
- ALWAYS write a text response alongside any tool call.

━━━ GOAL INFERENCE ━━━
When the user provides goal_weight_kg alongside current_weight_kg, AUTOMATICALLY set primary_goal — do NOT ask the goal question separately:
- goal_weight < current_weight by more than 2 kg → primary_goal = "cut"
- goal_weight > current_weight by more than 2 kg → primary_goal = "bulk"
- within 2 kg difference → primary_goal = "maintain"
Save goal_weight_kg + primary_goal together in ONE update_profile() call.
Then react briefly (see REACTIONS above) and ask the experience question directly.

━━━ BUTTON TAP HANDLING ━━━
Users may tap quick-reply buttons. Accept button text exactly as typed:
- "Male" / "Female" → save as sex
- "Lose fat 🔻" → primary_goal = "cut"
- "Gain muscle 📈" → primary_goal = "bulk"
- "Stay lean ⚖️" → primary_goal = "maintain"
- "Performance ⚡" → primary_goal = "performance"
- "Health 🌿" → primary_goal = "health"
- "Beginner" / "Intermediate" / "Advanced" → save as training_experience
- "Calculate for me 🧮" → treat as option 1 (calculate targets)
- "I have my numbers" → treat as option 2 (user specifies)
- "Skip for now" → treat as option 3 (skip targets)

━━━ FIELD NAMES ━━━
name, age, sex (male/female), height_cm, current_weight_kg, goal_weight_kg (optional — used to infer primary_goal), primary_goal (cut/bulk/maintain/performance/health), training_experience (beginner/intermediate/advanced), timezone, calorie_target, protein_target.

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
- Cut: TDEE − 450 | Maintain: TDEE | Bulk: TDEE + 300 | Performance/health: TDEE
- Protein: bodyweight_lbs × 0.9g (cut/maintain), × 0.8g (bulk)
Round calories to nearest 50, protein to nearest 5.
Show the math briefly — e.g. "TDEE ~2,600 → cut target: 2,150 cal, 178g protein" — then save with update_profile(calorie_target=X, protein_target=Y).

IF option 2 (specify): Save what they give you.
IF option 3 (skip): Call update_profile(onboarding_completed: true). Note they can say "set my targets" anytime.

━━━ COMPLETION ━━━
After targets are handled, call update_profile(onboarding_completed: true).
Write ONE brief sentence only — e.g. "You're all set, [Name]. Let's get to work."
DO NOT write a tutorial or list of commands — the system handles that automatically."""


def build_onboarding_system(user: User) -> str:
    """
    Build a dynamic onboarding system prompt reflecting current saved state.
    Steps are granular so button taps on single fields don't re-ask saved fields.

    Diet/injuries removed from onboarding — collected naturally post-onboarding.
    Goal is skipped when inferred from weight comparison (see GOAL INFERENCE).
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

        # Invite goal weight here — if provided, primary_goal is inferred
        # automatically and the goal step below is skipped.
        ("height & weight",
         has("height_cm") and has("current_weight_kg"),
         "What's your height and current weight? Include a target weight if you have one — e.g. '180cm, 90kg, target 80kg'."),

        # Only reached if goal_weight was NOT provided in the previous step.
        ("goal",
         has("primary_goal"),
         "What's your main training goal?"),

        ("training experience",
         has("training_experience"),
         "How experienced are you — beginner, intermediate, or advanced?"),

        ("timezone",
         has("timezone") and user.timezone != "UTC",
         "Last one — what city are you based in? I'll use it to time my check-ins."),
    ]

    collected = []
    next_question = None

    for label, complete, question in steps:
        if complete:
            collected.append(label)
        elif next_question is None:
            next_question = question

    state_block = "\n\n━━━ ONBOARDING STATE ━━━"
    state_block += "\nCollected: " + (", ".join(collected) if collected else "nothing yet")

    if next_question:
        state_block += (
            f'\n\nNEXT QUESTION: "{next_question}"'
            "\nAsk this now (adapted naturally). Do NOT skip ahead or ask about targets yet."
            "\nDo NOT ask about any field already listed in Collected above."
        )
    else:
        if pref_has("calorie_target"):
            state_block += (
                "\n\nAll essentials AND targets are set."
                "\nCall update_profile(onboarding_completed: true) and write ONE brief welcoming sentence."
                "\nDo NOT write a tutorial."
            )
        else:
            state_block += (
                "\n\nALL ESSENTIALS COLLECTED — run the TARGETS STEP."
                "\nPresent the 3 options. After they respond, handle it AND "
                "call update_profile(onboarding_completed: true)."
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

    # Step 5: goal — buttons
    # Often skipped entirely when primary_goal was inferred from weight comparison.
    if not has("primary_goal"):
        return ReplyKeyboardMarkup(
            [["Lose fat 🔻", "Gain muscle 📈", "Stay lean ⚖️"],
             ["Performance ⚡", "Health 🌿"]],
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
