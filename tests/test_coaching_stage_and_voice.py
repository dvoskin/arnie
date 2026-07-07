"""Pins for the 2026-07-06 coaching-quality pass (Danny's direction):

1. GOAL WORDS — 'cut'/'bulk' are internal labels; the user hears "losing
   weight" / "putting on size". Pinned across chat, nudges, and briefing.
2. Program nudge — users training regularly with no program get a coach note
   offering to build one, at their pace.
3. Muscle-emphasis accuracy — the cable-fly direction table (low-to-high =
   UPPER chest; it was said backwards in prod) + the coach-effort-not-anatomy
   fallback when unsure.
4. Stage ladder — meet users at their stage; most arrive with no program.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from core.context_builder import _recent_training_days
from core.prompts.arnie import build_arnie_system
from core.prompts.nudges import NUDGE_SYSTEM, NEW_USER_SYSTEM


def _s():
    return build_arnie_system("telegram")


# ── 1. plain-language goals ──────────────────────────────────────────────────

def test_chat_prompt_bans_cut_bulk_jargon():
    s = _s()
    assert 'the data says "cut" and "bulk"; you never do' in s
    assert "putting on size" in s and "losing weight" in s


def test_nudge_and_new_user_systems_ban_jargon():
    for sysprompt in (NUDGE_SYSTEM, NEW_USER_SYSTEM):
        assert "never use those words" in sysprompt
        assert "putting on size" in sysprompt


def test_briefing_system_bans_jargon():
    from scheduler.proactive_scheduler import _BRIEFING_SYSTEM
    assert "never use those words" in _BRIEFING_SYSTEM


# ── 2. program nudge ─────────────────────────────────────────────────────────

def _log(d, sources):
    return SimpleNamespace(
        date=d,
        exercise_entries=[SimpleNamespace(source_type=s) for s in sources],
    )


def test_recent_training_days_counts_real_workouts_only():
    today = date.today()
    logs = [
        _log(today - timedelta(days=1), ["ios"]),
        _log(today - timedelta(days=3), ["whoop"]),          # wearable-only: no
        _log(today - timedelta(days=5), ["whoop", "ios"]),   # mixed: yes
        _log(today - timedelta(days=8), ["text"]),
        _log(today - timedelta(days=20), ["ios"]),           # outside window
    ]
    assert _recent_training_days(logs, days=14) == 3


def test_philosophy_carries_stage_ladder():
    s = _s()
    assert "Meet them at their stage" in s
    assert "log anything → log consistently" in s
    assert "no_program" in s  # the coach-note name is referenced


# ── 3. muscle-emphasis accuracy ──────────────────────────────────────────────

def test_cable_fly_directions_are_correct_in_prompt():
    s = _s()
    assert "high-to-low cable fly (pull downward)  → LOWER chest" in s
    assert "low-to-high cable fly (pull upward)    → UPPER chest" in s


def test_unsure_anatomy_falls_back_to_form_coaching():
    s = _s()
    assert "coach effort, form, or progression instead of anatomy" in s
