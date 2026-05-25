"""
AI-generated dashboard insights.
Calls Claude with a compact data summary, returns 3-5 short coaching observations.
Cached per-user for 1 hour to keep cost down.
"""
import json
import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

# In-memory cache: {user_id: (timestamp, insights_list)}
_CACHE: dict = {}
_TTL = 3600  # 1 hour


def _build_summary(stats: dict) -> str:
    """Compact text summary of the user's stats for the LLM."""
    user = stats.get("user", {})
    targets = stats.get("targets") or {}
    today = stats.get("today") or {}
    history = stats.get("history") or []
    weights = stats.get("weights") or []

    lines = [
        f"User: {user.get('name')} | Goal: {user.get('goal')} | "
        f"Weight {user.get('current_weight_lbs')}lb → goal {user.get('goal_weight_lbs')}lb",
        f"Targets: {targets.get('calories') or '—'} cal / {targets.get('protein') or '—'}g protein per day",
        "",
        f"TODAY: {today.get('calories', 0)} cal, {today.get('protein', 0)}g protein, "
        f"{today.get('carbs', 0)}g C, {today.get('fats', 0)}g F  "
        f"workout={today.get('workout_completed', False)}  cardio={today.get('cardio_completed', False)}",
        "",
        "HISTORY (last 30 days, closed days only):",
    ]
    closed = [h for h in history if h.get("status") == "closed"]
    for h in closed[-14:]:
        lines.append(
            f"  {h['date']}: {h['calories']} cal, {h['protein']}g P, "
            f"workout={'✓' if h.get('workout') else '✗'}"
        )

    if weights:
        lines.append("")
        lines.append("WEIGHT TREND:")
        for w in weights[-10:]:
            lines.append(f"  {w['date']}: {w['lbs']} lbs")

    return "\n".join(lines)


async def generate_insights(stats: dict) -> List[str]:
    """Call Claude to produce 3-5 short coaching insights."""
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY():
        return []

    summary = _build_summary(stats)
    prompt = f"""You are Arnie, a no-BS fitness and nutrition coach reviewing a user's recent data. Write 3 to 5 SHORT coaching insights — each one line, 12-25 words, no preamble.

Be specific. Reference real numbers from the data. Call out patterns, not single days. Mix wins with things to fix. Avoid generic advice.

Examples of GOOD insights:
- "Protein averaging 145g over 7 days — solid, keep that floor"
- "Weight dropped 1.4 lb in 10 days — right on target for your cut"
- "3 workouts skipped in 5 days — recovery or motivation issue?"
- "Calories trending 200 over target on weekends — that's where the deficit is leaking"

Examples of BAD insights (do NOT write these):
- "Keep up the good work!" (vague, no data)
- "Make sure you're hitting your macros" (no specifics)
- "Consistency is key" (filler)

Return ONLY a valid JSON array of strings. No prose before or after.

DATA:
{summary}
"""

    try:
        client = _get_anthropic()
        response = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Strip markdown code fences if Claude wrapped the JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        insights = json.loads(text)
        if isinstance(insights, list):
            return [str(s) for s in insights if s][:5]
    except Exception as e:
        logger.error(f"Insight generation failed: {e}")

    return []


async def get_insights(user_id: int, stats: dict, force: bool = False) -> List[str]:
    """Cached insights — regenerates if older than 1 hour."""
    now = time.time()
    cached = _CACHE.get(user_id)
    if not force and cached and (now - cached[0]) < _TTL:
        return cached[1]

    insights = await generate_insights(stats)
    if insights:
        _CACHE[user_id] = (now, insights)
    return insights
