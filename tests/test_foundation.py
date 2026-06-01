"""
Foundation-stabilization regression tests.

These lock in the behavioral guarantees from the foundation pass WITHOUT needing a
live LLM (they assert on the prompt that gets built, the active-skill set, and the
deterministic fallbacks). They are the safety net for the larger refactor phases.
"""
import re
from types import SimpleNamespace

from core.prompts.arnie import build_arnie_system
from skills import load_all_skills
from handlers.tool_executor import deterministic_confirmation


# ── Skill isolation: only the 4 foundational skills are active ──────────────────

_ACTIVE_EXPECTED = {"DAILY CLOSEOUT", "FOOD SEARCH", "MEAL SUGGESTIONS", "WORKOUT BUILDER"}
_DISABLED = [
    "CARDIO", "HIIT", "YOGA", "RESTAURANT", "TRAVEL", "WEEKLY SUMMARY",
    "PROGRESS", "STRENGTH", "RECOVERY", "FLEXIBILITY", "SPORT", "GROCERY",
    "AGGRESSIVE", "WEIGH",
]


def test_only_foundational_skills_active():
    block = load_all_skills()
    active = {n.strip() for n in re.findall(r"▸ ([A-Z &]+?)\s+triggers:", block)}
    assert active == _ACTIVE_EXPECTED, f"unexpected active skills: {active}"


def test_disabled_skills_do_not_leak_into_prompt():
    block = load_all_skills()
    for dead in _DISABLED:
        assert dead not in block, f"disabled skill leaked into prompt: {dead}"


def test_skill_block_is_lean():
    # Pre-pass the block was ~14k chars (all 18 skills). After disabling 14 it should
    # be well under 4k. Guards against silently re-enabling skills.
    assert len(load_all_skills()) < 4000


# ── Behavior layer: the single source of truth carries the key rules ────────────

def test_prompt_has_coaching_philosophy():
    """The belief system must be encoded in the behavior layer so it silently shapes
    every reply — consistency-over-perfection, momentum, friction, next-action, etc."""
    s = build_arnie_system("imessage")
    for marker in (
        "Consistency beats intensity",   # belief 1
        "Momentum is fragile",           # belief 2
        "keystone habit",                # belief 3 (logging)
        "next action beats the perfect", # belief 4
        "Personalize over generic",      # belief 5
        "Coach, don't track",            # belief 6
        "Accountability direct, never shame",  # belief 7
        "Small wins compound",           # belief 8
        "PRIORITY ORDER",                # priority ladder
        "BEFORE YOU SEND",               # decision filter
    ):
        assert marker in s, f"coaching-philosophy marker missing: {marker!r}"


def test_philosophy_is_a_silent_shaper_not_a_manifesto():
    """It must instruct Arnie NOT to recite the beliefs at the user."""
    s = build_arnie_system("imessage")
    assert "never recite" in s.lower()


def test_priority_order_demotes_advanced_optimization():
    """Basics before optimization must be explicit (don't lecture nutrient timing /
    supplements / periodization when the user isn't even logging)."""
    s = build_arnie_system("imessage").lower()
    assert "nutrient timing" in s and "periodization" in s


def test_prompt_has_number_safety_rule():
    s = build_arnie_system("imessage")
    assert "NUMBERS ARE SACRED" in s


def test_prompt_has_anti_repetition_rule():
    s = build_arnie_system("imessage")
    assert "DON'T REPEAT YOURSELF" in s


def test_prompt_allows_conversational_replies_without_tools():
    s = build_arnie_system("imessage")
    assert "NOT EVERY MESSAGE NEEDS A TOOL" in s


def test_prompt_has_global_multibubble_cadence():
    """1 / 2 / 3-4 bubble guidance must be present and apply to everything, not
    just food logs — this is what makes the whole product feel like texting."""
    s = build_arnie_system("imessage")
    assert "1 bubble" in s and "2 bubbles" in s and "3-4 bubbles" in s
    assert "|||" in s  # the bubble separator is documented


