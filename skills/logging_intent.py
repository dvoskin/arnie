"""
Turn-intent gate shared by the food / water / exercise dedup guards.

THE PROBLEM the dedup guards have in common: each tries to decide whether a
`log_*` tool call is a genuine new entry or an accidental model re-fire using
only (payload, timing). Those two cases are indistinguishable by that measure —
a second identical coffee 30 min later and a model re-firing the same coffee
30 min later look the same. So every time-window is wrong in both directions:
too short missed the original re-fire bugs, too long eats real repeats (Anya
2026-06-26 "one more same coffee" was silently dropped; Danny needed ~6 tries
to log a 2nd cottage cheese, and a 2nd Barebells NEVER landed).

THE REAL SIGNAL is the user's current turn. There are THREE situations a guard
must tell apart, and only the user's words separate them:

  1. genuine repeat  — "one more coffee", "another set", "a second cottage
                        cheese", "2 more", "twice", "ещё один"
                        → the user is reporting a NEW portion/set. HONOR it.
  2. phantom re-fire  — user pivots topic ("connect apple health") and the model
                        re-logs a prior item from chat context. BLOCK it.
  3. retry / re-send  — "log the elmhurst again", a screenshot shake-confirm,
                        a client/webhook redelivery. BLOCK it (idempotency).

Cases 2 and 3 are exactly what the payload+window dedup is for, so the gate must
stay CLOSED for them. Only case 1 should open it. The distinguishing mark of
case 1 is an explicit ADD/REPEAT cue ("another", "one more", "a second X",
"twice", "N more", "x2", "ещё", "вторую"). Note what is deliberately NOT a cue:

  • bare item mention — a retry names the item too ("log the elmhurst AGAIN"),
    so naming the food/exercise cannot separate a real repeat from a re-send.
  • the word "again" / "снова" / "опять" — usually means "redo the action"
    (retry), not "I consumed another one". Too ambiguous for a blunt override.
  • a bare time "second" ("wait a second", "give me one second") — NOT a
    serving. The word-count cues below require a serving/portion noun (or item)
    after "second/third/fourth", and the time idioms are stripped first.
  • "N total" paired with a food noun ("3 eggs total") — too risky (it's often
    a correction of the running count, not an add), deliberately excluded.

The gate is high-precision on purpose: a missed open is a rare double-log the
user can delete; a wrong open re-introduces the phantom/retry double-logs these
guards were built to stop. It also defaults closed (empty message → False) so
every existing call path and test is byte-for-byte unchanged.
"""
from __future__ import annotations

import re
from typing import Optional


