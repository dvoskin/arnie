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
        return ("non_english" if any(ord(c) > 0x2FF for c in t)
                else "no_food_shape")
    return ""


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
    return bool(_CONSUMED_RE.search(t) or _MEAL_RE.search(t)
                or _CORRECTION_RE.search(t) or _PORTION_SHAPE_RE.search(t))


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
    'unclear -> {"action":"ask","points":[{"label":"Chicken","qs":["grilled, '
    'baked, or fried?","skin on or off?","rough amount - oz or one breast?"]},'
    '{"label":"Potato","qs":["baked, mashed, or fries?","any butter, cheese, '
    'or sour cream?"]}],"ready":["Bagel","Greek yogurt"]}\n'
    '3. Consumed food with enough detail -> {"action":"log","items":[{"food":'
    '"Caesar salad","amount":2,"unit":"handfuls","calories":180,"protein":4,'
    '"carbs":8,"fats":15,"meal":"dinner"}],"say":"Pizza and the Caesar logged, {batch_cal} cal and '
    '{batch_protein}g protein for the pair. You are at {day_cal} with {cal_left} left."}\n'
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
    "- CORRECTION OPERATOR discipline: 'two MORE tacos' is a NEW log (an "
    "addition), 'actually only one' REPLACES the amount, 'they were chicken "
    "not beef' keeps the amount and re-estimates macros for the new identity, "
    "'that was yesterday' is an update carrying date. Never collapse an "
    "addition into a replace or a replace into an addition.\n"
    "- AMBIGUITIES you chose to estimate through: when you log despite a "
    'borderline unknown, report it as "ambiguities":[{"item":"Chicken",'
    '"field":"quantity","impact_cal":250}] alongside the items (fields: '
    "quantity, identity, brand, prep, consumed). The system owns the final "
    "ask decision - report honestly, never round your doubt away.\n"
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
    "~{thresh} cal of possible swing as your calibration for 'worth asking', "
    "never as the framing of the question itself - ask like a human ('how much "
    "of the bag?'), not like a calorie auditor. Within a dish, ask about what "
    "moves the needle - the chicken, dressing, or cheese on a salad - never "
    "the trivial base (nobody clarifies lettuce).\n"
    "Under {thresh} cal of swing: do NOT ask — estimate HIGH at venue-real "
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
    if b in ("stated", "regular"):
        return True
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
    """The whole meal as we read it, then the one thing we need.

    Items the user stated are shown as they said them. The item we are asking
    about is shown in THEIR words too — "one scoop of peanut butter", never
    "one tablespoon of peanut butter", because the tablespoon is the thing in
    question and printing it as settled is what made the assumption invisible.
    """
    from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                    FoodResponsePlan, fallback)

    held = {question.staged_item_id}
    resolved, pending = [], []
    for item in (decision.staged_items or ()):
        summary = FoodItemSummary(
            name=item.original_text,
            portion=_spoken_portion(item, user_message),
            estimated=not item.quantity.is_stated,
            staged_item_id=item.staged_item_id,
            branded=(item.food_class.value == "branded"))
        (pending if item.staged_item_id in held else resolved).append(summary)

    return fallback(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=tuple(resolved), pending_items=tuple(pending),
        clarification_question=question.prompt,
        unresolved_item=(pending[0] if pending else None),
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


def _lc(name: str) -> str:
    """Sentence-case a food name for mid-sentence use: lowercase unless it
    reads branded (an uppercase beyond the first letter, or a digit)."""
    n = (name or "").strip()
    if any(c.isupper() for c in n[1:]) or any(c.isdigit() for c in n):
        return n
    return n.lower()


def clarify_text_from_points(points: list, ready: list | None = None, *,
                             user_message: str = "") -> str:
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
        return ""

    resolved = tuple(FoodItemSummary(name=str(r).strip())
                     for r in (ready or ()) if str(r).strip())[:4]
    pending = tuple(FoodItemSummary(name=label) for label, _ in asks if label)
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
    question = " ".join(q[:1].upper() + q[1:] for q in asks[0][1])

    return fallback(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=resolved, pending_items=pending,
        unresolved_item=(pending[0] if pending else None),
        clarification_question=question,
        requires_answer=True, user_message=user_message))


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
    ready_names = [_lc(str(r)) for r in (ready or []) if str(r).strip()][:4]
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


def _update_call(up: dict, board_by_id: dict) -> Optional[dict]:
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
    for k in ("calories", "protein", "carbs", "fats"):
        v = up.get(k)
        if isinstance(v, (int, float)):
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
        lines = []
        for b in board[-8:]:
            try:
                lines.append(f"#{b['id']} {b['food']}, {b.get('qty') or '?'}, "
                             f"{int(b.get('cal') or 0)} cal")
            except Exception:
                continue
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
        sys = (_SYSTEM.replace("{thresh}", str(_THRESH[mode]))
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
        if _shadow_parse is not None:
            _log_fast_path_shadow(_shadow_parse, data)
    if not isinstance(data, dict):
        return None
    action = data.get("action")

    if action == "ask" and not prior:
        text = clarify_text_from_points(data.get("points") or [],
                                        data.get("ready"),
                                        user_message=message)
        return {"action": "ask", "text": text} if text else None

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
            return {"action": "ask",
                    "text": clarify_text_from_points(
                        data["points"], data.get("ready"),
                        user_message=message),
                    "points": data["points"]}
        return None

    ops = _normalize_ops(data)
    if not ops:
        return None

    # Consumption-evidence invariant (fix #3): drop any log op the message
    # cannot support — an interrogative or evidence-free cold message never
    # yields a write, whatever action the model chose. Updates and deletes
    # are board-anchored corrections; they stand on their own intent.
    if any(k == "log" for k, _ in ops) and not consumption_evidence(
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
                _decision = plan_turn(
                    data, turn_id=(_pipe_turn() or ""), message=message,
                    mode=mode, preferences=_prefs_for(user))
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
            _text = clarify_text(_decision, _q, user_message=message)
            return {"action": "ask", "text": _text,
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
                _txt = clarify_text_from_points(_pts,
                                                user_message=message)
                if _txt:
                    return {"action": "ask", "text": _txt, "points": _pts}

    board_by_id = {}
    for b in (board or []):
        try:
            board_by_id[int(b["id"])] = b
        except Exception:
            continue

    calls, kinds, items_logged = [], [], []
    for kind, o in ops:
        call = (_log_call(o) if kind == "log"
                else _update_call(o, board_by_id) if kind == "update"
                else _delete_call(o, board_by_id))
        if call is None:
            continue
        calls.append(call)
        kinds.append(kind)
        if kind == "log":
            items_logged.append(o)

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
            "say": say[:400], "note": note, "follow_up": follow_up}
