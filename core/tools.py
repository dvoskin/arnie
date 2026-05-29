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
            "Call whenever the user mentions eating or drinking anything (except plain water). "
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
            },
            "required": ["food_name", "quantity", "calories", "protein", "carbs", "fats", "confidence"],
        },
    },
    {
        "name": "update_food_entry",
        "description": (
            "CORRECT an existing food entry already in today's log. "
            "Use when the user is fixing values for food already logged. "
            "Find the entry by its [#id] in the context. "
            "DO NOT call log_food for corrections — that creates a duplicate. "
            "Only include fields the user is actually changing."
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
        "name": "log_water",
        "description": "Log water intake when user mentions drinking water.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount_ml": {"type": "number"},
                "amount_oz": {"type": "number"},
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
            "Log ONE exercise to today's workout. "
            "Call once per exercise when the user reports completing sets. "
            "For multiple exercises, one call per exercise."
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
            },
            "required": ["exercise_name"],
        },
    },
    {
        "name": "update_exercise_entry",
        "description": (
            "CORRECT an existing exercise entry already in today's log. "
            "Use when user wants to fix weight, sets, reps, or name. "
            "Find the entry by its [#id] in the context. "
            "DO NOT call log_exercise for corrections — that creates a duplicate."
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
            "Log a body-weight measurement. "
            "Call ONLY when the user explicitly states their body weight. "
            "Do NOT call for food weights or exercise weights."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weight": {"type": "number"},
                "unit":   {"type": "string", "enum": ["lbs", "kg"]},
            },
            "required": ["weight", "unit"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# DAY MANAGEMENT TOOLS
# ─────────────────────────────────────────────────────────────────────────────

_DAY_TOOLS = [
    {
        "name": "close_day",
        "description": (
            "Close the current day's log. "
            "ONLY call when user explicitly says 'close the day', 'end my day', 'wrap up today'. "
            "Do NOT call for any other reason."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reopen_day",
        "description": (
            "Reopen a closed day's log so the user can continue logging. "
            "Call automatically when day is CLOSED and user wants to log — "
            "then immediately proceed with the logging tool."
        ),
        "input_schema": {"type": "object", "properties": {}},
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
            "protein_target, wake_time, sleep_time, proactive_messaging_enabled, preferred_language."
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
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

ALL_TOOLS = (
    _NUTRITION_TOOLS
    + _FITNESS_TOOLS
    + _DAY_TOOLS
    + _PROFILE_TOOLS
    + _CREATIVE_TOOLS
)


def build_tools() -> list[dict]:
    """Return the full tool list for the Anthropic API."""
    return ALL_TOOLS


def build_tools_openai() -> list[dict]:
    """Convert to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in ALL_TOOLS
    ]
