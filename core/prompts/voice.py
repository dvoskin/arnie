"""The voice compiler: one canonical Arnie, cut to the size of the moment.

`core/prompts/arnie.py` is authoritative and stays that way. Nothing here
restates a personality rule — every contract below is LIFTED from the canonical
text by anchor, so editing the persona edits the profiles, and a contract that
stops resolving is loud rather than silent.

The problem this solves is not that the food lane sounded wrong. Since the
shared-persona work it sounds right, because it sends `voice_core()` — all
3,400 tokens of IDENTITY, LANGUAGE, VOICE and EMOJI_SYSTEM — to write "rice
cake logged, 35 cal". The full persona on a two-bubble acknowledgement buys
nothing a tenth of it would not, and it is paid on every routine turn.

And underneath that, a second problem the token count hides: of the eleven
things in this system that produce user-visible text, TWO derive from the
canonical voice. The deterministic floors — `_deterministic_line`,
`clarify_text_from_points`, `enforce_say_contract`'s tokenized line, the
`fallback()` family — are hand-written templates with no derivation at all.
They are also, precisely, what the user reads when something has gone wrong.
So the paths where sounding like Arnie matters most are the paths with no
Arnie in them.

Four profiles, because there are four kinds of moment:

    micro_acknowledgement  a routine write landed and nothing needs discussing
    clarification          one answer is needed before a material estimate
    coaching               the turn earns interpretation, not just confirmation
    recovery               something failed and the user is owed the truth

A profile is a SELECTION, never a rewrite. `PROFILES` names which contracts
apply; the text of each contract has exactly one home, in `arnie.py`.

What is legitimately new here is task rules — "ask one consolidated question",
"never claim a write that failed". Those are not personality and do not belong
in the persona; they are what makes a brief a brief.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from core.prompts import arnie as _canon

logger = logging.getLogger(__name__)


# ── lifting a contract out of the canonical persona ──────────────────────────
@dataclass(frozen=True)
class Contract:
    """One named rule, and where it lives in the canonical text.

    `start`/`end` are anchors into the source constant rather than a copy of
    the rule. That is the whole mechanism: there is no second place to update,
    so a reworded persona cannot leave a profile quoting the old wording.
    """
    name: str
    source: str          # which canonical constant
    start: str           # first line of the span, verbatim
    end: Optional[str]   # first line AFTER the span; None → to the end


#: Every contract, with the canonical span it is lifted from. Anchored on
#: SHOUTED headings and opening sentences, which are the most stable lines in
#: the file — they are what the persona is organised by.
CONTRACTS: Tuple[Contract, ...] = (
    Contract("not_an_ai", "IDENTITY",
             "NEVER refer to yourself as AI or software.",
             "TONE, the core of who you are:"),
    Contract("tone", "IDENTITY",
             "TONE, the core of who you are:",
             "HOW YOU TEXT (texture, on top of the tone above):"),
    Contract("texting_texture", "IDENTITY",
             "HOW YOU TEXT (texture, on top of the tone above):",
             "DATA IS ALWAYS PROPERLY CAPITALIZED"),
    Contract("capitalization", "IDENTITY",
             "DATA IS ALWAYS PROPERLY CAPITALIZED",
             "KEEP THE THREAD ALIVE"),
    Contract("thread_alive", "IDENTITY",
             "KEEP THE THREAD ALIVE", None),
    Contract("sentence_case", "VOICE",
             "Sentence case, like a real person texting.",
             "BUBBLES — this applies to EVERYTHING"),
    Contract("bubbles", "VOICE",
             "BUBBLES — this applies to EVERYTHING",
             "examples showing the read-then-move rhythm:"),
    Contract("slang", "VOICE",
             "LIGHT SLANG", "DIRECTNESS, react to what they actually said"),
    Contract("directness", "VOICE",
             "DIRECTNESS, react to what they actually said",
             "ALWAYS capitalize their name."),
    Contract("their_name", "VOICE",
             "ALWAYS capitalize their name.", None),
)

_BY_NAME: Dict[str, Contract] = {c.name: c for c in CONTRACTS}

#: Anchors that failed to resolve, by contract name. Read by the test that
#: proves the compiler is still bound to the persona; a non-empty set means a
#: profile is running on the fallback below rather than on a lifted rule.
UNRESOLVED: Dict[str, str] = {}


def _lift(contract: Contract) -> str:
    """The contract's text, out of the canonical constant.

    On a missed anchor this returns the WHOLE source section and records the
    miss. Losing a personality rule because someone reworded a heading is the
    one outcome worth spending tokens to avoid — the degraded state is exactly
    today's behaviour, which is the floor everything else in this lane
    degrades to as well.
    """
    body = getattr(_canon, contract.source, "") or ""
    i = body.find(contract.start)
    if i < 0:
        UNRESOLVED[contract.name] = f"{contract.source}:{contract.start!r}"
        logger.error("voice contract %s no longer resolves against %s — "
                     "falling back to the whole section",
                     contract.name, contract.source)
        return body.strip()
    j = body.find(contract.end, i + len(contract.start)) if contract.end else -1
    return (body[i:j] if j > 0 else body[i:]).strip()


def contract(name: str) -> str:
    c = _BY_NAME.get(name)
    return _lift(c) if c else ""


# ── the profiles ─────────────────────────────────────────────────────────────
#: Which canonical contracts each profile carries. A routine acknowledgement
#: does NOT carry `thread_alive` — "end every reply with the next move or a
#: question" is what turns a two-line confirmation into unasked-for coaching,
#: and it is why routine logs have read as over-eager. It is exactly right for
#: the coaching profile, which is where it stays.
PROFILES: Dict[str, Tuple[str, ...]] = {
    "micro_acknowledgement": ("not_an_ai", "tone", "sentence_case", "bubbles",
                              "capitalization", "their_name"),
    "clarification": ("not_an_ai", "tone", "sentence_case", "bubbles",
                      "capitalization", "their_name", "directness"),
    "coaching": ("not_an_ai", "tone", "texting_texture", "capitalization",
                 "thread_alive", "sentence_case", "bubbles", "slang",
                 "directness", "their_name"),
    "recovery": ("not_an_ai", "tone", "sentence_case", "bubbles",
                 "capitalization", "their_name"),
}

#: Task rules — what this KIND of reply must and must not do. Not personality,
#: so they are not lifted from the persona; they are the brief. Each ends up
#: under the canonical contracts, never in place of them.
_TASK: Dict[str, str] = {
    "micro_acknowledgement": """\
