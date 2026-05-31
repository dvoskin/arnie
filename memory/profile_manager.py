"""
Adaptive per-user profile system — the "User Profile Matrix."

A living, structured markdown file at users/{telegram_id}/profile.md that Arnie
reads BEFORE coaching and updates AFTER meaningful interactions. It accumulates
durable understanding of each user so coaching gets progressively personalized.

Design principles:
  - Per-user, never global.
  - Atomic, traceable writes (temp file + os.replace, plus a changelog section).
  - Stable facts separated from temporary context.
  - Confidence tags: [confirmed] [inferred] [outdated] [needs verification].
  - Each section carries a "Last updated" date; a Change Log tracks evolution.
  - Updates preserve existing context — they refine, they don't wipe.
  - Throttled (won't rewrite more than once every few hours) to control cost.

This supersedes the older freeform arnie_memory.md as the primary long-term
context. memory_manager remains for backward-compatible reset/clear.
"""
import os
import re
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import aiofiles

from db.models import User

logger = logging.getLogger(__name__)

# Persistent per-user dir (survives deploys) — shared resolver with memory_manager.
from memory.memory_manager import USERS_DIR  # noqa: E402

# Don't rewrite the profile more often than this (cost control).
_MIN_UPDATE_INTERVAL = timedelta(hours=3)


def profile_path(telegram_id: str) -> Path:
    d = USERS_DIR / str(telegram_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "profile.md"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────────
# Template — the schema Arnie maintains
# ─────────────────────────────────────────────────────────────────────────────

def build_template(user: User) -> str:
    """Seed a fresh profile from known DB facts. Demographics start confirmed."""
    prefs = user.preferences
    name = user.name or "User"
    coaching = getattr(prefs, "coaching_style", "balanced") if prefs else "balanced"
    accountability = getattr(prefs, "accountability_level", "medium") if prefs else "medium"
    length = getattr(prefs, "preferred_response_length", "medium") if prefs else "medium"

    def line(label, val, conf="confirmed"):
        return f"- {label}: {val}  `[{conf}]`" if val not in (None, "", "Not set") else f"- {label}: unknown  `[needs verification]`"

    today = _today()
    return f"""<!-- last_synced: {_now_iso()} -->
# User Profile Matrix — {name}

> How to read this: each fact is tagged `[confirmed]` (user stated it),
> `[inferred]` (Arnie deduced it from behavior), `[outdated]` (superseded, kept
> for history), or `[needs verification]` (assumed, should confirm). STABLE facts
> live in their sections; TEMPORARY context (a single bad day, a one-off craving)
> does NOT get written here unless it becomes a recurring pattern.

## Demographics
_Last updated: {today}_
{line("Name", user.name)}
{line("Age", user.age)}
{line("Sex", user.sex)}
{line("Height (cm)", round(user.height_cm) if user.height_cm else None)}
{line("Current weight (kg)", round(user.current_weight_kg, 1) if user.current_weight_kg else None)}
{line("Goal weight (kg)", round(user.goal_weight_kg, 1) if user.goal_weight_kg else None)}
- Location / timezone: {user.timezone or "unknown"}  `[{'confirmed' if (user.timezone and user.timezone != 'UTC') else 'needs verification'}]`
- Lifestyle notes: (none yet)

## Goals & Aspirations
_Last updated: {today}_
{line("Primary goal", user.primary_goal)}
- Deeper why / motivation: (unknown)  `[needs verification]`
- Secondary goals: (none yet)

## Nutrition Preferences
_Last updated: {today}_
- Diet style: {user.dietary_preferences or "no restrictions stated"}  `[{'confirmed' if user.dietary_preferences else 'needs verification'}]`
- Favorite foods: (learning)
- Commonly eaten: (learning)
- Foods avoided: (learning)
- Typical meal timing: (learning)
- Protein habits: (learning)
- Snack patterns: (learning)
- Alcohol / sugar habits: (learning)

## Fitness Profile
_Last updated: {today}_
- Training experience: {user.training_experience or "unknown"}  `[{'confirmed' if user.training_experience else 'needs verification'}]`
- Sport: {user.sport or "none stated"}
- Workout split: (learning)
- Preferred exercises: (learning)
- Injuries / limitations: {user.injuries or "none stated"}  `[{'confirmed' if user.injuries else 'needs verification'}]`
- Cardio habits: (learning)
- Strength trends: (learning)
- Recovery patterns: (learning)

## Lifestyle & Routine
_Last updated: {today}_
- Wake / sleep schedule: (learning)
- Work schedule: (learning)
- Travel patterns: (learning)
- Family constraints: (learning)
- Social eating patterns: (learning)

## Behavior & Motivation
_Last updated: {today}_
- What motivates them: (learning)
- What discourages them: (learning)
- Coaching tone preference: {coaching}  `[inferred]`
- Accountability preference: {accountability}  `[inferred]`
- Common failure points: (learning)

## Concerns & Friction Points
_Last updated: {today}_
- (none identified yet — watch for: hunger, low energy, stress, inconsistency, cravings, injury, time constraints)

## Communication Preferences
_Last updated: {today}_
- Length: {length}  `[inferred]`
- Tone: {coaching}  `[inferred]`
- Check-in cadence: (learning)

## Important Historical Context
_Last updated: {today}_
- Major wins: (none yet)
- Recurring patterns: (none yet)
- Useful facts for future coaching: (none yet)

## Change Log
- {today}: profile created from onboarding.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Read / write (atomic) / ensure / clear
# ─────────────────────────────────────────────────────────────────────────────

async def read_profile(telegram_id: str) -> str:
    p = profile_path(telegram_id)
    if not p.exists():
        return ""
    async with aiofiles.open(p, "r") as f:
        return await f.read()


async def write_profile(telegram_id: str, content: str) -> None:
    """Atomic write: temp file in the same dir, then os.replace."""
    p = profile_path(telegram_id)
    tmp = p.with_suffix(".md.tmp")
    async with aiofiles.open(tmp, "w") as f:
        await f.write(content)
    os.replace(tmp, p)  # atomic on the same filesystem


async def ensure_profile(user: User) -> str:
    """Create the profile from template if it doesn't exist yet."""
    existing = await read_profile(user.telegram_id)
    if existing:
        return existing
    content = build_template(user)
    await write_profile(user.telegram_id, content)
    logger.info(f"Profile created for {user.telegram_id}")
    return content


async def clear_profile(telegram_id: str) -> None:
    p = profile_path(telegram_id)
    if p.exists():
        p.unlink()


def _last_synced(content: str):
    m = re.search(r"<!-- last_synced: (.+?) -->", content)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1))
    except ValueError:
        return None


def is_update_due(content: str) -> bool:
    """True if the profile hasn't been synced within the throttle window."""
    ts = _last_synced(content)
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts >= _MIN_UPDATE_INTERVAL
