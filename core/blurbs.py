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
    "here's your dashboard, everything you log lands here",
    "this is your spot, all your stats live here",
    "boom, your dashboard. logs, trends, macros, all of it",
    "here you go, your whole picture in one place",
    "your dashboard's right here, check it whenever",
    "this pulls up everything you've been tracking",
    "here's the link, your trends and logs all live there",
    "got you, this is where all your numbers live",
]


async def dashboard_line(name: str = "") -> str:
    """
    Return ONE short, natural lead-in line for handing over the dashboard link.
    The link is NOT included — send it as a separate bubble after this line.
    Never raises; falls back to a randomized phrase on any failure.
    """
    from core.llm import chat

    nm = (name or "").strip()
    system = (
        "you are arnie, a sharp, funny, direct fitness coach who texts like a real "
        "person. lowercase, casual, no corporate tone, no em dashes. you're handing "
        "the user the link to their personal dashboard (logs, trends, macros). "
        "write ONE short line, max ~12 words, that feels spontaneous and a little "
        "different every time. do NOT include any url or link. do NOT use the word "
        "'dashboard' more than once. no quotes. just the line."
    )
    who = f" the user's name is {nm}." if nm else ""
    prompt = (
        f"give me one fresh casual line handing over the dashboard link.{who} "
        "make it sound like a text from a friend, not a template."
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
            return txt
    except Exception:
        pass
    return random.choice(_DASH_FALLBACKS)
