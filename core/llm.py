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


def ARNIE_TOOLS() -> list:
    """The active tool list (flag-aware). Was a module-level import-time snapshot;
    now that build_tools() is gated by search_enabled(), a frozen snapshot would be
    stale/misleading, so this delegates to the single source of truth per call."""
    return build_tools()


def _oai_tools():
    """OpenAI-format tool list from core/tools.py."""
    return build_tools_openai()


# ── Public API ────────────────────────────────────────────────────────────────

async def chat(
    messages: List[Dict[str, Any]],
    system: str,
    tools: bool = True,
    max_tokens: int = 1024,
    model: Optional[str] = None,
    stream_handler: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Single-turn chat. Returns:
        {text, tool_calls, raw_content, stop_reason}
    raw_content is the list of Anthropic content blocks (needed for multi-turn).
    Pass model= to override the default (e.g. use Haiku for cheap low-latency calls).

    stream_handler — optional async callable(text_delta: str) → None. When provided
    AND using the Anthropic provider, the call uses messages.stream() and invokes
    stream_handler for every text delta as it arrives. The return value is identical
    to the non-streaming path (full text + tool_calls + stop_reason), so callers can
    consume it the same way; the deltas are a SEPARATE side channel. The OpenAI path
    ignores stream_handler (it's the Telegram-streaming feature, Anthropic-only).
    """
    # If OpenAI is the configured provider, use it directly.
    if LLM_PROVIDER() != "anthropic" and OPENAI_API_KEY():
        return await _openai_chat(messages, system, tools, max_tokens)

    # Default: Anthropic (already retries 429/500/529/connection internally).
    # If it STILL fails (e.g. a sustained outage) and an OpenAI key is configured,
    # fall back to OpenAI for this turn so Arnie keeps responding instead of going
    # dark. See AUDIT.md #8.
    try:
        return await _anthropic_chat(messages, system, tools, max_tokens,
                                     model=model, stream_handler=stream_handler)
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
    stream_handler: Optional[Any] = None,
) -> str:
    """
    Second turn after tool use — feed results back and get final text.
    Only used when the first turn had no text response.

    stream_handler — optional async callable(text_delta: str) → None. When
    provided, the follow-up streams its text via messages.stream() and the
    deltas are sent to stream_handler as they arrive. Return value is the
    final concatenated text (same as the non-streaming path).
    """
    if LLM_PROVIDER() == "anthropic" or not OPENAI_API_KEY():
        try:
            return await _anthropic_follow_up(
                messages, raw_assistant_content, tool_calls, tool_results, system,
                max_tokens, stream_handler=stream_handler,
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


# HEIC/HEIF (default iOS camera format) — recognizable but NOT accepted by the
# vision API. We detect it only to log a clear reason instead of a raw 400.
_HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc",
                b"hevm", b"hevs", b"heif", b"mif1", b"msf1"}


def _sniff_image_mime(data: bytes) -> Optional[str]:
    """Best-effort image media-type from the leading magic bytes.

    Returns an Anthropic-supported type (jpeg/png/gif/webp) or None when the
    format is unrecognized or unsupported. The vision API hard-400s on any
    mismatch between the declared media_type and the actual bytes (iOS
    screenshots are PNG but clients routinely tag them image/jpeg), so we sniff
    rather than trust the caller's hint.
    """
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        logger.warning("analyze_image: HEIC/HEIF is unsupported by the vision "
                       "API — client must transcode to JPEG/PNG before upload")
    return None


async def analyze_image(image_data: bytes, prompt: str,
                        mime_type: str = "image/jpeg",
                        max_tokens: int = 512) -> str:
    """Analyze an image with Claude vision.

    max_tokens override useful for: cheap classify calls (~20 tokens) or
    extractor calls that may produce long structured output (blood panels,
    workout logs, food diaries — bump to 1024+).
    """
    if not ANTHROPIC_API_KEY():
        logger.warning("ANTHROPIC_API_KEY not set — image analysis unavailable")
        return ""
    import base64
    client = _get_anthropic()
    # Never trust the caller's media_type hint — sniff the real format so a
    # PNG-sent-as-JPEG (iOS screenshots) can't 400 the vision call.
    detected = _sniff_image_mime(image_data)
    if detected and detected != mime_type:
        logger.info(f"analyze_image: overrode media_type hint {mime_type!r} "
                    f"with sniffed {detected!r}")
    media_type = detected or mime_type
    b64 = base64.standard_b64encode(image_data).decode()
    response = await client.messages.create(
        model=DEFAULT_MODEL(),
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                                              "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text


# ── Anthropic internals ───────────────────────────────────────────────────────

async def _anthropic_chat(messages, system, use_tools, max_tokens, model=None,
                          stream_handler=None):
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

    # Streaming path — called when a delta handler is provided (Telegram). The
    # final message is identical to the non-streaming path; the deltas are a
    # SEPARATE side channel for the caller to flush bubbles as they land. If
    # stream_handler raises, log and continue collecting — the caller's bubbles
    # may be incomplete, but the final return value (text + tool_calls) stays
    # correct so the rest of the pipeline keeps working.
    if stream_handler is not None:
        async with client.messages.stream(**kwargs) as stream:
            async for delta in stream.text_stream:
                try:
                    await stream_handler(delta)
                except Exception as e:
                    logger.warning(f"stream_handler raised on delta: {e}")
            final = await stream.get_final_message()

        text_parts, tool_calls = [], []
        for block in final.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({"name": block.name, "input": block.input, "id": block.id})
        return {
            "text": "\n".join(text_parts),
            "tool_calls": tool_calls,
            "raw_content": final.content,
            "stop_reason": final.stop_reason,
        }

    # Non-streaming path — existing buffered behavior.
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
                                tool_results, system, max_tokens,
                                stream_handler=None):
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

    kwargs = dict(
        model=DEFAULT_MODEL(),
        max_tokens=max_tokens,
        system=system,
        messages=follow_up_messages,
    )

    if stream_handler is not None:
        async with client.messages.stream(**kwargs) as stream:
            async for delta in stream.text_stream:
                try:
                    await stream_handler(delta)
                except Exception as e:
                    logger.warning(f"follow-up stream_handler raised: {e}")
            final = await stream.get_final_message()
        return "".join(b.text for b in final.content if b.type == "text")

    resp = await client.messages.create(**kwargs)
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
