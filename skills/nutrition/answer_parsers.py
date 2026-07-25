"""Narrow answer parsers (build order 9, and 21's clarification commands).

A clarification answer must not go through the full food interpreter. We asked
"which Fairlife bottle, and did you drink the whole thing?" — an answer of
"Elite, about half" is two field values, not a new meal. Sending it to the
interpreter is how a clarification becomes a second entry.

So each question declares a ResponseSchema, and each schema has a parser that
knows exactly which fields it is filling and which candidates are on offer.
The broad interpreter is the fallback, reached only when the answer does not
fit the shape we asked for.

Every parser returns a confidence, and a parse it is not confident about
returns nothing rather than a guess. Leaving a question pending is recoverable;
filling a field with the wrong value is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from skills.nutrition.clarify_policy import ClarificationQuestion, ResponseSchema


class ClarificationCommand(str, Enum):
    """Deterministic commands a user can give instead of an answer. These are
    not interpretations — "skip it" means skip it."""
    SKIP_ITEM = "skip_item"
    CANCEL_MEAL = "cancel_meal"
    ESTIMATE = "estimate"
    COMMIT_READY = "commit_ready"
    RESTART = "restart"


@dataclass(frozen=True)
class ClarificationAnswer:
    values: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    command: Optional[ClarificationCommand] = None
    unparsed: bool = False
    matched_candidate_id: Optional[str] = None

    @property
    def resolves_anything(self) -> bool:
        return bool(self.values) or self.command is not None


UNPARSED = ClarificationAnswer(unparsed=True)

#: Below this we do not apply the answer. Pending is recoverable; a wrong
#: value written to a committed row is not.
MIN_CONFIDENCE = 0.55


# ── commands (build order 21) ─────────────────────────────────────────────────
_COMMANDS = (
    (ClarificationCommand.CANCEL_MEAL,
     r"\b(?:cancel(?:\s+(?:the\s+)?(?:meal|all|everything))?|"
     r"forget\s+(?:the\s+)?(?:whole\s+)?(?:thing|meal)|"
     r"don'?t\s+log\s+(?:any\s+of\s+)?(?:it|that|this))\b"),
    (ClarificationCommand.SKIP_ITEM,
     r"\b(?:skip\s+(?:it|that|this|the\s+\w+)|never\s?mind|"
     r"don'?t\s+log\s+the\s+\w+|drop\s+(?:it|that|the\s+\w+)|"
     r"leave\s+(?:it|that)\s+out)\b"),
    (ClarificationCommand.ESTIMATE,
     r"\b(?:just\s+)?(?:estimate(?:\s+it)?|guess(?:\s+it)?|"
     r"(?:your|a)\s+best\s+guess|approximate\s+it|"
     r"(?:i\s+)?don'?t\s+know|dunno|no\s+idea|not\s+sure|unsure|"
     r"can'?t\s+remember|who\s+knows)\b"),
    (ClarificationCommand.COMMIT_READY,
     r"\b(?:log\s+the\s+rest|commit\s+(?:the\s+)?(?:rest|others)|"
     r"just\s+log\s+the\s+rest)\b"),
    (ClarificationCommand.RESTART,
     r"\b(?:start\s+over|restart|let\s+me\s+redo\s+(?:it|that))\b"),
)


def parse_command(text: str) -> Optional[ClarificationCommand]:
    """A command is checked BEFORE any schema parser: "skip it" is not a
    product name, however hard a fuzzy matcher tries."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for command, pattern in _COMMANDS:
        if re.search(pattern, t, re.I):
            return command
    return None


# ── fractions and quantities ──────────────────────────────────────────────────
_FRACTION_WORDS = {
    r"\b(?:the\s+)?whole(?:\s+(?:thing|bottle|bar|pack|can))?\b": 1.0,
    r"\ball\s+of\s+it\b": 1.0,
    r"\b(?:a\s+)?half\b": 0.5, r"\bhalf\s+of\s+it\b": 0.5, r"\b1/2\b": 0.5,
    r"\b(?:a\s+)?(?:quarter|fourth)\b": 0.25, r"\b1/4\b": 0.25,
    r"\bthree\s+quarters\b": 0.75, r"\b3/4\b": 0.75,
    r"\b(?:a\s+)?third\b": 1 / 3, r"\b1/3\b": 1 / 3,
    r"\btwo\s+thirds\b": 2 / 3, r"\b2/3\b": 2 / 3,
    r"\bmost\s+of\s+it\b": 0.8,
    r"\b(?:a\s+)?(?:couple\s+)?(?:sips?|bites?)\b": 0.15,
}

