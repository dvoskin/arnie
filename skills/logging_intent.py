"""
Turn-intent gate shared by the food / water / exercise dedup guards.

THE PROBLEM the dedup guards have in common: each tries to decide whether a
`log_*` tool call is a genuine new entry or an accidental model re-fire using
only (payload, timing). Those two cases are indistinguishable by that measure —
a second identical coffee 30 min later and a model re-firing the same coffee
30 min later look the same. So every time-window is wrong in both directions:
too short missed the original re-fire bugs, too long eats real repeats (Anya
2026-06-26 "one more same coffee" was silently dropped).

THE REAL SIGNAL is the user's current turn. There are THREE situations a guard
must tell apart, and only the user's words separate them:

  1. genuine repeat  — "one more coffee", "another set", "2 more", "ещё один"
                        → the user is reporting a NEW portion/set. HONOR it.
  2. phantom re-fire  — user pivots topic ("connect apple health") and the model
                        re-logs a prior item from chat context. BLOCK it.
  3. retry / re-send  — "log the elmhurst again", a screenshot shake-confirm,
                        a client/webhook redelivery. BLOCK it (idempotency).

Cases 2 and 3 are exactly what the payload+window dedup is for, so the gate must
stay CLOSED for them. Only case 1 should open it. The distinguishing mark of
case 1 is an explicit ADD/REPEAT cue ("another", "one more", "N more", "x2",
"ещё", "вторую"). Note what is deliberately NOT a cue:

  • bare item mention — a retry names the item too ("log the elmhurst AGAIN"),
    so naming the food/exercise cannot separate a real repeat from a re-send.
  • the word "again" / "снова" / "опять" — usually means "redo the action"
    (retry), not "I consumed another one". Too ambiguous for a blunt override.

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
# KEEP IN SYNC with the natural-language add-intent list in the RAPID-SEND
# DEDUPLICATION block of core/prompts/arnie.py — the model is told the same cues
# there, and this regex is what actually opens the server-side dedup override.
# If the two drift, the model logs a repeat the server then blocks (or vice
# versa), producing the "said logged ✅ but no row written" mismatch.
_ADD_INTENT_RX = re.compile(
    r"""(
        \banother\b |
        \bone\ more\b | \b1\ more\b | \b\d+\s*more\b |
        \bsome\ more\b | \ba\ bit\ more\b | \bmore\ of\ (?:those|them|that|it)\b |
        \bx\s?\d\b | ×\s?\d | \bround\ \d\b |
        \b2nd\b | \b3rd\b |
        ещё | еще | добав | дважды | два\ раза | втор | трет
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Phrases that contain an add-token but mean the opposite ("no more food",
# "больше не") or are idioms ("wait a second" — not relevant here since we don't
# match bare 'second', but 'any more' must not count). Stripped before matching
# so they can't open the gate; a real positive marker elsewhere still survives.
_ADD_NEGATION_RX = re.compile(
    r"\bno more\b | \bany ?more\b | больше\ не | не\ надо | не\ хочу",
    re.IGNORECASE | re.VERBOSE,
)


def has_add_intent(user_text: Optional[str]) -> bool:
    """True when the message explicitly signals a deliberate additional portion
    or set ('another', 'one more', '2 more', 'x2', 'ещё', 'вторую', ...).

    Conservative by design: bare 'more', bare 'again'/'снова', and plain item
    mentions are NOT markers — they collide with retries and re-sends. 'no more'
    / 'больше не' negations are stripped first so they can't flip the result."""
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