def test_prompt_has_multi_item_logging_rule():
    """A list of foods must be logged all-at-once. Guards the 7-item-dump regression."""
    s = build_arnie_system("imessage").lower()
    assert "multi-item" in s
    assert "one log_food() call" in s or "one log_food call" in s
    # must forbid logging just the first and deferring the rest
    assert "first" in s and ("there is no later" in s or "do it all now" in s)


def test_prompt_forbids_intent_narration():
    """Arnie must DO actions, not narrate 'let me also get X' across dead turns."""
    s = build_arnie_system("imessage")
    assert "DON'T NARRATE" in s or "don't narrate" in s.lower()
    assert "let me" in s.lower()  # the banned phrasing is named explicitly


def test_prompt_has_resilience_section():
    """Arnie must stay on task under hostile / messy / chaotic input."""
    s = build_arnie_system("imessage")
    assert "STAYING ON TASK" in s
    for marker in ("profanity", "loop", "rattled"):
        assert marker in s.lower(), f"resilience marker missing: {marker}"


def test_prompt_estimates_on_request_without_reasking():
    """'guestimate'/'estimate' must trigger an immediate estimate, never a re-ask."""
    s = build_arnie_system("imessage").lower()
    assert "guestimate" in s
    assert "do not ask" in s or "without asking" in s


_SIGNATURE_EMOJIS = ["☺️", "🎊", "🩻", "✅", "📊", "💪", "🍽️", "🏋️‍♂️", "💧", "🧠"]


def test_emoji_signature_set_present():
    """The 10-emoji signature set must be documented in the prompt."""
    s = build_arnie_system("imessage")
    assert "SIGNATURE SET" in s
    for e in _SIGNATURE_EMOJIS:
        assert e in s, f"signature emoji missing from prompt: {e}"


def test_emoji_five_categories_present():
    """All five emoji categories must be documented so each maps to the right moment."""
    s = build_arnie_system("imessage")
    for cat in ("WARM / FRIENDLY", "CELEBRATION / MOMENTUM",
                "SCIENCE / BODY / CLINICAL", "FOOD / NUTRITION", "TRAINING / RECOVERY"):
        assert cat in s, f"emoji category missing: {cat}"


def test_emoji_density_rule_present():
    """The 0-2-max, not-decorative rule must be explicit — this is what keeps Arnie legit."""
    s = build_arnie_system("imessage")
    assert "0-2" in s
    assert "marketing copy" in s  # "like a real coach texting, not marketing copy"


def test_emoji_no_contradictory_legacy_guidance():
    """
    REGRESSION GUARD: the old VOICE block said 'never 📊 📈 🎯 ✅ 💡', which directly
    contradicted the new system (📊 = summaries, ✅ = confirmations). That guidance
    must be gone or the model gets conflicting instructions.
    """
    s = build_arnie_system("imessage")
    assert "never 📊" not in s
    assert "📈 🎯 ✅" not in s


def test_emoji_category_anchors_in_rules():
    """Key category-to-emoji mappings the user specified must be spelled out."""
    s = build_arnie_system("imessage")
    # 🩻 for the deeper analytical read, 📊 for summaries/trends, 🧠 for behavior
    assert "🩻" in s and "📊" in s and "🧠" in s
    # celebration mapping: 🎊 wins, ✅ confirmations
    assert "🎊" in s and "✅" in s


def test_prompt_bans_ai_self_reference():
    """Arnie must never call itself an AI / model / software."""
    s = build_arnie_system("imessage")
    for banned in ("as an AI", "I'm your AI coach", "artificial intelligence",
                   "my model", "language model"):
        assert banned in s, f"AI-ban list missing phrase: {banned!r}"


def test_onboarding_each_stage_has_explicit_do_nots():
    """Every stage prompt must have DO NOT instructions — escape hatches get caught here."""
    from types import SimpleNamespace
    from handlers.onboarding import build_onboarding_system
    def _u(**kw):
        base = dict(name=None, primary_goal=None, current_weight_kg=None,
                    goal_weight_kg=None, training_experience=None, city=None,
                    height_cm=None, age=None, sex=None, onboarding_completed=False)
        base.update(kw)
        return SimpleNamespace(**base)
    for label, user in [
        ("get_name",   _u()),
        ("dump_pending_no_goal", _u(name="X")),
        ("dump_pending_no_weight", _u(name="X", primary_goal="cut")),
    ]:
        prompt = build_onboarding_system(user)
        assert "DO NOT" in prompt, f"Stage {label!r} missing DO NOT guardrails"
        assert "|||" in prompt, f"Stage {label!r} missing bubble separator example"


