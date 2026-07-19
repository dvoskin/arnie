"""
Arnie tool definitions — Anthropic function-calling schema.

Tools are grouped by category. build_tools() returns the full list.
Adding a new tool: define it in the appropriate category and add to ALL_TOOLS.
Removing a tool: set enabled=False or remove from ALL_TOOLS.

Note: OpenAI-format conversion is handled in core/llm.py.
"""

# ─────────────────────────────────────────────────────────────────────────────
# NUTRITION TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_NUTRITION_TOOLS = [
    {
        "name": "log_food",
        "description": (
            "Log ONE food or meal item to the daily nutrition log. "
            "Call when the user reports having eaten or drunk something — past or present tense "
            "('just had', 'ate', 'having right now', 'finished'). "
            "Do NOT call for future plans or intentions ('going to have', 'planning to eat', "
            "'thinking about', 'about to eat', 'might grab', 'gonna have'). "
            "Call ONCE per distinct food item — one item per call. "
            "Multiple foods = multiple calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "food_name":  {"type": "string"},
                "quantity":   {"type": "string", "description": "e.g. '1 cup', '200g', '2 slices'"},
                "calories":   {"type": "number"},
                "protein":    {"type": "number", "description": "grams"},
                "carbs":      {"type": "number", "description": "grams"},
                "fats":       {"type": "number", "description": "grams"},
                "fiber":      {"type": "number", "description": "grams, optional"},
                "confidence": {"type": "number", "description": "0.0-1.0. 0.9+ for known foods, 0.6-0.8 for estimates"},
                "estimated":  {"type": "boolean"},
                "date":       {"type": "string", "description": "Optional. Log to a specific date instead of today. Use 'yesterday', '2 days ago', or YYYY-MM-DD format. Only set when user explicitly says they forgot to log something for a past day."},
                "time":       {"type": "string", "description": "Optional. Clock time the food was actually eaten, ONLY when the user states one (e.g. '8:30am', '13:45', 'noon', 'around 7'). Combined with `date` + the user's timezone to place it on the day's timeline. Leave unset if no time is given — do not guess."},
                "meal_type":  {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack", "pre_workout", "post_workout"], "description": "Optional. Which meal slot this fits. Infer from time of day + user history if not stated."},
                "alcohol_units": {"type": "number", "description": "Optional. Standard alcohol units (1 unit ≈ 1 beer / 1 glass wine / 1 shot)."},
                "from_photo": {"type": "boolean", "description": "True when logging from a food photo — sets confidence ≤0.75 and estimated=true automatically."},
                "is_packaged": {"type": "boolean", "description": "True when this is a branded packaged product (PACKAGED: line from a photo, OR a clearly branded text mention like 'Quest bar', 'Liquid IV', 'Elmhurst shake', 'Oikos yogurt'). Routes enrichment through web search for label-accurate macros. Leave false for generic foods (chicken breast, white rice, eggs)."},
                "processing_level": {"type": "string", "enum": ["whole", "processed", "ultra_processed"], "description": "NOVA-style processing class. 'whole' = unprocessed/minimally processed (meat, eggs, fruit, veg, rice, plain dairy, scratch-cooked meals). 'processed' = processed staples (bread, cheese, deli meat, protein bars/powder, canned goods). 'ultra_processed' = formulated industrial products (soda, candy, chips, fast food, packaged desserts, instant noodles). Classify by how the food is made, not how healthy it sounds. Always set it."},
                "coach_read": {"type": "string", "description": "One decisive coach sentence about THIS log against the user's day — shown on the receipt card, so make it earn its line. ≤55 chars, sentence case, NO numbers (the card carries the numbers), no generic praise ('Great job'), never repeat what the day-impact line already says. Vary it — never the same read twice in a row. Examples: 'Solid anchor. Build the day on this.' / 'Carbs added. Protein still needs the anchor.' / 'Keep dinner lean and this lands fine.' / 'That closes the day. Don't overcorrect.' Omit when the log is neutral and needs no read."},
            },
            "required": ["food_name", "quantity", "calories", "protein", "carbs", "fats", "confidence"],
        },
    },
    {
        "name": "update_food_entry",
        "description": (
            "CORRECT or MOVE an existing food entry already in the log. "
            "Use when the user is fixing values for food already logged, OR moving an "
            "entry to a different day. Find the entry by its [#id] in the context. "
            "DO NOT call log_food for corrections — that creates a duplicate. "
            "Only include fields the user is actually changing. "
            "To move an entry to another day, set date= (e.g. 'yesterday'). Moving a WHOLE "
            "day means calling this once per entry with the same date — it's the same "
            "primitive as moving one item, just repeated. Totals on both days resync "
            "automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id":  {"type": "integer", "description": "The [#id] of the food entry to update"},
                "food_name": {"type": "string"},
                "quantity":  {"type": "string"},
                "calories":  {"type": "number"},
                "protein":   {"type": "number"},
                "carbs":     {"type": "number"},
                "fats":      {"type": "number"},
                "date":      {"type": "string", "description": "Optional. Move this entry to another day: 'yesterday', '2 days ago', or YYYY-MM-DD."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "delete_food_entry",
        "description": (
            "REMOVE a food entry from today's log. "
            "Use when user says 'delete my lunch', 'remove the coffee', 'I didn't eat that'. "
            "Find the entry by its [#id] in the context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"entry_id": {"type": "integer"}},
            "required": ["entry_id"],
        },
    },
    {
        "name": "clear_day_log",
        "description": (
            "Wipe ALL of today's food and exercise entries and zero the totals — a clean "
            "slate. Use when the user wants to REDO or restart today's log: 'redo today', "
            "'clear today', 'start today over', 'wipe today and re-log', 'reset today's "
            "food', 'delete everything from today'. "
            "CRITICAL: if they also gave you the new list in the same message ('redo today "
            "as the following: ...'), call this FIRST, then immediately call log_food once "
            "per new item in the SAME turn. One clean rebuild, never a second turn. "
            "Then confirm: cleared + what's now logged + the new total."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "log_water",
        "description": (
            "Log water intake when user mentions drinking water. "
            "Optionally include context (morning, with_meal, post_workout, "
            "during_workout, random) for timing-aware hydration coaching, "
            "and date= to log to a past day."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amount_ml": {"type": "number"},
                "amount_oz": {"type": "number"},
                "context":   {"type": "string", "enum": ["morning", "with_meal", "post_workout", "during_workout", "random"], "description": "Optional. When/why they drank — improves hydration timing coaching."},
                "date":      {"type": "string", "description": "Optional. Log to a specific date — 'yesterday', '2 days ago', or YYYY-MM-DD."},
            },
        },
    },
    {
        "name": "coach_on_photo",
        "description": (
            "Return a structured coaching DECISION for a photo that the preprocessor has tagged "
            "as a decision-mode block. Call this when you see ANY of these tagged blocks in the "
            "user's message: [MENU_DECISION], [FRIDGE], [GROCERY], [DELIVERY_APP], "
            "[PREPARED_MEAL_DECISION], [BODY_PROGRESS]. "
            ""
            "DO NOT call for: "
            "  • [FOOD_LOG] / [PACKAGED_PRODUCT] → use log_food per item with from_photo=true "
            "  • [WORKOUT_LOG] → use log_exercise per item "
            "  • [METRICS] with SOURCE: blood_test or wearable → use track_metric per value (and "
            "    log_body_weight if a body-weight reading is present) "
            "  • [FOOD_DIARY] → use log_food per item with from_photo=true AND date= from the diary "
            "  • [PREPARED_MEAL_AMBIGUOUS] / [UNKNOWN] → ASK the user, don't call any tool yet "
            ""
            "The decision must be CRISP and SPECIFIC. Not 'salmon is healthy' — 'get the salmon, "
            "sub broccoli for rice, one drink not two.' Reference the user's daily targets in "
            "reasoning. Coach voice, not chart voice. Cap confidence at 0.85 (photos are estimates)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "photo_type": {
                    "type": "string",
                    "enum": ["menu", "fridge", "grocery", "delivery_app", "prepared_meal", "body_progress"],
                    "description": "Which decision-block this responds to (match the tag from the preprocessor block).",
                },
                "decision": {
                    "type": "string",
                    "description": (
                        "Short, specific, actionable recommendation. Examples: "
                        "'Get the salmon, sub broccoli for rice, one drink not two.' "
                        "'Make scrambled eggs with spinach and toast — you have everything.' "
                        "'Swap the granola for greek yogurt, that's the one fix worth making.' "
                        "'Eat it, skip the bread.' For body progress: encouraging observation about "
                        "what's actually visible (don't quote a single BF % — quote a range or describe "
                        "the trend)."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "1-2 sentence WHY, referencing user's daily targets concretely. "
                        "'You're at 1200/2000 cals with 50g protein left to hit. Salmon nails it.' "
                        "Coach voice."
                    ),
                },
                "items_identified": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short list of items the preprocessor noticed (for transparency in the rendered card).",
                },
                "macros_estimate": {
                    "type": "object",
                    "properties": {
                        "calories": {"type": "number"},
                        "protein":  {"type": "number"},
                        "carbs":    {"type": "number"},
                        "fats":     {"type": "number"},
                    },
                    "description": "Estimated macros for the RECOMMENDED option (menu/delivery/prepared_meal). Omit for fridge/grocery/body_progress.",
                },
                "bf_range": {
                    "type": "object",
                    "properties": {
                        "low":  {"type": "number", "description": "Lower bound %, e.g. 14"},
                        "high": {"type": "number", "description": "Upper bound %, e.g. 17"},
                    },
                    "description": (
                        "BODY_PROGRESS only. Body fat ESTIMATE RANGE (never a single number). "
                        "Always pair with the 'trend vs prior photo' framing in reasoning. "
                        "Expand the range when uncertain — better to be honest than precise."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "0.0-1.0. CAP AT 0.85 for any photo decision (vision estimates are noisy). "
                        "Body fat estimates: cap at 0.75 specifically."
                    ),
                },
            },
            "required": ["photo_type", "decision", "reasoning", "confidence"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# FITNESS TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_FITNESS_TOOLS = [
    {
        "name": "log_exercise",
        "description": (
            "Log a strength/cardio movement to the workout. ONE call per movement — "
            "all of its sets go in that single call (the backend keeps one row per "
            "movement per session, so it stays clean and editable). Pick by load:\n"
            "• SAME load across sets → sets=N, reps='8,8,8' (per-set reps CSV), weight=135. "
            "e.g. '3x8 @ 135' → sets=3, reps='8,8,8', weight=135.\n"
            "• VARYING load (pyramid / drop / ramp) → sets=N, reps='10,8,6' AND "
            "weights='135,145,155' (parallel CSVs, same length/order). e.g. "
            "'bench 135x10, 145x8, 155x6' → ONE call: sets=3, reps='10,8,6', "
            "weights='135,145,155'. Do NOT split a movement into one call per set or per load.\n"
            "LIVE set-by-set logging: when the user reports ONE set at a time as they go "
            "('just did 10 at 165'), log that single set (sets=1, reps='10', weight=165). "
            "Repeat per set as they happen — the backend rolls successive sets of the SAME "
            "movement into the one row automatically. Never re-log a set already logged. "
            "Different movements: one call each. To fix/move an existing entry use "
            "update_exercise_entry, never a second log_exercise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name":     {"type": "string"},
                "sets":              {"type": "integer"},
                "reps":              {"type": "string", "description": "e.g. '5' or '5,5,5,4'"},
                "weight":            {"type": "number", "description": "the load when it's the SAME across all sets, in the unit the user specified"},
                "weights":           {"type": "string", "description": "PER-SET loads as a CSV, same order/length as reps, when the load VARIES across sets (pyramid / drop set / ramp). e.g. '135x10, 145x8, 155x6' -> reps='10,8,6', weights='135,145,155'. Log the whole movement as ONE call with reps + weights — do NOT split into one call per load. Omit when the weight is uniform (use `weight`)."},
                "weight_unit":       {"type": "string", "enum": ["lbs", "kg"], "default": "lbs"},
                "rir":               {"type": "integer", "description": "reps in reserve"},
                "duration_minutes":  {"type": "number"},
                "cardio_type":       {"type": "string", "description": "e.g. 'incline walk', 'HIIT'"},
                "is_cardio":         {"type": "boolean"},
                "date":              {"type": "string", "description": "Optional. Log to a specific date. Use 'yesterday', '2 days ago', or YYYY-MM-DD. Only set when user explicitly mentions a past day."},
                "time":              {"type": "string", "description": "Optional. Clock time the workout actually happened, ONLY when the user states one (e.g. '7am', '18:30', 'right after lunch' -> leave unset). Combined with `date` + the user's timezone to place it on the day's timeline. Leave unset if no time is given — do not guess."},
            },
            "required": ["exercise_name"],
        },
    },
    {
        "name": "update_exercise_entry",
        "description": (
            "CORRECT or MOVE an existing exercise entry already in the log. "
            "Use when the user fixes weight, sets, reps, or name, OR moves it to another "
            "day. Find the entry by its [#id] in the context. "
            "DO NOT call log_exercise for corrections — that creates a duplicate. "
            "To move it to another day, set date= (e.g. 'yesterday')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id":         {"type": "integer", "description": "The [#id] of the exercise entry to update"},
                "exercise_name":    {"type": "string"},
                "sets":             {"type": "integer"},
                "reps":             {"type": "string"},
                "weight":           {"type": "number"},
                "duration_minutes": {"type": "number"},
                "date":             {"type": "string", "description": "Optional. Move this entry to another day: 'yesterday' or YYYY-MM-DD."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "delete_exercise_entry",
        "description": (
            "REMOVE an exercise entry from today's log. "
            "Use when user says 'delete my bench press', 'remove that set'. "
            "Find the entry by its [#id] in the context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"entry_id": {"type": "integer"}},
            "required": ["entry_id"],
        },
    },
    {
        "name": "log_body_weight",
        "description": (
            "Log a body-weight measurement (the user's own scale weight). "
            "Call ONLY when the user explicitly states their body weight with phrases like "
            "'I weigh X', 'weighed in at X', 'scale said X', 'my weight is X', or a standalone "
            "number given in direct answer to a weigh-in question. "
            "NEVER call when the message NAMES AN EXERCISE OR MOVEMENT. If a lift, machine, or "
            "movement is mentioned (bench, squat, deadlift, press, row, curl, pulldown, lat "
            "pulldown, extension, raise, pull-up, etc.), ANY number is a LIFTED LOAD or rep "
            "count, never bodyweight → use log_exercise. This includes rep-notation like "
            "'165x', '165x8', '3 sets of lat pulldowns 165x', '225 for 5', '3x10 @ 185' — all "
            "are exercise loads, NOT a scale reading. 'benched 225', 'squatted 315', "
            "'hit 185 on bench', 'lat pulldowns 165x' → log_exercise, NOT log_body_weight. "
            "NEVER call based on food photo macro estimates — "
            "protein grams, fat grams, or calorie counts in a meal analysis are NOT body weight. "
            "Do NOT call for food weights, portion sizes, or nutrition label values "
            "('sub 200 cal', '4-5oz chicken' are FOOD, not body weight). "
            "The body-weight number MUST appear in the CURRENT user message. NEVER re-log a "
            "weight pulled from context, memory, or an earlier turn; if this message has no "
            "fresh body-weight number, do not call this tool. "
            "When in doubt and an exercise is in the message, prefer log_exercise. "
            "If the user mentions WHEN they weighed in (morning, after meal, etc.) include "
            "the context for trend interpretation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weight": {"type": "number"},
                "unit":   {"type": "string", "enum": ["lbs", "kg"]},
                "context": {
                    "type": "string",
                    "enum": ["morning_fasted", "post_meal", "evening", "post_workout", "unknown"],
                    "description": "When/how the weight was taken. morning_fasted is gold standard; others carry noise.",
                },
                "date": {"type": "string", "description": "Optional. Log to a specific PAST date — 'yesterday', '2 days ago', or YYYY-MM-DD. Only set when the user explicitly says they forgot to record a weigh-in for a past day. A backfilled past weigh-in feeds the trend but does NOT change their current weight."},
                "time": {"type": "string", "description": "Optional. Clock time of the weigh-in, ONLY when the user states one (e.g. '7am', 'this morning'). Combined with `date` + the user's timezone to place it on the right day. Leave unset if no time is given."},
            },
            "required": ["weight", "unit"],
        },
    },
    {
        "name": "propose_workout_program",
        "description": (
            "Build a structured, science-based, multi-day workout PROGRAM for the user — "
            "a recurring weekly plan with sessions, exercises, sets, reps, RIR, and rest. "
            "Call when the user asks to design a training program ('build me a plan', "
            "'I want a 5-day split', 'design a workout program', 'make me a PPL', "
            "'put together a routine'). DO NOT call for a SINGLE today's workout — that's "
            "suggest_workout. DO NOT call to log a workout — that's log_exercise. "
            "This persists the program (multiple sessions per week) and marks any prior "
            "active program inactive. The user's iOS app will render the new program. "
            "Volume + frequency are evidence-grounded (Schoenfeld 2017 sets-per-muscle, "
            "Schoenfeld 2016 frequency) — the rationale field returned in the tool result "
            "names the references so you can ground the in-chat explanation. "
            "BEFORE calling, ask up to 2 short clarifying questions if MISSING: goal "
            "(hypertrophy / strength / general), training days/week (3-6), split "
            "preference, gym equipment, experience level, weak points. Skip questions "
            "you can infer from the user's profile or stated context. Then call ONCE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "enum": ["hypertrophy", "strength", "general"],
                    "description": "Primary training goal. Default hypertrophy if user hasn't specified.",
                },
                "days_per_week": {
                    "type": "integer",
                    "minimum": 2, "maximum": 7,
                    "description": "How many training days per week the user wants. Most common: 3-6.",
                },
                "split": {
                    "type": "string",
                    "enum": ["ppl", "upper_lower", "full_body", "bro", "custom"],
                    "description": "Training split. ppl = push/pull/legs, upper_lower = U/L, full_body = full body, bro = bro split (one muscle per day), custom = auto-pick a sensible default by cadence.",
                },
                "equipment": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["barbell", "dumbbell", "cable", "machine", "bodyweight", "kettlebell", "bands"]},
                    "description": "Equipment the user has access to. Bodyweight is always included. Default = full gym (barbell + dumbbell + cable + machine + bodyweight).",
                },
                "experience": {
                    "type": "string",
                    "enum": ["beginner", "intermediate", "advanced"],
                    "description": "Training experience. Drives volume target + RIR. Default intermediate if user hasn't specified.",
                },
                "weak_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Muscle ids the user wants extra emphasis on (e.g. 'chest_upper', 'lats', 'glutes'). Adds 1 extra accessory on each session that targets them.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional. User-stated constraints / injuries / preferences. Stored on the program for reference.",
                },
            },
        },
    },
    {
        "name": "show_workout_program",
        "description": (
            "Show the user their CURRENT active workout program — the multi-day "
            "recurring plan stored from a prior propose_workout_program call. Call "
            "when the user asks 'what's my program?', 'show me my plan', 'remind me "
            "of my split', 'pull up my routine'. DO NOT use for a single day's "
            "session (use suggest_workout) or for today's history (use show_workout_log). "
            "Native clients ALSO render an inline program card, but your text reply must "
            "lay out the full week itself (one day per line) — the card does not render on "
            "every client, and answering 'show me my plan' with no visible plan is a failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# Day close/reopen was deleted in T1.1: every day (today or past) is always
# editable via the date= field on log_food / log_exercise / update_*_entry.
# No status transition, no "closed" state. _DAY_TOOLS kept as empty list so
# ALL_TOOLS below can stay structurally identical.

_DAY_TOOLS: list = []


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING PROGRAM TOOLS — edit the PLAN from conversation (day-of-rotation
# override + prescribed targets). The log tools above edit what HAPPENED;
# these edit what's PLANNED. Kept separate so the model never confuses a
# target with a logged set.
# ─────────────────────────────────────────────────────────────────────────────

_COACH_TOOLS = [
    {
        "name": "refresh_coach_brief",
        "description": (
            "Mark the user's standing Coach-screen directive (shown in "
            "[COACH SCREEN]) for regeneration because THIS message invalidates "
            "it — plans changed ('skipping the gym today', 'traveling this "
            "week', 'I'm sick', 'fasting today'), the goal shifted, or the "
            "day's context no longer matches what the directive assumes. "
            "Do NOT call for routine logging, questions, or messages the "
            "directive already accounts for — the brief is meant to stay "
            "stable through a normal day."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


_PROGRAM_TOOLS = [
    {
        "name": "set_program_day",
        "description": (
            "Mark which day of the user's TRAINING PROGRAM today is. "
            "Use when the user declares or swaps the day: 'today is leg day', "
            "'doing Push A today', 'swap today to back' — AND for rest days: "
            "'taking a rest day', 'going with a rest day today', 'day off' → "
            "day_name='rest'. day_name otherwise must refer to a day in "
            "[TRAINING PROGRAM] (fuzzy match is fine). Overrides the "
            "automatic day detection for TODAY only — tomorrow reverts to normal "
            "rotation. Do NOT call for logged exercises; this is the plan, not the log."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "day_name": {"type": "string", "description": "Program day name, e.g. 'Legs' or 'Day 2 - Back'"},
            },
            "required": ["day_name"],
        },
    },
    {
        "name": "set_program_target",
        "description": (
            "Set or update the PRESCRIBED target (sets × reps, optional working weight) "
            "for an exercise in the user's training program. Use when the user sets a "
            "goal for the PLAN: 'aim for 4x8 at 185 on bench', 'bump my squat target "
            "to 225', 'make curls 3x12'. This edits the PROGRAM — for sets actually "
            "performed use log_exercise / update_exercise_entry instead. exercise_name "
            "must match an exercise in [TRAINING PROGRAM]; pass day_name to narrow the "
            "match when the movement appears on multiple days. "
            "Set ONLY the fields the user stated — '3 sets each' means sets=3 and "
            "NOTHING else; never invent reps (no AMRAP unless they said AMRAP) or "
            "weight. For 'every movement' / 'each exercise' requests pass "
            "exercise_name='all' (with day_name to scope it to one day)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string"},
                "day_name":      {"type": "string", "description": "Optional. The program day containing the exercise."},
                "sets":          {"type": "integer"},
                "reps":          {"type": "string", "description": "e.g. '8' or '8-10'"},
                "weight":        {"type": "number", "description": "target working weight, in the unit the user stated"},
                "weight_unit":   {"type": "string", "enum": ["lbs", "kg"], "default": "lbs"},
            },
            "required": ["exercise_name"],
        },
    },
    {
        "name": "add_program_exercise",
        "description": (
            "ADD an exercise to the user's TRAINING PROGRAM. Use when the user "
            "wants a movement in the plan going forward: 'add dips to my chest "
            "days', 'put face pulls on pull day'. day_name fuzzy-matches program "
            "days ('chest days' matches every day with chest in the name) and the "
            "exercise is added to ALL matching days, skipping days that already "
            "have it. Optionally set a prescription (sets/reps/weight) in the same "
            "call. This edits the PLAN — for something they just performed, use "
            "log_exercise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string"},
                "day_name":      {"type": "string", "description": "Which program day(s) to add it to, e.g. 'chest days', 'Pull'"},
                "category":      {"type": "string", "enum": ["main", "accessory", "cardio"], "default": "accessory"},
                "sets":          {"type": "integer"},
                "reps":          {"type": "string"},
                "weight":        {"type": "number"},
                "weight_unit":   {"type": "string", "enum": ["lbs", "kg"], "default": "lbs"},
            },
            "required": ["exercise_name", "day_name"],
        },
    },
    {
        "name": "remove_program_exercise",
        "description": (
            "REMOVE an exercise from the user's TRAINING PROGRAM: 'drop the leg "
            "press', 'take dips off push day'. Removes from every matching day, "
            "or only days matching day_name when given. This edits the PLAN — to "
            "delete a logged set use delete_exercise_entry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string"},
                "day_name":      {"type": "string", "description": "Optional. Limit removal to matching day(s)."},
            },
            "required": ["exercise_name"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE & MEMORY TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_PROFILE_TOOLS = [
    {
        "name": "update_profile",
        "description": (
            "Update user profile or preference fields. "
            "ONLY call when user explicitly asks to change profile settings, targets, or preferences. "
            "Do NOT call for food, exercise, or weight logging — use the dedicated tools for those. "
            "Profile fields: name, age, sex, height_cm, current_weight_kg, goal_weight_kg, "
            "primary_goal (cut/bulk/maintain/performance/health), "
            "training_experience (beginner/intermediate/advanced), dietary_preferences, "
            "injuries, sport, units_preference, timezone. "
            "Preference fields: coaching_style, accountability_level, calorie_target, "
            "protein_target, wake_time, sleep_time, proactive_messaging_enabled, preferred_language, "
            "reminder_frequency (none/light/moderate/heavy, or relative less/more), "
            "food_logging_mode (quick/moderate/strict, or relative less/more — how much Arnie "
            "confirms food amounts and prep before logging)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": "Key-value pairs using the exact field names listed in the description",
                }
            },
            "required": ["fields"],
        },
    },
    {
        "name": "set_macro_targets",
        "description": (
            "Set the user's daily calorie and/or macro targets in a single call. "
            "Use this ONLY when the user has agreed (explicitly or implicitly: "
            "'sure', 'go ahead', 'sounds good', 'set them for me') to having Arnie "
            "lock in targets. The recommended values come from the [COACH NOTE — "
            "targets_unset] block in the user context: they're already math-derived "
            "from BMR + goal + body comp using the same formula as the dashboard "
            "'Calculate for me' button. "
            "All four fields are optional, but pass at least one. Pass the full set "
            "when accepting Arnie's recommendation; pass only what the user named "
            "(e.g. just `calories=2500`) when they specify a single value. "
            "Saves to user_preferences. Confirm to the user briefly in your reply."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "calories": {"type": "integer", "description": "Daily calorie target (kcal)"},
                "protein":  {"type": "integer", "description": "Daily protein target (grams)"},
                "carbs":    {"type": "integer", "description": "Daily carbohydrate target (grams)"},
                "fat":      {"type": "integer", "description": "Daily fat target (grams)"},
            },
        },
    },
    # update_memory was removed — store_attribute is now the single proactive
    # write path for everything Arnie learns. Multi-fact insights become
    # multiple store_attribute calls (one per discrete fact), and the
    # attribute store is queryable, timestamped, and confidence-tagged.
    # The handler in tool_executor.py remains for backward compatibility
    # with any in-flight tool calls during a deploy.
]


