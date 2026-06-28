"""
User attribute store — the structured, queryable layer beneath the profile markdown.

Every fact Arnie learns about a user (supplement stack, training habits, dietary
style, biomarkers, behavioral patterns, custom metrics) lands here as a row.
New attribute types are new rows, never new columns. The system scales to any
user-specific metric without migrations.

Write paths:
  1. profile_updater (primary) — holistic Sonnet synthesis emits a JSON block
     of new/changed attributes; this module upserts them after each profile write.
  2. update_profile tool (user-initiated) — "attr:" prefix keys route here with
     confidence=confirmed, source=user_stated.

Read paths:
  - context_builder via get_attributes_for_context()  → injected into every prompt
  - bio_generator via get_all_attributes()            → narrative bio generation
  - /api/profile/{token}                             → dashboard display
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.models import UserAttribute

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical key registry
# Maps common variant names → canonical attribute_key.
# The extractor always canonicalizes before upserting.
# ─────────────────────────────────────────────────────────────────────────────

CANONICAL_KEYS: dict[str, str] = {
    # nutrition
    "diet": "nutrition_diet_style",
    "diet_style": "nutrition_diet_style",
    "dietary_style": "nutrition_diet_style",
    "dietary_preference": "nutrition_diet_style",
    "eating_style": "nutrition_diet_style",
    "protein_habits": "nutrition_protein_habits",
    "protein_intake": "nutrition_protein_habits",
    "meal_timing": "nutrition_meal_timing",
    "meal_frequency": "nutrition_meal_timing",
    "favorite_foods": "nutrition_staple_foods",
    "nutrition_favorite_foods": "nutrition_staple_foods",  # collapse — same concept
    "staple_foods": "nutrition_staple_foods",
    "common_foods": "nutrition_staple_foods",
    "foods_avoided": "nutrition_foods_avoided",
    "food_restrictions": "nutrition_foods_avoided",
    "alcohol": "nutrition_alcohol_habits",
    "alcohol_habits": "nutrition_alcohol_habits",
    "snack_habits": "nutrition_snack_patterns",
    # fitness
    "training_time": "fitness_training_time",
    "workout_time": "fitness_training_time",
    "workout_schedule": "fitness_training_time",
    "training_split": "fitness_training_split",
    "workout_split": "fitness_training_split",
    "training_frequency": "fitness_training_frequency",
    "workout_frequency": "fitness_training_frequency",
    "cardio_habits": "fitness_cardio_habits",
    "cardio": "fitness_cardio_habits",
    "preferred_exercises": "fitness_preferred_exercises",
    "favorite_exercises": "fitness_preferred_exercises",
    "strength_trends": "fitness_strength_trends",
    "recovery_patterns": "fitness_recovery_patterns",
    "sport": "fitness_sport",
    # health
    "injuries": "health_injuries",
    "current_injury": "health_injuries",
    "limitations": "health_physical_limitations",
    "zinc": "health_supplement_zinc_mg",
    "zinc_mg": "health_supplement_zinc_mg",
    "creatine": "health_supplement_creatine",
    "protein_powder": "health_supplement_protein_powder",
    "testosterone": "health_biomarker_testosterone_ng_dl",
    "testosterone_level": "health_biomarker_testosterone_ng_dl",
    "sleep_quality": "health_sleep_quality",
    "chronic_fatigue": "health_chronic_fatigue",
    # lifestyle
    "wake_time": "lifestyle_wake_time",
    "sleep_time": "lifestyle_sleep_time",
    "bedtime": "lifestyle_sleep_time",
    "work_schedule": "lifestyle_work_schedule",
    "job": "lifestyle_occupation",
    "occupation": "lifestyle_occupation",
    "travel": "lifestyle_travel_frequency",
    "travel_frequency": "lifestyle_travel_frequency",
    "social_eating": "lifestyle_social_eating",
    "stress_level": "lifestyle_stress_level",
    # behavior
    "motivation": "behavior_motivation_driver",
    "what_motivates": "behavior_motivation_driver",
    "failure_points": "behavior_common_failure_points",
    "struggles": "behavior_common_failure_points",
    "accountability": "behavior_accountability_preference",
    "accountability_preference": "behavior_accountability_preference",
    "behavior_accountability": "behavior_accountability_preference",
    "coaching_tone": "behavior_coaching_tone",
    # mental
    "mental_health": "mental_general_notes",
    "anxiety": "mental_anxiety_notes",
    "stress": "mental_stress_patterns",
    # ── extended variants (collapse observed fragmentation at the source) ──
    # cardio: every phrasing → one slot key
    "cardio_preference": "fitness_cardio_habits",
    "cardio_type": "fitness_cardio_habits",
    "favorite_cardio": "fitness_cardio_habits",
    "preferred_cardio": "fitness_cardio_habits",
    "cardio_activities": "fitness_cardio_habits",
    # motivation
    "motivated_by": "behavior_motivation_driver",
    "motivators": "behavior_motivation_driver",
    "motivation_driver": "behavior_motivation_driver",
    "what_motivates_you": "behavior_motivation_driver",
    # supplements: aggregate restatements → one aggregate key (per-item zinc/creatine
    # etc. keep their own health_supplement_* keys via the entries above)
    "supplements": "health_supplements",
    "supplement_stack": "health_supplements",
    "supplement_list": "health_supplements",
    "vitamins": "health_supplements",
    "vitamins_minerals": "health_supplements",
    "vitamins_and_minerals": "health_supplements",
    # training time
    "preferred_training_time": "fitness_training_time",
    "workout_window": "fitness_training_time",
    "train_time": "fitness_training_time",
    # sleep schedule
    "wake_sleep_schedule": "lifestyle_sleep_schedule",
    "sleep_schedule": "lifestyle_sleep_schedule",
    "wake_and_sleep_schedule": "lifestyle_sleep_schedule",
    # staples / preferred exercises
    "commonly_eaten_staples": "nutrition_staple_foods",
    "common_staples": "nutrition_staple_foods",
    "key_exercises": "fitness_preferred_exercises",
    "main_lifts": "fitness_preferred_exercises",
    # cardio frequency phrasings → the one cardio slot
    "cardio_frequency": "fitness_cardio_habits",
    # protein amount restatements → the protein-habits slot
    "typical_protein": "nutrition_protein_habits",
    "protein_intake_daily": "nutrition_protein_habits",
    "daily_protein": "nutrition_protein_habits",
}

# Category defaults for keys that start with a known prefix
CATEGORY_PREFIXES = {
    "nutrition_": "nutrition",
    "fitness_": "fitness",
    "health_": "health",
    "lifestyle_": "lifestyle",
    "behavior_": "behavior",
    "mental_": "mental",
    "sleep_": "health",
    "custom_": "custom",
}

# Tier defaults by category
DEFAULT_TIERS = {
    "nutrition": "daily",
    "fitness": "core",
    "health": "contextual",
    "lifestyle": "contextual",
    "behavior": "core",
    "mental": "contextual",
    "custom": "contextual",
}

# Keys that are always core tier regardless of category
ALWAYS_CORE = {
    "nutrition_diet_style",
    "nutrition_protein_habits",
    "fitness_training_split",
    "fitness_training_frequency",
    "fitness_training_time",
    "fitness_sport",
    "health_injuries",
    "health_physical_limitations",
    "behavior_motivation_driver",
    "behavior_coaching_tone",
    "lifestyle_stress_level",   # ← добавить
}


def canonicalize_key(raw_key: str) -> str:
    """Normalize a raw attribute key to its canonical form.

    The alias map is keyed on bare nouns ("cardio_preference"), but the model
    usually emits already-prefixed keys ("fitness_cardio_preference"). Try the
    raw key first, then retry with a known category prefix stripped so prefixed
    synonyms still collapse to the canonical slot.
    """
    k = raw_key.strip().lower().replace(" ", "_").replace("-", "_")
    if k in CANONICAL_KEYS:
        return CANONICAL_KEYS[k]
    for prefix in CATEGORY_PREFIXES:
        if k.startswith(prefix):
            bare = k[len(prefix):]
            if bare in CANONICAL_KEYS:
                return CANONICAL_KEYS[bare]
            break
    return k


def category_for_key(key: str) -> str:
    for prefix, cat in CATEGORY_PREFIXES.items():
        if key.startswith(prefix):
            return cat
    return "custom"


def tier_for_key(key: str) -> str:
    if key in ALWAYS_CORE:
        return "core"
    cat = category_for_key(key)
    return DEFAULT_TIERS.get(cat, "contextual")


# Lane-3 live/transient keys — these have a live source (HealthSnapshot, today_log)
# or are recomputed every turn. Persisting them as attributes freezes a stale copy
# that then contradicts the live context (e.g. HRV stuck at an old reading, "today's
# session" showing yesterday). Writes to these keys are dropped at the source; the
# live data surfaces through [WEARABLE]/[COACHING STATE]/[SESSION STATE]/[TODAY].
_LIVE_METRIC_KEYS = {
    "health_biometric_hrv", "health_biometric_rhr", "health_recovery_metric",
    "health_recovery", "health_recovery_score", "health_sleep_quality",
    "health_biometric_sleep", "health_strain", "health_biometric_weight",
    "fitness_session_type_today", "fitness_session_today",
    "behavior_adherence_streak", "behavior_logging_streak",
}


def is_live_metric_key(key: str) -> bool:
    """True if `key` is a Lane-3 live/transient metric that must not be persisted."""
    return key in _LIVE_METRIC_KEYS or key.endswith("_today")


# ─────────────────────────────────────────────────────────────────────────────
# Upsert
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_attribute(
    db,
    user_id: int,
    attribute_key: str,
    value: str,
    *,
    display_name: Optional[str] = None,
    value_type: str = "string",
    unit: Optional[str] = None,
    category: Optional[str] = None,
    relevance_tier: Optional[str] = None,
    source: str = "conversation",
    confidence: str = "inferred",
    attribute_status: str = "active",
) -> None:
    """
    Upsert a single attribute. On conflict (user_id, attribute_key):
    - Only overwrite if incoming confidence >= existing confidence
      (confirmed > inferred > needs_verification)
    - Save old value to last_value before overwriting
    """
    key = canonicalize_key(attribute_key)

    # Lane-3 guard: never persist live/transient metrics (see _LIVE_METRIC_KEYS).
    if is_live_metric_key(key):
        logger.info(
            f"Skipped live/transient attribute {key!r} for user {user_id}"
            " — Lane 3, surfaced live not stored"
        )
        return

    # Per-item always wins: if writing the health_supplements aggregate while
    # any health_supplement_* per-item rows exist, skip — the per-item rows are
    # authoritative and the aggregate would only create a duplicate in the view.
    if key == "health_supplements":
        per_item = (await db.execute(
            select(UserAttribute).where(and_(
                UserAttribute.user_id == user_id,
                UserAttribute.attribute_status == "active",
                UserAttribute.attribute_key.like("health_supplement_%"),
            ))
        )).scalars().first()
        if per_item:
            logger.info(
                f"Skipped health_supplements aggregate for user {user_id}"
                " — per-item rows exist"
            )
            return

    # Taxonomy is enforced by the KEY PREFIX, not the model's free-text category.
    # The category arg comes straight from the LLM (store_attribute / synthesis),
    # and an arg like category='nutrition' on a 'health_supplement_*' key would
    # land the fact in the wrong lane — corrupting every grouped view that trusts
    # `category` ([AI PROFILE], the bio, the briefing brain block). When the key
    # carries a known lane prefix, the prefix wins; the caller's category is only
    # honored for keys with no recognized prefix (bare / custom keys).
    if any(key.startswith(p) for p in CATEGORY_PREFIXES):
        cat = category_for_key(key)
    else:
        cat = category or "custom"
    tier = relevance_tier or tier_for_key(key)

    _conf_rank = {"confirmed": 3, "inferred": 2, "needs_verification": 1}

    existing = (await db.execute(
        select(UserAttribute).where(
            and_(UserAttribute.user_id == user_id,
                 UserAttribute.attribute_key == key)
        )
    )).scalar_one_or_none()

    if existing:
        incoming_rank = _conf_rank.get(confidence, 2)
        existing_rank = _conf_rank.get(existing.confidence, 2)
        if incoming_rank < existing_rank:
            return  # never downgrade confirmed with an inference
        if existing.value != value:
            existing.last_value = existing.value
        existing.value = value
        existing.value_type = value_type
        if unit:
            existing.unit = unit
        existing.category = cat
        existing.relevance_tier = tier
        existing.source = source
        existing.confidence = confidence
        existing.attribute_status = attribute_status
        if display_name:
            existing.display_name = display_name
        existing.updated_at = datetime.now(timezone.utc)
    else:
        # F5 — dedup-on-write: a NEW key whose (substantial) value already exists
        # verbatim on an active attribute in the same category is the same fact
        # reworded under a different key. Skip it (kills the 'Supplements …' twins).
        # Guarded by length so short shared values ('daily', '1-2 RIR') aren't merged.
        norm = (value or "").strip().lower()
        if len(norm) >= 20:
            # Scan ALL statuses, not just active. Scanning only active rows let a
            # fact the nightly consolidator had just discontinued (or that decayed)
            # be re-inserted verbatim under a fresh key — so the duplicate
            # oscillated back every synthesis run. Now a retired twin blocks the
            # re-insert too; if the ONLY copies are retired, the fact is being
            # re-asserted, so revive one row instead of spawning a duplicate.
            siblings = (await db.execute(
                select(UserAttribute).where(and_(
                    UserAttribute.user_id == user_id,
                    UserAttribute.category == cat,
                ))
            )).scalars().all()
            twins = [s for s in siblings if (s.value or "").strip().lower() == norm]
            if twins:
                if not any(s.attribute_status == "active" for s in twins):
                    twins[0].attribute_status = "active"
                    twins[0].updated_at = datetime.now(timezone.utc)
                    logger.info(f"Revived retired duplicate-value twin for {key} (in {cat})")
                else:
                    logger.info(f"Skipped duplicate-value attribute {key} (already in {cat})")
                return
        db.add(UserAttribute(
            user_id=user_id,
            attribute_key=key,
            display_name=display_name or key.replace("_", " ").title(),
            value=value,
            value_type=value_type,
            unit=unit,
            category=cat,
            relevance_tier=tier,
            attribute_status=attribute_status,
            source=source,
            confidence=confidence,
        ))

    await db.commit()


async def upsert_many(db, user_id: int, attrs: list[dict]) -> int:
    """Upsert a batch of attribute dicts. Returns count upserted."""
    count = 0
    for a in attrs:
        key = a.get("attribute_key") or a.get("key")
        value = a.get("value")
        if not key or value is None or str(value).strip() == "":
            continue
        await upsert_attribute(
            db, user_id,
            attribute_key=key,
            value=str(value),
            display_name=a.get("display_name"),
            value_type=a.get("value_type", "string"),
            unit=a.get("unit"),
            category=a.get("category"),
            relevance_tier=a.get("relevance_tier"),
            source=a.get("source", "conversation"),
            confidence=a.get("confidence", "inferred"),
        )
        count += 1
    return count


# Self-healing lifecycle (B):
#   decay  — situational facts untouched for a while drop to ARCHIVE tier. They
#            leave the default block but stay RECALLABLE via salience (D), so the
#            profile stays lean over time without losing anything.
#   prune  — runaway backstop. Counts only the NON-archive (default-injected) set,
#            so decay relieves the pressure. Protects identity (core tier) and
#            user-stated / program facts; otherwise evicts weakest-then-oldest.
_DECAY_DAYS = 45
# Generous backstop — engaged users legitimately hold many durable facts; this only
# fires on true runaway, after decay has already swept the stale tail to archive.
_ACTIVE_CAP = 60
_PROTECTED_TIERS = {"core"}
_PROTECTED_SOURCES = {"user_stated", "training_program"}
_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ts(r):
    t = r.updated_at or _epoch
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


async def decay_stale_attributes(db, user_id: int, days: int = _DECAY_DAYS) -> int:
    """Move situational facts not re-observed in `days` to the archive tier.
    Core/daily identity facts and protected sources are never decayed. Archived
    rows stay active (recoverable + recallable on topic). Returns count decayed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(UserAttribute).where(and_(
            UserAttribute.user_id == user_id,
            UserAttribute.attribute_status == "active",
            UserAttribute.relevance_tier == "contextual",
        ))
    )).scalars().all()
    n = 0
    for r in rows:
        if r.source in _PROTECTED_SOURCES:
            continue
        if _ts(r) < cutoff:
            r.relevance_tier = "archive"
            n += 1
    if n:
        await db.commit()
        logger.info(f"Decayed {n} stale attributes to archive for user {user_id}")
    return n


