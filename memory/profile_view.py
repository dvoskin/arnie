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
import re
from typing import Optional

from db.models import User, UserPreferences, UserAttribute


def _split_list(value) -> list[str]:
    """Split a comma-separated attribute value into items WITHOUT breaking numbers
    that use a thousands separator (e.g. "9,200 steps/day" stays one item, while
    "running, walking" splits into two). Splits on a comma only when it's followed
    by a non-digit or end-of-string — a list separator, never a thousands comma."""
    return [x.strip() for x in re.split(r",(?=\D|$)", str(value)) if x.strip()]


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
    # Goals category in the AI profile is for LEARNED goal-related facts only
    # (motivation drivers, deeper "why", timelines Arnie picks up from conversation).
    # The structured settings — primary goal, goal weight, calories/protein/carbs/fat —
    # live in the "Goals & targets" card at the top of the profile tab, NOT here.
    # Empty by default; populates as Arnie learns specifics about the user's goals.
    "goals": [
        {"key": "goal_why",      "label": "Why this goal", "type": "single",
         "match": ["why_goal", "goal_why", "goal_reason", "goal_driver"], "hide_empty": True},
        {"key": "goal_timeline", "label": "Timeline",       "type": "single",
         "match": ["goal_timeline", "goal_deadline", "by_when", "target_date"], "hide_empty": True},
    ],
    "nutrition": [
        {"key": "nutrition_staple_foods", "label": "Staple foods", "type": "list",
         "aliases": ["nutrition_favorite_foods"]},
        {"key": "nutrition_foods_avoided",  "label": "Foods avoided",  "type": "list"},
        {"key": "nutrition_diet_style",     "label": "Diet style",     "type": "single", "col": "diet"},
        {"key": "nutrition_protein_habits", "label": "Protein habits", "type": "single"},
        {"key": "nutrition_meal_timing",    "label": "Meal timing",    "type": "single"},
    ],
    "fitness": [
        {"key": "fitness_training_split",     "label": "Training split",     "type": "single",
         "aliases": ["fitness_workout_split"]},
        {"key": "fitness_training_time",      "label": "Training time",      "type": "single",
         "match": ["training_time", "workout_time", "training time", "workout time"]},
        {"key": "fitness_training_frequency", "label": "Training frequency", "type": "single"},
        {"key": "fitness_experience",         "label": "Experience",         "type": "single", "col": "experience"},
        # Steps are their OWN metric — keep them out of "Favorite cardio" (which is
        # for activities like walking/running). value_match catches step counts even
        # when they were mis-filed under a cardio key, and claims them first so the
        # cardio slot below never absorbs them. hide_empty: only shows when present.
        {"key": "fitness_daily_steps",        "label": "Daily steps",        "type": "single",
         "match": ["step"], "value_match": ["step"], "hide_empty": True},
        {"key": "fitness_cardio_habits",      "label": "Favorite cardio",    "type": "list",
         "match": ["cardio"]},
        {"key": "fitness_sport",              "label": "Sport",              "type": "single", "col": "sport",
         "hide_empty": True},
    ],
    "health": [
        {"key": "health_injuries",    "label": "Injuries / limitations", "type": "single", "col": "injuries"},
        {"key": "health_supplements", "label": "Supplements",            "type": "supplements",
         "match": ["supplement", "vitamin", "mineral"]},
    ],
    "lifestyle": [
        {"key": "lifestyle_sleep_schedule", "label": "Sleep schedule", "type": "single", "col": "sleep",
         "match": ["wake", "bedtime", "sleep_schedule", "sleep schedule", "sleep_time"]},
        {"key": "lifestyle_work_schedule",  "label": "Work schedule",  "type": "single"},
        {"key": "lifestyle_stress_level",   "label": "Stress level",   "type": "single"},
        {"key": "lifestyle_timezone",       "label": "Timezone",       "type": "single", "col": "tz",
         "hide_empty": True},
    ],
    "behavior": [
        {"key": "behavior_coaching_tone",             "label": "Coaching style", "type": "single", "col": "coaching"},
        {"key": "behavior_accountability_preference", "label": "Accountability", "type": "single", "col": "accountability"},
        {"key": "behavior_motivation_driver",         "label": "Motivation",     "type": "single",
         "match": ["motivat"]},
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

    # Demographics — who the user is. Goal/targets live in the dedicated
    # "Goals & targets" card at the top of the profile tab and are NOT
    # duplicated here. Current weight stays because it's a measurement the
    # user logs regularly, not a target.
    basic("Name", _clean(user.name), "name", user.name)
    basic("Age", f"{user.age} yrs" if user.age else None, "age", user.age)
    basic("Sex", (_clean(user.sex) or "").title() or None)
    basic("Height", _height_str(user.height_cm))
    _cw = _lbs(user.current_weight_kg)
    basic("Current weight", f"{_cw} lbs" if _cw else None, "current_weight_lbs", _cw)

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

    def _concept_hits(slot_cat: str, match_kw: list) -> list:
        """Active attrs whose key/display-name contains a slot's match keyword,
        scoped to the slot's category (plus the generic 'custom' bucket, where
        the synthesizer often files matchable facts). Lets differently-worded
        variants — 'Cardio Preference', 'Cardio Type', 'Motivated By' — fold
        into the right standard slot instead of fragmenting into Custom."""
        if not match_kw:
            return []
        hits = []
        for a in active:
            if a.attribute_key in covered:
                continue
            acat = a.category or "custom"
            if acat != slot_cat and acat != "custom":
                continue
            hay = (a.attribute_key + " " + (a.display_name or "")).lower()
            if any(kw in hay for kw in match_kw):
                hits.append(a)
        return hits

    def _value_hits(slot_cat: str, value_kw: list) -> list:
        """Active attrs whose VALUE contains a keyword — catches facts mis-filed
        under the wrong key (e.g. a step count stored as 'favorite cardio'). Scoped
        to the slot's category (+ generic 'custom') and never re-claims a covered key."""
        if not value_kw:
            return []
        hits = []
        for a in active:
            if a.attribute_key in covered:
                continue
            acat = a.category or "custom"
            if acat != slot_cat and acat != "custom":
                continue
            if any(kw in (a.value or "").lower() for kw in value_kw):
                hits.append(a)
        return hits

    for cat in STANDARD_ORDER:
        out = []
        for slot in STANDARD_SCHEMA[cat]:
            key, typ = slot["key"], slot["type"]
            match_kw = slot.get("match", [])
            fact = {"label": slot["label"], "key": key, "type": typ, "filled": False,
                    "value": None, "chips": [], "confidence": "confirmed",
                    "origin": None, "edit_field": None, "raw": ""}

            if typ == "list":
                # Show the real list, not every rephrasing. Clean sources lead:
                # the derived behavioral signal (logged foods/cardio) + the
                # canonical attribute. Concept-match variants are always folded
                # away (covered, so they leave Custom); their wordy restatements
                # are unioned in ONLY when there's no clean source at all — so we
                # never drop data, but a canonical value isn't cluttered by its
                # own paraphrases. Recurrence leads (favorite foods 5 → 1 fix).
                has_derived = bool(derived.get(key))
                sources = []
                if has_derived:
                    sources.append(list(derived[key]))
                for ak in [key] + slot.get("aliases", []):
                    if ak in by_key and ak not in covered:
                        sources.append(_split_list(by_key[ak].value))
                        covered.add(ak)
                hits = _concept_hits(cat, match_kw)
                if not sources:
                    for a in hits:
                        sources.append(_split_list(a.value))
                for a in hits:
                    covered.add(a.attribute_key)
                chips, seen = [], set()
                for src in sources:
                    for it in src:
                        s = str(it).strip()
                        if s and s.lower() not in seen:
                            seen.add(s.lower())
                            chips.append(s)
                if chips:
                    fact.update(filled=True, chips=chips[:6], value=", ".join(chips[:6]),
                                origin="derived" if has_derived else "attribute",
                                confidence="inferred")

            elif typ == "supplements":
                # The per-item keys (health_supplement_*) are the real stack — one
                # clean chip each. Aggregate 'supplements: a, b, c' restatements and
                # vitamin/mineral notes are folded away (covered) and only shown
                # when there's no per-item data, so they never duplicate the
                # structured chips. Drop the verbose 'Health Supplement ' prefix.
                per_item = [a for a in active
                            if a.attribute_key.startswith("health_supplement_")
                            and a.attribute_key not in covered]
                hits = [a for a in _concept_hits(cat, match_kw)
                        if not a.attribute_key.startswith("health_supplement_")]
                for a in hits:
                    covered.add(a.attribute_key)
                display = per_item if per_item else hits
                if display:
                    chips, seen = [], set()
                    for s in display:
                        nm = (s.display_name or
                              s.attribute_key.replace("health_supplement_", "").replace("_", " ").title())
                        nm = nm.replace("Health Supplement ", "").strip()
                        unit = f" {s.unit}" if s.unit else ""
                        chip = f"{nm} {s.value}{unit}".strip()
                        if chip.lower() not in seen:
                            seen.add(chip.lower())
                            chips.append(chip)
                        covered.add(s.attribute_key)
                    fact.update(filled=True, origin="attribute", chips=chips,
                                value=", ".join(chips))

            else:  # single
                # 1) column source
                if "col" in slot:
                    v, ef, raw = _col(slot["col"])
                    if v:
                        fact.update(value=str(v), filled=True, origin="column",
                                    edit_field=ef, raw="" if raw is None else str(raw))
                # 2) learned attribute (exact key or alias)
                if not fact["filled"]:
                    hit = next((by_key[k] for k in [key] + slot.get("aliases", []) if k in by_key), None)
                    if hit:
                        val = hit.value + (f" {hit.unit}" if hit.unit else "")
                        fact.update(value=val, filled=True, origin="attribute", confidence=hit.confidence)
                        covered.add(hit.attribute_key)
                # 2.5) value match — claim a fact mis-filed under another key (e.g. a
                #      step count stored as 'favorite cardio'). Covered so the slots
                #      that follow (cardio) never re-absorb it.
                if slot.get("value_match"):
                    vhits = _value_hits(cat, slot["value_match"])
                    if vhits:
                        if not fact["filled"]:
                            m = vhits[0]
                            val = m.value + (f" {m.unit}" if m.unit else "")
                            val = re.sub(r"^(averages?|about|approx\.?|around|roughly|~)\s+",
                                         "", val, flags=re.I)
                            fact.update(value=val, filled=True, origin="attribute", confidence=m.confidence)
                        for a in vhits:
                            covered.add(a.attribute_key)
                # 3) concept match — fill if still empty, then absorb the rest so
                #    differently-worded restatements don't clutter Custom.
                hits = _concept_hits(cat, match_kw)
                if hits:
                    if not fact["filled"]:
                        m = hits[0]
                        val = m.value + (f" {m.unit}" if m.unit else "")
                        fact.update(value=val, filled=True, origin="attribute", confidence=m.confidence)
                    for a in hits:
                        covered.add(a.attribute_key)
                # 4) derived
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
            "key": a.attribute_key, "removable": True,
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
