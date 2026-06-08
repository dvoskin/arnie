"""
Profile consolidator — nightly attribute cleanup pass.

A tight Haiku call that reviews all active attributes and:
  1. Identifies attributes to discontinue (stale, redundant, superseded)
  2. Identifies attribute values > 80 chars to shorten

Slotted into the proactive scheduler at ~3am per-user local time.
Much cheaper than a full profile synthesis — pure cleanup, no new inference.
"""
import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CONSOLIDATOR_SYSTEM = """\
You are a profile data quality agent. Given a user's active attributes, output a
JSON cleanup plan.

Rules for discontinue:
- Flag keys that are CLEARLY superseded by a better-named key for the same concept
- Flag keys that are redundant (same concept tracked twice under different names)
- NEVER discontinue confirmed facts

Rules for shorten:
- Flag keys whose values exceed 80 characters
- Provide the compressed value (≤ 80 chars), preserving the core pattern
- Example: "takes fish oil 3×/wk, zinc 50mg daily, mag glycinate 400mg before bed"
  → "fish oil, zinc 50mg, magnesium"
- Only shorten genuinely verbose values; leave terse values unchanged

Output ONLY valid JSON, nothing else:
{
  "discontinue": ["key1", "key2"],
  "shorten": {"key3": "compressed value"}
}

If nothing to clean up: {"discontinue": [], "shorten": {}}
Be conservative — only flag obvious cases. When in doubt, leave it.\
"""


async def consolidate_user_profile(user, db) -> dict:
    """
    Run a Haiku cleanup pass on the user's active attributes.
    Discontinues redundant/superseded rows, shortens verbose values.
    Returns {"discontinued": N, "shortened": N} for logging.
    """
    from core.llm import chat
    from memory.attribute_store import get_all_attributes

    attrs = await get_all_attributes(db, user.id)
    if not attrs:
        return {"discontinued": 0, "shortened": 0}

    lines = []
    for a in attrs:
        conf = f" [{a.confidence}]" if a.confidence != "confirmed" else ""
        lines.append(f"  {a.attribute_key}: {a.value}{conf}")

    prompt = (
        f"User has {len(attrs)} active attributes:\n"
        + "\n".join(lines)
        + "\n\nOutput the cleanup plan JSON."
    )

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_CONSOLIDATOR_SYSTEM,
            tools=False,
            max_tokens=400,
            model="claude-haiku-4-5-20251001",
        )
        raw = (result.get("text") or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        plan = json.loads(raw)
    except Exception as e:
        logger.error(f"Consolidator LLM call failed for user {user.id}: {e}")
        return {"discontinued": 0, "shortened": 0}

    to_discontinue = [k for k in (plan.get("discontinue") or []) if isinstance(k, str)]
    to_shorten = {
        k: v for k, v in (plan.get("shorten") or {}).items()
        if isinstance(k, str) and isinstance(v, str) and 0 < len(v) <= 80
    }

    by_key = {a.attribute_key: a for a in attrs}
    n_disc = n_short = 0
    now = datetime.now(timezone.utc)

    for key in to_discontinue:
        row = by_key.get(key)
        if row and row.confidence != "confirmed":
            row.attribute_status = "discontinued"
            row.updated_at = now
            n_disc += 1

    for key, new_val in to_shorten.items():
        row = by_key.get(key)
        if row and row.value and len(row.value) > len(new_val):
            row.last_value = row.value
            row.value = new_val
            row.updated_at = now
            n_short += 1

    if n_disc or n_short:
        await db.commit()
        logger.info(
            f"Profile consolidation for user {user.id}: "
            f"discontinued {n_disc}, shortened {n_short}"
        )

    return {"discontinued": n_disc, "shortened": n_short}
