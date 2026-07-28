"""Structured food turn — the clean food-logging path (Danny 2026-07-23).

The old path asked one big model to do everything in one breath — decide, log,
write quantities, coach, ask — and every failure of that (question logged as a
food, an uneditable "~2 handfuls romaine, 3 strips chicken, few tbsp dressing"
quantity, phantom logs) grew another guard. This module replaces the guards with
structure: for a food-report turn, ONE small logger pass reads the message and
returns strict JSON —

  log    -> items [{food, amount, unit, calories, protein, carbs, fats}]
  update -> updates [{entry_id, amount, unit, macros}]  (corrections, board-aware:
            "I actually had 2 birria" / "I had 2 of those" resolve against today's
            logged entries and become clean update_food_entry calls — no dedup
            fight, no "already on the board" template. Danny IMG_8595.)
  delete -> deletes [{entry_id}]  (single-entry removals, board-anchored)
  ask    -> points [{label, q}]   (ONE rich-formatted question)
  pass   -> not a food report; the normal conversation path takes the turn
  ...or "operations": an ordered mixed plan of the write kinds above.

Asks and items are different actions, so an ask payload cannot carry writes;
on top of that, run() enforces a consumption-evidence invariant (an
interrogative or evidence-free cold message never yields a log write, whatever
the model chose). Quantities are always a clean "amount unit" so every entry is
editable. Composites split into natural separate items (Caesar salad one item,
grilled chicken strips another — Danny).

LEDGER SHAPE (Danny 2026-07-24): the logger is the INTERPRETER for a
transaction layer (core/food_ledger). It proposes ORDERED OPERATIONS — log,
update, delete, in one plan, so mixed turns ("bump the tacos and add a Coke")
commit atomically in order. The deterministic policy engine arbitrates
reported ambiguities (the system, not the model, owns the final ask
decision); duplicate delivery is absorbed by idempotency keys; narration
renders from ONE committed snapshot. The plan executes through the existing
tool executor (enrichment, dedup, meal-slot inheritance, cards intact) as
source=structured_food tool calls.

The word "cannot" is earned only where structure enforces it; everything the
prompt merely instructs (action choice, decomposition, reference resolution)
is validated downstream, not trusted. Non-food, mixed food+workout messages,
and non-English reports fall through to the legacy path untouched.

Kill switch: STRUCTURED_FOOD=false.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from core.llm import chat

logger = logging.getLogger(__name__)

ASK_KIND = "food_structured_ask"

# The structured interpreter is a NAMED producer, not an impersonation of
# pass-1: every tool call it emits carries this source tag (persisted in each
# entry's raw_input), so downstream behavior is testable per source and
# regressions trace to a version.
from core.food_ledger import INTERPRETER_VERSION as _IV  # noqa: E402
_SOURCE = f"structured_food:{_IV}"


def structured_food_enabled() -> bool:
    return os.getenv("STRUCTURED_FOOD", "true").lower() in ("true", "1", "yes")


def _logger_model() -> str:
    # Sonnet by default: the logger also estimates macros, which Haiku fumbles.
    # Tiny prompt, so it's still fast. Env-tunable.
    return os.getenv("FOOD_LOGGER_MODEL", "claude-sonnet-5") or "claude-sonnet-5"


# Ask-threshold by accuracy mode (Danny 2026-07-23): ONE dial — ask only when an
# unknown detail could swing the item by more than this many calories. The
# threshold IS the strictness gradient: a "some dressing" (~150 cal swing) asks
# for strict, not for quick; a "half a platter" (~400) asks for everyone.
#: What the interpreter is TOLD to report against. Derived from the one policy,
#: because a model briefed on 200 while the engine asks at 60 is being set up to
#: report the wrong things.
def _thresh_table() -> dict:
    from skills.nutrition.materiality import calorie_threshold
    return {m: int(calorie_threshold(m))
            for m in ("quick", "moderate", "strict")}


_THRESH = _thresh_table()


def _mode(user) -> str:
    prefs = getattr(user, "preferences", None)
    m = (getattr(prefs, "food_logging_mode", None) or "moderate").lower()
    return m if m in _THRESH else "moderate"


# ── pre-gate: is this plausibly a food report? ────────────────────────────────
# Cheap and conservative. Anything missed just takes the legacy path — the gate
# exists to avoid an extra model call on obvious non-food turns, not to be right.
_CONSUMED_RE = re.compile(
    r"\b(had|ate|eaten|having|grabbed|finished|snacked|downed|drank|"
    r"got|bought|ordered|picked\s+up|"
    r"just\s+(?:had|ate|grabbed|finished|got|made)|"
    r"for\s+(?:breakfast|lunch|dinner|a\s+snack|dessert))\b", re.I)
#: EATING, as distinct from OBTAINING. `_CONSUMED_RE` above bundles the two —
#: "ate" and "bought" are both in it — because it exists to decide whether the
#: logger should look at the message at all, and it should look at both. But
#: having a Barebells bar is not eating one, and the bundle is why "Got a
#: caramel cashew Barebells bar and a Legendary sweet roll" wrote two entries
#: without asking.
_EATEN_RE = re.compile(
    r"\b(had|ate|eaten|eating|having|finished|snacked|downed|drank|drinking|"
    r"ate\s+some|just\s+(?:had|ate|finished)|"
    r"for\s+(?:breakfast|lunch|dinner|a\s+snack|dessert))\b", re.I)

#: Obtaining. On its own it says a thing is in your possession, which is a fact
#: about the fridge rather than about the day's total.
#: PREPARATION IS NOT ACQUISITION. "made", "cooked" and "brought" were in this
#: set and should not have been: "chicken salad, made it with olive oil and
#: balsamic" came back as "Did you eat all 3 of those, or is that for later?"
#: — a question about a meal the user had plainly just described eating.
#: Someone who cooked a thing overwhelmingly ate it, and asking otherwise is
#: the friction this whole state model exists to avoid.
_ACQUIRED_RE = re.compile(
    r"\b(got|bought|buying|purchased|ordered|picked\s+up|grabb?ed|"
    r"packed)\b", re.I)

#: The four states a mentioned food can be in. Only one of them is a log.
STATE_CONSUMED = "consumed"
STATE_ACQUIRED = "acquired"
STATE_PLANNED = "planned"
STATE_UNCERTAIN = "uncertain"


def consumption_state(text: str, *, thread_active: bool = False) -> str:
    """Did they EAT it, get it, plan it, or is it not settled?

    Order matters and follows how people write. An explicit eating verb wins
    outright, even alongside an acquisition one — "picked up a poke bowl and
    ate half of it" is one sentence about lunch. A future frame beats a bare
    acquisition, because "got some steaks for tomorrow" is a shopping trip. An
    acquisition verb with no eating verb anywhere is the case this exists for.

    An OPEN FOOD THREAD settles it too: "and a coffee" after a logged meal is
    part of that meal, not a separate errand.
    """
    body = (text or "").strip()
    if not body:
        return STATE_UNCERTAIN
    if _EATEN_RE.search(body):
        return STATE_CONSUMED
    if _PLAN_RE.search(body):
        return STATE_PLANNED
    if _ACQUIRED_RE.search(body):
        return STATE_CONSUMED if thread_active else STATE_ACQUIRED
    return STATE_UNCERTAIN


_MEAL_RE = re.compile(r"\b(breakfast|lunch|dinner|snack|dessert)\b", re.I)
_ACK_RE = re.compile(
    r"^(ok(ay)?|k+|thx|thanks|thank\s+you|ty|cool|nice|great|sweet|got\s+it|gotcha|"
    r"yes|yeah|yep|yup|sure|no+|nope|word|bet|perfect|awesome|good|alright|lol|haha|"
    r"never\s*mind|nvm|"
    # Keep-as-is family: the user is CLOSING the thread, not asking for a write.
    # "Leave it like this" after a proposed bump must never apply the bump
    # (Danny's truffle fries, 2026-07-23).
    r"leave\s+(?:it|that|them)(?:\s+(?:like\s+(?:this|that)|as\s+is|alone))?|"
    r"keep\s+(?:it|that|them)(?:\s+(?:like\s+(?:this|that)|as\s+is))?|"
    r"(?:it|that)'?s\s+fine|don'?t\s+change\s+(?:it|that|anything)|as\s+is)"
    r"[.!,\s]*$", re.I)
_YES_RE = re.compile(
    r"^(y+e*s+|yes+|yep|yup|yeah|ya|sure|correct|right|good|perfect|exactly|"
    r"log\s+it|go(\s+ahead)?|do\s+it|confirm(ed)?|looks?\s+(good|right)|"
    r"that'?s\s+(right|correct|it)|ok(ay)?|k)[.!\s]*$", re.I)

_NEGATED_RE = re.compile(
    r"\b(?:do?n'?t\s+think|won'?t|not\s+(?:going\s+to|gonna|having)|"
    r"no\s+longer|decided\s+against|skipp?(?:ing|ed)?|pass(?:ing)?\s+on|"
    r"changed\s+my\s+mind|scrapp?(?:ing|ed))\b", re.I)

_PLAN_RE = re.compile(
    r"\b(gonna|going\s+to|about\s+to|planning|plan\s+to|might|maybe|probably|"
    r"thinking\s+(?:about|of)|will\s+(?:have|eat|grab)|later\b(?!\s+than)|for\s+(?:tonight|tomorrow|the\s+(?:week|fridge|freezer))|to\s+(?:save|bring|eat\s+later)|not\s+sure)\b", re.I)
# Correction/reference cues — IN scope (the logger owns updates, board-aware).
# Single-entry deletes are structured too (applies_destructive routes them with
# a board present); only whole-day wipes keep the big brain's judgment.
_CORRECTION_RE = re.compile(
    r"\b(actually|instead|make\s+(?:it|that)|change|it\s+was|that\s+was|"
    r"of\s+those|of\s+them)\b", re.I)
# NOTE (Danny 2026-07-23/24): complaints ("you only logged the sour cream
# ones") and confirmations ("okay log it") are NOT gated by phrase lists —
# that's the whack-a-mole disease. They route via THREAD STATE (an open
# ask-pending, or graded thread_relevance over a recent write), and the
# interpreter reads the context and decides. The regexes below shape the
# COLD-START gate and feed classify_thread_intent's mid-thread taxonomy.
_DESTRUCTIVE_RE = re.compile(
    r"\b(remove|delete|undo|scratch|clear\s+(?:my|the|it|that|all|everything|today)|take\s+(?:it|that)\s+off)\b", re.I)
# Non-food logging domains → legacy path (log_water / log_exercise / weight).
_NONFOOD_RE = re.compile(
    r"\b(water|weighed|weigh[- ]?in|workout|gym|bench|squat|deadlift|"
    r"(?:bench|overhead|leg|shoulder|incline|military)\s+press|"
    r"curls?|reps?|sets?\s+of\s+(?:\d+\s*(?:x|reps?|@)|bench|squat|curl)|"
    r"ran|running|walk(?:ed|ing)?\b(?=[^.!?]*\b(?:min|mile|km|steps?)\b)|"
    r"bike|biked|swam|swim|cardio|"
    r"treadmill|jump\s*rope|min(?:ute)?s?\s+of)\b", re.I)


_PORTION_SHAPE_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?|\bhalf\s+a?n?|\ba\s+few|\bcouple\s+of)\s*"
    r"(?:oz|ounces?|g|grams?|kg|ml|l|cups?|tbsp|tsp|slices?|bars?|bags?|"
    r"bowls?|plates?|servings?|scoops?|pieces?|handfuls?|cans?|bottles?|"
    r"packs?|eggs?|strips?)\b", re.I)

# ── mid-thread intent taxonomy (Danny 2026-07-24, fix #4) ─────────────────────
# "Food happened recently" must not seize the thread. These shapes separate
# ledger operations (which the logger owns) from food CONVERSATION — estimate
# challenges, explanation requests, coaching asks, commentary — which the
# conversational brain owns even seconds after a write.
_INTERROGATIVE_RE = re.compile(
    r"^(?:do(?:es)?|did|would|will|can|could|should|is|are|was|were|how|what|"
    r"which|why|where|when|who|am\s+i)\b", re.I)
_CHALLENGE_RE = re.compile(
    r"\b(?:too\s+(?:high|low|much|many|big|small)|way\s+(?:off|too\s+\w+)|"
    r"seems?\s+(?:high|low|off|wrong)|can'?t\s+be\s+right|no\s+way|"
    r"doesn'?t\s+(?:seem|look)\s+right)\b", re.I)
_COACHING_RE = re.compile(
    r"\b(?:what\s+should\s+i|should\s+i\s+(?:eat|have|get)|suggest|recommend|"
    r"still\s+hungry|craving)\b", re.I)
_CLEAR_DAY_RE = re.compile(
    r"\b(?:clear|wipe|reset)\b[^.!?]*\b(?:day|log|everything|today|all)\b", re.I)
# Explicit go-ahead on a proposal ("okay log it") — a report cue even with no
# food noun in the message itself.
_LOG_CUE_RE = re.compile(r"\b(?:log|add)\s+(?:it|them|those|that|all|the)\b", re.I)


def classify_thread_intent(text: str) -> str:
    """What is this message DOING, mid-food-thread? Ledger ops (report /
    correction / deletion) route to the logger; everything conversational
    (question / challenge / coaching / commentary / prospective) stays with
    the big brain. Order matters: closure and negation win first."""
    t = (text or "").strip()
    if not t or len(t) > 500:
        return "other"
    if _ACK_RE.match(t):
        return "ack"
    if _NEGATED_RE.search(t):
        return "retraction"
    if _CLEAR_DAY_RE.search(t):
        return "other"            # whole-day wipe → big brain's judgment
    if _DESTRUCTIVE_RE.search(t):
        return "deletion"
    if "?" in t or _INTERROGATIVE_RE.match(t):
        return "question"
    if _NONFOOD_RE.search(t):
        return "other_domain"
    if _CHALLENGE_RE.search(t):
        return "estimate_challenge"
    if _COACHING_RE.search(t):
        return "coaching"
    if _PLAN_RE.search(t):
        return "prospective"
    if _CORRECTION_RE.search(t):
        return "correction"
    if (_CONSUMED_RE.search(t) or _MEAL_RE.search(t)
            or _PORTION_SHAPE_RE.search(t) or _LOG_CUE_RE.search(t)):
        return "report"
    return "commentary"


def thread_relevance(text: str, minutes_since_write, has_pending: bool) -> bool:
    """Graded mid-thread routing (replaces the flat 15-minute takeover):
    an open ask binds anything answer-shaped; a minutes-old write binds
    reports and corrections; an hours-old write binds only explicit
    corrections and removals ('actually it was grilled' after lunch).
    Commentary, challenges, questions and coaching never route here."""
    intent = classify_thread_intent(text)
    if has_pending:
        # Free-text answers to an open ask are often bare fragments
        # ("half of it", "the big bag") — commentary-shaped, still answers.
        return intent in ("report", "correction", "deletion", "commentary")
    if minutes_since_write is None:
        return False
    if intent in ("report", "correction", "deletion") and minutes_since_write <= 15:
        return True
    if intent in ("correction", "deletion") and minutes_since_write <= 120:
        return True
    return False


def applies_destructive(text: str) -> bool:
    """Single-entry removals ('remove the fries', 'undo that') are ledger
    operations — they route structured so the delete op resolves against the
    board with a real entry_id. Whole-day wipes and non-food destructive stay
    with the big brain. Callers gate on a non-empty board."""
    t = (text or "").strip()
    if not t or len(t) > 500 or "?" in t:
        return False
    if _CLEAR_DAY_RE.search(t) or _NONFOOD_RE.search(t):
        return False
    return bool(_DESTRUCTIVE_RE.search(t))


#: "if ... would/could" — a hypothetical, not a report. Deliberately narrow:
#: it must have BOTH halves, so "if you want, I had the salad" still writes.
_CONDITIONAL_RE = re.compile(r"\bif\b[^.?!]{0,60}\b(would|could|were)\b",
                             re.IGNORECASE)


def consumption_evidence(message: str, prior=None, thread_active: bool = False) -> bool:
    """HARD EXECUTION INVARIANT (fix #3): a log write requires a message that
    can honestly be read as a consumption assertion — whatever action the
    model chose. An interrogative can never yield one ('Does a chicken caesar
    have 700 calories?' stays a question even if the model said log); a cold
    negation or plan can't either. Positive-evidence gating for cold entry
    lives in applies()/thread_relevance — this invariant is the backstop
    against the model MISCLASSIFYING the shapes that must never write."""
    t = (message or "").strip()
    if not t:
        return False
    if "?" in t or _INTERROGATIVE_RE.match(t):
        return False
    # A CONDITIONAL IS NOT AN ASSERTION. "if I had a burger would that blow my
    # day" carries no question mark and does not open with an interrogative, so
    # both guards above pass it — and it names a food in the past tense, which
    # is all the shapes downstream look for. This is grammar rather than food
    # knowledge: "if X, would Y" describes a world, it does not report one.
    if _CONDITIONAL_RE.search(t):
        return False
    if prior is not None or thread_active:
        return True
    return not (_NEGATED_RE.search(t) or _PLAN_RE.search(t))


def decline_reason(text: str) -> str:
    """WHY the cold-start gate declined this message, as a stable code.

    `applies()` returns a bare bool, so every message it turns away looked
    identical in the logs — and this is the single most consequential routing
    decision in the turn. A workout-and-food message and a plan ("I'm going to
    have salmon") both come back False and both land on the legacy path, but
    they are not the same event and a rollout cannot be read without telling
    them apart. Kept beside `applies` and in the same order, so the two cannot
    disagree about what happened.
    """
    t = (text or "").strip()
    if not t:
        return "empty"
    if len(t) > 500:
        return "too_long"
    if _NEGATED_RE.search(t):
        return "negated"
    if _ACK_RE.match(t):
        return "acknowledgement"
    if "?" in t:
        return "question"
    if _PLAN_RE.search(t):
        return "future_plan"
    if _DESTRUCTIVE_RE.search(t):
        return "destructive"
    if _NONFOOD_RE.search(t):
        return "mixed_domain"
    if not (_CONSUMED_RE.search(t) or _MEAL_RE.search(t)
            or _CORRECTION_RE.search(t) or _PORTION_SHAPE_RE.search(t)):
        # Every shape the gate recognises is written in ASCII, so a food report
        # in another script matches nothing and falls through here. Naming it
        # separately is the difference between "we don't serve that language
        # yet" and "the gate has a hole".
        # A NON-LATIN MESSAGE IS NOT A DECLINE, it is a blind spot. Every
        # shape below is written in ASCII, so a food report in another script
        # matches nothing — and 98 of the 301 real food logs this gate turned
        # away were rejected for no reason but their alphabet. The rules do not
        # apply, which is not the same as the message not being food, so it
        # goes to the interpreter that can actually read it.
        if _non_latin(t):
            return ""
        return "no_food_shape"
    return ""


def _non_latin(text: str) -> bool:
    """Whether the message is written in a script the ASCII shape rules cannot
    see. Not a language check — a check on whether our rules APPLY."""
    return any(ord(c) > 0x2FF for c in (text or ""))


def open_gate_enabled() -> bool:
    """Route on the absence of non-food evidence rather than the presence of an
    English food template.

    THE GATE IS A BAD CLASSIFIER. Measured over 1008 real production messages:
    it misses 64% of the messages that actually logged food, and 48% of the
    passes it does allow are not food at all — so it is not buying the cost it
    exists to save. What it turned away includes "Oh and a bag of quest chips",
    "The egg was poached", "Breast" and every message in Cyrillic.

    Open costs roughly 4x the interpreter passes, which is why this is a switch
    and not a rewrite: turn it on, watch latency and spend, turn it off if the
    trade is wrong. FOOD_GATE_OPEN=true.
    """
    return os.getenv("FOOD_GATE_OPEN", "false").lower() in ("true", "1", "yes")


def applies(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 500:
        return False
    if _NEGATED_RE.search(t):
        return False
    if _ACK_RE.match(t) or "?" in t:
        return False
    if _PLAN_RE.search(t) or _DESTRUCTIVE_RE.search(t) or _NONFOOD_RE.search(t):
        return False
    if _CONSUMED_RE.search(t) or _MEAL_RE.search(t) \
            or _CORRECTION_RE.search(t) or _PORTION_SHAPE_RE.search(t):
        return True
    # Past this point no ENGLISH food shape matched. Two reasons that can be
    # true, and they are not the same: the message is not about food, or our
    # rules cannot read it. The second is never a decline.
    if _non_latin(t):
        return True
    # Open gate: nothing above found evidence AGAINST food, and the checks
    # above are the ones that carry real signal (a question, an acknowledgement,
    # a plan, another domain). Absence of an English template is not evidence.
    return open_gate_enabled()


# ── the gate, asked properly ─────────────────────────────────────────────────
#: Judgements already made, so a repeated message costs nothing. Chat is full of
#: exact repeats ("yes", "ok", "same as yesterday") and the answer never changes
#: for the same words.
_RELEVANCE_CACHE: dict = {}
_RELEVANCE_CACHE_MAX = 512

_RELEVANCE_SYSTEM = (
    "Decide ONE thing: is the person reporting food or drink they consumed, "
    "or correcting something they logged?\n"
    "Answer with exactly one word: YES or NO.\n"
    "YES covers a bare food name, a brand, a flavour answering a question, a "
    "correction to a portion or an ingredient, and any language or script.\n"

    "NO covers questions ABOUT food rather than reports of eating it, "
    "hypotheticals (\"if I had a burger...\"), greetings, and messages about "
    "another topic entirely.\n"
    "A message can hold several things at once. If ANY part of it reports "
    "food they actually ate, answer YES \u2014 \"had eggs this morning, having "
    "steak later\" is YES for the eggs, and \"had a coffee then went to the "
    "gym\" is YES for the coffee. The other lanes read the rest.\n"
    "NO also covers food they have NOT eaten yet: what they intend to order, "
    "plan to cook, need to buy, or are about to have. Past tense or an "
    "explicit correction is the line \u2014 \"having chicken later\" and "
    "\"haven't gotten it yet\" are both NO, however much food is named. The "
    "negative rules upstream are written in English and cannot read other "
    "scripts, so in any other language this judgement is yours alone.\n"
    "When it is genuinely ambiguous, answer YES \u2014 a wasted look costs a "
    "moment, a missed meal costs their day."
)


def model_gate_enabled() -> bool:
    """Ask a model whether this is food instead of matching four English
    templates. FOOD_GATE_MODEL=true."""
    return os.getenv("FOOD_GATE_MODEL", "false").lower() in ("true", "1", "yes")


async def food_relevance(text: str, last_assistant: str = "") -> bool:
    """Whether this message belongs to the food lane.

    THE GATE AND "THE CLASSIFIER" ARE THE SAME JOB (Danny's point). This is
    `applies()` with a better implementation behind the same question, so both
    callers — conversation.py's route and the coordinator's route stage — get
    the improvement without either learning anything new.

    Three tiers, cheapest first, so the model is asked only when the cheap
    answers are genuinely uncertain:

      1. a strong NON-food signal (question, acknowledgement, plan, another
         domain) — free, and these travel across languages better than food
         templates do, because "?" is "?" everywhere.
      2. a lexical food shape — free. If a regex matches, it IS food; the
         regexes were never wrong in that direction, only silent.
      3. otherwise ask. This is the 64% the old gate dropped, and it is where
         "Oh and a bag of quest chips" and every Cyrillic meal live.

    Falls back to `applies()` on any failure, so the lane can never be lost to
    a slow or unavailable model.
    """
    t = (text or "").strip()
    if not t or len(t) > 500:
        return False
    if not model_gate_enabled():
        return applies(t)
    if applies(t):
        return True

    # WHAT WAS ASKED A MOMENT AGO. "Sweet chill" is meaningless alone and
    # unambiguous after "Quest Chips, which flavor?" — and the gate was
    # stateless, so an answer to a food question could not be recognised as
    # one. That is the loop that kept traffic OUT of this lane: only the
    # structured path records a pending question, so whenever LEGACY did the
    # asking the answer fell to legacy too, and the conversation never came
    # back. Context, not a better pattern.
    prior = (last_assistant or "").strip()
    # ONLY THE DECLINES THAT CANNOT BE WRONG. This tier existed to save model
    # calls and was costing accuracy instead: "had a coffee then a bagel then
    # went to the gym" died on `mixed_domain`, "had eggs this morning, having
    # steak later" on `future_plan`, and "does 2 eggs sound right? that's what
    # I had" on the question mark — all three real logs, none of which the
    # model ever got to see. A message can hold a meal AND a plan, a workout,
    # or a question at once; only the model can weigh that, and putting the
    # English regexes in front of it is the very failure this replaced.
    #
    # What stays is what no reading can rescue: nothing to read, or a bare
    # acknowledgement carrying no content at all.
    reason = decline_reason(t)
    if reason in ("acknowledgement", "too_long", "empty"):
        return False

    # Was the previous turn a question? Only then does the reply need reading
    # as an answer — and the cache must distinguish the two, or a cold "sweet
    # chill" and one answering "which flavor?" share a verdict.
    # REVERTED (Danny 2026-07-27). Feeding the previous assistant line in was
    # meant to rescue answers to a food question; measured over 150 real
    # production pairs it was a wash on recall (+3 food, -2) and cost
    # precision (60% -> 64% of non-food admitted). The mechanism is that a
    # PLAN answering a question reads as a log — "Actually I'm gonna have a
    # snickers" after "What flavor?" — which is the one shape the write
    # invariant exists to keep out.
    #
    # The loop it aimed at is already closed from the other side: the model
    # gate alone routes "Sweet chill", "90/10", "full fat" and "the leaner
    # one" with no context at all. The parameter stays so callers need no
    # change and so the experiment is re-runnable.
    asked = False
    content = t
    key = (" ".join(t.lower().split())[:200]
           + ("|answering" if asked else ""))
    hit = _RELEVANCE_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from core import deadline
        from core.llm import chat
        res = await deadline.wait_for(
            chat([{"role": "user", "content": content}], _RELEVANCE_SYSTEM,
                 tools=False, max_tokens=4,
                 model=os.getenv("FOOD_GATE_MODEL_ID",
                                 "claude-haiku-4-5-20251001")))
        verdict = "yes" in (res.get("text") or "").strip().lower()[:6]
    except Exception as e:
        logger.debug(f"food relevance unavailable, falling back: {e}")
        return applies(t)
    if len(_RELEVANCE_CACHE) >= _RELEVANCE_CACHE_MAX:
        _RELEVANCE_CACHE.pop(next(iter(_RELEVANCE_CACHE)), None)
    _RELEVANCE_CACHE[key] = verdict
    return verdict


def thread_routes(text: str) -> bool:
    """DEPRECATED shim over classify_thread_intent — kept only for the gate
    evals (scripts/eval_food_matrix) and their tests. Production routing is
    thread_relevance(); this delegates so the two can never drift. Old
    contract preserved: deletion stays excluded (it predates the structured
    delete op) and bare commentary routes (an open thread owned everything
    that wasn't clearly another domain)."""
    return classify_thread_intent(text) in ("report", "correction", "commentary")


# ── the logger pass ───────────────────────────────────────────────────────────
_SYSTEM = (
    "You are the food LOGGER for a nutrition coach. Read the user's message and "
    "output ONLY minified JSON. No prose, no code fences.\n"
    "Pick exactly one action:\n"
    '1. Not a report of food/drink they consumed -> {"action":"pass"}\n'
    '2. Consumed food, but a quantity or calorie-critical prep detail is genuinely '
    'unclear -> {"action":"ask","items":[{"food":"Chicken","amount":6,'
    '"unit":"oz","calories":280,"protein":52,"carbs":0,"fats":7}],'
    '"ambiguities":[{"item":"Chicken","field":"prep","impact_cal":180,"impact_protein":6}],'
    '"points":[{"label":"Chicken","qs":["grilled, baked, or fried?","skin on '
    'or off?","rough amount - oz or one breast?"]}],'
    '"ready":[{"food":"Bagel","amount":1,"unit":"bagel",'
    '"calories":280,"protein":10,"carbs":55,"fats":2},{"food":"Greek yogurt",'
    '"amount":1,"unit":"cup","calories":130,"protein":22}]}\n'
    "AN ASK IS A COMPLETE PARSE PLUS A PROPOSED QUESTION - never a question "
    "instead of a parse. Note what that example does: the food it is ASKING "
    "about still gets a full best-estimate row in `items`, and an entry in "
    "`ambiguities` saying which field is shaky and what the answer would swing. "
    "`ready` is the settled foods. So every food you heard carries a number "
    "somewhere, always.\n"
    "  This is not bookkeeping. The system weighs your reported spread against "
    "the user's mode and targets, and it can only decide NOT to interrupt them "
    "if you have already given it something to write. A question with no "
    "estimate behind it removes that choice and forces the interruption - so "
    "estimate first, then say what you would ask about and why it matters.\n"
    "READY CARRIES FULL ITEMS, exactly like `items` above — the foods you are "
    "NOT asking about are ready to be written now, and a bare name cannot be "
    "written. Give each one its amount and macros. Anything you ARE asking "
    "about belongs in `points`, never in `ready`.\n"
    '3. Consumed food with enough detail -> {"action":"log","items":[{"food":'
    '"Caesar salad","amount":2,"unit":"handfuls","calories":180,"protein":4,'
    '"carbs":8,"fats":15,"branded":false,"meal":"dinner"}],"say":"Pizza and the Caesar logged, {batch_cal} cal and '
    '{batch_protein}g protein for the pair. You are at {day_cal} with {cal_left} left."}\n'
    '4a. CORRECTING WHAT IT WAS ("it was actually a filled Twizzler", "that was '
    'the zero sugar one", "it was chicken not beef") -> set "food" to the '
    'corrected product and OMIT calories/protein/carbs/fats entirely. A '
    'different product is a LOOKUP, not something you remember: the system '
    're-resolves it against the label. Supplying your own numbers is how a '
    '140-calorie PACK figure got written against a quantity of one piece.\n'
    '4. CORRECTING something already on today\'s board ("I actually had 2 birria", '
    '"I had 2 of those", "make it 6 oz") -> {"action":"update","updates":[{'
    '"entry_id":123,"amount":2,"unit":"taco","calories":360,"protein":30,'
    '"carbs":26,"fats":18}],"say":"Bumped the birria to 2 tacos, {batch_cal} cal '
    'now."}\n'
    '5. REMOVING an entry from today\'s board ("remove the fries", "undo that", '
    '"I didn\'t actually eat the yogurt") -> {"action":"delete","deletes":[{'
    '"entry_id":123}],"say":"Took the fries off. You\'re back to {day_cal} with '
    '{cal_left} left."}\n'
    '6. MIXED turns (a correction AND a new item, a removal AND an addition) -> '
    'ordered {"operations":[{"op":"update","entry_id":123,"amount":2,"unit":'
    '"taco","calories":360,"protein":30,"carbs":26,"fats":18},{"op":"log",'
    '"food":"Coke","amount":12,"unit":"oz","calories":140,"carbs":39}],'
    '"say":"Bumped the tacos and the Coke is on, {batch_cal} cal for the '
    'changes."} Operation objects use the same fields as items/updates/deletes '
    'plus "op". Order them the way the user said them.\n'
    "RULES:\n"
    "- WHAT ELSE THEY SAID. When the message carries something that is NOT "
    "about the food and would be rude or strange to ignore, add "
    "\"context\":{\"topic\":\"quitting their job\",\"said\":\"I think I'm "
    "going to quit\",\"signal\":\"distressed\",\"obligation\":\"offer support "
    "before discussing food\",\"priority\":\"important\"}. `signal` only where "
    "there is a feeling; leave it \"\" otherwise, because most of these are "
    "SITUATIONAL rather than emotional \u2014 \"I ate this before my workout\", "
    "\"we were celebrating our anniversary\", \"the restaurant messed up my "
    "order\", \"I made this for my son too\". `priority` is \"normal\" for "
    "something worth knowing, \"important\" when a reply that ignored it would "
    "read as cold, \"urgent\" when the food is plainly the smaller half of "
    "what they said. OMIT the whole object when the message is only about "
    "food, which is most of them \u2014 inventing context is worse than "
    "missing it.\n"
    "- THEIR REGULARS SUGGEST, THEY DO NOT STATE. If their words did not name "
    "the flavour, the size or the amount, it is UNSTATED \u2014 even when their "
    "regulars make one obvious. Write what they said (\"Barebells bar\"), set "
    "basis:\"regular\", and report the gap in ambiguities. Do NOT promote a "
    "remembered variant into the food name as though they had chosen it: "
    "\"a barebell bar\" logged as \"Barebells Salty Peanut Protein Bar\" against "
    "six saved flavours is us answering a question they were asked to "
    "answer. When several of their regulars fit, that IS the ambiguity, and "
    "their own flavours are the options.\n"
    "- BRANDED: set \"branded\":true when the food names a MANUFACTURER or a "
    "packaged product, IN ANY LANGUAGE \u2014 Philadelphia, Oreo, Danone, "
    "\u041f\u0440\u043e\u0441\u0442\u043e\u043a\u0432\u0430\u0448\u0438\u043d\u043e, \u041c\u0438\u0440\u0430\u0442\u043e\u0440\u0433, \u0427\u0443\u0434\u043e, Alpen Gold. This flag decides whether the "
    "product's OWN LABEL is allowed to answer instead of a generic database "
    "entry, so missing it costs the real numbers \u2014 a whipped cream cheese "
    "logged from a generic row instead of its label was 70 calories against a "
    "published 50. You know brands; nothing downstream does. The fallback "
    "there reads capitals and apostrophes, so it is blind to lowercase "
    "typing, to every non-Latin script, and to any brand whose name is an "
    "ordinary word.\n"
    "  It is about the SOURCE of the food, not the words in it: a "
    "Philadelphia cheesesteak is a sandwich (false), Philadelphia cream "
    "cheese is a product (true). A restaurant dish is NOT branded \u2014 name the "
    "restaurant inside \"food\" and leave the flag false.\n"
    "- CORRECTION OPERATOR discipline: 'two MORE tacos' is a NEW log (an "
    "addition), 'actually only one' REPLACES the amount, 'they were chicken "
    "not beef' keeps the amount and re-estimates macros for the new identity, "
    "'that was yesterday' is an update carrying date. Never collapse an "
    "addition into a replace or a replace into an addition.\n"
    "- WHAT YOU DID NOT KNOW - ALWAYS, NOT ONLY WHEN YOU LOG. Every unknown "
    "you resolved by judgement is reported as \"ambiguities\":[{\"item\":"
    "\"<the item it concerns>\",\"field\":\"quantity\",\"impact_cal\":250,"
    "\"impact_protein\":12,"
    "\"assumed\":\"<what you went with, in their language>\"}] "
    "(fields: quantity, identity, brand, prep, consumed). `assumed` is shown "
    "to the user as what you went with so they can correct it in one tap - "
    "write the CHOICE, short and concrete (\"a medium restaurant portion\", "
    "\"pan-fried in oil\"), never a hedge like \"estimated\" and never a "
    "number, which the card already carries. This is the only "
    "channel that exists for doubt. If you are proposing a question, then the "
    "thing you want to ask about IS an unknown and belongs here too, with what "
    "it is worth - an ask that reports nothing is a question the system cannot "
    "weigh against anything.\n"
    "  A GRADE IS NOT A FLAVOUR. Many plain foods are sold at several fat or "
    "leanness levels under ONE name, and the level is most of the calorie "
    "difference between them \u2014 the same words cover the lean version and the "
    "rich one, and picking silently is picking a number they never gave you. "
    "When they name such a food without its grade, that is an unstated field: "
    "report it with the spread between the grades actually sold.\n"
    "  You know which foods work this way and which do not, in any language, "
    "and no list is given because the list would be wrong somewhere else. Note "
    "the trap: translating a food into their language can quietly change which "
    "grade is the default. If you rename it, the grade is MORE uncertain, not "
    "less.\n"    "  HOW IT WAS COOKED IS A QUANTITY OF FAT, and naming a food does not name "
    "its method. Cooking can add more calories than the food itself carries, "
    "and the same words cover both the version with none of it and the version "
    "swimming in it \\u2014 so an unstated method is an unstated number, not a "
    "detail. Work out per food whether the method moves it: for some it is "
    "most of the calories, for others it changes nothing at all, and you "
    "already know which is which without being given a list.\n"
    "  A UNIT THAT DOES NOT FIX A SIZE IS NOT A STATED AMOUNT. Counting "
    "something says how many, not how much, and for anything that comes in "
    "widely different sizes the count settles nothing on its own \u2014 the "
    "same words cover a small one and one three times the size. Treat that "
    "as an unstated quantity and report the spread, exactly as you would "
    "for a word like \"some\". Reason it out per food rather than matching "
    "on the measuring word: what matters is whether their phrasing pins the "
    "size down, in whatever language they used.\n"
    "  impact_cal is the SPREAD the answer would settle: the gap between the "
    "plausible extremes, not your estimate. Judge it against the food it is "
    "attached to, never against a fixed number - the same handful of calories "
    "is noise on a large meal and most of a small one. Report it honestly and "
    "never round your doubt away.\n"
    "  impact_protein is the SAME SPREAD for protein, in grams, and it is not "
    "optional. The system scores every span against that nutrient's OWN daily "
    "target and lets the WORST one decide, so a user chasing protein has "
    "protein uncertainty decide for them - but only if you report it. Omitting "
    "it does not mean zero doubt, it silently means zero WEIGHT, and a "
    "calorie-tight protein-wild item then sails through. 0 is a real answer "
    "when the answer genuinely cannot move protein (a splash of oil); say 0 "
    "rather than leaving it out.\n"
    "- ONE UNKNOWN, ONE ENTRY. Every question you put in \"points\" must have "
    "its own entry in \"ambiguities\" naming the same field, and nothing may "
    "appear in one and not the other. `points` is only the WORDING; "
    "`ambiguities` is what the system weighs, so a question with no entry "
    "behind it cannot be scored and is silently dropped or committed past. "
    "That is how a steak got asked about its size and its cooking while the "
    "CUT \u2014 sirloin against ribeye, a swing of a hundred calories and more on "
    "one portion \u2014 was asked in words and weighed as nothing.\n"
    "- YOU PROPOSE, THE SYSTEM DECIDES. \"action\" is your recommendation, not "
    "the outcome. Whether an unknown is worth interrupting someone for depends "
    "on their mode, their targets and the rest of their day - thresholds you "
    "cannot see and must not guess at. So ALWAYS carry your best-estimate "
    "\"items\" for everything you did understand, INCLUDING when you propose "
    "asking: if the system judges the unknown too small to be worth a "
    "question, it commits your estimate instead, and a proposal with no items "
    "leaves it nothing to commit.\n"
    "- ANSWER-TURN follow-up: when their answer itself introduces a NEW "
    "material unknown (a new item, a new unstated portion), you may ask ONCE "
    'more - set "new_ambiguity":true on that ask. Never re-ask anything '
    "already asked or answered.\n"
    '- Each log item may carry "basis": "stated" (user gave the amount), '
    '"regular" (from THEIR REGULARS), or "estimate" (your call) - provenance '
    "for the audit trail.\n"
    '- Optional "note": ONE short forward-looking coach fragment with NO '
    "numbers and NO nutrition claims (those come from the system after the "
    'commit). Optional "follow_up":"save_as_regular" ONLY when the meal looks '
    "like a repeated order that is not yet in their regulars.\n"
    "- In an ask, items that need NOTHING go in ready:[names] so the user "
    "sees every item was heard - never leave a clean item unacknowledged "
    "while you question the others.\n"
    "- ASK DEPTH scales with mode: on strict, list EVERY calorie-moving facet "
    "per item as its own short sub-question (prep / skin / amount for "
    "proteins; size / toppings for starches; bread, slices, butter for toast; "
    "'a scoop' = 1 tbsp, 2, or heaping). Moderate asks only each item's "
    "single biggest facet; quick asks one question total. Always ONE message.\n"
    "- Judge each item's ambiguity INDEPENDENTLY: a clearly-stated neighbor "
    "never excuses a vague main. 'Some caesar salad with chicken and 3 eggs' "
    "still asks about the salad even though the eggs are exact.\n"
    "- ACQUISITION verbs (got, grabbed, bought, ordered, picked up) report "
    "POSSESSION, not proof of eating. Log them as consumed when the shape says "
    "eaten (a stated amount, meal context, past-tense flow); storage or future "
    "markers ('for tonight', 'for the fridge', 'to bring to work') -> pass. On "
    "strict the confirm settles it either way before anything is written.\n"
    "- MEAL SLOT per item when clear: words like breakfast/lunch/dinner win; a "
    "composed plate or main (protein + sides) is a MEAL even at an odd hour; a "
    "lone bar, bag, or drink between meals is a snack. A textbook snack must "
    "never group with a later real meal. Omit when genuinely unclear (the "
    "clock decides).\n"
    "- The user declining a change or closing the thread ('leave it like this', "
    "'keep it as is', 'it's fine', 'don't change it') is NEVER a log or an update "
    "-> pass. Even if the last assistant message PROPOSED a change ('I'll bump it "
    "up'), their keep-it means the proposal is dead: write nothing.\n"
    "- A stated PIECE COUNT is the anchor: '5-6 fries' means 5-6 individual fries "
    "estimated per piece and multiplied, never a menu side portion's calories. "
    "A count is HIGH confidence: price each piece at its typical real value and "
    "do NOT stack the estimate-HIGH bias on top (that bias is for unknown "
    "amounts, not counted ones). Calibration: one restaurant fry is 25-40 cal "
    "even loaded with parm/truffle butter, so 5-6 such fries land 150-220, "
    "never 300+. The count survives follow-ups too: any later double-check or "
    "refinement re-prices the SAME counted amount, it never re-portions.\n"
    '- update "say" starts from words like Updated/Bumped/Fixed and gives the '
    "entry's new value, NEVER 'logged' — nothing new entered the log.\n"
    "- update: match against TODAY'S BOARD below by name or reference ('those' = "
    "the most recent matching entry). entry_id MUST come from the board. When only "
    "the amount changes, SCALE the board line's macros proportionally. If the "
    "correction's target isn't on the board, action is pass.\n"
    "- An item already on the board reported again as the SAME serving is never "
    "re-logged: correct it (update) or pass.\n"
    "- ELABORATING ON A FRESH ROW IS A CORRECTION, NOT A MEAL. When the board shows something logged minutes ago and their message gives a DIFFERENT detail for it - the amount, the flavour, the cut, how it was cooked - that is them refining what you just wrote, and it is an update to that entry_id. It is not a second helping and it is not a new food. Nobody eats a thing twice by describing it once.\n"
    "  Judge it per clause: a message can refine three board rows and add a fourth food, so each part is decided against the board on its own. What makes it an ADDITION is them saying so - \"another\", \"two more\", \"again\" - not the presence of a new number.\n"
    "  Keep what the row already established. A brand on the row survives a "
    "correction to any other field: naming a flavour makes it that flavour OF "
    "THAT BRAND, never a different maker whose version you happen to know "
    "better. They corrected one field, not the identity.\n"
    "  AN UPDATE THAT RESTATES THE ROW IS A DROPPED CORRECTION. Echoing the "
    "board's own amount and macros back with a new entry_id changes nothing and "
    "is worse than logging twice, because it looks handled. Every update you "
    "emit must carry the CHANGE: they named a flavour, a variant, a cut or a "
    "cooking method -> put the corrected full name in \"food\" and OMIT the "
    "macros so the numbers are re-resolved for what it actually was; they "
    "named an amount -> put it in amount/unit. If a clause tells you nothing "
    "new about a row, emit NO update for that row rather than a hollow one.\n"
    "- DECIDE BEFORE YOU WRITE: any calorie-relevant doubt (milk type, prep, "
    "portion, flavor) means action=ask INSTEAD of log. Once you log, there is "
    "nothing left to ask - the say NEVER contains a question; later drift is "
    "handled by corrections, not by asking after the fact.\n"
    '- "say" (log and update actions): the coach line the user sees. 1-2 short '
    "sentences, sentence case, warm and specific, NAMING every item (never just one "
    "of them), plus one forward read. NEVER write your own totals — the system fills "
    "these exact tokens from the database AFTER the write: {batch_cal} {batch_protein} "
    "{day_cal} {cal_left} {day_protein} {protein_left}. Example: 'Both bags logged, "
    "{batch_cal} cal and {batch_protein}g protein combined. You're at {day_cal} with "
    "{cal_left} left, keep dinner protein-forward.' Never the ~ character, never an "
    "em dash, never a list. Never characterize a nutrient (fiber, sugar, sodium) "
    "unless its value is in your context — no invented nutrition virtues. Sound "
    "like a sharp coach texting, not a tracker.\n"
    "PIPELINE (work WITH it, not against it):\n"
    "- Your macros are PROVISIONAL: after you log, enrichment refines them from the "
    "user's own logged history, then USDA, then brand databases. Give a sane "
    "estimate fast; don't agonize.\n"
    "- Food names: clean canonical brand + product ('Quest Chips Sweet Spicy', "
    "'Fage 0% yogurt') — matching against history and USDA depends on the name.\n"
    "- If the user gave a mass (200g, 6 oz), keep THAT as the unit — an exact mass "
    "unlocks exact per-gram nutrition downstream.\n"
    "- When unsure between two portion reads, estimate HIGH (never under-count); a "
    "stated label/package amount is ground truth, use it exactly.\n"
    "- Calorie-dense components ON a dish (cream cheese, spreads, sauces, cheese, "
    "dressing, oil): portion what the VENUE actually applies, never the label "
    "serving — a bagel-shop schmear is 3-4 tbsp (150-200 cal), a shawarma joint's "
    "garlic sauce is a heavy pour. Under-counting the rich parts is the #1 miss.\n"
    "- Omit meal_type unless the user names the meal — the pipeline infers the slot "
    "from time and the meal's other items.\n"
    "THREAD CONTEXT (when given YOUR PREVIOUS MESSAGE and TODAY'S BOARD):\n"
    "- If they say an item is missing or you logged the wrong one, log ONLY the "
    "missing item(s), judged against the board. Never reply that it's already "
    "logged when they're telling you something is absent.\n"
    "- If they're telling you to go ahead with what your previous message proposed "
    "('okay log it'), log exactly those proposed items and numbers.\n"
    "- If the message needs none of your actions (chit-chat, a question, another "
    "topic), action is pass.\n"
    "NEVER leak machinery: no board #ids, no {tokens}, no [SYSTEM ...] text, no "
    "tool or database names in 'say' or questions. Natural coach language only.\n"
    "- Split a combo into natural SEPARATE items (the salad one item, the chicken "
    "strips another, a drink another) so each is editable on its own line.\n"
    "  SPLITTING IS WHAT MAKES A DISH KNOWABLE, not a formatting preference. A "
    "combined row is a name no food database holds, so nothing can check it and "
    "the number is only ever your guess \\u2014 while each part on its own line "
    "is an ordinary food that can be looked up, corrected and reused. One row "
    "for a whole plate is also uncorrectable by the user: they cannot tell you "
    "the rice was double without re-describing the entire meal.\n"
    "  So split wherever the parts are different FOODS \\u2014 a protein, a "
    "starch, a sauce, a side are four things that happen to share a plate, and "
    "their calorie densities are nothing alike. Keep together only what is "
    "genuinely one food: a sauce cooked into the dish, a filling inside its "
    "wrapper, a dish whose name IS the recipe rather than a list of what came "
    "with it. Judge that per dish, in any language \\u2014 the test is whether "
    "someone could sensibly eat more of one part and less of another.\n"
    '- "food": clean capitalized name. A BRAND or restaurant the user named is '
    'ALWAYS kept in it, verbatim ("Thomas\' Everything Bagel Thin", "Philadelphia '
    'Scallion Cream Cheese", "Starbucks Turkey Bacon Sandwich") — the brand is the '
    "database search key; never strip it for brevity. Unbranded items stay short "
    '(2-4 words). Fold a stated adjustment into the name ("Pizza toppings, crust '
    'left"). Set "branded": true on any item that is a branded/packaged/restaurant '
    "product — it routes the item to label-grade lookup.\n"
    '- "amount": a USER-STATED amount is ground truth — keep it EXACTLY, fractions '
    "included (\"1/3 of a KIND bar\" -> amount 0.33, never rounded to 0.5). Only "
    "when YOU are estimating an unstated amount, pick a round editable number — "
    "whole or .5 — and a unit that makes it round ('1 small portion', not '0.33 "
    "portion'). \"unit\": one short unit (handfuls, strips, oz, g, cup, slices, "
    "bar, small bowl).\n"
    "- Macros: best estimate for that exact amount; calories consistent with "
    "protein*4 + carbs*4 + fats*9.\n"
    "- 'My usual X' is a POINTER into THEIR REGULARS: exactly one match -> log it "
    "with those exact numbers; TWO OR MORE plausible matches -> ALWAYS ask which "
    "('the americano or the oat latte?') — never pick one by frequency; NO "
    "matching regular -> ask ONCE how they usually take it (that answer becomes "
    "the regular). Never estimate a generic for 'my usual'.\n"
    "- STRICT mode only: a BRANDED product with an UNSTATED flavor/variant is "
    "ALWAYS an ask, regardless of swing size — name the range and, when one of "
    "THEIR REGULARS matches the brand, offer it: 'your usual Caramel Cashew?'. "
    "A stated variant, or a match to a regular they always log, logs directly "
    "with those exact numbers.\n"
    "- ASK when the report leaves a question a careful human coach could not "
    "honestly answer alone. The three logical ambiguity classes, in order:\n"
    "  1. HOW MUCH - an unstated portion of a multi-serving package or "
    "container (bag of jerky/chips, jar, tub, pint): 'some jerky' spans one "
    "serving to the whole bag. ALWAYS ask unless the user stated an amount, "
    "it's a single-unit item (a bar, a banana), or exactly one matching "
    "regular supplies their usual portion. Never silently assume one serving. "
    "PACKAGE SIZES are variants too: when they say 'the bag'/'a bottle' and "
    "the product ships in multiple common sizes, list the sizes you know "
    "('the 1.25 oz snack bag, the 2.85 oz, or the big sharing bag?') and "
    "confirm which one - same style as every other ask.\n"
    "  2. WHICH ONE - a branded product whose flavor/variant meaningfully "
    "changes macros (protein bars, chips, ICE CREAM and candy bars - 'a Dove bar' spans minis to king size). When asking, LIST the variants you know with rough "
    "calories ('Original ~80, Sweet & Hot ~80, Zero Sugar ~60 per oz - which "
    "one?') so they can point at one instead of describing from scratch.\n"
    "  3. HOW WAS IT MADE - prep and calorie-dense add-ons (fried vs grilled, "
    "dressing, oil, butter, sauce) with no amount.\n"
    "Accuracy mode ({mode}) sets how far down that ladder to dig: quick asks "
    "only class 1 when the range is huge, strict digs through all three. Use "
    "a swing worth ~{of_day} of their DAY'S TARGET as your calibration for "
    "'worth asking', "
    "never as the framing of the question itself - ask like a human ('how much "
    "of the bag?'), not like a calorie auditor. Within a dish, ask about what "
    "moves the needle - the chicken, dressing, or cheese on a salad - never "
    "the trivial base (nobody clarifies lettuce).\n"
    "JUDGE IT IN PROPORTIONS, NEVER A CALORIE COUNT. A flat number cannot "
    "work here: 80 calories is trivia on a slice of pizza and the whole story "
    "on a drizzle of oil. Below ~{of_item} of the FOOD, or below ~{of_day} of "
    "their DAY, or when the food itself is under ~{item_share} of their day and "
    "so cannot move it however the doubt resolves: do NOT ask — estimate HIGH "
    "at venue-real "
    "portions and log. A clear count or mass of a plain food ('2 slices', '6 oz', "
    "'a banana') never needs asking. Ask ONCE, at most 3 points, bundling every "
    "unclear item; log nothing until answered. Never ask about something clearly "
    "stated, or about water, diet soda, or black coffee.\n"
    "- When PRIOR CONTEXT shows you already asked and they answered: log EVERYTHING "
    "from the whole exchange with their answers applied. Do NOT ask again — fill "
    "any still-missing detail with your best estimate.\n"
    "- Consumed food only: a plan they haven't eaten or a question is pass."
)


def note_held_items(say: str, stashed: list, tool_calls: list) -> str:
    """A confirm-answer turn must never silently drop a stashed item: anything
    the user saw in 'Locking this in' that is not in the write gets NAMED as
    held (Dove bar incident 2026-07-24 — 3 confirmed, 2 logged, bar vanished)."""
    logged = {(tc.get("input") or {}).get("food_name", "").lower()
              for tc in (tool_calls or [])}
    missing = []
    for it in (stashed or []):
        food = (it.get("food") or "").strip()
        if food and not any(food.lower() in ln or ln in food.lower()
                            for ln in logged if ln):
            missing.append(food)
    if not missing:
        return say
    held = " and ".join(missing[:3])
    return ((say or "").rstrip(". ")
            + f". Holding the {held} - tell me which kind and it goes on too.")


def _build_calls(ops, board_by_id: dict):
    """`(calls, kinds, items_logged)` for an operation list.

    Extracted so the ASK branch can construct the same calls the commit path
    does. It has to be the same builder: units, entry-id binding and provenance
    are decided here, and a second construction for the partial-commit case
    would be a second definition of what a write is.
    """
    calls, kinds, items_logged = [], [], []
    # A LONE update is a correction; an update among others is part of a plan
    # that redistributes what is already there. Only the first defers its
    # macros to a fresh lookup.
    lone_update = len(ops or ()) == 1 and (ops[0][0] == "update")
    for kind, o in ops:
        call = (_log_call(o) if kind == "log"
                else _update_call(o, board_by_id, defer_macros=lone_update)
                if kind == "update"
                else _delete_call(o, board_by_id))
        if call is None:
            continue
        calls.append(call)
        kinds.append(kind)
        if kind == "log":
            items_logged.append(o)
    return calls, kinds, items_logged


def _apply_clarification_veto(decision, calls, kinds, items_logged):
    """Drop the log calls the clarification policy did not clear.

    Returns `(calls, kinds, items_logged, held_names)`.

    Only LOG calls are subject to it. Updates and deletes are the user's own
    explicit corrections to rows already on the board — they were never staged,
    the policy never reasoned about them, and vetoing them on the strength of a
    set they are absent from would silently swallow "remove the fries".

    Matched on the staged item's own text rather than on ids, because the
    interpreter's op and the staged item share exactly that: `_log_call` builds
    `food_name` from `o["food"]`, and `stage_items` builds `original_text` from
    the same field. Substring both ways, since the executor normalises names.
    """
    clarification = getattr(decision, "clarification", None)
    staged = getattr(decision, "staged_items", ()) or ()
    if clarification is None or not staged:
        return calls, kinds, items_logged, []

    held_ids = set(getattr(clarification, "held_item_ids", ()) or ())
    if not held_ids:
        return calls, kinds, items_logged, []
    held_texts = {(i.original_text or "").strip().lower()
                  for i in staged if i.staged_item_id in held_ids}
    held_texts.discard("")
    if not held_texts:
        return calls, kinds, items_logged, []

    def _is_held(call) -> bool:
        name = str(((call or {}).get("input") or {}).get("food_name")
                   or "").strip().lower()
        if not name:
            return False
        return any(name == t or name in t or t in name for t in held_texts)

    kept_calls, kept_kinds, held_names = [], [], []
    for call, kind in zip(calls, kinds):
        if kind == "log" and _is_held(call):
            held_names.append(
                str((call.get("input") or {}).get("food_name") or ""))
            continue
        kept_calls.append(call)
        kept_kinds.append(kind)

    if not held_names:
        return calls, kinds, items_logged, []

    lowered = {n.lower() for n in held_names}
    kept_items = [o for o in items_logged
                  if str(o.get("food") or "").strip().lower() not in lowered]
    return kept_calls, kept_kinds, kept_items, held_names



def _revalidate_after_answer(ops, prior, message: str, mode: str = "moderate"):
    """Re-derive what the answer invalidated, and decide MODE-APPROPRIATELY
    what to do when it cannot be re-derived (§2, §3, §4).

    Returns an `ask` action when the turn must stop, or None when it may
    proceed — with the correction disclosed as an assumption.

    The comparison is against the PRIOR INTERPRETATION, not against the user's
    words: they said "pieces" both times. What changed is that we had read it
    as skewers, and the only record of that is what we stashed with the
    question.

    MODERATE IS THE DAILY EXPERIENCE, and a second question on an answer turn
    is the most expensive thing this can do to it — the user has already been
    interrupted once and answered. So the modes differ in what they do with an
    unresolvable correction, not in whether they notice it:

      * a STALE estimate — the interpreter repeating its previous number under
        the new unit — stops every mode. There is no number to commit, and
        quick's licence is to accept an estimate, not to accept one nobody
        made.
      * otherwise, with a range available, moderate and quick COMMIT and
        disclose the range. Strict asks, because confirming assumptions before
        the write is what strict is.
      * with no range and no mass, everyone asks. Nothing else is honest.

    The result for a moderate user correcting "skewers" to "pieces": one
    question if we genuinely cannot size a piece, and otherwise a committed log
    that says on its face what was assumed.
    """
    prior_items = (prior or {}).get("items") or []
    if not prior_items:
        return None
    from skills.nutrition.unit_change import (compare, estimate_is_stale,
                                              mass_range_for, may_commit,
                                              question_for)
    from skills.nutrition.normalize import normalize_quantity

    by_food = {}
    for it in prior_items:
        if isinstance(it, dict):
            name = str(it.get("food") or "").strip().lower()
            if name:
                by_food[name] = it

    for kind, op in ops:
        if kind != "log" or not isinstance(op, dict):
            continue
        food = str(op.get("food") or "").strip()
        was = by_food.get(food.lower())
        if was is None:
            continue
        change = compare(str(was.get("unit") or ""), str(op.get("unit") or ""))
        if not change.changed:
            continue

        _before_cal = op.get("calories")
        # EVERYTHING DERIVED FROM THE OLD UNIT IS GONE. Dropped from the op so
        # nothing downstream can read a stale value: the enrichment path
        # recomputes from the corrected unit, and a missing key is a recompute
        # where a stale one is a wrong answer that looks settled.
        for _k in ("calories", "protein", "carbs", "fats", "grams",
                   "estimated_mass_g", "count_basis"):
            op.pop(_k, None)
        logger.info(
            "event=unit_correction food=%r %s->%s invalidated=%d",
            food, change.before, change.after, len(change.invalidated))

        # A REPEATED NUMBER IS NOT A RE-ESTIMATE. The interpreter sees the
        # prior exchange, and the easiest thing it can do with "actually they
        # were pieces" is hand back the figure it already gave. Identical
        # calories across a unit change that means a different amount of food
        # is the previous answer, unrevised — and it stops every mode.
        _stale = estimate_is_stale(was.get("calories"), _before_cal)
        if not change.blocks_commit and not _stale:
            continue

        _q = normalize_quantity(
            f"{op.get('amount') or 1} {op.get('unit') or ''}".strip(), food)
        _range = mass_range_for(op.get("unit") or "", food)
        # A MASS WE CAN STAND BEHIND MEANS A MEASURED ONE. "6 oz" and "200 g"
        # are conversions and settle the correction for every mode. An ontology
        # or piece-weight mass is an ESTIMATE wearing a gram figure — enough for
        # moderate and quick to commit against with the range disclosed, and
        # exactly the kind of assumption strict exists to confirm. Reading a
        # bare `grams` here made them the same thing, and strict committed a
        # correction it should have asked about.
        if not _stale and may_commit(change,
                                     mass_g=(_q.grams if _q.mass_is_exact
                                             else None)):
            continue

        # Moderate and quick resolve rather than re-ask, WHEN there is
        # something honest to resolve with. Strict asks: confirming an
        # assumption before the write is the whole of what strict is.
        if not _stale and _range and mode in ("moderate", "quick"):
            _lo, _hi = _range
            _amount = op.get("amount") or 1
            op["assumption"] = (
                f"a {change.after} of {food} taken as "
                f"{_lo:.0f}-{_hi:.0f}g, so {_amount} is a range not a figure")
            logger.info("event=unit_correction_ranged food=%r %s->%s %s-%sg",
                        food, change.before, change.after, _lo, _hi)
            continue

        _text = question_for(change, food) or (
            f"How big were the {change.after}s of {food}?")
        return {"action": "ask", "text": _text, "points": [_text],
                "items": [op], "kind": "clarify"}
    return None


def _item_is_stated(it: dict, message: str) -> bool:
    """Is this item's amount the USER's own words? The interpreter's "basis"
    declaration wins when present ("stated"/"regular" vs "estimate"); when
    absent, the amount literally appearing in the message is the deterministic
    proxy (digits, spelled small counts, "half"). Unsure → False, which errs
    toward confirming — the safe direction on strict."""
    b = str(it.get("basis") or "").strip().lower()
    if b == "stated":
        return True
    # "regular" IS NOT "stated". It means WE supplied this from their regulars,
    # which is the opposite of the user having said it — and this function asks
    # exactly one question, in its own first line: is this the USER's own words?
    #
    # Counting it as stated made an inference indistinguishable from a fact the
    # moment it left the interpreter, and every rule downstream that turns on
    # something being UNSTATED went quiet with it. A shipped turn: "Gonna have
    # a barebell bar" logged as "Barebells Salty Peanut Protein Bar" against a
    # history holding six Barebells flavours, on STRICT — whose own rule says a
    # branded product with an unstated flavour is always an ask. The flavour was
    # unstated. It just did not look unstated by the time anything could ask.
    if b == "regular":
        return False
    if b == "estimate":
        return False
    amt = it.get("amount")
    if amt is None:
        return False
    try:
        f = float(amt)
    except (TypeError, ValueError):
        return False
    # Scoped to the CLAUSE that names this food, not the whole message.
    #
    # The bug this fixes, straight from a shipped transcript: "I had like 15
    # peanut m&m, half a banana and a scoop of peanut butter" was read as
    # STATING one tablespoon of peanut butter, because the whole-message check
    # for the word "a" matched "a banana". The user was then asked to approve a
    # 190-calorie assumption they had never been shown.
    #
    # An article is the weakest possible evidence of a stated amount, so it now
    # has to sit in the clause about this food AND next to the unit or the food
    # itself.
    clause = _clause_for(message, str(it.get("food") or ""))

    # ASK THE NORMALIZER FIRST (§1, §3, §13). It parses the user's own words —
    # digit fractions, unicode fractions, "two thirds", "one and a half",
    # mixed numbers — and reports `user_stated_amount` as the number they
    # actually gave, or None when they gave none.
    #
    # The checks below this line are a SECOND, weaker implementation of the
    # same question, and they disagreed with the first on every fraction: "3/4
    # cup of rice" reaches here as f=0.75, "0.75" is not in the clause, 0.75 is
    # not 0.5, and it is not an integer — so a portion the user stated exactly
    # was classified as our inference, and strict mode asked them to confirm
    # their own words. The friction was the disagreement, not the strictness.
    #
    # Kept as the first check rather than the only one: it answers about the
    # clause's LEADING amount, and the older heuristics still catch a number
    # sitting further inside a clause that names several things.
    try:
        from skills.nutrition.normalize import normalize_quantity
        _food = str(it.get("food") or "")
        _unit = str(it.get("unit") or "").strip().lower()
        _words = clause.split()
        # The amount is rarely the first word — "I had 3/4 cup of rice" leads
        # with a verb. Walk in from the left until something parses, bounded so
        # a long clause naming several foods can't reach the next one's number.
        for _skip in range(min(len(_words), 6)):
            _q = normalize_quantity(" ".join(_words[_skip:]), _food)
            _said = _q.user_stated_amount
            if _said is None:
                continue
            if abs(_said - f) > max(0.02, abs(f) * 0.02):
                break
            # THE UNIT HAS TO AGREE TOO. "A scoop of peanut butter" arriving as
            # 1 tbsp matches on the amount alone, and treating that as stated
            # is precisely the shipped failure: a 190-calorie assumption
            # presented as the user's own words. They said scoop; we said
            # tablespoon; that is an inference whatever the number did.
            _said_unit = (_q.user_stated_unit or "").rstrip("s")
            if _unit and _said_unit and _said_unit != _unit.rstrip("s"):
                break
            return True
    except Exception:
        pass

    s = str(int(f)) if f.is_integer() else str(f)
    # Plain substring for digits: "200" has no word boundary before the "g" in
    # "200g", and requiring one dropped every mass the user actually typed.
    if s in clause:
        return True
    if f == 0.5 and re.search(r"\bhalf\b", clause):
        return True
    if not f.is_integer():
        return False
    _words = {1: ("one",), 2: ("two",), 3: ("three",), 4: ("four",),
              5: ("five",), 6: ("six",)}
    if any(re.search(rf"\b{w}\b", clause) for w in _words.get(int(f), ())):
        return True
    if f == 1.0:
        # "a"/"an" counts only immediately before the unit or the food.
        unit = str(it.get("unit") or "").strip().lower()
        food = str(it.get("food") or "").strip().lower()
        head = (food.split()[-1] if food else "")
        targets = [t for t in (unit, head) if t]
        if targets:
            return any(re.search(rf"\ban?\s+{re.escape(t)}\b", clause)
                       for t in targets)
        # Nothing to anchor to — no food, no unit. The bare article is weak
        # evidence, but it is the only evidence there is, and refusing it here
        # would call every unnamed single item an estimate.
        return bool(re.search(r"\ban?\b", clause))
    return False


def _clause_for(message: str, food: str) -> str:
    """The part of the message that talks about this food.

    Shared shape with the pipeline's vague-measure matcher: split on the
    conjunctions people actually use, then pick the clause with the most token
    overlap. Falls back to the whole message when nothing matches, which keeps
    the old behaviour for single-food messages.
    """
    text = (message or "").lower()
    if not text or not food:
        return text
    parts = [p for p in re.split(r"\s*(?:,|\band\b|\bwith\b|\bplus\b|\+)\s*",
                                 text) if p.strip()]
    if len(parts) <= 1:
        return text

    stop = {"a", "an", "the", "of", "some", "like", "had", "i", "my", "was",
            "also", "just", "about"}

    def _tok(t):
        return {w for w in re.findall(r"[a-z0-9&]+", t) if w not in stop}

    food_tokens = _tok(food.lower())
    if not food_tokens:
        return text
    best, best_score = text, 0.0
    for part in parts:
        part_tokens = _tok(part)
        overlap = food_tokens & part_tokens
        if not overlap:
            continue
        score = len(overlap) / len(food_tokens | part_tokens)
        if score > best_score:
            best, best_score = part, score
    return best


def _prefs_for(user):
    """Learned food defaults for this user, if they are already loaded.

    Never triggers a lazy load: the interpreter runs inside an async turn and
    touching an unloaded relationship raises MissingGreenlet. No preferences
    simply means none are applied — a degraded default, not a failed turn.
    """
    try:
        return list(getattr(user, "food_preferences", None) or ())
    except Exception:
        return []


def _strict_needs_confirm(items: list, data: dict, message: str) -> bool:
    """The narrowed strict-confirm gate (Danny 2026-07-25): pre-write
    confirmation only for the cases where it earns its friction —
      • any item's amount is system-estimated (not the user's own words),
      • a bulk plan (>=4 items),
      • unresolved consumed-vs-planned doubt the model reported below the
        ask threshold (above it, the policy engine already asked).
    Everything clearly stated commits directly, even on strict."""
    if len(items) >= 4:
        return True
    if any(str(a.get("field") or "").strip().lower() == "consumed"
           for a in (data.get("ambiguities") or []) if isinstance(a, dict)):
        return True
    return any(not _item_is_stated(it, message) for it in items)


def review_plan(items: list, *, user_message: str = ""):
    """The pre-log confirmation as a RESPONSE PLAN rather than final prose.

    The logger decides and writes; it does not author the conversation. What it
    supplies here is the parse — which items, at what amounts — and the
    response layer phrases it (core/food_response.py).
    """
    from core.food_response import FoodItemSummary, plan_review

    summaries = []
    for it in (items or [])[:8]:
        food = (it.get("food") or "").strip()
        if not food:
            continue
        portion = ""
        if it.get("amount") is not None:
            portion = f"{it.get('amount')} {it.get('unit') or ''}".strip()
        summaries.append(FoodItemSummary(
            name=food, portion=portion,
            estimated=not _item_is_stated(it, user_message)))
    return plan_review(summaries, user_message=user_message)


def clarify_text(decision, question, *, user_message: str = "") -> str:
    """The deterministic floor for `clarify_plan` — see it for the shape.

    Kept as-is so every existing caller and test kicks out the same text; the
    live path renders the plan through `food_response.render_plan` instead, so
    the question is voiced rather than assembled.
    """
    from core.food_response import fallback
    return fallback(clarify_plan(decision, question, user_message=user_message))


#: An ambiguity's type -> the kind the composer's brief already phrases. Shared
#: with the interpreter-ask path so both clarify routes describe an unknown the
#: same way, rather than one composing and the other reciting.
_AMBIGUITY_KIND = {
    "consumed_quantity": "portion",
    "unit_interpretation": "portion",
    "package_size": "portion",
    "product_identity": "identity",
    "product_line": "identity",
    "product_variant": "identity",
    "preparation": "preparation",
    "component_breakdown": "extras",
    "serving_basis": "detail",
}


def unknowns_from_decision(decision, user_message: str = "") -> tuple:
    """The staged items' ambiguities in the shape the composer's brief reads.

    WHY THIS EXISTS. `clarify_plan` set `clarification_question` and nothing
    else, so `build_prompt` fell through to its "ASK EXACTLY THIS (rephrasing
    for tone is fine)" branch — handing the composer a finished template and
    asking for a tone pass. Two different modes then produced BYTE-IDENTICAL
    text ("I picked the other amounts myself. Was the bowl closer to 150g or
    400g?"), which is the tell: an LLM does not write the same sentence twice.

    That is the same defect already fixed on the interpreter-ask path — the
    composer is given what is UNKNOWN and writes the turn — and this route
    never got it, so every question the staged pipeline raised, which is most
    of them on a composite meal, shipped as a template.

    WHAT IT USED TO THROW AWAY. `FoodAmbiguity` carries `calorie_span`,
    `protein_span`, `carb_span`, `fat_span` and `candidate_values` — labelled
    options with confidences — and this summed the first of them into one
    scalar named `stakes` and dropped the rest. A scalar can rank a question.
    It cannot phrase one, which is why the clarification opened by asserting a
    settled number for the one item whose identity was the open question:

        "You've got the hand roll down at 230 calories and 10g protein,
         that's your reading so far. The catch is which one you grabbed…"

    `stakes` stays, because the ranking and the mode thresholds are computed
    from it. What is added is what the sentence needs: the endpoints, and the
    options the user is actually choosing between.
    """
    groups = {}
    for item in (getattr(decision, "staged_items", None) or ()):
        for amb in (getattr(item, "ambiguities", None) or ()):
            try:
                kind = _AMBIGUITY_KIND.get(amb.ambiguity_type.value, "detail")
            except Exception:
                kind = "detail"
            g = groups.setdefault(kind, {"items": [], "stakes": 0.0,
                                         "ranges": {}, "options": []})
            name = (item.original_text or "").strip()
            if name and name not in g["items"]:
                g["items"].append(name)
            try:
                g["stakes"] += abs(float(amb.calorie_span or 0))
            except (TypeError, ValueError):
                pass
            _collect_range(g, name, amb)
    out = []
    for kind, g in groups.items():
        # Same fallback the interpreter path uses: an unknown nobody could
        # price still ranks by how many foods it covers, or a meal of unpriced
        # items never gets asked about at all.
        weight = g["stakes"] or float(len(g["items"]) * 200)
        out.append({"kind": kind, "phrase": _KIND_PHRASING.get(kind, kind),
                    "items": tuple(g["items"]), "asks": (),
                    "stakes": round(g["stakes"], 1), "weight": weight,
                    "ranges": dict(g["ranges"]),
                    "options": tuple(g["options"])})
    out.sort(key=lambda g: -g["weight"])
    return tuple(out)


def _collect_range(group: dict, name: str, amb) -> None:
    """Widen this item's range by one ambiguity, and keep its options.

    Several ambiguities can be open on one food — which product AND how much of
    it — and each is a separate reason the number could move. Taking the widest
    is the honest reading: a range that covers one doubt and not the other
    would be a narrower claim than we can support.
    """
    try:
        span = amb.calorie_range
    except Exception:
        span = None
    if name and span:
        low, high = span
        prior = group["ranges"].get(name)
        group["ranges"][name] = ((min(low, prior[0]), max(high, prior[1]))
                                 if prior else (low, high))
    try:
        for option in amb.top_options(3):
            label = str(getattr(option, "label", "") or "").strip()
            if label and label not in group["options"]:
                group["options"].append(label)
    except Exception:
        pass


def clarify_plan(decision, question, *, user_message: str = "",
                 context=None):
    """The whole meal as we read it, then the one thing we need.

    Items the user stated are shown as they said them. The item we are asking
    about is shown in THEIR words too — "one scoop of peanut butter", never
    "one tablespoon of peanut butter", because the tablespoon is the thing in
    question and printing it as settled is what made the assumption invisible.

    Returns the PLAN, not text: what to say is settled here, how to say it
    belongs to the one renderer. Splitting them is what lets a clarification
    be composed instead of concatenated.
    """
    from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                    FoodResponsePlan, fallback)

    # WHAT IS HELD IS THE DECISION'S ANSWER, NOT THE QUESTION'S.
    #
    # This read `{question.staged_item_id}` — one question names one staged
    # item, so however many items the engine refused to commit, the plan
    # reported exactly one pending and described the rest as resolved. Probed
    # at a1c26d3:
    #
    #     strict: engine held=3   plan pending=1
    #             resolved=['Peanut M&Ms', 'Banana']
    #
    # Two items the engine held were handed to the composer as settled. That is
    # why strict and moderate rendered BYTE-IDENTICAL replies while doing
    # opposite things — the difference between them is entirely in how many
    # items they hold, and the hold count never reached the sentence. It is
    # also the likely source of the `reason=pending_as_committed` composer
    # fallbacks in the logs: `validate()` checks `pending_items` against the
    # text, and `pending_items` was missing most of what was pending.
    #
    # The question's own item is the fallback, not the source. A decision that
    # somehow carries no held ids still has to describe the item it is asking
    # about as open.
    held = set(getattr(decision.clarification, "held_item_ids", ()) or ()) \
        or {question.staged_item_id}
    resolved, pending = [], []
    for item in (decision.staged_items or ()):
        summary = FoodItemSummary(
            name=item.original_text,
            portion=_spoken_portion(item, user_message),
            estimated=not item.quantity.is_stated,
            staged_item_id=item.staged_item_id,
            branded=(item.food_class.value == "branded"))
        (pending if item.staged_item_id in held else resolved).append(summary)

    # APPLY THE POLICY. Both clarify builders live here and constructed the
    # plan directly, so it reached the renderer with the dataclass defaults —
    # `allow_question=False` among them. `validate()` then rejected the
    # composer's sentence with FORBIDDEN_QUESTION on the one intent whose
    # entire purpose is to ask, twice per turn, and `compose` returned the
    # deterministic floor every time.
    #
    # The composer has therefore never voiced a clarification in production.
    # Turning it on could not change how these read, because nothing it wrote
    # was ever allowed to ship. Every other plan builder gets this by living in
    # food_response, where the builders wrap their own returns.
    from core.food_response import apply_policy
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=tuple(resolved), pending_items=tuple(pending),
        clarification_question=question.prompt,
        # ...and WHAT IS UNKNOWN, so the composer writes the question instead
        # of being handed one and asked to rephrase it.
        clarification_unknowns=unknowns_from_decision(decision, user_message),
        # THE ITEM THE QUESTION IS ABOUT, not merely the first one held. With
        # one pending item these were the same thing; now that `held` reports
        # everything the engine kept back, `pending[0]` is whichever staged
        # item happened to come first, and the renderer names `unresolved_item`
        # as the subject of the question.
        unresolved_item=next(
            (p for p in pending if p.staged_item_id == question.staged_item_id),
            pending[0] if pending else None),
        # WHAT ELSE THEY SAID travels with the question. CLARIFY's brief tells
        # the composer to acknowledge it BEFORE asking — "a clarification must
        # not make the rest of their message sound invisible" — and it can only
        # do that if the plan carries it.
        conversational_context=context,
        requires_answer=True, user_message=user_message))


def _spoken_portion(item, user_message: str) -> str:
    """The portion in the user's own words where we have them.

    An INFERRED amount on an item we are about to ask about must not be shown
    as the portion — that is the silent conversion. The measure the user
    actually used is recovered from their message instead.
    """
    quantity = item.quantity
    if quantity.is_stated:
        return f"{quantity.stated_amount:g} {quantity.stated_unit or ''}".strip()
    from core.food_pipeline import _vague_measure_in
    measure = _vague_measure_in(user_message, item.original_text)
    if measure:
        return f"1 {measure}"
    if quantity.is_inferred:
        return f"{quantity.inferred_amount:g} {quantity.inferred_unit or ''}".strip()
    return ""


def format_confirm(items: list, *, user_message: str = "") -> str:
    """Deterministic confirmation text.

    Was: a numbered, bolded list under "Locking this in:" ending in "Good to
    log, or anything to fix?" — three pieces of transaction vocabulary in one
    message, and a shape that reads like a form rather than a coach checking
    something. Now it is the response layer's REVIEW fallback: prose for one or
    two items, one food per line only when prose stops being scannable.
    """
    from core.food_response import fallback
    return fallback(review_plan(items, user_message=user_message))


def acquisition_question(items: list) -> str:
    """"Did you eat that, or is it for later?", naming what was named.

    One sentence, and it names the food rather than saying "that" — a question
    the user has to scroll up to understand is a worse question. Two items get
    both; more than two get a count, because listing five things back is the
    roll-call the card exists to avoid.
    """
    names = [_lc(str(it.get("food") or "").strip())
             for it in (items or []) if (it.get("food") or "").strip()]
    if not names:
        return "Did you eat that, or is it for later?"
    if len(names) == 1:
        subject = f"the {names[0]}"
    elif len(names) == 2:
        subject = f"the {names[0]} and the {names[1]}"
    else:
        subject = f"all {len(names)} of those"
    return f"Did you eat {subject}, or is that for later?"


def board_lines(board) -> list:
    """Today's rows as the interpreter sees them, WITH how long ago each landed.

    The age is the whole point. Without it every row reads "already logged
    today" whether it was written eight hours ago or sixty seconds ago, and a
    message elaborating on what we just wrote ("the chicken was a small
    breast") is indistinguishable from someone describing a new meal — so it
    gets logged a second time. Recency is what makes the difference decidable,
    and the rows carry the timestamp already.
    """
    out = []
    for b in (board or [])[-8:]:
        try:
            age = b.get("mins_ago")
            when = ""
            if isinstance(age, int):
                when = (" - JUST LOGGED, seconds ago" if age < 2 else
                        f" - logged {age} min ago" if age < 90 else "")
            out.append(f"#{b['id']} {b['food']}, {b.get('qty') or '?'}, "
                       f"{int(b.get('cal') or 0)} cal{when}")
        except Exception:
            continue
    return out


#: Shelf spreads, keyed by product name. A product line's spread is a fact
#: about the world, not about this turn, so re-fetching it per turn buys
#: nothing and costs a round trip on the critical path — measured at roughly
#: +3.5 s median when every branded item was looked up fresh. Bounded so a long
#: session cannot grow it without limit; evicting the oldest is fine because a
#: re-fetch is correct, just slower.
_SPREAD_CACHE: dict = {}
_SPREAD_CACHE_MAX = 256


#: A variant lookup may take this long before the turn stops waiting for it.
#: The spread is DECORATION FOR THE ASK, never for the write — every failure is
#: already an absent entry and the decision proceeds — so it does not get to
#: spend the turn's whole remaining budget. Measured at 3.5 s on a two-item
#: turn; the turn itself was 16 s against a legacy ~6 s.
_VARIANT_SPREAD_SECONDS = 1.5


def _spread_could_matter(raw, *, mode: str, targets) -> bool:
    """Could a shelf spread on this item ever change the ask decision?

    The BEST case is the whole item in doubt: no per-100g spread can exceed the
    ceiling it is measured against, so `span <= item_calories` always. If the
    real scorer calls even that immaterial, no fetch can produce an ambiguity
    that survives `_apply_variant_spreads`' own `is_material` check — the
    network round trip is spent to compute a number already known to be
    discarded.

    Asks the scorer rather than hard-coding a threshold, so this cannot drift
    from the mode thresholds it is standing in for. Unknown calories mean the
    doubt cannot be sized either way, and an unsizeable doubt is the case the
    fetch exists to answer, so it goes ahead.
    """
    calories = None
    for key in ("calories", "cal", "kcal"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and value > 0:
            calories = float(value)
            break
    if calories is None:
        return True
    try:
        from skills.nutrition.ambiguity import materiality
        return materiality(mode=mode, calorie_span=calories,
                           item_calories=calories,
                           targets=dict(targets) if targets else None) >= 1.0
    except Exception:                                    # pragma: no cover
        return True


async def _variant_spreads(data, *, mode: str = "moderate",
                           targets=None) -> dict:
    """`{food_lower: {nutrient: per-100g span, _max_per100: ceiling}}` for the
    branded items in this turn.

    Fetched HERE because the lookup is network-bound and `plan_turn` is not
    async. Fanned out, bounded by the turn's deadline, and every failure is
    simply an absent entry — a turn never loses its decision because a product
    database was slow.

    Bounded twice now. An item whose doubt could not be material even at its
    widest is never fetched at all (`_spread_could_matter`) — one production
    turn spent 3.5 s deriving a variant ambiguity on a RICE CAKE — and what is
    fetched gets `_VARIANT_SPREAD_SECONDS` rather than the whole remaining
    budget.
    """
    names = []
    for raw in (data.get("items") or []):
        if not isinstance(raw, dict):
            continue
        if not (raw.get("branded") or raw.get("is_packaged")):
            continue
        food = str(raw.get("food") or "").strip()
        if not food or food.lower() in [n.lower() for n in names]:
            continue
        if not _spread_could_matter(raw, mode=mode, targets=targets):
            logger.debug(f"variant spread skipped for {food!r}: "
                         f"immaterial even at its widest")
            continue
        names.append(food)
    if not names:
        return {}

    async def one(food):
        cached = _SPREAD_CACHE.get(food.strip().lower())
        if cached is not None:
            return food, (cached or None)
        try:
            from core import deadline
            from skills.nutrition.off import search_variants, variant_spread
            variants = await deadline.wait_for(
                search_variants(food, limit=6),
                seconds=_VARIANT_SPREAD_SECONDS)
            if not variants or len(variants) < 2:
                return food, None
            spread = variant_spread(variants)
            ceiling = max((float((v.get("per100g") or {}).get("calories") or 0)
                           for v in variants), default=0.0)
            if not spread or ceiling <= 0:
                return food, None
            spread = dict(spread)
            spread["_max_per100"] = ceiling
            return food, spread
        except Exception as e:
            logger.debug(f"variant spread unavailable for {food!r}: {e}")
            return food, None

    import asyncio as _aio
    out = {}
    for food, spread in await _aio.gather(*[one(n) for n in names]):
        key = food.strip().lower()
        if key not in _SPREAD_CACHE:
            if len(_SPREAD_CACHE) >= _SPREAD_CACHE_MAX:
                _SPREAD_CACHE.pop(next(iter(_SPREAD_CACHE)), None)
            # A miss is cached as {} too — a product with no shelf to compare
            # is a stable fact, and re-asking the database every turn for the
            # same absent product is the slowest possible way to learn nothing.
            _SPREAD_CACHE[key] = spread or {}
        if spread:
            out[key] = spread
    return out


def _carry_assumptions(items, ambiguities) -> list:
    """Attach each unresolved unknown to the row it concerns, as the CHOICE we
    made rather than the doubt we had.

    The wording is the interpreter's, written in the user's own language — a
    field-to-phrase table here would speak English at a Russian user and would
    have to grow a row for every lane we add.
    """
    by_name, out = {}, []
    for it in (items or []):
        if isinstance(it, dict):
            nm = str(it.get("food") or it.get("food_name") or "").strip().lower()
            if nm:
                by_name.setdefault(nm, []).append(it)
    for a in (ambiguities or []):
        if not isinstance(a, dict):
            continue
        said = str(a.get("assumed") or "").strip()
        if not said or len(said) > 80:
            continue
        for it in by_name.get(str(a.get("item") or "").strip().lower(), ()):
            it.setdefault("_assumed", []).append(
                {"field": str(a.get("field") or "").strip(), "text": said})
    for it in (items or []):
        out.append(it)
    return out


def _proposed_ask_is_material(data, *, mode: str, user) -> bool:
    """Whether the model's PROPOSED question survives the consequence engine.

    The interpreter recommends; this decides. Until now it did neither — a
    model `ask` returned before `plan_turn` was ever reached, so on every
    clarification the app has ever sent, the staging, the calibrated spans, the
    day-share and item-share dials and the user's own mode contributed exactly
    nothing. Measured over production food traffic: 100% of ask turns carried
    no scored consequence at all, and the ask rate was flat across modes
    (quick 25%, moderate 21%, strict 23%) because mode only ever reached the
    log path.

    Same rule as every other question in the system — `is_material`, against
    the user's targets, which do not move as the day fills. No food knowledge
    lives here: what the unknown is and what it is worth are the model's
    judgement, and whether that is worth interrupting someone for is ours.
    """
    from skills.nutrition.materiality import is_material

    reported = [a for a in (data.get("ambiguities") or []) if isinstance(a, dict)]
    if not reported:
        # UNWEIGHABLE, WHICH IS NOT THE SAME AS IMMATERIAL. A proposal that
        # reports no consequence gives us no grounds to say the question does
        # not matter — so we keep it. Reading silence as "no doubt" commits a
        # number nobody established: "3 pieces of chicken shish" is a spread of
        # several hundred calories depending on whether a piece is a chunk or a
        # whole skewer, and demoting that logs the parse instead of settling
        # it. The demotion has to be EARNED by a reported spread that scores
        # below the mode's bar, never granted by silence.
        return True

    targets = _daily_targets(user)
    by_name = {}
    for it in (data.get("items") or []) + (data.get("ready") or []):
        if isinstance(it, dict):
            nm = str(it.get("food") or it.get("food_name") or "").strip().lower()
            if nm:
                by_name[nm] = it

    for a in reported:
        try:
            span = float(a.get("impact_cal") or 0)
        except (TypeError, ValueError):
            continue
        item = by_name.get(str(a.get("item") or "").strip().lower()) or {}
        cal = item.get("calories")
        try:
            cal = float(cal) if cal is not None else None
        except (TypeError, ValueError):
            cal = None
        if is_material(mode=mode, calorie_span=span, item_calories=cal,
                       targets=targets, confidence=None):
            return True
    return False


def _daily_targets(user) -> Optional[dict]:
    """The user's daily goals, keyed the way the materiality scorer reads them.

    TARGETS, not what is left of them. What is left moves through the day, and
    scoring against it would hold the same food to a different standard
    depending on when it was logged — an entry backfilled at night judged more
    strictly than the same one typed at noon, and a retroactive log ("that was
    yesterday") measured against a remainder that does not apply to it. How
    precisely a food is understood cannot depend on the clock.

    Returns None on anything missing, which drops the scorer back to its
    absolute thresholds rather than losing the turn.
    """
    try:
        from core.targets import compute_macro_targets
        t = compute_macro_targets(user) or {}
        out = {}
        for key, source in (("calories", "calorie_target"),
                            ("protein", "protein_target"),
                            ("carbs", "carb_target"), ("fat", "fat_target")):
            value = t.get(source)
            if value:
                out[key] = float(value)
        return out or None
    except Exception as e:
        logger.debug(f"daily targets unavailable for materiality: {e}")
        return None


def _lc(name: str) -> str:
    """Sentence-case a food name for mid-sentence use: lowercase unless it
    reads branded (an uppercase beyond the first letter, or a digit)."""
    n = (name or "").strip()
    if any(c.isupper() for c in n[1:]) or any(c.isdigit() for c in n):
        return n
    return n.lower()


def _ready_name(entry) -> str:
    """`ready` used to be a list of names and is now a list of items. Accept
    both: the model is not versioned with the prompt, and a name-only reply
    must still render its recap rather than losing the food."""
    if isinstance(entry, dict):
        return str(entry.get("food") or entry.get("name") or "").strip()
    return str(entry or "").strip()


def ready_items(ready) -> list:
    """The `ready` entries that carry enough to actually be written.

    A name alone cannot be logged — which is why the partial commit was
    impossible on this path and why the reply still said "eggs and a banana
    logged" over a turn that wrote nothing. Only entries with a food and a
    calorie figure are returned, so a model that ignores the schema degrades to
    the old behaviour instead of writing rows it never costed.
    """
    out = []
    for entry in (ready or []):
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("food") or "").strip():
            continue
        if entry.get("calories") in (None, ""):
            continue
        out.append(entry)
    return out


def _looks_like_brand(label: str) -> bool:
    """Cheap check for the ask path, which has the point LABEL and not the item.

    The interpreter's `branded` flag is the authority and is consulted first;
    this only decides whether a variant lookup is worth one bounded request.
    """
    try:
        from skills.nutrition.branded import names_a_product
        return bool(names_a_product(label or ""))
    except Exception:
        return False


async def _variant_options(label: str, branded: bool) -> tuple:
    """The real variants of a branded product, as answer options.

    The composer offers a choice either way — it will say "the protein one or
    the plant-based" from world knowledge alone. This makes the choice the
    ACTUAL shelf: the flavours Open Food Facts holds, with their own numbers,
    so the option the user taps resolves to a real product instead of a
    plausible-sounding label nothing can look up.

    Bounded and optional by construction: read-only, capped by the turn's
    deadline, and every failure returns () — a clarification that loses its
    option list still asks its question.
    """
    if not branded or not (label or "").strip():
        return ()
    # Ask for one more than we would ever show. The extra is not for display —
    # it is how we learn whether we are looking at the WHOLE SHELF or a sample
    # of it, which decides whether listing is honest at all.
    _CEILING = 6
    try:
        from core import deadline
        from skills.nutrition.off import search_variants
        variants = await deadline.wait_for(search_variants(label, limit=_CEILING))
    except Exception as e:
        logger.debug(f"variant options unavailable for {label!r}: {e}")
        return ()
    seen, out = set(), []
    for v in variants or []:
        name = (v.get("name") or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    if len(out) >= _CEILING:
        # WE ONLY HAVE A SAMPLE. Naming three of a dozen flavours reads as the
        # full choice, so the answer gets anchored to a subset that may not
        # contain what they actually ate — and a wrong pick is worse than an
        # open question, because it commits a real product's numbers. Returning
        # nothing makes the composer ask which one, plainly, and their own
        # words then resolve against the whole database rather than our three.
        logger.debug(f"variant options withheld for {label!r}: shelf too wide")
        return ()
    return tuple(out)


def _calls_for_ready(ready) -> list:
    """Write calls for the foods an ask is NOT asking about.

    Built with the same `_log_call` the commit path uses, so provenance and
    units are decided in one place. Entries without calories are dropped by
    `ready_items` — a model that ignores the schema degrades to naming them,
    which is the old behaviour, rather than writing rows it never costed.
    """
    calls = []
    for item in ready_items(ready):
        call = _log_call(item)
        if call is not None:
            calls.append(call)
    return calls


def clarify_text_from_points(points: list, ready: list | None = None, *,
                             user_message: str = "") -> str:
    """The deterministic floor for `clarify_plan_from_points`.

    Kept so every existing caller and test gets the same text; the live path
    renders the plan through `food_response.render_plan`.
    """
    from core.food_response import fallback
    plan = clarify_plan_from_points(points, ready, user_message=user_message)
    return fallback(plan) if plan is not None else ""


def clarify_plan_from_points(points: list, ready: list | None = None, *,
                             user_message: str = "", items: list | None = None):
    """A clarification the INTERPRETER raised, phrased by the response layer.

    Every clarification goes through one renderer now, whatever noticed the
    ambiguity — the staged engine, the interpreter's own `ask`, or the
    calorie-only fallback. They used to have two: `clarify_text` built a
    FoodResponsePlan, and this path called `_format_question`, which spoke in
    system vocabulary the response contract had already retired ("locked in
    ✅", "Quick one so it's clean", "Nothing hits the board till then, keeps
    your log exact", numbered forms).

    The effect was not cosmetic. Two meals with near-identical uncertainty got
    different conversational treatment depending on which engine happened to
    notice it, and neither the user nor anyone reading a transcript could tell
    why. A response contract that governs one of its inputs is not a contract.

    The interpreter reports `points` (what it is unsure about) and `ready`
    (what it is not). Those map onto the plan's unresolved and resolved items
    exactly, so nothing is lost in the translation — only the phrasing moves to
    the layer that owns phrasing.
    """
    from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                    FoodResponsePlan, fallback)

    asks = []
    for point in points if isinstance(points, list) else []:
        if not isinstance(point, dict):
            continue
        label = str(point.get("label") or "").strip(", ").strip()
        qs = point.get("qs")
        if not isinstance(qs, list):
            qs = [point.get("q")]
        qs = [str(q).strip() for q in qs if q and str(q).strip()][:4]
        if qs:
            asks.append((label, qs))
    asks = asks[:4]
    if not asks:
        # Nothing to ask about. A PLAN builder returns no plan, not empty text
        # — the caller decides what an absent clarification means, and the
        # deterministic wrapper below turns it back into "".
        return None

    def _num(v):
        return int(v) if isinstance(v, (int, float)) else None

    # THE READING, WITH ITS NUMBERS. Nothing commits behind a clarification, so
    # no card carries the breakdown — and without it the composer can only ask,
    # never show. `items` is the interpreter's own costing of the whole meal.
    _priced = {}
    for it in (items or ()):
        if isinstance(it, dict):
            nm = str(it.get("food") or "").strip().lower()
            if nm:
                _priced[nm] = (_num(it.get("calories")), _num(it.get("protein")))

    def _summary(name: str):
        cal, pro = _priced.get(str(name).strip().lower(), (None, None))
        return FoodItemSummary(name=name, calories=cal, protein=pro)

    resolved = tuple(_summary(_ready_name(r))
                     for r in (ready or ()) if _ready_name(r))[:4]
    pending = tuple(_summary(label) for label, _ in asks if label)
    # Several facets of one item ("grilled or fried?", "skin on or off?") are
    # ONE question about that item. Joining them keeps the plan's promise that
    # `clarification_question` is a question and not a form.
    #
    # The label is NOT repeated into the question. The plan already carries the
    # item as `unresolved_item` and the renderer names it; prefixing it here
    # too produced "Chicken — chicken: grilled or fried?", which is the shape
    # the numbered form had, reassembled one layer down.
    # ONE QUESTION, about ONE item. The staged engine has always worked this
    # way — `should_ask` returns a single ambiguity — and the plan is shaped
    # for it: `unresolved_item` is singular. The interpreter can raise several
    # points at once, and concatenating them produced "How much did you leave?
    # roughly how much?", which is the numbered form again with the numbers
    # taken off.
    #
    # The items NOT asked about stay pending, so nothing commits behind an
    # unanswered question — they are named in the plan and the user sees them
    # held. Asking about them is the next turn's job.
    # Several facets of that ONE item ("grilled or fried?", "skin on or off?")
    # are still one question about it, so they stay together — each as its own
    # sentence, because the interpreter writes them lowercase as fragments of a
    # form while the staged engine writes whole sentences. Both land in the same
    # renderer now, so they have to arrive in the same shape, or the
    # unification is only structural and the user can still tell which engine
    # asked.
    # GROUPED, not picked. `asks[0][1][0]` shipped whichever fragment the
    # interpreter emitted first — for "some pasta some crudo some salad some
    # tartare" that was the sauce, worth ~100, while the four portions it
    # dropped were worth 2,760 between them. Grouping lets the shared unknown
    # win on its own evidence, and hands the renderer every unknown rather than
    # a pre-picked string.
    unknowns = group_unknowns(
        asks, user_message,
        priced={name: cal for name, (cal, _pro) in _priced.items() if cal})
    question = _situational_question(unknowns) or _one_question(asks[0][1])

    # APPLY THE POLICY. Both clarify builders live here and constructed the
    # plan directly, so it reached the renderer with the dataclass defaults —
    # `allow_question=False` among them. `validate()` then rejected the
    # composer's sentence with FORBIDDEN_QUESTION on the one intent whose
    # entire purpose is to ask, twice per turn, and `compose` returned the
    # deterministic floor every time.
    #
    # The composer has therefore never voiced a clarification in production.
    # Turning it on could not change how these read, because nothing it wrote
    # was ever allowed to ship. Every other plan builder gets this by living in
    # food_response, where the builders wrap their own returns.
    from core.food_response import apply_policy
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=resolved, pending_items=pending,
        unresolved_item=(pending[0] if pending else None),
        clarification_question=question,
        clarification_unknowns=unknowns,
        requires_answer=True, user_message=user_message))


