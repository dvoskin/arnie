"""
Lightweight LLM wrapper. Supports Anthropic (default) and OpenAI.
All public functions are async.

Tools are imported from core/tools.py — do not define them here.
Prompt caching is enabled for Anthropic: the system prompt block uses
cache_control={"type": "ephemeral"} for ~80% token cost reduction on
system prompt hits (5-minute TTL on Anthropic's side).
"""
import os
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key) or default


def LLM_PROVIDER() -> str:
    return _env("LLM_PROVIDER", "anthropic")


def ANTHROPIC_API_KEY() -> str:
    return _env("ANTHROPIC_API_KEY")


def OPENAI_API_KEY() -> str:
    return _env("OPENAI_API_KEY")


def DEFAULT_MODEL() -> str:
    return _env("DEFAULT_MODEL", "claude-sonnet-4-6")

_anthropic = None
_openai = None


def _get_anthropic():
    global _anthropic
    key = ANTHROPIC_API_KEY()
    if _anthropic is None or not key:
        from anthropic import AsyncAnthropic
        # Built-in resilience: the SDK retries 429/500/529/connection errors with
        # exponential backoff and times out a stuck request instead of hanging the
        # whole turn. Without this, a single transient API blip became a user-facing
        # "something went wrong" (a real glitch source). See AUDIT.md P0 #3.
        _anthropic = AsyncAnthropic(api_key=key or None, max_retries=3, timeout=45.0)
    return _anthropic


def _get_openai():
    global _openai
    key = OPENAI_API_KEY()
    if _openai is None:
        from openai import AsyncOpenAI
        _openai = AsyncOpenAI(api_key=key or None)
    return _openai


# ── Tool definitions — imported from core/tools.py ────────────────────────────
from core.tools import build_tools, build_tools_openai

# Keep ARNIE_TOOLS as a module-level alias for any external references
ARNIE_TOOLS = build_tools()

