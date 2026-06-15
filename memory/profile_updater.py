"""
Adaptive profile updater — extracts structured attributes from recent activity.

The attribute store (user_attributes table) is now the single source of long-term
memory. Synthesis output is a JSON array of new/changed attributes — no more
markdown profile. This is cheaper (Haiku instead of Sonnet), faster, and the
output is queryable and immediately available in context (no parse-out step).

Throttled to once per ~3 hours per user (cost control). Triggers bio regeneration
after upsert so the dashboard "Arnie's read" stays current.

History note: this used to also write a freeform markdown profile to disk
(profile.md) via profile_manager.write_profile. That layer was redundant with
the attribute store and lagged by hours. The markdown writer is no longer called,
though read_profile() still serves any existing files for old users until the
attribute store fully replaces them.
"""
import logging
from datetime import datetime, timezone

from memory.profile_manager import is_update_due, ensure_profile, _now_iso

logger = logging.getLogger(__name__)

_UPDATE_SYSTEM = """\
You extract structured attributes about a user from their recent activity for a
fitness/nutrition coaching app. The attribute store is the central source of truth
the coach reads on every turn — write to it aggressively, accurately, and reusably.

Input you'll receive:
  • STRUCTURED DB DATA — confirmed ground truth (age, height, dietary prefs, etc.)
  • ALREADY-TRACKED ATTRIBUTE KEYS — keys already in the store. REUSE these EXACT
    keys, never invent synonyms (no fitness_cardio_preference if fitness_cardio_habits
    already exists).
  • Recent conversation (last ~30 turns)
  • Food/exercise patterns (last 30 days)
  • Weight trend

Return ONLY a JSON array of new or materially-changed attributes. No markdown,
no preamble, no code fences, no explanation text. Empty array `[]` if nothing
changed.

═══════════════════════════════════════════════════════
JSON SCHEMA — each object in the array:
═══════════════════════════════════════════════════════
{
  "attribute_key": "nutrition_diet_style",   // {category}_{noun} format, lowercase, snake_case
  "display_name": "Diet style",              // SHORT, human, NEVER repeats the category
  "value": "high-protein, flexible dieting", // ≤ 80 chars, " · " separator for lists (not commas)
  "value_type": "string",                    // string | number | boolean | json
  "unit": null,                              // mg, g, hours, lbs, ng/dL, etc. — null if N/A
  "category": "nutrition",                   // nutrition|fitness|health|lifestyle|behavior|mental|custom
  "relevance_tier": "core",                  // core (always shown) | daily | contextual | archive
  "confidence": "confirmed",                 // confirmed | inferred | needs_verification
  "source": "conversation"                   // conversation | training_program | user_stated
}

═══════════════════════════════════════════════════════
KEY REUSE — CRITICAL:
═══════════════════════════════════════════════════════
Before emitting an attribute_key, scan ALREADY-TRACKED ATTRIBUTE KEYS in the
context. If a fact is the SAME concept as one already tracked, reuse that EXACT
key — never a synonym.

CANONICAL keys for standard concepts (do not invent variants):
  nutrition_diet_style · nutrition_staple_foods · nutrition_protein_habits
  nutrition_meal_timing · nutrition_foods_avoided
  fitness_training_split · fitness_training_time · fitness_training_frequency
  fitness_cardio_habits · fitness_preferred_exercises · fitness_sport
  health_injuries · health_physical_limitations
  health_supplement_<name>  (one per supplement: health_supplement_creatine,
                             health_supplement_zinc, health_supplement_vitamin_d…)
  lifestyle_sleep_schedule · lifestyle_work_schedule · lifestyle_stress_level
  lifestyle_occupation · behavior_motivation_driver · behavior_coaching_tone

So: cardio preference/type → fitness_cardio_habits; what motivates them →
behavior_motivation_driver; vitamins/supplement stack → health_supplement_<name>;
wake/sleep times → lifestyle_sleep_schedule; workout time → fitness_training_time.

BANNED keys: health_supplements (aggregate). Always emit one
health_supplement_<name> row per supplement. Never a list under one key.

Only coin a new key for a genuinely new durable metric. Keep it generic
({category}_{noun}) so next time you reuse it instead of fragmenting.

═══════════════════════════════════════════════════════
CONFIDENCE — be honest, do NOT present guesses as facts:
═══════════════════════════════════════════════════════
  "confirmed"          → the user EXPLICITLY stated it, OR it's in the structured DB.
  "inferred"           → you DEDUCED it from behavior/patterns (3+ recurrences).
                         Most learned attributes are inferred.
  "needs_verification" → a single offhand mention you're not sure is durable.

If you didn't hear the user say it in plain words, it's NOT "confirmed".

═══════════════════════════════════════════════════════
VALUE LENGTH & DELIMITERS:
═══════════════════════════════════════════════════════
  • Values ≤ 80 characters. If a fact needs more, compress to the core pattern.
  • Lists use " · " (space-dot-space). Never commas — they look like attribute boundaries.
    Good: "chicken · rice · eggs · oats"   Bad: "chicken, rice, eggs, oats"
  • Shorten verbose old values on update; don't inherit them.

═══════════════════════════════════════════════════════
display_name — SHORT, human, NEVER repeats the category:
═══════════════════════════════════════════════════════
  "Cardio habits", not "Fitness cardio habits"
  "Diet style",    not "Nutrition diet style"
  "Motivation",    not "Behavior motivation driver"

═══════════════════════════════════════════════════════
RECURRENCE = PREFERENCE:
═══════════════════════════════════════════════════════
People reveal preferences by what they DO repeatedly, not just by saying
"I like X". If logs/conversation show something recurring, infer it as a
preference (confidence=inferred) even with no explicit statement:
  • a cardio activity logged most sessions → fitness_cardio_habits
  • a food eaten 3+ times → nutrition_staple_foods
  • an exercise hit every week → fitness_preferred_exercises
  • a recurring meal/training time → the matching attribute

═══════════════════════════════════════════════════════
BEHAVIORAL INFERENCE — learn from what they DID, not just said:
═══════════════════════════════════════════════════════
You now also receive a BEHAVIORAL DATA block (macro adherence, strength trend,
meal timing, recovery, detected signals). Mine it for DURABLE PATTERNS and store
them as confidence="inferred":
  • strength e1RM rising/stalling on a lift → fitness_strength_trends
    ("incline bench progressing · lat pulldown stalled 3 wks")
  • protein/calorie adherence that splits by day type → nutrition_adherence_pattern
    ("protein slips on rest days, ~40g under" / "weekends run 300 cal high")
  • consistent eating window / late-night habit → nutrition_meal_timing
  • recovery/sleep responding to training load → fitness_recovery_patterns
CRITICAL: store the PATTERN, never the daily snapshot numbers. "protein slips on
rest days" ✓  —  "117g protein on 06-13" ✗ (that's live data, has its own UI).
Only assert a pattern the data actually supports; if a signal is one-off, skip it.
For fitness_strength_trends: use ONLY the numbers in the current STRENGTH TREND
line (actual weight×reps). Do NOT carry forward old per-lift figures from the
existing attribute value — replace them with the current data.

═══════════════════════════════════════════════════════
WHAT TO OUTPUT:
═══════════════════════════════════════════════════════
ONLY new or materially changed attributes. If nothing changed since the last
synthesis, output `[]`.

NEVER output (these live elsewhere and only drift if duplicated here):
  • Structured DB fields — weight, goal weight, calorie/protein/carb/fat targets,
    wake/sleep times, age, height. They have their own UI.
  • Live wearable metrics — HRV, recovery, RHR, last-night sleep, strain. These
    update daily from the device feed; a frozen copy here goes stale immediately.
  • Transient state — today's session focus, today's macros, current streak,
    one-off events ("stomach upset today"). Not durable traits.

CLASSIFICATION (resolve at the source):
  • Protein bars, protein shakes (RTD), energy drinks → FOOD/DRINK, category
    "nutrition" (nutrition_protein_bar_preference / nutrition_staple_foods /
    nutrition_beverage_habits). NEVER health_supplement_*.
  • health_supplement_* is ONLY real supplements: vitamins, minerals, fish oil,
    creatine, protein POWDER.
  • Lab values (a1c, glucose, tsh, lh, testosterone, vitamin-D level, eGFR,
    ferritin) → health_biomarker_<name> with unit, NOT health_supplement_*.

DO output: durable training/eating/sleep habits, real supplements, lab biomarkers,
behavioral patterns, lifestyle details, food preferences, motivators, custom metrics.
"""