def _situational_question(unknowns: tuple) -> str:
    """The deterministic FLOOR — situational, not a fixed shape.

    One unknown about one food is the sentence that always shipped, and its
    tests still pin it. An unknown shared by several foods is one question
    about all of them, because that is what it is: asking "how much of each"
    once resolves four portions, while asking four times is an interrogation
    the user abandons halfway through.

    Deliberately a floor. It has to be correct and cover the top unknown; the
    composer is handed every unknown and owns how the turn actually reads.
    """
    if not unknowns:
        return ""
    top = unknowns[0]
    items = list(top.get("items") or ())
    asks = list(top.get("asks") or ())
    if len(items) <= 1:
        # Unchanged from what shipped: one food, one unknown, its own wording.
        return _one_question(asks)
    # THE ITEMS ARE NOT NAMED AGAIN. The recap directly above this sentence
    # already lists them, and "Roughly how much of each — Pasta, Yellowtail
    # crudo, Caesar salad and Beef tartare?" is the bullet list read back with
    # a question mark on it. Two foods can be named in one breath; four is a
    # roll call, and "each" is unambiguous when the list is right there.
    if top.get("kind") == "portion":
        return "Roughly how much of each?"
    if top.get("kind") == "identity":
        return "Which ones were they?" if len(items) > 2 \
            else f"Which {_join_names([i.lower() for i in items])}?"
    return _one_question(asks)


