"""The food response contract (directive 2026-07-25).

One place decides WHAT a food turn is allowed to say, and one place checks that
what came back obeys it. Before this, confirmation copy lived in food_turn.py,
transaction narration lived in conversation.py, failure prose lived in
families.py and coaching lived in the model — so the user heard four systems
taking turns.

The pipeline:

    structured food state
      → deterministic intent      (what KIND of thing is being said)
      → deterministic plan        (which facts are approved for expression)
      → constrained generation    (how to say it, in Arnie's voice)
      → validation                (did it obey the plan?)
      → deterministic fallback    (when it didn't)

The split that matters: the model never decides whether a clarification is
needed, whether a meal committed, which item is pending, or what the numbers
are. Those come from structured state. The model decides only how to say the
approved thing naturally.

Two rules do most of the work:

**The card owns the facts.** After a committed meal card renders, reciting its
contents is not confirmation, it is duplication. A number may still appear when
it serves a recommendation — "I'd aim for 30-40g at lunch" is useful, "130
calories and 3g protein, you have 1,990 remaining" is the card read aloud.

**A question needs a purpose.** Ending every commit with a question is not
engagement, it is a system asking to be talked to. Momentum comes from
relevance — an observation, an assumption worth correcting, a next step — and a
question is one option among those, not the default.

No database writes and no nutrition resolution live here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, FrozenSet, Mapping, Optional, Tuple

import logging

logger = logging.getLogger(__name__)

RESPONSE_CONTRACT_VERSION = "food_response_v1"


class FoodResponseIntent(str, Enum):
    REVIEW = "review"                    # confirm the parse before writing
    CLARIFY = "clarify"                  # resolve one material uncertainty
    CONFIRM_ANSWER = "confirm_answer"    # acknowledge a clarification answer
    COMMIT = "commit"                    # accompany a completed write
    PARTIAL_COMMIT = "partial_commit"    # some in, some held
    CORRECT = "correct"                  # an edit to an existing entry
    UNDO = "undo"                        # a reversal
    FAILURE = "failure"                  # could not complete, with a way out
    COACH = "coach"                      # one useful interpretation
    GENERAL_CONVERSATION = "general_conversation"


#: Amounts people say as words, with the connector each one needs. "0.5 banana"
#: is a parser's output; nobody says it aloud, and a review turn is read aloud
#: in the user's head. The connector is stored rather than derived because
#: "half a banana" and "a quarter of a banana" do not take the same one.
_SPOKEN_FRACTIONS = {
    0.5: ("half", "a"), 0.25: ("a quarter", "of a"),
    0.33: ("a third", "of a"), 0.333: ("a third", "of a"),
    0.67: ("two thirds", "of a"), 0.667: ("two thirds", "of a"),
    0.75: ("three quarters", "of a"), 0.125: ("an eighth", "of a"),
}
_SPOKEN_COUNTS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                  6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
                  11: "eleven", 12: "twelve"}

#: Units carrying no information beyond "there was a number of them". "15
#: pieces Peanut M&M's" is worse than "15 Peanut M&M's" — the unit does nothing
#: except make the sentence sound like a database row.
_EMPTY_UNITS = frozenset({"piece", "pieces", "item", "items", "unit", "units",
                          "serving", "servings", "x", "count", ""})

#: Measured units. The number attaches directly — "150g", not "150 g of".
_MASS_UNITS = {"g": "g", "gram": "g", "grams": "g", "gm": "g", "kg": "kg",
               "oz": "oz", "ounce": "oz", "ounces": "oz", "lb": "lb",
               "lbs": "lb", "ml": "ml", "l": "l"}

#: Units that follow the food rather than preceding it: "a Barebells bar", not
#: "one bar of Barebells".
_FORMAT_UNITS = {"bar": "bar", "bars": "bar", "can": "can", "cans": "can",
                 "bottle": "bottle", "bottles": "bottle",
                 "packet": "packet", "packets": "packet",
                 "pack": "pack", "packs": "pack"}

#: Everything else, spoken in full. "1 tbsp" reads as a label; "one tablespoon"
#: reads as a sentence.
_SPOKEN_UNITS = {
    "tbsp": "tablespoon", "tablespoon": "tablespoon",
    "tablespoons": "tablespoon", "tsp": "teaspoon", "teaspoon": "teaspoon",
    "teaspoons": "teaspoon", "cup": "cup", "cups": "cup", "scoop": "scoop",
    "scoops": "scoop", "slice": "slice", "slices": "slice",
    "handful": "handful", "handfuls": "handful", "bowl": "bowl",
    "bowls": "bowl", "plate": "plate", "plates": "plate", "glass": "glass",
    "glasses": "glass", "shot": "shot", "square": "square",
    "squares": "square", "wedge": "wedge", "strip": "strip",
}

_PORTION_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(.*)$")


def _plural(word: str, amount: float) -> str:
    if amount == 1 or not word:
        return word
    return word + ("es" if word.endswith(("s", "sh", "ch", "x")) else "s")


def _article(word: str) -> str:
    return "an" if (word or " ")[:1].lower() in "aeiou" else "a"


def _spoken_name(name: str, branded: bool = False) -> str:
    """Lowercase a generic food for mid-sentence use; leave a brand alone.

    "Banana" mid-sentence is a database row showing through. "Barebells" is a
    product and keeps its capital.

    `branded` is passed in rather than guessed, because guessing it from
    capitalisation gets "Barebells" wrong — one capitalised token with no
    internal capital and no digit looks exactly like "Banana". The interpreter
    already knows which one it is.
    """
    n = (name or "").strip()
    if not n or branded:
        return n
    # Brand-ish means a capital INSIDE a word, a digit, or an ampersand —
    # "M&Ms", "RXBAR", "Core Power 26g". Checking `n[1:]` for any capital made
    # every Title Case generic look branded, so "Peanut Butter" kept its
    # capitals mid-sentence and read like a database row.
    for word in n.split():
        if any(c.isupper() for c in word[1:]) or any(c.isdigit() for c in word):
            return n
    if "&" in n:
        return n
    return " ".join([n.split()[0][0].lower() + n.split()[0][1:]]
                    + [w[0].lower() + w[1:] if w[:1].isupper() else w
                       for w in n.split()[1:]])


def describe_portion(portion: str, name: str,
                     branded: bool = False) -> str:
    """The item as a person would say it.

    Every rule here fixes something visible in a shipped screenshot:

        "0.5 banana Banana"      → "half a banana"
        "15 pieces Peanut M&Ms"  → "15 Peanut M&Ms"
        "1 tbsp Peanut Butter"   → "one tablespoon of Peanut Butter"
        "1 bar Barebells"        → "a Barebells bar"

    In order: a unit that IS the food is said once, a count unit that means
    nothing is dropped, measures are spoken in full, and a container unit
    follows the food instead of preceding it.
    """
    name = (name or "").strip()
    portion = (portion or "").strip()
    if not portion:
        return _spoken_name(name, branded)
    if not name:
        return portion

    match = _PORTION_RE.match(portion)
    if match is None:
        return f"{portion} {name}".strip()

    amount = float(match.group(1))
    unit = match.group(2).strip().lower()
    spoken = _spoken_name(name, branded)

    # The unit IS the food — "0.5 banana" of "Banana" — or says nothing.
    stem = spoken.lower().rstrip("s")
    if unit in _EMPTY_UNITS or (
            unit and (unit.rstrip("s") == stem
                      or stem.endswith(" " + unit.rstrip("s")))):
        return _count_of(amount, spoken)

    if unit in _MASS_UNITS:
        return f"{_trim_amount(amount)}{_MASS_UNITS[unit]} of {spoken}"

    if unit in _FORMAT_UNITS:
        word = _FORMAT_UNITS[unit]
        if amount == 1:
            return f"{_article(spoken)} {spoken} {word}"
        return f"{_number_word(amount)} {spoken} {_plural(word, amount)}"

    measure = _SPOKEN_UNITS.get(unit, unit)
    fraction = _SPOKEN_FRACTIONS.get(round(amount, 3))
    if fraction:
        word, connector = fraction
        return f"{word} {connector} {measure} of {spoken}"
    return f"{_number_word(amount)} {_plural(measure, amount)} of {spoken}"


def _count_of(amount: float, name: str) -> str:
    """A count of the food itself, with no unit worth naming."""
    fraction = _SPOKEN_FRACTIONS.get(round(amount, 3))
    if fraction:
        word, connector = fraction
        if connector == "a":
            return f"{word} {_article(name)} {name}"
        return f"{word} of {_article(name)} {name}"
    if amount == 1:
        return f"{_article(name)} {name}"
    return f"{_number_word(amount)} {_plural_food(name, amount)}"


def _plural_food(name: str, amount: float) -> str:
    """Pluralize the head noun only: "two Peanut M&M's" already reads plural,
    "two egg" does not."""
    if amount == 1 or not name:
        return name
    if name.endswith(("s", "'s", "x", "ch", "sh")):
        return name
    return name + "s"


def _number_word(amount: float) -> str:
    if amount == int(amount):
        return _SPOKEN_COUNTS.get(int(amount)) or _trim_amount(amount)
    return _trim_amount(amount)


def _trim_amount(amount: float) -> str:
    return (str(int(amount)) if float(amount).is_integer()
            else f"{amount:g}")


@dataclass(frozen=True)
class FoodItemSummary:
    """One item, as the response layer is allowed to describe it. Deliberately
    thin: a name and a portion phrase, not a nutrient row. If the composer
    cannot see the numbers it cannot recite them."""
    name: str
    portion: str = ""
    estimated: bool = False
    entry_id: Optional[int] = None
    staged_item_id: str = ""
    #: A named product rather than a generic food. Drives capitalisation, and
    #: is data the interpreter already has rather than something to infer.
    branded: bool = False

    def describe(self) -> str:
        """The item as a person would say it.

        Was `f"{portion} {name}"`, which produced "0.5 banana Banana" the
        moment the interpreter used the food as its own unit — and "15 pieces
        Peanut M&Ms" and "1 tbsp Peanut Butter" the rest of the time. Those
        read like a form, not a sentence, which is what the whole review turn
        was accused of.
        """
        return describe_portion(self.portion, self.name,
                                branded=self.branded)


@dataclass(frozen=True)
class CoachingOpportunity:
    """A specific, non-obvious observation worth making. Generic encouragement
    is not an opportunity — it is filler that teaches the user to skip the
    text after the card."""
    kind: str                    # low_protein | pre_workout | large_meal | ...
    detail: str = ""
    suggested_angle: str = ""


@dataclass(frozen=True)
class FailureIntent:
    """A structured failure, phrased by the composer rather than by the module
    that detected it. Keeps the distinction that matters: an ambiguity the user
    can resolve is not the same conversation as an outage they cannot."""
    code: str
    user_fixable: bool
    recovery_action: str
    approved_message: str = ""
    requires_question: bool = False


@dataclass(frozen=True)
class FoodResponsePlan:
    """Everything the composer may say, and the limits it must respect."""
    intent: FoodResponseIntent

    # Facts approved for expression.
    resolved_items: Tuple[FoodItemSummary, ...] = ()
    unresolved_item: Optional[FoodItemSummary] = None
    committed_items: Tuple[FoodItemSummary, ...] = ()
    pending_items: Tuple[FoodItemSummary, ...] = ()
    assumptions: Tuple[Any, ...] = ()

    # Clarification.
    clarification_question: Optional[str] = None
    clarification_options: Tuple[str, ...] = ()
    requires_answer: bool = False

    # What the existing card already shows.
    card_will_render: bool = False
    facts_visible_in_card: FrozenSet[str] = frozenset()

    #: Foods in play this turn, for the invented-item check. A general
    #: "is this a food word" test would flag ordinary language, so the caller
    #: supplies the vocabulary.
    known_foods: Tuple[str, ...] = ()

    # Conversational context.
    user_message: str = ""
    user_emotional_context: Optional[str] = None
    previous_assistant_message: Optional[str] = None
    recent_response_openers: Tuple[str, ...] = ()

    # Coaching.
    coaching_opportunity: Optional[CoachingOpportunity] = None
    coaching_is_material: bool = False

    # Failure.
    failure: Optional[FailureIntent] = None

    # Limits.
    max_sentences: int = 2
    max_words: int = 45
    allow_question: bool = False
    allow_no_text: bool = False

    contract_version: str = RESPONSE_CONTRACT_VERSION

    @property
    def approved_names(self) -> set:
        names = set()
        for group in (self.resolved_items, self.committed_items,
                      self.pending_items):
            for item in group:
                names.add(item.name.lower())
        if self.unresolved_item is not None:
            names.add(self.unresolved_item.name.lower())
        return names


# ── intent policy (build order: deterministic, never model-chosen) ────────────
#: max_sentences, max_words, allow_question, allow_no_text
INTENT_POLICY = {
    FoodResponseIntent.REVIEW: (2, 55, True, False),
    FoodResponseIntent.CLARIFY: (2, 40, True, False),
    FoodResponseIntent.CONFIRM_ANSWER: (1, 20, False, True),
    # COMMIT allows no text at all — the card already said it happened.
    FoodResponseIntent.COMMIT: (2, 35, False, True),
    FoodResponseIntent.PARTIAL_COMMIT: (2, 45, True, False),
    FoodResponseIntent.CORRECT: (1, 25, False, False),
    FoodResponseIntent.UNDO: (1, 20, False, False),
    FoodResponseIntent.FAILURE: (2, 45, True, False),
    FoodResponseIntent.COACH: (2, 45, False, True),
    FoodResponseIntent.GENERAL_CONVERSATION: (3, 70, True, False),
}


def apply_policy(plan: FoodResponsePlan) -> FoodResponsePlan:
    """Stamp the intent's limits onto the plan.

    `requires_answer` can raise allow_question but nothing can lower it below
    what the intent permits — a plan that must be answered has to be allowed to
    ask.
    """
    sentences, words, allow_q, allow_none = INTENT_POLICY[plan.intent]
    if plan.requires_answer:
        allow_q = True
        allow_none = False
    return replace(plan, max_sentences=sentences, max_words=words,
                   allow_question=allow_q, allow_no_text=allow_none)


# ── plan builders ─────────────────────────────────────────────────────────────
def plan_review(items, *, user_message: str = "", **kw) -> FoodResponsePlan:
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.REVIEW, resolved_items=tuple(items),
        requires_answer=True, user_message=user_message, **kw))


def plan_clarify(*, question: str, resolved=(), unresolved=None, options=(),
                 user_message: str = "", **kw) -> FoodResponsePlan:
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY, resolved_items=tuple(resolved),
        unresolved_item=unresolved, clarification_question=question,
        clarification_options=tuple(options), requires_answer=True,
        user_message=user_message, **kw))


def plan_from_resolution(resolution, *, user_message: str = "",
                         card_will_render: bool = True,
                         clarification_question: Optional[str] = None,
                         coaching: Optional[CoachingOpportunity] = None,
                         **kw) -> FoodResponsePlan:
    """Build a commit-side plan from a MealResolution.

    MealResolution is the ONLY authority for what committed and what is
    pending. Nothing here re-derives that from the model's earlier prose — the
    whole reason it exists is that the interpretation and the outcome can
    differ, and the outcome is what the user is looking at.
    """
    committed = tuple(FoodItemSummary(name=c.name, portion=c.quantity_text,
                                      estimated=(c.outcome.value ==
                                                 "committed_estimated"),
                                      entry_id=c.entry_id,
                                      staged_item_id=c.staged_item_id)
                      for c in (resolution.committed or ()))
    pending = tuple(FoodItemSummary(name=p.name, portion="",
                                    staged_item_id=p.staged_item_id)
                    for p in (resolution.pending or ()))

    if pending and committed:
        intent = FoodResponseIntent.PARTIAL_COMMIT
    elif pending:
        intent = FoodResponseIntent.CLARIFY
    else:
        intent = FoodResponseIntent.COMMIT

    return apply_policy(FoodResponsePlan(
        intent=intent, committed_items=committed, pending_items=pending,
        unresolved_item=(pending[0] if pending else None),
        assumptions=tuple(resolution.assumptions or ()),
        clarification_question=clarification_question,
        requires_answer=bool(pending and clarification_question),
        card_will_render=(card_will_render and bool(committed)),
        facts_visible_in_card=(CARD_FACTS if (card_will_render and committed)
                               else frozenset()),
        user_message=user_message, coaching_opportunity=coaching,
        coaching_is_material=coaching is not None, **kw))


def plan_correct(target: str, *, user_message: str = "", **kw) -> FoodResponsePlan:
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CORRECT,
        committed_items=(FoodItemSummary(name=target),),
        card_will_render=True, facts_visible_in_card=CARD_FACTS,
        user_message=user_message, **kw))


def plan_undo(target: str, *, user_message: str = "", **kw) -> FoodResponsePlan:
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.UNDO,
        committed_items=(FoodItemSummary(name=target),),
        user_message=user_message, **kw))


def plan_failure(failure: FailureIntent, *, user_message: str = "",
                 **kw) -> FoodResponsePlan:
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.FAILURE, failure=failure,
        requires_answer=failure.requires_question, user_message=user_message,
        **kw))


def plan_confirm_answer(summary: str, *, user_message: str = "",
                        card_will_render: bool = True,
                        **kw) -> FoodResponsePlan:
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CONFIRM_ANSWER,
        resolved_items=(FoodItemSummary(name=summary),),
        card_will_render=card_will_render,
        facts_visible_in_card=(CARD_FACTS if card_will_render else frozenset()),
        user_message=user_message, **kw))


#: What the committed meal card already shows. Reciting these after it renders
#: is duplication, not confirmation.
CARD_FACTS = frozenset({"calories", "protein", "carbs", "fat", "quantities",
                        "day_totals", "remaining_targets"})

#: The subset whose presence makes a number in the text a RECITATION. A card
#: showing only item quantities does not make "about 300 calories" a duplicate.
_NUTRIENT_CARD_FACTS = frozenset({"calories", "protein", "carbs", "fat",
                                  "day_totals", "remaining_targets"})


# ── validation ────────────────────────────────────────────────────────────────
class Reason:
    OK = "ok"
    TRANSACTION_NARRATION = "transaction_narration"
    CARD_DUPLICATION = "card_duplication"
    FORBIDDEN_QUESTION = "forbidden_question"
    MISSING_QUESTION = "missing_question"
    PENDING_AS_COMMITTED = "pending_as_committed"
    INVENTED_ITEM = "invented_item"
    TOO_LONG = "too_long"
    MULTIPLE_COACHING = "multiple_coaching"
    SYSTEM_TONE = "system_tone"
    REPEATED_OPENER = "repeated_opener"
    EMPTY_NOT_ALLOWED = "empty_not_allowed"
    DASHBOARD_SYNTAX = "dashboard_syntax"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str = Reason.OK
    detail: str = ""


#: Narration of internal work. The model is already told not to do this and
#: turn_health already flags it — but the structured path used to EMIT it
#: deterministically, which is why it needs catching here too.
_TRANSACTION_RE = re.compile(
    r"\b(?:give me a (?:moment|sec(?:ond)?)|one (?:sec(?:ond)?|moment)|"
    r"hang on|hold on|logging (?:it|that|this|all|them|everything)|"
    r"processing|working on it|saving (?:that|this|it)|"
    # "let me log" is always pre-action narration. "I'll log" is only
    # narration with an immediacy marker — "Tell me the calories and I'll log
    # it as stated" is a conditional OFFER contingent on the user acting, and
    # catching it left the unsupported-food failure with no usable message.
    r"updating your log|calculating|let me log|"
    r"i'?ll log\s+(?:it|that|this|them)?\s*(?:now|right away|for you)|"
    r"successfully logged|has been logged|been (?:added|saved) to your|"
    r"your request has been|the operation was|entry has been updated)\b",
    re.I)

#: Corporate/system register. Distinct from narration: these are not about
#: internal work, they are about sounding like software.
_SYSTEM_TONE_RE = re.compile(
    r"\b(?:please confirm whether|has been (?:completed|processed)|"
    r"i have successfully|your (?:food )?entry (?:has|was)|"
    r"is there anything else|would you like (?:me to )?help|"
    r"let me know if you (?:need|have) any)\b", re.I)

#: Endings that ask for engagement rather than information.
_FILLER_QUESTION_RE = re.compile(
    r"\b(?:anything else|what(?:'s| is| are you)? (?:next|eating next)|"
    r"what (?:will|are) you (?:have|having|eating)|how are you feeling|"
    r"does that make sense|sound good\?|make sense\?)", re.I)

#: Forward-looking language. A number inside one of these is a recommendation,
#: not a recitation — "I'd aim for 30-40g at lunch" earns its number.
_RECOMMENDATION_RE = re.compile(
    r"\b(?:i'?d|aim|target|shoot for|get|keep|make|leave[s]?|room for|"
    r"next|later|tonight|lunch|dinner|breakfast|rest of|remaining for|"
    r"so you|before|after|worth)\b", re.I)

#: Numbers presented as a nutrition fact.
_NUTRIENT_NUMBER_RE = re.compile(
    r"\b\d[\d,]*\s*(?:kcal|cal(?:orie)?s?|g\b|grams?|mg)\b", re.I)

#: Day-total and remaining phrasings, where the number carries NO unit —
#: "You're at 130." reads as a running total and is exactly what the card's
#: progress row shows, but a unit-anchored pattern misses it entirely.
_DAY_TOTAL_RE = re.compile(
    r"(?:\byou'?re at\s+\d|\bat\s+\d[\d,]*\s+(?:today|so far)|"
    r"\b\d[\d,]*\s+(?:left|remaining|to go)\b)", re.I)

#: Progress rendered as arithmetic: "458 / 2165 calories", "12 / 180g".
#:
#: Stripped and rejected unconditionally, unlike the other recitation patterns,
#: because this one is not a fact repeated in the wrong place — it is a
#: DASHBOARD leaking into a sentence. It survived the recitation check by
#: carrying a recommendation ("go protein-first next"), which is exactly the
#: shape that reached production: a progress bar with advice stapled to it.
#: The card owns the numbers; the sentence says what they mean.
_SLASH_TOTAL_RE = re.compile(
    r"\b\d[\d,]*\s*/\s*\d[\d,]*\s*(?:g\b|kcal|cal(?:orie)?s?|grams?)?",
    re.I)

#: More than one recommendation in a coaching message.
_RECOMMENDATION_SPLIT_RE = re.compile(r"\b(?:i'?d|you should|try to|make sure|"
                                      r"aim to|aim for|focus on)\b", re.I)


def _sentences(text: str) -> list:
    """Sentence count that does not punish a scannable item list.

    A REVIEW listing four foods on four lines is one readable thing, not five
    sentences, and counting it as five would force the composer into prose that
    is harder to read.
    """
    body = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # A bare item line ("Rice, roughly 1 cup") is part of the list.
        if not re.search(r"[.!?]$", line) and len(line.split()) <= 8:
            continue
        body.append(line)
    joined = " ".join(body) if body else (text or "")
    return [s for s in re.split(r"(?<=[.!?])\s+", joined.strip()) if s]


def _opener(text: str) -> str:
    words = re.findall(r"[a-z']+", (text or "").lower())
    return " ".join(words[:2])


def _recites_card_facts(text: str, plan: FoodResponsePlan) -> bool:
    """A number that repeats what the card shows, without doing any work.

    Deliberately not a blanket ban on digits. The test is whether the sentence
    carrying the number is forward-looking; "I'd aim for 30-40g at lunch" is a
    recommendation, "130 calories and 3g protein" is the card read aloud.
    """
    # Only NUTRIENT facts make a number a recitation. A card showing just
    # quantities does not make "about 300 calories" a duplicate.
    if not (plan.facts_visible_in_card & _NUTRIENT_CARD_FACTS):
        return False
    return any(_is_recitation(s)
               for s in re.split(r"(?<=[.!?])\s+|\n", text or ""))


def validate(text: str, plan: FoodResponsePlan) -> ValidationResult:
    """Did the generated text obey the plan? Returns a reason code so a
    regeneration can be targeted and a fallback can be chosen."""
    raw = (text or "").strip()

    if not raw:
        if plan.allow_no_text and not plan.requires_answer:
            return ValidationResult(True)
        return ValidationResult(False, Reason.EMPTY_NOT_ALLOWED)

    if _TRANSACTION_RE.search(raw):
        return ValidationResult(False, Reason.TRANSACTION_NARRATION)
    if _SYSTEM_TONE_RE.search(raw):
        return ValidationResult(False, Reason.SYSTEM_TONE)
    # Progress as arithmetic is never acceptable copy, card or no card. "12 /
    # 180g" is a progress bar someone typed out.
    if _SLASH_TOTAL_RE.search(raw):
        return ValidationResult(False, Reason.DASHBOARD_SYNTAX)

    has_question = "?" in raw
    if has_question and not plan.allow_question:
        return ValidationResult(False, Reason.FORBIDDEN_QUESTION)
    if plan.requires_answer and not has_question:
        return ValidationResult(False, Reason.MISSING_QUESTION)
    if has_question and _FILLER_QUESTION_RE.search(raw):
        return ValidationResult(False, Reason.FORBIDDEN_QUESTION,
                                "engagement question, not an informational one")

    if _recites_card_facts(raw, plan):
        return ValidationResult(False, Reason.CARD_DUPLICATION)

    lowered = raw.lower()
    for item in plan.pending_items:
        name = item.name.lower()
        if not name or name not in lowered:
            continue
        # Naming a held item is fine — saying it is IN is not.
        if re.search(rf"{re.escape(name)}[^.?!]{{0,40}}\b(?:logged|in|added|"
                     rf"counted|committed)\b", lowered):
            return ValidationResult(False, Reason.PENDING_AS_COMMITTED,
                                    item.name)

    if plan.known_foods and mentions_unapproved_item(raw, plan,
                                                     plan.known_foods):
        return ValidationResult(False, Reason.INVENTED_ITEM)

    words = len(raw.split())
    if words > plan.max_words:
        return ValidationResult(False, Reason.TOO_LONG,
                                f"{words} words > {plan.max_words}")
    sentences = _sentences(raw)
    if len(sentences) > plan.max_sentences:
        return ValidationResult(False, Reason.TOO_LONG,
                                f"{len(sentences)} sentences > "
                                f"{plan.max_sentences}")

    if plan.intent is FoodResponseIntent.COACH:
        if len(_RECOMMENDATION_SPLIT_RE.findall(raw)) > 1:
            return ValidationResult(False, Reason.MULTIPLE_COACHING)

    opener = _opener(raw)
    if opener and opener in {_opener(o) for o in plan.recent_response_openers}:
        return ValidationResult(False, Reason.REPEATED_OPENER, opener)

    return ValidationResult(True)


def mentions_unapproved_item(text: str, plan: FoodResponsePlan,
                             known_foods) -> bool:
    """Did the text name a food that is not in the plan?

    Needs a vocabulary to check against — a general "is this a food word"
    test would flag ordinary language. Callers pass the foods in play.
    """
    lowered = (text or "").lower()
    approved = plan.approved_names
    return any(food.lower() in lowered and food.lower() not in approved
               for food in (known_foods or ()))


# ── the voice prompt ──────────────────────────────────────────────────────────
ARNIE_VOICE = """You are Arnie, the user's persistent nutrition and training coach.

