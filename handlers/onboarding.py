"""
Onboarding flow. Uses tool-based architecture — Arnie calls update_profile()
as it collects answers. The system prompt is built dynamically so Claude always
knows exactly what's been collected and what to ask next.

Steps (in order): name → sex → age → height/weight → goal → experience → diet/injuries → timezone → targets
goal_weight_kg is collected naturally during the goal step but is NOT a required blocker.
"""
from db.models import User

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie — a sharp, direct fitness coach meeting a new client for the first time. Think: first conversation at the gym. Efficient, real, no fluff. Warm but never a cheerleader.

LANGUAGE: Detect the language of the user's first message and conduct the entire onboarding in that language. Translate every question, label, and option naturally — never leave English text in a non-English response.

STYLE:
- Acknowledge each answer in ONE sentence. Make it specific and coaching — not "great!" but an actual reaction. Then immediately ask the next question.
- NO hollow praise: no "Awesome!", "Great!", "Fantastic!", "Perfect!"
- YES to specific reactions:
  • After name: "Good to meet you, [Name]."
  • After goal — cut: "Cutting is 80% nutrition. That's where we'll do the real work."
  • After goal — bulk: "Smart. We'll chase progressive overload and keep the surplus clean."
  • After goal — maintain: "Maintenance done right is harder than people think. Consistency is the whole game."
  • After goal — performance: "Performance goals are the fun ones. Let's build something that actually transfers."
  • After goal — health: "Solid foundation to work from. We'll keep it sustainable."
  • After weight/height: "Got it — those numbers are about to mean something."
  • After experience — beginner: "Good starting point. We'll build the habits right from day one."
  • After experience — intermediate: "Solid base. We'll work on the details that actually move the needle."
  • After experience — advanced: "You already know how this works. We'll go deeper."
  • After diet/injuries: "Noted — I'll keep that in mind every time I coach you."

RULES:
- ALWAYS end your message with the next question.
- Save each answer immediately using update_profile() with exact field names.
- If they give multiple pieces of info at once (e.g. "26, male"), save ALL of it in one update_profile() call.
- Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
- If user says "no restrictions", "no injuries", "none" — save that string, don't skip.
- ALWAYS write a text response alongside any tool call.
- If they tap a button option (e.g. "Male", "Cut 🔻", "Beginner") — accept it exactly as typed and respond naturally.
- goal_weight_kg is optional — ask for it as part of the goal question (e.g. "What are you cutting to?") but do NOT block progress if they skip it.

Field names: name, age, sex (male/female), height_cm, current_weight_kg, goal_weight_kg (optional), primary_goal (cut/bulk/maintain/performance/health), training_experience (beginner/intermediate/advanced), dietary_preferences, injuries, timezone, calorie_target, protein_target.

TARGETS STEP — after all essentials are collected, help them set calorie and protein targets. Present THREE clear options:

"Last thing — targets. Three ways to handle it:
1. <b>Calculate for me</b> — I'll run the math from your stats
2. <b>I have my numbers</b> — tell me what you want
3. <b>Skip for now</b> — we'll dial in once we see how you eat"

IF they pick option 1 (calculate): Use Mifflin-St Jeor BMR:
- BMR (male): 10×W_kg + 6.25×H_cm − 5×age + 5
- BMR (female): 10×W_kg + 6.25×H_cm − 5×age − 161
- TDEE = BMR × 1.55 (moderately active lifter)
- Cut: TDEE − 450 cal | Maintain: TDEE | Bulk: TDEE + 300 cal | Performance/health: TDEE
- Protein: bodyweight_lbs × 0.9g (cut/maintain), × 0.8g (bulk)
Round calories to nearest 50, protein to nearest 5.
Show the math briefly — e.g. "TDEE ~2,600 → cut target: 2,150 cal, 178g protein" — then save with update_profile(calorie_target, protein_target).

IF they pick option 2 (specify): Save the numbers they give.

IF they pick option 3 (skip): Call update_profile(onboarding_completed: true) and note they can say "set my targets" anytime.