def _join_names(names: list) -> str:
    """`a, b, c and d` — the way it is said out loud, not `a, b, c, d`."""
    names = [str(n).strip() for n in names if str(n or "").strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


#: What KIND of thing a facet is asking about. The interpreter writes facets as
#: form fragments ("rough amount - a cup or two?", "what sauce - red, cream?"),
#: and the kind is what lets several of them be recognised as ONE unknown asked
#: about four different foods. Order matters: "how much of the sauce" is a
#: portion question, so portion is tested first.
_FACET_KINDS = (
    ("portion", ("how much", "how many", "rough amount", "what size", "how big",
                 "portion", "oz", "grams", "how much of", "whole thing",
                 "full or", "share", "shared", "bites", "pieces", "cups")),
    ("identity", ("what kind", "which", "what sauce", "what type", "what brand",
                  "flavor", "flavour", "variety")),
    ("preparation", ("cooked", "grilled", "fried", "baked", "roasted", "raw",
                     "prepared", "skin on", "breaded")),
    ("extras", ("dressing", "added", "extra", "toppings", "with cheese",
                "butter", "oil", "sauce on")),
)


def _facet_kind(text: str) -> str:
    """Name the unknown a facet is about, in the coach's words rather than the
    form's. Unrecognised shapes get "detail" — honest, and it still groups."""
    t = (text or "").strip().lower()
    for kind, needles in _FACET_KINDS:
        if any(n in t for n in needles):
            return kind
    return "detail"


#: Plain-language names for each kind, for a renderer that has to say it out
#: loud. "consumed_quantity" produces a sentence that reads like a form.
_KIND_PHRASING = {
    "portion": "how much of each there was",
    "identity": "which one it was",
    "preparation": "how it was cooked",
    "extras": "what else was on it",
    "detail": "one missing detail",
}


def _portion_stakes(item_label: str, user_message: str) -> float:
    """Calories riding on an unstated portion, from the calibrated ontology.

    The same source `derive_vague_quantities` scores against, reached here so
    the QUESTION can be ranked by what it is worth before anything commits.
    Without a vague measure in the user's own words there is no span to claim,
    so this returns 0 rather than inventing one.
    """
    try:
        from core.food_pipeline import _vague_measure_in, _span_from
        from skills.nutrition.portions import distribution_for
        measure = _vague_measure_in(user_message or "", item_label or "")
        if not measure:
            return 0.0
        dist = distribution_for(measure, item_label or "")
        if dist is None or not dist.lower_g:
            return 0.0
        return float(_span_from(dist, None))
    except Exception:      # a ranking aid, never a reason to lose the turn
        return 0.0


def group_unknowns(asks: list, user_message: str = "",
                   priced: Optional[dict] = None) -> tuple:
    """The meal's unknowns, grouped by what is actually unknown.

    THE POINT OF THIS FUNCTION. Four foods described as "some" are not four
    questions, they are ONE question — how big were the portions — asked about
    four things at once. Extracting per item and then shipping whichever
    fragment came first is what produced "What sauce - red, cream, oil based?"
    for a message whose four portions were worth 2,288 calories of doubt
    between them.

    Groups carry the SUM of what they resolve, so a shared unknown outranks a
    single-item one on the evidence rather than by a rule, and the renderer is
    handed material to compose from instead of a pre-picked string.

    `priced` is the interpreter's own costing of the meal, keyed by lowered
    food name. With it a portion unknown reports ENDPOINTS rather than a width,
    which is what lets the reading be written as "somewhere between 230 and
    380" instead of a settled 230 with a question under it. Without it — and
    for an unknown nobody can price, which is most identity questions — the
    item is still marked open, and the brief's job is then to stop the reading
    asserting a figure it is about to ask about.
    """
    groups = {}
    for label, facets in asks:
        for facet in facets:
            kind = _facet_kind(facet)
            g = groups.setdefault(kind, {"items": [], "asks": [], "stakes": 0.0,
                                         "ranges": {}})
            if label and label not in g["items"]:
                g["items"].append(label)
                if kind == "portion":
                    span = _portion_stakes(label, user_message)
                    g["stakes"] += span
                    centre = (priced or {}).get(str(label).strip().lower())
                    if span > 0 and centre:
                        g["ranges"][label] = (max(0, round(centre - span / 2)),
                                              round(centre + span / 2))
            g["asks"].append(facet)
    out = []
    for kind, g in groups.items():
        # An unknown nobody could price still ranks — by how many foods it
        # covers — or a meal of unpriced items would always lose to one priced
        # one and never get asked about at all.
        #
        # The per-food figure is the MODERATE threshold on purpose. "Which
        # sauce" has no span until the candidates are priced, but a cream sauce
        # against a tomato one is a real swing, and treating unpriced as ~0 quietly
        # decided it was never worth asking. Sitting it at the moderate line
        # says what we actually know: material to someone who wants accuracy,
        # skippable for someone who asked to be left alone.
        weight = g["stakes"] or float(len(g["items"]) * 200)
        out.append({"kind": kind, "phrase": _KIND_PHRASING.get(kind, kind),
                    "items": tuple(g["items"]), "asks": tuple(g["asks"]),
                    "stakes": round(g["stakes"], 1), "weight": weight,
                    "ranges": dict(g["ranges"]), "options": ()})
    out.sort(key=lambda g: -g["weight"])
    return tuple(out)


def _one_question(facets: list) -> str:
    """ONE question, from however many facets arrived.

    Joining with a space kept each facet's own question mark, so a single ask
    shipped as "What kind of cheese and about how much - a slice or a bit
    sprinkled? How many slices of toast?" — two questions in one bubble, which
    is two things to answer and one to forget. It also cannot be offered as a
    quick reply, because there is no single thing being asked.

    Interior question marks are dropped and the facets are joined with ", and ",
    so what arrives is one sentence with one mark at the end.
    """
    parts = []
    for facet in facets:
        text = str(facet or "").strip().rstrip("?").strip().rstrip(",").strip()
        if text:
            parts.append(text)
    if not parts:
        return ""
    # ONE FACET. Joining them with ", and " still produced "What kind of cheese
    # and about how much, and how many slices of toast?" — one question mark
    # over two unrelated asks, which is not an improvement and cannot be a tap.
    # A reply the user can give in one gesture is worth more than covering the
    # whole meal in one turn, and the rest stays pending exactly as the comment
    # above promises.
    text = parts[0]
    return text[:1].upper() + text[1:] + "?"


def _format_question(points: list, ready: list | None = None) -> str:
    """RETIRED from routing — kept only for the gate evals that assert on its
    exact strings. Live clarifications go through `clarify_text_from_points`,
    and `tests/test_turn_ownership_invariant.py` fails if this is called from
    the turn again.

    The clarify moment in Arnie's older voice: an acknowledgment bubble for
    what's already locked (✅), the question with bolded items and facet
    bullets, and the hold guarantee as its own beat."""
    norm = []
    for p in points if isinstance(points, list) else []:
        if not isinstance(p, dict):
            continue
        label = str(p.get("label") or "").strip(", ").strip()
        qs = p.get("qs")
        if not isinstance(qs, list):
            qs = [p.get("q")]
        qs = [str(q).strip() for q in qs if q and str(q).strip()][:4]
        if qs:
            norm.append((label, qs))
    norm = norm[:4]
    if not norm:
        return ""
    bubbles = []
    ready_names = [_lc(_ready_name(r)) for r in (ready or []) if _ready_name(r)][:4]
    if ready_names:
        bold = [f"**{n}**" for n in ready_names]
        joined = (bold[0] if len(bold) == 1
                  else ", ".join(bold[:-1]) + " and " + bold[-1])
        bubbles.append(f"{joined} locked in ✅")
    if len(norm) == 1 and len(norm[0][1]) == 1:
        l, (q,) = norm[0]
        lead = "Just need the" if ready_names else "Quick one so it's clean, the"
        bubbles.append(f"{lead} **{_lc(l)}**: {q}" if l else
                       ("Just need one thing: " + q if ready_names
                        else "Quick one so it's clean: " + q))
        return "|||".join(bubbles)
    head = ("Just need a couple things:" if ready_names
            else "Quick one so it's clean:")
    lines = [head]
    for i, (label, qs) in enumerate(norm, 1):
        if len(qs) == 1:
            lines.append(f"{i}. **{_lc(label)}**: {qs[0]}" if label
                         else f"{i}. {qs[0]}")
        else:
            lines.append(f"{i}. **{_lc(label)}**" if label else f"{i}.")
            lines.extend(f"   • {q}" for q in qs)
    bubbles.append("\n".join(lines))
    bubbles.append("Nothing hits the board till then, keeps your log exact.")
    return "|||".join(bubbles)


def enforce_say_contract(say: str, tool_calls: list) -> str:
    """ENFORCE 'the system writes the numbers' — don't just request it. The model
    claimed 647 cal while its own card showed 343 (Danny IMG_8610). Digits in the
    say are allowed ONLY when they're quantities the system itself wrote (the
    amounts in the tool inputs — '2 tacos', '4 oz'); any other number (a calorie
    or macro claim) must come from a {token}, or the say is rejected and replaced
    with a deterministic tokenized line naming the items. The contract is physics."""
    raw = say or ""
    # A committed write's narration NEVER asks (Danny 2026-07-24: "all
    # clarification should be happening before the log"). If a detail was
    # worth a question, the action should have been ask — drop any sentence
    # carrying one; if nothing survives, the tokenized line below takes over.
    if "?" in raw:
        kept = [seg for seg in re.split(r"(?<=[.!?])\s+", raw.strip())
                if "?" not in seg]
        raw = " ".join(kept).strip()
    stripped = re.sub(r"\{[a-z_]{2,24}\}", "", raw)
    allowed = set()
    for tc in (tool_calls or []):
        inp = tc.get("input") or {}
        # Digits from the system's own writes are legal: quantities AND food
        # names ("Fage 0%", "5-hour Energy") — a product's digit is not an
        # invented total (sim battery 2026-07-24, 17/18 false positive).
        # food_hint covers update/delete/undo calls, whose narration names the
        # board entry ("Undone, took the 5-hour Energy off").
        for field in ("quantity", "food_name", "food_hint"):
            for m in re.finditer(r"\d+(?:\.\d+)?", str(inp.get(field) or "")):
                allowed.add(m.group(0).rstrip("0").rstrip(".") or "0")
    said = {m.group(0).rstrip("0").rstrip(".") or "0"
            for m in re.finditer(r"\d+(?:\.\d+)?", stripped)}
    if raw and said <= allowed:
        return raw
    names = [((tc.get("input") or {}).get("food_name") or "").strip()
             for tc in (tool_calls or [])]
    names = [n for n in names if n]
    if len(names) > 3:
        joined = f"{', '.join(names[:3])} and {len(names) - 3} more"
    elif names:
        joined = ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1
                                          else names[0])
    else:
        joined = "That"
    return (f"{joined} logged, {{batch_cal}} cal and {{batch_protein}}g protein. "
            f"You're at {{day_cal}} with {{cal_left}} left and {{protein_left}}g "
            f"protein to go.")


