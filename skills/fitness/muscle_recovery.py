"""
Muscle-group recovery model — the engine behind the Coach page "recovery board".

Given a user's recently logged training (strength + cardio) and their most recent
wearable snapshot, this derives a per-muscle-group readiness status:

    ready  →  recovering  →  strained  →  just_hit

The model is intentionally a transparent, deterministic heuristic (no ML, no IO):

  1. Each logged set produces a *stimulus* = normalized volume x effort (RIR),
     distributed across the muscles it works via an involvement map (primary mover
     1.0, synergists 0.3-0.6, stabilizers ~0.2). Exercises not in the involvement
     map fall back to the catalog's `primary` muscle at 1.0 — so coverage is
     graceful, never all-or-nothing.

  2. Cardio adds a small *systemic* (full-body) load plus a larger *leg-weighted*
     load, both scaled by duration and an avg-HR zone multiplier. A Zone 4-5 run
     meaningfully fatigues the legs and bumps the whole body; an easy walk barely
     registers. (This is the user's explicit ask: walks/cardio have a minimal
     full-body effect that grows with intensity.)

  3. Each stimulus *decays* exponentially toward zero on a muscle-specific time
     constant — big movers (back, quads, hams) take ~3 days, small/fast muscles
     (biceps, calves, forearms, abs) ~1.5-2 days.

  4. A whole-body *recovery factor* from the wearable (WHOOP/Apple Health
     recovery score + sleep) scales residual fatigue up when the user is
     under-recovered, so a poor night lingers in the numbers.

The output is a JSON-able dict (see `compute_recovery`) consumed by
`/api/v1/recovery` and rendered as the iOS recovery board.

Pure functions only — feed it plain dicts. The API layer adapts ORM rows.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from skills.fitness.exercise_catalog import canonicalize


# ── Muscle metadata ───────────────────────────────────────────────────────────
# group: "major"|"minor" controls iOS chip emphasis (major = larger).
# tau_hours: time constant of the exponential recovery model — a reference hard
#   session's residual fatigue falls to ~37% after `tau`, ~13% after 2*tau, <5%
#   after 3*tau. Calibrated so a hard session crosses back to "ready" inside the
#   muscle's EVIDENCE-BASED recovery window (not an arbitrary curve):
#     • small muscles  (delts, arms, calves, core, traps): ~24-48 h
#     • large muscles  (chest, back, glutes):              ~48-72 h
#     • eccentric legs (quads, hamstrings):                ~72-96 h (severe DOMS
#       from heavy eccentric work can run longer, 4-7 days)
#   This is why a muscle hit 3 days ago must read MORE recovered than one hit
#   yesterday — the previous taus (e.g. shoulders 54 h) stretched small muscles
#   ~2-3x too long and inverted that. Sources:
#     - MacDougall et al. 1995, Can J Appl Physiol — MPS peaks ~24 h, ~baseline by
#       36 h, elevated 24-48 h after heavy resistance exercise.
#     - Schoenfeld et al. 2016, Sports Med (meta-analysis) — train each muscle
#       >=2x/week, i.e. ~48-72 h spacing per muscle.
#     - Eccentric-damage / DOMS literature — force/soreness from heavy eccentric
#       (large-muscle) work peaks 24-72 h and can take 4+ days to fully resolve.
# Chest and back split into sub-muscles so the board can advise around regional
# fatigue (upper-chest after incline vs lower-chest after decline; lats after
# vertical pulls vs mid-back after rows vs lower-back after deadlifts). Lower
# back has the slowest tau in the body — heavy spinal-erector load lingers.
# `obliques` and `cardio` are NOT board muscles: obliques fold into abs, and a
# cardio entry is decomposed into systemic + leg load (it has no muscle of its
# own). Order here is the canonical board order.
# Sub-muscle taxonomy. Chest/back were split previously; this expands the
# remaining compound groups into their anatomical heads/regions so the board can
# show, e.g., that side delts are fried while rear delts are fresh:
#   shoulders → front / side / rear delts
#   triceps   → long / lateral / medial heads
#   calves    → gastrocnemius / soleus
#   traps     → upper / mid / lower
#   glutes    → maximus / medius
# Quads + hamstrings are intentionally NOT split (their heads almost always
# train together; the extra rows would be noise). Legacy single ids route to a
# sensible default head via _PRIMARY_ALIAS, so any unedited involvement entry or
# catalog primary still attributes somewhere.
MUSCLES: dict[str, dict] = {
    "chest_upper":   {"name": "Upper Chest",      "group": "major", "tau_hours": 32.0},
    "chest_mid":     {"name": "Mid Chest",        "group": "major", "tau_hours": 34.0},
    "chest_lower":   {"name": "Lower Chest",      "group": "major", "tau_hours": 32.0},
    "lats":          {"name": "Lats",             "group": "major", "tau_hours": 34.0},
    "mid_back":      {"name": "Mid Back",         "group": "major", "tau_hours": 36.0},
    "lower_back":    {"name": "Lower Back",       "group": "major", "tau_hours": 48.0},
    "delts_front":   {"name": "Front Delt",       "group": "major", "tau_hours": 28.0},
    "delts_side":    {"name": "Side Delt",        "group": "major", "tau_hours": 26.0},
    "delts_rear":    {"name": "Rear Delt",        "group": "major", "tau_hours": 24.0},
    "quads":         {"name": "Quads",            "group": "major", "tau_hours": 40.0},
    "hamstrings":    {"name": "Hamstrings",       "group": "major", "tau_hours": 40.0},
    "glutes_max":    {"name": "Glute Max",        "group": "major", "tau_hours": 34.0},
    "glutes_med":    {"name": "Glute Med",        "group": "major", "tau_hours": 30.0},
    "biceps_long":   {"name": "Biceps (Long)",    "group": "minor", "tau_hours": 24.0},
    "biceps_short":  {"name": "Biceps (Short)",   "group": "minor", "tau_hours": 24.0},
    "brachialis":    {"name": "Brachialis",       "group": "minor", "tau_hours": 26.0},
    "triceps_long":  {"name": "Triceps (Long)",   "group": "minor", "tau_hours": 26.0},
    "triceps_lateral": {"name": "Triceps (Lateral)", "group": "minor", "tau_hours": 26.0},
    "triceps_medial": {"name": "Triceps (Medial)", "group": "minor", "tau_hours": 24.0},
    "forearms":      {"name": "Forearms",         "group": "minor", "tau_hours": 22.0},
    "traps_upper":   {"name": "Upper Traps",      "group": "minor", "tau_hours": 26.0},
    "traps_mid":     {"name": "Mid Traps",        "group": "minor", "tau_hours": 28.0},
    "traps_lower":   {"name": "Lower Traps",      "group": "minor", "tau_hours": 28.0},
    "abs_upper":     {"name": "Upper Abs",        "group": "minor", "tau_hours": 22.0},
    "abs_lower":     {"name": "Lower Abs",        "group": "minor", "tau_hours": 22.0},
    "obliques":      {"name": "Obliques",         "group": "minor", "tau_hours": 24.0},
    "calves_gastroc": {"name": "Calf (Gastroc)",  "group": "minor", "tau_hours": 26.0},
    "calves_soleus": {"name": "Calf (Soleus)",    "group": "minor", "tau_hours": 30.0},
}

# Catalog primaries that aren't their own board muscle map here.
# Legacy plain "chest"/"back" route to a sensible default sub-muscle so unmapped
# rows still attribute somewhere; specific sub-muscle ids in INVOLVEMENT below
# override this for known compounds.
_PRIMARY_ALIAS = {
    "chest": "chest_mid",
    "back": "lats",
    # generic core → upper abs; generic curls → short head (both heads work,
    # short is the safe default and long/short isolations override below).
    "abs":    "abs_upper",
    "biceps": "biceps_short",
    # Legacy single-muscle ids → default head. The default is chosen for where
    # the bulk of *secondary* involvement lands: pressing hits the FRONT delt
    # and LATERAL/medial triceps; squats/hinges hit glute MAX; rows/shrugs and
    # deadlift traps read as MID/upper traps; cardio + incidental calf work is
    # gastroc. Head-specific isolations (lateral raise → side delt, seated calf
    # → soleus, etc.) are mapped explicitly in INVOLVEMENT below and override this.
    "shoulders": "delts_front",
    "triceps":   "triceps_lateral",
    "glutes":    "glutes_max",
    "traps":     "traps_mid",
    "calves":    "calves_gastroc",
}


# ── Involvement map ───────────────────────────────────────────────────────────
# canonical exercise name -> {muscle: coefficient}. Primary mover 1.0, synergists
# 0.3-0.6, stabilizers ~0.2. Only the compounds where secondary involvement
# matters are listed; everything else falls back to its catalog `primary` at 1.0.
INVOLVEMENT: dict[str, dict[str, float]] = {
    # ── chest presses (sub-muscle split: upper / mid / lower) ────────────────
    "Bench Press":            {"chest_mid": 1.0, "chest_upper": 0.3, "chest_lower": 0.4, "triceps": 0.4, "shoulders": 0.3},
    "Incline Bench Press":    {"chest_upper": 1.0, "chest_mid": 0.4, "shoulders": 0.4, "triceps": 0.35},
    "Decline Bench Press":    {"chest_lower": 1.0, "chest_mid": 0.3, "triceps": 0.4},
    "Flat Dumbbell Press":    {"chest_mid": 1.0, "chest_upper": 0.3, "chest_lower": 0.4, "triceps": 0.35, "shoulders": 0.3},
    "Incline Dumbbell Press": {"chest_upper": 1.0, "chest_mid": 0.4, "shoulders": 0.4, "triceps": 0.3},
    "Chest Fly":              {"chest_mid": 1.0, "chest_upper": 0.3, "chest_lower": 0.3},
    "Cable Fly":              {"chest_mid": 1.0, "chest_upper": 0.3, "chest_lower": 0.3},
    "High-to-Low Fly":        {"chest_lower": 1.0, "chest_mid": 0.4},
    "Low-to-High Fly":        {"chest_upper": 1.0, "chest_mid": 0.4},
    "Push-Up":                {"chest_mid": 1.0, "chest_upper": 0.2, "chest_lower": 0.3, "triceps": 0.4, "shoulders": 0.3, "abs": 0.2},
    "Close-Grip Bench Press": {"triceps_lateral": 1.0, "triceps_medial": 0.6, "triceps_long": 0.4, "chest_mid": 0.5, "shoulders": 0.25},
    "Dip":                    {"triceps_lateral": 1.0, "triceps_medial": 0.5, "chest_lower": 0.6, "shoulders": 0.3},
    "Machine Chest Press":    {"chest_mid": 1.0, "chest_upper": 0.3, "chest_lower": 0.3, "triceps": 0.35, "shoulders": 0.25},
    "Floor Press":            {"chest_mid": 1.0, "chest_lower": 0.3, "triceps": 0.5, "shoulders": 0.2},
    "Landmine Press":         {"chest_upper": 1.0, "shoulders": 0.6, "triceps": 0.3, "abs": 0.2},
    "Diamond Push-Up":        {"triceps_lateral": 1.0, "triceps_medial": 0.5, "chest_mid": 0.6, "shoulders": 0.3, "abs": 0.2},
    # ── shoulder presses / raises ───────────────────────────────────────────
    # presses are front-delt dominant, with real side-delt involvement
    "Overhead Press":           {"delts_front": 1.0, "delts_side": 0.5, "triceps": 0.45, "traps_upper": 0.3, "abs": 0.2},
    "Dumbbell Shoulder Press":  {"delts_front": 1.0, "delts_side": 0.5, "triceps": 0.4, "traps_upper": 0.25},
    "Arnold Press":             {"delts_front": 1.0, "delts_side": 0.6, "triceps": 0.4, "traps_upper": 0.25},
    "Push Press":               {"delts_front": 1.0, "delts_side": 0.4, "triceps": 0.5, "traps_upper": 0.3, "quads": 0.3, "abs": 0.2},
    "Front Raise":              {"delts_front": 1.0},
    # side-delt isolations
    "Dumbbell Lateral Raise":   {"delts_side": 1.0},
    "Cable Lateral Raise":      {"delts_side": 1.0},
    "Upright Row":              {"delts_side": 1.0, "traps_upper": 0.5, "biceps": 0.2},
    # rear-delt isolations
    "Rear Delt Fly":            {"delts_rear": 1.0, "traps_mid": 0.3},
    "Machine Rear Delt Fly":    {"delts_rear": 1.0, "traps_mid": 0.35},
    "Face Pull":                {"delts_rear": 1.0, "traps_mid": 0.4},
    # ── back pulls (sub-muscle split: lats / mid_back / lower_back) ─────────
    "Deadlift":              {"lower_back": 1.0, "mid_back": 0.6, "lats": 0.4, "glutes": 0.6, "hamstrings": 0.6, "traps": 0.4, "forearms": 0.3, "quads": 0.3},
    "Pull-Up":               {"lats": 1.0, "mid_back": 0.4, "biceps": 0.5, "forearms": 0.3},
    "Lat Pulldown":          {"lats": 1.0, "mid_back": 0.3, "biceps": 0.45, "forearms": 0.25},
    "Single-Arm Pulldown":   {"lats": 1.0, "mid_back": 0.3, "biceps": 0.4, "forearms": 0.25},
    "Straight-Arm Pulldown": {"lats": 1.0, "triceps": 0.2},
    "Barbell Row":           {"mid_back": 1.0, "lats": 0.5, "lower_back": 0.3, "biceps": 0.4, "forearms": 0.3},
    "Chest-Supported Row":   {"mid_back": 1.0, "lats": 0.4, "biceps": 0.35, "traps": 0.3},
    "Seated Cable Row":      {"mid_back": 1.0, "lats": 0.5, "biceps": 0.35, "forearms": 0.2},
    "Dumbbell Row":          {"mid_back": 1.0, "lats": 0.6, "biceps": 0.4, "forearms": 0.25},
    "Pendlay Row":           {"mid_back": 1.0, "lats": 0.5, "lower_back": 0.4, "biceps": 0.4, "forearms": 0.3},
    "T-Bar Row":             {"mid_back": 1.0, "lats": 0.55, "lower_back": 0.3, "biceps": 0.4, "forearms": 0.3},
    "Rack Pull":             {"lower_back": 1.0, "mid_back": 0.6, "traps": 0.5, "lats": 0.3, "glutes": 0.4, "forearms": 0.4},
    "Hyperextension":        {"lower_back": 1.0, "glutes": 0.5, "hamstrings": 0.4},
    "Reverse Hyperextension": {"lower_back": 1.0, "glutes": 0.6, "hamstrings": 0.4},
    # ── arms (biceps/triceps/forearms) ──────────────────────────────────────
    # curls hit both heads; grip/angle biases one. preacher/concentration → short
    # head; incline (shoulder extended) → long head; hammer/reverse → brachialis.
    "Barbell Curl":  {"biceps_long": 1.0, "biceps_short": 0.85, "forearms": 0.4},
    "Dumbbell Curl": {"biceps_long": 0.95, "biceps_short": 0.95, "forearms": 0.35},
    "Hammer Curl":   {"brachialis": 1.0, "biceps_long": 0.6, "forearms": 0.5},
    "Preacher Curl": {"biceps_short": 1.0, "biceps_long": 0.5, "forearms": 0.3},
    "Reverse Curl":  {"forearms": 1.0, "brachialis": 0.6, "biceps_short": 0.3},
    "Shrug":         {"traps_upper": 1.0, "forearms": 0.3},
    "Incline Dumbbell Curl": {"biceps_long": 1.0, "biceps_short": 0.5, "forearms": 0.3},
    "Concentration Curl":   {"biceps_short": 1.0, "biceps_long": 0.4, "forearms": 0.3},
    "EZ-Bar Curl":          {"biceps_short": 1.0, "biceps_long": 0.7, "forearms": 0.4},
    "Zottman Curl":         {"biceps_long": 0.8, "biceps_short": 0.7, "brachialis": 0.6, "forearms": 0.6},
    # lying/overhead extensions bias the LONG head; pushdowns the lateral/medial
    "Skull Crusher":             {"triceps_long": 1.0, "triceps_lateral": 0.5, "triceps_medial": 0.4, "forearms": 0.2},
    "Overhead Tricep Extension": {"triceps_long": 1.0, "triceps_medial": 0.4, "shoulders": 0.2},
    "Overhead Cable Extension":  {"triceps_long": 1.0, "triceps_medial": 0.4},
    "Cable Pushdown":            {"triceps_lateral": 1.0, "triceps_medial": 0.5, "triceps_long": 0.3},
    "Bench Dip":                 {"triceps_lateral": 1.0, "triceps_medial": 0.5, "chest_lower": 0.3, "shoulders": 0.25},
    "Wrist Curl":         {"forearms": 1.0},
    "Reverse Wrist Curl": {"forearms": 1.0},
    # ── traps / carries ─────────────────────────────────────────────────────
    "Farmer's Carry": {"traps_upper": 1.0, "forearms": 0.8, "abs": 0.4, "glutes_max": 0.3, "quads": 0.2},
    # ── legs (quads / hamstrings / glutes / calves) ─────────────────────────
    "Back Squat":            {"quads": 1.0, "glutes": 0.6, "hamstrings": 0.4, "abs": 0.3, "lower_back": 0.3},
    "Front Squat":           {"quads": 1.0, "glutes": 0.5, "abs": 0.4, "lower_back": 0.3},
    "Leg Press":             {"quads": 1.0, "glutes": 0.5, "hamstrings": 0.3},
    # single-leg work recruits glute MED (frontal-plane stability) on top of max
    "Bulgarian Split Squat": {"quads": 1.0, "glutes_max": 0.7, "glutes_med": 0.35, "hamstrings": 0.3},
    "Lunge":                 {"quads": 1.0, "glutes_max": 0.6, "glutes_med": 0.3, "hamstrings": 0.3},
    "Hack Squat":            {"quads": 1.0, "glutes_max": 0.5, "hamstrings": 0.3},
    "Step-Up":               {"quads": 1.0, "glutes_max": 0.6, "glutes_med": 0.3, "hamstrings": 0.3, "calves_gastroc": 0.2},
    "Box Squat":             {"quads": 1.0, "glutes": 0.7, "hamstrings": 0.4, "lower_back": 0.3},
    "Romanian Deadlift":     {"hamstrings": 1.0, "glutes": 0.6, "lower_back": 0.4, "forearms": 0.25},
    "Good Morning":          {"hamstrings": 1.0, "glutes": 0.5, "lower_back": 0.4},
    "Nordic Curl":           {"hamstrings": 1.0, "glutes": 0.3, "calves": 0.2},
    "Seated Leg Curl":       {"hamstrings": 1.0},
    "Hip Thrust":            {"glutes_max": 1.0, "glutes_med": 0.3, "hamstrings": 0.4},
    "Glute Bridge":          {"glutes_max": 1.0, "glutes_med": 0.25, "hamstrings": 0.4, "lower_back": 0.2},
    "Glute Kickback":        {"glutes_max": 1.0, "glutes_med": 0.3, "hamstrings": 0.2},
    # seated calf (bent knee) hits the SOLEUS; standing (straight knee) the GASTROC
    "Seated Calf Raise":     {"calves_soleus": 1.0, "calves_gastroc": 0.3},
    "Standing Calf Raise":   {"calves_gastroc": 1.0, "calves_soleus": 0.4},
    "Donkey Calf Raise":     {"calves_gastroc": 1.0, "calves_soleus": 0.3},
    "Calf Raise":            {"calves_gastroc": 1.0, "calves_soleus": 0.4},
    # ── core ────────────────────────────────────────────────────────────────
    # leg raises bias LOWER abs; anti-rotation/lateral work is OBLIQUES; planks
    # are whole-core isometric.
    "Hanging Leg Raise": {"abs_lower": 1.0, "abs_upper": 0.4, "forearms": 0.2},
    "Plank":             {"abs_upper": 0.7, "abs_lower": 0.5, "obliques": 0.4, "shoulders": 0.2},
    "Dead Bug":          {"abs_lower": 1.0, "abs_upper": 0.5},
    "Pallof Press":      {"obliques": 1.0, "abs_upper": 0.4},
    "Side Plank":        {"obliques": 1.0, "abs_upper": 0.3, "shoulders": 0.2},
    # ── cardio finishers / conditioning ─────────────────────────────────────
    "Battle Ropes": {"shoulders": 1.0, "abs": 0.4, "forearms": 0.5, "biceps": 0.2, "traps": 0.3},
    "Burpees":      {"abs": 1.0, "shoulders": 0.4, "quads": 0.5, "chest_mid": 0.3, "triceps": 0.3, "glutes": 0.3},
    "Box Jumps":    {"quads": 1.0, "glutes": 0.7, "calves": 0.5, "hamstrings": 0.3},
}

# ── Cardio leg-involvement by modality ────────────────────────────────────────
# Each cardio canonical maps to the muscles its leg/limb load lands on. Systemic
# load (every muscle) is added separately. Default = running profile.
# NOTE: cardio loads bypass _PRIMARY_ALIAS (they're applied directly against the
# MUSCLES set), so these MUST use the new head ids. Running-type cardio loads the
# gastroc; glute work is glute-max dominant.
_CARDIO_DEFAULT = {"calves_gastroc": 0.6, "quads": 0.5, "hamstrings": 0.4, "glutes_max": 0.35}
CARDIO_INVOLVEMENT: dict[str, dict[str, float]] = {
    "Running":        _CARDIO_DEFAULT,
    "Treadmill":      _CARDIO_DEFAULT,
    "Stair Climber":  {"quads": 0.7, "glutes_max": 0.6, "calves_gastroc": 0.5, "hamstrings": 0.35},
    "Walking":        {"calves_gastroc": 0.4, "quads": 0.25, "glutes_max": 0.2, "hamstrings": 0.15},
    "Stationary Bike": {"quads": 0.6, "hamstrings": 0.3, "glutes_max": 0.3, "calves_gastroc": 0.2},
    "Elliptical":     {"quads": 0.4, "glutes_max": 0.35, "hamstrings": 0.3, "calves_gastroc": 0.3},
    "Rowing":         {"quads": 0.4, "hamstrings": 0.3, "mid_back": 0.5, "glutes_max": 0.3, "biceps_short": 0.2},
}


# ── Tunable constants ─────────────────────────────────────────────────────────
VOLUME_REF = 3000.0      # kg*reps for a "solid" working session (~4x8 @ ~94kg) -> stimulus 1.0
SESSION_CAP = 1.4        # cap a single entry's base stimulus before effort
NOMINAL_BW_LOAD = 50.0   # kg stand-in load for bodyweight moves (push-ups, dips, pull-ups)
LOOKBACK_HOURS = 10 * 24

CARDIO_REF_STIM = 0.55   # leg/limb stimulus for a reference (40 min, Zone 3-4) cardio bout
CARDIO_DURATION_REF = 40.0
SYSTEMIC_COEF = 0.13     # share of cardio load applied to EVERY muscle (full-body effect)
DEFAULT_MAX_HR_AGE = 30  # used when the user's age is unknown

FATIGUE_CLAMP = 1.2
# status thresholds on final fatigue F
T_JUST_HIT = 0.78
T_STRAINED = 0.50
T_RECOVERING = 0.22
RECENT_HIT_HOURS = 16    # trained this recently + non-trivial fatigue -> just_hit
MIN_ATTRIBUTION = 0.03   # min direct residual to count as "trained this muscle"


def _effort_from_rir(rir: Optional[int]) -> float:
    """Lower reps-in-reserve = closer to failure = more fatigue per unit volume."""
    if rir is None:
        return 0.8
    if rir <= 0:
        return 1.0
    if rir <= 2:
        return 0.85
    return 0.7


def _parse_csv_floats(s) -> list[float]:
    if not s:
        return []
    out = []
    for part in str(s).replace("/", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _strength_volume(entry: dict) -> float:
    """kg*reps for a strength entry, honoring per-set `weights`/`reps` CSVs."""
    sets = entry.get("sets") or 1
    try:
        sets = int(sets)
    except (TypeError, ValueError):
        sets = 1
    sets = max(sets, 1)

    reps_list = _parse_csv_floats(entry.get("reps"))
    weights_list = _parse_csv_floats(entry.get("weights"))
    single_w = entry.get("weight")
    try:
        single_w = float(single_w) if single_w is not None else 0.0
    except (TypeError, ValueError):
        single_w = 0.0

    # Per-set path: pair reps[i] with weights[i] (fall back to the single weight).
    n = max(len(reps_list), len(weights_list), sets)
    avg_reps = (sum(reps_list) / len(reps_list)) if reps_list else 10.0
    total = 0.0
    for i in range(n):
        r = reps_list[i] if i < len(reps_list) else avg_reps
        if i < len(weights_list):
            w = weights_list[i]
        elif single_w > 0:
            w = single_w
        else:
            w = NOMINAL_BW_LOAD
        if w <= 0:
            w = NOMINAL_BW_LOAD
        total += r * w
    return total


def _hr_zone_multiplier(avg_hr: Optional[int], age: Optional[int],
                        cardio_name: str) -> float:
    """Intensity multiplier from avg HR vs estimated max. Zone 3+ ramps up.
    When HR is missing, infer from modality (walks easy, machines moderate)."""
    if not avg_hr or avg_hr <= 0:
        return 0.3 if cardio_name == "Walking" else 0.6
    max_hr = 220.0 - float(age or DEFAULT_MAX_HR_AGE)
    frac = avg_hr / max_hr if max_hr > 0 else 0.7
    if frac < 0.60:   # Zone 1-2 — easy
        return 0.3
    if frac < 0.70:   # Zone 2-3 — steady
        return 0.6
    if frac < 0.80:   # Zone 3-4 — tempo
        return 1.0
    if frac < 0.90:   # Zone 4 — threshold
        return 1.3
    return 1.5        # Zone 5 — max


def _cardio_loads(entry: dict, canonical: str,
                  age: Optional[int]) -> tuple[dict[str, float], float]:
    """Decompose a cardio entry into (targeted leg/limb load per muscle,
    systemic full-body load). Both scale with duration and HR-zone intensity.

    The systemic load is returned separately because it contributes to fatigue
    (the user's "minimal full-body effect, bigger at Zone 3+") but must NOT count
    as having *trained* a muscle — otherwise an easy jog would flip Chest to
    "just hit". Only the targeted leg load registers as a movement / last-hit."""
    duration = entry.get("duration_minutes") or 0.0
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        duration = 30.0  # assume a half-hour bout when unlogged

    zmult = _hr_zone_multiplier(entry.get("avg_hr"), age, canonical)
    dur_factor = min(duration / CARDIO_DURATION_REF, 1.5)
    load = CARDIO_REF_STIM * dur_factor * zmult

    profile = CARDIO_INVOLVEMENT.get(canonical, _CARDIO_DEFAULT)
    targeted: dict[str, float] = {m: 0.0 for m in MUSCLES}
    for muscle, coeff in profile.items():
        if muscle in targeted:
            targeted[muscle] += load * coeff
    systemic = load * SYSTEMIC_COEF
    return targeted, systemic


def _is_cardio(entry: dict, catalog_entry: Optional[dict]) -> bool:
    if entry.get("cardio_type"):
        return True
    if catalog_entry and catalog_entry.get("primary") == "cardio":
        return True
    # duration but no resistance signal -> treat as cardio
    if entry.get("duration_minutes") and not (entry.get("sets") or entry.get("weight")):
        return True
    return False


def _entry_muscle_stimulus(entry: dict,
                           age: Optional[int]) -> tuple[dict[str, float], float, bool, str]:
    """Return (targeted muscle->stimulus, systemic stimulus, is_cardio, display_name).

    `targeted` is direct work on a muscle (counts as training it). `systemic` is
    a whole-body load from cardio that adds fatigue everywhere but trains nothing.
    """
    raw_name = entry.get("name") or entry.get("exercise_name") or "Workout"
    canonical, catalog_entry = canonicalize(raw_name)
    cardio = _is_cardio(entry, catalog_entry)

    if cardio:
        targeted, systemic = _cardio_loads(entry, canonical, age)
        return targeted, systemic, True, canonical

    base = min(_strength_volume(entry) / VOLUME_REF, SESSION_CAP)
    stim = base * _effort_from_rir(entry.get("rir"))

    involvement = INVOLVEMENT.get(canonical)
    if not involvement:
        primary = (catalog_entry or {}).get("primary")
        primary = _PRIMARY_ALIAS.get(primary, primary)
        if primary in MUSCLES:
            involvement = {primary: 1.0}
        else:
            involvement = {}  # unknown, non-cardio -> no muscle attribution

    out = {m: 0.0 for m in MUSCLES}
    for muscle, coeff in involvement.items():
        muscle = _PRIMARY_ALIAS.get(muscle, muscle)
        if muscle in out:
            out[muscle] += stim * coeff
    return out, 0.0, False, canonical


def _whole_body_factor(snapshot: Optional[dict]) -> float:
    """>=1.0 multiplier on residual fatigue. Under-recovery / short sleep makes
    yesterday's training linger. Neutral (1.0) when no wearable data."""
    if not snapshot:
        return 1.0
    factor = 1.0
    rec = snapshot.get("recovery_score")
    if rec is not None:
        try:
            factor += (1.0 - float(rec) / 100.0) * 0.3
        except (TypeError, ValueError):
            pass
    sleep = snapshot.get("sleep_hours")
    if sleep is not None:
        try:
            if float(sleep) < 6.0:
                factor += 0.05
        except (TypeError, ValueError):
            pass
    return max(1.0, min(factor, 1.35))


def _status_for(fatigue: float, hours_since: Optional[float]) -> str:
    if hours_since is not None and hours_since < RECENT_HIT_HOURS and fatigue >= 0.5:
        return "just_hit"
    if fatigue >= T_JUST_HIT:
        return "just_hit"
    if fatigue >= T_STRAINED:
        return "strained"
    if fatigue >= T_RECOVERING:
        return "recovering"
    return "ready"


def _entry_time(entry: dict) -> Optional[datetime]:
    t = entry.get("occurred_at") or entry.get("timestamp")
    if isinstance(t, datetime):
        return t
    return None


def _label_for(hours: Optional[float]) -> str:
    if hours is None:
        return "—"
    if hours < RECENT_HIT_HOURS:
        return "just hit"
    days = round(hours / 24.0)
    if days <= 0:
        return "today"
    if days == 1:
        return "1d ago"
    return f"{days}d ago"


def compute_recovery(entries: list[dict],
                     snapshot: Optional[dict],
                     profile: Optional[dict],
                     now: datetime) -> dict:
    """Build the recovery-board payload.

    entries:  list of dicts with keys name/exercise_name, sets, reps, weight,
              weights, rir, duration_minutes, cardio_type, avg_hr, occurred_at,
              timestamp. (timestamp/occurred_at are naive UTC datetimes.)
    snapshot: most recent wearable dict (recovery_score, sleep_hours, strain) or None.
    profile:  {age, ...} or None.
    now:      naive UTC datetime to decay against.
    """
    age = (profile or {}).get("age")
    wb_factor = _whole_body_factor(snapshot)

    # accumulator: residual fatigue per muscle + contributing movements
    fatigue: dict[str, float] = {m: 0.0 for m in MUSCLES}
    last_hit_hours: dict[str, Optional[float]] = {m: None for m in MUSCLES}
    # movements: muscle -> {key: {name, hours, sets, is_cardio, contribution}}
    movements: dict[str, dict[str, dict]] = {m: {} for m in MUSCLES}

    for entry in entries:
        t = _entry_time(entry)
        if t is None:
            continue
        dt_hours = (now - t).total_seconds() / 3600.0
        if dt_hours < 0:
            dt_hours = 0.0
        if dt_hours > LOOKBACK_HOURS:
            continue

        targeted, systemic, is_cardio, disp = _entry_muscle_stimulus(entry, age)
        sets = entry.get("sets") or (1 if is_cardio else 0)

        for muscle in MUSCLES:
            decay = math.exp(-dt_hours / MUSCLES[muscle]["tau_hours"])
            t_stim = targeted.get(muscle, 0.0)
            # both targeted and systemic load count toward fatigue...
            total_residual = (t_stim + systemic) * decay * wb_factor
            if total_residual > 0.001:
                fatigue[muscle] += total_residual

            # ...but only DIRECT work registers as having trained the muscle
            # (last-hit + movement attribution). Systemic cardio load does not.
            t_residual = t_stim * decay * wb_factor
            if t_residual <= MIN_ATTRIBUTION:
                continue
            if last_hit_hours[muscle] is None or dt_hours < last_hit_hours[muscle]:
                last_hit_hours[muscle] = dt_hours
            agg = movements[muscle].setdefault(
                disp, {"name": disp, "hours": dt_hours, "sets": 0,
                       "is_cardio": is_cardio, "contribution": 0.0})
            agg["contribution"] += t_residual
            agg["hours"] = min(agg["hours"], dt_hours)
            try:
                agg["sets"] += int(sets or 0)
            except (TypeError, ValueError):
                pass

    muscles_out = []
    for mid, meta in MUSCLES.items():
        f = min(fatigue[mid], FATIGUE_CLAMP)
        hours = last_hit_hours[mid]
        status = _status_for(f, hours)
        movs = sorted(movements[mid].values(),
                      key=lambda d: d["contribution"], reverse=True)[:5]
        muscles_out.append({
            "id": mid,
            "name": meta["name"],
            "group": meta["group"],
            "status": status,
            "fatigue": round(f, 3),
            "recovery_pct": int(round(100 * max(0.0, min(1.0, 1.0 - f)))),
            "last_trained_hours": round(hours, 1) if hours is not None else None,
            "last_trained_label": _label_for(hours),
            "movements": [{
                "name": m["name"],
                "sets": m["sets"],
                "is_cardio": m["is_cardio"],
                "label": _label_for(m["hours"]),
                "contribution": round(m["contribution"], 3),
            } for m in movs],
        })

    ready = [m["id"] for m in muscles_out if m["status"] == "ready"]
    not_ready = [m for m in muscles_out if m["status"] != "ready"]
    # worst-hit major muscles drive the headline
    not_ready_sorted = sorted(not_ready, key=lambda m: m["fatigue"], reverse=True)

    return {
        "v": 1,
        "generated_at": now.replace(microsecond=0).isoformat() + "Z",
        "whole_body": {
            "recovery_score": (snapshot or {}).get("recovery_score"),
            "strain": (snapshot or {}).get("strain"),
            "sleep_hours": (snapshot or {}).get("sleep_hours"),
            "factor": round(wb_factor, 3),
        },
        "muscles": muscles_out,
        "summary": {
            "ready": ready,
            "recovering": [m["id"] for m in not_ready_sorted],
            "headline": _headline(not_ready_sorted, ready),
        },
    }


def _headline(not_ready_sorted: list[dict], ready: list[str]) -> str:
    """One-line coaching read of the board."""
    def nm(mid):
        return MUSCLES[mid]["name"]

    if not not_ready_sorted:
        return "Everything's recovered — you're clear to train anything."

    worst = not_ready_sorted[0]
    fresh = [nm(r) for r in ready[:2]]
    worst_name = worst["name"]

    if worst["status"] in ("just_hit", "strained"):
        if fresh:
            tail = " and ".join(fresh)
            return f"{worst_name} still need rest — {tail} are ready to go."
        return f"{worst_name} are freshly worked — give them a day before hitting them again."
    # only light recovering left
    if fresh:
        return f"Mostly recovered — {', '.join(fresh)} are fully fresh."
    return "Everything's on the mend — keep it light or rest today."
