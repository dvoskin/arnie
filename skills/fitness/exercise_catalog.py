"""
Canonical exercise registry. Phase 2 of the live-coaching reinforcements.

Solves three problems at once:
  1. The "what would you like to call this?" UX failure — Arnie stops asking
     users to name their movements mid-set.
  2. PR / history fragmentation — "Crunches (Cable/Machine)" and "Cable Crunch"
     no longer count as two different exercises.
  3. Phase 1 dedup's normalize-by-whitespace fallback was too narrow — the
     canonical name becomes the dedup key, so two distinct user phrasings of
     the same movement collide.

Design: static Python list, forward-only (no backfill of existing rows).
Exact-alias lookup with light normalization (strip hyphens, trailing 's', case,
whitespace). No fuzzy matching — explicit aliases beat clever guesses. Adding
a new alias is one line; mis-mapping is expensive.

When a user-typed name doesn't resolve, canonicalize() returns it unchanged.
The Phase 1 dedup helper still works (whitespace+case normalization).
Coverage is graceful, not all-or-nothing.

Fields per entry:
  canonical     str         — what we store in exercise_entries.exercise_name
  aliases       list[str]   — lowercase strings that resolve to canonical
  primary       str         — main muscle group (used by Phase 3 ordering)
  equipment     str         — barbell|dumbbell|cable|machine|bodyweight|kettlebell|cardio
  rest_seconds  (int,int)   — typical rest range for live pacing cues
  category      str         — main|accessory|cardio|finisher|mobility|core
"""
from __future__ import annotations

from typing import Optional


