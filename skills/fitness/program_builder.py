"""
Science-based workout program generator.

Given a goal (hypertrophy | strength | general), training frequency (3-6 d/wk),
split (ppl | upper_lower | full_body | bro | custom), available equipment, and
user experience level, build_program() returns a deterministic, serializable
program spec:

    {
      "name":            "Push / Pull / Legs",
      "goal":            "hypertrophy",
      "days_per_week":   6,
      "split":           "ppl",
      "experience":      "intermediate",
      "equipment":       ["barbell", "dumbbell", "cable", "machine", "bodyweight"],
      "weak_points":     ["chest_upper"],
      "rationale":       "12-16 sets/muscle/week ... [evidence-grounded]",
      "weekly_volume":   {"chest_mid": 14, "lats": 16, ...},
      "sessions": [
        {
          "name":   "Push A",
          "focus":  ["chest_mid", "chest_upper", "triceps", "shoulders"],
          "exercises": [
            {"canonical": "Bench Press",
             "sets": 4, "reps": "6-8", "rir": 2,
             "rest_seconds": 150, "notes": "main lift"},
            ...
          ]
        }, ...
      ]
    }

The function is PURE — no DB, no IO. The API layer / tool executor handles
persistence.

Evidence base (cited in `rationale`):
  • Schoenfeld et al. 2017, J Sports Sci — set-volume meta: 10+ sets/muscle/wk
    grows muscle ~more than <10; benefit tapers above 20.
  • Schoenfeld et al. 2016, Sports Med — frequency meta: training each muscle
    >=2x/week beats 1x for hypertrophy, equating volume.
  • Helms et al. 2018 / Zourdos RIR — proximity-to-failure (RIR) drives
    stimulus on compound lifts; RIR 1-3 works hypertrophy, RIR 0-1 isolation.
  • ACSM 2009 / Schoenfeld 2017 — rep ranges: hypertrophy 6-12 (sweet spot
    8-10), strength 1-5, general fitness 8-12.
  • Grgic et al. 2018 — rest 2-3 min on compound lifts > 1 min for strength
    AND hypertrophy.

Adding a new split: register it in SPLITS and provide a session-template
mapping `position -> {name, focus_muscles}`.
"""
from __future__ import annotations

from typing import Optional

from skills.fitness.exercise_catalog import EXERCISES, lookup_canonical


# ── Constants ─────────────────────────────────────────────────────────────────

# Volume bands per muscle per week. Sourced from Schoenfeld 2017 — 10-20
# sets/muscle/week with diminishing returns above 20. Tuned by experience:
# beginners under-recover, advanced lifters need more volume to keep growing.
VOLUME_BY_EXPERIENCE = {
    "beginner":     (10, 12),
    "intermediate": (12, 16),
    "advanced":     (15, 20),
}

# Rep ranges by goal. Compound lifts use the lower end, isolation the upper.
REPS_BY_GOAL = {
    "hypertrophy": {"main": "6-10", "accessory": "8-12", "isolation": "10-15"},
    "strength":    {"main": "3-5",  "accessory": "5-8",  "isolation": "8-12"},
    "general":     {"main": "6-8",  "accessory": "8-10", "isolation": "10-12"},
}

# RIR targets by goal. Beginners stay further from failure to manage form +
# recovery; advanced lifters push harder.
RIR_BY_GOAL = {
    "hypertrophy": {"main": 2, "accessory": 1, "isolation": 0},
    "strength":    {"main": 2, "accessory": 2, "isolation": 1},
    "general":     {"main": 2, "accessory": 2, "isolation": 1},
}

# Beginner pad — add 1 RIR across the board.
RIR_BEGINNER_PAD = 1

# Rest seconds by category (overrides catalog when goal/experience dictates).
# Strength training uses longer rest on main lifts to preserve force output.
REST_BY_GOAL = {
    "hypertrophy": {"main": 150, "accessory": 90,  "isolation": 60},
    "strength":    {"main": 180, "accessory": 120, "isolation": 90},
    "general":     {"main": 120, "accessory": 90,  "isolation": 60},
}

# Default equipment when the user doesn't specify — assume a fully-equipped gym.
DEFAULT_EQUIPMENT = ("barbell", "dumbbell", "cable", "machine", "bodyweight")

# Valid splits and the cadence each supports.
SPLITS = {
    "ppl":          {"days_options": (3, 6),       "label": "Push / Pull / Legs"},
    "upper_lower":  {"days_options": (4,),         "label": "Upper / Lower"},
    "full_body":    {"days_options": (3, 4),       "label": "Full Body"},
    "bro":          {"days_options": (5,),         "label": "Bro Split"},
    "custom":       {"days_options": (3, 4, 5, 6), "label": "Custom"},
}

