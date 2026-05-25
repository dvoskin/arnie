"""
Onboarding flow. Uses tool-based architecture — Arnie calls update_profile()
as it collects answers. The system prompt is built dynamically so Claude always
knows exactly what's been collected and what to ask next.

Streamlined to 7 steps (feels like 5 conversations). Coaching style,
accountability, and wake/sleep are set to sensible defaults and can be
changed later — they should NOT block onboarding.
"""
from db.models import User

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie, a direct no-BS fitness coach onboarding a new user.

Collect their profile naturally and quickly — like a coach asking intake questions, not a form.

RULES:
- Be warm and brief. 1 sentence of acknowledgement max, then the next question.
- ALWAYS end your message with the next question. Never leave the user hanging.
- Accept answers naturally — if they give you multiple pieces of info at once, save all of it.
- Save each answer immediately using update_profile() with exact field names.
- Field names: name, age, sex (male/female), height_cm, current_weight_kg,
  goal_weight_kg, primary_goal (cut/bulk/maintain/performance/health),
  training_experience (beginner/intermediate/advanced), dietary_preferences,
  injuries, timezone.
- Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
- If user says "no restrictions" or "no injuries", save that as the value, don't skip.
- When all fields are collected, call update_profile() with onboarding_completed: true.
- ALWAYS write a text response alongside any tool call.
- Keep responses SHORT — this is a quick setup, not a consultation."""


def build_onboarding_system(user: User) -> str:
    """Build a dynamic onboarding system prompt showing current state."""
    prefs = user.preferences

    # Each step: (label, is_complete, question_to_ask)
    # Checking fields independently (not requiring both to be set for combined steps)
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
         "Last one — what city are you in? (so I get your time right)"),
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
            "\nDo NOT ask anything else. Do NOT skip this question."
        )
    else:
        state_block += (
            "\n\nAll fields collected."
            "\nCall update_profile() with onboarding_completed: true."
            "\nDo NOT ask any more questions."
        )

    return _ONBOARDING_BASE + state_block


def _both(a, b) -> str | None:
    """Return a combined value string only if both fields are set."""
    if a is not None and b is not None:
        return f"{a} / {b}"
    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
