"""
Adaptive profile updater — synthesizes the User Profile Matrix after meaningful
interactions. Full-rewrite with strong preservation guardrails, throttled to
~3h per user.

Key fixes vs. original:
  - Synthesis context now includes User model structured fields (age, height,
    training_experience, dietary_preferences, injuries, coaching_style, etc.)
    which were previously ignored, causing the profile to contradict the DB.
  - arnie_memory.md (reflection notes) is now fed in as context.
  - Model upgraded to Sonnet for higher-quality holistic synthesis.
  - Synthesis prompt is assertive: replace (learning) placeholders when data exists.
  - After each successful write, extracts structured attributes via a JSON block
    and upserts them to user_attributes table.
  - Triggers bio regeneration after attribute upsert.
"""
import logging
from datetime import datetime, timezone

from memory.profile_manager import (
    read_profile, write_profile, ensure_profile, is_update_due, _now_iso,
)

logger = logging.getLogger(__name__)

_UPDATE_SYSTEM = """\
You maintain a user's "Profile Matrix" — a living markdown file that makes Arnie
a better coach over time. You receive the CURRENT profile, the user's structured
DB data, and recent behavioral context (conversations + food/exercise logs + weight).

Return TWO things separated by the exact marker ---ATTRIBUTES---:

PART 1: The COMPLETE updated profile markdown (everything before ---ATTRIBUTES---).
PART 2: A JSON array of new or updated attributes (everything after ---ATTRIBUTES---).

═══════════════════════════════════════════════════════
MARKDOWN RULES (Part 1):
═══════════════════════════════════════════════════════
1. PRESERVE everything still true. Refine, don't wipe. Keep exact section headings.
2. REPLACE (learning) placeholders whenever you have ANY evidence. A partial note
   beats a placeholder. If STRUCTURED DB DATA shows dietary_preferences, injuries,
   training_experience — write them. DB data is confirmed ground truth.
3. TRANSLATE DB fields into profile lines:
   - dietary_preferences → Diet style (confirmed)
   - training_experience → Training experience (confirmed)
   - injuries → Injuries / limitations (confirmed)
   - coaching_style pref → Coaching tone preference (confirmed)
   - age, height, sex → Demographics (confirmed)
   If FREQUENT FOODS shows any item 3+ times → write it as Commonly eaten staples.
   If any item appears 8+ times → write it as Favorite foods.
4. CONFIDENCE TAGS: `[confirmed]` (user stated/DB has it), `[inferred]` (you deduced
   from behavior), `[outdated]` (superseded), `[needs verification]` (assumed).
   DB fields count as [confirmed]. Single-turn mentions are [needs verification].
   Repeated patterns (3+ occurrences) earn [inferred].
5. STABLE vs TEMPORARY: only write durable traits. One bad day → no. Repeated
   pattern → yes. But if DB clearly shows it, write it regardless of recurrence.
6. CONFLICT RESOLUTION: explicit user statement > old inference. DB value > inference.
   Newer > older for same fact. Mark prior value [outdated] if historically useful.
7. Update "_Last updated: YYYY-MM-DD_" only for sections you changed.
8. CHANGE LOG: append one line per material change. Keep most recent ~12 entries.
9. Update top <!-- last_synced: ... --> to the provided timestamp.
10. Return ONLY the markdown (no preamble, no code fences).

═══════════════════════════════════════════════════════
JSON RULES (Part 2, after ---ATTRIBUTES---):
═══════════════════════════════════════════════════════
Output a JSON array. Each object represents one new or updated attribute:
[
  {
    "attribute_key": "nutrition_diet_style",
    "display_name": "Diet style",
    "value": "high-protein, flexible dieting",
    "value_type": "string",
    "unit": null,
    "category": "nutrition",
    "relevance_tier": "core",
    "confidence": "confirmed",
    "source": "conversation"
  }
]

Key naming: {category}_{noun}_{qualifier}
  Categories: nutrition, fitness, health, lifestyle, behavior, mental, custom
  Tiers: core (always shown), daily (shown if updated recently), contextual (topic-match), archive (stored only)

KEY REUSE — CRITICAL, this is what stops duplicate fields from piling up:
  • Before emitting an attribute_key, scan ALREADY-TRACKED ATTRIBUTE KEYS in the
    context. If a fact is the SAME concept as one already tracked, reuse that EXACT
    key — never a reworded synonym (no second key for a concept you already track).
  • Use these CANONICAL keys for standard concepts (do not invent variants):
      nutrition_diet_style · nutrition_favorite_foods · nutrition_staple_foods ·
      nutrition_protein_habits · nutrition_meal_timing · nutrition_foods_avoided ·
      fitness_training_split · fitness_training_time · fitness_training_frequency ·
      fitness_cardio_habits · fitness_preferred_exercises ·
      health_injuries · health_supplement_<name> (one per supplement, e.g.
        health_supplement_zinc) · lifestyle_sleep_schedule · lifestyle_work_schedule ·
      lifestyle_stress_level · behavior_motivation_driver · behavior_coaching_tone
    So: cardio preference/type → fitness_cardio_habits; what motivates them →
    behavior_motivation_driver; vitamins/supplement stack → health_supplement_<name>;
    wake/sleep times → lifestyle_sleep_schedule; workout time → fitness_training_time.
  • Per-supplement facts use health_supplement_<name> — NOT a fresh "supplements:
    a, b, c" aggregate each run (that creates duplicates).
  • Only coin a NEW key for a genuinely new durable metric not covered above, and
    make it GENERIC and reusable ({category}_{noun}) so next time you reuse it too —
    never one-off phrasings like fitness_cardio_preference vs fitness_cardio_type.

CONFIDENCE — be honest, do NOT present guesses as facts:
  "confirmed"          → the user EXPLICITLY stated it, or it's in the structured DB.
  "inferred"           → you DEDUCED it from behavior/patterns. MOST learned
                         attributes are inferred — a noticed pattern, a tendency,
                         a weakness you spotted. Tag these "inferred", not "confirmed".
  "needs_verification" → a single offhand mention you're not sure is durable.
  If you didn't hear the user say it in plain words, it is NOT "confirmed".

display_name — SHORT, human, and do NOT repeat the category (it renders under a
  category header). "Calorie range", not "Nutrition calorie range". "Cardio
  preference", not "Fitness cardio preference". "Frustrated by", not "Psychology
  frustrated by".

RECURRENCE = PREFERENCE. People reveal preferences by what they DO repeatedly, not
just by saying "I like X". If the logs/conversation show something recurring, infer
it as a preference (tag [inferred]) even with no explicit statement:
  • a cardio activity logged most sessions → nutrition? no → fitness_cardio_habits
    (e.g. "spin bike, walks") [inferred]
  • a food eaten most days → nutrition_favorite_foods / staples [inferred]
  • an exercise hit every week → fitness_preferred_exercises [inferred]
  • a recurring meal-timing / training-time pattern → the matching attribute [inferred]
Look actively for these, don't wait to be told.

Only output attributes that are NEW or materially CHANGED from the current profile.
If nothing changed, output an empty array: []
Do not output attributes for things like name, weight, goal — those are in the DB.
DO output attributes for: supplements, biomarkers, training habits, behavioral patterns,
  food preferences, lifestyle details, custom tracked metrics.\
"""


