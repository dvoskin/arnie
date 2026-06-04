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
) -> dict:
    # ── Basics — short scalar demographics → compact grid ──────────────────
    basics: list[dict] = []

    def basic(label, value, edit_field=None, raw=None):
        if value is None:
            return
        basics.append({
            "label": label,
            "value": str(value),
            "edit_field": edit_field,
            "raw": "" if raw is None else str(raw),
        })

    basic("Name", _clean(user.name), "name", user.name)
    basic("Age", f"{user.age} yrs" if user.age else None, "age", user.age)
    basic("Sex", (_clean(user.sex) or "").title() or None)              # display-only
    basic("Height", _height_str(user.height_cm))                       # display-only
    _cw = _lbs(user.current_weight_kg)
    basic("Current", f"{_cw} lbs" if _cw else None, "current_weight_lbs", _cw)
    _gw = _lbs(user.goal_weight_kg)
    basic("Goal", f"{_gw} lbs" if _gw else None, "goal_weight_lbs", _gw)

    # ── Categories — declared columns + learned attributes, merged ─────────
    cats: dict[str, list] = {}

    def add(cat, label, value, *, edit_field=None, raw=None,
            confidence="confirmed", origin="column", unit=None):
        v = _clean(value)
        if v is None:
            return
        cats.setdefault(cat, []).append({
            "label": label, "value": v, "unit": unit,
            "confidence": confidence, "origin": origin,
            "edit_field": edit_field, "raw": "" if raw is None else str(raw),
        })

    # Goals
    add("goals", "Primary goal",
        _GOAL_LABELS.get(user.primary_goal, (_clean(user.primary_goal) or "").title() or None),
        edit_field="primary_goal", raw=user.primary_goal)
    if prefs:
        add("goals", "Calorie target",
            f"{prefs.calorie_target} kcal/day" if prefs.calorie_target else None,
            edit_field="calorie_target", raw=prefs.calorie_target)
        add("goals", "Protein target",
            f"{prefs.protein_target} g/day" if prefs.protein_target else None,
            edit_field="protein_target", raw=prefs.protein_target)

    # Nutrition / Fitness / Health / Behavior / Lifestyle (declared)
    add("nutrition", "Diet style", user.dietary_preferences,
        edit_field="dietary_preferences", raw=user.dietary_preferences)
    add("fitness", "Experience", (_clean(user.training_experience) or "").title() or None,
        edit_field="training_experience", raw=user.training_experience)
    add("fitness", "Sport", (_clean(user.sport) or "").title() or None)  # display-only
    add("health", "Injuries / limitations", user.injuries,
        edit_field="injuries", raw=user.injuries)
    if prefs:
        add("behavior", "Coaching style", (_clean(prefs.coaching_style) or "").title() or None,
            edit_field="coaching_style", raw=prefs.coaching_style)
        add("behavior", "Accountability", (_clean(prefs.accountability_level) or "").title() or None)
    _tz = user.timezone if (user.timezone and user.timezone != "UTC") else None
    add("lifestyle", "Timezone", _tz, edit_field="timezone", raw=user.timezone)

    # Learned attributes → their categories (active only); declared facts already
    # sit first in each list, so learned ones append after them.
    for a in attributes:
        if getattr(a, "attribute_status", "active") != "active":
            continue
        cat = a.category or "custom"
        val = a.value + (f" {a.unit}" if a.unit else "")
        cats.setdefault(cat, []).append({
            "label": a.display_name or a.attribute_key.replace("_", " ").title(),
            "value": val, "unit": None,
            "confidence": a.confidence, "origin": "attribute",
            "edit_field": None, "raw": "",
        })

    # Stable ordering of categories for the client
    ordered = {}
    for c in CATEGORY_ORDER:
        if c in cats:
            ordered[c] = cats[c]
    for c in cats:  # any unexpected category, appended at the end
        if c not in ordered:
            ordered[c] = cats[c]

    # Clean redundant leading words from LEARNED labels so they read cleanly under
    # their category header: every "Nutrition X" under Nutrition → "X", and any
    # sub-prefix shared by 2+ learned facts in a group (e.g. "Psychology …") gets
    # collapsed too. Declared (column) facts already have clean human labels.
    for cat, facts in ordered.items():
        _dedupe_labels(facts, cat)

    return {
        "name": user.name or "User",
        "basics": basics,
        "categories": ordered,
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