def fill_say_tokens(say: str, batch_cal: int, batch_protein: int,
                    day_cal: int, day_protein: int,
                    cal_target: int, protein_target: int) -> str:
    """The logger writes the WORDS; the system writes the NUMBERS. Token values
    come from the COMMITTED day (post-enrichment) so the numeric channel of the
    say can never disagree with the card/DB. Canonical fill lives in the ledger
    layer (core/food_ledger.fill_tokens); this wrapper keeps the historical
    signature for the legacy path and tests."""
    from core.food_ledger import fill_tokens
    return fill_tokens(say, {
        "batch_cal": batch_cal, "batch_protein": batch_protein,
        "day_cal": day_cal, "day_protein": day_protein,
        "cal_left": max(0, int(cal_target or 0) - day_cal),
        "protein_left": max(0, int(protein_target or 0) - day_protein),
    })


# ── ordered operations (fix #1): one plan, executed in the user's order ──────
def _normalize_ops(data: dict) -> list:
    """Normalize interpreter output into an ordered [(kind, op), ...] plan.
    Accepts the v2 shape ({"operations":[{"op":...}]}) and the v1 single-action
    shape (items/updates/deletes) — one executor path either way."""
    raw = data.get("operations")
    ops = []
    if isinstance(raw, list) and raw:
        for o in raw:
            if not isinstance(o, dict):
                continue
            k = str(o.get("op") or o.get("type") or "").strip().lower()
            if k in ("log", "update", "delete"):
                ops.append((k, o))
        return ops
    action = data.get("action")
    key = {"log": "items", "update": "updates", "delete": "deletes"}.get(action)
    if not key:
        return []
    return [(action, o) for o in (data.get(key) or []) if isinstance(o, dict)]


