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
    "logging it all", "logging all of that", "logging all of it",
    "i'll log all", "let me get all",
    "adding it all", "adding all of that", "gonna log", "going to log",
    # Russian stall phrases
    "исправляю прямо сейчас", "исправляю сейчас", "сейчас всё занесу",
    "сейчас занесу", "сейчас залогирую", "сейчас всё залогирую",
    "сейчас исправлю", "давай занесу", "давай залогирую",
    "сейчас всё внесу", "сейчас внесу", "внесу прямо сейчас",
    "залогирую прямо сейчас", "логирую прямо сейчас",
    "мне нужно залогировать", "мне нужно внести",
    "я залогирую", "я внесу", "я занесу",
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
    # single-token forms
    "done", "got it", "gotcha", "logged", "recorded", "noted", "okay", "ok",
    "perfect", "sounds good", "all set", "updated", "great", "nice", "cool",
    "yep", "yup", "sure", "alright", "roger",
    # two-word variants that slip past the single-token filter
    "logged that", "logged it", "got it logged", "all logged", "got that",
    "got that logged", "done for now", "all good", "that's logged",
    # NOTE: "sleep well" / "goodnight" intentionally NOT here — they are correct
    # contextual responses when the user signs off. Including them caused quality
    # repair to fire after a goodnight and re-log food from context (real bug).
}

# Sign-off phrases that the user might say to trigger a goodnight response.
# When the user's message contains one of these, Arnie's "Sleep well 🌙" is
# intentional — NOT a dead-end. Used to gate quality repair.
_USER_SIGNOFF_PATTERNS = re.compile(
    r"\b(goodnight|good night|night|nite|gn|sleep well|going to sleep|"
    r"going to bed|off to bed|heading to bed|спокойной ночи|ночи|"
    r"dormir|buenas noches|bonne nuit)\b",
    re.IGNORECASE,
)


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


# Phrases that expose internal mechanics the user should never see — tool names,
# sync/resync language, DB confirmation wording. Substring-matched so partial
# sentences containing these are caught ("Updated totals are resynced for you.").
_MECHANICS_PHRASES = (
    "totals are resynced", "totals resynced", "totals have been resynced",
    "totals have been updated", "totals have been synced", "totals synced",
    "entry has been updated", "entry updated successfully", "entry saved",
    "changes saved", "changes have been saved", "database updated",
    "your log has been updated", "the log has been updated", "log has been updated",
    "synced successfully", "resynced successfully",
    "updated in the system", "saved in the system", "stored in the system",
    # Russian equivalents
    "итоги пересинхронизированы", "данные обновлены в системе",
)


# Subset of dead-end phrases that are ALWAYS wrong even on logging turns —
# pure log acknowledgments with no coaching. Unlike "Nice 💪" or "Clean ✅"
# (which ARE valid brief coaching after a tool call), these contain zero
# substance: they only confirm the mechanical act of logging itself.
_LOG_ACK_PHRASES = {
    "logged", "logged that", "logged it", "got it logged", "all logged",
    "got that logged", "that's logged", "done logging",
}


def looks_like_bare_log_ack(text: str) -> bool:
    """
    True for pure log-acknowledgment replies ("Logged that.", "All logged.") that
    are bad even after tool calls. Narrower than looks_like_dead_end — it never
    flags valid brief coaching like "Nice 💪" or "Clean 🔥" on a logging turn.
    """
    t = (text or "").replace("|||", " ").strip().lower()
    if not t:
        return False
    core = re.sub(r"[^a-z' ]+", " ", t).strip()
    return core in _LOG_ACK_PHRASES


