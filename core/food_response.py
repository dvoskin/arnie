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

#: Words that HEDGE a quantity rather than measure it, with how they read in
#: front of a food. The interpreter emits them as units with an amount of 1 —
#: "some" of mustard arrives as `1 some` — and every rule below treats a unit
#: as a noun to be counted, which produced "One some of mustard" in a shipped
#: review turn.
#:
#: They are not units and they are not counts. "Some mustard" is the whole
#: phrase, and the 1 in front of it is an artefact of a field that has to hold
#: a number.
_HEDGE_UNITS = {
    "some": "some {food}",
    "little": "a little {food}",
    "bit": "a bit of {food}",
    "lots": "lots of {food}",
    "plenty": "plenty of {food}",
}

#: Size words are ADJECTIVES, not units. They modify whatever follows them and
#: are never the head of the phrase.
#:
#: A portion string arrives as free text, and the old code took everything after
#: the number as one opaque "unit" to be pluralized by suffix. So "2 large" of
#: eggs produced "two larges of eggs", and "2 small slice" produced "two small
#: sliceses" once the suffix rule met a word that was already plural. Splitting
#: the descriptor off is what lets the adjective attach to the noun it belongs
#: to — "two large eggs", "two small slices of vodka pizza".
_SIZE_DESCRIPTORS = (
    "extra large", "extra-large", "x-large", "jumbo", "large", "big",
    "medium", "regular", "standard", "small", "mini", "tiny",
    "thin", "thick", "heaping", "heaped", "generous", "scant", "level",
)

#: Irregular plurals worth knowing. Everything else takes the suffix rule, but
#: only AFTER the phrase has been parsed — never on a raw unit string.
_IRREGULAR_PLURALS = {"half": "halves", "loaf": "loaves", "leaf": "leaves",
                      "knife": "knives", "foot": "feet", "tooth": "teeth"}


def _split_descriptor(unit_text: str) -> tuple:
    """`"small slice"` → `("small", "slice")`. Longest descriptor wins.

    Returns `("", unit_text)` when nothing modifies the unit, so callers can
    treat the descriptor as optional without a second code path.
    """
    text = (unit_text or "").strip().lower()
    for word in sorted(_SIZE_DESCRIPTORS, key=len, reverse=True):
        # A descriptor is an adjective, so a PLURAL one is always malformed
        # input — "2 larges" is an upstream inflection of a word that should
        # never have been inflected. Accept it and correct it here rather than
        # passing it through to be pluralized a second time.
        for form in (word, word + "s"):
            if text == form:
                return word, ""
            if text.startswith(form + " "):
                return word, text[len(form) + 1:].strip()
    return "", text


def _plural(word: str, amount: float) -> str:
    """Pluralize a single NOUN. Never call this on a raw portion string.

    Already-plural words are left alone: the suffix rule applied to "slices"
    produced "sliceses" and to "sticks" produced "stickses", which is what put
    both on a shipped screenshot.
    """
    if amount == 1 or not word:
        return word
    if word in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[word]
    # Already plural — "slices", "sticks", "wings". Bare "s" after a consonant
    # is the ordinary plural; "ss" (glass, hummus) is not.
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
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
    descriptor, unit = _split_descriptor(match.group(2))
    spoken = _spoken_name(name, branded)

    # A HEDGE IS NOT A UNIT. Handled before anything tries to pluralize it or
    # put a number in front of it, because both are wrong: nobody says "one
    # some of mustard", and "two somes" is not the repair.
    _hedge = _HEDGE_UNITS.get((unit or "").rstrip("s")) or \
        _HEDGE_UNITS.get(unit or "")
    if _hedge:
        return _hedge.format(food=spoken)

    # The unit IS the food — "0.5 banana" of "Banana" — or says nothing.
    #
    # "Names the food" means the unit word appears ANYWHERE in the food name,
    # not only at its end. Checking only the tail let "3 stick" of "mozzarella
    # sticks with marinara" through as "three sticks of mozzarella sticks with
    # marinara", saying the same noun twice in one phrase.
    stem = spoken.lower().rstrip("s")
    food_words = {w.rstrip("s") for w in re.findall(r"[a-z]+", spoken.lower())}
    # An "empty" unit stops being empty once a descriptor modifies it: "piece"
    # says nothing, "thin piece" says the thing the user bothered to tell us.
    names_the_food = unit and (unit.rstrip("s") == stem
                               or stem.endswith(" " + unit.rstrip("s"))
                               or unit.rstrip("s") in food_words)
    # A food that IS a discrete item does not also need "piece". "2 large
    # piece" of eggs came out as "two large pieces of eggs" — the descriptor
    # rescued the empty unit, correctly for "2 large pieces of pizza" and
    # wrongly here, because an egg is already the piece. The countable-noun
    # list in the normalizer is what knows the difference, and asking it beats
    # keeping a second list in sync with it.
    if unit in _EMPTY_UNITS and not names_the_food:
        try:
            from skills.nutrition.normalize import is_count_unit
            head = re.findall(r"[a-z]+", spoken.lower())
            if head and is_count_unit(head[-1]):
                names_the_food = True
        except Exception:
            pass
    # No unit word at all ("2 large" of eggs) means the descriptor belongs to the
    # food: two large eggs, not two large pieces of eggs.
    if names_the_food or not unit or (unit in _EMPTY_UNITS and not descriptor):
        return _count_of(amount, spoken, descriptor)
    if unit in _EMPTY_UNITS:
        sized = f"{descriptor} {unit.rstrip('s') or 'piece'}".strip()
        if amount == 1:
            return f"{_article(sized)} {sized} of {spoken}"
        return f"{_number_word(amount)} {_plural_phrase(sized, amount)} of {spoken}"

    if unit in _MASS_UNITS:
        return f"{_trim_amount(amount)}{_MASS_UNITS[unit]} of {spoken}"

    if unit in _FORMAT_UNITS:
        word = _FORMAT_UNITS[unit]
        sized = f"{descriptor} {word}".strip() if descriptor else word
        if amount == 1:
            return f"{_article(sized)} {spoken} {sized}"
        return f"{_number_word(amount)} {spoken} {_plural_phrase(sized, amount)}"

    measure = _SPOKEN_UNITS.get(unit, unit)
    sized = f"{descriptor} {measure}".strip() if descriptor else measure
    fraction = _SPOKEN_FRACTIONS.get(round(amount, 3))
    if fraction:
        word, connector = fraction
        return f"{word} {connector} {sized} of {spoken}"
    return f"{_number_word(amount)} {_plural_phrase(sized, amount)} of {spoken}"


def _count_of(amount: float, name: str, descriptor: str = "") -> str:
    """A count of the food itself, with no unit worth naming.

    The descriptor stays an adjective on the food: "2 large" of eggs is "two
    large eggs", never "two larges of eggs".
    """
    sized = f"{descriptor} {name}".strip() if descriptor else name
    fraction = _SPOKEN_FRACTIONS.get(round(amount, 3))
    if fraction:
        word, connector = fraction
        if connector == "a":
            return f"{word} {_article(sized)} {sized}"
        return f"{word} of {_article(sized)} {sized}"
    if amount == 1:
        one = _singular_food(sized)
        return f"{_article(one)} {one}"
    return f"{_number_word(amount)} {_plural_food(sized, amount)}"


def _plural_phrase(phrase: str, amount: float) -> str:
    """Pluralize the HEAD of an adjective phrase: "small slice" → "small
    slices". Pluralizing the whole string gave "small sliceses"."""
    parts = (phrase or "").split()
    if not parts:
        return phrase
    parts[-1] = _plural(parts[-1], amount)
    return " ".join(parts)


#: Prepositions that end the head of a food name. "mozzarella sticks with
#: marinara" is a kind of STICK; everything from "with" onward is a modifier.
_HEAD_STOPS = (" with ", " and ", " in ", " of ", " on ", " over ", " topped ")


def _head_span(name: str) -> int:
    """Index where the head noun phrase ends — before the first preposition
    or comma."""
    lowered = f" {name.lower()} "
    cuts = [lowered.index(stop) for stop in _HEAD_STOPS if stop in lowered]
    # A COMMA ENDS THE HEAD TOO. The interpreter routinely names a food in the
    # appositive form — "chicken thigh, grilled teriyaki marinated" — where
    # everything after the comma says how the head was prepared. Without this
    # the head ran to the end of the string and the preparation got inflected:
    # "Two chicken thigh, grilled teriyaki marinateds".
    comma = name.find(",")
    if comma >= 0:
        cuts.append(comma)
    return min(cuts) if cuts else len(name)


def _plural_food(name: str, amount: float) -> str:
    """Pluralize the food's HEAD noun only.

    "two Peanut M&M's" already reads plural and "two egg" does not — but the
    head is not always the last word. Pluralizing the last word turned
    "mozzarella sticks with marinara" into "...with marinaras", inflecting the
    sauce instead of the sticks. And a head that is ALREADY plural needs
    nothing: that is the same "sticks"→"stickses" mistake one level up.
    """
    if amount == 1 or not name:
        return name
    head = name[:_head_span(name)].rstrip()
    tail = name[len(head):]
    if not head:
        return name
    words = head.split()
    last = words[-1]
    if last.endswith(("s", "'s", "x", "ch", "sh")):
        return name
    words[-1] = last + "s"
    return " ".join(words) + tail


def _singular_food(name: str) -> str:
    """"eggs" → "egg", for the amount==1 case. The head only, and never a word
    whose "s" is part of it ("hummus", "asparagus")."""
    if not name:
        return name
    head = name[:_head_span(name)].rstrip()
    tail = name[len(head):]
    words = head.split()
    if not words:
        return name
    last = words[-1]
    if last.endswith("s") and not last.endswith(("ss", "us", "is", "'s")):
        words[-1] = last[:-1]
    return " ".join(words) + tail


def _number_word(amount: float) -> str:
    if amount == int(amount):
        return _SPOKEN_COUNTS.get(int(amount)) or _trim_amount(amount)
    return _trim_amount(amount)


def _trim_amount(amount: float) -> str:
    return (str(int(amount)) if float(amount).is_integer()
            else f"{amount:g}")