# Explicit ADD / REPEAT cues — unambiguous "I had/did another one" markers.
# Bilingual: users mix EN/RU ("ещё один", "вторую"). High precision: every
# entry here means a deliberate additional portion or set, not a re-send.
#
# The word-number cues ("second"/"third"/"fourth", "two of those", "a couple")
# were added after Danny's 2026-06-27 logs: he typed "second cottage cheese"
# and "a second barebells" — phrasings the numeral-only draft ("2nd"/"one more")
# missed entirely, so the guard ate both. To stay clear of a bare time "second"
# ("wait a second"), "second"/"third"/"fourth" only count when followed by the
# item or a serving/portion noun (one, serving, helping, round, portion, glass,
# set, cup, scoop, slice, piece, bar, shake, of). The time idioms are stripped
# by _ADD_NEGATION_RX first.
_SERVING_NOUN = (
    r"(?:one|serving|servings|helping|helpings|round|portion|portions|"
    r"glass|glasses|set|sets|cup|cups|scoop|scoops|slice|slices|piece|"
    r"pieces|bar|bars|shake|shakes|of)"
)
_ADD_INTENT_RX = re.compile(
    rf"""(
        \banother\b |
        \bone\ more\b | \b1\ more\b | \b\d+\s*more\b |
        \bsome\ more\b | \ba\ bit\ more\b | \bmore\ of\ (?:those|them|that|it)\b |
        \bx\s?\d\b | ×\s?\d | \bround\ \d\b |
        \b2nd\b | \b3rd\b |
        # word-number serving cues (NOT a bare time "second" — needs a noun)
        \b(?:second|third|fourth)\ (?:{_SERVING_NOUN}|[a-z]) |
        \btwice\b | \bdouble\b |
        \btwo\ of\ (?:them|those|these)\b |
        \ba\ couple(?:\ more)?\b |
        \bextra(?:\ one)?\b |
        ещё | еще | добав | дважды | два\ раза | втор | трет
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Phrases that contain an add-token but mean the opposite ("no more food",
# "больше не") or are idioms ("wait a second" — a TIME second, not a serving).
# Stripped before matching so they can't open the gate; a real positive marker
# elsewhere still survives.
_ADD_NEGATION_RX = re.compile(
    r"""(
        \bno\ more\b | \bany\ ?more\b |
        больше\ не | не\ надо | не\ хочу |
        # time-"second" idioms — kill them so they never reach the serving cue
        \bwait\ a\ second\b | \bhold\ on\ a\ second\b | \bgive\ me\ a\ second\b |
        \bjust\ a\ second\b | \bin\ a\ second\b | \bone\ second\b |
        \ba\ second\ (?:to|here|there|please)\b | \bevery\ second\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def has_add_intent(user_text: Optional[str]) -> bool:
    """True when the message explicitly signals a deliberate additional portion
    or set ('another', 'one more', 'a second cottage cheese', '2 more', 'x2',
    'twice', 'ещё', 'вторую', ...).

    Conservative by design: bare 'more', bare 'again'/'снова', a bare time
    'second', and plain item mentions are NOT markers — they collide with
    retries and re-sends. 'no more' / 'больше не' negations and the time-second
    idioms are stripped first so they can't flip the result."""
    if not user_text:
        return False
    t = " ".join(str(user_text).lower().split())
    t = _ADD_NEGATION_RX.sub(" ", t)
    return bool(_ADD_INTENT_RX.search(t))


# Words that, right after an add cue, do NOT name a distinct food — a generic
# repeat ("another one", "a second helping", "one more glass", "another cold one")
# we can't pin to a specific item. When the cue is followed only by one of these,
# the gate stays open (the historical, no-item behavior). A serving noun or a
# modifier here is still "another of the same thing", not a different food.
_GENERIC_AFTER_CUE = frozenset({
    "one", "ones", "serving", "servings", "helping", "helpings", "portion",
    "portions", "round", "rounds", "glass", "glasses", "cup", "cups", "scoop",
    "scoops", "slice", "slices", "piece", "pieces", "bar", "bars", "shake",
    "shakes", "set", "sets", "of", "them", "those", "these", "it", "that",
    "more", "time", "times", "go", "bite", "bites", "bowl", "bowls", "plate",
    # common modifiers that describe a serving, not a new food
    "cold", "hot", "big", "large", "small", "quick", "light", "full", "same",
})

# Cue → following-noun: the noun the user is adding "another of". If it's a
# concrete food (not in _GENERIC_AFTER_CUE) and is NOT the item being logged,
# the add cue is about a DIFFERENT item.
_CUE_NOUN_RX = re.compile(
    r"\b(?:another|one\s+more|\d+\s*more|a\s+couple(?:\s+more)?\s+(?:of\s+)?|"
    r"(?:second|third|fourth|2nd|3rd)|two\s+of)\s+([a-z][a-z'-]{2,})",
    re.IGNORECASE,
)


def _name_tokens(name: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(w) >= 3}


def _tokens_overlap(a: str, b: str) -> bool:
    """Prefix-tolerant token match so 'coffee' matches 'coffees', 'bar' matches
    'barebells'. Both inputs are already lowercased word tokens (len ≥ 3)."""
    return a == b or a.startswith(b) or b.startswith(a)


_AFFIRMATION_RX = re.compile(
    r"^(?:yes|yep|yeah|yup|ya|sure|correct|right|exactly|indeed|ok(?:ay)?|"
    r"да|ага|угу|конечно|верно|точно)\b",
    re.IGNORECASE,
)


def effective_intent_message(current: Optional[str], prior: Optional[str]) -> str:
    """The message the logging-intent gates should judge. A bare affirmation
    ("Yes", "yes the full one", "да") is an ANSWER to a clarifying question —
    the actual intent (item names, add cues) lives in the PRIOR user message,
    so the gates must judge both together. The cookies-and-caramel incident
    (2026-07-19): the log fired on the "Yes" turn, the gate saw no item and no
    cue, and blocked a brand-new flavor as a duplicate of a 5-min-old
    different bar. Conservative: only short (≤4 word) affirmation-led
    messages combine; anything longer stands on its own."""
    cur = (current or "").strip()
    if not cur or not prior:
        return cur
    if len(cur.split()) <= 4 and _AFFIRMATION_RX.match(cur):
        return f"{prior}\n{cur}"
    return cur


def turn_supports_log(user_text: Optional[str], item_name: Optional[str] = None) -> bool:
    """The dedup gate: True when the current user turn justifies honoring this
    log despite a payload+window match — i.e. the user explicitly signalled
    another portion/set OF THIS ITEM. When True the guards must NOT block; when
    False they apply unchanged (phantom-re-fire and retry cases).

    Item-scoped: an add cue that names a DIFFERENT food ("another coffee") must
    not rescue a phantom re-fire of some OTHER item logged in the same turn (a
    `log_food(chicken)` carried from chat context). So:
      • no add cue at all                         → False (closed; unchanged)
      • cue + this item named ("another coffee",
        logging coffee — plural-tolerant)         → True  (honor the repeat)
      • cue + a DIFFERENT concrete food named
        ("another coffee", logging chicken)        → False (cue isn't about this)
      • generic cue, no distinct food named
        ("one more", "a second helping", "twice")  → True  (can't disambiguate;
                                                     preserve historical behavior)
    With no `item_name` it collapses to `has_add_intent` (back-compat for the
    no-item call sites and the water 'water' sentinel)."""
    if not has_add_intent(user_text):
        return False
    if not item_name:
        return True
    t = _ADD_NEGATION_RX.sub(" ", " ".join(str(user_text).lower().split()))
    item_tokens = _name_tokens(item_name)
    text_tokens = [w for w in re.split(r"[^a-z0-9]+", t) if w]

    # (a) The turn names THIS item alongside the cue → it's a genuine repeat.
    if any(_tokens_overlap(it, tt) for it in item_tokens for tt in text_tokens):
        return True

    # (b) The cue is followed by a DIFFERENT concrete food → it's about that
    #     item, not this one. Don't let "another coffee" rescue a phantom chicken.
    for m in _CUE_NOUN_RX.finditer(t):
        noun = m.group(1)
        if noun in _GENERIC_AFTER_CUE:
            continue                       # "another one / glass / cold one" — generic
        if any(_tokens_overlap(it, noun) for it in item_tokens):
            return True                    # cue noun IS this item (redundant w/ (a))
        return False                       # cue names a different food → not this item

    # Generic cue, no distinct food named → preserve the historical open behavior.
    return True