async def _gather_context(user, db) -> str:
    """
    Compact recent context for the updater.
    Includes: structured DB profile + arnie_memory.md + conversations + logs + weight.
    """
    from db.queries import (
        get_recent_conversations, get_recent_logs, get_recent_weights,
    )
    from memory.memory_manager import read_memory

    parts = []

    # ── 1. Structured DB profile — confirmed ground truth ──────────────────────
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
        parts.append("STRUCTURED DB DATA (confirmed ground truth — these have their own UI, "
                     "do not emit attributes for them):\n"
                     + "\n".join(structured_lines))

    # ── Already-tracked attribute keys — drives key reuse ─────────────────────
    try:
        from memory.attribute_store import get_all_attributes
        existing = await get_all_attributes(db, user.id)
        if existing:
            key_lines = [f"  {a.attribute_key} = {a.value or '(empty)'}"
                         for a in existing[:60]]
            parts.append(
                "ALREADY-TRACKED ATTRIBUTE KEYS — REUSE these EXACT keys when the fact "
                "matches the concept. Never invent a synonym key:\n"
                + "\n".join(key_lines)
            )
    except Exception:
        pass

    # ── Legacy reflection notes (read-only — update_memory is retired) ────────
    mem = await read_memory(user.telegram_id)
    if mem and len(mem.strip()) > 50:
        parts.append("LEGACY REFLECTION NOTES (older system, treat as background context):\n"
                     + mem[:1500])

    # ── Recent conversations ──────────────────────────────────────────────────
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

    # ── Food and exercise patterns ────────────────────────────────────────────
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
        parts.append("FREQUENT FOODS (30d, name×count — items with 3+ = commonly eaten, 8+ = staple):\n"
                     + ", ".join(f"{n}×{c}" for n, c in top))

    if ex_names:
        top = sorted(ex_names.items(), key=lambda x: -x[1])[:12]
        parts.append("FREQUENT EXERCISES (30d): " + ", ".join(f"{n}×{c}" for n, c in top))
        if total_sessions:
            parts.append(f"Training time: {evening_sessions}/{total_sessions} logged sessions were evening (5pm+).")

    # ── Weight trend ──────────────────────────────────────────────────────────
    weights = await get_recent_weights(db, user.id, days=30)
    if len(weights) >= 2:
        sw = sorted(weights, key=lambda w: w.timestamp)
        parts.append(f"Weight trend (30d): {sw[0].weight_kg:.1f}kg → {sw[-1].weight_kg:.1f}kg over {len(sw)} weigh-ins.")

    # ── Behavioral signals (G) — what the user actually DID, for pattern inference
    try:
        from db.queries import get_recent_health_snapshots
        from memory.behavioral_signals import build_behavioral_block
        snaps = await get_recent_health_snapshots(db, user.id, days=21)
        block = build_behavioral_block(logs, weights, snaps, prefs, user)
        if block:
            parts.append(block)
    except Exception:
        logger.warning("behavioral signal block failed", exc_info=True)

    return "\n\n".join(parts) if parts else "No context data available."


