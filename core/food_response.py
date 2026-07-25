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

    def describe(self) -> str:
        if self.portion:
            return f"{self.portion} {self.name}".strip()
        return self.name


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
    r"updating your log|calculating|let me log|i'?ll log|"
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
    if not plan.facts_visible_in_card:
        return False
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        if not _NUTRIENT_NUMBER_RE.search(sentence):
            continue
        if _RECOMMENDATION_RE.search(sentence):
            continue
        return True
    return False


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

    approved = plan.approved_names
    if approved:
        for quoted in re.findall(r"\b([a-z]{4,}(?:\s+[a-z]{3,}){0,2})\b",
                                 lowered):
            pass   # names are checked positively below, not by extraction

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
    names = [n for n in names if n][:limit]
    if not names:
        return "that"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def fallback(plan: FoodResponsePlan) -> str:
    """Correct without sounding procedural. Reached when generation fails
    validation twice, or when no composer is available."""
    intent = plan.intent

    if intent is FoodResponseIntent.REVIEW:
        return f"{format_items(plan.resolved_items)}\n\nDoes that look right?" \
            if len(plan.resolved_items) > 2 else \
            f"I've got {_join([i.describe() for i in plan.resolved_items])}. " \
            f"Does that look right?"

    if intent is FoodResponseIntent.CLARIFY:
        question = plan.clarification_question or "Which one was it?"
        if plan.resolved_items:
            return (f"I've got {_join([i.name for i in plan.resolved_items])}. "
                    f"{question}")
        return question

    if intent is FoodResponseIntent.CONFIRM_ANSWER:
        return f"Got it, {_join([i.name for i in plan.resolved_items])}."

    if intent is FoodResponseIntent.COMMIT:
        return "" if plan.allow_no_text else "Got it."

    if intent is FoodResponseIntent.PARTIAL_COMMIT:
        question = plan.clarification_question or ""
        held = plan.unresolved_item.name if plan.unresolved_item else "one item"
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


def format_items(items) -> str:
    """One food per line, quantity on the same line. Used when prose would be
    hard to scan — not as the default shape."""
    lines = ["I've got:"]
    for item in items[:8]:
        lines.append(item.describe())
    return "\n".join(lines)


# ── composition ───────────────────────────────────────────────────────────────
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