#: Asking for one entry to become several. The only intent in the vocabulary
#: that a single operation cannot satisfy.
_SPLIT_RE = re.compile(
    r"\b(separate|split|break\s+(?:out|up|down)|itemi[sz]e|"
    r"list\s+(?:them|those)\s+separately|as\s+two\s+(?:items|entries))\b",
    re.I)


def _asks_to_split(message: str) -> bool:
    """Did the user ask for an existing entry to be broken into components?"""
    return bool(_SPLIT_RE.search(message or ""))

#: Cap on a captured payload. A replay corpus is worth having and a log is not
#: a database — past this the line is a liability rather than a fixture.
_CAPTURE_MAX_CHARS = 2000


def _capture_interpreter_output(message: str, data) -> None:
    """Record the interpreter's raw plan so a real turn can be REPLAYED.

    Every fixture in the meal harness is a hand-authored guess at what this
    function receives. That is the harness's real weakness: if the model emits
    a shape nobody predicted, the tests exercise an invention and pass. Twelve
    invented meals also missed the interpreter's own `ask` path entirely, which
    is how a two-questions-in-one-bubble defect survived a file written to
    catch exactly that.

    One line per turn, and the corpus grows with USE rather than with someone
    remembering to add a case. Best-effort and bounded: a capture must never
    cost a user their log, and a log line must never become a data store.
    """
    try:
        if not isinstance(data, dict) or not data:
            return
        import json as _json
        payload = _json.dumps(data, separators=(",", ":"), default=str)
        if len(payload) > _CAPTURE_MAX_CHARS:
            payload = payload[:_CAPTURE_MAX_CHARS] + "\u2026"
        logger.info("event=interpreter_output msg=%r plan=%s",
                    (message or "")[:120], payload)
    except Exception:
        pass