def _parse_attribute_array(raw: str) -> list[dict]:
    """Parse a JSON array from the LLM output. Tolerates code fences and stray prose."""
    import json
    import re

    s = (raw or "").strip()
    if not s:
        return []
    # Strip code fences if model added them despite instructions
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip()

    # Locate the first `[` and last `]` so any stray preamble/postamble is ignored
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        arr = json.loads(s[start:end + 1])
        return arr if isinstance(arr, list) else []
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse attribute JSON array: {e}")
        return []


async def maybe_update_profile(user, db, force: bool = False) -> bool:
    """
    Extract structured attributes from recent activity and upsert them.
    Throttled to once per ~3 hours per user. Returns True if attributes were upserted.

    On success:
      1. Parses JSON attribute array → upserts to user_attributes (the source of truth)
      2. Prunes low-priority attributes if over the active cap
      3. Triggers bio regeneration (dashboard "Arnie's read")
    """
    from core.llm import chat

    # Throttle check — keep the existing profile.md file as the timestamp source
    # so we don't re-derive throttling. ensure_profile() returns the file content
    # (and creates it on first call) — we only read the sync stamp.
    current = await ensure_profile(user)
    if not force and not is_update_due(current):
        return False

    try:
        context = await _gather_context(user, db)
        prompt = (
            f"TODAY: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"SYNC TIMESTAMP: {_now_iso()}\n\n"
            f"=== RECENT CONTEXT ===\n{context}\n\n"
            "Return a JSON array of new or materially-changed attributes. "
            "No markdown, no preamble. Empty array `[]` if nothing changed."
        )

        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_UPDATE_SYSTEM,
            tools=False,
            max_tokens=1500,
            model="claude-haiku-4-5-20251001",
        )
        raw_output = (result.get("text") or "").strip()

        attrs = _parse_attribute_array(raw_output)

        # Bump the throttle timestamp so we don't re-run for 3h even if attrs is empty
        # (preserves the existing file-based throttle without writing the full markdown).
        try:
            from memory.profile_manager import _touch_sync_stamp
            await _touch_sync_stamp(user.telegram_id)
        except Exception:
            pass

        if attrs:
            try:
                from memory.attribute_store import upsert_many, prune_attributes
                count = await upsert_many(db, user.id, attrs)
                pruned = await prune_attributes(db, user.id)
                logger.info(f"Synthesized {count} attributes for {user.telegram_id}"
                            + (f", pruned {pruned}" if pruned else ""))

                # Audit trail
                try:
                    from db.models import MemoryUpdate
                    db.add(MemoryUpdate(
                        user_id=user.id,
                        update_summary=f"Profile synthesis: {count} attributes upserted",
                        reasoning="Adaptive attribute refresh from recent activity",
                    ))
                    await db.commit()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Attribute upsert failed for {user.telegram_id}: {e}")
                return False

        # Bio regen runs whether or not new attributes landed — it picks up the
        # latest snapshot of all attributes and refreshes the dashboard read.
        try:
            from memory.bio_generator import maybe_update_bio
            await maybe_update_bio(user, db)
        except Exception as e:
            logger.error(f"Bio update failed for {user.telegram_id}: {e}")

        return bool(attrs)

    except Exception as e:
        logger.error(f"Profile synthesis failed for {user.telegram_id}: {e}")
        return False