def test_onboarding_dump_stage_no_skip_path():
    """
    REGRESSION GUARD: old ONBOARDING_BASE had 'ADAPT TO THEIR ENERGY' with a skip path
    that let the LLM jump straight to food logging. Must not exist in any stage prompt.
    """
    from types import SimpleNamespace
    from handlers.onboarding import build_onboarding_system
    u = SimpleNamespace(name="X", primary_goal=None, current_weight_kg=None,
                        goal_weight_kg=None, training_experience=None, city=None,
                        height_cm=None, age=None, sex=None, onboarding_completed=False)
    prompt = build_onboarding_system(u)
    assert "ADAPT TO THEIR ENERGY" not in prompt
    assert "skip setup" not in prompt.lower()
    assert "just let me log" not in prompt.lower()


def test_onboarding_dump_stage_forbids_direct_weight_ask():
    """
    REGRESSION GUARD: LLM was skipping brain dump and asking weight directly.
    The dump_pending stage must explicitly forbid this.
    """
    from types import SimpleNamespace
    from handlers.onboarding import build_onboarding_system
    u = SimpleNamespace(name="X", primary_goal="cut", current_weight_kg=None,
                        goal_weight_kg=None, training_experience=None, city=None,
                        height_cm=None, age=None, sex=None, onboarding_completed=False)
    prompt = build_onboarding_system(u)
    assert "Do NOT ask for weight directly" in prompt or \
           "do not ask for weight" in prompt.lower(), \
        "dump_pending stage must forbid direct weight ask"


def test_onboarding_complete_stage_drives_to_first_log():
    """Complete stage must push to first log, not ask more questions."""
    from types import SimpleNamespace
    from handlers.onboarding import build_onboarding_system
    u = SimpleNamespace(name="X", primary_goal="cut", current_weight_kg=86.0,
                        goal_weight_kg=None, training_experience=None, city=None,
                        height_cm=None, age=None, sex=None, onboarding_completed=False)
    prompt = build_onboarding_system(u)
    assert "first log" in prompt.lower() or "ate today" in prompt.lower()
    assert "DO NOT ask any more setup" in prompt or "no more setup" in prompt.lower()


def test_prompt_is_sentence_case_not_forced_lowercase():
    s = build_arnie_system("imessage")
    # the only "lowercase" mention should be the "not all-lowercase" guidance
    assert "lowercase. always" not in s
    assert "Sentence case" in s or "sentence case" in s


def test_prompt_builds_for_both_platforms():
    for platform in ("imessage", "telegram", "web"):
        s = build_arnie_system(platform)
        assert len(s) > 5000


# ── Deterministic fallback stays sentence-case + authoritative ──────────────────

def _prefs(cal_t=1800, pro_t=200):
    return SimpleNamespace(calorie_target=cal_t, protein_target=pro_t)


def _log(cal=0, pro=0):
    return SimpleNamespace(total_calories=cal, total_protein=pro)


def test_fallback_confirmation_is_sentence_case():
    tc = [{"name": "log_food", "input": {"food_name": "royo bagel"}}]
    out = deterministic_confirmation(tc, _log(160, 6), _prefs())
    first = out.split("|||")[0].strip()
    assert first[:1].isupper(), f"fallback not sentence-case: {first!r}"


def test_fallback_uses_authoritative_totals():
    tc = [{"name": "log_food", "input": {"food_name": "eggs"}}]
    out = deterministic_confirmation(tc, _log(435, 60), _prefs())
    assert "435" in out and "1800" in out
    # must never echo the historical hallucinated numbers
    assert "1,601" not in out and "192g" not in out
