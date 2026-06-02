"""
Small, varied conversational lead-ins generated in Arnie's voice.

Used for moments that would otherwise feel templated — like handing over the
dashboard link. Every call should feel a little different. LLM-generated via
core.llm.chat(), with a randomized fallback so it never blocks or repeats a
fixed string. The actual URL is always sent separately, so these lines never
contain the link itself.
"""
import random

# Fallbacks — only used if the LLM call fails or returns something unusable.
# Kept varied so even the fallback path doesn't feel canned.
_DASH_FALLBACKS = [
    "Here's your dashboard, everything you log lands here",
    "This is your spot, all your stats live here",
    "Boom, your dashboard. logs, trends, macros, all of it",
    "Here you go, your whole picture in one place",
    "Your dashboard's right here, check it whenever",
    "This pulls up everything you've been tracking",
    "Here's the link, your trends and logs all live there",
    "Got you, this is where all your numbers live",
]


async def dashboard_line(name: str = "") -> str:
    """
    Return ONE short, natural lead-in line for handing over the dashboard link.
    The link is NOT included — send it as a separate bubble after this line.
    Never raises; falls back to a randomized phrase on any failure.
    """
    from core.llm import chat

    # name intentionally unused in the prompt — greeting the user by name ("yo Danny")
    # mid-conversation is exactly what we're avoiding here. Param kept for call-site parity.
    system = (
        "you are arnie, a sharp, direct fitness coach mid-conversation with the user. "
        "they just asked for their dashboard, so you're pointing them to the link as a "
        "natural continuation of the chat, NOT starting a new message. "
        "write ONE short line, max ~12 words, that leads with what's in there (their "
        "logs, trends, macros) and feels a little different every time. "
        "do NOT greet or open with 'yo'/'hey'/'hi' or the user's name. "
        "do NOT include any url. do NOT use the word 'dashboard' more than once. "
        "sentence case, casual, no corporate tone, no em dashes, no quotes. just the line."
    )
    prompt = (
        "give me one fresh line handing over their dashboard link. just point them to "
        "it and lead with what's inside. no greeting, no name, like a real text."
    )
    try:
        result = await chat(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            tools=False,
            max_tokens=40,
        )
        txt = (result.get("text") or "").strip().strip('"').strip()
        if txt and "http" not in txt.lower() and len(txt) <= 120:
            # This line is sent via bb_send_text (not Response.from_text), so apply the
            # em-dash sanitizer here too — the one place all bubbles flow through skips it.
            from core.platform import _sanitize_bubble
            return _sanitize_bubble(txt)
    except Exception:
        pass
    return random.choice(_DASH_FALLBACKS)
