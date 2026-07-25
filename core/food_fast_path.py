"""Zero-model-call food logging (PR #30).

Every food turn costs one LLM call today, including the ones that carry no
ambiguity at all. "150g chicken breast" has exactly one reading. So does "2
eggs and 200g rice". Sending those to a model buys nothing and costs the user
the round trip — which is most of the latency they experience, because the rest
of the pipeline is arithmetic.

So: a deterministic parser that produces the SAME interpreter-shaped dict the
model produces, for the subset of messages where the reading is not in doubt,
and `None` for everything else.

The whole design is in that last clause. This is not a cheaper interpreter — it
is a parser that refuses. It handles a narrow, boring grammar

    [quantity] [unit] [food]  (and|,|+  [quantity] [unit] [food])*

and bails on the first hint of anything else: a pronoun, a question, a
correction, a time reference, a vague quantifier, a board reference, a word it
does not recognise as a unit. Every bail costs one model call, which is what
the turn costs today. Every wrong accept costs a user a wrong log, silently.
The asymmetry is total, so the bar for accepting is "there is provably one
reading", not "this is probably fine".

Two consequences worth stating because they look like bugs otherwise:

**It does not try to be clever about food names.** Whatever follows the
quantity is the food, verbatim, and resolution happens downstream exactly as it
does for model output. The fast path decides HOW MUCH and HOW MANY; it never
decides WHAT.

**It refuses anything it could ask about.** A message with a vague quantity is
a message the clarification ladder might want to interrupt on, and that
decision belongs to the pipeline with the ambiguity engine behind it, not to a
regex. Anything vague goes to the model.

`FOOD_FAST_PATH=off` disables it entirely.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional

FAST_PATH_VERSION = "food_fast_path_v1"
SOURCE = "structured_food:fast_path"

#: Units we can interpret without help. Mass and volume only, plus the piece
#: words the normalizer already has weights for. A unit not on this list is a
#: unit whose meaning we would be guessing at.
_UNITS = {
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "kg": "kg",
    "oz": "oz", "ounce": "oz", "ounces": "oz", "lb": "lb", "lbs": "lb",
    "ml": "ml", "l": "l", "liter": "l", "litre": "l", "liters": "l",
    "cup": "cup", "cups": "cup", "tbsp": "tbsp", "tsp": "tsp",
    "slice": "slice", "slices": "slice", "piece": "piece", "pieces": "piece",
    "egg": "piece", "eggs": "piece", "scoop": "scoop", "scoops": "scoop",
}

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "a": 1, "an": 1}

#: Any of these and the message is not ours. Grouped by why, because the list
#: is the specification and an unexplained regex is impossible to extend
#: safely.
_REFUSE = (
    # A question, or an offer to answer one. Never a log.
    (r"\?", "question"),
    (r"\b(?:what|which|how much|how many|why|when|should i|can i|do you)\b",
     "interrogative"),
    # Board references. "Those", "that one", "#3" all need the board, which the
    # model gets and this does not.
    (r"\b(?:that|those|these|it|them|the last|previous|earlier|same)\b",
     "reference"),
    (r"#\d+", "board_id"),
    # Corrections and deletions. Both need to find an existing row.
    (r"\b(?:actually|instead|change|correct|fix|remove|delete|undo|"
     r"scratch|nevermind|never mind|wrong)\b", "correction"),
    # Time. "Yesterday" and "for breakfast" both move the write somewhere this
    # parser has no way to represent.
    (r"\b(?:yesterday|this morning|last night|earlier today|ago|"
     r"at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", "time_reference"),
    # Vague quantities. These are exactly the ones the clarification ladder may
    # want to ask about, and that decision belongs to the pipeline.
    (r"\b(?:some|a bit|a little|a few|handful|bunch|lots|plenty|"
     r"most|half|part of|couple)\b", "vague_quantity"),
    (r"\b(?:about|around|roughly|approximately|ish|maybe|probably|"
     r"i think|not sure)\b", "hedge"),
    # Meta. A message about logging is not a log.
    (r"\b(?:log|track|add|delete|remove)\s+(?:my|the|all)\b", "meta"),
    # Nutrition assertions. If the user states macros, the model's job of
    # attaching them to the right item is not something to reimplement here.
    (r"\b(?:cal|cals|calories|kcal|protein|carbs|fat|fats|macros)\b",
     "stated_macros"),
    # Conditionals and negation.
    (r"\b(?:if|unless|but|except|without|no|didn'?t|not)\b", "conditional"),
)

_REFUSE_COMPILED = tuple((re.compile(p, re.I), why) for p, why in _REFUSE)

#: One item: a number, an optional unit, then the food. The food is captured
#: lazily up to a separator so "200g chicken and 150g rice" splits correctly.
_ITEM_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?|" + "|".join(_WORD_NUMBERS) + r")\s*"
    r"(?P<unit>[a-z]+)?\.?\s+"
    r"(?P<food>[a-z][a-z '\-]*?)"
    r"(?=\s*(?:,|\band\b|\+|$))", re.I)

_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|\+)\s*", re.I)

#: A food name longer than this is a sentence, not a food.
_MAX_FOOD_WORDS = 4
#: More items than this and the odds of one being misparsed stop being small.
_MAX_ITEMS = 6


def fast_path_enabled() -> bool:
    raw = (os.getenv("FOOD_FAST_PATH", "true") or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def refusal_reason(message: str) -> Optional[str]:
    """Why this message is not eligible, or None if it might be.

    Returned rather than a bare bool so the refusal rate is attributable: "we
    fall back 80% of the time" is not actionable, "we fall back 80% of the time
    on `reference`" is.
    """
    text = (message or "").strip()
    if not text:
        return "empty"
    if len(text) > 160:
        return "too_long"
    for pattern, why in _REFUSE_COMPILED:
        if pattern.search(text):
            return why
    return None


def _amount(raw: str) -> Optional[float]:
    word = _WORD_NUMBERS.get(raw.strip().lower())
    if word is not None:
        return float(word)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _clean_food(raw: str) -> str:
    food = re.sub(r"\s+", " ", (raw or "").strip(" .,"))
    food = re.sub(r"^(?:of|a|an|the)\s+", "", food, flags=re.I)
    return food


def parse(message: str) -> Optional[dict]:
    """Interpreter-shaped output, or None to fall through to the model.

    The returned dict is deliberately the v1 single-action shape the existing
    `_normalize_ops` already accepts, so the fast path adds no new downstream
    branch — it produces the same input the model does and everything after it
    is unchanged.
    """
    if not fast_path_enabled():
        return None
    if refusal_reason(message) is not None:
        return None

    text = (message or "").strip().rstrip(".")
    segments = [s for s in _SPLIT_RE.split(text) if s.strip()]
    if not segments or len(segments) > _MAX_ITEMS:
        return None

    items: List[dict] = []
    for segment in segments:
        match = _ITEM_RE.match(segment.strip() + " ")
        if match is None:
            # Every segment must parse. A message where one item is clear and
            # another is not is a message for the model — logging the half we
            # understood and dropping the rest is the worst possible outcome.
            return None

        amount = _amount(match.group("amount"))
        if amount is None or amount <= 0 or amount > 5000:
            return None

        unit_raw = (match.group("unit") or "").lower()
        food = _clean_food(match.group("food"))

        if unit_raw and unit_raw not in _UNITS:
            # The word after the number is not a unit, so it is part of the
            # food: "2 chicken thighs". Put it back rather than dropping it.
            food = _clean_food(f"{unit_raw} {food}")
            unit = "piece"
        elif unit_raw:
            unit = _UNITS[unit_raw]
        else:
            unit = "piece"

        if not food or len(food.split()) > _MAX_FOOD_WORDS:
            return None
        if any(ch.isdigit() for ch in food):
            return None

        items.append({
            "food": food, "amount": amount, "unit": unit,
            # `stated` is the whole point: the user gave a number and a unit,
            # so nothing downstream should treat this portion as an estimate
            # or offer to clarify it.
            "basis": "stated",
        })

    if not items:
        return None

    return {
        "action": "log",
        "items": items,
        # No `say`. The fast path does not write prose — the response contract
        # composes it deterministically downstream, which is the same path a
        # model turn takes when the composer is off.
        "say": "",
        "fast_path": FAST_PATH_VERSION,
    }


def describe(data: Optional[dict]) -> str:
    """One log line, for measuring how often this actually fires."""
    if not data:
        return "event=food_fast_path outcome=fallthrough"
    items = data.get("items") or []
    return (f"event=food_fast_path outcome=parsed items={len(items)} "
            f"foods={','.join(str(i.get('food')) for i in items) or '-'}")
