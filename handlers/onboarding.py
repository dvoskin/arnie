"""
Onboarding flow — minimal & conversational.

Collects ONLY: name → fitness goal → current/goal weight. That's enough to start.
age, sex, and height are collected AFTER onboarding via proactive nudges
(scheduler._llm_profile_nudge). Once those three land, tool_executor auto-computes
calorie + protein targets via core.targets.calc_targets.

COMPLETION: tool_executor auto-flips onboarding_completed the moment the three
essentials (name, current_weight_kg, primary_goal) are saved. No targets step.

Diet/injuries/experience NOT collected during onboarding — they surface organically.
"""
from db.models import User
from core.prompts.onboarding import ONBOARDING_BASE as _ONBOARDING_BASE

# Minimal onboarding — just enough to start coaching. age/sex/height are
# collected post-onboarding via proactive nudges (see scheduler), which then
# auto-computes targets once all three land.
_ESSENTIAL = ["name", "current_weight_kg", "primary_goal", "training_experience", "city"]


def build_onboarding_system(user: User) -> str:
    """
    Build a dynamic onboarding system prompt reflecting current saved state.
    Shows actual saved values in the COLLECTED list so the LLM has no doubt
    about what is already done. Injects the exact NEXT QUESTION so the LLM
    cannot skip, re-ask, or deviate.
    """
    prefs = user.preferences

    def has(field):
        return getattr(user, field, None) is not None

    def pref_has(field):
        return prefs and getattr(prefs, field, None) is not None

    # Only the minimal essentials are tracked. age/sex/height come later via proactive.
    weight_val = (
        f"{user.current_weight_kg:.1f}kg"
        + (f" → {user.goal_weight_kg:.1f}kg" if user.goal_weight_kg else "")
        if user.current_weight_kg else ""
    )
    fields = [
        ("name",         has("name"),               user.name or ""),
        ("primary goal", has("primary_goal"),       user.primary_goal or ""),
        ("weight",       has("current_weight_kg"),  weight_val),
        ("training",     has("training_experience"), user.training_experience or ""),
        ("city",         has("city"),                user.city or ""),
    ]

    still_needed = [label for label, done, _ in fields if not done]
    collected_lines = [
        f"  • {label}: {val}" if val else f"  • {label}"
        for label, done, val in fields if done
    ]

    state_block = "\n\n━━━ ONBOARDING STATE ━━━"

    if collected_lines:
        state_block += "\nCOLLECTED & LOCKED — never ask about these:\n" + "\n".join(collected_lines)
    else:
        state_block += "\nNothing collected yet. Start by asking their name."

    if still_needed:
        state_block += f"\n\nSTILL NEEDED: {', '.join(still_needed)}"
        state_block += (
            "\n\nCollect these naturally — name, then goal, then weight, then training, then city. React as you go."
            "\nDo NOT ask for age, sex, or height. Those come later."
        )
    else:
        state_block += (
            "\n\nALL ESSENTIALS COLLECTED. Wrap up warmly and tell them to start logging."
            "\nDo NOT ask anything else. Do NOT present a targets step."
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

    # Name first — free text, no keyboard
    if not has("name"):
        return None

    # Goal — quick-tap buttons (the one place buttons genuinely speed things up)
    if not has("primary_goal"):
        return ReplyKeyboardMarkup(
            [["Lose Weight", "Gain Weight", "Maintain"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Weight — free text. Everything else (age/sex/height) is collected later.
    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
