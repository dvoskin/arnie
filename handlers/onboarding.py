"""
Onboarding flow. Uses tool-based architecture — Arnie calls update_profile()
as it collects answers. The system prompt is built dynamically so Claude always
knows exactly what's been collected and what to ask next.
"""
from db.models import User

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie, a direct, no-BS fitness and nutrition coach onboarding a new user.

Your job right now: collect their profile naturally, one topic at a time, in conversation.

RULES:
- Be warm and brief — 1-2 sentences of acknowledgement, then the next question.
- ALWAYS end your message with the next question. Never end without one.
- Save each answer immediately using update_profile() with exact field names.
- Exact field names: name, age, sex (male/female), height_cm, current_weight_kg,
  goal_weight_kg, primary_goal (cut/bulk/maintain/performance/health),
  training_experience (beginner/intermediate/advanced), dietary_preferences,
  injuries, timezone, coaching_style, accountability_level, wake_time, sleep_time.
- Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
- When all essential fields are collected, add onboarding_completed: true in the
  same update_profile() call.
- ALWAYS write a text response alongside any tool call."""


def build_onboarding_system(user: User) -> str:
    """Build a dynamic onboarding system prompt showing current state."""
    prefs = user.preferences

    # Map fields to (label, current_value, question_to_ask)
    steps = [
        ("name",              user.name,                       "What's your first name?"),
        ("age + sex",         _both(user.age, user.sex),       "How old are you, and are you male or female?"),
        ("height + weight",   _both(user.height_cm, user.current_weight_kg),
                                                               "What's your height and current weight?"),
        ("goal weight + goal",_both(user.goal_weight_kg, user.primary_goal),
                                                               "What's your goal weight, and are you cutting, bulking, maintaining, focusing on performance, or general health?"),
        ("training experience", user.training_experience,      "How would you describe your training experience — beginner, intermediate, or advanced?"),
        ("dietary preferences", user.dietary_preferences,      "Any dietary restrictions or preferences I should know about?"),
        ("injuries",          user.injuries,                   "Any injuries or physical limitations?"),
        ("coaching style",    prefs.coaching_style if prefs else None,
                                                               "How do you like to be coached — strict and to-the-point, balanced, or more supportive?"),
        ("accountability",    prefs.accountability_level if prefs else None,
                                                               "What level of accountability do you want from me — low, medium, or high?"),
        ("timezone",          user.timezone,                   "What city are you in, or what's your timezone?"),
        ("wake + sleep time", _both(prefs.wake_time if prefs else None,
                                   prefs.sleep_time if prefs else None),
                                                               "What time do you usually wake up and go to sleep?"),
    ]

    collected_lines = []
    next_question = None

    for label, value, question in steps:
        if value:
            collected_lines.append(f"  ✓ {label}: {value}")
        elif next_question is None:
            next_question = question

    state_block = "\n\nONBOARDING STATE:"
    if collected_lines:
        state_block += "\nCollected so far:\n" + "\n".join(collected_lines)
    else:
        state_block += "\nNothing collected yet."

    if next_question:
        state_block += f"\n\nNEXT REQUIRED QUESTION: \"{next_question}\"\nYou MUST ask this question in your response. Do not skip it or ask something else."
    else:
        state_block += "\n\nAll fields collected. Call update_profile() with onboarding_completed: true."

    return _ONBOARDING_BASE + state_block


def _both(a, b) -> str | None:
    """Return a combined value string only if both fields are set."""
    if a is not None and b is not None:
        return f"{a} / {b}"
    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