# Per-session muscle focus map. Each entry: split_key → ordered list of
# (session_name, focus_muscles). When days_per_week exceeds the base rotation,
# the list cycles ("Push A", "Push B", ...).
SESSION_TEMPLATES: dict[str, list[tuple[str, list[str]]]] = {
    "ppl": [
        ("Push A",  ["chest_mid", "chest_upper", "triceps", "shoulders"]),
        ("Pull A",  ["lats", "mid_back", "biceps", "traps"]),
        ("Legs A",  ["quads", "glutes", "hamstrings", "calves", "abs"]),
        ("Push B",  ["chest_upper", "shoulders", "triceps", "chest_mid"]),
        ("Pull B",  ["mid_back", "lats", "biceps", "traps"]),
        ("Legs B",  ["hamstrings", "glutes", "quads", "calves"]),
    ],
    "upper_lower": [
        ("Upper A", ["chest_mid", "lats", "mid_back", "shoulders", "biceps", "triceps"]),
        ("Lower A", ["quads", "hamstrings", "glutes", "calves", "abs"]),
        ("Upper B", ["chest_upper", "lats", "mid_back", "shoulders", "biceps", "triceps"]),
        ("Lower B", ["hamstrings", "quads", "glutes", "calves", "abs"]),
    ],
    "full_body": [
        ("Full Body A", ["quads", "chest_mid", "lats", "shoulders", "abs"]),
        ("Full Body B", ["hamstrings", "chest_upper", "mid_back", "biceps", "calves"]),
        ("Full Body C", ["glutes", "chest_mid", "lats", "triceps", "abs"]),
        ("Full Body D", ["quads", "mid_back", "shoulders", "biceps", "calves"]),
    ],
    "bro": [
        ("Chest",      ["chest_mid", "chest_upper", "chest_lower", "triceps"]),
        ("Back",       ["lats", "mid_back", "lower_back", "biceps"]),
        ("Shoulders",  ["shoulders", "traps"]),
        ("Legs",       ["quads", "hamstrings", "glutes", "calves", "abs"]),
        ("Arms / Abs", ["biceps", "triceps", "forearms", "abs"]),
    ],
    "custom": [
        # Mirrors PPL when no concrete custom template is supplied — keeps the
        # generator coverage-clean instead of returning nothing.
        ("Push",  ["chest_mid", "chest_upper", "triceps", "shoulders"]),
        ("Pull",  ["lats", "mid_back", "biceps", "traps"]),
        ("Legs",  ["quads", "glutes", "hamstrings", "calves", "abs"]),
        ("Upper", ["chest_mid", "lats", "shoulders", "biceps", "triceps"]),
        ("Lower", ["quads", "hamstrings", "glutes", "calves"]),
    ],
}


# ── Indices over the catalog ──────────────────────────────────────────────────

def _by_primary(equipment: tuple[str, ...]) -> dict[str, list[dict]]:
    """Index catalog entries by primary muscle, filtered to the allowed
    equipment. Used to PICK exercises for each session."""
    out: dict[str, list[dict]] = {}
    for e in EXERCISES:
        eq = e.get("equipment")
        if eq not in equipment:
            continue
        # Skip pure cardio in strength session selection.
        if e.get("category") == "cardio":
            continue
        out.setdefault(e["primary"], []).append(e)
    return out


def _pick_for_muscle(
    primary: str, by_primary: dict, want_category: str,
    used_canonicals: set[str],
) -> Optional[dict]:
    """Pick the first catalog entry for `primary` matching `want_category`
    ('main' | 'accessory' | 'finisher') that hasn't been used yet in this
    session. Falls back to any unused movement for that primary."""
    candidates = by_primary.get(primary) or []
    # Preferred order: main lifts first when want_category == "main", else
    # accessories first. Stable — catalog order is meaningful (compounds first).
    if want_category == "main":
        cand_first = [c for c in candidates if c.get("category") == "main"]
        cand_rest = [c for c in candidates if c.get("category") != "main"]
    else:
        cand_first = [c for c in candidates if c.get("category") == "accessory"]
        cand_rest = [c for c in candidates if c.get("category") not in ("accessory", "cardio")]
    for c in cand_first + cand_rest:
        if c["canonical"] not in used_canonicals:
            return c
    return None


# ── Per-session builder ────────────────────────────────────────────────────────