_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(g|grams?|oz|ounces?|ml|l|liters?|litres?|cups?|"
    r"tbsp|tsp|slices?|pieces?|servings?|bottles?|cans?|bars?)\b", re.I)


def parse_fraction(text: str) -> Optional[float]:
    t = (text or "").strip().lower()
    if not t:
        return None
    m = _PERCENT_RE.search(t)
    if m:
        try:
            pct = float(m.group(1))
            if 0 < pct <= 100:
                return round(pct / 100.0, 3)
        except ValueError:
            pass
    for pattern, value in _FRACTION_WORDS.items():
        if re.search(pattern, t, re.I):
            return round(value, 3)
    return None


def parse_quantity_answer(text: str, question=None) -> ClarificationAnswer:
    """A quantity answer is either an amount with a unit, or a fraction of the
    thing we asked about. Anything else is not a quantity."""
    command = parse_command(text)
    if command is not None:
        return ClarificationAnswer(command=command, confidence=1.0)

    m = _AMOUNT_RE.search(text or "")
    if m:
        return ClarificationAnswer(
            values={"stated_amount": float(m.group(1)),
                    "stated_unit": m.group(2).lower().rstrip(".")},
            confidence=0.95)
    fraction = parse_fraction(text)
    if fraction is not None:
        return ClarificationAnswer(values={"consumed_fraction": fraction},
                                   confidence=0.9)
    return UNPARSED


# ── product selection ─────────────────────────────────────────────────────────
_STOPWORDS = {"the", "a", "an", "one", "it", "was", "i", "had", "it's", "its",
              "that", "this", "of", "my", "yeah", "yes"}

#: Answers that sound like a selection but identify nothing. "The normal one"
#: is the case the directive names: it must stay pending, not resolve to
#: whatever ranked first.
_VAGUE_SELECTIONS = re.compile(
    r"^\s*(?:the\s+)?(?:normal|regular|usual|standard|basic|original|"
    r"same|default)\s*(?:one|kind|size)?\s*$", re.I)


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOPWORDS}


def parse_product_selection(text: str,
                            question: Optional[ClarificationQuestion] = None,
                            options=None) -> ClarificationAnswer:
    """Match the answer against the OPTIONS WE OFFERED, never against the food
    universe. "Elite" is unambiguous in a two-option question and meaningless
    outside one."""
    command = parse_command(text)
    if command is not None:
        return ClarificationAnswer(command=command, confidence=1.0)

    options = tuple(options if options is not None
                    else (question.options if question else ()))
    if not options:
        return UNPARSED
    if _VAGUE_SELECTIONS.match((text or "").strip()):
        # Deliberately unresolved: "the normal one" does not name a product,
        # and guessing here writes the wrong bottle to the ledger.
        return UNPARSED

    answer_tokens = _tokens(text)
    if not answer_tokens:
        return UNPARSED

    scored = []
    for opt in options:
        opt_tokens = _tokens(opt.label)
        if not opt_tokens:
            continue
        overlap = len(answer_tokens & opt_tokens)
        scored.append((overlap / max(1, len(opt_tokens)), overlap, opt))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    if not scored or scored[0][1] == 0:
        return UNPARSED
    # A tie between two offered options is not an answer.
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return UNPARSED

    best = scored[0][2]
    fields = tuple(question.requested_fields) if question else ()
    values = {}
    if best.value is not None and len(fields) == 1:
        values[fields[0]] = best.value
    elif isinstance(best.value, dict):
        values.update(best.value)
    elif fields:
        values[fields[0]] = best.label
    return ClarificationAnswer(values=values,
                               confidence=round(0.6 + 0.35 * scored[0][0], 3),
                               matched_candidate_id=best.candidate_id)