# Legacy list — kept so nothing outside this module breaks during transition
_LEGACY_TOOLS = [
    {
        "name": "log_food",
        "description": (
            "Log ONE food or meal item to the daily nutrition log. "
            "Call this whenever the user mentions eating or drinking anything (except plain water). "
            "Call ONCE per distinct food item — do NOT split one item across multiple calls. "
            "If the user mentions multiple foods, call this once per food (e.g. eggs AND toast = 2 calls)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "food_name": {"type": "string"},
                "quantity": {"type": "string", "description": "e.g. '1 cup', '200g', '2 slices'"},
                "calories": {"type": "number"},
                "protein": {"type": "number", "description": "grams"},
                "carbs": {"type": "number", "description": "grams"},
                "fats": {"type": "number", "description": "grams"},
                "fiber": {"type": "number", "description": "grams, optional"},
                "confidence": {
                    "type": "number",
                    "description": "0.0–1.0. 0.9+ for well-known foods, 0.6–0.8 for estimates",
                },
                "estimated": {"type": "boolean"},
            },
            "required": ["food_name", "quantity", "calories", "protein", "carbs", "fats",
                         "confidence"],
        },
    },
    {
        "name": "log_exercise",
        "description": (
            "Log ONE exercise to today's workout. "
            "Call once per exercise when the user reports completing a workout or individual sets. "
            "For multiple exercises, make one call per exercise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string"},
                "sets": {"type": "integer"},
                "reps": {"type": "string", "description": "e.g. '5' or '5,5,5,4'"},
                "weight": {"type": "number", "description": "in the unit the user specified"},
                "weight_unit": {"type": "string", "enum": ["lbs", "kg"], "default": "lbs"},
                "rir": {"type": "integer", "description": "reps in reserve"},
                "duration_minutes": {"type": "number"},
                "cardio_type": {"type": "string", "description": "e.g. 'incline walk', 'HIIT'"},
                "is_cardio": {"type": "boolean"},
            },
            "required": ["exercise_name"],
        },
    },
    {
        "name": "log_body_weight",
        "description": (
            "Log a body-weight measurement. "
            "Call ONLY when the user explicitly states their body weight (e.g. 'I weigh 191 lbs', "
            "'weight 190 this morning'). Do NOT call for food weights or exercise weights."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weight": {"type": "number"},
                "unit": {"type": "string", "enum": ["lbs", "kg"]},
            },
            "required": ["weight", "unit"],
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
    {
        "name": "close_day",
        "description": (
            "Close the current day's log. "
            "ONLY call this when the user explicitly says 'close the day', 'close day', "
            "'end my day', 'wrap up today', or a direct equivalent. "
            "Do NOT call for any other reason."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reopen_day",
        "description": (
            "Reopen a closed day's log so the user can continue logging. "
            "Call this automatically when the day status is CLOSED and the user wants to log "
            "food, exercise, or water — then immediately proceed with the logging tool. "
            "Also call when the user says 'reopen', 'open the day back up', etc."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_memory",
        "description": (
            "Persist an important behavioral pattern, preference, or coaching note "
            "to the user's permanent memory file. Use sparingly — only for durable insights."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "updates": {"type": "string", "description": "Markdown-formatted memory note"},
                "reasoning": {"type": "string", "description": "Why this is worth remembering"},
            },
            "required": ["updates", "reasoning"],
        },
    },
    {
        "name": "update_food_entry",
        "description": (
            "CORRECT an existing food entry that's already in today's log. "
            "Use this when the user is fixing or updating values for a food they "
            "already told you about — e.g. 'actually that bowl was 700 cal not 550', "
            "'the chicken was 8oz not 4oz', 'change my breakfast eggs to 4 instead of 3'. "
            "Find the matching entry by its [#id] in the context. "
            "DO NOT call log_food for corrections — that creates a duplicate. "
            "Only include fields the user is actually changing. The system "
            "auto-adjusts the daily totals by the delta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "integer",
                    "description": "The [#id] of the food entry to update, shown in the today's log context.",
                },
                "food_name": {"type": "string"},
                "quantity": {"type": "string"},
                "calories": {"type": "number"},
                "protein": {"type": "number"},
                "carbs": {"type": "number"},
                "fats": {"type": "number"},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "delete_food_entry",
        "description": (
            "REMOVE a food entry from today's log. Use when the user says "
            "'delete my lunch', 'remove the coffee', 'I didn't actually eat that'. "
            "Find the matching entry by its [#id] in the context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "update_exercise_entry",
        "description": (
            "CORRECT an existing exercise entry that's already in today's log. "
            "Use when the user wants to fix weight, sets, reps, or name — e.g. "
            "'actually I did 4 sets not 3', 'the squat weight was 185 not 175', "
            "'change my bench to 3×6'. Find the matching entry by its [#id] in the context. "
            "DO NOT call log_exercise for corrections — that creates a duplicate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "integer",
                    "description": "The [#id] of the exercise entry to update.",
                },
                "exercise_name": {"type": "string"},
                "sets": {"type": "integer"},
                "reps": {"type": "string", "description": "e.g. '5' or '5,5,5,4'"},
                "weight": {"type": "number", "description": "Weight in lbs"},
                "duration_minutes": {"type": "number"},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "delete_exercise_entry",
        "description": (
            "REMOVE an exercise entry from today's log. Use when the user says "
            "'delete my bench press', 'remove that set', 'I didn't do that exercise'. "
            "Find the matching entry by its [#id] in the context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer"},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate a visual image when the user EXPLICITLY asks for a visual, "
            "drawing, illustration, infographic, or diagram. "
            "Examples: 'show me what good squat form looks like', "
            "'draw me a push day split', 'make a meal prep infographic', "
            "'visualize my weekly workout plan'. "
            "DO NOT call this proactively. DO NOT call for data viz (the user has a "
            "/dash dashboard for that). ONLY when they explicitly request an image."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed image-generation prompt. Be specific about style, content, layout. Include 'photorealistic' or 'illustration' as a style hint.",
                },
                "caption": {
                    "type": "string",
                    "description": "Short caption to send with the image (optional)",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "update_profile",
        "description": (
            "Update user profile or preference fields. "
            "ONLY call this when the user explicitly asks to change their profile settings, "
            "targets, or preferences (e.g. 'update my calorie target', 'change my goal'). "
            "Do NOT call this for food logging, exercise logging, or weight logging — use the "
            "dedicated log_food, log_exercise, and log_body_weight tools for those. "
            "Exact field names: name, age, sex (male/female), height_cm, current_weight_kg, "
            "goal_weight_kg, primary_goal (cut/bulk/maintain/performance/health), "
            "training_experience (beginner/intermediate/advanced), dietary_preferences, "
            "injuries, timezone, onboarding_completed (boolean). "
            "Preference fields: coaching_style, accountability_level, calorie_target, "
            "protein_target, wake_time, sleep_time, proactive_messaging_enabled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": "Key-value pairs using the exact column names listed in the description",
                }
            },
            "required": ["fields"],
        },
    },
]
# End of legacy list — tools are now sourced from core/tools.py via build_tools()


