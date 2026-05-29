"""
Onboarding flow — strictly sequential, server-managed completion.

Step order: name → sex → age → height/weight (+goal weight) → goal (skipped if
inferred from weights) → experience → timezone → targets

COMPLETION MODEL (not LLM-driven):
  • "Calculate for me" and "Skip for now" are intercepted server-side in
    telegram_handler before the LLM is called.
  • "I have my numbers": LLM parses the reply and calls
    update_profile(calorie_target=X, protein_target=Y). tool_executor.py
    then auto-flips onboarding_completed when all essentials + calorie_target
    are present.
  • The LLM must NEVER call update_profile(onboarding_completed=true). That
    requirement is removed — the follow-up LLM call cannot use tools, so
    relying on it caused the "Got it." dead-end.

Diet/injuries NOT collected during onboarding.
"""
from db.models import User
from core.prompts.onboarding import ONBOARDING_BASE as _ONBOARDING_BASE

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]


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

    # (label, is_complete, next_question, display_value)
    steps = [
        ("name",
         has("name"),
         "what's your first name?",
         user.name or ""),

        ("sex",
         has("sex"),
         "male or female?",
         user.sex or ""),

        ("age",
         has("age"),
         "how old are you?",
         str(user.age) if user.age else ""),

        ("height & weight",
         has("height_cm") and has("current_weight_kg"),
         "height and weight? throw in a target weight too if you have one.",
         f"{user.height_cm:.0f}cm / {user.current_weight_kg:.1f}kg"
         if (user.height_cm and user.current_weight_kg) else ""),

        ("primary goal",
         has("primary_goal"),
         "what's the goal — lose weight, gain, or maintain?",
         user.primary_goal or ""),

        ("training experience",
         has("training_experience"),
         "how experienced are you — beginner, intermediate, or advanced?",
         user.training_experience or ""),

        ("timezone",
         has("timezone") and user.timezone != "UTC",
         "what city are you in? i'll use it to time my check-ins.",
         user.timezone or ""),
    ]

    collected_lines = []
    next_question = None

    for label, complete, question, display in steps:
        if complete:
            val = f": {display}" if display else ""
            collected_lines.append(f"  • {label}{val}")
        elif next_question is None:
            next_question = question

    # ── State block ──
    state_block = "\n\n━━━ ONBOARDING STATE ━━━"

    if collected_lines:
        state_block += "\nCOLLECTED & LOCKED — do NOT ask about any of these:\n"
        state_block += "\n".join(collected_lines)
    else:
        state_block += "\nNothing collected yet."

    if next_question:
        state_block += (
            f"\n\n╔═ NEXT QUESTION — ask this and only this ═╗"
            f'\n  "{next_question}"'
            f"\n╚══════════════════════════════════════════╝"
            f"\nAsk it now. Do not ask anything else first."
        )
    else:
        if pref_has("calorie_target"):
            state_block += (
                "\n\nAll essentials AND targets are set."
                "\nWrite ONE brief completion — e.g. \"you're all set, [name]. let's get to work.\""
                "\nDo NOT call any tools. Do NOT ask anything."
            )
        else:
            state_block += (
                "\n\nALL 7 ESSENTIALS COLLECTED. Run the TARGETS STEP now."
                "\nPresent the 3 options exactly as written in the TARGETS STEP section above."
                "\nWait for the user's selection, then follow the instruction for whichever option they choose."
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

    # Step 7: timezone — free text
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