def parse_product_and_fraction(text: str,
                               question: Optional[ClarificationQuestion] = None,
                               options=None) -> ClarificationAnswer:
    """"Elite, about half" → product line, package size AND consumed fraction,
    deterministically. One sentence, three fields, no interpreter."""
    command = parse_command(text)
    if command is not None:
        return ClarificationAnswer(command=command, confidence=1.0)

    product = parse_product_selection(text, question, options)
    fraction = parse_fraction(text)
    amount = _AMOUNT_RE.search(text or "")

    values = dict(product.values) if not product.unparsed else {}
    if fraction is not None:
        values["consumed_fraction"] = fraction
    elif amount:
        values["stated_amount"] = float(amount.group(1))
        values["stated_unit"] = amount.group(2).lower()
    if not values:
        return UNPARSED

    # Confident only where both halves landed; a product with no portion is a
    # partial answer, which is progress but not completion.
    confidence = product.confidence if not product.unparsed else 0.0
    if fraction is not None or amount:
        confidence = max(confidence, 0.9) if values.get("consumed_fraction") \
            or values.get("stated_amount") else confidence
    if not product.unparsed and (fraction is not None or amount):
        confidence = 0.96
    return ClarificationAnswer(
        values=values, confidence=round(confidence, 3),
        matched_candidate_id=product.matched_candidate_id)


_YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|correct|right|sure|ok(?:ay)?|"
                  r"that'?s it|exactly|mhm|👍)\b", re.I)
_NO = re.compile(r"^\s*(?:no|nope|nah|negative|not quite|wrong)\b", re.I)


def parse_yes_no(text: str,
                 question: Optional[ClarificationQuestion] = None,
                 options=None) -> ClarificationAnswer:
    command = parse_command(text)
    if command is not None:
        return ClarificationAnswer(command=command, confidence=1.0)
    t = (text or "").strip()
    fields = (question.requested_fields if question else ("confirmed",))
    key = fields[0] if fields else "confirmed"
    if _YES.match(t):
        return ClarificationAnswer(values={key: True}, confidence=0.97)
    if _NO.match(t):
        return ClarificationAnswer(values={key: False}, confidence=0.97)
    return UNPARSED


def parse_nutrient_values(text: str,
                          question: Optional[ClarificationQuestion] = None,
                          options=None) -> ClarificationAnswer:
    """Delegates to the entity-bound label parser, which already owns "unknown
    is not zero" and the bare-number ordering rule."""
    from core.pending_clarification import (answer_is_refusal,
                                            parse_nutrient_answer)
    if answer_is_refusal(text):
        return ClarificationAnswer(command=ClarificationCommand.ESTIMATE,
                                   confidence=1.0)
    fields = tuple(question.requested_fields) if question else ()
    values = parse_nutrient_answer(text, fields)
    if not values:
        return UNPARSED
    return ClarificationAnswer(values=values, confidence=0.95)


def parse_serving_basis(text: str,
                        question: Optional[ClarificationQuestion] = None,
                        options=None) -> ClarificationAnswer:
    command = parse_command(text)
    if command is not None:
        return ClarificationAnswer(command=command, confidence=1.0)
    t = (text or "").lower()
    if re.search(r"\bper\s+serving\b|\bone\s+serving\b|\ba\s+serving\b", t):
        return ClarificationAnswer(values={"serving_basis": "per_serving"},
                                   confidence=0.93)
    if re.search(r"\bwhole\b|\bentire\b|\bpackage\b|\bcontainer\b|\bpack\b",
                 t):
        return ClarificationAnswer(values={"serving_basis": "per_package"},
                                   confidence=0.9)
    if re.search(r"\bper\s+100\s*g\b|\b100\s*g\b", t):
        return ClarificationAnswer(values={"serving_basis": "per_100g"},
                                   confidence=0.93)
    return UNPARSED


PARSERS = {
    ResponseSchema.PRODUCT_SELECTION: parse_product_selection,
    ResponseSchema.PRODUCT_AND_FRACTION: parse_product_and_fraction,
    ResponseSchema.QUANTITY: parse_quantity_answer,
    ResponseSchema.SERVING_BASIS: parse_serving_basis,
    ResponseSchema.NUTRIENT_VALUES: parse_nutrient_values,
    ResponseSchema.YES_NO: parse_yes_no,
}


def parse_answer(text: str,
                 question: ClarificationQuestion) -> ClarificationAnswer:
    """Parse against the shape we asked for. An answer that does not fit is
    returned UNPARSED so the caller can fall back to the interpreter — with
    the question still bound to its item."""
    parser = PARSERS.get(question.response_schema)
    if parser is None:
        return UNPARSED
    try:
        answer = parser(text, question)
    except Exception:
        return UNPARSED
    if answer.command is not None:
        return answer
    if answer.unparsed or answer.confidence < MIN_CONFIDENCE:
        return UNPARSED
    return answer