def _log_call(it: dict, source: Optional[str] = None) -> Optional[dict]:
    if not isinstance(it, dict):
        return None
    food = str(it.get("food") or "").strip()
    # Structural sanity, not a guard pile: an item is a NAMED FOOD.
    if not food or "?" in food or len(food) > 60:
        return None
    amount = it.get("amount")
    unit = str(it.get("unit") or "").strip()
    try:
        amount = round(float(amount), 2)
        amount = int(amount) if float(amount).is_integer() else amount
    except (TypeError, ValueError):
        amount = None
    qty = f"{amount} {unit}".strip() if amount is not None else unit
    # First-class source + provenance (ledger fixes #15/"provenance"): the
    # write names its producer and where the amount came from; both persist
    # verbatim in the entry's raw_input, so "why did you log 6 oz?" has a
    # recorded answer instead of a plausible excuse.
    inp = {"food_name": food, "quantity": qty,
           "estimated": True, "confidence": 0.65,
           "source": source or _SOURCE}
    _basis = str(it.get("basis") or "").strip().lower()
    if _basis in ("stated", "regular", "estimate"):
        inp["basis"] = _basis
    # What we chose in place of asking. Persists in the entry's raw_input
    # alongside `source` and `basis`, so "why 6 oz?" keeps having a recorded
    # answer rather than a plausible excuse.
    _assumed = [a for a in (it.get("_assumed") or [])
                if isinstance(a, dict) and a.get("text")]
    if _assumed:
        inp["assumptions"] = _assumed[:3]
    if it.get("branded"):
        # The logger read the message — it declares brandedness; the
        # downstream heuristic (_looks_branded) is only the backup net, and
        # with the package-noun list completed that net is what actually
        # catches the named products the interpreter forgets to flag.
        inp["is_packaged"] = True
    for k in ("calories", "protein", "carbs", "fats"):
        v = it.get(k)
        if isinstance(v, (int, float)):
            inp[k] = v
    mt = str(it.get("meal_type") or "").strip().lower()
    if mt in ("breakfast", "lunch", "dinner", "snack"):
        inp["meal_type"] = mt
    _meal = str(it.get("meal") or "").lower().strip()
    if _meal in ("breakfast", "lunch", "dinner", "snack"):
        inp["meal_type"] = _meal
    return {"name": "log_food", "input": inp}


