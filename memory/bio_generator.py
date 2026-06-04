"""
Bio generator — produces a warm, narrative profile summary from the user's
structured attributes + DB profile fields.

The bio is:
  - User-facing: shown on the dashboard profile section
  - In-chat deliverable: sent when user asks "what do you know about me?"
  - NOT injected into Arnie's coaching context (the profile.md handles that)

Throttled: regenerates at most once per 24 hours, or when forced.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from db.models import User, UserAttribute
from memory.attribute_store import get_all_attributes

logger = logging.getLogger(__name__)

_BIO_TTL = timedelta(hours=24)

_BIO_SYSTEM = """\
You write a sharp coaching read on a fitness/nutrition client — the kind a great
coach jots in their notes before a session. NOT a flattering description.

In 3–4 tight sentences:
  • where they are vs their goal, in one line (use their real numbers)
  • what's already working — their strength / the leverage to build on
  • the single biggest lever or limiter, and the concrete move that fixes it
  • one thing to watch (injury, recurring friction, pattern) when relevant

Be specific and ACTIONABLE — name the actual lever ("front-load protein at
breakfast", "the ACL caps heavy leg volume"), never vague praise. Use their real
patterns and numbers. The more you know about them, the more precise and more
useful the read gets — lean on whatever signal you have. Third person, present
tense, a coach's voice.

Do NOT mention "profile", "AI", "data", or "system". No preamble — just the read.\
"""


def _build_bio_input(user: User, attributes: list[UserAttribute]) -> str:
    parts = []

    # Core structured fields
    facts = []
    if user.name:
        facts.append(f"Name: {user.name}")
    if user.age:
        facts.append(f"Age: {user.age}")
    if user.sex:
        facts.append(f"Sex: {user.sex}")
    if user.height_cm:
        facts.append(f"Height: {user.height_cm:.0f}cm")
    if user.current_weight_kg:
        lbs = user.current_weight_kg * 2.20462
        facts.append(f"Current weight: {lbs:.1f}lb ({user.current_weight_kg:.1f}kg)")
    if user.goal_weight_kg:
        lbs = user.goal_weight_kg * 2.20462
        facts.append(f"Goal weight: {lbs:.1f}lb")
    if user.primary_goal:
        facts.append(f"Primary goal: {user.primary_goal}")
    if user.training_experience:
        facts.append(f"Training experience: {user.training_experience}")
    if user.dietary_preferences:
        facts.append(f"Dietary preferences: {user.dietary_preferences}")
    if user.injuries:
        facts.append(f"Injuries/limitations: {user.injuries}")
    if user.preferences:
        prefs = user.preferences
        if prefs.coaching_style:
            facts.append(f"Coaching style preference: {prefs.coaching_style}")
        if prefs.calorie_target:
            facts.append(f"Calorie target: {prefs.calorie_target}")
        if prefs.protein_target:
            facts.append(f"Protein target: {prefs.protein_target}g")

    if facts:
        parts.append("CORE PROFILE:\n" + "\n".join(facts))

    # Learned attributes by category
    if attributes:
        by_cat: dict[str, list] = {}
        for a in attributes:
            if a.attribute_status != "active":
                continue
            if a.relevance_tier == "archive":
                continue
            by_cat.setdefault(a.category, []).append(a)

        for cat, rows in sorted(by_cat.items()):
            cat_lines = []
            for row in rows:
                unit_str = f" {row.unit}" if row.unit else ""
                conf = f" [{row.confidence}]" if row.confidence != "confirmed" else ""
                cat_lines.append(f"  {row.display_name or row.attribute_key}: {row.value}{unit_str}{conf}")
            if cat_lines:
                parts.append(f"{cat.upper()} ATTRIBUTES:\n" + "\n".join(cat_lines))

    return "\n\n".join(parts) if parts else "No profile data available yet."


async def generate_bio(user: User, attributes: list[UserAttribute]) -> str:
    """Generate a narrative bio from user data. Returns bio text."""
    from core.llm import chat

    bio_input = _build_bio_input(user, attributes)
    prompt = f"Write a profile summary for this user:\n\n{bio_input}"

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_BIO_SYSTEM,
            tools=False,
            max_tokens=300,
            model="claude-haiku-4-5-20251001",
        )
        bio = (result.get("text") or "").strip()
        if len(bio) < 50:
            logger.warning("Bio generation returned too short a result")
            return ""
        return bio
    except Exception as e:
        logger.error(f"Bio generation failed: {e}")
        return ""


async def maybe_update_bio(user: User, db, force: bool = False) -> bool:
    """
    Regenerate and persist the bio if due (24h TTL) or forced.
    Returns True if bio was updated.
    """
    now = datetime.now(timezone.utc)

    if not force and user.user_bio_updated_at:
        last = user.user_bio_updated_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last < _BIO_TTL:
            return False

    attributes = await get_all_attributes(db, user.id)
    bio = await generate_bio(user, attributes)

    if bio:
        user.user_bio = bio
        user.user_bio_updated_at = now
        await db.commit()
        logger.info(f"Bio updated for user {user.telegram_id}")
        return True

    return False


async def get_bio_for_chat(user: User, db) -> str:
    """
    Returns the current bio, refreshing if stale. Used for in-chat delivery
    when the user asks 'what do you know about me?'
    """
    await maybe_update_bio(user, db)
    return user.user_bio or ""