# ─────────────────────────────────────────────────────────────────────────────
# CREATIVE TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_CREATIVE_TOOLS = [
    {
        "name": "generate_image",
        "description": (
            "Generate a visual image when the user EXPLICITLY asks for a visual, "
            "drawing, illustration, or infographic. "
            "Examples: 'show me squat form', 'draw a push day split', 'meal prep infographic'. "
            "DO NOT call proactively. DO NOT call for data visualisation. "
            "ONLY when they explicitly request an image."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt":  {"type": "string", "description": "Detailed image prompt. Include style hint: 'photorealistic' or 'illustration'."},
                "caption": {"type": "string", "description": "Short caption to send with the image (optional)"},
            },
            "required": ["prompt"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY & ANALYTICS TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_HISTORY_TOOLS = [
    {
        "name": "query_history",
        "description": (
            "Pull ANY data point from the user's history — the canonical way to "
            "answer questions about past food, workouts, weight, water, sleep, or "
            "recovery beyond what's already in context. Use whenever the user "
            "asks about a specific past date, day-of-week, or window: "
            "'what did I eat on sunday?', 'show me last monday's workout', "
            "'what was my weight on june 1?', 'how was my sleep this week?', "
            "'water intake yesterday?', 'bench press 3 weeks ago?'. "
            "Do NOT use for data already visible in [TODAY] / [RECENT DAY DETAIL] / "
            "[FOOD HISTORY] context blocks — those are already in front of you. "
            "Period accepts: 'yesterday', 'today', 'N days ago', weekday names "
            "('sunday', 'last monday'), 'this week', 'last week', month-day "
            "('june 7'), ISO dates ('2026-06-07'), date ranges ('2026-06-01:2026-06-07'), "
            "or rolling windows ('last_7', 'last_30', 'last_90')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "calories", "protein", "weight", "workouts", "exercise", "all",
                        "food_entries", "exercise_entries", "water",
                        "body_metrics", "day_detail",
                    ],
                    "description": (
                        "What to pull. PER-ENTRY shapes (return individual rows): "
                        "'food_entries' = every food logged in the period; "
                        "'exercise_entries' = every lift/cardio session; "
                        "'water' = water entries + daily totals; "
                        "'body_metrics' = sleep/HRV/recovery/steps from Apple Health or Whoop; "
                        "'day_detail' = comprehensive single-day or range recap "
                        "(food + exercise + water + totals). "
                        "AGGREGATE shapes (return averages/totals): "
                        "'calories', 'protein', 'workouts' = daily rollups + averages; "
                        "'weight' = body weight time series; "
                        "'exercise' = a specific lift's history (requires exercise_name); "
                        "'all' = compact daily summary."
                    ),
                },
                "period": {
                    "type": "string",
                    "description": (
                        "When. Accepts natural language ('yesterday', 'sunday', "
                        "'last monday', '2 days ago', '120 days ago', "
                        "'3 weeks ago', '6 months ago', 'this week', 'last week', "
                        "'june 7', 'march 15 2024'), ISO dates ('2026-06-07'), "
                        "date ranges ('2026-06-01:2026-06-07'), or rolling windows "
                        "('last_7', 'last_30', 'last_90', 'last_120', 'last_365' — "
                        "any positive 'last_N' works). The DB stores entries "
                        "indefinitely — there is NO upper limit on how far back "
                        "you can pull. If the user asks for a food from 4 months "
                        "ago, call this tool with period='120 days ago' or the "
                        "exact ISO date — don't refuse or say you don't have it. "
                        "CRITICAL — WEEKDAY REQUESTS: when the user names a weekday "
                        "('last Saturday', 'Sunday', 'last Monday'), pass the WEEKDAY "
                        "STRING VERBATIM ('saturday', 'last saturday', 'sunday', "
                        "'last monday'). DO NOT try to compute the ISO date yourself "
                        "and pass that instead — the parser knows today's weekday and "
                        "resolves the correct past date. Computing it yourself causes "
                        "off-by-one bugs (e.g. passing '2026-06-07' for 'last Saturday' "
                        "when June 7 is actually a Sunday). Pass the WORD, not a date."
                    ),
                },
                "exercise_name": {
                    "type": "string",
                    "description": "Required when metric='exercise'. Name of the lift (e.g. 'bench press', 'squat').",
                },
            },
            "required": ["metric", "period"],
        },
    },
    {
        "name": "show_day_recap",
        "description": (
            "Surface a visual snapshot of TODAY'S totals — calories vs target, "
            "macros, water, training done. Call this when the user asks for a "
            "summary, recap, or current standing: 'how am I doing today?', "
            "'recap', 'where am I at', 'show my totals', 'today so far', "
            "'how's the day looking?'. Native clients render it as an inline "
            "card; the card itself is the answer, so keep your text reply "
            "short — one short sentence with a quick take, no number dump. "
            "Do NOT call for past dates (use query_history) or as an opener "
            "the user didn't ask for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "show_food_log",
        "description": (
            "Surface every food entry the user logged on a specific day as an "
            "inline expandable card — compact by default (date + total cal + "
            "entry count), expand to see each item. Call when the user asks "
            "'what have I eaten today?', 'show me my food', 'food log for "
            "yesterday', 'what did I eat on monday?'. For multi-day windows "
            "or trend questions, use query_history instead. Keep your text "
            "reply short — the card is the answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional. 'today', 'yesterday', 'N days ago', weekday name ('monday'), or YYYY-MM-DD. Default = today."
                },
            },
        },
    },
    {
        "name": "show_workout_log",
        "description": (
            "Surface every exercise the user logged on a specific day as an "
            "inline expandable card — compact by default (date + total sets / "
            "minutes + exercise count), expand to see each lift / cardio "
            "block. Call when the user asks 'what did I train today?', "
            "'show me yesterday's workout', 'monday's lifts'. For multi-day "
            "trends or a specific lift's history, use query_history. Keep "
            "your text reply short — the card is the answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional. 'today', 'yesterday', 'N days ago', weekday name, or YYYY-MM-DD. Default = today."
                },
            },
        },
    },
    {
        "name": "suggest_meals",
        "description": (
            "Offer 2–4 meal IDEAS as an inline carousel. Call when the user "
            "asks 'what should I eat?', 'meal ideas', 'something quick for "
            "lunch', etc. Fit the user's remaining macros + time of day + "
            "stated preferences. Each meal carries its macros. Native clients "
            "render the carousel one card at a time with a 'Plan it' button: "
            "tapping it does NOT log the meal — it SELECTS it as the user's "
            "plan for an upcoming meal (they may still need to cook or order "
            "it), and sends a future-tense message like 'Planning to have the "
            "<dish>…'. When that arrives, acknowledge the plan, do NOT log it "
            "yet, and offer to log it once they've eaten. "
            "Keep your text reply short — one line of context, not a numbered "
            "list. DO NOT call to log a meal the user already ate or named "
            "(use log_food); this is for *ideas* to plan. "
            "BE SPECIFIC — every meal is a real, orderable/cookable dish named "
            "with its key components, and every meal carries a `note` with real "
            "context. Bare categories ('steak', 'chicken bowl', 'sashimi') are "
            "useless to the user; name the actual plate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short heading for the carousel — 'Fits 1,100 left', 'Quick lunch ideas', 'High protein options'."
                },
                "meals": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":      {"type": "string", "description": "The SPECIFIC dish with its key components — 'grilled salmon, sweet potato + broccoli', '8oz ribeye, asparagus + rice', 'chicken burrito bowl, double protein + black beans'. NEVER a bare category ('steak', 'chicken bowl')."},
                            "calories":  {"type": "integer"},
                            "protein_g": {"type": "integer"},
                            "carbs_g":   {"type": "integer"},
                            "fats_g":    {"type": "integer"},
                            "note":      {"type": "string", "description": "REQUIRED context, one line: why it fits (the macro it nails / how it slots into what's left) PLUS a prep, portion, or where-to-get cue. 'hits the protein gap clean, ~15 min in a pan.' / 'lean + filling, grab it from the salad spot downstairs.'"},
                            "ingredients": {"type": "array", "items": {"type": "string"}, "description": "3–6 components with rough quantities so the user can actually build or order it — '8oz ribeye', '1 cup asparagus', '½ sweet potato'. Shown inline on the card, so ALWAYS include them — they're what make the idea actionable."},
                            "prep":      {"type": "string", "description": "One or two short lines: how to make it or where to grab it. Shown inline on the card. Include whenever it adds real clarity ('sear 3 min/side, rest 5' / 'sweetgreen, sub double chicken')."},
                        },
                        "required": ["name", "calories", "protein_g", "carbs_g", "fats_g", "note"],
                    },
                },
            },
            "required": ["meals"],
        },
    },
    {
        "name": "suggest_workout",
        "description": (
            "Show today's training plan as an inline carousel of exercises "
            "with target sets×reps and load. Call when the user asks 'what "
            "should I train today?', 'push day?', 'give me a workout', or "
            "when starting a session and they want guidance. Tap a tile = "
            "logs that exercise, so the carousel doubles as the workout "
            "guide. Anchor target loads on the user's recent baseline + "
            "trend (visible in [WORKOUT HISTORY] context); progress 2.5–5 "
            "lb when last week hit all reps clean. Native clients render "
            "the carousel; keep your text reply short — one line on focus "
            "+ flow, no full list. DO NOT call to log a workout already "
            "named (use log_exercise)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short heading — 'Push day', 'Pull · heavy', 'Legs · hypertrophy'."
                },
                "split_day": {
                    "type": "string",
                    "description": "The split this maps to: 'push', 'pull', 'legs', 'upper', 'lower', 'full body', 'cardio', 'rest', or a custom label.",
                },
                "exercises": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":             {"type": "string"},
                            "sets":             {"type": "integer"},
                            "reps":             {"type": "string", "description": "'8' or '8,8,8' for per-set targets."},
                            "target_weight":    {"type": "number"},
                            "weight_unit":      {"type": "string", "enum": ["lbs", "kg"], "default": "lbs"},
                            "duration_minutes": {"type": "number", "description": "For cardio entries."},
                            "is_cardio":        {"type": "boolean"},
                            "note":             {"type": "string", "description": "Optional — '+5 lb vs last week', 'drop set on final', 'finisher'."},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["exercises"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# FOOD DATABASE TOOL
# ─────────────────────────────────────────────────────────────────────────────

_FOOD_DB_TOOLS = [
    {
        "name": "search_food_database",
        "description": (
            "Look up USDA macro data to ANSWER A QUESTION about a food's macros when the user is "
            "NOT asking you to log it (e.g. 'how many calories in a Royo challah roll?', "
            "'what's the protein in this?'). Returns per-100g data plus calculated totals. "
            "CRITICAL: do NOT call this before logging. log_food already enriches every entry with "
            "USDA data automatically — when the user says 'log X', call log_food(food_name=\"X\") "
            "DIRECTLY and the macros are pulled for you in the same step. Calling search first and "
            "then trying to log creates a broken two-step where the food never gets logged. "
            "Do NOT use for staples you already know well (chicken breast, rice, eggs, oats)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "food_name": {
                    "type": "string",
                    "description": "The food or product name to search. Be specific: brand + product name if known.",
                },
                "quantity": {
                    "type": "string",
                    "description": "Optional. The user's serving size (e.g. '1 cup', '200g', '1 bar') to calculate totals.",
                },
            },
            "required": ["food_name"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# ATTRIBUTE & METRIC TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_ATTRIBUTE_TOOLS = [
    {
        "name": "store_attribute",
        "description": (
            "Persist a DURABLE fact you've learned about this user to their permanent profile. "
            "Use for stable, discrete facts: supplement dosages, LAB biomarkers (testosterone, A1c, TSH — a drawn value), "
            "food intolerances, training habits, lifestyle details, behavioral patterns. "
            "ALSO use for the RELATIONAL facts that make coaching personal (these are always kept "
            "front-and-center): the PEOPLE in their life (key like 'lifestyle_person_wife'='Sarah, "
            "does keto', 'lifestyle_person_daughter'='Mia, 3yo'), their deeper WHY (key "
            "'behavior_deeper_why'='wants to be strong for his daughter'), and their BOUNDARIES / "
            "SENSITIVITIES (key 'mental_boundary_x' / 'health_sensitivity_x' — e.g. 'past disordered "
            "eating, avoid calorie-shaming', 'hates being weighed'). Capture these the moment they "
            "come up, from what they actually said. "
            "NEVER store live/transient state — wearable daily metrics (HRV, recovery, RHR, last-night sleep), "
            "today's session, streaks, or anything with its own field (weight, macro targets, wake/sleep times). "
            "Protein bars/shakes/energy drinks are FOOD (category=nutrition), not supplements. "
            "Each call stores ONE fact under one key. "
            "Prefer this over update_memory when the fact has a single value and a clear category. "
            "Use update_memory only for multi-part coaching observations or narrative notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Attribute key in {category}_{noun} format. Examples: "
                        "'health_supplement_creatine_g', 'nutrition_diet_style', "
                        "'fitness_training_time', 'behavior_motivation_driver', "
                        "'health_biomarker_testosterone_ng_dl', 'lifestyle_occupation'."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The value to store (always as a string, even for numbers).",
                },
                "unit": {
                    "type": "string",
                    "description": "Optional unit (mg, hours, lbs, ng/dL, etc.)",
                },
                "category": {
                    "type": "string",
                    "enum": ["nutrition", "fitness", "health", "lifestyle", "behavior", "mental", "custom"],
                },
            },
            "required": ["key", "value", "category"],
        },
    },
    {
        "name": "track_metric",
        "description": (
            "Log a self-reported health or performance metric as a time-series data point. "
            "Use for values the user reports that aren't food or exercise: "
            "resting heart rate, HRV, sleep hours, steps, a race time, VO2max estimate, "
            "blood pressure, body temperature, or any custom personal metric. "
            "Do NOT use for body weight (use log_body_weight) or macros (use log_food)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": (
                        "What was measured. Use snake_case. Examples: 'resting_hr', 'hrv', "
                        "'sleep_hours', 'steps', 'vo2max', '5k_time_seconds', "
                        "'blood_pressure_systolic', 'spo2', 'skin_temp_celsius'."
                    ),
                },
                "value": {"type": "number"},
                "unit": {
                    "type": "string",
                    "description": "Optional. E.g. 'bpm', 'ms', 'hours', 'steps', 'seconds', 'mmHg'.",
                },
                "date": {
                    "type": "string",
                    "description": "Optional. YYYY-MM-DD or 'yesterday'. Defaults to today.",
                },
            },
            "required": ["metric_name", "value"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULING TOOL
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# CLARIFICATION TOOL (T2.2)
# ─────────────────────────────────────────────────────────────────────────────
# When Arnie asks "grilled or fried?" / "what brand?" / "what size?" about a
# food, we record it. The context block surfaces it next turn so Arnie SEES
# what's pending and doesn't re-ask. Auto-resolves the moment log_food fires
# for any food on this user's account.

_CLARIFICATION_TOOLS = [
    {
        "name": "note_food_clarification",
        "description": (
            "Record that you JUST asked the user a clarifying question about a food "
            "before logging it. Call this in the SAME turn you ask the question, "
            "alongside the question text in your reply. Examples of when to call: "
            "'grilled or fried?' about a chicken sandwich, 'which brand?' about a "
            "protein bar, 'what dressing?' about a salad. Do NOT call when you "
            "already have the info needed to log — only when you're explicitly "
            "deferring the log on a question. The next turn's context will show "
            "this as PENDING CLARIFICATION so you don't re-ask. Auto-resolves "
            "when log_food fires (or after 30 min)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The exact question you asked (e.g. 'grilled or fried?').",
                },
                "food_item": {
                    "type": "string",
                    "description": "The food the question is about (e.g. 'chicken sandwich').",
                },
                "kind": {
                    "type": "string",
                    "enum": ["cook_method", "brand", "portion", "ingredient", "other"],
                    "description": "What sort of clarification this is.",
                },
            },
            "required": ["question", "food_item"],
        },
    },
]


_SCHEDULING_TOOLS = [
    {
        "name": "schedule_check_in",
        "description": (
            "Schedule a one-time proactive check-in to this user at a specific time today. "
            "Use when you make a coaching promise: 'I'll check on your workout tonight', "
            "'I'll follow up after dinner', 'remind me to log that later'. "
            "Only schedule for LATER TODAY — the time must be in the future. "
            "The message is generated in your coaching voice at send time, not pre-written."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "send_at": {
                    "type": "string",
                    "description": "Time to send in HH:MM format (24-hour, user's local timezone). Must be later than now.",
                },
                "directive": {
                    "type": "string",
                    "description": (
                        "A coaching directive describing what to check in about — written for you "
                        "to act on at send time, not a user-facing message. "
                        "E.g. 'follow up on whether the evening workout happened — they said 6pm at the gym', "
                        "'ask how dinner went and if they hit protein for the day'."
                    ),
                },
            },
            "required": ["send_at", "directive"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH TOOLS (GATED — inert unless SEARCH_ENABLED=true)
# ─────────────────────────────────────────────────────────────────────────────

# ONE generic web_search tool — no per-usecase search tools (Interface Segregation).
# The name MUST be exactly "web_search" (the prompt's SEARCH_RULES + the dispatch
# elif + the re-voice set all key off this literal).
_SEARCH_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the open web for an external or current fact you don't already "
            "have. Use ONLY for facts not in context or your training: exact macros "
            "for a specific branded/restaurant product, a real-world place/menu "
            "lookup, or recent research/news the user asks you to check. Do NOT use "
            "for anything in the user's logged data, common-food estimates, standard "
            "training/nutrition knowledge, opinions, or coaching judgment. The result "
            "is re-voiced in your own coaching voice — never pasted raw."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":   {"type": "string", "description": "What to look up on the web"},
                "context": {"type": "string", "description": "Optional. The user's situation to bias the lookup (e.g. an injury to keep results safe)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "deep_research",
        "description": (
            "Build a RESEARCHED, multi-part plan that needs several current outside "
            "facts checked and cross-referenced — a researcher runs multiple web "
            "searches, reconciles hours/menus/schedules/options, and returns a "
            "complete plan in your voice. Call for asks like: an eating strategy for "
            "a trip ('flying to Miami tomorrow, plan my food'), training/eating "
            "around a real-world event or race, gym + food options in a specific "
            "place, comparing real products/programs, planning a week around "
            "restaurant menus. DO NOT call for: logging anything, questions answered "
            "from the user's own data or standard coaching knowledge, a single fact "
            "(that's web_search), or a workout program (that's "
            "propose_workout_program). This is your SLOWEST tool (~20s) — call it at "
            "most once per turn, ALWAYS with a heads-up bubble first, and only when "
            "the user clearly wants a researched plan. Put every personal fact that "
            "should shape the plan into key_context — the researcher can't see the "
            "conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "The plan to build, specific and dated: 'eating strategy for Miami trip Wed-Sun, hotel near South Beach, wants to hold 2100 cal'.",
                },
                "key_context": {
                    "type": "string",
                    "description": "Personal facts that must shape the plan: goal + daily targets, training schedule, dietary preferences, schedule constraints, location/home base, family context. Be generous — this is ALL the researcher knows about them.",
                },
            },
            "required": ["objective", "key_context"],
        },
    },
]


# ONE location tool — find_nearby_places. GATED by location_enabled() (default OFF),
# same pattern as web_search. The name MUST be exactly "find_nearby_places" (the
# prompt's LOCATION_RULES + the dispatch elif + the heads-up + the re-voice set all
# key off this literal).
_LOCATION_TOOLS = [
    {
        "name": "find_nearby_places",
        "description": (
            "Find real-world places near the user — restaurants, cafes, gyms, grocery "
            "stores — when they ask 'what's around me', 'where can I eat', 'find a "
            "high-protein spot nearby', etc. Put the place TYPE and any food/goal "
            "intent in the query ('high protein restaurants', 'salad bowls', 'open "
            "gym'). Include the area in the query when you know it ('ramen in "
            "Shoreditch'); if the user shared a precise location, pass lat/lng too. "
            "The result is a short list you re-voice in your own coaching voice with a "
            "pick that fits their targets — never pasted raw. Do NOT use for general "
            "nutrition facts (that's web_search) or anything already in context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to find, with type + intent + area, e.g. 'high protein lunch near Soho'"},
                "lat":   {"type": "number", "description": "Optional. User's latitude if a precise location was shared."},
                "lng":   {"type": "number", "description": "Optional. User's longitude if a precise location was shared."},
            },
            "required": ["query"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# MEMORY — open loops / threads (the followed-through slice of the memory graph)
# ─────────────────────────────────────────────────────────────────────────────

_MEMORY_TOOLS = [
    {
        "name": "remember_thread",
        "description": (
            "File an OPEN LOOP — a real, durable thing in this person's life that "
            "you should carry forward and follow through on, not a one-off. Use for: "
            "an upcoming event/trip/appointment/race, a stated plan or intention "
            "('starting a cut Monday'), a habit change they're attempting, a "
            "constraint with a window (a tweaked shoulder they're resting, travel, "
            "illness), a decision they're weighing, an experiment they're running, a "
            "target/milestone in flight, or a promise YOU just made to check on "
            "something. This is what lets you react like a coach who knows what's "
            "going on ('two trips? which first?') and come back to it later. "
            "DO NOT use for: logging food/exercise/weight (dedicated tools), a "
            "timeless trait or preference (store_attribute — 'likes sushi'), or "
            "small talk. BEFORE creating, check the [OPEN THREADS] block in context: "
            "if this is already there, call update_thread instead of making a "
            "duplicate. Only file what the user actually said or you confidently "
            "infer. One tight summary per loop."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["event", "intention", "habit", "constraint", "promise",
                             "watch_item", "decision", "experiment", "milestone",
                             "state", "other"],
                    "description": "The loop type. event=dated thing happening; intention=a plan; habit=a behavior change; constraint=an injury/limit with a window; promise=something YOU said you'd do; watch_item=a pattern to keep an eye on; decision=something they're weighing; experiment=a trial with a review; milestone=a target in flight; state=an emotional/motivation state to check back on.",
                },
                "summary": {
                    "type": "string",
                    "description": "One tight line, in plain terms, with the details that matter: 'Hamptons trip with wife + baby, wants high-end restaurants', 'resting a tweaked left shoulder ~1 week', 'trying to add protein at breakfast'.",
                },
                "when": {
                    "type": "string",
                    "description": "Optional. The date it happens/starts, as YYYY-MM-DD (compute it from today's date in context — 'tomorrow', 'next Friday'). Omit if there's no specific date.",
                },
                "salience": {
                    "type": "integer",
                    "minimum": 1, "maximum": 5,
                    "description": "How much this should shape coaching, 1-5. Default 3. A trip or an injury is 4-5; a mild 'might try X' is 2.",
                },
            },
            "required": ["kind", "summary"],
        },
    },
    {
        "name": "update_thread",
        "description": (
            "Update or CLOSE an existing open loop from the [OPEN THREADS] block, by "
            "its [#id]. Closing loops matters as much as opening them — when the user "
            "reports back ('the trip was great', 'shoulder's fine now', 'started the "
            "cut') or it's clearly past, resolve it so it stops surfacing. Also use "
            "to add detail or fix a date on a loop they're already tracking (instead "
            "of creating a duplicate via remember_thread)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "integer", "description": "The [#id] from the [OPEN THREADS] block."},
                "status": {
                    "type": "string",
                    "enum": ["done", "dropped"],
                    "description": "Set 'done' when it happened / they followed through / it resolved; 'dropped' when it's cancelled or no longer relevant. Omit to just edit fields.",
                },
                "summary": {"type": "string", "description": "Optional. Replace the summary (e.g. add newly-shared detail)."},
                "when": {"type": "string", "description": "Optional. Correct the date, YYYY-MM-DD."},
                "salience": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Optional. Re-rate importance 1-5."},
            },
            "required": ["thread_id"],
        },
    },
]


ALL_TOOLS = (
    _NUTRITION_TOOLS
    + _FITNESS_TOOLS
    + _DAY_TOOLS
    + _PROGRAM_TOOLS
    + _COACH_TOOLS
    + _PROFILE_TOOLS
    + _CREATIVE_TOOLS
    + _HISTORY_TOOLS
    + _FOOD_DB_TOOLS
    + _ATTRIBUTE_TOOLS
    + _MEMORY_TOOLS
    + _CLARIFICATION_TOOLS
    + _SCHEDULING_TOOLS
)


def _active_tools() -> list[dict]:
    """The single gating source of truth: the always-on tools plus web_search
    ONLY when search is enabled. ONE gate decision, consumed by both formats."""
    from db.queries import search_enabled, location_enabled
    return (
        ALL_TOOLS
        + (_SEARCH_TOOLS if search_enabled() else [])
        + (_LOCATION_TOOLS if location_enabled() else [])
    )


def build_tools() -> list[dict]:
    """Return the active tool list for the Anthropic API (flag-aware)."""
    return _active_tools()


def build_tools_openai() -> list[dict]:
    """Same active set as build_tools(), reshaped to OpenAI format. MUST delegate
    to the single gate so the OpenAI path can never silently darken vs. Anthropic."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in build_tools()
    ]