async def prune_attributes(db, user_id: int, cap: int = _ACTIVE_CAP) -> int:
    """Runaway backstop. If the NON-archive active set exceeds `cap`, soft-
    discontinue the weakest (lowest confidence, then oldest) down to the cap.
    Core-tier and user-stated/program facts are never evicted. Returns count."""
    rows = (await db.execute(
        select(UserAttribute).where(and_(
            UserAttribute.user_id == user_id,
            UserAttribute.attribute_status == "active",
        ))
    )).scalars().all()
    non_archive = [r for r in rows if (r.relevance_tier or "contextual") != "archive"]
    if len(non_archive) <= cap:
        return 0

    _rank = {"needs_verification": 0, "inferred": 1, "confirmed": 2}
    evictable = [r for r in non_archive
                 if (r.relevance_tier or "contextual") not in _PROTECTED_TIERS
                 and r.source not in _PROTECTED_SOURCES]
    evictable.sort(key=lambda r: (_rank.get(r.confidence, 1), _ts(r)))
    n_evict = min(len(non_archive) - cap, len(evictable))
    for r in evictable[:n_evict]:
        r.attribute_status = "discontinued"
    if n_evict:
        await db.commit()
        logger.info(f"Pruned {n_evict} low-priority attributes for user {user_id} (cap {cap})")
    return n_evict


