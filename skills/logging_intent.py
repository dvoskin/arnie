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


def turn_supports_log(user_text: Optional[str], item_name: Optional[str] = None) -> bool:
    """The dedup gate: True when the current user turn justifies honoring this
    log despite a payload+window match — i.e. the user explicitly signalled
    another portion/set. When True the guards must NOT block; when False they
    apply unchanged (phantom-re-fire and retry cases).

    `item_name` is accepted for call-site symmetry and as a forward hook (a
    future verb-aware "consumption report" signal could use it), but is
    intentionally unused today: naming the item cannot distinguish a genuine
    repeat from a retry that also names it ('log the elmhurst again')."""
    return has_add_intent(user_text)