@dataclass(frozen=True)
class ConversationalContext:
    """What the message was ALSO about, as a structured obligation.

    A mixed message is not either food or conversation. It is both, and the
    plan modelled only one of them: `intent` is singular, so
    GENERAL_CONVERSATION is mutually exclusive with COMMIT and CLARIFY rather
    than sitting alongside them. The food half arrives as approved facts and a
    narrow brief; everything else arrived as `user_message`, unstructured, and
    the specific task won.

        "I had chicken and rice after a brutal meeting. I think I'm going to
         quit."

    The plan understood chicken, rice, and a disposition. It had no
    representation of the meeting, the distress, or the fact that the food
    operation was one part of the turn — so COMMIT's brief ("return an empty
    string if there is nothing useful") made silence the compliant answer.

    Not only emotional. "I ate this before my workout", "we were celebrating
    our anniversary", "the restaurant messed up my order", "I made this for my
    son too" carry obligations with no feeling attached, which is why
    `user_emotional_context` — present on this plan since it was written, and
    populated by nothing anywhere — was never going to be enough.

    THE APPROVED WORDINGS ARE NOT DECORATION. `fallback()` runs when the
    composer has already failed twice, and a deterministic renderer must not
    improvise a reply to distress. It may only repeat wording the upstream
    extractor approved; absent that it says nothing rather than guessing, and
    genuinely urgent content should be routed out of the food renderer
    entirely rather than prefaced by it.
    """
    #: What the non-food part was about, in a few words ("quitting their job").
    topic: str = ""
    #: Their own words, so the composer can answer what was actually said.
    user_statement: str = ""
    #: Present only when there is one — "distressed", "relieved", "celebrating".
    emotional_signal: str = ""
    #: What the reply owes them. "briefly acknowledge", "answer the user's
    #: question", "offer support before discussing food", "address this
    #: directly; do not ignore it".
    response_obligation: str = "briefly acknowledge"
    priority: str = "normal"                 # normal | important | urgent
    #: Deterministic wording, supplied upstream, for the fallback path only.
    approved_acknowledgement: str = ""
    approved_fallback_response: str = ""

    @property
    def is_material(self) -> bool:
        """Whether a reply that ignores this is wrong rather than merely terse."""
        return self.priority in ("important", "urgent")


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
    #: What we costed this item at — populated ONLY where no card will show it.
    #:
    #: The thinness above is deliberate and stays: a composer that can see
    #: numbers a card is already displaying will recite them. But on a
    #: clarification nothing commits, so there IS no card — and the brief still
    #: told the composer "the card already shows your reading of the meal".
    #: It does not. The user got a bare question with no reading at all, while
    #: the legacy path showed the breakdown, reasoned about the shakiest line
    #: and asked about that one. That is the better turn, and this is what it
    #: needs.
    calories: Optional[int] = None
    protein: Optional[int] = None

    def describe(self) -> str:
        """The item as a person would say it.

        Was `f"{portion} {name}"`, which produced "0.5 banana Banana" the
        moment the interpreter used the food as its own unit — and "15 pieces
        Peanut M&Ms" and "1 tbsp Peanut Butter" the rest of the time. Those
        read like a form, not a sentence, which is what the whole review turn
        was accused of.
        """
        described = describe_portion(self.portion, self.name,
                                     branded=self.branded)
        # AN AMOUNT NOBODY STATED IS NOT SHOWN AS THOUGH THEY DID.
        #
        # "had a Barebells bar and some chicken and rice" listed back "One cup
        # of white rice" — a cup nobody mentioned, printed in the same voice as
        # the items the user actually specified. `estimated` was already on
        # this object and only reached the card badge; the sentence the user
        # reads had no way to tell its own guesses from their words.
        #
        # A parenthetical rather than a rewrite: the phrase still reads as a
        # portion, and the marker is short enough not to turn a three-item list
        # into a wall.
        if self.estimated and self.portion.strip():
            described = f"{described} (my estimate)"
        return described

    def describe_bare(self) -> str:
        """The phrase without the estimate marker.

        Layout decisions measure how long a FOOD reads, and the marker is an
        annotation on top of that — letting it count flipped a two-item review
        out of prose and into a bulleted list purely because we had annotated
        our own guesses.
        """
        return describe_portion(self.portion, self.name, branded=self.branded)


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
    #: Items that were attempted and did NOT land. A fourth bucket rather than
    #: a flag, for the same reason `pending_items` is its own collection:
    #: MealResolution has carried a `failed` tuple all along, and
    #: `plan_from_resolution` dropped it on the floor. So a failed item reached
    #: the composer as nothing at all — which made the false claim legal (the
    #: validator had no item to check) and the honest mention illegal (the name
    #: was not in `approved_names`, so the invented-item guard would flag it).
    #: The Barebells bar in the 2026-07-25 transcript came through this seam.
    failed_items: Tuple[FoodItemSummary, ...] = ()
    assumptions: Tuple[Any, ...] = ()
    #: HOW each committed number was arrived at, as
    #: `{"name", "detail", "confidence"}` — the same account `_stash_sourcing`
    #: already builds for the "Arnie's thoughts" receipt.
    #:
    #: The receipt knew the whole story ("From the product label", "Generic
    #: USDA data standing in for this product", which lanes ran and what each
    #: returned) and the writer knew only the total. That is why the sentence
    #: could not sound like it understood its own answer: an assistant that
    #: knows a number came off a label and one that knows it was sized from a
    #: typical portion should not hedge identically, and this one had no way to
    #: tell.
    #:
    #: Reasoning material, NEVER the subject. "That's straight off the label,
    #: so it's solid" is the use; "USDA had no match so I fell back to the
    #: portion ontology" is the mechanics narration the persona forbids.
    sourcing: Tuple[dict, ...] = ()
    #: What a correction actually changed, as "before -> after" pairs.
    #: The plan used to carry only the AFTER state, and the CORRECT
    #: brief asks the composer to name what changed — so it invented the
    #: before. A turn correcting a pork portion shipped "you swapped the
    #: chashu pork for the chicken" over a conversation containing no
    #: chicken. A composer cannot describe a change it was never told.
    corrections: Tuple[str, ...] = ()
    #: Foods whose identity was corrected and whose numbers could NOT follow,
    #: because nothing could price the new identity and a zero is not a price.
    #:
    #: The row keeps the previous food's figures, which is the right write and
    #: the wrong silence: "Fixed it to a double cheeseburger" shipped over the
    #: single cheeseburger's 324 cal against a real 450, and the user had to
    #: notice and supply the number. The executor recorded exactly this and
    #: nothing read it.
    #:
    #: Presence forces `requires_answer` — a correction normally may not ask,
    #: and this is the one shape that has to, because the only remaining source
    #: for the number is the person who ate it.
    unpriced_corrections: Tuple[str, ...] = ()

    # Clarification.
    clarification_question: Optional[str] = None
    clarification_options: Tuple[str, ...] = ()
    #: The meal's unknowns, GROUPED by what is actually unknown — not one
    #: extracted point per food.
    #:
    #: Four foods described as "some" are one question (how big were the
    #: portions) asked about four things, not four questions of which we ship
    #: the first. Each entry carries the items it covers, the plain-words name
    #: of the unknown, the phrasings available, and the calories riding on it,
    #: so the renderer can compose what the situation needs — one thing when
    #: one thing is unclear, two when two genuinely belong in the same breath —
    #: instead of reciting a fragment chosen by the order the interpreter
    #: happened to emit.
    #:
    #: Sorted by weight, so `[0]` is the unknown worth the most.
    clarification_unknowns: Tuple[dict, ...] = ()
    requires_answer: bool = False

    # What the existing card already shows.
    card_will_render: bool = False
    facts_visible_in_card: FrozenSet[str] = frozenset()

    # ── What a COMMIT is allowed to say (review item 3) ─────────────────────
    #
    # The commit confirmation used to be authored OUTSIDE this module —
    # `food_ledger.render_committed()` produced the whole reply, and
    # `strip_card_recitation()` then removed the parts the card was already
    # showing. So the response contract was a post-processing pass over text
    # somebody else wrote: old copy could be generated first and then
    # imperfectly stripped, and the plan had no say in what got written.
    #
    # These are the inputs that rendering needs, carried on the plan so the
    # authoring happens here, once, with the card facts already known.
    # `committed_snapshot` is a food_ledger.TransactionSnapshot — the numbers
    # as the database holds them after the write, never the plan's own.
    committed_snapshot: Optional[Any] = None
    #: The interpreter's sentence. An INPUT, not the answer: it is used only if
    #: it is question-free and claim-free, which is the say contract.
    model_say: str = ""
    note: str = ""
    follow_up: str = ""
    #: What did NOT land, already phrased. Never suppressed by the card — a
    #: card cannot show an item that was not written.
    failure_notice: str = ""

    #: Foods in play this turn, for the invented-item check. A general
    #: "is this a food word" test would flag ordinary language, so the caller
    #: supplies the vocabulary.
    known_foods: Tuple[str, ...] = ()

    # Conversational context.
    user_message: str = ""
    user_emotional_context: Optional[str] = None
    #: The thread this turn belongs to, oldest first, as
    #: `{"role": "user"|"assistant", "content": str}`.
    #:
    #: Replaces `previous_assistant_message`, which was declared here and read
    #: by nothing — one remembered line was never going to be enough anyway.
    #: The composer was called with a single hard-coded "Write the response.",
    #: so it had never seen the conversation it was writing into: it could not
    #: refer back, could not match register, could not tell a first log from
    #: the fourth in a row. The persona asks it to be context-aware and this is
    #: the context.
    conversation_history: Tuple[dict, ...] = ()
    recent_response_openers: Tuple[str, ...] = ()

    #: What else the message was about. A SECOND OBLIGATION, not a second
    #: intent — see `ConversationalContext`.
    conversational_context: Optional["ConversationalContext"] = None

    # The day this reply is being written into, and who it is being written
    # for. Both are FACTS TO REASON FROM, never things to recite.
    #
    # `build_prompt` read neither of these, which made the composer strictly
    # less informed than the template it replaced: `fallback` reads
    # `committed_snapshot` for its numbers, so turning the composer ON traded
    # a reply that knew the day for one that only sounded like it did. It
    # could not say "that's the last 300 you've got with dinner still open",
    # because nobody ever told it where the day stood.
    #
    # `day_state` is the pre-write form — the same DB-derived sentence the
    # interpreter already receives as `day_line` (totals and targets read off
    # `DailyLog` + preferences, never a model's claim). After a write,
    # `committed_snapshot` carries the same facts structurally and wins.
    day_state: str = ""
    #: quick | moderate | strict — how much friction this user has asked for.
    user_mode: str = ""
    #: cut | bulk | maintain — what the numbers are FOR.
    user_goal: str = ""

    # Coaching.
    coaching_opportunity: Optional[CoachingOpportunity] = None

    # Failure.
    failure: Optional[FailureIntent] = None

    # Limits.
    max_sentences: int = 2
    max_words: int = 45
    allow_question: bool = False
    allow_no_text: bool = False


    @property
    def approved_names(self) -> set:
        names = set()
        # Failed items are approved for MENTION. Naming what did not land is
        # the honest thing to do, and it must not be mistaken for an invented
        # food; whether the text may claim it LANDED is a separate check.
        for group in (self.resolved_items, self.committed_items,
                      held_items(self), self.failed_items):
            for item in group:
                # AN UNNAMED ITEM APPROVES EVERYTHING. The empty string is a
                # substring of every text, so one nameless failure would make
                # the invented-item guard pass anything at all.
                #
                # `plan_from_resolution` used to drop these on the way in, and
                # it was the only builder that did — so the guarantee lived in
                # one constructor rather than on the plan. It is here now,
                # where every caller gets it and none can forget.
                name = (item.name or "").strip().lower()
                if name:
                    names.add(name)
        return names


