"""Recovery lines — the one place a failed turn gets its words.

RECOVERY MESSAGES are the short user-facing fallbacks for failure / dead-end
paths. The user should NEVER be left staring at silence or a confusing reply
when the pipeline trips. Every recovery line:
  • acknowledges the snag honestly (no system-blaming, no pretending)
  • gives ONE concrete next move ("resend", "say it again simpler")
  • is short (1-2 bubbles, |||-split)
  • is in Arnie's voice (sentence case, no em dashes, no helpdesk filler)
This is a retention play: the user knows what happened and what to do,
instead of wondering whether Arnie is broken.

Variance is deterministic (seed-length index) so the same input always yields
the same line — resume-safe, testable, and avoids the same bubble firing
back-to-back when seeds differ.

WHY THIS IS ITS OWN MODULE. The pool used to live in handlers/tool_executor,
which is the tool layer — so the two other places that need it could not have
it. Both worked around the import rather than through it, and both diverged:

  • `core/platform.Response.from_text` had its OWN fallback for an empty
    reply, `"still here. what's the move?"` — lowercase, off-voice, and a
    second stall line in a product that is supposed to have one. It was the
    only in-code lowercase leak the foundation audit still listed, and it
    shipped from the render layer, below every check that reads a reply.
  • `core/chat_service._RECOVERY_SIGS` hand-copied a fragment of each bubble
    so an idempotent resend would not replay onto an errored turn. A copy
    that has to be updated by hand when the pool changes is a copy that will
    not be, and it had already drifted: it carried the platform fallback,
    which was never in the pool at all.

So the pool moves down to `core/`, where both can reach it, and the
signatures are DERIVED from it. Editing a bubble now updates the replay guard
in the same commit, because there is nothing left to keep in sync.
"""
from __future__ import annotations

RECOVERY_BUBBLES = {
    # A tool call returned Error:/Skipped/Failed to — the action did NOT land.
    "tool_error": (
        "That didn't go through.|||Resend and it usually catches the second try.",
        "Something hiccupped saving that.|||Try once more, should land cleanly.",
        "That one didn't save right.|||Resend it and I'll get it.",
    ),
    # The whole LLM turn errored out (exception in chat()). Pipeline can't
    # produce a coached reply — fall back to an honest "try again" line.
    "llm_error": (
        "Something went sideways on my end.|||Resend that and I'll catch it.",
        "Hit a snag on that one.|||Send it again, I'll be back on track.",
        "Wires crossed for a sec.|||Resend it and I'll get it cleanly.",
    ),
    # Degenerate fallback: model produced no text AND no tool calls (or every
    # repair attempt failed). We have nothing to coach on — admit confusion
    # and ask for a simpler restate.
    "stall": (
        "Got a bit confused on that one.|||Say it again, simpler if you can.",
        "Didn't quite land for me.|||Resend it, shorter is fine.",
        "Lost the thread there.|||Try one more time and I'll catch it.",
    ),
}


def recovery_message(kind: str, seed: str = "") -> str:
    """Short user-facing recovery line for failure / dead-end fallbacks.

    Acknowledges the snag in Arnie's voice + gives one concrete recovery
    action (resend, simplify, try again). Helps retention — the user knows
    what went wrong and what to do, instead of staring at silence or a
    confusing reply.

    kind: 'tool_error' (a save failed), 'llm_error' (the whole turn errored),
          'stall' (no usable response_text). Unknown kinds fall back to
          'stall' so a typo can't return empty.
    seed: text the deterministic index keys off — same input maps to the
          same variant. Pass the user's message or a tool-input string.
    """
    pool = RECOVERY_BUBBLES.get(kind) or RECOVERY_BUBBLES["stall"]
    idx = (len(seed or "") + len(kind)) % len(pool)
    return pool[idx]


def _signature(bubble: str) -> str:
    """The lead sentence of a recovery bubble, lowercased, as a match key.

    The lead bubble is what a stored reply starts with, and it is the part
    that identifies the line — the second bubble is the recovery instruction
    and several of them read alike ("resend it and I'll get it").

    Matched against the stored `|||`-joined reply, which is the SANITIZED
    bubbles (core/platform._sanitize_bubble). Nothing in the pool contains an
    em dash, a tilde, a fence or a marker, so sanitizing is a no-op on these
    lines and the stored text is character-identical to what is derived here.
    A bubble that ever gained one of those would break this — which is the
    correct failure, and the test that pins it says so.
    """
    return bubble.split("|||", 1)[0].strip().lower()


#: Every recovery line's signature, derived rather than transcribed.
#:
#: A reply matching one of these means the turn ERRORED — never collapse an
#: idempotent resend onto it, or a resend-after-error loops on the canned
#: apology instead of actually retrying.
RECOVERY_SIGNATURES = frozenset(
    _signature(bubble)
    for pool in RECOVERY_BUBBLES.values()
    for bubble in pool
)


def is_recovery_text(text: str) -> bool:
    """True when a stored reply is a recovery/error bubble.

    Never replay onto one, so a resend after an errored turn actually retries.
    """
    lowered = (text or "").lower()
    return any(sig in lowered for sig in RECOVERY_SIGNATURES)
