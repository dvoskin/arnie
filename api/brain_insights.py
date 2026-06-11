"""
AI-generated coaching insights for the Brain tab.

For each lobe the user opens (NUTRITION, FITNESS, HEALTH, …), this calls
Claude to write 2–4 sentences in Arnie's voice that reference the user's
ACTUAL parameter values and explain how Arnie uses them to coach THEM —
not generic platitudes.

The mindmap currently ships with a static `coaching:` string per lobe as a
fallback (see LOBE_ORDER in api/brain_page.py). When the API key is set and
the call succeeds, that fallback is replaced by personalized prose like:

    "Because you eat banana + Barebells bars pre-workout and target 180g
    protein/day, when you ask 'what should I eat after the gym?' I default
    to your Oikos shake + honey combo over generic recovery food."

Surface: POST /api/brain/insights/{token}  body: {"lobe_id": "nutrition"}
Returns: {"insight": "...", "model": "...", "generated_at": "..."}

We re-derive the lobe data from the user's actual profile server-side rather
than trusting the client payload — keeps the prompt grounded and prevents a
manipulated browser from making Arnie say arbitrary things.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.llm import _get_anthropic


# Tiny per-session in-memory cache keyed by (user_id, lobe_id, lobe_signature).
# Signature is a tuple of (label, value) pairs so changes in the underlying
# parameters invalidate the cached insight automatically.
_CACHE: dict[tuple, str] = {}

# Use Haiku for snappy responses. The insight is short (~3 sentences) and
# the call lives in the user's interactive loop, so latency matters more
# than reasoning depth.
_MODEL = "claude-haiku-4-5-20251001"


def _format_nodes(nodes: list[dict]) -> str:
    """Render the lobe's nodes as a compact bullet list for the prompt."""
    lines = []
    for n in nodes:
        label = n.get("label") or n.get("key") or "?"
        if n.get("chips"):
            value = ", ".join(str(c) for c in n["chips"])
        else:
            value = (n.get("value") or "").strip() or "(still learning)"
        lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def _signature(nodes: list[dict]) -> tuple:
    """Stable cache key derived from the lobe's parameter values."""
    sig = []
    for n in nodes:
        v = tuple(n["chips"]) if n.get("chips") else (n.get("value") or "")
        sig.append((n.get("label"), v, n.get("state")))
    return tuple(sig)


def _system_prompt() -> str:
    return (
        "You are Arnie — the user's AI fitness/nutrition coach. They are looking at "
        "the brain visualization of what you've learned about them. They tapped into "
        "one specific section to understand how you actually USE that data to coach "
        "THEM. Make that crystal clear in 3 to 4 short bullet points."
        "\n\nRules:"
        "\n- Output exactly 3-4 bullets. Each bullet starts with \"• \" (bullet + space)."
        "\n- One newline between bullets. No header, no intro, no outro."
        "\n- Use \"you\" — address them directly."
        "\n- Each bullet: ≤ 15 words. Lead with the verb (e.g. \"Default to…\", \"Pace nudges…\")."
        "\n- Reference their ACTUAL values — exact numbers, specific foods, specific limitations."
        "\n- Say what you concretely DO with the data, not what data you have."
        "\n- No hedging, no \"As your coach\", no \"I use this to\". Just the action."
    )


def _user_prompt(lobe_name: str, lobe_short: str, nodes: list[dict]) -> str:
    return (
        f"Section: {lobe_name} ({lobe_short})\n\n"
        f"What I know about you here:\n{_format_nodes(nodes)}\n\n"
        f"Write 3-4 concrete bullet points telling them how you use "
        f"these {lobe_short.lower()} parameters to coach them specifically. "
        f"Each bullet ≤ 15 words, leads with a verb."
    )


async def generate_lobe_insight(
    user_id: int,
    lobe_id: str,
    lobe_name: str,
    lobe_short: str,
    nodes: list[dict],
) -> Optional[dict]:
    """Generate a personalized coaching paragraph for the given lobe.

    Returns ``{"insight": str, "model": str, "generated_at": iso}`` on success,
    ``None`` on failure (caller falls back to the static coaching string).
    """
    if not nodes:
        return None

    cache_key = (user_id, lobe_id, _signature(nodes))
    if cache_key in _CACHE:
        return {
            "insight": _CACHE[cache_key],
            "model": _MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cached": True,
        }

    client = _get_anthropic()
    try:
        resp = await client.messages.create(
            model=_MODEL,
            max_tokens=300,
            system=_system_prompt(),
            messages=[{"role": "user", "content": _user_prompt(lobe_name, lobe_short, nodes)}],
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("brain_insight failed: %r", e)
        return None

    text = ""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text
    text = text.strip()
    if not text:
        return None

    _CACHE[cache_key] = text
    return {
        "insight": text,
        "model": _MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