THIS MOMENT: a write landed and there is nothing to discuss. Confirm it and
stop. Two short bubbles — the canonical rule is that a food log is never one
bubble alone, and it is also never a paragraph. Name what was logged, give the
committed figures if they carry information, and say where the day stands only
when that is worth knowing. No coaching, no next move, no question: they did
not ask one and the turn did not raise one. Never a receipt ("Successfully
logged: 1 x rice cake"), never a total the card is already showing.""",
    "clarification": """\
THIS MOMENT: one thing has to be settled before the number means anything.
Ask once, about the thing that moves the estimate most, in words a person
would use. Acknowledge what you already have so it is plainly not lost. Ask
about ONE item — several facets of that item are one question, not a form.
Sound like someone who already has a good read and wants to be exact, not like
someone unsure. Never name a database, a tool, a resolver, a confidence score
or a schema; never present a range you would not offer a person.""",
    "coaching": """\
THIS MOMENT: the turn earns more than confirmation — it affects their goal,
they said something about their day, they asked, or a pattern is worth naming.
Give the read, then the move. Use what they actually said, including anything
that was not about food; ignoring that is what makes a coach sound like a
tracker.""",
    "recovery": """\
THIS MOMENT: something failed. Say what is true, in their terms, and no more.
Be exact about what did and did not happen — what was written stays written,
what could not be established is named as unresolved. Never claim a write that
did not land. Never use failure language ("error", "unavailable", "timed out",
"the system") or name the component. Do not apologise twice, and do not reach
for the same sentence you used last time this happened.""",
}


def profiles() -> Tuple[str, ...]:
    return tuple(PROFILES)


# ── the same rules, for text no model wrote ──────────────────────────────────
#: Where the persona declares a list of forbidden phrasings. Both are quoted
#: lists in the canonical text, so the ban propagates: adding a phrase to the
#: persona adds it here, with nothing to update in between.
_BAN_MARKERS = ("These phrases are BANNED, no exceptions:", "Banned outright:")

_QUOTED = re.compile(r"[\"“]([^\"”]{3,60})[\"”]")