async def _gather_context(user, db) -> str:
    """
    Compact recent context for the updater.
    Includes: structured DB profile + arnie_memory.md + conversations + logs + weight.
    """
    from db.queries import (
        get_recent_conversations, get_recent_logs, get_recent_weights,
    )
    from core.context_builder import fmt_profile
    from memory.memory_manager import read_memory

    parts = []

    # ── 1. Structured DB profile (THIS WAS MISSING — now the most important input) ──
    prefs = user.preferences
    structured_lines = []
    if user.age:
        structured_lines.append(f"Age: {user.age}")
    if user.sex:
        structured_lines.append(f"Sex: {user.sex}")
    if user.height_cm:
        structured_lines.append(f"Height: {user.height_cm:.0f}cm")
    if user.current_weight_kg:
        structured_lines.append(f"Current weight: {user.current_weight_kg:.1f}kg")
    if user.goal_weight_kg:
        structured_lines.append(f"Goal weight: {user.goal_weight_kg:.1f}kg")
    if user.primary_goal:
        structured_lines.append(f"Primary goal: {user.primary_goal}")
    if user.training_experience:
        structured_lines.append(f"Training experience: {user.training_experience}")
    if user.dietary_preferences:
        structured_lines.append(f"Dietary preferences: {user.dietary_preferences}")
    if user.injuries:
        structured_lines.append(f"Injuries / limitations: {user.injuries}")
    if user.sport:
        structured_lines.append(f"Sport: {user.sport}")
    if prefs:
        if prefs.coaching_style:
            structured_lines.append(f"Coaching style preference: {prefs.coaching_style}")
        if prefs.accountability_level:
            structured_lines.append(f"Accountability level: {prefs.accountability_level}")
        if prefs.calorie_target:
            structured_lines.append(f"Calorie target: {prefs.calorie_target}")
        if prefs.protein_target:
            structured_lines.append(f"Protein target: {prefs.protein_target}g")
        if prefs.wake_time:
            structured_lines.append(f"Wake time: {prefs.wake_time}")
        if prefs.sleep_time:
            structured_lines.append(f"Sleep time: {prefs.sleep_time}")

    if structured_lines:
        parts.append("STRUCTURED DB DATA (confirmed ground truth — always populate profile from this):\n"
                     + "\n".join(structured_lines))

    # ── Already-tracked attribute keys (so synthesis REUSES keys, not reinvents) ──
    # Feeding the existing key list is the durable fix for duplicate fields: the
    # model reuses fitness_cardio_habits instead of coining fitness_cardio_preference.
    try:
        from memory.attribute_store import get_all_attributes
        existing = await get_all_attributes(db, user.id)
        if existing:
            key_lines = [f"  {a.attribute_key} = {a.display_name or a.attribute_key}"
                         for a in existing[:60]]
            parts.append(
                "ALREADY-TRACKED ATTRIBUTE KEYS — when a fact matches one of these "
                "concepts, REUSE the EXACT key; never invent a synonym key for it:\n"
                + "\n".join(key_lines)
            )
    except Exception:
        pass

    # ── 2. Previously captured behavioral notes ───────────────────────────────
    mem = await read_memory(user.telegram_id)
    if mem and len(mem.strip()) > 50:
        parts.append("BEHAVIORAL NOTES (previously captured by reflection system):\n"
                     + mem[:1500])

    # ── 3. Recent conversations ───────────────────────────────────────────────
    convos = await get_recent_conversations(db, user.id, limit=20)
    if convos:
        lines = []
        for c in reversed(convos):
            u = (c.raw_message or "").strip()[:200]
            a = (c.response or "").strip()[:200]
            if u:
                lines.append(f"User: {u}")
            if a:
                lines.append(f"Arnie: {a}")
        parts.append("RECENT CONVERSATION:\n" + "\n".join(lines[-30:]))

    # ── 4. Food and exercise patterns ────────────────────────────────────────
    logs = await get_recent_logs(db, user.id, days=30)
    food_names: dict[str, int] = {}
    ex_names: dict[str, int] = {}
    evening_sessions = total_sessions = 0

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
        top = sorted(food_names.items(), key=lambda x: -x[1])[:15]
        parts.append("FREQUENT FOODS (30d, name×count — items with 3+ = commonly eaten, 8+ = staple/favorite):\n"
                     + ", ".join(f"{n}×{c}" for n, c in top))

    if ex_names:
        top = sorted(ex_names.items(), key=lambda x: -x[1])[:12]
        parts.append("FREQUENT EXERCISES (30d): " + ", ".join(f"{n}×{c}" for n, c in top))
        if total_sessions:
            parts.append(f"Training time: {evening_sessions}/{total_sessions} logged sessions were evening (5pm+).")

    # ── 5. Weight trend ──────────────────────────────────────────────────────
    weights = await get_recent_weights(db, user.id, days=30)
    if len(weights) >= 2:
        sw = sorted(weights, key=lambda w: w.timestamp)
        parts.append(f"Weight trend (30d): {sw[0].weight_kg:.1f}kg → {sw[-1].weight_kg:.1f}kg over {len(sw)} weigh-ins.")

    return "\n\n".join(parts) if parts else "No context data available."


