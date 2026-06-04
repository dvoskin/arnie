"""
Unified profile read model.

Merges the three profile sources into ONE categorized structure for the
dashboard + bio:
  • typed columns   (User / UserPreferences)  → declared, editable facts
  • user_attributes (EAV)                     → learned facts
  • WorkoutProgram  (structured)              → summary already bridged into
                                                fitness attributes

This is a pure READ-time merge. It writes nothing and — importantly — it does
NOT touch Arnie's conversation context. Arnie still reads the typed columns
(via context_builder.fmt_profile) and the synthesized markdown exactly as
before; this model only powers what the *user* sees on the dashboard.

Shape returned by build_unified_profile():
  {
    "name": str,
    "basics":     [ {label, value, edit_field|None, raw} ],   # compact grid
    "categories": { cat: [ {label, value, unit, confidence,
                            origin, edit_field|None, raw} ] },
  }

Editability mirrors the existing PATCH /api/profile whitelist exactly — a fact
is editable iff its column is in that whitelist, so no new write surface is
introduced.
"""
from typing import Optional

from db.models import User, UserPreferences, UserAttribute


# Order categories render in (declared 'goals' first, then the learned-attr cats)
CATEGORY_ORDER = [
    "goals", "fitness", "nutrition", "health", "behavior", "lifestyle",
    "mental", "custom",
]

_GOAL_LABELS = {
    "cut": "Cut", "bulk": "Bulk", "maintain": "Maintain",
    "performance": "Performance", "health": "Health",
}

# ─────────────────────────────────────────────────────────────────────────────
# Standard parameter schema — the "every fitness user has these" skeleton.
# Each slot ALWAYS renders (filled, or a muted "learning" placeholder), so the
# profile has a consistent shape across users. A slot's value resolves from, in
# order: a backing DB column ("col"), a learned attribute (by key or alias), a
# supplements aggregate, or a passed-in derived value (favorite foods mined from
# logs). Learned attributes that AREN'T a standard slot fall through to Custom
# Tracking. Slots flagged hide_empty only appear when they have a value.
# ─────────────────────────────────────────────────────────────────────────────
STANDARD_ORDER = ["goals", "nutrition", "fitness", "health", "lifestyle", "behavior"]

STANDARD_SCHEMA = {
    "goals": [
        {"key": "goal_primary",  "label": "Primary goal",   "type": "single", "col": "goal"},
        {"key": "goal_calories", "label": "Calorie target", "type": "single", "col": "cal"},
        {"key": "goal_protein",  "label": "Protein target", "type": "single", "col": "pro"},
    ],
    "nutrition": [
        {"key": "nutrition_favorite_foods", "label": "Favorite foods", "type": "list"},
        {"key": "nutrition_foods_avoided",  "label": "Foods avoided",  "type": "list"},
        {"key": "nutrition_diet_style",     "label": "Diet style",     "type": "single", "col": "diet"},
        {"key": "nutrition_protein_habits", "label": "Protein habits", "type": "single"},
        {"key": "nutrition_meal_timing",    "label": "Meal timing",    "type": "single"},
    ],
    "fitness": [
        {"key": "fitness_training_split",     "label": "Training split",     "type": "single",
         "aliases": ["fitness_workout_split"]},
        {"key": "fitness_training_time",      "label": "Training time",      "type": "single"},
        {"key": "fitness_training_frequency", "label": "Training frequency", "type": "single"},
        {"key": "fitness_experience",         "label": "Experience",         "type": "single", "col": "experience"},
        {"key": "fitness_cardio_habits",      "label": "Cardio habits",      "type": "single"},
        {"key": "fitness_sport",              "label": "Sport",              "type": "single", "col": "sport",
         "hide_empty": True},
    ],
    "health": [
        {"key": "health_injuries",    "label": "Injuries / limitations", "type": "single", "col": "injuries"},
        {"key": "health_supplements", "label": "Supplements",            "type": "supplements"},
    ],
    "lifestyle": [
        {"key": "lifestyle_sleep_schedule", "label": "Sleep schedule", "type": "single", "col": "sleep"},
        {"key": "lifestyle_work_schedule",  "label": "Work schedule",  "type": "single"},
        {"key": "lifestyle_stress_level",   "label": "Stress level",   "type": "single"},
        {"key": "lifestyle_timezone",       "label": "Timezone",       "type": "single", "col": "tz",
         "hide_empty": True},
    ],
    "behavior": [
        {"key": "behavior_coaching_tone",             "label": "Coaching style", "type": "single", "col": "coaching"},
        {"key": "behavior_accountability_preference", "label": "Accountability", "type": "single", "col": "accountability"},
        {"key": "behavior_motivation_driver",         "label": "Motivation",     "type": "single"},
    ],
}

