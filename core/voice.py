"""Arnie's voice, in one place.

The stated voice is simple — sentence case, no em dashes, no tildes, no joke
emoji, no helpdesk filler, short texting-length bubbles. The problem §8 of the
market-readiness scorecard names is not the rules, it is that they were
RE-STATED and RE-IMPLEMENTED in three registers that then drifted:

  • the PROMPTS tell the model the rules in prose (core/prompts/arnie.py,
    core/log_voice._SYSTEM, the proactive builders);
  • the COMPOSERS hand-assemble bubbles that are supposed to already obey them
    (onboarding intros, proactive greetings, food recaps);
  • the DETERMINISTIC normalizers enforce a SUBSET on the way out, and two of
    them disagree: `platform._sanitize_bubble` turns an em dash into a comma but
    KEEPS an en dash so "12–13%" survives, while `log_voice._clean` collapses
    BOTH — so the same range renders two different ways depending on which path
    voiced it.

None of the three enforced the one rule that was historically the actual bug:
sentence case. `feedback_arnie_voice_format` (2026-06-15) flipped the prompt
anchor to sentence case, but the memory's own residual note — "many lowercase
EXAMPLES remain; if lowercase leaks in a specific flow, flip that flow" — is
still live. `handlers/onboarding.py` ships "good to meet you" and "alright,
you're set"; the proactive scheduler ships "morning {name}." next to "Good
morning {name}". Lowercase was never closed at the root, only at the prompt.

This module is the root. `normalize` is the ONE character-level pass (the
merge of the two divergent ones, keeping the range-preserving behaviour).
`enforce_sentence_case` is the rule nobody enforced. `check_voice` is the
linter that makes "is this in voice?" a measurable question instead of a matter
of opinion. `CoachMessagePlan` + `render` is the structured path for code that
builds a message from parts rather than a raw string. `platform._sanitize_bubble`
and `log_voice._clean` both delegate here, so there is nothing left to keep in
sync — the same lesson `core/recovery.py` already learned for the fallback pool.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Character-level normalization — the merge of the two that had drifted
# ─────────────────────────────────────────────────────────────────────────────

# An em dash is almost always a clause break a comma handles. An EN dash and a
# hyphen are left alone so a number range ("12-13%", "8–10 reps") survives —
# this is the behaviour platform._sanitize_bubble documented and log_voice._clean
# got wrong by collapsing en dashes too. This module keeps the correct one.
_EM_DASH = re.compile(r"\s*—\s*")

# A tilde before a number is the model approximating ("~230 cal"); say it in
# words so the estimate signal survives honestly. A stray tilde just goes.
_TILDE_NUM = re.compile(r"~\s*(?=\d)")

_MULTISPACE = re.compile(r"[ \t]{2,}")


def normalize(text: str) -> str:
    """The single deterministic character pass every bubble gets.

    Em dash → comma (en dash / hyphen preserved for ranges), approximating
    tilde → "about", stray tilde dropped, runs of spaces collapsed. Pure and
    idempotent: normalize(normalize(x)) == normalize(x). Does NOT touch case
    (see enforce_sentence_case) and does NOT strip transport markers like leaked
    tool XML — that stays in platform._sanitize_bubble, which owns the wire.
    """
    if not text:
        return ""
    text = _EM_DASH.sub(", ", text)
    text = _TILDE_NUM.sub("about ", text)
    text = text.replace("~", "")
    # "about ~230" would become "about about 230"; collapse the accidental double.
    text = re.sub(r"\babout\s+about\b", "about", text, flags=re.I)
    text = _MULTISPACE.sub(" ", text)
    # A comma we just introduced can end up doubled ("foo — , bar" sources) or
    # left with a space before a closing bracket; tidy the obvious ones.
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+([)\].,])", r"\1", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Sentence case — the rule nobody enforced deterministically
# ─────────────────────────────────────────────────────────────────────────────

# Tokens whose lowercase lead is INTENTIONAL and must never be "corrected":
# a URL scheme, and any word with an internal capital (iOS, iPhone, eBay,
# macOS). The internal-cap test is structural, so it covers brands we never
# enumerate; the scheme set is the one case with no internal cap to key on.
_URLISH = ("http://", "https://", "www.")
_LEAD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’.]*")


def enforce_sentence_case(bubble: str) -> str:
    """Capitalize the first letter of a bubble when — and only when — it is the
    genuine start of the sentence and is safe to change.

    Arnie's anchor rule is that every bubble opens capitalized. This closes the
    lowercase leak at the seam instead of hoping each prompt example and each
    hand-written composer string got it right. Deliberately conservative; it
    leaves a bubble untouched when the lead is:
      • not a letter at all — an emoji ("📋 Sunday"), a number ("190 now"), or
        punctuation. Nothing to capitalize, and forcing a later word would be
        wrong.
      • an intentionally-cased token — iOS, eBay, iPhone (internal capital), or
        a URL. Capitalizing these corrupts a real name.
    Everything else — "good to meet you", "morning", the standalone pronoun
    "i'll" — gets its lead capitalized. Idempotent.
    """
    if not bubble:
        return bubble
    m = re.search(r"[A-Za-z]", bubble)
    if not m:
        return bubble                       # emoji / number / punctuation lead
    i = m.start()
    if any(c.isalnum() for c in bubble[:i]):
        return bubble                       # a digit/word precedes it → not the lead
    lead = bubble[i]
    if not lead.islower():
        return bubble                       # already capital or uncased
    token = _LEAD_TOKEN.match(bubble[i:]).group(0)
    if any(c.isupper() for c in token[1:]):
        return bubble                       # iOS, eBay, iPhone — intentional
    if bubble[i:].lower().startswith(_URLISH):
        return bubble                       # a URL lead
    return bubble[:i] + lead.upper() + bubble[i + 1:]


def sentence_case_enabled() -> bool:
    """Kill switch, per the codebase's convention of a per-turn env flag on any
    change with a wide blast radius (this one touches every outbound bubble).
    Default ON — the behaviour we want — but `VOICE_SENTENCE_CASE=false` reverts
    to model/composer-supplied case without a deploy if it ever misfires."""
    return os.getenv("VOICE_SENTENCE_CASE", "true").lower() in ("1", "true", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# The voice linter — turns "is this in Arnie's voice?" into a measurement
# ─────────────────────────────────────────────────────────────────────────────

class V(str, Enum):
    """Voice-rule codes. String-valued so they serialize straight to the audit
    JSON and read cleanly in an assertion."""
    EM_DASH = "em_dash"                 # — used as a clause break
    TILDE = "tilde"                     # ~ before a number, or stray
    LOWERCASE_LEAD = "lowercase_lead"   # bubble opens with a lowercase word
    JOKE_EMOJI = "joke_emoji"           # 😅 😂 🤣 — Arnie doesn't laugh at himself
    HELPDESK_FILLER = "helpdesk_filler" # "let me know if", "feel free to", "as an AI"
    EXCLAMATION_PILE = "exclamation_pile"  # !! or 2+ ! in one bubble
    ROBOTIC_ACK = "robotic_ack"         # a whole bubble that is just "Logged."/"Got it"
    LEAKED_MARKER = "leaked_marker"     # [[LOGGED]], {say_x}, <invoke, [SYSTEM, ```, #1234
    EMPTY_BUBBLE = "empty_bubble"       # a ||| produced a blank


# The three that `normalize` + `enforce_sentence_case` fix on their own. The
# audit separates these (a seam guarantees them) from the content violations a
# machine cannot safely rewrite — those are for the author.
AUTO_FIXED = frozenset({V.EM_DASH, V.TILDE, V.LOWERCASE_LEAD})

_JOKE_EMOJI = ("😅", "😂", "🤣")
_HELPDESK = (
    "let me know if", "feel free to", "i'm here to help", "i am here to help",
    "as an ai", "i hope this helps", "don't hesitate", "do not hesitate",
    "happy to help", "is there anything else",
)
_ROBOTIC = {"logged.", "logged", "got it", "got it.", "done", "done.",
            "noted", "noted.", "ok", "ok.", "okay", "okay."}
_LEAK = (re.compile(r"\[\[|\]\]"), re.compile(r"\{[a-z_]{2,24}\}"),
         re.compile(r"<\/?(?:invoke|parameter)\b", re.I), re.compile(r"\[SYSTEM\b", re.I),
         re.compile(r"```"), re.compile(r"#\d{2,}\b"))


@dataclass(frozen=True)
class Violation:
    code: V
    bubble_index: int
    detail: str = ""

    def __str__(self) -> str:
        return f"[{self.code.value}] bubble {self.bubble_index}: {self.detail}"


def _lead_is_lowercase(bubble: str) -> bool:
    # A bubble is lowercase-lead exactly when enforce_sentence_case would change
    # it — one definition, so the linter and the fixer can never disagree.
    return enforce_sentence_case(bubble) != bubble


def check_bubble(bubble: str, index: int = 0) -> list[Violation]:
    """Every voice violation in a single bubble, in a stable order."""
    out: list[Violation] = []
    stripped = bubble.strip()
    if not stripped:
        out.append(Violation(V.EMPTY_BUBBLE, index))
        return out
    if "—" in bubble:
        out.append(Violation(V.EM_DASH, index, "em dash"))
    if "~" in bubble:
        out.append(Violation(V.TILDE, index, "tilde"))
    if _lead_is_lowercase(bubble):
        out.append(Violation(V.LOWERCASE_LEAD, index, repr(stripped[:24])))
    for e in _JOKE_EMOJI:
        if e in bubble:
            out.append(Violation(V.JOKE_EMOJI, index, e))
            break
    low = bubble.lower()
    for phrase in _HELPDESK:
        if phrase in low:
            out.append(Violation(V.HELPDESK_FILLER, index, phrase))
            break
    if "!!" in bubble or bubble.count("!") >= 2:
        out.append(Violation(V.EXCLAMATION_PILE, index, f"{bubble.count('!')} exclamation marks"))
    if low.strip() in _ROBOTIC:
        out.append(Violation(V.ROBOTIC_ACK, index, repr(stripped)))
    for pat in _LEAK:
        if pat.search(bubble):
            out.append(Violation(V.LEAKED_MARKER, index, pat.pattern))
            break
    return out


def check_voice(text: str) -> list[Violation]:
    """Every voice violation in a ||| bubble string. The evaluation primitive:
    scripts/voice_audit.py runs this over the shipped deterministic corpus, and
    the seam tests assert it returns [] after normalize + sentence-case."""
    bubbles = (text or "").split("|||")
    out: list[Violation] = []
    for i, b in enumerate(bubbles):
        out.extend(check_bubble(b, i))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CoachMessagePlan — the structured path for code that builds from parts
# ─────────────────────────────────────────────────────────────────────────────

class Segment(str, Enum):
    """What a bubble is DOING, so a builder names intent and the renderer owns
    voice. A read of the data, the receipt, the one forward move, a question."""
    READ = "read"          # the coach's read of what just happened
    RECEIPT = "receipt"    # the verifiable number ("245 cal, 32g protein")
    NUDGE = "nudge"        # one concrete forward move
    ASK = "ask"            # a question back
    ACK = "ack"            # a light acknowledgement


@dataclass
class CoachMessagePlan:
    """A message as intent, not prose. A composer appends segments; `render`
    turns them into normalized, sentence-cased, ||| bubbles — so a new
    deterministic message is in voice BY CONSTRUCTION instead of by the author
    remembering the rules. Not every surface must adopt this at once; it is the
    target shape, and the linter measures the gap for those that haven't."""
    segments: list[tuple[Segment, str]] = field(default_factory=list)
    max_bubbles: int = 4

    def add(self, kind: Segment, text: str) -> "CoachMessagePlan":
        if text and text.strip():
            self.segments.append((kind, text.strip()))
        return self

    def read(self, text: str) -> "CoachMessagePlan":
        return self.add(Segment.READ, text)

    def receipt(self, text: str) -> "CoachMessagePlan":
        return self.add(Segment.RECEIPT, text)

    def nudge(self, text: str) -> "CoachMessagePlan":
        return self.add(Segment.NUDGE, text)

    def ask(self, text: str) -> "CoachMessagePlan":
        return self.add(Segment.ASK, text)

    def render(self) -> str:
        """The one place a plan becomes text: each segment normalized and
        sentence-cased, joined with |||, capped at max_bubbles. Guaranteed to
        pass check_voice for the rules the seam owns."""
        bubbles: list[str] = []
        for _kind, text in self.segments[: self.max_bubbles]:
            b = normalize(text)
            if sentence_case_enabled():
                b = enforce_sentence_case(b)
            if b:
                bubbles.append(b)
        return "|||".join(bubbles)


def render_bubble(text: str) -> str:
    """Normalize + sentence-case a single already-written bubble. The shared
    implementation platform._sanitize_bubble calls after it has stripped wire
    markers, so the two paths (raw string, structured plan) voice identically."""
    b = normalize(text)
    if sentence_case_enabled():
        b = enforce_sentence_case(b)
    return b