# ─────────────────────────────────────────────────────────────────────────────
# Training-program bridge
# ─────────────────────────────────────────────────────────────────────────────
# A full workout split is STRUCTURED data and stays in the WorkoutProgram table
# (its source of truth — multi-day, per-exercise). We only mirror a COMPACT
# summary into the fitness attributes so the program surfaces in the AI Profile's
# Fitness section and feeds the bio + synthesis, without flattening the structure
# into EAV rows.

_PROGRAM_ATTR_KEYS = ("fitness_training_split", "fitness_program_focus")


async def sync_program_to_attributes(db, user_id: int, program: dict) -> None:
    """Mirror a saved workout program's summary into the fitness attributes.

    Called after a WorkoutProgram row is written (parse / auto-fill). Keeps the
    profile in sync with the user's actual split. The full structured program
    still lives in WorkoutProgram.
    """
    if not program or not isinstance(program, dict):
        return
    split = (program.get("split_name") or "").strip()
    focus = (program.get("focus") or "").strip()
    n_days = len(program.get("days") or []) or len(program.get("rotation") or [])

    if split:
        val = split + (f" ({n_days}-day)" if n_days else "")
        await upsert_attribute(
            db, user_id, attribute_key="fitness_training_split", value=val,
            display_name="Training split", category="fitness",
            relevance_tier="core", source="training_program", confidence="confirmed",
        )
    if focus:
        await upsert_attribute(
            db, user_id, attribute_key="fitness_program_focus", value=focus,
            display_name="Program focus", category="fitness",
            relevance_tier="core", source="training_program", confidence="confirmed",
        )


