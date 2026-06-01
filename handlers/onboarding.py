"""
Onboarding flow — hybrid brain-dump model (fast path to first log).

The play: name → goal → one messy "brain dump" (voice note or paragraph) → Arnie
parses everything he can, reflects it back, asks AT MOST one missing critical thing
(weight), then pushes straight to the first log. Not a questionnaire.

COMPLETION needs only the three essentials: name, primary_goal, current_weight_kg.
tool_executor auto-flips onboarding_completed the moment those land (via
is_onboarding_complete). Everything else — height, age, sex, training, city, diet,
injuries, deadline, coaching style — is a BONUS: grabbed from the brain dump if
volunteered, otherwise picked up later (age/sex/height via the proactive
profile_stats follow-up loop; the rest surfaces organically). Never block on a bonus.
"""
from db.models import User
from core.prompts.onboarding import ONBOARDING_BASE as _ONBOARDING_BASE

# The only fields required to finish onboarding and start coaching. Kept minimal on
# purpose — the fastest path to the first log is the whole retention game.
_ESSENTIAL = ["name", "current_weight_kg", "primary_goal"]

# Bonus fields we happily extract from a brain dump but never gate completion on.
# Surfaced in the COLLECTED list so Arnie never re-asks something already given.
_BONUS = [
    ("goal weight",  "goal_weight_kg"),
    ("training",     "training_experience"),
    ("city",         "city"),
    ("height",       "height_cm"),
    ("age",          "age"),
    ("sex",          "sex"),
]


def onboarding_stage(user: User) -> str:
    """
    Derived onboarding stage (computed from field presence, not a stored column, so
    it can never desync from reality). Maps to the conceptual state machine:

      intro_started → name_collected → goal_collected → essentials_collected →
      onboarding_complete

    Out-of-order / all-in-one answers just jump straight ahead — whatever's present
    determines the stage. Used for observability + tests; the live flow is driven by
    build_onboarding_system below.
    """
    def has(f):
        return getattr(user, f, None) is not None

    if getattr(user, "onboarding_completed", False):
        return "onboarding_complete"
    if not has("name"):
        return "intro_started"
    if not has("primary_goal"):
        return "name_collected"
    if not has("current_weight_kg"):
        return "goal_collected"        # next move: brain dump / ask weight
    return "essentials_collected"      # has name+goal+weight; completion imminent


def build_onboarding_system(user: User) -> str:
    """
    Build a dynamic onboarding system prompt reflecting current saved state. Shows
    exactly what's already known (so Arnie never re-asks) and what essential is still
    missing, plus the brain-dump-aware next move. Bonus fields that were volunteered
    show up as COLLECTED but are never listed as "still needed".
    """
    def has(field):
        return getattr(user, field, None) is not None

    weight_val = (
        f"{user.current_weight_kg:.1f}kg"
        + (f" → {user.goal_weight_kg:.1f}kg" if user.goal_weight_kg else "")
        if user.current_weight_kg else ""
    )
    essentials = [
        ("name",         has("name"),              user.name or ""),
        ("primary goal", has("primary_goal"),      user.primary_goal or ""),
        ("weight",       has("current_weight_kg"), weight_val),
    ]
    still_needed = [label for label, done, _ in essentials if not done]

    collected_lines = [
        f"  • {label}: {val}" if val else f"  • {label}"
        for label, done, val in essentials if done
    ]
    # Surface any bonus fields already known so Arnie won't re-ask them.
    for label, field in _BONUS:
        if has(field):
            val = getattr(user, field)
            collected_lines.append(f"  • {label}: {val}")

    state_block = "\n\n━━━ ONBOARDING STATE ━━━"
    if collected_lines:
        state_block += "\nKNOWN ALREADY — never ask about these again:\n" + "\n".join(collected_lines)
    else:
        state_block += "\nNothing collected yet. Open warm and ask their name."

    if still_needed:
        state_block += f"\n\nSTILL NEEDED (essential): {', '.join(still_needed)}"
        if not has("name"):
            state_block += "\nNEXT MOVE: get their name."
        elif not has("primary_goal"):
            state_block += "\nNEXT MOVE: react to their name, ask what they're working toward."
        else:
            # name + goal known, weight missing → this is the brain-dump moment.
            state_block += (
                "\nNEXT MOVE: invite the brain dump (voice note or messy paragraph). "
                "Pull out everything they give and save it in ONE update_profile call. "
                "If they didn't give their current weight, ask ONLY that — it's the one "
                "essential left. Then push them to their first log. Do not ask for "
                "height, age, sex, training, or city — those are bonuses for later."
            )
    else:
        state_block += (
            "\n\nALL ESSENTIALS IN. Reflect back what you understood so they feel known, "
            "then DRIVE TO THE FIRST LOG. Do not ask anything else. No targets step."
        )

    return _ONBOARDING_BASE + state_block


def get_onboarding_keyboard(user: User):
    """
    Telegram ReplyKeyboardMarkup for the current step, or None. Mirrors the flow:
    name = free text, goal = quick-tap buttons, everything after (brain dump + weight)
    = free text / voice. Must stay in sync with build_onboarding_system's next move.
    """
    from telegram import ReplyKeyboardMarkup

    def has(field):
        return getattr(user, field, None) is not None

    if not has("name"):
        return None  # name — free text

    if not has("primary_goal"):
        return ReplyKeyboardMarkup(
            [["Lose Weight", "Gain Weight", "Maintain"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    # Brain dump + weight + first log — all free text / voice, no keyboard.
    return None


def is_onboarding_complete(user: User) -> bool:
    return all(getattr(user, f, None) for f in _ESSENTIAL)
