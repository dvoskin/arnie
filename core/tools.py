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
                "meal_type":  {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack", "pre_workout", "post_workout"], "description": "Optional. Which meal slot this fits. Infer from time of day + user history if not stated."},
                "alcohol_units": {"type": "number", "description": "Optional. Standard alcohol units (1 unit ≈ 1 beer / 1 glass wine / 1 shot)."},
                "from_photo": {"type": "boolean", "description": "True when logging from a food photo — sets confidence ≤0.75 and estimated=true automatically."},
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
]


# ─────────────────────────────────────────────────────────────────────────────
# FITNESS TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_FITNESS_TOOLS = [
    {
        "name": "log_exercise",
        "description": (
            "Log a strength/cardio entry to the workout. "
            "SETS WITH THE SAME LOAD: one call — set sets=N and reps='8,8,7' (comma list "
            "captures per-set reps). e.g. '3x8 @ 135' -> sets=3, reps='8,8,8', weight=135. "
            "SETS WITH DIFFERENT LOADS: one call PER load — each weight is its own entry. "
            "e.g. 'bench 135x10, 145x8, 155x6' -> THREE calls: (sets=1,reps=10,weight=135), "
            "(sets=1,reps=8,weight=145), (sets=1,reps=6,weight=155). The dashboard groups "
            "same-named entries back into one exercise with each set shown separately. "
            "Different exercises: one call each."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name":     {"type": "string"},
                "sets":              {"type": "integer"},
                "reps":              {"type": "string", "description": "e.g. '5' or '5,5,5,4'"},
                "weight":            {"type": "number", "description": "in the unit the user specified"},
                "weight_unit":       {"type": "string", "enum": ["lbs", "kg"], "default": "lbs"},
                "rir":               {"type": "integer", "description": "reps in reserve"},
                "duration_minutes":  {"type": "number"},
                "cardio_type":       {"type": "string", "description": "e.g. 'incline walk', 'HIIT'"},
                "is_cardio":         {"type": "boolean"},
                "date":              {"type": "string", "description": "Optional. Log to a specific date. Use 'yesterday', '2 days ago', or YYYY-MM-DD. Only set when user explicitly mentions a past day."},
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
            "'I weigh X', 'weighed in at X', 'scale said X', 'my weight is X'. "
            "NEVER call for exercise or lifting weights — "
            "'benched 225', 'squatted 315', 'hit 185 on bench' → use log_exercise instead. "
            "NEVER call based on food photo macro estimates — "
            "protein grams, fat grams, or calorie counts in a meal analysis are NOT body weight. "
            "Do NOT call for food weights, portion sizes, or nutrition label values. "
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
            },
            "required": ["weight", "unit"],
        },
    },
]


# Day close/reopen was deleted in T1.1: every day (today or past) is always
# editable via the date= field on log_food / log_exercise / update_*_entry.
# No status transition, no "closed" state. _DAY_TOOLS kept as empty list so
# ALL_TOOLS below can stay structurally identical.

_DAY_TOOLS: list = []


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
        "name": "update_memory",
        "description": (
            "Persist an important behavioral pattern, preference, or coaching note "
            "to the user's permanent memory. Use sparingly — only for durable insights."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "updates":   {"type": "string", "description": "Markdown-formatted memory note"},
                "reasoning": {"type": "string", "description": "Why this is worth remembering"},
            },
            "required": ["updates", "reasoning"],
        },
    },
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
            "Persist a structured fact you've learned about this user to their permanent profile. "
            "Use for clear, discrete, queryable facts: supplement dosages, biomarkers (testosterone, HRV), "
            "food intolerances, training habits, lifestyle details, behavioral patterns. "
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
]


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

ALL_TOOLS = (
    _NUTRITION_TOOLS
    + _FITNESS_TOOLS
    + _DAY_TOOLS
    + _PROFILE_TOOLS
    + _CREATIVE_TOOLS
    + _HISTORY_TOOLS
    + _FOOD_DB_TOOLS
    + _ATTRIBUTE_TOOLS
    + _CLARIFICATION_TOOLS
    + _SCHEDULING_TOOLS
)


def _active_tools() -> list[dict]:
    """The single gating source of truth: the always-on tools plus web_search
    ONLY when search is enabled. ONE gate decision, consumed by both formats."""
    from db.queries import search_enabled
    return ALL_TOOLS + (_SEARCH_TOOLS if search_enabled() else [])


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