async def clear_program_attributes(db, user_id: int) -> None:
    """Discontinue the mirrored program attributes when the program is deleted.

    Discontinue (not delete) so history survives and a re-added program
    reactivates the same rows via upsert. The CALLER commits.
    """
    from sqlalchemy import update as _sql_update
    await db.execute(
        _sql_update(UserAttribute)
        .where(and_(
            UserAttribute.user_id == user_id,
            UserAttribute.attribute_key.in_(_PROGRAM_ATTR_KEYS),
            UserAttribute.source == "training_program",
        ))
        .values(attribute_status="discontinued")
    )


# ─────────────────────────────────────────────────────────────────────────────
# User-initiated status change (dashboard "remove")
# ─────────────────────────────────────────────────────────────────────────────

async def set_attribute_status(
    db, user_id: int, attribute_key: str, status: str = "discontinued"
) -> bool:
    """Flip one attribute's status — the dashboard 'remove' control sets it to
    'discontinued' (soft-hide). The row stays for history and drops out of every
    active read path (dashboard, bio, context). It can be re-learned later, which
    re-activates it via upsert. Returns True if a row was found. Commits here."""
    key = canonicalize_key(attribute_key)
    row = (await db.execute(
        select(UserAttribute).where(
            and_(UserAttribute.user_id == user_id,
                 UserAttribute.attribute_key == key)
        )
    )).scalar_one_or_none()
    if not row:
        return False
    row.attribute_status = status
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────────────