def banned_phrases() -> Tuple[str, ...]:
    """Every phrasing the canonical persona forbids outright, lifted from it.

    Scoped to the declarations rather than every quote in the contract: the
    persona is full of quoted EXAMPLES of good lines, and banning those would
    reject the voice it is describing.
    """
    out = []
    for name in ("not_an_ai", "tone"):
        body = contract(name)
        for marker in _BAN_MARKERS:
            i = body.find(marker)
            if i < 0:
                continue
            # A COMMA-SEPARATED RUN, and it ends where the commas do. Taking
            # the whole paragraph swallowed the line right after the list —
            # `("I'm your coach, that's all that matters...")`, which is the
            # persona DEMONSTRATING the right deflection. Banning the example
            # of good behaviour is the failure mode of extracting by proximity
            # instead of by structure.
            cursor = i + len(marker)
            for m in _QUOTED.finditer(body, cursor):
                gap = body[cursor:m.start()]
                if gap.strip(" ,\n"):        # anything but a comma: run over
                    break
                out.append(" ".join(m.group(1).split()))
                cursor = m.end()
    return tuple(dict.fromkeys(p for p in out if p))


#: Phrasings no persona would think to forbid because no PERSON would write
#: them — they are what a system emits when a template is doing the talking.
#: Legitimately authored here rather than lifted, for the same reason `_TASK`
#: is: this is not personality, it is the shape of the failure being guarded.
_RECEIPT = ("successfully", "has been logged", "has been added", "entry added",
            "food entry", "your request", "operation completed", "1 x ",
            "logged:", "added:", "error:", "unable to process")

#: Internal vocabulary. The user has no model of any of it, so naming one is
#: the moment a coach stops sounding like a coach.
_MACHINERY = ("resolver", "schema", "usda", "endpoint", "database", "payload",
              "tool call", "confidence score", "validation", "fallback",
              "the system", "api", "timed out", "null", "none type")


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str


def check(text: str, *, after_food_log: bool = False) -> Tuple[Violation, ...]:
    """Whether a line no model wrote still sounds like Arnie.

    The deterministic floors — `_deterministic_line`, `clarify_text_from_points`,
    `enforce_say_contract`'s tokenized line, the `fallback()` family — run when
    the composer has already failed, which is exactly when a reply that sounds
    like a different product does the most damage. They cannot be sent through
    a model without ceasing to be the floor, so they get the rules mechanically
    instead, from the same source the briefs are compiled from.

    Not a style opinion: every rule here is either lifted from the persona or
    describes a shape a person would never type.
    """
    found = []
    flat = " ".join((text or "").split())
    low = flat.lower()

    for phrase in banned_phrases():
        if phrase.lower() in low:
            found.append(Violation("banned_phrase", phrase))
    for phrase in _RECEIPT:
        if phrase in low:
            found.append(Violation("receipt", phrase))
    for word in _MACHINERY:
        if word in low:
            found.append(Violation("machinery", word))
    # The lane already strips these from model output; the floor is held to
    # the same bar rather than a lower one.
    if "~" in flat:
        found.append(Violation("tilde", "~"))
    if "—" in flat:
        found.append(Violation("em_dash", "—"))
    # SHOUTING. Units and short acronyms are fine ("2 OZ" never appears, but
    # "1450 CAL" would); a run of three or more capitals that is not a known
    # unit reads as a system, not a person.
    for word in re.findall(r"\b[A-Z]{3,}\b", flat):
        if word not in ("USDA", "OFF"):     # named separately as machinery
            found.append(Violation("shouting", word))
    if after_food_log and "|||" not in flat:
        # Straight from the canonical voice, whose last line is exactly this.
        found.append(Violation("one_bubble_after_log",
                               "the persona forbids a lone bubble after a log"))
    return tuple(found)


def compile_voice(profile: str, context: Optional[dict] = None) -> str:
    """The brief for one kind of reply: canonical voice first, task second.

    `context` is accepted and deliberately unused for now — the caller already
    passes the committed snapshot, thread and evidence as structured fields on
    `FoodResponsePlan`, and duplicating them into the system prompt would be a
    second copy of facts that already have an owner. The parameter exists so
    profiles that genuinely need to vary their RULES by context (a recovery
    brief that knows a write half-landed) have somewhere to read from without
    every call site changing.
    """
    names = PROFILES.get(profile)
    if names is None:
        raise KeyError(f"unknown voice profile {profile!r}; "
                       f"known: {', '.join(sorted(PROFILES))}")
    parts = [_lift(_BY_NAME[n]) for n in names]
    parts.append(_TASK[profile])
    return "\n\n".join(p for p in parts if p)