def _oai_tools():
    """OpenAI-format tool list from core/tools.py."""
    return build_tools_openai()


def _legacy_oai():
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


# ── Public API ────────────────────────────────────────────────────────────────

async def chat(
    messages: List[Dict[str, Any]],
    system: str,
    tools: bool = True,
    max_tokens: int = 1024,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Single-turn chat. Returns:
        {text, tool_calls, raw_content}
    raw_content is the list of Anthropic content blocks (needed for multi-turn).
    Pass model= to override the default (e.g. use Haiku for cheap low-latency calls).
    """
    # If OpenAI is the configured provider, use it directly.
    if LLM_PROVIDER() != "anthropic" and OPENAI_API_KEY():
        return await _openai_chat(messages, system, tools, max_tokens)

    # Default: Anthropic (already retries 429/500/529/connection internally).
    # If it STILL fails (e.g. a sustained outage) and an OpenAI key is configured,
    # fall back to OpenAI for this turn so Arnie keeps responding instead of going
    # dark. See AUDIT.md #8.
    try:
        return await _anthropic_chat(messages, system, tools, max_tokens, model=model)
    except Exception as e:
        if OPENAI_API_KEY():
            logger.warning(f"Anthropic chat failed ({e}); falling back to OpenAI.")
            try:
                return await _openai_chat(messages, system, tools, max_tokens)
            except Exception as e2:
                logger.error(f"OpenAI fallback also failed: {e2}")
                raise
        raise


async def chat_follow_up(
    messages: List[Dict[str, Any]],
    raw_assistant_content: Any,
    tool_calls: List[Dict],
    tool_results: Dict[str, str],
    system: str,
    max_tokens: int = 512,
) -> str:
    """
    Second turn after tool use — feed results back and get final text.
    Only used when the first turn had no text response.
    """
    if LLM_PROVIDER() == "anthropic" or not OPENAI_API_KEY():
        try:
            return await _anthropic_follow_up(
                messages, raw_assistant_content, tool_calls, tool_results, system, max_tokens
            )
        except Exception as e:
            # The follow-up only refines the post-tool confirmation; on failure
            # return "" so the caller falls back to deterministic_confirmation
            # (a real "logged X, you're at Y" message) instead of erroring.
            logger.warning(f"Anthropic follow-up failed ({e}); using deterministic confirmation.")
            return ""
    # OpenAI path: the caller already has first-pass text; no follow-up needed.
    return ""


async def transcribe_voice(audio_data: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe a voice note via OpenAI Whisper."""
    if not OPENAI_API_KEY():
        logger.warning("OPENAI_API_KEY not set — voice transcription unavailable")
        return ""
    import io
    client = _get_openai()
    buf = io.BytesIO(audio_data)
    buf.name = filename
    transcript = await client.audio.transcriptions.create(model="whisper-1", file=buf)
    return transcript.text
async def text_to_speech(text: str, voice: str = "onyx") -> Optional[bytes]:
    if not OPENAI_API_KEY():
        return None
    try:
        import io
        client = _get_openai()
        response = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return response.content
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        return None


async def voice_variant(text: str, name: str = "", language: str = "English") -> str:
    system = (
        "You are a fitness coach. Rewrite the message as natural SPOKEN audio — "
        "no formatting, no '|||'. Under 25 words. Different words, same message."
    )
    name_hint = f" Their name is {name}." if name else ""
    prompt = f"Original: {text}{name_hint}\nLanguage: {language}\nSpoken version:"
    try:
        result = await chat(
            messages=[{"role": "user", "content": prompt}],
            system=system, tools=False, max_tokens=80,
            model="claude-haiku-4-5-20251001",
        )
        return (result.get("text") or "").strip() or text
    except Exception:
        return text

async def generate_image(prompt: str, size: str = "1024x1024") -> Optional[str]:
    """
    Generate an image via OpenAI DALL-E 3. Returns a URL valid for ~1 hour,
    or None if the API key is missing or the request fails.
    """
    if not OPENAI_API_KEY():
        logger.warning("OPENAI_API_KEY not set — image generation unavailable")
        return None
    try:
        client = _get_openai()
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality="standard",
            n=1,
        )
        return response.data[0].url
    except Exception as e:
        logger.error(f"DALL-E image generation failed: {e}")
        return None