Write only the conversational text appropriate to the supplied response intent.

You have structured facts. Do not add, alter, recompute, or infer nutrition
facts that are not supplied.

Sound natural, intelligent, confident and context-aware. Use concise, complete
sentences rather than robotic fragments. Contractions are normal.

Do not narrate internal operations. Never mention tools, databases, resolvers,
models, processing, saving, or logging mechanics. The write already happened —
do not describe it.

Do not repeat information marked as visible in the existing card.

Do not force a question. Ask one only when the plan allows it and the answer
has a clear purpose. Keep the conversation open through relevance and
personality rather than constant prompting.

Respond to emotional or situational context when it is present.

Do not praise routine logging. Do not use generic coaching filler.

Return only the user-facing text. Return an empty string when the plan allows
no text and nothing useful needs saying."""


_INTENT_BRIEF = {
    FoodResponseIntent.REVIEW:
        "Confirm your reading of the meal and ask one simple confirmation "
        "question. Do not coach and do not mention daily targets.",
    FoodResponseIntent.CLARIFY:
        "Acknowledge what you already understood, then ask the one supplied "
        "question. Do not repeat the whole meal.",
    FoodResponseIntent.CONFIRM_ANSWER:
        "Briefly acknowledge the resolved meaning. Do not re-review the meal "
        "and do not ask again.",
    FoodResponseIntent.COMMIT:
        "The card already confirms what was logged. Add one natural "
        "observation, or return an empty string if there is nothing useful.",
    FoodResponseIntent.PARTIAL_COMMIT:
        "Say what is in, name the one item still open, and ask only the "
        "supplied question. Never describe the open item as logged.",
    FoodResponseIntent.CORRECT:
        "One natural acknowledgement of what changed.",
    FoodResponseIntent.UNDO:
        "State briefly what was reversed.",
    FoodResponseIntent.FAILURE:
        "Explain what you could not do and give the one useful next step. "
        "Never blame the user, and never ask them to fix an outage.",
    FoodResponseIntent.COACH:
        "One useful observation. Not a summary of the card.",
    FoodResponseIntent.GENERAL_CONVERSATION:
        "Answer what they actually said.",
}


def build_prompt(plan: FoodResponsePlan) -> str:
    """The generation prompt: voice, intent brief, approved facts, limits."""
    parts = [ARNIE_VOICE, "", f"INTENT: {plan.intent.value}",
             _INTENT_BRIEF.get(plan.intent, "")]

    if plan.resolved_items:
        parts.append("UNDERSTOOD: "
                     + "; ".join(i.describe() for i in plan.resolved_items))
    if plan.committed_items:
        parts.append("LOGGED (the card shows these — do not recite them): "
                     + "; ".join(i.describe() for i in plan.committed_items))
    if plan.pending_items:
        parts.append("NOT LOGGED, still open: "
                     + "; ".join(i.name for i in plan.pending_items))
    if plan.assumptions:
        texts = [getattr(a, "user_visible_text", "") or str(a)
                 for a in plan.assumptions]
        parts.append("ASSUMPTIONS you may surface: " + "; ".join(t for t in texts if t))
    if plan.clarification_question:
        parts.append(f"ASK EXACTLY THIS (rephrasing for tone is fine): "
                     f"{plan.clarification_question}")
    if plan.clarification_options:
        parts.append("OPTIONS: " + " / ".join(plan.clarification_options))
    if plan.failure is not None:
        parts.append(f"FAILURE: {plan.failure.code} — "
                     f"{plan.failure.recovery_action}")
        parts.append("This is "
                     + ("something the user can resolve."
                        if plan.failure.user_fixable
                        else "an outage on our side. Do not ask them to fix it."))
    if plan.coaching_opportunity is not None:
        c = plan.coaching_opportunity
        parts.append(f"COACHING ANGLE ({c.kind}): {c.detail or c.suggested_angle}")
    if plan.user_emotional_context:
        parts.append(f"THEY SIGNALLED: {plan.user_emotional_context}")
    if plan.facts_visible_in_card:
        parts.append("ALREADY ON THE CARD: "
                     + ", ".join(sorted(plan.facts_visible_in_card)))
    if plan.recent_response_openers:
        parts.append("DO NOT OPEN WITH: "
                     + "; ".join(plan.recent_response_openers))

    limits = [f"at most {plan.max_sentences} sentences",
              f"at most {plan.max_words} words"]
    limits.append("you may ask one question" if plan.allow_question
                  else "no questions")
    if plan.allow_no_text:
        limits.append("an empty response is allowed")
    parts.append("LIMITS: " + "; ".join(limits))
    return "\n".join(p for p in parts if p)


# ── deterministic fallbacks ───────────────────────────────────────────────────
def _join(names, limit: int = 3) -> str:
    """Natural list, honest about overflow.

    Silently truncating is how "I've got A, B and C in" gets said about five
    committed items — a miscount the user has no way to see.
    """
    names = [n for n in names if n]
    if not names:
        return "that"
    if len(names) == 1:
        return names[0]
    if len(names) <= limit:
        return ", ".join(names[:-1]) + " and " + names[-1]
    rest = len(names) - limit
    return (", ".join(names[:limit])
            + f" and {rest} more" + ("" if rest == 1 else ""))


def _held_name(plan: "FoodResponsePlan") -> str:
    """The item a clarification is about. Prefers the explicit unresolved item,
    falls back to the first pending one — dropping to "one item" names nothing,
    which is exactly the vague question this layer exists to avoid."""
    if plan.unresolved_item is not None and plan.unresolved_item.name:
        return plan.unresolved_item.name
    if plan.pending_items and plan.pending_items[0].name:
        return plan.pending_items[0].name
    return "one item"


def fallback(plan: FoodResponsePlan) -> str:
    """Correct without sounding procedural. Reached when generation fails
    validation twice, or when no composer is available."""
    intent = plan.intent

    if intent is FoodResponseIntent.REVIEW:
        # A complete sentence, then a list only when a list earns its place.
        # "I've got:" over three bare rows read as a component spec; the point
        # of a review turn is that the user can hear it as a sentence.
        #
        # REVIEW and CLARIFY open differently ON PURPOSE. Nothing is open here,
        # so the turn is a last look before the write — "here's what I'm about
        # to log". CLARIFY is still forming an opinion, so it says it is
        # interpreting. Sharing one opener made the two turns indistinguishable
        # to a reader, which is how "does that look right?" ended up standing
        # in front of a question the user had not been shown yet.
        items = plan.resolved_items
        if _wants_a_list(items):
            return (f"{REVIEW_OPENER}\n\n"
                    f"{format_items(items)}\n\nDoes that all look right?")
        described = _join([i.describe() for i in items])
        return f"I'm reading that as {described}. Does that look right?"

    if intent is FoodResponseIntent.CLARIFY:
        # The interpretation and the question in ONE turn. Asking "does that
        # look right?" and then asking a second question afterwards spends two
        # turns on one meal and invites the user to approve an assumption they
        # were never shown.
        question = plan.clarification_question or f"Which {_held_name(plan)} was it?"
        shown = list(plan.resolved_items) + list(plan.pending_items)
        if _wants_a_list(shown):
            return (f"{CLARIFY_OPENER}\n\n"
                    f"{format_items(shown)}\n\n{question}")
        if shown:
            return (f"I'm reading that as "
                    f"{_join([i.describe() for i in shown])}. {question}")
        return question

    if intent is FoodResponseIntent.CONFIRM_ANSWER:
        return f"Got it, {_join([i.name for i in plan.resolved_items])}."

    if intent is FoodResponseIntent.COMMIT:
        return "" if plan.allow_no_text else "Got it."

    if intent is FoodResponseIntent.PARTIAL_COMMIT:
        question = plan.clarification_question or ""
        held = _held_name(plan)
        got = _join([i.name for i in plan.committed_items])
        base = f"I've got {got} in."
        return f"{base} {question}".strip() if question else \
            f"{base} Still need a detail on the {held}."

    if intent is FoodResponseIntent.CORRECT:
        return f"Updated {_join([i.name for i in plan.committed_items])}."

    if intent is FoodResponseIntent.UNDO:
        return f"Undid {_join([i.name for i in plan.committed_items])}."

    if intent is FoodResponseIntent.FAILURE:
        return (plan.failure.approved_message if plan.failure
                else "I couldn't complete that one.")

    if intent is FoodResponseIntent.COACH:
        # Silence beats generic advice.
        return ""

    return ""


#: The two review openers. Distinct because the turns are: CLARIFY is still
#: forming an opinion and is about to ask about part of it; REVIEW has nothing
#: open and is taking a last look before writing.
#:
#: Both are full sentences that introduce what follows. The banned register is
#: the heading — "Meal check", "Quick review", "Before I log this" — which
#: labels the list instead of speaking to the person reading it.
CLARIFY_OPENER = "Here's how I'm interpreting that:"
REVIEW_OPENER = "Here's what I'm about to log:"

#: Above this many foods, prose stops scanning and a list starts helping.
LIST_THRESHOLD = 3

#: A food whose description is longer than this is doing enough work on its own
#: that two of them in a sentence is already a wall.
_LONG_ITEM_CHARS = 36


def _wants_a_list(items) -> bool:
    """Whether these foods read better as a list than as a sentence.

    Not a fixed template: one or two simple foods belong in a sentence, three
    or more belong in a list, and two complicated ones belong in a list too.
    Forcing every response into the same shape is what made the review turn
    read like a form.
    """
    items = [i for i in items if i]
    if len(items) >= LIST_THRESHOLD:
        return True
    return any(len(i.describe()) > _LONG_ITEM_CHARS for i in items)


def format_items(items) -> str:
    """One food per line, as a bulleted list.

    No heading — the caller supplies the sentence that introduces it. A heading
    here ("I've got:") plus rows below is the shape that read as a component
    spec rather than a coach talking.
    """
    return "\n".join(f"• {_sentence_case(item.describe())}"
                     for item in list(items)[:8])


def _sentence_case(text: str) -> str:
    """Capitalise a bullet's first letter without touching the rest.

    `.capitalize()` would lowercase "Peanut M&Ms" to "Peanut m&ms"; the rest of
    the line has already been cased deliberately.
    """
    text = (text or "").strip()
    return text[:1].upper() + text[1:] if text else text


def strip_card_recitation(text: str, plan: FoodResponsePlan) -> str:
    """Remove sentences that only read the card back, keep the ones that work.

    The deterministic committed renderer (core.food_ledger.render_committed)
    predates the meal card and says everything: what was logged, its macros, the
    day total, what is left. On a surface where the card renders, most of that
    is the card read aloud — and on a surface where it does NOT (Telegram has no
    card frame), the same sentences are the only confirmation the user gets.

    So this strips rather than replaces, and only when a card is actually
    rendering. A sentence survives if it carries no nutrition number, or if it
    is forward-looking — "I'd aim for 30-40g at lunch" earns its digits.

    Bubbles (|||) are handled independently so a whitelisted coaching follow-up
    or a refusal notice is never collateral.
    """
    if not text or not (plan.facts_visible_in_card & _NUTRIENT_CARD_FACTS):
        return text

    kept_bubbles = []
    for bubble in text.split("|||"):
        bubble = bubble.strip()
        if not bubble:
            continue
        # A question is never recitation — it is asking for something.
        if "?" in bubble:
            kept_bubbles.append(bubble)
            continue
        kept = [s for s in re.split(r"(?<=[.!?])\s+", bubble)
                if s.strip() and not _is_recitation(s)
                and not _is_roll_call(s, plan)]
        if kept:
            kept_bubbles.append(" ".join(kept).strip())
    return "|||".join(kept_bubbles)


def _is_recitation(sentence: str) -> bool:
    """A number doing no work beyond repeating the card.

    Three shapes, because they are written differently: a nutrient with a unit
    ("3g protein"), a running total without one ("You're at 130"), and progress
    as arithmetic ("458 / 2165 calories"). The third is stripped even when it
    carries a recommendation — a recommendation does not redeem a progress bar
    rendered as text.
    """
    if _SLASH_TOTAL_RE.search(sentence):
        return True
    if not (_NUTRIENT_NUMBER_RE.search(sentence)
            or _DAY_TOTAL_RE.search(sentence)):
        return False
    return not _RECOMMENDATION_RE.search(sentence)


def _is_roll_call(sentence: str, plan: "FoodResponsePlan") -> bool:
    """A sentence that only re-lists what the card already lists.

    "Logged: Peanut M&Ms, Banana, Peanut Butter." carries no number, so the
    recitation check never saw it — and it shipped directly above a card
    showing the same three names with their macros. A receipt printed twice is
    not a receipt, it is noise between the user and the thing they wanted.
    """
    names = [i.name for i in (plan.committed_items or ()) if i.name]
    if len(names) < 1:
        return False
    text = (sentence or "").strip().rstrip(".")
    if not text:
        return False
    # Strip a leading receipt verb, then see whether what is left is only the
    # item names and separators.
    stripped = re.sub(r"^(?:logged|added|saved|got|in)\s*[:\-—]?\s*", "",
                      text, flags=re.I)
    for name in names:
        stripped = re.sub(rf"\b{re.escape(name)}\b", "", stripped,
                          flags=re.I)
    remainder = re.sub(r"[,\s;&·]+|\band\b", "", stripped, flags=re.I)
    return not remainder and stripped != text


# ── composition ───────────────────────────────────────────────────────────────
def plan_clarify_from_question(question, *, user_message: str = "",
                               **kw) -> FoodResponsePlan:
    """Build a CLARIFY plan from the policy's question, semantics and all.

    This is what lets the sentence be a sentence: without resolved_item_names
    the composer can only ask "Which yogurt?", and the acknowledgement that
    makes it feel like one conversation ("I've got the toast and fruit") is
    unavailable to it.
    """
    resolved = tuple(FoodItemSummary(name=n)
                     for n in (getattr(question, "resolved_item_names", ()) or ()))
    unresolved_name = getattr(question, "unresolved_item_name", "")
    assumption = getattr(question, "material_assumption", "")
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=resolved,
        unresolved_item=(FoodItemSummary(name=unresolved_name)
                         if unresolved_name else None),
        clarification_question=question.prompt,
        clarification_options=tuple(o.label for o in (question.options or ())),
        assumptions=((assumption,) if assumption else ()),
        requires_answer=True, user_message=user_message, **kw))


async def compose_async(plan: FoodResponsePlan, *, model: Optional[str] = None,
                        attempts: int = 2) -> tuple:
    """Generate → validate → retry → fall back, against the real model.

    Wraps compose() rather than duplicating it, so the validation rules cannot
    drift between the sync path (tests, fallback-only callers) and the live one.
    A model failure is not an error here: the deterministic fallback is always
    correct, just plainer.
    """
    from core.llm import chat

    async def _run(prompt: str) -> str:
        try:
            out = await chat([{"role": "user",
                               "content": "Write the response."}],
                             prompt, tools=False, max_tokens=200,
                             model=model or _composer_model())
            return (out or {}).get("text", "") if isinstance(out, dict) else str(out or "")
        except Exception as e:
            logger.warning(f"food composer model call failed: {e}")
            return ""

    prompt = build_prompt(plan)
    last = ValidationResult(False, Reason.EMPTY_NOT_ALLOWED)
    for _ in range(max(1, attempts)):
        text = await _run(prompt)
        last = validate(text, plan)
        if last.ok:
            return text.strip(), Reason.OK
        prompt = f"{prompt}\n\nYOUR LAST ATTEMPT FAILED: {last.reason}. Fix it."
    return fallback(plan), last.reason


def _composer_model() -> str:
    """Small and fast. The composer is phrasing an approved plan, not deciding
    anything — a large model here buys nothing and costs latency on every food
    turn."""
    import os
    return os.getenv("FOOD_COMPOSER_MODEL", "claude-haiku-4-5-20251001")


def composer_enabled() -> bool:
    """Off by default. The deterministic fallbacks are already correct and
    non-robotic; the composer buys tone, and it costs a model call on every
    food turn. Turn it on deliberately."""
    import os
    return (os.getenv("FOOD_COMPOSER", "") or "").strip().lower() in (
        "1", "true", "yes")


def compose(plan: FoodResponsePlan, generate: Optional[Callable] = None,
            *, attempts: int = 2) -> tuple:
    """Generate → validate → retry → fall back. Returns (text, reason).

    `generate` takes the prompt and returns text. Synchronous by design so this
    module stays testable without an event loop; async callers wrap it.
    """
    if generate is None:
        return fallback(plan), "no_composer"

    prompt = build_prompt(plan)
    last = ValidationResult(False, Reason.EMPTY_NOT_ALLOWED)
    for _ in range(max(1, attempts)):
        try:
            text = generate(prompt) or ""
        except Exception:
            break
        last = validate(text, plan)
        if last.ok:
            return text.strip(), Reason.OK
        prompt = f"{prompt}\n\nYOUR LAST ATTEMPT FAILED: {last.reason}. Fix it."
    return fallback(plan), last.reason
