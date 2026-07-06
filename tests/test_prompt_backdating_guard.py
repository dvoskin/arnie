"""Prompt pin: an open backfill thread must not make new food mentions
retroactive.

Prod regression (Gi, 2026-07-06): the night before, he described a bender and
Arnie had an unanswered question about yesterday's tacos. His 9:39 AM "Had an
egg bagel..." — no day reference — got logged with date="yesterday" onto
Sunday's log. The tool contract already says date= only on an explicit past-day
mention, but conversational pull overrode it; this rule closes that gap."""
from core.prompts.arnie import build_arnie_system


def test_prompt_requires_current_message_day_reference():
    s = build_arnie_system("telegram")
    assert "past-day reference must be in the user's CURRENT message" in s


def test_prompt_names_the_backfill_thread_trap():
    s = build_arnie_system("telegram")
    assert "does NOT make a new food mention retroactive" in s
    assert "mid-backfill-conversation" in s