async def get_all_attributes(db, user_id: int) -> list[UserAttribute]:
    """All active attributes for a user, ordered by tier then key."""
    _tier_order = {"core": 0, "daily": 1, "contextual": 2, "archive": 3}
    rows = (await db.execute(
        select(UserAttribute).where(
            and_(UserAttribute.user_id == user_id,
                 UserAttribute.attribute_status == "active")
        )
    )).scalars().all()
    return sorted(rows, key=lambda r: (_tier_order.get(r.relevance_tier, 2), r.attribute_key))


_DAILY_WINDOW = timedelta(days=7)


async def get_attributes_for_context(db, user_id: int, message_text: str = "") -> str:
    """
    Build the AI profile block for injection into Arnie's context.

    The user_attributes table is the central source of truth — ALL active
    attributes (everything except archive tier) are included on every turn so
    Arnie never misses a known fact regardless of the current message topic.

    Attributes are grouped by category and annotated with confidence so the
    model can distinguish confirmed facts from working hypotheses.

    `message_text` drives the salience layer (memory/salience.py): the full
    active picture is always shown, but the facts most relevant to THIS message
    are spotlighted up top, and archived facts the default block omits are
    RECALLED when the topic matches — purely additive, nothing is dropped.
    """
    from memory.salience import select_relevant

    rows = await get_all_attributes(db, user_id)
    if not rows:
        return ""

    # Active picture = everything except archive tier (coaching benefits from the
    # full picture — e.g. an injury matters for a meal question). Archive tier is
    # held back from the default block but stays recallable on a topic match.
    selected = [r for r in rows if (r.relevance_tier or "contextual") != "archive"]
    archived = [r for r in rows if (r.relevance_tier or "contextual") == "archive"]

    if not selected:
        return ""

    lines = [
        "[AI PROFILE — central source of truth, what Arnie has learned about this user.",
        "Read on every turn. Confirmed facts are ground truth; inferred facts are working hypotheses.]"
    ]

    # Spotlight: the active facts most pertinent to what the user just said, so
    # the model attends to them first even as the profile grows.
    spotlight = select_relevant(message_text, selected, k=4)
    if spotlight:
        lines.append("  [RELEVANT TO THIS MESSAGE — weight these first]")
        for row in spotlight:
            lines.append(f"    {row.display_name or row.attribute_key}: {row.value}")

    by_cat: dict[str, list] = {}
    for row in selected:
        by_cat.setdefault(row.category, []).append(row)

    # Stable category order — important categories first so a context truncation
    # never drops health/fitness before lifestyle nice-to-haves.
    cat_order = ["fitness", "nutrition", "health", "behavior", "lifestyle", "mental", "custom"]
    ordered = [c for c in cat_order if c in by_cat] + [c for c in by_cat if c not in cat_order]

    for cat in ordered:
        cat_rows = by_cat[cat]
        lines.append(f"  [{cat.upper()}]")
        for row in cat_rows:
            conf_tag = f" [{row.confidence}]" if row.confidence != "confirmed" else ""
            unit_str = f" {row.unit}" if row.unit else ""
            lines.append(f"    {row.display_name or row.attribute_key}: {row.value}{unit_str}{conf_tag}")

    # Recall: archived facts (aged out of the default block) that match the topic.
    recalled = select_relevant(message_text, archived, k=3)
    if recalled:
        lines.append("  [RECALLED — older facts that fit this topic]")
        for row in recalled:
            unit_str = f" {row.unit}" if row.unit else ""
            lines.append(f"    {row.display_name or row.attribute_key}: {row.value}{unit_str}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Parse structured JSON block from profile synthesis output
# ─────────────────────────────────────────────────────────────────────────────

def parse_attributes_from_synthesis(synthesis_output: str) -> tuple[str, list[dict]]:
    """
    The profile_updater synthesis prompt asks the LLM to append a JSON block
    after the markdown, delimited by ---ATTRIBUTES---.

    Returns (markdown_text, list_of_attribute_dicts).
    If no JSON block found, returns (full_text, []).
    """
    marker = "---ATTRIBUTES---"
    if marker not in synthesis_output:
        return synthesis_output.strip(), []

    parts = synthesis_output.split(marker, 1)
    markdown = parts[0].strip()
    json_str = parts[1].strip() if len(parts) > 1 else ""

    if not json_str:
        return markdown, []

    # Strip code fences if present
    json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
    json_str = re.sub(r"\s*```$", "", json_str)

    try:
        attrs = json.loads(json_str)
        if isinstance(attrs, list):
            return markdown, attrs
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse attributes JSON block: {e}")

    return markdown, []