EXERCISES: list[dict] = [
    # ── CHEST ────────────────────────────────────────────────────────────────
    # Primary names a SUB-MUSCLE (chest_upper / chest_mid / chest_lower) so the
    # board can show regional readiness — an incline-only day leaves mid/lower
    # chest fresh, etc. Plain "chest" routes via _PRIMARY_ALIAS → chest_mid.
    {"canonical": "Bench Press",
     "aliases": ["bench", "barbell bench", "barbell bench press", "flat bench",
                 "flat barbell bench"],
     "primary": "chest_mid", "equipment": "barbell",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Incline Bench Press",
     "aliases": ["incline bench", "incline barbell bench", "incline press",
                 "incline barbell press"],
     "primary": "chest_upper", "equipment": "barbell",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Decline Bench Press",
     "aliases": ["decline bench", "decline barbell bench", "decline press"],
     "primary": "chest_lower", "equipment": "barbell",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Flat Dumbbell Press",
     "aliases": ["flat db press", "dumbbell bench", "db bench",
                 "flat dumbbell bench", "flat db bench"],
     "primary": "chest_mid", "equipment": "dumbbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Incline Dumbbell Press",
     "aliases": ["incline db press", "incline dumbbell bench",
                 "incline db bench"],
     "primary": "chest_upper", "equipment": "dumbbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Chest Fly",
     "aliases": ["fly", "dumbbell fly", "db fly", "chest flies", "pec fly",
                 "pec deck"],
     "primary": "chest_mid", "equipment": "machine",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Cable Fly",
     "aliases": ["cable chest fly", "cable crossover", "cable cross over"],
     "primary": "chest_mid", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "High-to-Low Fly",
     "aliases": ["high to low fly", "high low fly", "high-low cable fly"],
     "primary": "chest_lower", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Low-to-High Fly",
     "aliases": ["low to high fly", "low high fly", "low-high cable fly"],
     "primary": "chest_upper", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Push-Up",
     "aliases": ["pushup", "push up", "pushups", "press up"],
     "primary": "chest_mid", "equipment": "bodyweight",
     "rest_seconds": (45, 90), "category": "accessory"},
    {"canonical": "Machine Chest Press",
     "aliases": ["hammer chest press", "smith bench", "smith machine bench",
                 "chest press machine", "plate loaded chest press"],
     "primary": "chest_mid", "equipment": "machine",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Floor Press",
     "aliases": ["barbell floor press", "dumbbell floor press", "db floor press"],
     "primary": "chest_mid", "equipment": "barbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Landmine Press",
     "aliases": ["landmine chest press", "single arm landmine press",
                 "kneeling landmine press"],
     "primary": "chest_upper", "equipment": "barbell",
     "rest_seconds": (75, 120), "category": "accessory"},

    # ── BACK ─────────────────────────────────────────────────────────────────
    # Primary names a SUB-MUSCLE (lats / mid_back / lower_back). Plain "back"
    # routes via _PRIMARY_ALIAS → lats so legacy data still attributes somewhere.
    {"canonical": "Deadlift",
     "aliases": ["barbell deadlift", "conventional deadlift", "dl"],
     "primary": "lower_back", "equipment": "barbell",
     "rest_seconds": (180, 300), "category": "main"},
    {"canonical": "Romanian Deadlift",
     "aliases": ["rdl", "romanian dl", "stiff leg deadlift", "stiff-leg deadlift"],
     "primary": "hamstrings", "equipment": "barbell",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Pull-Up",
     "aliases": ["pullup", "pull up", "pullups", "chin up", "chinup", "chin-up"],
     "primary": "lats", "equipment": "bodyweight",
     "rest_seconds": (90, 150), "category": "main", "level": "advanced"},
    {"canonical": "Lat Pulldown",
     "aliases": ["pulldown", "lat pull down", "wide grip pulldown",
                 "cable pulldown"],
     "primary": "lats", "equipment": "cable",
     "rest_seconds": (60, 120), "category": "main"},
    {"canonical": "Single-Arm Pulldown",
     "aliases": ["single arm pulldown", "one arm pulldown", "unilateral pulldown"],
     "primary": "lats", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Barbell Row",
     "aliases": ["bent over row", "bent-over row", "barbell bent over row",
                 "bb row"],
     "primary": "mid_back", "equipment": "barbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Chest-Supported Row",
     "aliases": ["chest supported row", "chest-supported t-bar"],
     "primary": "mid_back", "equipment": "machine",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Seated Cable Row",
     "aliases": ["cable row", "seated row", "low row", "machine row"],
     "primary": "mid_back", "equipment": "cable",
     "rest_seconds": (60, 120), "category": "accessory"},
    {"canonical": "Straight-Arm Pulldown",
     "aliases": ["straight arm pulldown", "stiff arm pulldown",
                 "straight-arm cable pulldown",
                 "straight arm pull down", "stiff arm pull down",
                 "straight arm pulldowns"],
     "primary": "lats", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Dumbbell Row",
     "aliases": ["db row", "one arm db row", "single arm dumbbell row",
                 "kroc row"],
     "primary": "mid_back", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Pendlay Row",
     "aliases": ["pendlay rows", "dead-stop row", "dead stop row"],
     "primary": "mid_back", "equipment": "barbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "T-Bar Row",
     "aliases": ["t bar row", "t-bar rows", "landmine row", "barbell t-bar row"],
     "primary": "mid_back", "equipment": "barbell",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Rack Pull",
     "aliases": ["rack pulls", "partial deadlift", "block pull"],
     "primary": "lower_back", "equipment": "barbell",
     "rest_seconds": (150, 240), "category": "main"},
    {"canonical": "Hyperextension",
     "aliases": ["hyperextensions", "back extension", "back extensions",
                 "45 degree hyperextension"],
     "primary": "lower_back", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Reverse Hyperextension",
     "aliases": ["reverse hyper", "reverse hypers", "reverse back extension"],
     "primary": "lower_back", "equipment": "machine",
     "rest_seconds": (60, 90), "category": "accessory"},

    # ── SHOULDERS ────────────────────────────────────────────────────────────
    {"canonical": "Overhead Press",
     "aliases": ["ohp", "overhead barbell press", "military press",
                 "standing press", "shoulder press"],
     "primary": "shoulders", "equipment": "barbell",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Dumbbell Shoulder Press",
     "aliases": ["db shoulder press", "seated dumbbell press",
                 "seated db press", "dumbbell ohp"],
     "primary": "shoulders", "equipment": "dumbbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Cable Lateral Raise",
     "aliases": ["cable lateral", "cable laterals", "cable side raise",
                 "cable lat raise"],
     "primary": "shoulders", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Dumbbell Lateral Raise",
     "aliases": ["db lateral raise", "lateral raise", "side raise",
                 "db lat raise", "lateral raises"],
     "primary": "shoulders", "equipment": "dumbbell",
     "rest_seconds": (45, 90), "category": "accessory"},
    {"canonical": "Rear Delt Fly",
     "aliases": ["rear delt", "reverse fly", "rear lateral", "rear delt raise",
                 "rear delts", "cable rear delt fly", "rope rear delt fly"],
     "primary": "shoulders", "equipment": "dumbbell",
     "rest_seconds": (45, 90), "category": "accessory"},
    {"canonical": "Upright Row",
     "aliases": ["upright rows", "barbell upright row", "cable upright row"],
     "primary": "shoulders", "equipment": "barbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Shrug",
     "aliases": ["shrugs", "barbell shrug", "dumbbell shrug", "db shrug",
                 "cable shrug", "machine shrug", "smith machine shrug", "trap shrug"],
     "primary": "traps", "equipment": "barbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Face Pull",
     "aliases": ["face pulls", "rope face pull", "cable face pull"],
     "primary": "shoulders", "equipment": "cable",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Arnold Press",
     "aliases": ["arnold presses", "dumbbell arnold press", "db arnold press"],
     "primary": "shoulders", "equipment": "dumbbell",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Push Press",
     "aliases": ["barbell push press", "overhead push press"],
     "primary": "shoulders", "equipment": "barbell",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Front Raise",
     "aliases": ["front raises", "dumbbell front raise", "db front raise",
                 "plate front raise", "cable front raise"],
     "primary": "shoulders", "equipment": "dumbbell",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Machine Rear Delt Fly",
     "aliases": ["rear delt machine", "reverse pec deck", "rear delt pec deck"],
     "primary": "shoulders", "equipment": "machine",
     "rest_seconds": (45, 75), "category": "accessory"},
    # Distinct from barbell Overhead Press (guided path, different load curve) —
    # mirrors the Machine Chest Press precedent. Do NOT alias bare "shoulder
    # press" here; that phrase belongs to Overhead Press.
    {"canonical": "Machine Shoulder Press",
     "aliases": ["shoulder press machine", "machine overhead press",
                 "seated shoulder press machine", "seated machine shoulder press",
                 "plate loaded shoulder press", "hammer shoulder press",
                 "smith machine shoulder press", "smith shoulder press"],
     "primary": "shoulders", "equipment": "machine",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Farmer's Carry",
     "aliases": ["farmers carry", "farmer carry", "farmers walk", "farmer's walk",
                 "dumbbell farmer's carry"],
     "primary": "traps", "equipment": "dumbbell",
     "rest_seconds": (90, 150), "category": "accessory"},

    # ── BICEPS ───────────────────────────────────────────────────────────────
    {"canonical": "Barbell Curl",
     "aliases": ["bb curl", "standing barbell curl", "straight bar curl"],
     "primary": "biceps", "equipment": "barbell",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Dumbbell Curl",
     "aliases": ["db curl", "dumbbell bicep curl", "standing db curl"],
     "primary": "biceps", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Hammer Curl",
     "aliases": ["db hammer curl", "dumbbell hammer curl", "hammer curls"],
     "primary": "biceps", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Preacher Curl",
     "aliases": ["preacher curls", "ez bar preacher curl", "preacher"],
     "primary": "biceps", "equipment": "barbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Cable Curl",
     "aliases": ["cable curls", "cable bicep curl"],
     "primary": "biceps", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Straight Bar Cable Curl",
     "aliases": ["straight bar cable curl", "cable bar curl",
                 "ez bar cable curl", "ez-bar cable curl"],
     "primary": "biceps", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Incline Dumbbell Curl",
     "aliases": ["incline db curl", "incline bicep curl", "incline curl"],
     "primary": "biceps", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Concentration Curl",
     "aliases": ["concentration curls", "seated concentration curl"],
     "primary": "biceps", "equipment": "dumbbell",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "EZ-Bar Curl",
     "aliases": ["ez bar curl", "ez curl", "ez-bar curls"],
     "primary": "biceps", "equipment": "barbell",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Zottman Curl",
     "aliases": ["zottman curls", "dumbbell zottman curl", "db zottman curl"],
     "primary": "biceps", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "accessory"},

    # ── TRICEPS ──────────────────────────────────────────────────────────────
    {"canonical": "Cable Pushdown",
     "aliases": ["pushdown", "pushdowns", "tricep pushdown", "rope pushdown",
                 "cable tricep pushdown", "tricep push down", "tricep pushdowns"],
     "primary": "triceps", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Overhead Cable Extension",
     "aliases": ["overhead extension cable", "overhead extension",
                 "overhead tricep extension", "rope overhead extension",
                 "cable overhead extension", "overhead cable tricep extension"],
     "primary": "triceps", "equipment": "cable",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Skull Crusher",
     "aliases": ["skullcrusher", "skull crushers", "lying tricep extension",
                 "ez bar skull crusher", "french press"],
     "primary": "triceps", "equipment": "barbell",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Dip",
     "aliases": ["dips", "tricep dip", "tricep dips", "body weight dip",
                 "bodyweight dip", "parallel bar dip"],
     "primary": "triceps", "equipment": "bodyweight",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Close-Grip Bench Press",
     "aliases": ["close grip bench", "cgbp", "close-grip bench"],
     "primary": "triceps", "equipment": "barbell",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Bench Dip",
     "aliases": ["bench dips", "tricep bench dip", "tricep bench dips"],
     "primary": "triceps", "equipment": "bodyweight",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Diamond Push-Up",
     "aliases": ["diamond pushup", "diamond push up", "diamond pushups",
                 "close grip pushup", "close grip push up"],
     "primary": "triceps", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},

    # ── FOREARMS ─────────────────────────────────────────────────────────────
    {"canonical": "Forearm Cable Curl",
     "aliases": ["forearm curl", "forearm curls", "forearm straight bar curl",
                 "forearm straight bar curls", "reverse cable curl"],
     "primary": "forearms", "equipment": "cable",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Reverse Curl",
     "aliases": ["reverse curls", "reverse barbell curl", "ez bar reverse curl"],
     "primary": "forearms", "equipment": "barbell",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Wrist Curl",
     "aliases": ["wrist curls", "barbell wrist curl", "dumbbell wrist curl",
                 "db wrist curl"],
     "primary": "forearms", "equipment": "barbell",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Reverse Wrist Curl",
     "aliases": ["reverse wrist curls", "wrist extension", "wrist extensions"],
     "primary": "forearms", "equipment": "barbell",
     "rest_seconds": (45, 60), "category": "accessory"},

    # ── CORE / ABS ───────────────────────────────────────────────────────────
    {"canonical": "Cable Crunch",
     "aliases": ["cable crunches", "crunches (cable/machine)", "rope crunch",
                 "cable ab crunch", "ab crunch", "kneeling cable crunch"],
     "primary": "abs", "equipment": "cable",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Crunch",
     "aliases": ["crunches", "ab crunches", "bodyweight crunch", "sit up",
                 "situp", "sit-up", "sit ups"],
     "primary": "abs", "equipment": "bodyweight",
     "rest_seconds": (30, 60), "category": "accessory"},
    {"canonical": "Plank",
     "aliases": ["planks", "front plank", "forearm plank"],
     "primary": "abs", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "core"},
    {"canonical": "Hanging Leg Raise",
     "aliases": ["leg raise", "leg raises", "hanging knee raise",
                 "hanging leg raises", "knee raise"],
     "primary": "abs", "equipment": "bodyweight",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Russian Twist",
     "aliases": ["russian twists", "weighted twist", "ab twist"],
     "primary": "obliques", "equipment": "bodyweight",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Oblique Cable Crunch",
     "aliases": ["oblique work", "oblique crunch", "side cable crunch",
                 "cable oblique"],
     "primary": "obliques", "equipment": "cable",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Dead Bug",
     "aliases": ["dead bugs", "dead-bug", "deadbug", "alternating dead bug"],
     "primary": "abs", "equipment": "bodyweight",
     "rest_seconds": (30, 45), "category": "core"},
    {"canonical": "Pallof Press",
     "aliases": ["pallof presses", "anti-rotation press", "cable pallof press"],
     "primary": "abs", "equipment": "cable",
     "rest_seconds": (45, 60), "category": "core"},
    {"canonical": "Side Plank",
     "aliases": ["side planks", "side plank hold", "lateral plank"],
     "primary": "obliques", "equipment": "bodyweight",
     "rest_seconds": (30, 60), "category": "core"},

    # ── LEGS — QUADS ─────────────────────────────────────────────────────────
    {"canonical": "Back Squat",
     "aliases": ["squat", "barbell back squat", "high bar squat", "low bar squat"],
     "primary": "quads", "equipment": "barbell",
     "rest_seconds": (180, 240), "category": "main"},
    {"canonical": "Front Squat",
     "aliases": ["front squats", "barbell front squat"],
     "primary": "quads", "equipment": "barbell",
     "rest_seconds": (150, 210), "category": "main"},
    {"canonical": "Leg Press",
     "aliases": ["leg presses", "45 degree leg press", "machine leg press"],
     "primary": "quads", "equipment": "machine",
     "rest_seconds": (90, 150), "category": "main"},
    {"canonical": "Leg Extension",
     "aliases": ["leg extensions", "quad extension", "knee extension"],
     "primary": "quads", "equipment": "machine",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Bulgarian Split Squat",
     "aliases": ["bulgarian split squats", "rear foot elevated split squat",
                 "bss"],
     "primary": "quads", "equipment": "dumbbell",
     "rest_seconds": (90, 120), "category": "accessory"},
    {"canonical": "Lunge",
     "aliases": ["lunges", "walking lunge", "walking lunges", "dumbbell lunge",
                 "db lunge", "reverse lunge"],
     "primary": "quads", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Hack Squat",
     "aliases": ["hack squats", "machine hack squat", "plate loaded hack squat"],
     "primary": "quads", "equipment": "machine",
     "rest_seconds": (120, 180), "category": "main"},
    {"canonical": "Step-Up",
     "aliases": ["step ups", "step-ups", "stepup", "stepups", "dumbbell step-up",
                 "db step up", "box step-up"],
     "primary": "quads", "equipment": "dumbbell",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Box Squat",
     "aliases": ["box squats", "barbell box squat", "low box squat"],
     "primary": "quads", "equipment": "barbell",
     "rest_seconds": (150, 210), "category": "main"},

    # ── LEGS — HAMSTRINGS / GLUTES ───────────────────────────────────────────
    {"canonical": "Hamstring Curl",
     "aliases": ["hamstring curls", "leg curl", "leg curls", "lying leg curl",
                 "lying hamstring curl"],
     "primary": "hamstrings", "equipment": "machine",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Seated Leg Curl",
     "aliases": ["seated leg curls", "seated hamstring curl",
                 "seated hamstring curls", "machine seated leg curl"],
     "primary": "hamstrings", "equipment": "machine",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Nordic Curl",
     "aliases": ["nordic curls", "nordic hamstring curl",
                 "nordic ham curl", "russian leg curl"],
     "primary": "hamstrings", "equipment": "bodyweight",
     "rest_seconds": (90, 120), "category": "accessory", "level": "advanced"},
    {"canonical": "Hip Thrust",
     "aliases": ["hip thrusts", "barbell hip thrust"],
     "primary": "glutes", "equipment": "barbell",
     "rest_seconds": (90, 120), "category": "main"},
    {"canonical": "Glute Bridge",
     "aliases": ["glute bridges", "bodyweight glute bridge", "barbell glute bridge"],
     "primary": "glutes", "equipment": "bodyweight",
     "rest_seconds": (60, 90), "category": "accessory"},
    {"canonical": "Glute Kickback",
     "aliases": ["glute kickbacks", "cable kickback", "donkey kick",
                 "glute push back"],
     "primary": "glutes", "equipment": "cable",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Good Morning",
     "aliases": ["good mornings", "barbell good morning"],
     "primary": "hamstrings", "equipment": "barbell",
     "rest_seconds": (90, 120), "category": "accessory"},

    # ── LEGS — CALVES ────────────────────────────────────────────────────────
    {"canonical": "Calf Raise",
     "aliases": ["calf raises", "standing calf raise machine", "calves", "calf"],
     "primary": "calves", "equipment": "machine",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Seated Calf Raise",
     "aliases": ["seated calf raises", "machine seated calf raise",
                 "seated calf"],
     "primary": "calves", "equipment": "machine",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Standing Calf Raise",
     "aliases": ["standing calf raises", "standing calves",
                 "smith machine calf raise"],
     "primary": "calves", "equipment": "machine",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Donkey Calf Raise",
     "aliases": ["donkey calf raises", "donkey calves", "machine donkey calf raise"],
     "primary": "calves", "equipment": "machine",
     "rest_seconds": (45, 75), "category": "accessory"},

    # ── CARDIO ───────────────────────────────────────────────────────────────
    {"canonical": "Stationary Bike",
     "aliases": ["stationary biking", "spin bike", "spin", "spinning",
                 "exercise bike", "bike", "indoor bike"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},
    {"canonical": "Treadmill",
     "aliases": ["treadmill run", "treadmill walk", "incline walk",
                 "incline treadmill"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},
    {"canonical": "Running",
     "aliases": ["run", "runs", "outdoor run", "jog", "jogging"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},
    {"canonical": "Rowing",
     "aliases": ["row", "rower", "erg", "rowing machine", "ergometer"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},
    {"canonical": "Stair Climber",
     "aliases": ["stairmaster", "stair master", "stairs"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},
    {"canonical": "Walking",
     "aliases": ["walk", "walks", "outdoor walk", "brisk walk"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},
    {"canonical": "Elliptical",
     "aliases": ["elliptical machine", "cross trainer"],
     "primary": "cardio", "equipment": "cardio",
     "rest_seconds": (0, 0), "category": "cardio"},

    # ── CONDITIONING / FINISHERS ─────────────────────────────────────────────
    # Distinct from steady-state cardio: treated as strength sets (sets x reps)
    # with their own INVOLVEMENT maps so they land on the right muscles, not as
    # generic Zone-X cardio. Primary is the dominant mover (NOT "cardio").
    {"canonical": "Battle Ropes",
     "aliases": ["battle rope", "rope slams", "battling ropes"],
     "primary": "shoulders", "equipment": "cardio",
     "rest_seconds": (60, 90), "category": "finisher"},
    {"canonical": "Burpees",
     "aliases": ["burpee", "bodyweight burpee"],
     "primary": "abs", "equipment": "bodyweight",
     "rest_seconds": (45, 90), "category": "finisher"},
    {"canonical": "Box Jumps",
     "aliases": ["box jump", "plyo box jump", "plyometric box jump"],
     "primary": "quads", "equipment": "bodyweight",
     "rest_seconds": (60, 90), "category": "finisher"},

    # ── HOME · BANDS · BODYWEIGHT ─────────────────────────────────────────────
    # Coverage layer so an at-home user (resistance bands + bodyweight — the most
    # common home setup) gets a COMPLETE program: every major muscle has a real
    # movement, not a degenerate 1-exercise day. Placed LAST so catalog order
    # keeps barbell/dumbbell/machine movements first for a fully-equipped user;
    # these are only reached when equipment is restricted to bands/bodyweight.
    # Beginner-appropriate: band presses/rows/squats/hinges are the mains; the
    # genuinely hard bodyweight staples (Pull-Up, Nordic Curl) carry
    # level="advanced" so the builder ranks them BEHIND band regressions unless
    # the user is intermediate+ or nothing else covers the muscle.

    # CHEST
    {"canonical": "Band Chest Press",
     "aliases": ["banded chest press", "resistance band chest press",
                 "band bench press", "standing band chest press"],
     "primary": "chest_mid", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Incline Push-Up",
     "aliases": ["incline pushup", "incline push up", "hands-elevated push-up",
                 "hands elevated pushup", "knee push-up", "knee pushup",
                 "kneeling push-up"],
     "primary": "chest_mid", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Band Incline Press",
     "aliases": ["banded incline press", "band incline chest press",
                 "resistance band incline press"],
     "primary": "chest_upper", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Decline Push-Up",
     "aliases": ["decline pushup", "decline push up", "feet-elevated push-up",
                 "feet elevated pushup"],
     "primary": "chest_upper", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},

    # BACK
    {"canonical": "Band Row",
     "aliases": ["banded row", "resistance band row", "seated band row",
                 "band bent over row", "band bent-over row"],
     "primary": "mid_back", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Band Pull-Apart",
     "aliases": ["band pull apart", "banded pull-apart", "band pull aparts",
                 "resistance band pull apart"],
     "primary": "mid_back", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Band Lat Pulldown",
     "aliases": ["banded lat pulldown", "band pulldown", "resistance band pulldown",
                 "kneeling band pulldown", "band lat pull down"],
     "primary": "lats", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Band Straight-Arm Pulldown",
     "aliases": ["band straight arm pulldown", "banded straight-arm pulldown",
                 "band lat pullover"],
     "primary": "lats", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Superman",
     "aliases": ["supermans", "superman hold", "prone back extension"],
     "primary": "lower_back", "equipment": "bodyweight",
     "rest_seconds": (30, 60), "category": "accessory"},
    {"canonical": "Bird Dog",
     "aliases": ["bird dogs", "bird-dog", "quadruped bird dog"],
     "primary": "lower_back", "equipment": "bodyweight",
     "rest_seconds": (30, 45), "category": "core"},

    # SHOULDERS
    {"canonical": "Band Overhead Press",
     "aliases": ["banded overhead press", "band shoulder press",
                 "resistance band overhead press", "band military press"],
     "primary": "shoulders", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Pike Push-Up",
     "aliases": ["pike pushup", "pike push up", "pike pushups"],
     "primary": "shoulders", "equipment": "bodyweight",
     "rest_seconds": (60, 90), "category": "main", "level": "advanced"},
    {"canonical": "Band Lateral Raise",
     "aliases": ["banded lateral raise", "band side raise", "band lat raise",
                 "resistance band lateral raise"],
     "primary": "shoulders", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Band Front Raise",
     "aliases": ["banded front raise", "band front raises"],
     "primary": "shoulders", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Band Face Pull",
     "aliases": ["banded face pull", "band face pulls", "resistance band face pull"],
     "primary": "shoulders", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Band Shrug",
     "aliases": ["banded shrug", "band shrugs", "resistance band shrug"],
     "primary": "traps", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},

    # ARMS
    {"canonical": "Band Curl",
     "aliases": ["banded curl", "band bicep curl", "resistance band curl",
                 "band biceps curl"],
     "primary": "biceps", "equipment": "bands",
     "rest_seconds": (45, 75), "category": "main"},
    {"canonical": "Band Hammer Curl",
     "aliases": ["banded hammer curl", "band hammer curls"],
     "primary": "biceps", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},
    {"canonical": "Band Pushdown",
     "aliases": ["banded pushdown", "band tricep pushdown", "band tricep push down",
                 "resistance band pushdown"],
     "primary": "triceps", "equipment": "bands",
     "rest_seconds": (45, 75), "category": "main"},
    {"canonical": "Band Overhead Tricep Extension",
     "aliases": ["banded overhead extension", "band tricep extension",
                 "band overhead tricep extension"],
     "primary": "triceps", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},

    # LEGS — QUADS
    {"canonical": "Bodyweight Squat",
     "aliases": ["bodyweight squats", "air squat", "air squats", "bw squat"],
     "primary": "quads", "equipment": "bodyweight",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Band Squat",
     "aliases": ["banded squat", "resistance band squat", "band goblet squat"],
     "primary": "quads", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Bodyweight Reverse Lunge",
     "aliases": ["bodyweight reverse lunge", "bodyweight lunge", "bw lunge",
                 "bodyweight lunges", "bw reverse lunge"],
     "primary": "quads", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Bodyweight Split Squat",
     "aliases": ["bodyweight split squat", "static lunge", "bw split squat"],
     "primary": "quads", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},

    # LEGS — HAMSTRINGS / GLUTES
    {"canonical": "Band Romanian Deadlift",
     "aliases": ["band rdl", "banded romanian deadlift", "band romanian dl",
                 "resistance band rdl"],
     "primary": "hamstrings", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Single-Leg Romanian Deadlift",
     "aliases": ["single leg rdl", "single-leg rdl", "sl rdl",
                 "single leg romanian deadlift"],
     "primary": "hamstrings", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Band Good Morning",
     "aliases": ["banded good morning", "band good mornings"],
     "primary": "hamstrings", "equipment": "bands",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Band Hip Thrust",
     "aliases": ["banded hip thrust", "band hip thrusts", "resistance band hip thrust"],
     "primary": "glutes", "equipment": "bands",
     "rest_seconds": (60, 90), "category": "main"},
    {"canonical": "Single-Leg Glute Bridge",
     "aliases": ["single leg glute bridge", "single-leg glute bridge",
                 "one leg glute bridge"],
     "primary": "glutes", "equipment": "bodyweight",
     "rest_seconds": (45, 75), "category": "accessory"},
    {"canonical": "Band Glute Kickback",
     "aliases": ["banded glute kickback", "band kickback", "band donkey kick"],
     "primary": "glutes", "equipment": "bands",
     "rest_seconds": (45, 60), "category": "accessory"},

    # CALVES
    {"canonical": "Bodyweight Calf Raise",
     "aliases": ["bodyweight calf raises", "standing bodyweight calf raise",
                 "bw calf raise"],
     "primary": "calves", "equipment": "bodyweight",
     "rest_seconds": (30, 60), "category": "accessory"},
    {"canonical": "Single-Leg Calf Raise",
     "aliases": ["single leg calf raise", "single-leg calf raises",
                 "one leg calf raise"],
     "primary": "calves", "equipment": "bodyweight",
     "rest_seconds": (30, 60), "category": "accessory"},
]


# ── Lookup index ──────────────────────────────────────────────────────────────

def _norm_key(s: Optional[str]) -> str:
    """Normalize for matching. Light touch only — keep this predictable.
      • lowercase
      • strip hyphens (so 'pull-up' == 'pull up')
      • collapse whitespace
    Does NOT strip plurals; aliases are responsible for plural variants.
    Does NOT do fuzzy matching."""
    if not s:
        return ""
    return " ".join(s.lower().replace("-", " ").split())


def _build_alias_map() -> dict[str, dict]:
    """Build alias→entry map at import time. Adds the canonical name as
    its own alias so it always resolves to itself. Asserts no alias
    collisions across entries — protects against silent regressions when
    adding new exercises."""
    m: dict[str, dict] = {}
    for e in EXERCISES:
        keys = [e["canonical"]] + list(e.get("aliases", []))
        for k in keys:
            nk = _norm_key(k)
            if not nk:
                continue
            if nk in m and m[nk]["canonical"] != e["canonical"]:
                raise ValueError(
                    f"Alias collision: '{nk}' maps to both "
                    f"'{m[nk]['canonical']}' and '{e['canonical']}'"
                )
            m[nk] = e
    return m


_ALIAS_MAP: dict[str, dict] = _build_alias_map()


def canonicalize(name: Optional[str]) -> tuple[str, Optional[dict]]:
    """Map a user-typed exercise name to its canonical form + catalog entry.

    Returns:
        (canonical_name, entry) when a match is found
        (original_name, None)   when no match — caller logs under the raw name

    Behavior is intentionally narrow. Only exact alias hits (after light
    normalization for hyphens/case/whitespace, plus a single plural-strip
    fallback) resolve. No fuzzy matching — a confident "no match" is better
    than a wrong mapping. Adding explicit aliases is one line; mis-mapping
    is silent data corruption.

    Plural fallback: if the normalized name ends in 's' and doesn't resolve
    directly, retry with the trailing 's' stripped. This catches user
    plural variants like 'pull ups' → 'pull up' → 'Pull-Up' without us
    having to list every plural form in every entry's aliases.
    """
    if not name:
        return name or "", None
    nk = _norm_key(name)
    e = _ALIAS_MAP.get(nk)
    if e:
        return e["canonical"], e
    if nk.endswith("s") and len(nk) > 1:
        e = _ALIAS_MAP.get(nk[:-1])
        if e:
            return e["canonical"], e
    return name, None


def lookup_canonical(canonical_name: str) -> Optional[dict]:
    """Find a catalog entry by exact canonical name (for downstream code
    that has the canonical from a prior canonicalize() call)."""
    nk = _norm_key(canonical_name)
    e = _ALIAS_MAP.get(nk)
    if e and e["canonical"].lower() == (canonical_name or "").lower():
        return e
    return None
