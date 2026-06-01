"""
Turn-health detectors — cheap, deterministic signals that a turn went wrong.

These are PURE functions with no side effects. They are used for telemetry and
flagging only — never to alter the reply the user gets. The point: make every
deviation (a truncated dump, a narration stall, a frustrated user, a tool error)
self-evident in logs and the admin audit view, instead of relying on someone
eyeballing a screenshot.

The flags persist on ConversationLog.parsed_intent (an existing, unused column —
no schema migration) and surface in /admin/audit's "intent" field.
"""
import re

# Action-commitment phrases that signal a STALL when they appear with NO tool calls:
# the model promised to do something ("let me delete...", "deleting all of today's…")
# but emitted nothing, so a broken promise ships and nothing happens. High precision —
# a normal conversational reply doesn't use these first-person DB-action verbs.
# ("let me know" / "let me think" are deliberately absent.)
_STALL_MARKERS = (
    "let me do that", "let me do this", "let me handle this", "let me handle that",
    "let me delete", "let me clear", "let me log", "let me move", "let me relog",
    "let me reopen", "let me sort", "let me get that logged",
    "i need to delete", "i need to log", "i need to clear", "i need to move",
    "i need to relog", "i need to reopen", "i need to update that",
    "i'll delete", "i'll clear", "i'll relog", "i'll move that", "i'll handle that",
    "deleting all", "clearing today", "relogging", "logging everything",
)

# Frustration / "you got it wrong" markers — a very high-precision proxy for "Arnie
# screwed up." Whole-word / phrase matching to avoid false hits ("scunthorpe" etc.).
_FRUSTRATION = re.compile(
    r"\b(wtf|wth|stfu|dumb|stupid|idiot|downy|useless|"
    r"you missed|u missed|already told you|i told you|that'?s not what|"
    r"not what i (said|meant)|are you (ok|serious|dumb|stupid|kidding)|"
    r"makes no sense|wrong again|still wrong)\b",
    re.I,
)


def looks_like_stall(text: str) -> bool:
    """True if `text` promises an action but (paired with no tool calls) didn't do it."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return t.endswith(":") or t.startswith("on it") or any(m in t for m in _STALL_MARKERS)


# Bare acknowledgments that are banned as a COMPLETE reply — they dead-end the
# conversation and add nothing. Especially wrong right after the user answered a
# question (that should continue, not close).
_DEAD_END_PHRASES = {
    "done", "got it", "gotcha", "logged", "recorded", "noted", "okay", "ok",
    "perfect", "sounds good", "all set", "updated", "great", "nice", "cool",
    "yep", "yup", "sure", "alright", "roger",
}


def looks_like_dead_end(text: str) -> bool:
    """
    True if the WHOLE reply is just a bare acknowledgment ("done", "got it", "logged",
    even "done ✅"). Substance after the word ("done, you're at 450") is fine — only a
    reply that reduces to a dead-end token is flagged.
    """
    t = (text or "").replace("|||", " ").strip().lower()
    if not t:
        return False
    core = re.sub(r"[^a-z' ]+", " ", t)   # strip emoji / digits / punctuation
    core = re.sub(r"\s+", " ", core).strip()
    return core in _DEAD_END_PHRASES


def detect_frustration(user_text: str) -> bool:
    return bool(user_text and _FRUSTRATION.search(user_text))


def detect_turn_flags(
    *,
    user_text: str,
    response_text: str,
    has_tool_calls: bool,
    stop_reason: str | None,
    retried: bool,
    tool_error: bool,
) -> list[str]:
    """
    Return the list of health flags for a completed turn. Empty list = clean turn.
    Order is stable so persisted strings are deterministic.
    """
    flags: list[str] = []
    if stop_reason == "max_tokens":
        flags.append("truncated")
    if retried:
        flags.append("retried")
    if tool_error:
        flags.append("tool_error")
    if not has_tool_calls and looks_like_stall(response_text):
        flags.append("stall_shipped")
    if detect_frustration(user_text):
        flags.append("user_frustrated")
    return flags