# ── intent policy (build order: deterministic, never model-chosen) ────────────
#: max_sentences, max_words, allow_question, allow_no_text
INTENT_POLICY = {
    FoodResponseIntent.REVIEW: (2, 55, True, False),
    # 40 words was written for a bare question. A clarification that has to
    # SHOW its reading before asking cannot do it in that, and a budget that
    # forces a worse turn is the wrong constraint (Danny 2026-07-27).
    FoodResponseIntent.CLARIFY: (3, 70, True, False),
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


def pursued_unknowns(unknowns: Tuple[dict, ...],
                     mode: str = "moderate") -> Tuple[dict, ...]:
    """The unknowns THIS mode cares about — the granularity dial.

    The mode is not a length setting. It is a statement about how precisely the
    user wants their food understood before it is written down, and the
    thresholds that encode it already exist: 300 / 200 / 100 calories in
    `skills.nutrition.materiality`. They governed whether the staged engine
    asked, and never reached the clarification the user actually reads — so
    quick, moderate and strict pursued exactly the same unknowns and differed
    only in how many words they took to say so.

    Scaling the SENTENCE budget by mode was the same mistake wearing a nicer
    hat: it made strict wordier rather than more thorough. Strict is not three
    sentences, it is willing to ask about the cooking oil.

    The top unknown always survives, whatever the mode: a turn that decided
    something was worth stopping the user for, and then asked nothing, is worse
    than either asking or committing quietly.
    """
    from skills.nutrition.materiality import calorie_threshold
    threshold = calorie_threshold((mode or "moderate").strip().lower() or "moderate")
    kept = tuple(u for u in unknowns
                 if float(u.get("weight") or u.get("stakes") or 0) >= threshold)
    return kept or unknowns[:1]


#: Intents whose turn actually moved the log. Silence is not available to any
#: of them once something landed — see `apply_policy` and `_subject_line`.
_WRITE_INTENTS = frozenset({
    FoodResponseIntent.COMMIT, FoodResponseIntent.PARTIAL_COMMIT,
    FoodResponseIntent.CORRECT, FoodResponseIntent.UNDO,
})


def apply_policy(plan: FoodResponsePlan) -> FoodResponsePlan:
    """Stamp the intent's limits onto the plan.

    `requires_answer` can raise allow_question but nothing can lower it below
    what the intent permits — a plan that must be answered has to be allowed to
    ask.

    A clarification's room follows from HOW MUCH IT HAS TO ASK, not from the
    mode. One unknown is a sentence; three genuinely material ones cannot be
    covered in a sentence, and squeezing them into one is how a coach starts
    sounding like a form. The mode decides which unknowns qualify
    (`pursued_unknowns`); the budget is downstream of that count.
    """
    sentences, words, allow_q, allow_none = INTENT_POLICY[plan.intent]
    if plan.intent is FoodResponseIntent.CLARIFY and plan.clarification_unknowns:
        count = len(pursued_unknowns(plan.clarification_unknowns, plan.user_mode))
        sentences = max(sentences, min(3, count + 1))
        words = max(words, min(70, 25 * count + 20))
    if plan.unpriced_corrections:
        # A correction may not normally ask — its job is to show the change
        # took. This is the one shape that has to: the identity moved, nothing
        # could price the new one, and the only remaining source for the number
        # is the person who ate it. Staying silent here is what let "Fixed it
        # to a double cheeseburger" ship over the old food's calories.
        allow_q = True
        allow_none = False
        words = max(words, 45)
    if plan.requires_answer:
        allow_q = True
        allow_none = False
    if (plan.intent is FoodResponseIntent.CLARIFY and not plan.card_will_render
            and any(getattr(i, "calories", None)
                    for i in (tuple(plan.resolved_items)
                              + held_items(plan)))):
        # An itemised reading plus a total plus the question does not fit in a
        # two-sentence, forty-word budget written for a question alone.
        sentences = max(sentences, 8)
        words = max(words, 170)
    if plan.conversational_context is not None:
        # A MIXED TURN IS NOT A FOOD TURN WITH EXTRA WORDS. COMMIT's budget is
        # two sentences and thirty-five words with silence permitted, written
        # for a turn where the card says everything — and on a message that
        # also mentioned quitting a job, silence is the compliant answer to the
        # wrong question. Reserve room, and take away the permission to say
        # nothing: the card cannot acknowledge anything.
        sentences = max(sentences, 3)
        words = max(words, 65)
        allow_none = False
    if plan.committed_items and plan.intent in _WRITE_INTENTS:
        # A TURN THAT WROTE A ROW MAY NOT SAY NOTHING. COMMIT's `allow_no_text`
        # was written for the card: the card confirms the entry, so the
        # sentence is free to be silent. What that produced in practice was a
        # reply with no subject — the strip took every figure, the permission
        # took what was left, and logging a meal returned the empty string.
        #
        # The permission stays on the table for a COMMIT plan that committed
        # nothing (a coaching-shaped turn that reached this intent), which is
        # the only case where silence names nothing because there is nothing to
        # name. `_subject_line` is the floor everywhere else.
        allow_none = False
    if plan.assumptions and not plan.card_will_render:
        # AN UNDISCLOSED ASSUMPTION IS THE ONE THING SILENCE CANNOT COVER.
        # COMMIT permits no text at all on the reasoning that the card already
        # said it happened — true of the numbers, false of a choice the turn
        # made on the user's behalf. WHERE A CARD RENDERS it now carries that
        # choice as its own chip, so the sentence is free to do its usual job;
        # where none does (Telegram, iMessage, an older client) the sentence is
        # the only carrier there is, and it must speak.
        allow_none = False
        words = max(words, 45)
    return replace(plan, max_sentences=sentences, max_words=words,
                   allow_question=allow_q, allow_no_text=allow_none)


def held_items(plan) -> tuple:
    """Everything this turn is holding rather than writing.

    Audit T-2: `validate()`'s PENDING_AS_COMMITTED guard iterates
    `pending_items`, and every clarify builder records the food in question as
    `unresolved_item` instead — so the guard had nothing to iterate and could
    never fire on a clarification. `pending_items` has exactly one producer in
    the tree, `plan_from_resolution`, part of the MealResolution chain that has
    no caller. The one check between an un-committed item and a
    committed-looking sentence was fed solely by the function nobody calls.

    Read here rather than by populating `pending_items` in the builders. That
    was tried and is wrong: `pending_items` is also what the deterministic
    fallback lists as the meal (`_leads_with_the_meal`), so filling it made the
    held food appear in the read-back as though it were settled. Two fields
    describing one fact is the failure mode this whole audit is about — the fix
    is for the guard to read the field that already holds the answer, not for a
    second field to start holding it too.
    """
    if plan.pending_items:
        return tuple(plan.pending_items)
    item = getattr(plan, "unresolved_item", None)
    return (item,) if item is not None and getattr(item, "name", "") else ()


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
    MISSED_CONVERSATIONAL_CONTEXT = "missed_conversational_context"
    NUMBER_NOT_COMMITTED = "number_not_committed"
    FAILED_AS_COMMITTED = "failed_as_committed"
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

#: A batch total, stated as a total. "Total: 300 cal, 25g protein",
#: "totals 300 calories", "for a total of 300".
#:
#: Separate from `_SLASH_TOTAL_RE` (a dashboard leaking into prose) and from
#: `_DAY_TOTAL_RE` (the day's running figure) because this is neither: it is
#: THIS MEAL summed, and on a turn that wrote nothing it is a number describing
#: something that does not exist.
#:
#: Production, 2026-07-28: "Protein roll, 300 cal, 25g protein / Total: 300
#: cal, 25g protein" — no card, no write, and a day sitting near 800, so
#: "Total" was not the day either. It was the batch total of an item that never
#: landed, and every existing guard was structurally unable to see it:
#: PENDING_AS_COMMITTED iterated an empty collection, `_recites_card_facts`
#: reads `facts_visible_in_card` which is empty on a clarify, and
#: `_claims_it_landed` needs a success verb near the name — a bare recital has
#: no verb.
#: The LABEL form only — a line that opens "Total:" or "Total —".
#:
#: Deliberately not "that totals 380" or "about 380 all in". Pricing the items
#: and summing them out loud is what SHOW THE READING, THEN ASK asks for
#: (2d69d41), and `build_prompt` instructs it. The defect is narrower: a
#: line-leading `Total:` is typographically identical to the day-state row the
#: card renders, so on a turn that committed nothing it reads as the day.
#:
#: A wider pattern was tried and rejected the composer's own instructed output,
#: so every clarification silently fell back to the deterministic renderer —
#: a guard that fights the prompt turns a feature off instead of protecting it.
_BATCH_TOTAL_RE = re.compile(r"(?:^|[|\n])\s*totals?\b\s*[:\-–—]", re.I)

#: The day's REMAINING budget, restated in prose.
#:
#: "That leaves about 240 calories for the day" and "about 60g to go" are the
#: card's own remaining row read aloud — the card renders "240 cal left · 60g
#: protein to go" directly above them, and often "Next: 60g protein, lean
#: sources" as well. They survived the recitation check by ending
#: forward-looking ("so make your next meal protein-forward"), which is the
#: shape that shipped: the remaining row, twice, with advice stapled to the
#: second copy.
#:
#: A recommendation still earns its digits — "I'd aim for 30-40g at lunch" names
#: a target for a future meal rather than restating today's balance. The
#: difference is the leaves/left/to-go phrasing, not the presence of a number.
_REMAINING_RE = re.compile(
    r"(?:\bleaves?\s+(?:you\s+)?(?:about\s+|around\s+|roughly\s+)?\d"
    r"|\b\d[\d,]*\s*(?:g|grams?|kcal|cal(?:orie)?s?)?\s*"
    r"(?:left|to go|remaining)\b"
    r"|\b(?:about|around|roughly)\s+\d[\d,]*\s*(?:g|grams?)?\s*to go\b)",
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
        # SILENCE IS AN ANSWER TO SOMETHING THEY SAID. A card can confirm a
        # meal; it cannot acknowledge a person, so an empty reply to a message
        # that also carried weight reads as having ignored them. Checked before
        # the general empty rule so the failure names the real reason.
        if plan.conversational_context is not None \
                and plan.conversational_context.is_material:
            return ValidationResult(False, Reason.MISSED_CONVERSATIONAL_CONTEXT,
                                    plan.conversational_context.topic)
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
    # A TOTAL OF WHAT? (audit T-2.) Nothing committed on this turn, so a batch
    # total is a sum over an empty set presented as a fact. The user reads it
    # as "logged"; the board disagrees, and the card that would have settled it
    # was never rendered because nothing landed.
    #
    # Scoped to plans that committed nothing at all — a PARTIAL_COMMIT legitimately
    # totals what it did write, and COMMIT obviously does.
    if not plan.committed_items and _BATCH_TOTAL_RE.search(raw):
        return ValidationResult(False, Reason.PENDING_AS_COMMITTED,
                                "a total on a turn that committed nothing")
    # ...and the commit case (audit I-5). `enforce_say_contract` is absolute
    # about digits — "the contract is physics" — but its output becomes
    # `plan.model_say`, a HINT. With FOOD_COMPOSER=true the text the user reads
    # is `compose_async()`'s own, and nothing compared it to what committed:
    # the numeric regexes here only test card-duplication and dashboard syntax.
    #
    # So the commit path had a contract that was bypassed and the ask path had
    # a guard that was unfed, which together meant NO stage checked a number in
    # a food reply against the row it describes. This is the commit half; T-2's
    # rule above is its no-snapshot case.
    _unbacked = _unbacked_figures(raw, plan)
    if _unbacked:
        return ValidationResult(False, Reason.NUMBER_NOT_COMMITTED,
                                ", ".join(_unbacked[:3]))

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
    # Held and failed items are both "not in the day", and a reply may name
    # either — but neither may be described as landed. The two share one check
    # and differ only in the reason code, because a guard written for one state
    # and not the other is how the failed bucket went unchecked for as long as
    # it did.
    # The verb-based check stays on the COMMIT-side collections. Pointing it at
    # a clarification's held item was tried and is wrong: naming that food is
    # required by SHOW THE READING, THEN ASK, and `_claims_it_landed` fires on
    # ordinary phrasing near the name — "chicken 180 — about 380 all in" reads
    # as landed because of the "in". It rejected the very sentences the feature
    # exists to produce, and the audit's own analysis says why it could not have
    # helped anyway: a bare recital has no verb for it to find.
    for items, reason in ((plan.pending_items, Reason.PENDING_AS_COMMITTED),
                          (plan.failed_items, Reason.FAILED_AS_COMMITTED)):
        for item in items:
            name = item.name.lower()
            if not name or name not in lowered:
                continue
            if _claims_it_landed(lowered, name):
                return ValidationResult(False, reason, item.name)

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


#: Success verbs that may follow the food's name — "the bar is in", "the bar
#: was counted". Bare "in" belongs only here: before a name it is ordinary
#: English ("in the morning I had a bar") and would fire on everything.
_LANDED_AFTER_RE = r"[^.?!]{0,40}\b(?:logged|in|added|counted|committed)\b"

#: The same claim with the verb in front — "logged the Barebells bar". The
#: original guard only looked forward from the name, so the most natural way to
#: say it walked straight through.
_LANDED_BEFORE_RE = (r"\b(?:logged|added|counted|committed|got)\b[^.?!]{0,40}")

#: Negations that turn a success verb into an honest report of the failure.
#: Without these the guard would reject the very sentence it wants — "couldn't
#: get the Barebells bar in" contains the food, then "in".
_NOT_LANDED_RE = re.compile(
    r"\b(?:could\s*n[o']?t|couldn't|did\s*n[o']?t|didn't|was\s*n[o']?t|wasn't|"
    r"is\s*n[o']?t|isn't|never|failed|unable|no|not)\b")


def _unbacked_figures(raw: str, plan) -> list:
    """Nutrient figures in the text that the committed snapshot cannot back.

    Audit I-5. Only runs when a snapshot exists — a turn that committed
    something has an authoritative set of numbers, and every figure in the
    reply has to be one of them.

    Deliberately narrow, because a false positive here costs the composer's
    reply and ships the deterministic fallback instead:

      * only `_NUTRIENT_NUMBER_RE` matches, so a figure must already look like
        a nutrient fact ("340 cal", "28g") — bare numerals, times and dates are
        not nutrition claims;
      * every legal value is allowed at ±1 to absorb rounding, and each item's
        own calories count as legal, since naming what an item cost is not a
        claim about the day;
      * small integers are ignored. "one of your two bars" is a count, and an
        item count is not a nutrient figure however the regex reads it.
    """
    snapshot = getattr(plan, "committed_snapshot", None)
    if snapshot is None:
        return []
    legal = set()
    try:
        for value in (snapshot.token_values() or {}).values():
            legal.add(round(float(value)))
    except Exception:
        return []
    for item in (tuple(plan.committed_items) + tuple(plan.resolved_items)):
        for attr in ("calories", "protein", "carbs", "fat"):
            value = getattr(item, attr, None)
            if isinstance(value, (int, float)):
                legal.add(round(float(value)))
    if not legal:
        return []

    out = []
    for match in _NUTRIENT_NUMBER_RE.finditer(raw or ""):
        digits = re.sub(r"[^\d]", "", match.group(0).split()[0])
        if not digits:
            continue
        stated = int(digits)
        # A count, not a nutrient figure.
        if stated <= 10:
            continue
        if not any(abs(stated - ok) <= 1 for ok in legal):
            out.append(match.group(0).strip())
    return out


def _claims_it_landed(lowered: str, name: str) -> bool:
    """Whether the text says this food made it onto the log.

    Naming a held or failed item is fine. Saying it is IN is not — unless the
    clause negates it, which is the honest report and must stay expressible.
    """
    escaped = re.escape(name)
    for pattern in (rf"{escaped}{_LANDED_AFTER_RE}",
                    rf"{_LANDED_BEFORE_RE}{escaped}"):
        match = re.search(pattern, lowered)
        if match is None:
            continue
        # Judge the whole clause, not just the matched span: the negation
        # usually sits in front of the verb ("couldn't touch the X", "didn't
        # log the X"), which a forward-only window never sees.
        start = max((lowered.rfind(c, 0, match.start()) for c in ".?!"),
                    default=-1)
        if _NOT_LANDED_RE.search(lowered[start + 1:match.end()]) is None:
            return True
    return False


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
#: What this lane adds ON TOP of the shared persona — the rules that exist
#: because this writer is handed committed facts rather than free rein.
#:
#: It used to be the whole persona. `ARNIE_VOICE` was 323 tokens defined right
#: here, and this module imported nothing from `core/prompts/arnie` — so a food
#: reply was written against a miniature Arnie with no bubble rules, no emoji
#: policy and no register, while every other turn in the product got ~3,400
#: tokens of it. Two personas, and the food one had never seen a conversation.
#: That is why a logged meal read like a different assistant answering.
#:
#: Everything below is genuinely lane-specific: it is about not inventing
#: numbers and not reciting a card. Who Arnie IS now comes from one place.
_FOOD_LANE_RULES = """\
You are writing ONE turn of an ongoing conversation. The rules above are who
you are; the rules below are what this particular turn allows.

Write only the conversational text appropriate to the supplied response intent.

You have structured facts. Do not add, alter, recompute, or infer nutrition
facts that are not supplied.

Do not narrate internal operations. Never mention tools, databases, resolvers,
models, processing, saving, or logging mechanics. The write already happened —
do not describe it.

Do not repeat information marked as visible in the existing card.

Do not force a question. Ask one only when the plan allows it and the answer
has a clear purpose.

Do not praise routine logging. Do not use generic coaching filler.

Write plain sentences. No markdown syntax, no headers, no horizontal rules, no
tables, and no asterisks for emphasis. Bullets are supplied by the caller when
a list is wanted — do not invent your own.

Return only the user-facing text. An empty reply is legal ONLY when the brief
below says so — a turn that wrote a row always says something, because silence
next to a card reads as a message that got dropped."""


#: Which compiled profile each moment gets. The mapping is the product
#: decision; `core/prompts/voice.py` owns what each profile contains.
#:
#: COMMIT, CORRECT and UNDO are the routine writes — something landed and
#: there is nothing to discuss — so they take the micro brief. COACH and
#: GENERAL_CONVERSATION are the turns that earn interpretation. FAILURE is the
#: only one that must never sound like either, so it has its own.
#:
#: PARTIAL_COMMIT is deliberately NOT micro: some of the meal went in and some
#: did not, and a brief whose whole instruction is "confirm it and stop" is the
#: wrong shape for a reply that has to say which was which.
_INTENT_PROFILE = {
    FoodResponseIntent.COMMIT: "micro_acknowledgement",
    FoodResponseIntent.CORRECT: "micro_acknowledgement",
    FoodResponseIntent.UNDO: "micro_acknowledgement",
    FoodResponseIntent.CONFIRM_ANSWER: "micro_acknowledgement",
    FoodResponseIntent.CLARIFY: "clarification",
    FoodResponseIntent.REVIEW: "clarification",
    FoodResponseIntent.PARTIAL_COMMIT: "coaching",
    FoodResponseIntent.COACH: "coaching",
    FoodResponseIntent.GENERAL_CONVERSATION: "coaching",
    FoodResponseIntent.FAILURE: "recovery",
}


def voice_profile_for(intent) -> str:
    """The profile name for a moment. `coaching` when unmapped: the widest
    brief is the safe default, because an unknown moment that reads as
    over-explained is recoverable and one that reads as curt is not."""
    return _INTENT_PROFILE.get(intent, "coaching")


def arnie_voice(intent=None) -> str:
    """The voice this moment needs, plus this lane's rules.

    Was the whole persona — `voice_core()`, ~3,400 tokens of IDENTITY,
    LANGUAGE, VOICE and EMOJI_SYSTEM — on every food turn, including the ones
    that write "rice cake logged, 35 cal". The compiled micro brief is around
    a third of that and drops nothing a routine acknowledgement uses; it is
    the same canonical text, selected rather than rewritten.

    Called with no intent it still returns the full persona, because the
    callers that pass nothing are the ones that do not know what moment they
    are in, and the widest voice is the right answer there.

    A function rather than a constant because `core.prompts.arnie` imports the
    skill loader at module scope, and a food turn that is only building a
    fallback should not pay for that. Falls back to the lane rules alone if the
    persona cannot be loaded — a thinner voice is survivable; failing the turn
    is not.
    """
    try:
        if intent is None:
            from core.prompts.arnie import voice_core
            return f"{voice_core()}\n\n{_FOOD_LANE_RULES}"
        from core.prompts.voice import compile_voice
        return f"{compile_voice(voice_profile_for(intent))}\n\n{_FOOD_LANE_RULES}"
    except Exception:                                    # pragma: no cover
        return _FOOD_LANE_RULES


_INTENT_BRIEF = {
    FoodResponseIntent.REVIEW:
        "Confirm your reading of the meal and ask one simple confirmation "
        "question. Do not coach and do not mention daily targets.",
    FoodResponseIntent.CLARIFY:
        # "Acknowledge what you already understood, THEN do not repeat the
        # whole meal" asked for two opposite things, and the acknowledgement
        # won every time: "So you had pasta, yellowtail crudo, Caesar salad,
        # and beef tartare. What kind of pasta was it, and roughly how much of
        # each dish did you eat?" — thirty words of list before the question,
        # above a card listing the same four foods.
        #
        # The reading is already on screen. What the user needs from the
        # sentence is the QUESTION, and the fastest way to answer it.
        "Ask the question. Where a card renders, lead with the question — the "
        "card is the receipt and repeating it wastes the turn. Where NO card "
        "renders, which is every clarification that commits nothing, show your "
        "reading FIRST: the itemised lines with their calories, the total, one "
        "clause on which line you trust least and why, and then the question "
        "about that line. A bare question with no reading attached asks them "
        "to check arithmetic they cannot see. Offer the likely answers as a short natural "
        "choice ('half or the whole thing?') rather than an open question, "
        "since a choice is answered in one tap and an open one is not "
        "answered at all. If they also said something meaningful outside the "
        "food log, acknowledge it briefly BEFORE the question — a "
        "clarification must not make the rest of their message sound "
        "invisible.",
    FoodResponseIntent.CONFIRM_ANSWER:
        "Briefly acknowledge the resolved meaning. Do not re-review the meal "
        "and do not ask again.",
    FoodResponseIntent.COMMIT:
        # "or return an empty string if there is nothing useful" was still here
        # after `allow_no_text` was withdrawn for a turn that actually wrote a
        # row. So the brief invited exactly what `validate()` then rejected as
        # EMPTY_NOT_ALLOWED — costing a second generation and, when that also
        # came back thin, the deterministic floor. An instruction the validator
        # refuses is worse than no instruction.
        #
        # And the length: the shared persona teaches 2-4 bubbles for a coaching
        # moment, which is right in general and wrong here — this one is 35
        # words. Saying so beats letting the two briefs argue and paying for a
        # retry when the general one wins.
        "The card already confirms the food entry. If the user also said "
        "something meaningful outside the food log, acknowledge or answer "
        "that FIRST. Otherwise name what landed and add at most one natural "
        "observation. This is a short moment — one or two bubbles, never "
        "three — and it always says something: a row went into their log and "
        "silence reads as a dropped message.",
    FoodResponseIntent.PARTIAL_COMMIT:
        "Say what is in, name the one item still open, and ask only the "
        "supplied question. Never describe the open item as logged.",
    FoodResponseIntent.CORRECT:
        # "One natural acknowledgement of what changed" produced
        # "Got it — you're making smart choices with that chicken and
        # shake", which acknowledges nothing and changes nothing. A
        # correction has exactly one job: show them it took.
        "Name WHAT CHANGED, in their words — the new flavour, the new "
        "amount, the method. \"Swapped it to the cookies and cream\" is "
        "the whole reply; a coach observation instead of the change is "
        "how a correction looks ignored. Do not recite the new numbers, "
        "the card carries those. If several things changed, one clause "
        "each.",
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


#: What each mode is ASKING FOR, in the coach's terms. The number of questions
#: is not capped anywhere — this is the judgement the cap was standing in for,
#: and it belongs with the model that is writing the sentence.
_MODE_INTENT = {
    "quick": ("They chose QUICK logging: a rough number now beats an exact one "
              "after an interview. Only the unknown below is worth stopping "
              "them for — everything else you estimate and move on."),
    "moderate": ("They chose MODERATE logging: get the food right without "
                 "turning it into a form. The unknowns below are the ones that "
                 "actually move the number; estimate anything finer."),
    "strict": ("They chose STRICT logging: they want the entry to be genuinely "
               "accurate and they expect to be asked. Understand the food "
               "properly — how it was cooked, what was on it, how much of it — "
               "and do not let something below go unasked to seem breezy."),
}


def _unknowns_brief(unknowns: Tuple[dict, ...], mode: str = "") -> str:
    """What the coach does not know yet, as material to write from.

    Deliberately not a sentence and not a list of per-food prompts. Each entry
    names ONE unknown and every food it applies to, because four foods
    described as "some" are one question asked about four things — and the
    shape that shipped, one extracted point per food with the first one
    surviving, is what this exists to stop.

    Stakes are given as reasoning material and fenced off from the text: the
    model decides how hard to push on an unknown, never reports the number.
    """
    lines = ["WHAT YOU DON'T KNOW YET (most consequential first):"]
    for unknown in pursued_unknowns(unknowns, mode)[:4]:
        names = [str(i) for i in (unknown.get("items") or ())]
        line = f"  • {unknown.get('phrase') or 'a missing detail'}"
        if names:
            # "for: A, B" read as a menu — the composer asked "which one did
            # you have, the bar or the shake?" about a meal containing both.
            # The list is what this unknown APPLIES TO, never a set of
            # alternatives, and one word of framing is what keeps it that way.
            line += (f" — applies to EACH of these (they had all of them): "
                     f"{', '.join(names)}" if len(names) > 1
                     else f" — for: {names[0]}")
        stakes = unknown.get("stakes") or 0
        if stakes:
            line += f"  [worth ~{int(stakes)} cal; never say this number]"
        lines.append(line)
        # ONE OWNER FOR THE RANGE. This block used to print endpoints AND the
        # reading block printed them again, so the shipped clarification said
        # it twice — "somewhere between 0 and 500 cal" and then "that puts the
        # snack somewhere in the 0 to 500 range". The second sentence carried
        # nothing. The reading block owns how an open line is described; this
        # one supplies the evidence it is described FROM.
        options = [str(o).strip() for o in (unknown.get("options") or ())
                   if str(o).strip()]
        if options:
            # These now carry their pack size and that pack's cost — "Takis
            # Fuego (3 oz, ~425 cal)" — so they are answerable in one word and
            # they are the honest ends of any range worth giving.
            lines.append("      they are choosing between: "
                         + " / ".join(options[:4]))
        # WHAT IT ACTUALLY NEEDS TO KNOW. `phrase` is a CATEGORY — "one missing
        # detail" — and the concrete question lived in `asks` and was never
        # rendered, so the composer had a category and had to invent the
        # question from it. For a stated 150 g of cottage cheese whose FAT
        # GRADE was the unknown, it invented the commonest kind and asked
        # "about a half cup, or more than that?" — a question about the one
        # thing the user had already told us.
        #
        # Phrasing still belongs to the composer; this is the substance it
        # phrases, not a sentence to repeat.
        asks = [str(a).strip() for a in (unknown.get("asks") or ()) if str(a).strip()]
        for ask in asks[:3]:
            lines.append(f"      needs: {ask}")
    intent = _MODE_INTENT.get((mode or "").strip().lower())
    if intent:
        lines.append(intent)
    lines.append(
        "Ask for what you need, the way you would out loud — it is a judgement "
        "about THIS meal, not a fixed number of questions. Do not work through "
        "them as a list and do not name the fields. Foods are theirs — write "
        "their names the way a person would, brands included.\n"
        "MAKE IT ANSWERABLE IN A WORD. Put your own best guess INTO the "
        "question as one of two concrete choices — \"about a cup, or more than "
        "that?\", \"the whole thing or half?\" — so agreeing costs them one "
        "word and correcting you costs them two. An open question (\"how much "
        "was it?\", \"which one?\") makes them do the work of inventing an "
        "answer, and that is the question people skip.\n"
        "  ASK IT THE WAY A PERSON WOULD, not the way a label prints it. "
        "Grades, percentages and ratios are how the packet is written, not how "
        "anyone speaks: \"Which lean %?\" and \"what lean/fat ratio?\" read like a "
        "form. Lead with the plain contrast they actually chose between and let "
        "the number ride along if it helps \u2014 \"the leaner one or the regular?\", "
        "\"full fat or the light one?\". Same for a cut, a milk, a mince: the "
        "words they would use standing in the shop, not the spec on the back.\n"
        "  OFFERING IS NOT ASSERTING. Naming a likely amount as one side of a "
        "choice is how a person asks; stating it as settled is not. \"Was that "
        "about a cup, or more?\" is right. \"You had a cup — sound right?\" is "
        "not: it invites a yes to a number nobody established.\n"
        "  Several unknowns go in ONE breath, grouped the way they would be "
        "spoken — a clause per thing, not a paragraph per thing. Every part "
        "gets its own choice; a question that trails off into an open one at "
        "the end is the part that goes unanswered.")
    return "\n".join(lines)


def _open_readings(plan: FoodResponsePlan) -> set:
    """The foods, lowered, that some unknown still covers.

    This used to return `(ranges, open_names)` — a computed endpoint pair
    alongside the open set. The endpoints are gone (see the note where
    `FoodAmbiguity.calorie_range` used to live); what survives is the part that
    was always sound, which is knowing WHICH lines are still open.
    """
    open_names = set()
    for unknown in (plan.clarification_unknowns or ()):
        if not isinstance(unknown, dict):
            continue
        for name in (unknown.get("items") or ()):
            key = str(name).strip().lower()
            if key:
                open_names.add(key)
    return open_names


def _reading_line(item, open_names: set) -> str:
    """One food in the reading: the figure where it is settled, and an explicit
    "open, do not state this as settled" where it is not.

    There is no longer a third form. An open line used to be rendered as
    "between X and Y" whenever the doubt could be priced, and those endpoints
    were arithmetic on a width — the reading ± half the span, floored at zero —
    which is how a bag of Cheez Doodles became "somewhere between 0 and 500
    cal". Whether a range is worth offering, and what its ends should be, is a
    judgement about the food and the occasion. It belongs to the sentence, made
    from the reading, the swing and the priced options, not to this line.
    """
    key = (item.name or "").strip().lower()
    protein = (f", {item.protein}g protein"
               if getattr(item, "protein", None) else "")
    if key in open_names:
        return (f"{item.name} — around {item.calories} cal, but OPEN: this is "
                f"what your question decides, so do not state it as "
                f"settled{protein}")
    return f"{item.name} — {item.calories} cal{protein}"


def build_prompt(plan: FoodResponsePlan) -> str:
    """The generation prompt: voice, intent brief, approved facts, limits."""
    brief = _INTENT_BRIEF.get(plan.intent, "")
    if plan.intent is FoodResponseIntent.COMMIT and plan.card_will_render:
        # THE CARD IS A RECEIPT, NOT AN ACKNOWLEDGEMENT. The standing brief —
        # "the card already confirms the food entry … or return an empty string
        # if there is nothing useful" — is what produced a reply that never
        # said what was logged. Forbidden the figures by ALREADY ON THE CARD,
        # and told the entry was already confirmed, the composer had one thing
        # left to write and wrote a mood: "You've got solid room to work with."
        #
        # The numbers stay the card's. The NAME is the sentence's, and it is
        # not optional, because it is the only part of the reply that says the
        # message was heard.
        brief = ("Say what you logged, by name — in their words where they "
                 "gave you words. That is this sentence's job and it is not "
                 "optional: a reply that names nothing reads as a message that "
                 "was dropped. Do NOT recite calories, macros, the day total "
                 "or what is left; the card directly below carries all of it, "
                 "and repeating it is how the sentence stops being worth "
                 "reading. If the user also said something meaningful outside "
                 "the food log, answer that FIRST, then name the food. One "
                 "natural observation may follow the name — it is never a "
                 "substitute for it.")
    if (plan.assumptions and not plan.card_will_render
            and plan.intent is FoodResponseIntent.COMMIT):
        # THE BRIEF ITSELF HAD TO CHANGE. "The card already confirms what was
        # logged, add one natural observation" frames the whole job as
        # coaching, so a disclosure line further down the prompt loses to it —
        # four assumptions were made and the shipped sentence was a generic
        # read about having room left. True of the numbers, which the card
        # does confirm; false of a choice made on their behalf, which no card
        # explains and which no card exists to explain on Telegram or iMessage.
        brief = ("No card renders here, so this sentence is the only place\n"
                 "the guess can surface. You logged this WITHOUT asking, "
                 "judged too small to interrupt them for. That judgement is "
                 "yours to disclose: the one thing this sentence owes them is "
                 "what you assumed. Say it plainly, briefly, in their own "
                 "words — a wrong guess has to be obvious enough that they "
                 "correct it in one tap. The card confirms the numbers, so do "
                 "not recite those; a coach observation is optional and comes "
                 "second, if at all.")
    parts = [arnie_voice(plan.intent), "", f"INTENT: {plan.intent.value}", brief]

    # THE READING GOES IN THE TEXT WHEN NO CARD WILL CARRY IT. A clarification
    # commits nothing, so the brief's old promise — "the card already shows
    # your reading of the meal" — was false exactly where it mattered, and the
    # user got a question with no reading attached.
    # `held_items`, not `pending_items` — on a clarification the held food
    # lives in `unresolved_item`, so reading the commit-side field alone left
    # THE VERY FOOD BEING ASKED ABOUT out of the reading. "Show your reading,
    # then ask" listed the bar and silently dropped the chicken it was about
    # to ask about.
    _priced = [i for i in (tuple(plan.resolved_items) + held_items(plan))
               if getattr(i, "calories", None)]
    if _priced and not plan.card_will_render:
        # RANGE FIRST, FOR THE LINE THAT IS IN QUESTION. This block used to
        # print "{name} — {calories} cal" for every food including the one the
        # turn was about to ask the identity of, and the composer wrote what it
        # was given: "You've got the hand roll down at 230 calories and 10g
        # protein, that's your reading so far. The catch is which one you
        # grabbed…" — a number asserted as settled, contradicted by the next
        # sentence.
        #
        # The endpoints were computed and discarded one layer up
        # (`unknowns_from_decision`, `FoodAmbiguity.calorie_range`). Where they
        # survive, the open line is written as the range it actually is. Where
        # nothing could price the doubt, the line is still marked open, because
        # the failure to price it is not a licence to state it.
        _open = _open_readings(plan)
        _any_open = bool(_open & {i.name.strip().lower() for i in _priced})
        parts.append(
            "SHOW YOUR READING, THEN ASK. Two bubbles.\n"
            "First bubble: one line per food, then the roll-up IN WORDS as "
            "your reading of the meal — \"about 380 for the two of them\", or "
            "\"somewhere in the 380 to 530 range\" when a line below is open. "
            "NEVER a line beginning \"Total:\": that is the "
            "day-state row the card prints, and this turn has logged nothing, "
            "so it reads as a day they have not eaten. Second bubble: name "
            "the line you trust least, say in a "
            "clause why it is shaky, and ask about that one thing. Always end "
            "on the question — a reading with no question asks nothing and "
            "commits nothing.\n"
            + ("A LINE MARKED OPEN IS THE ONE YOU ARE ASKING ABOUT — never "
               "state a single figure for it. Stating a number for the thing "
               "you are about to ask about tells them the answer does not "
               "matter, and the roll-up inherits it: if any line is open, the "
               "meal total is a range too.\n"
               "IF YOU GIVE A RANGE, MAKE IT ONE A PERSON WOULD ACTUALLY "
               "OFFER. Both ends have to be things they could plausibly have "
               "eaten in this sitting. A bottom end of zero is never right — "
               "they told you they ate it — and neither is a top end nobody "
               "finishes in one go, like a whole share bag. Where the options "
               "below carry sizes and costs, those are your real ends; where "
               "they do not, say plainly that it is not settled yet rather "
               "than inventing a spread.\n" if _any_open else "")
            + "These are your own estimates. Write them as estimates, and use "
            "the foods below exactly; do not ask what they ate, you have it:\n  "
            + "\n  ".join(_reading_line(i, _open) for i in _priced))
    if plan.resolved_items:
        # UNDERSTOOD IS NOT LOGGED, and the bare label let the composer assume
        # it was. On a clarification nothing is written until they answer, so a
        # sentence like "got the chicken down" is a false claim about the day —
        # `validate()` catches it as PENDING_AS_COMMITTED and the deterministic
        # floor ships instead. That is why a mixed meal fell back to a bullet
        # list: the plan told the composer these were settled and the validator
        # knew they were not.
        _understood = "; ".join(i.describe() for i in plan.resolved_items)
        parts.append(
            ("UNDERSTOOD but NOT YET WRITTEN — nothing lands until they "
             "answer, so name these as read-back, never as logged/added/"
             "tracked/counted: " + _understood)
            if held_items(plan) else "UNDERSTOOD: " + _understood)
    ctx = plan.conversational_context
    if ctx is not None:
        parts.extend([
            "",
            "NON-FOOD CONTEXT THAT MUST NOT BE IGNORED:",
            f"They said: {ctx.user_statement or plan.user_message}",
            f"What it is about: {ctx.topic or 'unstated'}",
            f"Emotional signal: {ctx.emotional_signal or 'none'}",
            f"What your reply owes them: {ctx.response_obligation}",
            "Answer or acknowledge this in the SAME reply, in your own words "
            "and without repeating theirs back to them. Do not write as "
            "though they had submitted a food record. The food question or "
            "confirmation still happens — this comes first and stays short.",
        ])
        if ctx.priority == "urgent":
            parts.append(
                "This one is urgent. Address it directly; the food half may "
                "wait for a later turn if giving it room would be tone-deaf.")

    if plan.committed_items:
        parts.append("LOGGED (the card shows these — do not recite them): "
                     + "; ".join(i.describe() for i in plan.committed_items))
    if plan.sourcing:
        # HOW SURE TO SOUND. The receipt has always shown the user where a
        # number came from; the writer was never told, so it hedged the same
        # way over a label reading and a portion guess. That is most of what
        # separates a reply that sounds like it understands its own answer from
        # one that sounds like a form.
        _lines = []
        for src in plan.sourcing:
            if not isinstance(src, dict):
                continue
            name = str(src.get("name") or "").strip()
            detail = str(src.get("detail") or "").strip()
            if name and detail:
                _lines.append(f"  {name}: {detail}")
        if _lines:
            parts.append(
                "WHERE THESE NUMBERS CAME FROM — reasoning material, never the "
                "subject. Let it set how confident you sound and what is worth "
                "a caveat, in THEIR terms: \"that's straight off the label, so "
                "it's solid\", \"nobody publishes that one so I sized it from a "
                "typical portion\". Never name a database, a lookup, a source "
                "or a fallback — that is the mechanics narration you are "
                "already forbidden. Say nothing at all about sourcing when the "
                "answer is solid and the turn has something better to do with "
                "the sentence.\n" + "\n".join(_lines))
    if held_items(plan):
        parts.append("NOT LOGGED, still open: "
                     + "; ".join(i.name for i in held_items(plan)))
        if not plan.resolved_items and len(held_items(plan)) > 1:
            # THE WHOLE MEAL IS WAITING, and that is the only place the user
            # can see their logging mode at work. A turn holding everything and
            # a turn holding one item read identically until the hold set
            # stopped coming from the question — say the difference.
            parts.append(
                "NOTHING FROM THIS MEAL IS GOING ON THE BOARD until they "
                "answer — not one item of it. Say so in a clause, plainly and "
                "without apology; they chose this. Do not describe any of it "
                "as logged, added, tracked or counted.")
    if plan.corrections:
        parts.append(
            "WHAT ACTUALLY CHANGED — these and nothing else. Name them in "
            "their words; do not describe a swap, an addition or a removal "
            "that is not in this list, and if it is empty say only that it is "
            "updated:\n  " + "\n  ".join(plan.corrections))
    if plan.unpriced_corrections:
        parts.append(
            "THE NUMBERS COULD NOT FOLLOW. You renamed these, and nothing "
            "could price the new food — so the entry still carries the OLD "
            "food's calories. Say that plainly and ask them for the number; "
            "it is the only place left to get it. Do not imply the figures "
            "were updated, and do not guess one yourself:\n  "
            + "\n  ".join(plan.unpriced_corrections))
    if plan.assumptions:
        texts = [getattr(a, "user_visible_text", "") or str(a)
                 for a in plan.assumptions]
        # SAY IT, don't offer to. These are choices the turn made in place of a
        # question it decided not to ask — the user never supplied them and has
        # no other way to learn of them on a surface without cards. "May
        # surface" left the one thing they might want to correct as the one
        # thing most likely to be dropped for brevity.
        parts.append(
            "WHAT YOU ASSUMED — name it plainly in your sentence, briefly, so "
            "they can correct it: " + "; ".join(t for t in texts if t))
    if plan.clarification_unknowns:
        # THE QUESTION IS THE COACH'S TO WRITE.
        #
        # This used to say "ASK EXACTLY THIS (rephrasing for tone is fine)"
        # followed by an f-string built four modules upstream, which made the
        # composer a tone pass over a template and is why turning it on changed
        # nothing about how these read. Worse, the template it was handed had
        # already thrown away everything but one fragment: for a meal whose
        # four portions were worth 2,760 calories of doubt, what survived was
        # "What sauce - red, cream, oil based?".
        #
        # So the composer is given what is UNKNOWN rather than a sentence, and
        # writes the turn. No cap on how many unknowns it may cover — one when
        # one thing is unclear, two when two belong in the same breath. That is
        # a judgement about the situation, and judgement is what it is for.
        parts.append(_unknowns_brief(plan.clarification_unknowns,
                                     plan.user_mode))
    elif plan.clarification_question:
        parts.append(f"ASK EXACTLY THIS (rephrasing for tone is fine): "
                     f"{plan.clarification_question}")
    if plan.clarification_options:
        # THE ACTUAL SHELF. These come from the product database, so offering
        # them means the answer resolves to a real item with real numbers —
        # unlike a plausible-sounding pair the composer would invent, which
        # nothing downstream can look up. Entries are "Product: a, b, c" when
        # more than one product is in question; the pairing is not guesswork.
        parts.append(
            "REAL VARIANTS (from the product database — offer two or three of "
            "these verbatim rather than inventing options, and keep each set "
            "with the product it names):\n  "
            + "\n  ".join(plan.clarification_options))
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
    # WHERE THE DAY STANDS. Structural form first — a committed snapshot is
    # post-enrichment database state, so these are the same numbers the card
    # and the daily log show. The pre-write sentence is the fallback, for the
    # clarify moment that happens before anything is written.
    #
    # Reasoning material, not recitation material: the limits below cap the
    # reply, `facts_visible_in_card` names what the card already shows, and
    # `validate()` refuses card duplication. So the model can say "that's most
    # of what's left" without being able to restate a total the user is
    # already looking at.
    _snap = plan.committed_snapshot
    if _snap is not None:
        parts.append(
            "WHERE THE DAY STANDS (reason from these; do not restate a number "
            f"the card already shows): {_snap.day_cal} of {_snap.cal_target} "
            f"calories, {_snap.day_protein} of {_snap.protein_target}g "
            f"protein, so {_snap.cal_left} calories and "
            f"{_snap.protein_left}g protein left.")
    elif plan.day_state:
        parts.append("WHERE THE DAY STANDS (reason from these, do not recite "
                     f"them): {plan.day_state}")
    if plan.user_goal:
        parts.append(f"THEIR GOAL: {plan.user_goal} — what the targets are for.")
    if plan.user_mode:
        # The friction they asked for. A strict user WANTS the question; a
        # quick user finds the same question annoying, and the voice should
        # not read identically to both.
        parts.append(f"LOGGING MODE: {plan.user_mode}")
    if plan.facts_visible_in_card:
        parts.append("ALREADY ON THE CARD: "
                     + ", ".join(sorted(plan.facts_visible_in_card)))
    if plan.recent_response_openers:
        parts.append("DO NOT OPEN WITH: "
                     + "; ".join(plan.recent_response_openers))

    limits = [f"at most {plan.max_sentences} sentences",
              f"at most {plan.max_words} words"]
    # NOT "one question". `validate()` only ever checked whether a question is
    # PERMITTED, never how many — the cap lived here, in the wording, and it is
    # the same instinct that had the plan builder ship one facet of one food
    # out of six raised.
    #
    # And when the unknowns brief is present it already carries the judgement,
    # scaled to the mode: repeating a count here would contradict it outright,
    # since strict is told to pursue everything material while this line was
    # telling it "one thing usually".
    if not plan.allow_question:
        limits.append("no questions")
    elif not plan.clarification_unknowns:
        limits.append("ask for what you actually need")
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


#: The verb each write intent uses when the sentence has to name what it did
#: and nothing else. Same words the no-snapshot fallbacks already use, so a
#: turn does not change voice depending on whether a snapshot reached it.
_SUBJECT_VERB = {
    FoodResponseIntent.CORRECT: "Updated",
    FoodResponseIntent.UNDO: "Undid",
}


def _subject_line(plan: "FoodResponsePlan") -> str:
    """What this turn did, by name, with no number on it.

    The floor beneath every write. A turn that put a row in the log and then
    said nothing reads as a dropped message — the card is a receipt, and a
    receipt with no covering sentence is not how a person tells you they heard
    you. This is what the reply falls back to when the card has already taken
    every figure.

    Returns "" when there is nothing to name, so silence survives where silence
    is honest: a COMMIT plan that committed nothing has no subject.
    """
    names = [i.name for i in (plan.committed_items or ()) if i.name]
    if not names:
        return ""
    return f"{_SUBJECT_VERB.get(plan.intent, 'Logged')} {_join(names)}."


def _names_the_food(text: str, plan: "FoodResponsePlan") -> bool:
    """Does this text already name something the turn wrote?"""
    lowered = (text or "").lower()
    return any(i.name and i.name.lower() in lowered
               for i in (plan.committed_items or ()))


def _commit_text(plan: FoodResponsePlan) -> str:
    """The confirmation for a write, authored HERE (review item 3).

    This used to happen outside the response contract entirely:
    `food_ledger.render_committed()` wrote the whole reply and
    `strip_card_recitation()` then took back the parts the card was already
    showing. Old copy generated first, imperfectly stripped second — and the
    plan, which knows exactly which facts the card shows, had no say in what
    got written.

    Both steps happen here now, in one owner, in the order that makes the
    second one a consequence of the first rather than a correction to it. The
    words are unchanged: the say contract, the deterministic line and the
    follow-up whitelist all still live in `food_ledger`, which is where the
    committed numbers live, and this asks them for the text rather than being
    handed it.

    A surface with no card frame — Telegram — gets the whole thing, because
    there the sentence IS the confirmation. That is why "the card already said
    it" cannot be a property of the intent, only of the turn.
    """
    snapshot = plan.committed_snapshot
    if snapshot is None:
        # No numbers to describe — but "no snapshot" is not "nothing landed".
        # A plan can carry the committed names without the figures, and there
        # the subject is still available and still owed; "Got it." names less
        # than the plan knows. Silence remains the answer when there is
        # genuinely nothing to name.
        return _subject_line(plan) or ("" if plan.allow_no_text else "Got it.")

    from core.food_ledger import render_committed

    text = render_committed(plan.model_say or "", plan.note or "",
                            plan.follow_up or "", snapshot)
    if plan.failure_notice:
        # Never card-suppressed, and appended before the strip so the strip
        # judges it — a failure notice carries no nutrition number, so it
        # survives, and asserting that is better than exempting it by hand.
        text = f"{text}|||{plan.failure_notice}" if text else plan.failure_notice
    kept = strip_card_recitation(text, plan)
    # WHAT THE CARD TOOK, THE SENTENCE STILL OWES. Where a card renders, the
    # strip above removes every figure — which on an ordinary commit is every
    # sentence there was, leaving "". Put the subject back, without the numbers
    # the card is already carrying. A failure notice can survive the strip on
    # its own; it names what did NOT land, so it is not a subject either.
    if not _names_the_food(kept, plan):
        subject = _subject_line(plan)
        if subject:
            kept = f"{subject} {kept}".strip() if kept.strip() else subject
    return kept


def contextual_preface(plan: FoodResponsePlan) -> str:
    """Approved wording for the non-food half, or nothing.

    Reached only from `fallback()` — which means the composer has already
    failed validation twice. A deterministic renderer must NOT improvise a
    reply to distress, so this repeats only what the upstream extractor
    approved and stays silent otherwise. Saying nothing is a smaller failure
    than saying the wrong thing warmly.

    Genuinely urgent content should be routed out of the food renderer
    entirely rather than prefaced by it; that routing is upstream's call, and
    this returns the approved line if one was supplied so the reply is at
    least not blank.
    """
    ctx = plan.conversational_context
    if ctx is None:
        return ""
    if ctx.response_obligation == "briefly acknowledge":
        return (ctx.approved_acknowledgement or "").strip()
    return (ctx.approved_fallback_response
            or ctx.approved_acknowledgement or "").strip()


def fallback(plan: FoodResponsePlan) -> str:
    """Correct without sounding procedural. Reached when generation fails
    validation twice, or when no composer is available.

    A mixed turn gets the approved acknowledgement in front of the food line,
    so the deterministic path does not answer only the half it can compute.
    """
    preface = contextual_preface(plan)
    if preface:
        food = _fallback_food_only(plan)
        return " ".join(part for part in (preface, food) if part)
    return _fallback_food_only(plan)


def _fallback_food_only(plan: FoodResponsePlan) -> str:
    """The food half, unchanged — what `fallback` always was."""
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
            return (f"{_pick_opener(_REVIEW_OPENERS, items)}\n\n"
                    f"{format_items(items)}\n\nDoes that all look right?")
        described = _join([i.describe() for i in items])
        lead = _pick_opener(_REVIEW_LEADS, items).format(items=described)
        return f"{lead} Does that look right?"

    if intent is FoodResponseIntent.CLARIFY:
        # The interpretation and the question in ONE turn. Asking "does that
        # look right?" and then asking a second question afterwards spends two
        # turns on one meal and invites the user to approve an assumption they
        # were never shown.
        question = plan.clarification_question or f"Which {_held_name(plan)} was it?"
        shown = list(plan.resolved_items) + list(plan.pending_items)
        # WHAT IS WAITING ON THE ANSWER. The hold set used to be the question's
        # single staged item whatever the engine decided, so this line could
        # never be written: strict held three items and the plan reported one,
        # which is why strict and moderate rendered byte-identical replies
        # while doing opposite things. Now that `pending_items` is the engine's
        # own hold set, a turn that is holding the WHOLE meal can say so — and
        # that sentence is the only thing the user can see the mode in.
        waiting = ("" if plan.resolved_items or len(plan.pending_items) < 2
                   else " Nothing goes on the board until then.")
        if _wants_a_list(shown):
            return (f"{_pick_opener(_CLARIFY_OPENERS, shown, question)}\n\n"
                    f"{format_items(shown)}\n\n{question}{waiting}")
        if shown:
            lead = _pick_opener(_CLARIFY_LEADS, shown, question).format(
                items=_join([i.describe() for i in shown]))
            return f"{lead} {question}{waiting}"
        return f"{question}{waiting}"

    if intent is FoodResponseIntent.CONFIRM_ANSWER:
        return f"Got it, {_join([i.name for i in plan.resolved_items])}."

    if intent is FoodResponseIntent.COMMIT:
        return _commit_text(plan)

    if intent is FoodResponseIntent.PARTIAL_COMMIT:
        question = plan.clarification_question or ""
        held = _held_name(plan)
        got = _join([i.name for i in plan.committed_items])
        # A snapshot means the write really happened and its numbers are
        # available, so the confirmation is authored the same way a full
        # COMMIT's is. Without one — the ordinary case, where the plan
        # describes intent rather than a completed write — the item names are
        # all there is to say, and `_commit_text` would answer "Got it.",
        # which drops the names the user needs to see.
        base = (_commit_text(plan) if plan.committed_snapshot is not None
                else "") or f"I've got {got} in."
        tail = question or f"Still need a detail on the {held}."
        return f"{base} {tail}".strip()

    # CORRECT and UNDO carry the day exactly as COMMIT does when there IS a
    # day to carry. Both moments were rendered as COMMIT until now — an update
    # turn and an undo turn both reached `_commit_text` — so falling back to
    # the bare "Updated X." here would have made naming the intent honestly a
    # REGRESSION: the user would lose the totals they get today, on the one
    # path where the numbers just moved and they most want to see them.
    #
    # The intent is what the composer needs to phrase the moment correctly
    # ("one natural acknowledgement of what changed", not "logged"). The
    # deterministic floor stays byte-identical to what these turns render
    # today, so switching them on cannot regress a single reply.
    if intent is FoodResponseIntent.CORRECT:
        # A correction nobody could price does NOT get the day line. The whole
        # point is that the numbers did not move, and `_commit_text` reads as
        # though they did — that is the reply the user had to argue with.
        if plan.unpriced_corrections:
            names = _join(list(plan.unpriced_corrections))
            return (f"Renamed it to {names}, but I couldn't find numbers for "
                    f"it anywhere — the entry still has the old calories. "
                    f"What should it be?")
        if plan.committed_snapshot is not None:
            return _commit_text(plan)
        return f"Updated {_join([i.name for i in plan.committed_items])}."

    if intent is FoodResponseIntent.UNDO:
        if plan.committed_snapshot is not None:
            return _commit_text(plan)
        return f"Undid {_join([i.name for i in plan.committed_items])}."

    if intent is FoodResponseIntent.FAILURE:
        return (plan.failure.approved_message if plan.failure
                else "I couldn't complete that one.")

    if intent is FoodResponseIntent.COACH:
        # Silence beats generic advice — and COACH's policy allows none, so an
        # empty string satisfies its own plan.
        return ""

    # EVERY REMAINING INTENT MUST STILL SATISFY ITS OWN PLAN.
    #
    # This used to `return ""` unconditionally, and GENERAL_CONVERSATION's
    # policy is `allow_no_text=False` — so its fallback failed its own
    # `validate()` with EMPTY_NOT_ALLOWED. `compose()` returns a fallback
    # WITHOUT re-validating it, so the empty string shipped: on the one turn
    # where the composer had already failed twice, the user got nothing at all.
    #
    # It survived because the invariant test enumerated intents by hand and
    # this one was not in the list. The test is exhaustive over the enum now.
    if not INTENT_POLICY[intent][3]:        # allow_no_text
        return "Let me get back to you on that one."
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

#: THE SAME SENTENCE EVERY TIME IS A TELL. One fixed opener read as a template
#: the moment a user logged twice in a session, and this turn is common enough
#: that they see it constantly. Varied deterministically — the same meal always
#: opens the same way, so a resend or a replayed transcript is stable — and
#: keyed on the SHAPE of what follows rather than picked at random, so the
#: sentence still describes its own list.
_CLARIFY_OPENERS = (
    "Here's how I'm interpreting that:",
    "This is what I've got so far:",
    "Reading that as:",
    "Here's my read:",
)
#: The PROSE lead-ins, which is what a one- or two-item meal actually takes.
#: Varying only the list openers was half a fix: "coffee and toast with cheese"
#: is two items, so it took this branch, and the user got "I'm reading that as
#: coffee and toast with cheese." verbatim twice in consecutive turns.
_CLARIFY_LEADS = (
    "I'm reading that as {items}.",
    "Reading that as {items}.",
    "Got {items} so far.",
    "So far that's {items}.",
)
_REVIEW_LEADS = (
    "I'm reading that as {items}.",
    "About to log {items}.",
    "That's {items} going down.",
)
_REVIEW_OPENERS = (
    "Here's what I'm about to log:",
    "About to put this down:",
    "This is what goes on the board:",
    "Logging this unless you say otherwise:",
)


def _pick_opener(choices, items, salt: str = "") -> str:
    """Pick one, stably, from the items and what is being asked.

    Deterministic so the same turn never produces two different openers — a
    line that changes on retry reads as instability, not personality.

    `salt` is the question, and it is why the meal alone is not enough. Two
    clarification rounds on ONE meal are two different turns: "coffee and toast
    with cheese" was asked about twice in a row and, keyed on the meal only,
    opened with the identical sentence both times. Same meal plus same question
    is a resend and stays stable; same meal plus a new question moves on.
    """
    key = "|".join(sorted((i.name or "") for i in items)) + "|" + (salt or "")
    return choices[sum(map(ord, key)) % len(choices)] if key.strip("|") \
        else choices[0]

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
    return any(len(i.describe_bare()) > _LONG_ITEM_CHARS for i in items)


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
                if s.strip() and not _is_recitation(s)]
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
    # The remaining budget is the card's own row. Unlike an ordinary nutrition
    # number, a recommendation does not redeem it — the card already shows both
    # the remaining figures and its own "Next:" line.
    if _REMAINING_RE.search(sentence):
        return True
    if not (_NUTRIENT_NUMBER_RE.search(sentence)
            or _DAY_TOTAL_RE.search(sentence)):
        return False
    return not _RECOMMENDATION_RE.search(sentence)


# THE ROLL-CALL STRIP IS GONE, DELIBERATELY.
#
# `_is_roll_call` used to drop a sentence whose whole content was the committed
# item names — "Logged: Peanut M&Ms, Banana, Peanut Butter." above a card
# listing the same three with their macros. The reasoning was that a receipt
# printed twice is noise, and on its own terms it was right.
#
# What it missed is that it was the LAST thing naming the food. Every other
# sentence render_committed writes carries a nutrient number, so
# `_is_recitation` takes it; the name line was all that survived, and removing
# it left the empty string. Measured on the deployed path: the deterministic
# reply for a COMMIT with a card was `''`, and the composer — told by its own
# brief that the card confirms the entry — wrote a mood instead of a subject.
# What the user got for logging a meal was "You've got solid room to work
# with", which never says what was logged.
#
# So the rule is now SUPPRESS THE NUMBERS, KEEP THE SUBJECT. Figures live on
# the card and only on the card (`_NUTRIENT_CARD_FACTS`, unchanged); naming the
# food is the sentence's job and cannot be duplication, because a sentence that
# names the food stands on its own whether or not the card renders.


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


def with_context(plan: FoodResponsePlan, *, user=None,
                 day_state: str = "", messages=None) -> FoodResponsePlan:
    """Attach the day, the person and the thread to a plan before rendering.

    Every render site needs the same facts, so they are gathered in ONE place
    rather than restated per caller — the way `card_will_render` used to be
    restated per transport, and drifted.

    `messages` is the conversation in the caller's own shape (the same list the
    general lane hands the model). It is already in scope at every render site;
    it simply was never passed, which is why the composer had never seen a word
    the user said.

    Pure: returns a copy. Never raises — a plan that reaches the renderer
    without context still renders, it just reasons from less.
    """
    import dataclasses as _dc
    try:
        prefs = getattr(user, "preferences", None)
        history = plan.conversation_history
        if messages:
            turns = []
            for m in messages:
                if not isinstance(m, dict):
                    continue
                content = m.get("content")
                # Photo and tool turns arrive as content BLOCKS. They are not
                # conversation the composer can read, and flattening them would
                # put tool JSON in the thread.
                if not isinstance(content, str) or not content.strip():
                    continue
                turns.append({"role": m.get("role") or "user",
                              "content": content})
            history = tuple(turns) or history
        return _dc.replace(
            plan,
            day_state=day_state or plan.day_state,
            conversation_history=history,
            user_mode=(getattr(prefs, "food_logging_mode", "") or ""),
            user_goal=(getattr(user, "primary_goal", "") or ""))
    except Exception:                                    # pragma: no cover
        return plan


async def render_plan(plan: FoodResponsePlan) -> str:
    """THE renderer: one way an approved plan becomes text, for every intent.

    `_INTENT_BRIEF` has always carried a brief for all ten intents and
    `build_prompt` reads it generically — the composer could voice a
    clarification, a correction, an undo or a failure from the day it was
    written. It was only ever CALLED from the commit branch, so nine intents
    out of ten rendered from `fallback()`: canned openers picked by rotation,
    a bulleted item block, and the question concatenated on the end. Rotation
    is variety without intelligence, which is exactly why every clarification
    read as a form, and `format_items`' own docstring names the bullet block
    as "the shape that read as a component spec rather than a coach talking".

    Safety is identical to the commit path, because it IS the commit path's
    call: `compose_async` validates twice and returns `fallback(plan)` itself
    on any failure, so the floor is the deterministic text this replaces. With
    the composer off, this is `fallback()` and nothing else.
    """
    if not composer_enabled():
        # Still a voice profile — a deterministic renderer is a renderer, and
        # a report that only counts the model path cannot see the turns where
        # nothing spoke but the template.
        _note_voice(plan, fallback_path="composer_off")
        return fallback(plan)
    try:
        text, why = await compose_async(plan)
        if why != Reason.OK:
            logger.info("event=food_composer intent=%s outcome=fallback "
                        "reason=%s", plan.intent.value, why)
        return text
    except Exception as e:
        # A renderer may never cost the user their reply.
        logger.warning(f"render_plan fell back ({plan.intent.value}): {e}")
        _note_voice(plan, fallback_path="renderer_exception")
        return fallback(plan)


#: How many turns of the thread the composer sees. Enough to know what was just
#: said and what it is answering; not the whole history, which is the general
#: lane's job and its token budget.
_COMPOSER_HISTORY_TURNS = 6


def _composer_messages(plan: FoodResponsePlan) -> list:
    """The conversation, as messages, ending in the instruction to write.

    This was a single hard-coded `"Write the response."` — so the composer had
    never seen a word the user said. It could not refer to what was asked two
    turns ago, could not match the register of the conversation it was in, and
    could not tell a first log from the fourth in a row. "Context-aware" was in
    the persona and impossible to obey.

    The turn's own text still arrives through the prompt (`user_message`, and
    the plan's facts). What this adds is the THREAD around it, which is the
    difference between answering a message and continuing a conversation.
    """
    messages = []
    for turn in (plan.conversation_history or ())[-_COMPOSER_HISTORY_TURNS:]:
        if not isinstance(turn, dict):
            continue
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = str(turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content[:1500]})
    messages.append({"role": "user", "content": "Write the response."})
    # A model rejects two assistant turns in a row and an opening assistant
    # turn; trim rather than risk the call over a display nicety.
    while len(messages) > 1 and messages[0]["role"] == "assistant":
        messages.pop(0)
    return messages


def _note_voice(plan: "FoodResponsePlan", **fields) -> None:
    """Who spoke, on which model, at what cost — onto the ambient trace.

    Recorded from inside the voice layer rather than at its call sites,
    because the call sites do not know the two facts that matter. `retry_count`
    is invisible from outside `compose_async` (a validation retry is a second
    model call wearing the same await), and `fallback_path` is decided by
    which return branch the function takes.

    `voice_profile` is the COMPILED profile, not the raw intent. Ten intents
    map onto four briefs, and the question the report has to answer is "how
    does each brief behave" — a `commit` and a `correct` that share the micro
    brief share its latency and its failure modes, and splitting them by
    intent would put four samples in ten buckets.
    """
    try:
        from core import food_trace as _ft
        intent = getattr(plan, "intent", None)
        _ft.note(voice_profile=voice_profile_for(intent) if intent else "",
                 **fields)
    except Exception:
        pass


async def compose_async(plan: FoodResponsePlan, *, model: Optional[str] = None,
                        attempts: int = 2) -> tuple:
    """Generate → validate → retry → fall back, against the real model.

    Wraps compose() rather than duplicating it, so the validation rules cannot
    drift between the sync path (tests, fallback-only callers) and the live one.
    A model failure is not an error here: the deterministic fallback is always
    correct, just plainer.
    """
    from core.llm import chat

    async def _run(prompt: str) -> Optional[str]:
        """The model's text, or None when the CALL ITSELF failed.

        The distinction is load-bearing and was missing: an exception returned
        "" here, and "" is a legal composed reply — the COMMIT brief invites
        it ("return an empty string if there is nothing useful"), so
        `apply_policy` sets `allow_no_text` on any card-bearing turn and
        `validate("")` answers OK. An outage therefore came back as
        `("", Reason.OK)` and the user got a card with no words next to it,
        which is precisely the failure the deterministic fallback exists to
        prevent. Silence has to be a DECISION the model made, never a thing
        that happened to it.
        """
        try:
            out = await chat(_composer_messages(plan),
                             prompt, tools=False, max_tokens=200,
                             model=model or _composer_model())
            return (out or {}).get("text", "") if isinstance(out, dict) else str(out or "")
        except Exception as e:
            logger.warning(f"food composer model call failed: {e}")
            return None

    prompt = build_prompt(plan)
    last = ValidationResult(False, Reason.EMPTY_NOT_ALLOWED)
    _model = model or _composer_model()
    # Calls beyond the first on this stage. A validation retry is a second
    # model call wearing the same `await`, so from outside this function the
    # difference between a one-call turn and a three-call turn is invisible —
    # which is how stacked retries turn a bounded turn into an unbounded one
    # without anything in the log changing shape.
    # Count the CALLS and subtract one, rather than counting retries directly:
    # the loop can exit from three places and "how many did we pay for" is the
    # same arithmetic at all three, where "was that last one a retry" is a
    # different answer at each and gets one of them wrong.
    _calls = 0
    for _ in range(max(1, attempts)):
        text = await _run(prompt)
        _calls += 1
        if text is None:
            # Not a validation failure, so not worth a retry with "YOUR LAST
            # ATTEMPT FAILED" appended — there was no attempt. `chat()` has
            # already tried its own model fallback by this point; the honest
            # move now is the deterministic text.
            _note_voice(plan, voice_model=_model, retry_count=_calls - 1,
                        fallback_path="model_unavailable")
            return fallback(plan), "model_unavailable"
        last = validate(text, plan)
        if last.ok:
            _note_voice(plan, voice_model=_model, retry_count=_calls - 1)
            return text.strip(), Reason.OK
        prompt = f"{prompt}\n\nYOUR LAST ATTEMPT FAILED: {last.reason}. Fix it."
    _note_voice(plan, voice_model=_model, retry_count=_calls - 1,
                fallback_path=f"validation:{last.reason}")
    return fallback(plan), last.reason


def _composer_model() -> str:
    """The model that writes every OTHER turn.

    It used to be Haiku, on the reasoning that "the composer is phrasing an
    approved plan, not deciding anything — a large model here buys nothing".
    True about the DECISION and wrong about the writing: this is the voice the
    user reads, and it was a different, smaller one than the voice answering
    everything else in the product. Paired with a 323-token persona and no
    conversation history, that is why a logged meal read like another
    assistant had taken over the thread.

    The lane already skips the 46k-token general pass on food turns, so the
    same model here costs a fraction of what not running that pass saves.

    `FOOD_COMPOSER_MODEL` still overrides — and `DEFAULT_MODEL` is what the
    general lane resolves to, so "the same voice" stays true by construction
    rather than by two constants agreeing.
    """
    import os
    return (os.getenv("FOOD_COMPOSER_MODEL")
            or os.getenv("DEFAULT_MODEL")
            or "claude-opus-4-7")


def composer_enabled() -> bool:
    """ON by default (Danny 2026-07-26).

    It shipped off, on the reasoning that "the deterministic fallbacks are
    already correct and non-robotic". The first half held; the second did not.
    The fallbacks pick openers by ROTATION, which is variety without
    intelligence, and they assemble a bulleted block whose own docstring warns
    it reads "as a component spec rather than a coach talking". Food logging is
    the most frequent thing anyone does in this app, so the moment that felt
    most like a machine was also the moment users met most often.

    The default is flipped rather than left to the environment because leaving
    it there already failed once: `render.yaml` documented FOOD_COMPOSER=true
    for a deployment where the variable had never been set, and nothing
    anywhere reported it — the app quietly served templates for as long as
    that went unnoticed. A default that matches the intended behaviour cannot
    fail that way; FOOD_COMPOSER=false still turns it off, with no deploy.

    The floor has not moved: `render_plan` validates twice and returns the
    deterministic text on a refusal, a model failure or an outage, so the
    worst case is exactly the old behaviour plus one Haiku call.
    """
    import os
    return (os.getenv("FOOD_COMPOSER", "true") or "").strip().lower() in (
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