def _update_call(up: dict, board_by_id: dict,
                 defer_macros: bool = False) -> Optional[dict]:
    if not isinstance(up, dict):
        return None
    try:
        eid = int(up.get("entry_id"))
    except (TypeError, ValueError):
        return None
    line = board_by_id.get(eid)
    if line is None:
        return None          # structural: only entries actually on the board
    inp = {"entry_id": eid}
    amount = up.get("amount")
    unit = str(up.get("unit") or "").strip()
    try:
        amount = round(float(amount), 2)
        amount = int(amount) if float(amount).is_integer() else amount
        inp["quantity"] = f"{amount} {unit}".strip()
    except (TypeError, ValueError):
        pass
    # A CORRECTION MAY CHANGE WHAT IT WAS, not just how much. There was no path
    # for that here: `inp` carried a quantity and four macros, so "it was
    # actually a filled Twizzler" arrived as a macro edit and the executor's
    # re-resolution — gated on `changes.get("food_name")` — could never fire
    # from this lane. What shipped instead was the model's own figure: 140
    # calories, the whole pack, written against a quantity of one piece.
    renamed = str(up.get("food") or up.get("food_name") or "").strip()
    if renamed:
        inp["food_name"] = renamed

    for k in ("calories", "protein", "carbs", "fats"):
        v = up.get(k)
        if isinstance(v, (int, float)):
            # THE LADDER OWNS THE NUMBERS FOR A NEW IDENTITY. Keeping the
            # model's macros here would win: the executor only fills what the
            # re-resolution returns, and a supplied value is what it re-resolved
            # against. A different product is a lookup, not a recollection.
            #
            # ONLY WHEN THE UPDATE STANDS ALONE. In a SPLIT the rename arrives
            # inside a multi-operation plan — "separate the toast and cheese" is
            # [update, log] — and its macros are a PARTITION of a total already
            # on the board, not something remembered. Dropping those loses the
            # component's share and the split stops conserving.
            if renamed and defer_macros:
                continue
            inp[k] = v
    # Compare-and-swap seed (fix #9): the interpreter targeted this entry
    # holding a board snapshot; the executor refuses the write if the row has
    # since changed materially (cross-device edit, enrichment drift) — a
    # scale computed from stale numbers corrupts the entry.
    try:
        inp["expected_calories"] = float(line.get("cal") or 0)
    except (TypeError, ValueError):
        pass
    _hint = str(line.get("food") or "").strip()
    if _hint:
        inp["food_hint"] = _hint
    if str(up.get("date") or "").strip():
        # move-to-date rides the update primitive ("that was yesterday").
        inp["date"] = str(up["date"]).strip()
    inp["source"] = _SOURCE
    return {"name": "update_food_entry", "input": inp}


def _delete_call(d: dict, board_by_id: dict) -> Optional[dict]:
    if not isinstance(d, dict):
        return None
    try:
        eid = int(d.get("entry_id"))
    except (TypeError, ValueError):
        return None
    line = board_by_id.get(eid)
    if line is None:
        return None          # structural: never delete an id not on the board
    inp = {"entry_id": eid, "source": _SOURCE}
    _hint = str(line.get("food") or "").strip()
    if _hint:
        inp["food_hint"] = _hint
    return {"name": "delete_food_entry", "input": inp}


