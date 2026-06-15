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
- NEVER flag lifestyle_stress_level and mental_stress_patterns as duplicates — they
  track different things: current stress level vs. recurring stress patterns over time
  
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


async def _merge_canonical_aliases(db, user_id: int, attrs: list) -> int:
    """
    Pre-pass: merge rows whose keys are aliases of each other into the canonical key.
    Deterministic — no LLM needed. Keeps the higher-confidence row; if tied, keeps
    the more recently updated one. Returns count of rows discontinued.
    """
    from memory.attribute_store import canonicalize_key
    from sqlalchemy import select, and_
    from db.models import UserAttribute

    _conf_rank = {"confirmed": 3, "inferred": 2, "needs_verification": 1}
    _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Group active rows by their canonical key
    by_canonical: dict = {}
    for a in attrs:
        canon = canonicalize_key(a.attribute_key)
        by_canonical.setdefault(canon, []).append(a)

    n_merged = 0
    now = datetime.now(timezone.utc)
    for canon, rows in by_canonical.items():
        if len(rows) < 2:
            continue
        # Sort: confirmed first, then most recently updated
        rows.sort(
            key=lambda r: (
                _conf_rank.get(r.confidence, 2),
                (r.updated_at or _epoch).replace(tzinfo=timezone.utc)
                if (r.updated_at or _epoch).tzinfo is None
                else (r.updated_at or _epoch),
            ),
            reverse=True,
        )
        keeper = rows[0]
        # Rename keeper to canonical if it isn't already
        if keeper.attribute_key != canon:
            keeper.attribute_key = canon
            keeper.updated_at = now
        for dupe in rows[1:]:
            dupe.attribute_status = "discontinued"
            dupe.updated_at = now
            n_merged += 1
            logger.info(
                f"Merged alias {dupe.attribute_key!r} → {canon!r} for user {user_id}"
            )

    if n_merged:
        await db.commit()
    return n_merged


async def consolidate_user_profile(user, db) -> dict:
    """
    Run a Haiku cleanup pass on the user's active attributes.
    Phase 1: deterministic canonical-alias merge (no LLM).
    Phase 2: Haiku reviews remaining attrs for semantic redundancy + verbose values.
    Returns {"discontinued": N, "shortened": N} for logging.
    """
    from core.llm import chat
    from memory.attribute_store import get_all_attributes, decay_stale_attributes

    attrs = await get_all_attributes(db, user.id)
    if not attrs:
        return {"discontinued": 0, "shortened": 0}

    # Phase 0 — decay: sweep stale situational facts to archive (lean default block,
    # still recallable on topic via salience). Reload so they drop out of the pass.
    n_decay = await decay_stale_attributes(db, user.id)
    if n_decay:
        attrs = await get_all_attributes(db, user.id)

    # Phase 1 — merge rows that are canonical aliases of each other
    n_alias = await _merge_canonical_aliases(db, user.id, attrs)
    # Reload after merge so the LLM sees the cleaned-up state
    if n_alias:
        attrs = await get_all_attributes(db, user.id)

    # The LLM only reviews the default-injected (non-archive) set.
    review = [a for a in attrs if (a.relevance_tier or "contextual") != "archive"]
    lines = []
    for a in review:
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
            model="claude-sonnet-4-6",
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
    total_disc = n_alias + n_disc
    logger.info(
        f"Profile consolidation for user {user.id}: decayed {n_decay}, "
        f"alias-merged {n_alias}, discontinued {n_disc}, shortened {n_short}"
    )

    return {"discontinued": total_disc, "shortened": n_short, "decayed": n_decay}