def _build_session(
    name: str,
    focus_muscles: list[str],
    *,
    goal: str,
    experience: str,
    by_primary: dict,
    weak_points: list[str],
) -> dict:
    """Build one session covering its focus_muscles.

    Allocation rule:
      • For each PRIMARY focus muscle: 1 main lift + 1 accessory.
      • For each SECONDARY focus muscle (only 1 movement, accessory).
      • Weak-point muscles get +1 accessory.
      • Compounds are placed first (catalog order is intentional).
    """
    rir_pad = RIR_BEGINNER_PAD if experience == "beginner" else 0
    reps = REPS_BY_GOAL.get(goal, REPS_BY_GOAL["general"])
    rir = RIR_BY_GOAL.get(goal, RIR_BY_GOAL["general"])
    rest = REST_BY_GOAL.get(goal, REST_BY_GOAL["general"])

    # First half = primary focus (gets main + accessory each); rest = secondary
    # (1 accessory each). Cap session size at ~6 exercises so sessions stay
    # sane (~60-75 min for hypertrophy with the prescribed rest).
    primary_focus = focus_muscles[: max(1, len(focus_muscles) // 2 + 1)]
    secondary_focus = focus_muscles[len(primary_focus):]

    used: set[str] = set()
    exercises: list[dict] = []

    # MAIN LIFTS on each primary
    for muscle in primary_focus:
        pick = _pick_for_muscle(muscle, by_primary, "main", used)
        if not pick:
            continue
        used.add(pick["canonical"])
        sets_count = 4 if goal != "strength" else 5
        exercises.append({
            "canonical":    pick["canonical"],
            "sets":         sets_count,
            "reps":         reps["main"],
            "rir":          rir["main"] + rir_pad,
            "rest_seconds": rest["main"],
            "notes":        "main lift",
            "primary":      pick["primary"],
            "equipment":    pick["equipment"],
        })

    # ACCESSORIES on primaries
    for muscle in primary_focus:
        pick = _pick_for_muscle(muscle, by_primary, "accessory", used)
        if not pick:
            continue
        used.add(pick["canonical"])
        exercises.append({
            "canonical":    pick["canonical"],
            "sets":         3,
            "reps":         reps["accessory"],
            "rir":          rir["accessory"] + rir_pad,
            "rest_seconds": rest["accessory"],
            "notes":        "accessory",
            "primary":      pick["primary"],
            "equipment":    pick["equipment"],
        })

    # SECONDARY muscles get one isolation each
    for muscle in secondary_focus:
        pick = _pick_for_muscle(muscle, by_primary, "accessory", used)
        if not pick:
            continue
        used.add(pick["canonical"])
        exercises.append({
            "canonical":    pick["canonical"],
            "sets":         3,
            "reps":         reps["isolation"],
            "rir":          rir["isolation"] + rir_pad,
            "rest_seconds": rest["isolation"],
            "notes":        "isolation",
            "primary":      pick["primary"],
            "equipment":    pick["equipment"],
        })

    # WEAK POINTS: +1 accessory each (if this session targets them)
    for muscle in weak_points:
        if muscle in focus_muscles:
            pick = _pick_for_muscle(muscle, by_primary, "accessory", used)
            if not pick:
                continue
            used.add(pick["canonical"])
            exercises.append({
                "canonical":    pick["canonical"],
                "sets":         3,
                "reps":         reps["isolation"],
                "rir":          rir["isolation"] + rir_pad,
                "rest_seconds": rest["isolation"],
                "notes":        f"weak-point bias ({muscle})",
                "primary":      pick["primary"],
                "equipment":    pick["equipment"],
            })

    return {
        "name":      name,
        "focus":     focus_muscles,
        "exercises": exercises,
    }


# ── Weekly volume calculator ──────────────────────────────────────────────────

def _weekly_volume(sessions: list[dict]) -> dict[str, int]:
    """Total set count per muscle across the week. The PRIMARY of each picked
    movement carries the full set count — synergist contribution is real but is
    accounted for downstream in muscle_recovery (involvement map), and double-
    counting it here would inflate the per-week numbers above evidence-based
    targets."""
    totals: dict[str, int] = {}
    for s in sessions:
        for ex in s["exercises"]:
            p = ex.get("primary")
            if not p:
                continue
            totals[p] = totals.get(p, 0) + int(ex.get("sets", 0))
    return totals


# ── Public API ────────────────────────────────────────────────────────────────

def _normalize_equipment(equipment) -> tuple[str, ...]:
    """Accept list / CSV / None → tuple of valid tags. Bodyweight is ALWAYS
    available (push-ups, planks etc.); even an "equipment=barbell only" gym
    still has the floor."""
    if equipment is None:
        eq = list(DEFAULT_EQUIPMENT)
    elif isinstance(equipment, str):
        eq = [t.strip().lower() for t in equipment.split(",") if t.strip()]
    else:
        eq = [str(t).strip().lower() for t in equipment]
    valid = {"barbell", "dumbbell", "cable", "machine", "bodyweight", "kettlebell", "bands", "cardio"}
    eq = [t for t in eq if t in valid]
    if "bodyweight" not in eq:
        eq.append("bodyweight")
    return tuple(eq)


def _normalize_split(split: Optional[str], days_per_week: int) -> str:
    """Resolve a split key, defaulting to a sensible one for the given cadence
    when split is unset or invalid."""
    if split and split in SPLITS:
        return split
    # auto-pick by cadence
    if days_per_week <= 3:
        return "full_body"
    if days_per_week == 4:
        return "upper_lower"
    if days_per_week == 5:
        return "bro"
    return "ppl"


def _normalize_goal(goal: Optional[str]) -> str:
    g = (goal or "hypertrophy").strip().lower()
    if g in REPS_BY_GOAL:
        return g
    # common synonyms
    if g in ("muscle", "size", "growth", "build"):
        return "hypertrophy"
    if g in ("powerlifting", "max", "1rm", "strong"):
        return "strength"
    return "general"


def _normalize_experience(experience: Optional[str]) -> str:
    e = (experience or "intermediate").strip().lower()
    return e if e in VOLUME_BY_EXPERIENCE else "intermediate"


def _normalize_weak_points(weak_points) -> list[str]:
    if not weak_points:
        return []
    if isinstance(weak_points, str):
        return [w.strip().lower() for w in weak_points.split(",") if w.strip()]
    return [str(w).strip().lower() for w in weak_points]


def _rationale(
    goal: str, experience: str, split_key: str, days_per_week: int,
    volume: dict[str, int],
) -> str:
    """Short, evidence-grounded paragraph naming the volume target, frequency,
    and effort prescription. Used by Arnie to ground the in-chat explanation."""
    low, high = VOLUME_BY_EXPERIENCE[experience]
    split_label = SPLITS[split_key]["label"]
    sample = ", ".join(
        f"{m} {v}" for m, v in sorted(volume.items(), key=lambda x: -x[1])[:4]
    )
    return (
        f"{split_label}, {days_per_week} d/wk. Targets {low}-{high} sets per muscle "
        f"per week (Schoenfeld 2017 hypertrophy meta — diminishing returns above 20). "
        f"Each muscle hit at least 2x/week where the split allows (Schoenfeld 2016 "
        f"frequency meta). Effort prescribed in RIR for a {goal} stimulus "
        f"(Helms/Zourdos): compounds RIR 1-2, isolations RIR 0-1. "
        f"Top volumes this week: {sample}."
    )


def build_program(
    goal: Optional[str] = None,
    days_per_week: int = 4,
    split: Optional[str] = None,
    equipment=None,
    experience: Optional[str] = None,
    weak_points=None,
) -> dict:
    """Build a science-based program. Pure function. Returns the serializable
    spec described in the module docstring.

    Defaults are sensible (hypertrophy / intermediate / 4-day upper-lower / full
    gym) so a bare build_program() call still yields a complete program.
    """
    goal_n = _normalize_goal(goal)
    exp_n = _normalize_experience(experience)
    days_n = max(2, min(7, int(days_per_week or 4)))
    split_n = _normalize_split(split, days_n)
    eq_n = _normalize_equipment(equipment)
    weak_n = _normalize_weak_points(weak_points)

    by_primary = _by_primary(eq_n)

    rotation = SESSION_TEMPLATES[split_n]
    sessions: list[dict] = []
    for i in range(days_n):
        name, focus = rotation[i % len(rotation)]
        # When we cycle past the end of the base rotation, suffix the name so
        # two Push sessions don't share a name verbatim.
        if i >= len(rotation):
            name = f"{name} ({i // len(rotation) + 1})"
        sessions.append(_build_session(
            name=name, focus_muscles=focus,
            goal=goal_n, experience=exp_n,
            by_primary=by_primary, weak_points=weak_n,
        ))

    volume = _weekly_volume(sessions)
    rationale = _rationale(goal_n, exp_n, split_n, days_n, volume)

    program_name = SPLITS[split_n]["label"]
    if days_n != SPLITS[split_n]["days_options"][0]:
        program_name = f"{program_name} ({days_n} d/wk)"

    return {
        "name":          program_name,
        "goal":          goal_n,
        "days_per_week": days_n,
        "split":         split_n,
        "experience":    exp_n,
        "equipment":     list(eq_n),
        "weak_points":   weak_n,
        "rationale":     rationale,
        "weekly_volume": volume,
        "sessions":      sessions,
    }


def serialize_sessions_for_db(sessions: list[dict]) -> list[dict]:
    """Drop the planner-only keys (`primary`, `equipment`) when writing
    sessions to the DB. The user-facing shape is just the prescription."""
    out = []
    for s in sessions:
        out.append({
            "name":      s["name"],
            "focus":     s["focus"],
            "exercises": [
                {
                    "canonical":    ex["canonical"],
                    "sets":         ex["sets"],
                    "reps":         ex["reps"],
                    "rir":          ex["rir"],
                    "rest_seconds": ex["rest_seconds"],
                    "notes":        ex.get("notes", ""),
                }
                for ex in s["exercises"]
            ],
        })
    return out
