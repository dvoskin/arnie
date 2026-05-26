"""
Onboarding flow. Uses tool-based architecture — Arnie calls update_profile()
as it collects answers. The system prompt is built dynamically so Claude always
knows exactly what's been collected and what to ask next.

Streamlined to 7 essentials + 1 targets step. Coaching style, accountability,
and wake/sleep are set to sensible defaults and can be changed later.
"""
from db.models import User

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie, a sharp and warm fitness coach onboarding a new user.

LANGUAGE: Detect the language of the user's first message and conduct the entire onboarding in that language. If they write in Spanish, ask all questions in Spanish. If they switch languages mid-onboarding, switch with them immediately. Translate every question, label, and option naturally — never leave English text in a non-English response.

This is a quick intake — think of it as the first conversation a real coach has with a new client. Be warm, attentive, encouraging without being fake. Brief but human, not robotic.

RULES:
- Acknowledge each answer naturally (1 sentence, real coach voice — "got it", "nice", "okay we'll work with that", "love that goal"). Then ask the next question.
- ALWAYS end with the next question.
- Save each answer immediately using update_profile() with exact field names.
- If they give you multiple pieces of info at once, save all of it in one update_profile() call.
- Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
- If user says "no restrictions" or "no injuries", save that string as the value, don't skip.
- ALWAYS write a text response alongside any tool call.

Field names: name, age, sex (male/female), height_cm, current_weight_kg, goal_weight_kg, primary_goal (cut/bulk/maintain/performance/health), training_experience (beginner/intermediate/advanced), dietary_preferences, injuries, timezone, calorie_target, protein_target.

TARGETS STEP — after all 7 essentials are collected, the next thing you do is help them set calorie and protein targets. Give them THREE choices in a clear, conversational message:

"Last thing — let's set your calorie and protein targets. You've got three ways to go:
1. <b>Calculate them for me</b> — I'll do the math based on your stats and goal
2. <b>I have numbers in mind</b> — just tell me what you want
3. <b>Skip for now</b> — we can dial them in once we see how you actually eat"

IF they pick option 1 (calculate): Use Mifflin-St Jeor BMR and follow this formula:
- BMR (male): 10*W_kg + 6.25*H_cm - 5*age + 5
- BMR (female): 10*W_kg + 6.25*H_cm - 5*age - 161
- TDEE = BMR × 1.55 (assume moderately active lifter)
- Cut goal: TDEE - 450 calories
- Maintain goal: TDEE
- Bulk goal: TDEE + 300 calories
- Performance/health goal: TDEE
- Protein: bodyweight_lbs × 0.9 grams (cut/maintain), × 0.8 (bulk)
Round calories to nearest 50, protein to nearest 5.
Show them the math briefly, then save with update_profile(calorie_target, protein_target).

IF they pick option 2 (specify): Save the numbers they give you.

IF they pick option 3 (skip): Don't set calorie_target or protein_target. Just call update_profile(onboarding_completed: true) and mention they can always say "set my targets" later.

COMPLETION: After targets are handled (calculated, specified, or skipped), call update_profile(onboarding_completed: true) in that same call. Then write a brief welcoming message — but DO NOT write a long usage tutorial; the system will send detailed instructions automatically after onboarding_completed flips to true."""


def build_onboarding_system(user: User) -> str:
    """Build a dynamic onboarding system prompt showing current state."""
    prefs = user.preferences

    def has(field):
        return getattr(user, field, None) is not None

    def pref_has(field):
        return prefs and getattr(prefs, field, None) is not None

    steps = [
        ("name",
         has("name"),
         "What's your first name?"),
        ("age & sex",
         has("age") and has("sex"),
         "How old are you, and male or female?"),
        ("height & weight",
         has("height_cm") and has("current_weight_kg"),
         "What's your height and current weight?"),
        ("goal",
         has("goal_weight_kg") and has("primary_goal"),
         "What's your goal weight, and are you cutting, bulking, or maintaining?"),
        ("training experience",
         has("training_experience"),
         "How experienced are you — beginner, intermediate, or advanced?"),
        ("diet & injuries",
         has("dietary_preferences") and has("injuries"),
         "Any dietary restrictions or injuries I should know about? (Say 'none' if not.)"),
        ("timezone",
         has("timezone") and user.timezone != "UTC",
         "What city are you in? (so I can time my check-ins right)"),
    ]

    collected_lines = []
    next_question = None

    for label, complete, question in steps:
        if complete:
            collected_lines.append(f"  ✓ {label}")
        elif next_question is None:
            next_question = question

    state_block = "\n\nONBOARDING STATE:"
    if collected_lines:
        state_block += "\nCollected: " + ", ".join(
            line.strip().lstrip("✓ ") for line in collected_lines
        )
    else:
        state_block += "\nNothing collected yet."

    if next_question:
        state_block += (
            f'\n\nNEXT QUESTION (ask this exactly, no deviations): "{next_question}"'
            "\nDo NOT skip ahead. Do NOT ask the targets question yet."
        )
    else:
        # All 7 essentials done — now handle targets
        if pref_has("calorie_target"):
            state_block += (
                "\n\nAll essentials AND targets are set."
                "\nCall update_profile(onboarding_completed: true) now and write a brief warm welcome."
                "\nDo NOT write a long tutorial — the system handles that automatically."
            )
        else:
            state_block += (
                "\n\nALL 7 ESSENTIALS DONE — Now run the TARGETS STEP."
                "\nFollow the TARGETS STEP instructions in the system prompt exactly."
                "\nOffer the user the 3 options (calculate / specify / skip)."
                "\nWhen they respond, handle accordingly AND call update_profile(onboarding_completed: true)."
            )

    return _ONBOARDING_BASE + state_block


def _both(a, b) -> str | None:
    if a is not None and b is not None:
        return f"{a} / {b}"
    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