async def analyze_image(image_data: bytes, prompt: str,
                        mime_type: str = "image/jpeg") -> str:
    """Analyze an image with Claude vision."""
    if not ANTHROPIC_API_KEY():
        logger.warning("ANTHROPIC_API_KEY not set — image analysis unavailable")
        return ""
    import base64
    client = _get_anthropic()
    b64 = base64.standard_b64encode(image_data).decode()
    response = await client.messages.create(
        model=DEFAULT_MODEL(),
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                                              "media_type": mime_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text


# ── Anthropic internals ───────────────────────────────────────────────────────

async def _anthropic_chat(messages, system, use_tools, max_tokens, model=None):
    client = _get_anthropic()

    # Prompt caching: mark the system prompt block as cacheable.
    # Anthropic caches the first 1024+ token prefix for 5 minutes.
    # With a ~400-line system prompt this saves ~80% on system prompt tokens.
    system_block = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    kwargs: Dict[str, Any] = dict(
        model=model or DEFAULT_MODEL(),
        max_tokens=max_tokens,
        system=system_block,
        messages=messages,
    )
    if use_tools:
        kwargs["tools"] = build_tools()

    resp = await client.messages.create(**kwargs)

    text_parts, tool_calls = [], []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({"name": block.name, "input": block.input, "id": block.id})

    return {
        "text": "\n".join(text_parts),
        "tool_calls": tool_calls,
        "raw_content": resp.content,
        "stop_reason": resp.stop_reason,
    }


async def _anthropic_follow_up(messages, raw_assistant_content, tool_calls,
                                tool_results, system, max_tokens):
    client = _get_anthropic()

    tool_result_blocks = [
        {"type": "tool_result", "tool_use_id": tc["id"],
         "content": tool_results.get(tc["name"], "Done")}
        for tc in tool_calls
    ]

    follow_up_messages = messages + [
        {"role": "assistant", "content": raw_assistant_content},
        {"role": "user", "content": tool_result_blocks},
    ]

    resp = await client.messages.create(
        model=DEFAULT_MODEL(),
        max_tokens=max_tokens,
        system=system,
        messages=follow_up_messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# ── OpenAI internals ──────────────────────────────────────────────────────────

async def _openai_chat(messages, system, use_tools, max_tokens):
    client = _get_openai()
    oai_messages = [{"role": "system", "content": system}] + messages

    kwargs: Dict[str, Any] = dict(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        max_tokens=max_tokens,
        messages=oai_messages,
    )
    if use_tools:
        kwargs["tools"] = _oai_tools()
        kwargs["tool_choice"] = "auto"

    resp = await client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append({
                "name": tc.function.name,
                "input": json.loads(tc.function.arguments),
                "id": tc.id,
            })

    return {
        "text": msg.content or "",
        "tool_calls": tool_calls,
        "raw_content": None,
        "stop_reason": resp.choices[0].finish_reason,
    }
