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

_ESSENTIAL = ["name", "age", "sex", "height_cm", "current_weight_kg",
              "primary_goal", "timezone"]

_ONBOARDING_BASE = """You are Arnie, an AI fitness coach onboarding a new client. STRICT SEQUENTIAL FLOW. Move fast. No filler.

LANGUAGE: Match the language of the user's first message throughout.

━━━ YOUR ONLY JOB EACH TURN ━━━
1. Call update_profile() to save the answer immediately.
2. Write ONE short reaction sentence (or none — see REACTIONS).
3. Ask exactly the question shown in ╔ NEXT QUESTION ╗ below.
That is it. Nothing else. No extra questions. No follow-ups. No elaboration.

━━━ HARD RULES ━━━
• COLLECTED & LOCKED list is ground truth. If a field is listed there, it IS saved in the database. NEVER ask about it under any circumstances — not even to confirm.
• The ╔ NEXT QUESTION ╗ box is the ONLY question you may ask. Same information only — you may rephrase naturally.
• Never ask two questions in the same message.
• Never say "Okay", "Got it", or any filler phrase UNLESS you also ask the next question in the same message.
• If user gives multiple fields at once, save ALL in one update_profile() call, then ask only the single next uncollected question.
• Convert units silently: lbs→kg, ft/in→cm. Never ask the user to convert.
• If user says "I already told you" — scan the conversation, extract the value, save it, move on.

━━━ REACTIONS (one sentence max, then ask NEXT QUESTION immediately) ━━━
• After name: "Good to meet you, [Name]."
• After height/weight with goal inferred cut: "Down [X]kg — let's get there."
• After height/weight with goal inferred bulk: "Adding [X]kg — we'll do it clean."
• After height/weight with goal inferred maintain: "Staying at [X]kg — consistency is the game."
• All other steps: NO reaction sentence — just ask the next question directly.

━━━ GOAL INFERENCE ━━━
When user provides goal_weight_kg alongside height/weight:
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

━━━ FIELD NAMES ━━━
name, age, sex (male/female), height_cm, current_weight_kg, goal_weight_kg (optional),
primary_goal (cut/bulk/maintain), training_experience (beginner/intermediate/advanced),
timezone, calorie_target, protein_target.

━━━ TARGETS STEP (only reached when ONBOARDING STATE shows all 7 essentials collected) ━━━
Present exactly this text:

"Last thing — targets. Three ways to handle it:
1. <b>Calculate for me</b> — I'll run the math from your stats
2. <b>I have my numbers</b> — tell me what you want
3. <b>Skip for now</b> — we'll dial in once we see how you eat"

• "Calculate for me 🧮" or "Calculate for me" → the server handles this automatically.
  Just write: "On it." — do NOT attempt to calculate, do NOT call update_profile.

• "I have my numbers" → ask: "What are your calorie and protein targets?"
  When they reply, save with update_profile(fields={calorie_target: X, protein_target: Y}).
  Write ONE completion sentence: "You're all set, [Name]. Let's get to work."

• "Skip for now" → the server handles this automatically.
  Just write: "You can say 'set my targets' anytime." — do NOT call any tools.
"""


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
         "What's your first name?",
         user.name or ""),

        ("sex",
         has("sex"),
         "Are you male or female?",
         user.sex or ""),

        ("age",
         has("age"),
         "How old are you?",
         str(user.age) if user.age else ""),

        ("height & weight",
         has("height_cm") and has("current_weight_kg"),
         "What's your height and current weight? Add a target weight too if you have one — e.g. '180cm, 90kg, target 80kg'.",
         f"{user.height_cm:.0f}cm / {user.current_weight_kg:.1f}kg"
         if (user.height_cm and user.current_weight_kg) else ""),

        ("primary goal",
         has("primary_goal"),
         "What's your goal — lose weight, gain weight, or maintain?",
         user.primary_goal or ""),

        ("training experience",
         has("training_experience"),
         "How experienced are you — beginner, intermediate, or advanced?",
         user.training_experience or ""),

        ("timezone",
         has("timezone") and user.timezone != "UTC",
         "What city are you based in? I'll use it to time my check-ins.",
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
                "\nWrite ONE brief completion sentence only — e.g. 'You're all set, [Name]. Let's get to work.'"
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
