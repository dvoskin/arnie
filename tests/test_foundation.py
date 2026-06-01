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

def test_prompt_has_number_safety_rule():
    s = build_arnie_system("imessage")
    assert "NUMBERS ARE SACRED" in s


def test_prompt_has_anti_repetition_rule():
    s = build_arnie_system("imessage")
    assert "DON'T REPEAT YOURSELF" in s


def test_prompt_allows_conversational_replies_without_tools():
    s = build_arnie_system("imessage")
    assert "NOT EVERY MESSAGE NEEDS A TOOL" in s


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
