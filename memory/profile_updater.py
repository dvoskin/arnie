"""
Adaptive profile updater — synthesizes the User Profile Matrix after meaningful
interactions. Full-rewrite with strong preservation guardrails, throttled so it
won't run more than once every few hours per user.
"""
import logging
from datetime import datetime, timezone

from memory.profile_manager import (
    read_profile, write_profile, ensure_profile, is_update_due, _now_iso,
)

logger = logging.getLogger(__name__)

_UPDATE_SYSTEM = """\
You maintain a user's "Profile Matrix" — a living markdown file that makes Arnie
a better coach over time. You are given the CURRENT profile and recent context
(conversation + logged food/workouts/weight). Return the COMPLETE updated profile
markdown and NOTHING else (no preamble, no code fences).

RULES — follow exactly:
1. PRESERVE everything that's still true. You are refining, not rewriting. Never
   drop a section or a fact that hasn't changed. Keep the exact section headings.
2. Only change a fact when the new context clearly supports it (a stated change,
   or a repeated behavior pattern — not a single occurrence).
3. CONFIDENCE TAGS on facts: `[confirmed]` (user explicitly said it),
   `[inferred]` (you deduced it from behavior), `[outdated]` (was true, now
   superseded — keep only if historically useful), `[needs verification]`
   (assumed). When unsure, use `[inferred]` or `[needs verification]` — never
   present a guess as `[confirmed]`.
4. STABLE vs TEMPORARY: only write durable traits. A one-off bad day, a single
   craving, a single skipped workout → do NOT record as a trait. A repeated
   pattern (e.g. logs Oikos shakes most days, trains in the evening) → DO record.
5. CONFLICT RESOLUTION: an explicit user statement beats an old inference. Newer
   beats older for the same fact. If a stable fact genuinely changed (weight,
   goal, routine, schedule), update it and add a Change Log line. Mark the prior
   value `[outdated]` only if it's useful history; otherwise just replace it.
6. TIMESTAMPS: update the "_Last updated: YYYY-MM-DD_" line ONLY for sections you
   actually changed. Leave untouched sections' dates as they are.
7. CHANGE LOG: append a one-line dated entry for each material change. Keep the
   log to the most recent ~12 entries (trim oldest beyond that).
8. PRIVACY: do not record sensitive medical information unless the user explicitly
   shared it for coaching relevance. No diagnoses, medications, or conditions
   inferred from offhand remarks.
9. Keep it TIGHT and useful. Replace "(learning)" / "(none yet)" placeholders with
   real findings as they emerge; leave them if nothing's been learned.
10. Update the top `<!-- last_synced: ... -->` comment to the provided timestamp.

Return only the full updated markdown.\
"""


async def _gather_context(user, db) -> str:
    """Compact recent context for the updater: conversation + logs + weight."""
    from db.queries import (
        get_recent_conversations, get_recent_logs, get_recent_weights,
    )
    parts = []

    convos = await get_recent_conversations(db, user.id, limit=14)
    if convos:
        lines = []
        for c in reversed(convos):
            u = (c.raw_message or "").strip()[:160]
            a = (c.response or "").strip()[:160]
            if u:
                lines.append(f"User: {u}")
            if a:
                lines.append(f"Arnie: {a}")
        parts.append("RECENT CONVERSATION:\n" + "\n".join(lines[-24:]))

    logs = await get_recent_logs(db, user.id, days=21)
    food_names, ex_names, evening_sessions, total_sessions = {}, {}, 0, 0
    for lg in logs:
        for fe in (lg.food_entries or []):
            n = (fe.parsed_food_name or "").strip().lower()
            if n:
                food_names[n] = food_names.get(n, 0) + 1
        for ee in (lg.exercise_entries or []):
            n = (ee.exercise_name or "").strip().lower()
            if n:
                ex_names[n] = ex_names.get(n, 0) + 1
            if ee.timestamp and ee.timestamp.hour >= 17:
                evening_sessions += 1
            total_sessions += 1
    if food_names:
        top = sorted(food_names.items(), key=lambda x: -x[1])[:12]
        parts.append("FREQUENT FOODS (21d, name×count): " +
                     ", ".join(f"{n}×{c}" for n, c in top))
    if ex_names:
        top = sorted(ex_names.items(), key=lambda x: -x[1])[:12]
        parts.append("FREQUENT EXERCISES (21d): " +
                     ", ".join(f"{n}×{c}" for n, c in top))
        if total_sessions:
            parts.append(f"Training time: {evening_sessions}/{total_sessions} logged sessions were evening (5pm+).")

    weights = await get_recent_weights(db, user.id, days=30)
    if len(weights) >= 2:
        sw = sorted(weights, key=lambda w: w.timestamp)
        parts.append(f"Weight trend (30d): {sw[0].weight_kg:.1f}kg → {sw[-1].weight_kg:.1f}kg over {len(sw)} weigh-ins.")

    return "\n\n".join(parts) if parts else "No new structured data."


async def maybe_update_profile(user, db, force: bool = False) -> bool:
    """
    Refresh the Profile Matrix if due. Returns True if it updated.
    Throttled to once per few hours per user (see profile_manager).
    """
    from core.llm import chat

    current = await ensure_profile(user)
    if not force and not is_update_due(current):
        return False

    try:
        context = await _gather_context(user, db)
        prompt = (
            f"TODAY: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"SYNC TIMESTAMP TO USE: {_now_iso()}\n\n"
            f"=== CURRENT PROFILE ===\n{current}\n\n"
            f"=== RECENT CONTEXT ===\n{context}\n\n"
            f"Return the complete updated profile markdown."
        )
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_UPDATE_SYSTEM,
            tools=False,
            max_tokens=2000,
            model="claude-haiku-4-5-20251001",
        )
        updated = (result.get("text") or "").strip()
        # Sanity: must look like the profile (has the header + several sections),
        # otherwise keep the existing one — never let a bad generation wipe it.
        if updated.startswith("```"):
            updated = updated.strip("`").lstrip("markdown").strip()
        if "# User Profile Matrix" in updated and updated.count("##") >= 6 and len(updated) > 400:
            await write_profile(user.telegram_id, updated)
            try:
                from db.models import MemoryUpdate
                db.add(MemoryUpdate(
                    user_id=user.id,
                    update_summary="Profile Matrix synced",
                    reasoning="Adaptive profile refresh from recent activity",
                ))
                await db.commit()
            except Exception:
                pass
            logger.info(f"Profile Matrix updated for {user.telegram_id}")
            return True
        logger.warning(f"Profile update for {user.telegram_id} rejected (failed sanity check)")
        return False
    except Exception as e:
        logger.error(f"Profile update failed for {user.telegram_id}: {e}")
        return False