COMPLETION: After targets are handled, call update_profile(onboarding_completed: true). Then write ONE brief sentence — e.g. "You're all set, [Name]. Let's get to work." DO NOT write a tutorial — the system sends detailed instructions automatically."""


def build_onboarding_system(user: User) -> str:
    """
    Build a dynamic onboarding system prompt showing current state.

    Steps are intentionally granular (sex and age separate) so that partial
    answers from button taps don't re-ask already-answered fields.
    goal_weight_kg is NOT a step blocker — it's collected as part of the goal
    question but progress continues regardless.
    """
    prefs = user.preferences

    def has(field):
        return getattr(user, field, None) is not None

    def pref_has(field):
        return prefs and getattr(prefs, field, None) is not None

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
        ("height & weight",
         has("height_cm") and has("current_weight_kg"),
         "What's your height and current weight?"),
        ("goal",
         has("primary_goal"),
         "What are you training for — cutting, bulking, maintaining, performance, or health? "
         "If you have a target weight, drop that in too."),
        ("training experience",
         has("training_experience"),
         "How experienced are you — beginner, intermediate, or advanced?"),
        ("diet & injuries",
         has("dietary_preferences") and has("injuries"),
         "Any dietary restrictions or injuries I should know about?"),
        ("timezone",
         has("timezone") and user.timezone != "UTC",
         "What city are you based in? I'll use it to time my check-ins."),
    ]

    collected_lines = []
    next_question = None

    for label, complete, question in steps:
        if complete:
            collected_lines.append(label)
        elif next_question is None:
            next_question = question

    state_block = "\n\nONBOARDING STATE:"
    if collected_lines:
        state_block += "\nCollected: " + ", ".join(collected_lines)
    else:
        state_block += "\nNothing collected yet."

    if next_question:
        state_block += (
            f'\n\nNEXT QUESTION (ask this, adapt naturally to conversation): "{next_question}"'
            "\nDo NOT skip ahead. Do NOT ask about targets yet."
        )
    else:
        if pref_has("calorie_target"):
            state_block += (
                "\n\nAll essentials AND targets are set."
                "\nCall update_profile(onboarding_completed: true) and write ONE brief welcoming sentence."
                "\nDo NOT write a usage tutorial — the system handles that automatically."
            )
        else:
            state_block += (
                "\n\nALL ESSENTIALS COLLECTED — run the TARGETS STEP now."
                "\nPresent the 3 options exactly as specified above."
                "\nAfter they respond, handle it AND call update_profile(onboarding_completed: true)."
            )

    return _ONBOARDING_BASE + state_block


def get_onboarding_keyboard(user: User):
    """
    Return a ReplyKeyboardMarkup for the current onboarding step, or None for free-text steps.

    IMPORTANT: This must mirror build_onboarding_system's steps exactly —
    same field checks, same order — so the keyboard always matches what
    the LLM is about to ask.
    """
    from telegram import ReplyKeyboardMarkup

    def has(field):
        return getattr(user, field, None) is not None

    prefs = user.preferences

    # Step 1: name — free text
    if not has("name"):
        return None

    # Step 2: sex — quick-reply buttons
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

    # Step 5: goal — quick-reply buttons (mirrors: has("primary_goal"))
    if not has("primary_goal"):
        return ReplyKeyboardMarkup(
            [["Cut 🔻", "Bulk 📈", "Maintain ⚖️"],
             ["Performance ⚡", "Health 🌿"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Step 6: training experience
    if not has("training_experience"):
        return ReplyKeyboardMarkup(
            [["Beginner", "Intermediate", "Advanced"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Step 7: diet & injuries
    if not (has("dietary_preferences") and has("injuries")):
        return ReplyKeyboardMarkup(
            [["No restrictions", "Vegetarian", "Vegan"],
             ["No injuries", "Gluten-free", "Other…"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Step 8: timezone — free text (city name)
    if not has("timezone") or user.timezone == "UTC":
        return None

    # Targets step
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