def _parse(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    start = t.find("{")
    if start < 0:
        return None
    try:
        return json.loads(t[start:t.rfind("}") + 1])
    except Exception:
        return None


def _fast_path_items(data) -> tuple:
    """(food, amount, unit) per item, comparable across the two paths."""
    if not isinstance(data, dict):
        return ()
    out = []
    for item in (data.get("items") or []):
        if not isinstance(item, dict):
            continue
        out.append((
            str(item.get("food") or item.get("food_name") or "").strip().lower(),
            item.get("amount") if item.get("amount") is not None
            else item.get("grams"),
            str(item.get("unit") or "").strip().lower()))
    return tuple(out)


def _log_fast_path_shadow(parsed, model_data) -> None:
    """Record what the fast path WOULD have done against what the model did.

    The step that has to come before the parser is trusted with a write: the
    review's rollout note asks for the disagreement rate measured in shadow, and
    a rate nobody emits cannot be measured. Deliberately compares only the fields
    the fast path claims to decide — how much and how many, never what.
    """
    try:
        fast_items = _fast_path_items(parsed)
        model_items = _fast_path_items(model_data)
        model_action = (model_data or {}).get("action") \
            if isinstance(model_data, dict) else None
        agree = (fast_items == model_items and model_action == "log")
        logger.info(
            "event=food_fast_path_shadow "
            f"agree={str(agree).lower()} "
            f"fast_items={len(fast_items)} model_items={len(model_items)} "
            f"model_action={model_action or '-'} "
            f"version={FAST_PATH_VERSION_FOR_SHADOW}")
    except Exception:
        pass


try:                                    # pragma: no cover - import shape only
    from core.food_fast_path import FAST_PATH_VERSION as _FPV
    FAST_PATH_VERSION_FOR_SHADOW = _FPV
except Exception:                       # pragma: no cover
    FAST_PATH_VERSION_FOR_SHADOW = "unknown"


def _handle_clarification_command(command, prior: Optional[dict],
                                  message: str) -> Optional[dict]:
    """A command settles the turn deterministically, or returns None.

    None means "the interpreter should still run" — for ESTIMATE, which is not
    a refusal but an instruction to decide, and deciding is what the
    interpreter is for. The difference matters: SKIP and CANCEL are the user
    declining to answer, and a model asked to interpret a decline can talk
    itself into asking again.
    """
    from skills.nutrition.answer_parsers import ClarificationCommand as _C

    items = [i for i in ((prior or {}).get("items") or [])
             if isinstance(i, dict)]

    if command is _C.CANCEL_MEAL:
        logger.info("event=clarify_command cmd=cancel_meal")
        return {"action": "pass",
                "text": "Dropped it — nothing went on the board."}

    if command is _C.SKIP_ITEM:
        # The held item is dropped; anything already understood still commits.
        # Skipping one item has never meant abandoning the meal, and the ledger
        # work made "what else was ready" answerable.
        logger.info("event=clarify_command cmd=skip_item items=%d", len(items))
        return {"action": "pass",
                "text": "Left that one off. Everything else stands."}

    if command is _C.COMMIT_READY:
        logger.info("event=clarify_command cmd=commit_ready")
        return None

    if command is _C.ESTIMATE:
        # NOT a short-circuit. "Use your best guess" asks us to decide, and the
        # interpreter is what decides — the command only records that the user
        # authorised it, so the disclosure can say the estimate was requested
        # rather than assumed.
        logger.info("event=clarify_command cmd=estimate")
        return None

    return None


def _conversational_ctx(data):
    """`_context_from` as the typed object the response plan wants.

    Built here because the ask path renders inside this module — `clarify_plan`
    needs the object, not the dict. The import stays function-local so the
    module-level dependency still runs one way.
    """
    raw = _context_from(data)
    if not raw:
        return None
    try:
        from core.food_response import ConversationalContext
        return ConversationalContext(
            topic=raw["topic"], user_statement=raw["said"],
            emotional_signal=raw["signal"],
            response_obligation=raw["obligation"], priority=raw["priority"])
    except Exception:
        return None


def _context_from(data) -> Optional[dict]:
    """The interpreter's `context` object, sanitised, or None.

    Kept as a plain dict here because `core.food_turn` must not import the
    response layer — `core.food_response` is downstream of this module, and the
    dependency only runs one way. `core.conversation` builds the
    `ConversationalContext` from it.

    Absent is the common case and the right default. A message that is only
    about food carries no obligation, and inventing one would make every meal
    log sound like it was consoling someone.
    """
    raw = (data or {}).get("context")
    if not isinstance(raw, dict):
        return None
    topic = str(raw.get("topic") or "").strip()[:120]
    said = str(raw.get("said") or "").strip()[:300]
    if not (topic or said):
        return None
    priority = str(raw.get("priority") or "normal").strip().lower()
    if priority not in ("normal", "important", "urgent"):
        priority = "normal"
    return {
        "topic": topic, "said": said,
        "signal": str(raw.get("signal") or "").strip()[:60],
        "obligation": (str(raw.get("obligation") or "").strip()[:120]
                       or "briefly acknowledge"),
        "priority": priority,
    }


def parse_prior_answer(message: str, prior: Optional[dict]):
    """The user's answer, read by the parser we asked the question with.

    `skills/nutrition/answer_parsers` was imported by no production code. The
    deterministic parsers — "the elite one", "about a cup", "skip it", "not
    sure" — existed, were tested by the transcript replay suite, and the live
    answer turn re-ran the whole interpreter instead. So the suite exercised a
    path production did not take, "skip it" was a judgement call by a model
    rather than a command, and an answer reached the item as prose to be
    re-parsed rather than as the field it settles.

    Returns a `ClarificationAnswer`, or None when there is nothing to parse
    against. UNPARSED is a legitimate outcome and means exactly what it says:
    the answer did not fit the shape we asked for, so the interpreter takes it
    — with the question still bound to its item.
    """
    if not prior or not (message or "").strip():
        return None
    try:
        from skills.nutrition.answer_parsers import (parse_answer,
                                                     parse_command)
        from skills.nutrition.clarify_policy import ClarificationQuestion

        # A COMMAND needs no question. "Cancel" means cancel whatever we asked,
        # and requiring a schema to recognise it would make the deterministic
        # half depend on the part most likely to be missing.
        command = parse_command(message)
        if command is not None:
            from skills.nutrition.answer_parsers import ClarificationAnswer
            return ClarificationAnswer(command=command)

        schema = str(prior.get("response_schema") or "").strip()
        if not schema:
            return None
        question = ClarificationQuestion(
            question_id=str(prior.get("question_id") or ""),
            staged_item_id=str(prior.get("staged_item_id") or ""),
            requested_fields=tuple(prior.get("requested_fields") or ()),
            prompt=str(prior.get("question") or ""),
            response_schema=schema,
            options=tuple(prior.get("options") or ()))
        return parse_answer(message, question)
    except Exception as e:
        logger.warning(f"answer parse skipped: {e}")
        return None


async def run(message: str, user, prior: Optional[dict] = None,
              day_line: str = "", board: Optional[list] = None,
              last_assistant: str = "", regulars: Optional[list] = None,
              thread_active: bool = False) -> Optional[dict]:
    """The traced entry point (PR #29).

    A thin wrapper rather than instrumentation threaded through the body: the
    interpreter pass has a dozen return points, and making each of them
    responsible for closing a trace would mean the one that got missed is the
    one that mattered. One entry, one exit.

    This is a `span`, not a `begin`/`finish` pair, because this function is NOT
    the whole food turn. It returns the structured action and the tool calls;
    the writes, the cards and the coaching line all happen after it, in the
    coordinator. Owning the trace here ended it before the interesting half —
    resolution, the commits, the render — so the coordinator opens it now and
    this defers when it finds one. Direct callers (tests, the simulator) still
    get a trace of the interpreter pass on its own.

    Everything about the trace is best-effort: `span` yields None when tracing
    is off, so the wrapper costs a function call and nothing else.
    """
    from core import food_trace

    fields = {}
    try:
        from core.turn_identity import current_turn_id
        from skills.nutrition.canary import cohort_label
        fields = dict(turn_id=(current_turn_id() or ""),
                      user_id=getattr(user, "id", None), mode=_mode(user),
                      cohort=cohort_label(getattr(user, "id", None)))
    except Exception:
        fields = {}

    with food_trace.span(**fields):
        return await _run_untraced(
            message, user, prior=prior, day_line=day_line, board=board,
            last_assistant=last_assistant, regulars=regulars,
            thread_active=thread_active)


async def _run_untraced(message: str, user, prior: Optional[dict] = None,
                        day_line: str = "", board: Optional[list] = None,
                        last_assistant: str = "",
                        regulars: Optional[list] = None,
                        thread_active: bool = False) -> Optional[dict]:
    """Run the interpreter pass. Returns
        {"action": "log"|"update"|"delete"|"commit", "tool_calls": [...],
         "kinds": [...], "say": "...", "note": "...", "follow_up": "..."}
            an ordered transaction plan (homogeneous plans keep their kind as
            the action label; mixed plans are "commit")
        {"action": "ask", "text": "...", ...}      the formatted question —
            answer-turn and policy asks also carry "points"; strict pre-write
            confirms carry kind="confirm" + "items" + the held "tool_calls"
        None                                       pass / any failure → legacy path
    board: today's committed entries [{"id", "food", "qty", "cal"}] so corrections,
    deletes and references ("2 of those") resolve deterministically against real
    ids. thread_active: an active food thread relaxes the cold-start consumption-
    evidence requirement for additions ("also a coke with it"). ONE model call
    per food turn — the narration material rides the same JSON. Never raises."""
    if not (message or "").strip():
        return None

    # ── THE ANSWER IS READ BY THE PARSER THAT ASKED THE QUESTION ────────────
    #
    # A command is deterministic and settles the turn without a model call:
    # "skip it" means skip it, and asking a model whether it meant skip is how
    # a stated instruction becomes a judgement.
    _parsed = parse_prior_answer(message, prior)
    if _parsed is not None and _parsed.command is not None:
        _cmd = _handle_clarification_command(_parsed.command, prior, message)
        if _cmd is not None:
            return _cmd
    # A PARSED VALUE rides into the interpreter's context as a settled field
    # rather than as prose to re-read. The interpreter still composes the meal
    # — it owns the items — but it is told what the answer WAS instead of being
    # asked to work it out a second time, which is where the previous number
    # used to come back unchanged.
    _answer_line = ""
    if _parsed is not None and _parsed.values:
        _answer_line = ("\nThat answer resolves: "
                        + ", ".join(f"{k}={v}" for k, v in
                                    sorted(_parsed.values.items()))[:200])
        if _parsed.disclosure:
            _answer_line += f" (assumed: {_parsed.disclosure})"

    if prior:
        content = (
            f"Earlier they reported: \"{prior.get('original', '')}\"\n"
            f"You asked: \"{prior.get('question', '')}\"\n"
            f"They just answered: \"{message}\"" + _answer_line)
    else:
        content = message
    if (last_assistant or "").strip():
        content = (f"Your previous message to them: "
                   f"\"{last_assistant.strip()[:300]}\"\n\n{content}")
    if regulars:
        lines = []
        for r in regulars[:8]:
            try:
                # A malformed regular must never silently vanish from context —
                # an invisible regulars list makes the pointer rules dead letters.
                _n = r.get("name") or r.get("food") or ""
                if not _n:
                    continue
                r = {**r, "name": _n}
                lines.append(f"- {r['name']} ({r.get('qty') or '1'}) — "
                             f"{int(r.get('calories') or 0)} cal, "
                             f"{int(r.get('protein') or 0)}P/"
                             f"{int(r.get('carbs') or 0)}C/"
                             f"{int(r.get('fats') or 0)}F "
                             f"(logged {r.get('count', 0)}x)")
            except Exception:
                continue
        if lines:
            content = (f"{content}\n\nTHEIR REGULARS (their own logged history — "
                       f"when an item matches one, use these exact macros, never "
                       f"re-estimate; in an ask, offer the regular by name):\n"
                       + "\n".join(lines))
    if board:
        lines = board_lines(board)
        if lines:
            content = f"{content}\n\nTODAY'S BOARD (already logged):\n" + "\n".join(lines)
    if day_line:
        content = f"{content}\n\nDay context for the 'say' line: {day_line}"
    mode = _mode(user)

    # The zero-model-call path. "150g chicken breast" has one reading, and
    # spending a round trip to discover that is most of the latency the user
    # experiences. The parser refuses everything it cannot prove, so a miss
    # costs what the turn costs today and a hit costs nothing.
    #
    # Only for a cold turn: a `prior` means this is an answer to a question we
    # asked, which needs the question's context, and a thread means the message
    # may reference what came before.
    data = None
    _shadow_parse = None
    if not prior and not thread_active and not board:
        try:
            from core.food_fast_path import (parse as _fast_parse,
                                             fast_path_enabled,
                                             shadow_enabled)
            if fast_path_enabled():
                data = _fast_parse(message)
                if data is not None:
                    logger.info(f"event=food_fast_path outcome=parsed "
                                f"items={len(data.get('items') or [])}")
            elif shadow_enabled():
                # SHADOW: parse, keep the result, act on none of it. The model
                # runs as usual below and the two are compared, which is how the
                # disagreement rate gets measured before the parser is trusted
                # with a write.
                _shadow_parse = _fast_parse(message)
        except Exception as _fe:
            logger.warning(f"fast path skipped: {_fe}")
            data = None

    if data is None:
        from skills.nutrition.materiality import (day_fraction_for,
                                                  fraction_for,
                                                  min_item_share_for)
        _of_item = fraction_for(mode)
        sys = (_SYSTEM
               .replace("{of_item}", ("any share" if _of_item > 1.0
                                      else f"{_of_item:.0%}"))
               .replace("{of_day}", f"{day_fraction_for(mode):.1%}")
               .replace("{item_share}", f"{min_item_share_for(mode):.1%}")
               .replace("{thresh}", str(_THRESH[mode]))
                      .replace("{mode}", mode))
        try:
            # Under the turn's budget like everything else that waits. The
            # interpreter pass is the single largest block in a food turn — a
            # forty-five-second model timeout inside a twenty-second turn budget
            # meant the "turn budget" could not bound the turn's biggest wait.
            from core import deadline
            res = await deadline.wait_for(
                chat([{"role": "user", "content": content}], sys,
                     tools=False, max_tokens=700, model=_logger_model()))
        except Exception as e:
            # Includes DeadlineExceeded: out of time is a fall-through to the
            # legacy path, never a lost meal.
            logger.warning(f"food_turn logger pass failed: {e}")
            return None
        data = _parse(res.get("text") or "")
        _capture_interpreter_output(message, data)
        if _shadow_parse is not None:
            _log_fast_path_shadow(_shadow_parse, data)
    if not isinstance(data, dict):
        return None
    action = data.get("action")

    if action == "ask" and not prior and not _proposed_ask_is_material(
            data, mode=mode, user=user) and (data.get("items")
                                             or data.get("ready")):
        # PROPOSAL DECLINED. The model wanted to ask; nothing it reported is
        # worth interrupting for at this mode. Commit its own best estimate
        # instead — which the prompt now requires it to carry for exactly this
        # case — and fall through to the ordinary log path below.
        data = dict(data)
        # MERGED BY IDENTITY, NOT BY DICT EQUALITY. `ready` and `items` overlap
        # — the same food appears in both whenever the model lists everything
        # it parsed and then repeats the settled ones — and `i not in items`
        # compares whole dicts, so one differing key (a basis, a rounded macro)
        # made a second copy of the same food. That wrote six rows for four
        # foods in a single turn, with the reply narrating it: "you've logged
        # two dark chocolates instead of one".
        _merged, _seen = [], set()
        for _it in list(data.get("items") or []) + list(data.get("ready") or []):
            if not isinstance(_it, dict):
                continue
            _key = str(_it.get("food") or _it.get("food_name") or "").strip().lower()
            if _key and _key in _seen:
                continue
            if _key:
                _seen.add(_key)
            _merged.append(_it)
        data["items"] = _merged
        data["action"] = action = "log"
        data.pop("points", None)
        # DECLINING THE QUESTION IS NOT THE SAME AS RESOLVING IT. We judged the
        # unknown too small to interrupt for — we did not learn the answer, we
        # picked one. So the pick rides along to the write and onto the card,
        # where a tap corrects it. Otherwise the quieter mode is simply the one
        # that hides its guesses, which is the opposite of what quick is for.
        data["items"] = _carry_assumptions(data["items"],
                                           data.get("ambiguities"))

    if action == "ask" and not prior:
        # Through the ONE renderer, so the question is voiced rather than
        # assembled from rotating openers. Falls back to exactly the previous
        # deterministic text whenever the composer is off or unhappy.
        from core.food_response import render_plan as _render
        from core.food_response import with_context as _ctx
        _plan = clarify_plan_from_points(data.get("points") or [],
                                         data.get("ready"),
                                         user_message=message,
                                         items=data.get("items"))
        # REAL VARIANTS AS THE OPTIONS, when the thing being asked about is a
        # branded product. `build_prompt` already passes `clarification_options`
        # to the composer; they were simply never populated on this path.
        if _plan is not None and not _plan.clarification_options:
            # EVERY branded unknown, not just the first. Looking up only
            # `points[0]` meant a meal with two branded products got the real
            # shelf for one of them and invented options for the other — "the
            # protein one or the allulose one" for a line whose flavours are
            # all protein bars. Options are labelled with the product they
            # belong to, because an unlabelled pool of flavours spanning two
            # products is worse than none.
            _branded_any = any(bool(i.get("branded"))
                               for i in (data.get("items") or [])
                               if isinstance(i, dict))
            _labels = [str(p.get("label") or "").strip()
                       for p in (data.get("points") or [])
                       if isinstance(p, dict) and str(p.get("label") or "").strip()]
            _found = []
            for _lb in _labels[:3]:
                if not (_branded_any or _looks_like_brand(_lb)):
                    continue
                _v = await _variant_options(_lb, True)
                if _v:
                    _found.append(f"{_lb}: " + ", ".join(_v))
            if _found:
                import dataclasses as _dc
                _plan = _dc.replace(_plan, clarification_options=tuple(_found))
        text = (await _render(_ctx(_plan, user=user, day_state=day_line))
                if _plan is not None else "")
        # THE READY FOODS GO ON THE BOARD. The recap has always named them as
        # settled — "So you've got eggs and a banana logged" — over a turn that
        # wrote nothing, because `ready` carried names and a name cannot be
        # written. It carries items now, so the foods we are NOT asking about
        # commit while the one we are asking about waits.
        # RELEASED, and it belongs HERE as much as on the pipeline branch. The
        # partial commit only ever existed where the staged pipeline raised the
        # question; when the interpreter proposes the ask itself — which is
        # most asks — this returned the question alone and the settled foods
        # waited too. Measured: 1 of 6 mixed meals committed anything.
        #
        # Safe for the same reason the other branch is: the answer turn now
        # sees these rows on the board with their age, so refining them is an
        # update rather than a second write.
        _ready_now = _calls_for_ready(data.get("ready"))
        return ({"action": "ask", "text": text, "tool_calls": _ready_now}
                if text else None)

    if action == "ask" and prior:
        # An unprompted ask on the answer turn = the model chaining its own
        # questions — refused by default (never loop). Two legitimate lifts:
        # the USER invited it ("don't you wanna know what kind?"), or their
        # answer introduced a NEW material unknown (model sets new_ambiguity)
        # and we haven't already asked twice — bounded information gain, not
        # an absolute one-question ceiling (fix #11).
        _user_invited = bool(re.search(
            r"\?|\b(what|which|don'?t\s+you|shouldn'?t\s+you|why\s+not)\b",
            message or "", re.I))
        _ask_count = int((prior or {}).get("ask_count") or 1)
        _new_amb = bool(data.get("new_ambiguity"))
        if data.get("points") and (_user_invited or (_new_amb and _ask_count < 2)):
            from core.food_response import render_plan as _render
            from core.food_response import with_context as _ctx
            _p2 = clarify_plan_from_points(data["points"], data.get("ready"),
                                           user_message=message)
            return {"action": "ask",
                    "text": (await _render(_ctx(_p2, user=user,
                                                day_state=day_line))
                             if _p2 is not None else ""),
                    "points": data["points"]}
        return None

    ops = _normalize_ops(data)
    if not ops:
        return None

    # Consumption-evidence invariant (fix #3): drop any log op the message
    # cannot support — an interrogative or evidence-free cold message never
    # yields a write, whatever action the model chose. Updates and deletes
    # are board-anchored corrections; they stand on their own intent.
    #
    # A SPLIT IS NOT A NEW CONSUMPTION CLAIM, and this is where the missing
    # calories actually went. "Can you separate the toast and cheese for me in
    # my log." is an interrogative, so the invariant dropped the `log` op — and
    # the interpreter had produced the RIGHT plan: update the entry to the
    # cheese, log the toast. Half of it was deleted here, one component was
    # renamed, and 105 calories disappeared from a day the user then had to
    # audit by hand.
    #
    # The invariant is correct in general: "does a chicken caesar have 700
    # calories?" must never write a row. But a log op that accompanies an
    # UPDATE on an entry already on the board is not asserting a new meal — it
    # is the second half of a restructure of a meal already asserted. The
    # consumption evidence for it was given when the composite was logged.
    _restructure = ("update" in [k for k, _ in ops]
                    and _asks_to_split(message))
    if any(k == "log" for k, _ in ops) and not _restructure \
            and not consumption_evidence(
                message, prior=prior, thread_active=thread_active):
        ops = [(k, o) for k, o in ops if k != "log"]
        if not ops:
            return None

    # ── §2, §3, §4, §5: the answer turn revalidates ─────────────────────────
    #
    # An answer turn used to be treated as automatically safe: the policy
    # engine was skipped outright ("that turn fills with best estimates instead
    # of re-asking"), so whatever the user said was folded into the previous
    # interpretation and written. That is right for an answer that ADDS a
    # detail and wrong for one that CHANGES the unit, because the unit is what
    # every downstream value was derived from.
    #
    # "3 skewers" corrected to "3 pieces" keeps the count, which is exactly why
    # it looks like nothing happened. The mass, the count basis, the portion
    # assumption, the resolver's winner and the macros were all computed for
    # skewers, and none of them survive.
    if prior is not None and any(k == "log" for k, _ in ops):
        _blocked = _revalidate_after_answer(ops, prior, message, _mode(user))
        if _blocked is not None:
            return _blocked

    # Declared out here because the VETO below reads it. It used to live
    # entirely inside the branch that produces it, which is a fair description
    # of the seam being closed: the decision existed only where it was made,
    # and the place that executes never saw it.
    _decision = None

    # Policy engine (fix #12, first inversion step): the model REPORTS the
    # ambiguities it estimated through; the SYSTEM decides whether any of
    # them is worth holding the write for. Never on the answer turn — that
    # turn fills with best estimates instead of re-asking.
    if prior is None and any(k == "log" for k, _ in ops):
        # THE STAGED-ITEM PIPELINE OWNS THIS (Danny 2026-07-25). The old policy
        # read one number — the model's impact_cal — against calorie-only
        # thresholds, so an item that was calorie-tight and protein-wild sailed
        # through. core/food_pipeline.py stages the items, scores calorie,
        # protein, carb, fat, identity and serving-basis risk, applies learned
        # preferences, and ranks questions across the WHOLE meal instead of
        # firing on the first material one.
        #
        # Same call from both callers: the live turn arrives here, and the
        # coordinator's food stage delegates to this function — so promoting
        # the coordinator changes orchestration, not food intelligence.
        # THE PIPELINE RUNS FIRST, ALWAYS.
        #
        # Strict's whole-parse confirm used to SUPPRESS it: `plan_turn` was
        # gated on `not _strict_confirm_pending`, so whenever strict wanted a
        # confirmation the staging, normalization and ambiguity derivation
        # never ran at all. The reasoning was that a confirm is the better
        # exchange than interrogating one item — true when the alternative is a
        # question about something the confirm would settle, and false when the
        # alternative is a question the confirm CANNOT settle.
        #
        # "3 pieces of chicken shish" is the second case. A piece may be a
        # chunk or a whole skewer, a spread of several hundred calories, and
        # "does that look right?" over a parse that already says "3 pieces"
        # does not ask it — the user says yes to a number nobody established.
        # A generic confirmation may never stand in for an unresolved unit
        # question, so the order is now: stage, normalize, derive, resolve what
        # is material, and only then decide whether a final review is useful.
        try:
            from core.food_pipeline import pipeline_enabled, plan_turn
            if pipeline_enabled():
                from core.turn_identity import current_turn_id as _pipe_turn
                # WHAT THE SHELF SAYS, fetched before the decision because the
                # decision is synchronous. The model cannot know which other
                # products share the name it just wrote; the database can, and
                # a name spanning two product forms is a doubt nobody was
                # reporting.
                _targets = _daily_targets(user)
                _spreads = await _variant_spreads(data, mode=mode,
                                                  targets=_targets)
                _decision = plan_turn(
                    data, turn_id=(_pipe_turn() or ""), message=message,
                    mode=mode, preferences=_prefs_for(user),
                    targets=_targets,
                    variant_spreads=_spreads)
        except Exception as _pe:
            logger.warning(f"food pipeline unavailable: {_pe}")
            _decision = None

        if _decision is not None and _decision.asks:
            _q = _decision.question
            # The interpretation AND the question, in one turn. Sending the
            # bare question made the user answer about a food they had not
            # been shown our reading of; sending "does that look right?" first
            # and the question second spent two turns and invited them to
            # approve an assumption they never saw.
            from core.food_response import render_plan as _render
            from core.food_response import with_context as _ctx
            _text = await _render(_ctx(
                clarify_plan(_decision, _q, user_message=message,
                             context=_conversational_ctx(data)),
                user=user, day_state=day_line))
            # PARTIAL COMMIT. Moderate's contract is that the foods already
            # confident enough go on the board, with the assumption stated,
            # while the one still in question is asked about — not that the
            # whole meal waits on the least certain item in it.
            #
            # The veto already computes exactly this: it drops the HELD items'
            # log calls and returns the rest. It simply never ran on an ask,
            # because this branch returns first, so an ask committed nothing in
            # any mode and PARTIAL_COMMIT behaved as ATOMIC_HOLD.
            #
            # Built with the same `_build_calls` the commit path uses, so there
            # is one definition of what a write is.
            _ready_calls = []
            try:
                _board_by_id = {}
                for _b in (board or []):
                    try:
                        _board_by_id[int(_b["id"])] = _b
                    except Exception:
                        continue
                _c, _k, _il = _build_calls(ops, _board_by_id)
                _ready_calls, _, _, _ = _apply_clarification_veto(
                    _decision, _c, _k, _il)
            except Exception as _ve:
                # A partial commit is an improvement, never a precondition —
                # losing it costs an extra turn, losing the QUESTION loses the
                # meal.
                logger.warning(f"partial-commit calls unavailable: {_ve}")
                _ready_calls = []
            return {"action": "ask", "text": _text,
                    "tool_calls": _ready_calls,
                    "points": [_q.prompt],
                    "question_id": _q.question_id,
                    "staged_item_id": _q.staged_item_id,
                    "requested_fields": list(_q.requested_fields),
                    # THE SHAPE WE ASKED FOR travels too. `parse_answer`
                    # dispatches on `response_schema` — without it the narrow
                    # parsers cannot run at all, which is why they sat unwired
                    # while the answer turn re-ran the whole interpreter.
                    "response_schema": getattr(_q, "response_schema", "") or "",
                    "options": [str(o) for o in
                                (getattr(_q, "options", ()) or ())][:6],
                    # THE PRIOR INTERPRETATION TRAVELS WITH THE QUESTION (§2).
                    # An answer turn has to rebuild the affected item from the
                    # user's original wording, what we made of it, and what
                    # they just said. Without this it had only the first and
                    # the third, so "3 pieces" arriving after we had read "3
                    # skewers" looked like a fresh parse with nothing to
                    # compare against — and nothing to invalidate.
                    "items": data.get("items") or None,
                    "meal_group_id": _decision.meal_group_id}

        if _decision is None:
            # Pipeline off or unavailable — the calorie-only policy still
            # stands rather than the turn losing its ask entirely. It used to
            # be suppressed whenever strict's whole-parse confirm was pending;
            # with the confirm gone there is nothing left to defer to.
            from core import food_ledger as _FL
            _mat = _FL.material_ambiguities(data.get("ambiguities"), mode)
            if _mat:
                _pts = _FL.ambiguity_points(_mat)
                from core.food_response import render_plan as _render
                from core.food_response import with_context as _ctx
                _p3 = clarify_plan_from_points(_pts, user_message=message)
                _txt = (await _render(_ctx(_p3, user=user,
                                           day_state=day_line))
                        if _p3 is not None else "")
                if _txt:
                    return {"action": "ask", "text": _txt, "points": _pts}

    board_by_id = {}
    for b in (board or []):
        try:
            board_by_id[int(b["id"])] = b
        except Exception:
            continue

    calls, kinds, items_logged = _build_calls(ops, board_by_id)

    # ── THE POLICY'S VETO, APPLIED TO THE CALLS THAT WILL ACTUALLY RUN ──────
    #
    # `plan_turn` ran above and returned early if it wanted to ASK. Everything
    # else it decided was then dropped on the floor: the calls below were built
    # from the complete operation list, and `decision.approved_operations` was
    # never consulted. So the staged-ambiguity architecture's promise — only
    # approved commands execute — was not structurally true in the live path.
    # It held only because a hold almost always comes WITH a question, and the
    # question returns early. A no-question hold, an unsupported edge case, or
    # any future change to the clarification policy would have executed
    # everything the interpreter proposed.
    #
    # `approved_operations` itself could not close this: it filters
    # `data["_calls"]`, which the interpreter's JSON does not carry live — it
    # is present only in the fixtures that exercise the policy directly. So the
    # veto is applied HERE, against the calls as constructed, keyed on the
    # staged item ids the policy actually reasoned about.
    if _decision is not None:
        calls, kinds, items_logged, _held_names = _apply_clarification_veto(
            _decision, calls, kinds, items_logged)
        if _held_names:
            logger.info(
                "event=policy_veto held=%s %s",
                ",".join(_held_names), (data.get("say") or "")[:40])

    # ── A SPLIT CONSERVES THE TOTAL ─────────────────────────────────────────
    #
    #   You:   Can you separate the toast and cheese for me in my log.
    #   Arnie: Slice of cheese logged, 70 cal
    #   You:   And put the toast back
    #   Arnie: Toast's on the board, 80 cal
    #
    # The composite was 175. After the split it was 70, and after the repair it
    # was 150. Twenty-five calories evaporated and the user had to notice the
    # missing half themselves.
    #
    # The operation vocabulary can express this correctly — a mixed turn is
    # `[{op: update}, {op: log}]` — and the interpreter emitted only the update,
    # so one component was renamed and the other was never written. Nothing
    # downstream could tell, because a lone update that lowers a number is
    # exactly what an ordinary correction looks like.
    #
    # Prompting harder is not the fix. The structural fact is that SEPARATING an
    # entry is the one intent that cannot be satisfied by a single operation, so
    # a plan of one update is incomplete by construction. Refusing it keeps the
    # log intact — the user's total stays right and they are told why — where
    # committing it loses calories silently and asks them to audit us.
    # Checked against the INTERPRETER's plan, not the post-veto calls. Whether
    # the split was expressed completely is a fact about what was proposed; the
    # clarification veto runs in between and can hold the new component, which
    # would make a complete plan look like an incomplete one.
    _op_kinds = [k for k, _ in ops]
    if _asks_to_split(message) and "update" in _op_kinds \
            and "log" not in _op_kinds:
        logger.info("event=split_refused_incomplete %s", (message or "")[:60])
        return {"action": "ask",
                "text": ("I can split that, but I need both halves so the "
                         "total stays right — what should each part be?"),
                "points": ["both components of the split"]}

    if not calls:
        return None

    say = str(data.get("say") or "").strip()
    say = say.replace("~", "").replace("—", ",").replace("–", ",")
    note = str(data.get("note") or "").strip()[:200]
    follow_up = str(data.get("follow_up") or "").strip()
    label = (kinds[0] if all(k == kinds[0] for k in kinds) else "commit")

    # ── HAVING FOOD IS NOT EATING IT ────────────────────────────────────────
    #
    # "Got a caramel cashew Barebells bar and a Legendary Milk Chocolate Sweet
    # Roll" wrote two entries and 400 calories against a day in which nothing
    # had been eaten. The gate that let it through reads `_CONSUMED_RE`, which
    # bundles "ate" with "bought" — right for deciding whether the logger looks
    # at the message, wrong for deciding whether to write.
    #
    # This is the one question of the four the directive names that the user
    # alone can answer, and it passes every legality test: it names one
    # unresolved field, the field decides whether the food is on the day at all,
    # a yes or no settles it, and the answer changes the outcome.
    #
    # QUICK COMMITS AND SAYS SO. Its whole contract is low friction with the
    # assumption stated, and an unwanted entry there is one tap from removal.
    if (label == "log" and prior is None and _mode(user) != "quick"
            and consumption_state(message,
                                  thread_active=thread_active) == STATE_ACQUIRED):
        _items_a = [it for it in items_logged if (it.get("food") or "").strip()]
        if _items_a:
            # `kind="confirm"` reuses the deterministic yes-replay: a yes logs
            # THESE items through the same builder, with no second parse.
            return {"action": "ask", "kind": "confirm",
                    "text": acquisition_question(_items_a),
                    "items": _items_a,
                    "tool_calls": calls, "say": say[:400],
                    "note": note, "follow_up": follow_up}

    # THE WHOLE-PARSE CONFIRM IS GONE (Danny 2026-07-26: "remove the strict
    # confirm line, it's killing the interaction, Arnie should just clarify
    # based on our plans instead").
    #
    # It was a second question layer sitting on top of a clarification policy
    # that had already decided. `plan_turn` runs above and asks when an
    # ambiguity is material — that is the whole staged-ambiguity architecture,
    # and it reasons about calorie impact per item. The confirm reasoned about
    # nothing: it fired on any system-estimated amount, which is most portions,
    # so strict paid a round trip on "I had 2 chicken thighs" to be told what
    # it had just been told. "Does that all look right?" is not a clarification,
    # it is an interruption wearing one.
    #
    # What replaces it is what was already underneath it: the policy asks when
    # a doubt is worth a turn, the assumption disclosure says what we picked
    # when it is not, and the committed card stays one tap from repair.
    return {"action": label, "tool_calls": calls, "kinds": kinds,
            "say": say[:400], "note": note, "follow_up": follow_up,
            # WHAT ELSE THE MESSAGE WAS ABOUT. Reported by the same pass that
            # read the food, so a mixed turn costs no extra model call — and
            # the response layer gets it as an obligation rather than as
            # unstructured background it is free to ignore.
            "context": _context_from(data)}