# Empty-praise patterns that the voice rules ban but the LLM still occasionally
# generates. These sound like coaching but contain zero substance: no numbers,
# no specific next move. "Great workout! How did it feel?" is the canonical
# example — it loops in lifecycle (pending question) until answered, making
# it look like Arnie is glitching. We catch it here and trigger quality repair
# the same way we catch mechanics narration.
#
# Guard: only fire on SHORT replies (< 150 chars) with NO digits. A reply like
# "Great macro split — 165g protein" has real data and is fine. "Great workout!
# How did it feel?" has no numbers and is caught.
_EMPTY_PRAISE_PATTERNS = re.compile(
    r"\b(great (workout|session|job|work|effort|progress|stuff)|"
    r"amazing (workout|session|job|work|effort)|"
    r"nice (workout|session|job|work|effort)|"
    r"good (workout|session|job|work|effort)|"
    r"solid (workout|session|job|work)(?!\s+\w)|"
    r"excellent (workout|session|job|effort)|"
    r"way to go|"
    r"you('?ve)? got this|"
    r"keep it up|"
    r"proud of you|"
    r"you'?re doing (great|amazing|well|good)|"
    r"stay (consistent|strong|focused|on track))\b",
    re.IGNORECASE,
)


def looks_like_empty_praise(text: str) -> bool:
    """
    True if the reply is short, contains no numeric data, and leads with a
    banned empty-praise phrase ("Great workout!", "Nice job!", etc.).

    These replies are bad because they contain zero coaching value — no
    numbers, no next move — and when stored as conversation hooks they create
    a loop where proactive messages keep re-asking the generic question until
    the user answers. Catching them here triggers the same quality repair as
    mechanics narration.
    """
    t = (text or "").replace("|||", " ").strip()
    if not t or len(t) > 150:
        return False
    if re.search(r'\d', t):  # real numeric data present → not empty praise
        return False
    return bool(_EMPTY_PRAISE_PATTERNS.search(t))


def looks_like_mechanics(text: str) -> bool:
    """
    True if the response leaks internal plumbing language the user should never see
    ('Updated totals are resynced', 'Entry saved', etc.). Substring match so partial
    sentences are caught.
    """
    t = (text or "").strip().lower()
    return any(phrase in t for phrase in _MECHANICS_PHRASES)


def user_is_signing_off(user_text: str) -> bool:
    """True if the user's message is a sign-off (goodnight, going to sleep, etc.)."""
    return bool(user_text and _USER_SIGNOFF_PATTERNS.search(user_text))


def detect_frustration(user_text: str) -> bool:
    return bool(user_text and _FRUSTRATION.search(user_text))


# Calorie/macro estimate pattern — signals that a food photo's nutrition analysis
# text is present in the first-pass response. Used to detect when the LLM narrates
# macro numbers instead of calling log_food (partial stall from photo turns).
_CALORIE_ESTIMATE_RE = re.compile(r'\d+\s*(?:cal(?:ories)?|kcal)\b', re.I)


def looks_like_partial_narration(text: str, has_food_calls: bool) -> bool:
    """
    True when the first-pass text alongside log_food tool calls contains calorie
    estimates — the model described food items inline instead of tool-calling them.
    'rice ~200cal' fires; 'Nice 💪' does not.
    Only relevant when at least one log_food was already called (partial, not full stall).
    """
    if not has_food_calls or not text:
        return False
    return bool(_CALORIE_ESTIMATE_RE.search(text))


def detect_turn_flags(
    *,
    user_text: str,
    response_text: str,
    has_tool_calls: bool,
    stop_reason: str | None,
    retried: bool,
    tool_error: bool,
    source_type: str | None = None,
    tool_names: set | None = None,
) -> list[str]:
    """
    Return the list of health flags for a completed turn. Empty list = clean turn.
    Order is stable so persisted strings are deterministic.

    source_type: "text" | "image" | "voice" — used for image-specific checks.
    tool_names:  set of tool names called this turn — used for cross-tool checks.
    """
    flags: list[str] = []
    tool_names = tool_names or set()
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
    if looks_like_mechanics(response_text):
        flags.append("mechanics_narration")
    if looks_like_empty_praise(response_text):
        flags.append("empty_praise")
    # Image turn where log_body_weight fired without log_food — almost always a
    # nutrition-analysis false positive (macro gram numbers mistaken for body weight).
    if (source_type == "image"
            and "log_body_weight" in tool_names
            and "log_food" not in tool_names):
        flags.append("image_body_weight_misroute")
    return flags