async def maybe_update_profile(user, db, force: bool = False) -> bool:
    """
    Refresh the Profile Matrix if due. Returns True if it updated.
    Throttled to once per ~3 hours per user.

    On success:
      1. Writes updated markdown to profile.md
      2. Parses the structured attributes JSON block → upserts to user_attributes
      3. Triggers bio regeneration
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
            "Return the complete updated profile markdown, then ---ATTRIBUTES--- "
            "followed by the JSON array of changed attributes."
        )

        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_UPDATE_SYSTEM,
            tools=False,
            max_tokens=3000,
            model="claude-sonnet-4-6",
        )
        raw_output = (result.get("text") or "").strip()

        # Strip code fences from the whole output if present
        if raw_output.startswith("```"):
            raw_output = raw_output.strip("`").lstrip("markdown").strip()

        # Split into markdown + attributes JSON
        from memory.attribute_store import parse_attributes_from_synthesis
        updated_markdown, attrs = parse_attributes_from_synthesis(raw_output)

        # Sanity check the markdown
        if ("# User Profile Matrix" in updated_markdown
                and updated_markdown.count("##") >= 6
                and len(updated_markdown) > 400):
            await write_profile(user.telegram_id, updated_markdown)

            # Audit trail
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

            # Upsert extracted attributes
            if attrs:
                try:
                    from memory.attribute_store import upsert_many, prune_attributes
                    count = await upsert_many(db, user.id, attrs)
                    pruned = await prune_attributes(db, user.id)
                    logger.info(f"Upserted {count} attributes for {user.telegram_id}"
                                + (f", pruned {pruned}" if pruned else ""))
                except Exception as e:
                    logger.error(f"Attribute upsert failed for {user.telegram_id}: {e}")

            # Trigger bio regeneration
            try:
                from memory.bio_generator import maybe_update_bio
                await maybe_update_bio(user, db)
            except Exception as e:
                logger.error(f"Bio update failed for {user.telegram_id}: {e}")

            return True

        logger.warning(f"Profile update for {user.telegram_id} rejected (failed sanity check)")
        return False

    except Exception as e:
        logger.error(f"Profile update failed for {user.telegram_id}: {e}")
        return False