# All keys (incl. aliases) consumed by the standard skeleton — used to decide
# what's "custom".
STANDARD_KEYS = set()
for _slots in STANDARD_SCHEMA.values():
    for _s in _slots:
        STANDARD_KEYS.add(_s["key"])
        STANDARD_KEYS.update(_s.get("aliases", []))


def _lbs(kg: Optional[float]) -> Optional[float]:
    return round(kg * 2.20462, 1) if kg else None


def _height_str(cm: Optional[float]) -> Optional[str]:
    if not cm:
        return None
    inches = cm / 2.54
    ft = int(inches // 12)
    inch = int(round(inches - ft * 12))
    if inch == 12:  # rounding edge
        ft += 1
        inch = 0
    return f"{ft}'{inch}\""


def _clean(v) -> Optional[str]:
    """Normalize a value to a non-empty display string, or None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "not set"):
        return None
    return s


def build_unified_profile(
    user: User,
    prefs: Optional[UserPreferences],
    attributes: list,
    derived: Optional[dict] = None,
) -> dict:
    derived = derived or {}

    # ── Basics — short scalar demographics → compact grid ──────────────────
    basics: list[dict] = []

    def basic(label, value, edit_field=None, raw=None):
        if value is None:
            return
        basics.append({
            "label": label, "value": str(value),
            "edit_field": edit_field, "raw": "" if raw is None else str(raw),
        })

    basic("Name", _clean(user.name), "name", user.name)
    basic("Age", f"{user.age} yrs" if user.age else None, "age", user.age)
    basic("Sex", (_clean(user.sex) or "").title() or None)
    basic("Height", _height_str(user.height_cm))
    _cw = _lbs(user.current_weight_kg)
    basic("Current", f"{_cw} lbs" if _cw else None, "current_weight_lbs", _cw)
    _gw = _lbs(user.goal_weight_kg)
    basic("Goal", f"{_gw} lbs" if _gw else None, "goal_weight_lbs", _gw)

    # ── Index active learned attributes by key ─────────────────────────────
    active = [a for a in attributes if getattr(a, "attribute_status", "active") == "active"]
    by_key = {}
    for a in active:
        by_key.setdefault(a.attribute_key, a)

    # Resolver for column-backed slot sources → (display_value, edit_field, raw)
    def _col(marker):
        if marker == "goal":
            return (_GOAL_LABELS.get(user.primary_goal, (_clean(user.primary_goal) or "").title() or None),
                    "primary_goal", user.primary_goal)
        if marker == "cal":
            return (f"{prefs.calorie_target} kcal/day" if (prefs and prefs.calorie_target) else None,
                    "calorie_target", prefs.calorie_target if prefs else None)
        if marker == "pro":
            return (f"{prefs.protein_target} g/day" if (prefs and prefs.protein_target) else None,
                    "protein_target", prefs.protein_target if prefs else None)
        if marker == "diet":
            return (_clean(user.dietary_preferences), "dietary_preferences", user.dietary_preferences)
        if marker == "experience":
            return ((_clean(user.training_experience) or "").title() or None,
                    "training_experience", user.training_experience)
        if marker == "sport":
            return ((_clean(user.sport) or "").title() or None, None, None)
        if marker == "injuries":
            return (_clean(user.injuries), "injuries", user.injuries)
        if marker == "coaching":
            return ((_clean(prefs.coaching_style) or "").title() or None if prefs else None,
                    "coaching_style", prefs.coaching_style if prefs else None)
        if marker == "accountability":
            return ((_clean(prefs.accountability_level) or "").title() or None if prefs else None, None, None)
        if marker == "sleep":
            if prefs and prefs.wake_time and prefs.sleep_time:
                return (f"{prefs.wake_time}–{prefs.sleep_time}", None, None)
            return (None, None, None)
        if marker == "tz":
            tz = user.timezone if (user.timezone and user.timezone != "UTC") else None
            return (tz, "timezone", user.timezone)
        return (None, None, None)

    # ── Standard skeleton — always-present slots, by category ──────────────
    standard: dict[str, list] = {}
    covered = set()  # learned keys consumed by a standard slot
    for cat in STANDARD_ORDER:
        out = []
        for slot in STANDARD_SCHEMA[cat]:
            key, typ = slot["key"], slot["type"]
            fact = {"label": slot["label"], "type": typ, "filled": False,
                    "value": None, "chips": [], "confidence": "confirmed",
                    "origin": None, "edit_field": None, "raw": ""}
            # 1) column source
            if "col" in slot:
                v, ef, raw = _col(slot["col"])
                if v:
                    fact.update(value=str(v), filled=True, origin="column",
                                edit_field=ef, raw="" if raw is None else str(raw))
            # 2) supplements aggregate
            if not fact["filled"] and typ == "supplements":
                supps = [a for a in active if a.attribute_key.startswith("health_supplement_")]
                if supps:
                    chips = []
                    for s in supps:
                        nm = s.display_name or s.attribute_key.replace("health_supplement_", "").replace("_", " ").title()
                        unit = f" {s.unit}" if s.unit else ""
                        chips.append(f"{nm} {s.value}{unit}".strip())
                        covered.add(s.attribute_key)
                    fact.update(filled=True, origin="attribute", chips=chips,
                                value=", ".join(chips))
            # 3) learned attribute (key or alias)
            if not fact["filled"] and typ != "supplements":
                hit = next((by_key[k] for k in [key] + slot.get("aliases", []) if k in by_key), None)
                if hit:
                    val = hit.value + (f" {hit.unit}" if hit.unit else "")
                    fact.update(value=val, filled=True, origin="attribute", confidence=hit.confidence)
                    covered.add(hit.attribute_key)
                    if typ == "list":
                        fact["chips"] = [c.strip() for c in str(hit.value).split(",") if c.strip()]
            # 4) derived (e.g. favorite foods mined from logs)
            if not fact["filled"] and derived.get(key):
                vals = list(derived[key])
                fact.update(filled=True, origin="derived", confidence="inferred",
                            chips=vals, value=", ".join(vals))
            # hide_empty optional slots when there's nothing to show
            if not fact["filled"] and slot.get("hide_empty"):
                continue
            out.append(fact)
        standard[cat] = out

    # ── Custom — active learned attrs not consumed by the skeleton ─────────
    custom = []
    for a in active:
        if a.attribute_key in covered:
            continue
        val = a.value + (f" {a.unit}" if a.unit else "")
        custom.append({
            "label": a.display_name or a.attribute_key.replace("_", " ").title(),
            "value": val, "category": a.category or "custom",
            "confidence": a.confidence, "origin": "attribute",
            "edit_field": None, "raw": "",
        })
    _dedupe_labels(custom, "custom")

    return {
        "name": user.name or "User",
        "basics": basics,
        "standard": standard,
        "custom": custom,
    }


def _dedupe_labels(facts: list, category: str) -> None:
    """In place: strip a learned fact's leading word when it just repeats the
    category, or is a prefix shared by 2+ learned facts in the same group."""
    learned = [f for f in facts if f.get("origin") == "attribute"]
    if not learned:
        return
    counts: dict = {}
    for f in learned:
        parts = f["label"].split()
        if parts:
            counts[parts[0].lower()] = counts.get(parts[0].lower(), 0) + 1
    cat_l = (category or "").lower()
    for f in learned:
        parts = f["label"].split()
        if len(parts) > 1:
            lead = parts[0].lower()
            if lead == cat_l or counts.get(lead, 0) >= 2:
                cleaned = " ".join(parts[1:])
                # Capitalize first letter so "calorie range" → "Calorie range"
                f["label"] = cleaned[:1].upper() + cleaned[1:]
