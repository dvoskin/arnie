"""
core/prompts — all Arnie prompt content lives here.

Public API:
    build_arnie_system(platform)   → full coaching system prompt
    build_onboarding_system(user)  → dynamic onboarding prompt
    NUDGE_SYSTEM                   → proactive scheduler base prompt
    NUDGE_SLOT_INSTRUCTIONS        → per-slot nudge instructions
    NEW_USER_SYSTEM                → new-user engagement base prompt
    NEW_USER_SLOT_INSTRUCTIONS     → per-slot new-user instructions
"""

from core.prompts.arnie import build_arnie_system
from core.prompts.onboarding import ONBOARDING_BASE
from core.prompts.nudges import (
    NUDGE_SYSTEM,
    NUDGE_SLOT_INSTRUCTIONS,
    NEW_USER_SYSTEM,
    NEW_USER_SLOT_INSTRUCTIONS,
)

__all__ = [
    "build_arnie_system",
    "ONBOARDING_BASE",
    "NUDGE_SYSTEM",
    "NUDGE_SLOT_INSTRUCTIONS",
    "NEW_USER_SYSTEM",
    "NEW_USER_SLOT_INSTRUCTIONS",
]
