"""Quantity normalization (review 2026-07-25, work order step 6).

"6 oz", "two slices", "half a bar", "a cup of rice" all have to become the
same kind of thing before any nutrient arithmetic happens. This module is the
only place that decides what a portion IS; scaling.py is the only place that
multiplies by it.

The honest part is the uncertainty. "Six thin deli slices" does not have a
mass — it has an estimate and a spread. Recording that spread is what lets the
clarification ladder ask about the portions worth asking about and stay quiet
about the ones that don't move the number. Pretending 6 slices is exactly 54 g
throws that signal away.

Food-specific piece weights live here rather than in a source adapter, because
they describe the FOOD, not the database that happens to be answering.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional

from skills.nutrition.models import (COUNT_BASIS_ESTIMATE, COUNT_BASIS_UNIT,
                                     NormalizedQuantity)

#: Mass units → grams. Exact conversions; no judgement involved.
_MASS_G = {
    "g": 1.0, "gram": 1.0, "grams": 1.0, "gm": 1.0,
    "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0,
    "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
    "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
}

#: Volume units → millilitres. Also exact.
_VOL_ML = {
    "ml": 1.0, "milliliter": 1.0, "millilitre": 1.0, "milliliters": 1.0,
    "l": 1000.0, "liter": 1000.0, "litre": 1000.0, "liters": 1000.0,
    "cup": 236.588, "cups": 236.588,
    "tbsp": 14.787, "tablespoon": 14.787, "tablespoons": 14.787,
    "tsp": 4.929, "teaspoon": 4.929, "teaspoons": 4.929,
    "floz": 29.574, "fl oz": 29.574, "fluid ounce": 29.574,
    "pint": 473.176, "pints": 473.176,
    "quart": 946.353, "quarts": 946.353,
}

#: Countable units. These carry no mass on their own — the food decides.
_COUNT_UNITS = {
    "piece", "pieces", "slice", "slices", "serving", "servings", "unit",
    "units", "item", "items", "bar", "bars", "bagel", "bagels", "egg", "eggs",
    "scoop", "scoops", "packet", "packets", "package", "packages", "can",
    "cans", "bottle", "bottles", "container", "containers", "handful",
    "handfuls", "wing", "wings", "fry", "fries", "cookie", "cookies",
    "cracker", "crackers", "chip", "chips", "nugget", "nuggets",
    # Butter's own units. Without them "a pat of butter" was not countable, so
    # it never reached `piece_weight`, had no mass, and left a zero-calorie
    # read with nothing to correct it.
    "pat", "pats", "stick", "sticks",
    # Common serving units that returned NO mass (prod 0801): "1 ear" of corn,
    # "1 clove" of garlic, "1 bun" all fell through, so a seated density was
    # discarded and the model's guess (0/low) stood.
    "ear", "ears", "clove", "cloves", "bun", "buns",
}

#: Count units that name a container or a rough helping rather than a discrete
#: unit of the food. They still take a count — "two bowls" is two of something —
#: but that count is not one of a label's servings, so scaling has to reach for
#: the estimated mass instead. Keeping them in `_COUNT_UNITS` is what gets them
#: a mass estimate at all; this set is what stops that estimate being ignored.
_VAGUE_COUNT_UNITS = {
    "scoop", "scoops", "handful", "handfuls", "bowl", "bowls", "plate",
    "plates", "bite", "bites", "spoonful", "spoonfuls", "drizzle", "drizzles",
    "splash", "splashes", "dash", "dashes",
}

#: Drinkware the user poured into, as opposed to a sealed product container. A
#: can and a bottle are the unit the label describes; a glass is not.
_VAGUE_VESSELS = {"glass", "mug", "shot"}


def is_count_unit(word: str) -> bool:
    """Whether this word names a DISCRETE item — an egg, a slice, a bar.

    Public because `core.food_response` needs it to decide whether a food is
    already the piece ("2 large pieces of eggs" — an egg IS the piece), and it
    was reaching into `_COUNT_UNITS` directly to find out. A private set is not
    an interface: it can be renamed or have its membership rules change, and
    the caller has no way to know. Asking a question beats importing a
    container.

    Singular-insensitive, which the raw set is not.
    """
    word = (word or "").strip().lower()
    if not word:
        return False
    return word in _COUNT_UNITS or _singular(word) in {
        _singular(u) for u in _COUNT_UNITS}


#: Units that name a PART of a dish rather than the dish. "A piece", "a slice",
#: "a bite" all presuppose a larger whole they were cut from — which is exactly
#: the case an as-served basis may not treat as one helping.
_PARTITIVE_UNITS = {
    "piece", "pieces", "slice", "slices", "bite", "bites", "bit", "bits",
    "sliver", "slivers", "wedge", "wedges", "square", "squares",
    "strip", "strips", "chunk", "chunks", "forkful", "forkfuls",
    "spoonful", "spoonfuls", "mouthful", "mouthfuls",
}


def is_partitive_unit(word: str) -> bool:
    """Whether this word names a PART of something rather than the whole thing.

    The distinction an as-served basis depends on and never asked for. A
    restaurant lookup returns the dish, and `PerServing(as_served=True)` says
    "one helping of it is one serving, however loosely they described the
    helping" — true for "a plate of pad thai", false for "1 piece" of an
    eight-piece roll, which is a precise description of a FRACTION. Prod
    2026-08-03: a special roll's whole-roll label scaled by count=1 committed
    460 cal for one piece, over the interpreter's own correct 130-190.

    Deliberately NOT answerable by `count_units_compatible`: that asks whether
    two panels count the same object, and it holds "piece" and "serving"
    interchangeable on purpose — "12 pieces" does answer someone who said "15
    units". Interchangeable for MATCHING is not the same as equivalent for
    SCALING, and conflating them is what let a part be priced as a whole.
    """
    return _singular((word or "").strip().lower()) in {
        _singular(u) for u in _PARTITIVE_UNITS}


def is_measured_unit(word: str) -> bool:
    """Whether this word names a MEASURE — a mass or a volume — as opposed to a
    discrete item or a vague "serving".

    Public for the same reason `is_count_unit` is, and urgently so. Callers were
    asking this question by string-matching the canonical tokens, e.g.
    `unit not in ("g", "ml")` in `skills.nutrition.candidates`, which was only
    ever correct while `_volume()` returned `unit="ml"`. When c360fad made `unit`
    carry the SURFACE token the user said ("cup", "tbsp", "glass"), every one of
    those comparisons silently changed meaning — a cup flipped from a per-100
    basis to an as-served one. The membership question belongs here, next to the
    tables that answer it, so a change to what `unit` carries cannot quietly
    re-point a caller again.
    """
    word = (word or "").strip().lower()
    if not word:
        return False
    if word in _MASS_G or word in _VOL_ML:
        return True
    s = _singular(word)
    if (s in {_singular(u) for u in _MASS_G}
            or s in {_singular(u) for u in _VOL_ML}):
        return True
    # VESSELS ARE VOLUMES TOO. "a glass", "a mug", "a bowl" carry a millilitre
    # figure via `vessel_volume` and used to reach callers as unit="ml", so
    # leaving them out here would re-create the same basis flip this predicate
    # exists to stop — just for the vessel words instead of the unit words.
    return vessel_volume(word) is not None


def _singular(word: str) -> str:
    """Crude, but correct on the words this module actually compares.

    `rstrip("s")` turned "glass" into "glas", which let every glass through as a
    countable unit. The sibilant plurals matter here because the vessels and
    containers are full of them: glasses, dishes, boxes.
    """
    if word.endswith(("ses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _unit_is_fraction(unit_word: str, food_name: str = "") -> bool:
    """Does this count name a PART of the food rather than one of the food?

    Both halves are needed and only here are both in hand. `is_partitive_unit`
    knows "piece" and "slice" presuppose a whole; `_unit_names_the_food` knows
    a TURKEY DELI SLICE is itself the product, so counting slices of it counts
    units. Same yield-to-the-food-name shape `_count_basis` uses for vessels.
    """
    return (is_partitive_unit(unit_word)
            and not _unit_names_the_food(unit_word, food_name))


def _count_basis(unit_word: str, food_name: str = "") -> str:
    """Whether a count of `unit_word` counts a label's units or a container.

    Deny-list rather than allow-list, because the countable nouns are open-ended
    and the vague ones are not: "1 burger", "1 platter" and "1 quesadilla" are
    all genuine single units of the food, and no list will ever hold them all.
    What CAN be enumerated is the measures that only ever describe a helping.

    Unless the food IS that measure. "1 bowl" of a Chipotle burrito bowl counts
    the product, not a helping of it — the vague word is the item's own name, so
    the deny-list has to yield to the food name. Same for a poke bowl, a bread
    bowl, a cheese plate.

    An empty word means the food is its own unit ("2 eggs") — also a unit count.
    """
    word = (unit_word or "").lower().strip()
    vague = word in _VAGUE_COUNT_UNITS or _singular(word) in _VAGUE_VESSELS
    if not vague:
        return COUNT_BASIS_UNIT
    food_words = {_singular(w)
                  for w in re.findall(r"[a-z]+", (food_name or "").lower())}
    if _singular(word) in food_words:
        return COUNT_BASIS_UNIT
    return COUNT_BASIS_ESTIMATE


_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "dozen": 12, "couple": 2, "few": 3, "several": 4,
}

#: Single characters that ARE a fraction. Handled with the digits rather than
#: with the words, so "1½" and "1 ½" work like "1 1/2".
_UNICODE_FRACTIONS = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
    "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 0.125, "⅜": 0.375,
    "⅝": 0.625, "⅞": 0.875,
}

#: The denominator words, singular and plural. "Two thirds" is `2 × third`,
#: which is also how "three quarters" works, so one table covers both.
_FRACTION_WORDS = {
    "half": 0.5, "halves": 0.5,
    "third": 1 / 3, "thirds": 1 / 3,
    "quarter": 0.25, "quarters": 0.25,
    "fourth": 0.25, "fourths": 0.25,
    "eighth": 0.125, "eighths": 0.125,
}

#: Words that turn a fraction word into part of a NAME. "A quarter pounder" is
#: not a quarter of a pounder. Deliberately tiny — the general rule below (a
#: bare fraction word must be followed by "of", an article, a unit, or nothing)
#: does the real work, and this covers the compound that rule would let through
#: because the next word looks like a food.
_FRACTION_COMPOUNDS = {"pounder", "pounders", "moon", "moons", "time", "times"}

#: Kept for callers that import it; the parser uses the tables above.
_FRACTIONS = dict(_UNICODE_FRACTIONS)
_FRACTIONS.update({"half": 0.5, "quarter": 0.25, "third": 1 / 3,
                   "three quarters": 0.75})

#: Typical mass per piece, with a ± spread. The spread is the point: it is
#: what the clarification ladder reads. Keys are matched as substrings of the
#: normalized food name, longest first.
PIECE_WEIGHTS_G = {
    "deli slice": (18.0, 4.0),
    "turkey slice": (18.0, 4.0),
    "bacon slice": (12.0, 4.0),
    "bread slice": (28.0, 6.0),
    "cheese slice": (21.0, 4.0),
    "pizza slice": (107.0, 35.0),
    "bagel": (98.0, 25.0),
    "egg": (50.0, 6.0),
    "french fry": (8.0, 3.0),
    "fries": (8.0, 3.0),
    "chicken wing": (32.0, 8.0),
    "chicken nugget": (17.0, 4.0),
    "cookie": (25.0, 10.0),
    "cracker": (3.0, 1.0),
    "chip": (2.0, 0.5),
    "protein bar": (60.0, 8.0),
    "granola bar": (35.0, 8.0),
    # Butter is served in units nothing else uses, and none of them were here.
    # A pat is what a restaurant brings; a stick is the US wrapper's quarter
    # pound. Without them "a pat of butter" had no mass, which is how a
    # zero-calorie read had nothing to correct it with.
    #
    # Keyed unit-first because `piece_weight` matches against
    # f"{unit_text} {food_name}" — "a pat of butter" arrives as "pat butter".
    "pat butter": (5.0, 1.5),
    "pat": (5.0, 1.5),
    "stick butter": (113.0, 4.0),
    "banana": (118.0, 20.0),
    "apple": (182.0, 35.0),
    "orange": (131.0, 25.0),
    # Serving units that priced to nothing in prod (0801). Unit-first keys because
    # `piece_weight` matches f"{unit} {food}"; bare keys catch the food alone.
    "ear corn": (90.0, 20.0), "ear": (90.0, 20.0),        # 1 medium ear ~90 g kernels
    "clove garlic": (3.0, 1.0), "clove": (3.0, 1.0),      # 1 garlic clove ~3 g
    "burger bun": (50.0, 15.0), "bun": (50.0, 15.0),      # standard bun ~50 g
    "slice": (28.0, 10.0),          # last resort for an unqualified "slice"
}

#: `_singular` (defined above) is what compares a serving panel's count unit
#: with the parser's, so "12 pieces" on a label and "15 piece" from the user
#: line up. It deliberately lives in ONE place: this module briefly carried two
#: functions of that name, and the second silently shadowed the first — which
#: turned "glass" back into "glas" and let every poured drink through as a
#: countable unit again, with no import error and no test naming either one.


#: Count units that are interchangeable with each other. A label saying
#: "12 pieces" answers a user who said "15 pieces" and equally one who said
#: "15 units"; it does NOT answer one who said "1 bar", because a bar is a
#: different object from a piece of one.
_INTERCHANGEABLE_COUNTS = {"piece", "unit", "item", "serving"}

_SERVING_MASS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(g|gram|grams)\b", re.I)

#: Recorded when a countable portion has no mass we are willing to claim.
#: Named so the resolver can DROP it when a serving panel later supplies one,
#: rather than matching the sentence by hand in two places.
MASS_UNKNOWN = "portion mass unknown"


def _serving_count(serving_text: str) -> Optional[tuple]:
    """(count, singular_unit) named by a serving panel, or None.

    LOWERCASED BEFORE COMPARING. The regex is case-insensitive but `_singular`
    is not, so "15 PIECES" became "PIECE" and missed a `_COUNT_UNITS` set that
    is lowercase — and USDA writes its panels in caps, which is where the
    uppercase ones come from. Prod 2026-08-03: the gummy-burger row carried
    serving_text "15 PIECES" and nothing could read it, so a correction to one
    burger had no count to price against.
    """
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*([a-z]+)", serving_text or "",
                             re.I):
        unit = _singular(match.group(2).lower())
        if unit in {_singular(u) for u in _COUNT_UNITS}:
            try:
                count = float(match.group(1))
            except ValueError:
                continue
            if count > 0:
                return count, unit
    return None


def serving_unit_mass(serving_text: str,
                      serving_mass_g: Optional[float] = None) -> Optional[tuple]:
    """(grams_per_unit, unit) implied by a source's OWN serving panel, or None.

    "35 g (12 pieces)" says one piece is 2.9 g — for THIS product, off THIS
    record. That is the only honest way to turn "15 pieces" of a named
    confection into a mass: `PIECE_WEIGHTS_G` describes foods, and no table of
    food-shaped averages knows that a Peanut M&M is three times a plain one.

    Nothing is derived when the panel does not say both things. A serving with
    a mass but no count, or a count but no mass, returns None and the portion
    stays unscalable — which the ask ladder can act on and a guess cannot.
    """
    text = serving_text or ""
    mass = serving_mass_g
    if mass is None:
        found = _SERVING_MASS_RE.search(text)
        mass = float(found.group(1)) if found else None
    if not mass or mass <= 0:
        return None
    count = _serving_count(text)
    if count is None:
        return None
    per_unit, unit = mass / count[0], count[1]
    if per_unit <= 0:
        return None
    return round(per_unit, 3), unit


def count_units_compatible(portion_unit: str, serving_unit: str) -> bool:
    """Whether a serving panel's count unit answers the portion's.

    Same object, or both generic counters. "15 pieces" against a panel of
    "12 pieces" is the same object. "15 pieces" against "1 bar" is not, and
    scaling one by the other is how a portion silently becomes a package.
    """
    a, b = _singular(portion_unit), _singular(serving_unit)
    if not a or not b:
        return False
    if a == b:
        return True
    return a in _INTERCHANGEABLE_COUNTS and b in _INTERCHANGEABLE_COUNTS


def unit_counts_the_pieces(unit_word: str, food_name: str,
                           panel_unit: str) -> bool:
    """Whether a count of `unit_word` counts the items a panel enumerates.

    Two ways to be the panel's item, and a panel-word match only finds the
    first. "15 PIECES" of Sour Gummy Mini Burgers enumerates gummy burgers, so
    "1 burger" counts exactly what the panel counts — but
    `count_units_compatible("burger", "piece")` is False and must stay False,
    because that predicate asks whether two PANELS count the same object and
    holds "piece" and "serving" interchangeable to do it. A product's own noun
    is not interchangeable with anything; it is the item itself, which is what
    `_unit_names_the_food` knows and nothing else does.

    Prod 2026-08-03, fe#2721: the correction "1 small snack bag" -> "1 burger"
    had a readable panel and a unit that named the food, and no code could put
    those two facts together — so the row kept the whole bag's 140 cal against
    one gummy.

    Same shape as `_unit_is_fraction` one screen up, and its near-mirror: that
    one asks whether a count names a PART of the food, this one whether it
    names ONE of the panel's items. Both need the unit and the food name
    together, which is why neither is answerable from the unit word alone.
    """
    return (count_units_compatible(unit_word, panel_unit)
            or _unit_names_the_food(unit_word, food_name))


#: Adjectives that shift a piece weight. Small effect, large in aggregate over
#: six slices — and cheap to honour.
_SIZE_MODIFIERS = {
    "thin": 0.7, "thick": 1.4, "small": 0.75, "large": 1.35, "big": 1.35,
    "extra large": 1.6, "jumbo": 1.6, "mini": 0.5, "medium": 1.0,
}

#: A leading amount, in every written form. ORDER MATTERS and it was wrong:
#: the old pattern tried `\d+(?:\.\d+)?` before `\d+/\d+`, and since regex
#: alternation is leftmost-first, "3/4 cup" matched the bare "3" and left "/4
#: cup" as the unit. Every digit fraction was silently multiplied by its
#: numerator — three quarters of a cup of rice logged as three cups.
#:
#: `whole` requires trailing WHITESPACE, which is what separates the mixed
#: number "1 1/2" from the plain fraction "1/2"; without it the whole-number
#: group eats the numerator again.
_UNI_CLASS = "".join(_UNICODE_FRACTIONS)
_QTY_RE = re.compile(
    r"^\s*(?:(?P<whole>\d+)\s+(?=[\d" + re.escape(_UNI_CLASS) + r"]))?"
    r"(?:(?P<frac>\d+\s*/\s*\d+)"
    r"|(?P<uni>[" + re.escape(_UNI_CLASS) + r"])"
    r"|(?P<dec>\d+(?:\.\d+)?))?"
    r"\s*(?P<rest>.*)$", re.I | re.S)


def _lead_words(low: str):
    """`(amount, remainder)` for a written-out amount, or None.

    Handles the shapes a person actually types: "two thirds of a cup", "half a
    bagel", "a half bagel", "one and a half bagels", "three quarters", "a
    couple of eggs". The old version checked `_FRACTIONS` by `startswith` and
    read the first token otherwise, so "two thirds" came back as 2 and
    "three-quarters" as 1 — both of them portions the user stated exactly.
    """
    words = low.split()
    if not words:
        return None

    def _frac_at(idx):
        """`(value, tokens_consumed)` if words[idx:] opens with a fraction."""
        if idx >= len(words):
            return None
        val = _FRACTION_WORDS.get(words[idx])
        if val is None:
            return None
        nxt = words[idx + 1] if idx + 1 < len(words) else ""
        if nxt in _FRACTION_COMPOUNDS:
            return None
        # A bare fraction word is a fraction when something follows that can be
        # fractioned — "of", an article, or a unit — or when nothing follows.
        # "Quarter chicken" is a menu item; "quarter of a chicken" is a portion.
        if nxt and nxt not in ("of", "a", "an") and nxt not in _COUNT_UNITS \
                and nxt not in _MASS_G and nxt not in _VOL_ML \
                and _singular(nxt) not in _VAGUE_VESSELS:
            return None
        return val, 1

    def _tail(idx):
        rest = words[idx:]
        while rest and rest[0] in ("of", "a", "an"):
            rest = rest[1:]
        return " ".join(rest)

    lead = _WORD_NUMBERS.get(words[0])
    if lead is not None:
        # "a couple of eggs", "a few slices", "a dozen wings" — the article is
        # not the amount, the word after it is. Reading the article as 1 turned
        # a couple of eggs into one egg.
        if words[0] in ("a", "an") and len(words) > 1:
            nxt = _WORD_NUMBERS.get(words[1])
            if nxt is not None:
                return nxt, _tail(2)
        # "one and a half", "two and a half"
        if words[1:4] == ["and", "a", "half"]:
            return lead + 0.5, _tail(4)
        if words[1:3] == ["and", "half"]:
            return lead + 0.5, _tail(3)
        got = _frac_at(1)
        if got is not None:
            val, used = got
            # "a half" is one half, not one times a half — the article is not a
            # multiplier even though it reads as 1 everywhere else.
            amount = val if words[0] in ("a", "an") else lead * val
            return amount, _tail(1 + used)
        return lead, _tail(1)

    got = _frac_at(0)
    if got is not None:
        val, used = got
        return val, _tail(used)
    return None


def _parse_amount(text: str) -> tuple:
    """(amount, remainder). Digits, fractions, mixed numbers and number words.

    Works on a lowercased, de-hyphenated copy — "three-quarters" and "three
    quarters" are the same portion, and the remainder is only ever used as unit
    text, which is lowercased downstream anyway. The user's own spelling is
    preserved separately (`original_user_wording`), not recovered from here.
    """
    t = (text or "").strip()
    if not t:
        return 1.0, ""
    low = t.lower().replace("-", " ")

    m = _QTY_RE.match(low)
    if m:
        whole = m.group("whole")
        frac, uni, dec = m.group("frac"), m.group("uni"), m.group("dec")
        rest = (m.group("rest") or "").strip()
        value = None
        if frac:
            try:
                num, den = frac.split("/")
                value = float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                value = None
        elif uni:
            value = _UNICODE_FRACTIONS.get(uni)
        elif dec:
            try:
                value = float(dec)
            except ValueError:
                value = None
        if value is not None:
            if whole:
                value += float(whole)
            while rest.split(" ", 1)[0] in ("of", "a", "an") and " " in rest:
                rest = rest.split(" ", 1)[1].strip()
            return value, rest
        if whole:
            return float(whole), rest

    got = _lead_words(low)
    if got is not None:
        return got
    return 1.0, low


def _head_matches(name: str, key: str) -> bool:
    """Whether `key` is the HEAD of this food name, not merely inside it.

    Plain substring matching made "eggplant parmesan" weigh 50 g (egg), a
    "chipotle bowl" weigh 2 g (chip) and "banana bread" weigh 118 g (banana).
    English compounds put the head noun last, so the key has to land at the
    end — "banana bread" is a bread, "orange chicken" is a chicken, and neither
    has a piece weight here.
    """
    words = [w.rstrip("s") for w in re.findall(r"[a-z']+", name)]
    key_words = [w.rstrip("s") for w in key.split()]
    return bool(words) and words[-len(key_words):] == key_words


def piece_weight(food_name: str, unit_text: str = "") -> Optional[tuple]:
    """(grams, uncertainty_g) for one piece of this food, or None when we have
    no basis for a guess. None is a legitimate answer — it becomes an unknown
    mass, which downstream can ask about."""
    name = f"{unit_text} {food_name}".strip().lower()
    match = None
    for key in sorted(PIECE_WEIGHTS_G, key=len, reverse=True):
        if _head_matches(name, key):
            match = PIECE_WEIGHTS_G[key]
            break
    if match is None:
        return None
    grams, spread = match
    for modifier, factor in _SIZE_MODIFIERS.items():
        if re.search(rf"\b{re.escape(modifier)}\b", name):
            grams *= factor
            spread *= factor
            break
    return round(grams, 1), round(spread, 1)


#: Density in g/ml, per portion-ontology food category. There is deliberately
#: NO default: a food absent from this table has no density we are willing to
#: claim, and the volume stays a volume. Water density applied to everything is
#: exactly the silent guess scaling.py refuses — 100 ml of popcorn is not 100 g.
#:
#: This exists because a per-100g source and a volume portion are otherwise
#: irreconcilable, and the alternative the resolver used to take — keep the
#: source's per-100g numbers unscaled — logged a teaspoon of sugar as 387
#: calories. A stated density, disclosed as an assumption, is worse than a
#: scale and far better than that.
#:
#: EVERY KEY HERE IS A SOLID OR A SEMI-SOLID, and that is not a coincidence:
#: these are `portions.food_category` names, and that ontology exists to say
#: what a HANDFUL or a CUP of a dry food weighs. `oats: 0.38` is the packing
#: density of loose rolled oats in a measuring cup. It is the right number for
#: the question that table was built to answer and the wrong one for a drink,
#: which is why beverages are keyed separately below and consulted first.
VOLUME_DENSITY_G_PER_ML = {
    "oil": 0.92, "syrup": 1.37, "sauce": 1.03, "yogurt": 1.03,
    "nut_butter": 0.95, "sugar": 0.85, "soup": 1.0, "rice": 0.67,
    "pasta": 0.59, "oats": 0.38, "cereal": 0.13, "berries": 0.63,
    "ice_cream": 0.55, "protein_powder": 0.45, "salad": 0.25,
}


#: Density in g/ml for DRINKS, keyed by name fragment rather than by portion
#: category. Longest fragment wins, and this is consulted BEFORE the category
#: table.
#:
#: Two failures made it necessary, and they are the same failure — a drink
#: being asked what a dry solid weighs:
#:
#:   • A drink with no category got no density, so a volume portion stayed a
#:     volume and a per-100g source could not be scaled at all. "240ml of
#:     milk" against USDA's own milk row resolved with the source seated and
#:     the CALORIES NULL. Not a refusal anyone could see — a glass of milk
#:     that logged as a glass of nothing. Milk, juice, broth, soda, coffee and
#:     every smoothie were in that state.
#:   • A drink that DID match a category borrowed a solid's packing density.
#:     `food_category("oat milk")` is `oats`, so 240 ml of oat milk weighed
#:     91 g and logged at 41 calories against a true ~110. The word "oat" was
#:     doing all the work and the word "milk" none.
#:
#: The values sit close to water because drinks are mostly water; what moves
#: them is dissolved sugar (juice, soda) and fat (cream, canned coconut milk).
#: They are stated to two decimals because that is the honest precision — a
#: density is an assumption, disclosed as one, and `_volume` says so on the
#: card.
BEVERAGE_DENSITY_G_PER_ML = {
    # water-like
    "water": 1.00, "sparkling water": 1.00, "seltzer": 1.00,
    "coffee": 1.00, "espresso": 1.02, "americano": 1.00, "tea": 1.00,
    "broth": 1.00, "stock": 1.00, "bone broth": 1.01, "consomme": 1.00,
    # dairy and the plant milks that stand in for it
    "milk": 1.03, "whole milk": 1.03, "skim milk": 1.03, "buttermilk": 1.03,
    "kefir": 1.03, "half and half": 1.02, "cream": 1.00, "heavy cream": 0.99,
    "oat milk": 1.03, "almond milk": 1.02, "soy milk": 1.03,
    "cashew milk": 1.02, "rice milk": 1.02, "coconut milk beverage": 1.02,
    "coconut milk": 0.98,        # canned/full-fat: fat drops it below water
    "coconut water": 1.01,
    "latte": 1.02, "cappuccino": 1.01, "macchiato": 1.02, "mocha": 1.04,
    "hot chocolate": 1.04, "chocolate milk": 1.05,
    # sugar carries the rest
    "juice": 1.05, "orange juice": 1.05, "apple juice": 1.05,
    "lemonade": 1.04, "soda": 1.04, "cola": 1.04, "soft drink": 1.04,
    "diet soda": 1.00, "sports drink": 1.03, "energy drink": 1.04,
    "kombucha": 1.01, "smoothie": 1.04, "milkshake": 1.09,
    "protein shake": 1.04, "shake": 1.04,
    # alcohol is lighter than water; sugar in the mixer pulls it back
    "beer": 1.01, "wine": 0.99, "cider": 1.01, "cocktail": 1.00,
    "liquor": 0.94, "vodka": 0.94, "whiskey": 0.94, "spirits": 0.94,
}


#: Drink vessels → (typical ml, ± ml). A vessel is not a unit of the food; it
#: is a container whose size is a property of the glass, not the juice. Kept
#: separate from the portion ontology because the ontology speaks in grams and
#: the primary quantity here is genuinely a volume.
#:
#: Bags, tubs, boxes and packets are DELIBERATELY absent. A bag of chips is 28 g
#: or 300 g depending on the bag, and inventing a middle is the package-size
#: ambiguity the clarification ladder exists to ask about.
#:
#: "cup" and "pint" are absent too, but for the opposite reason: they are exact
#: volume units and the loop above claims them first, so a row here would never
#: be reached.
VESSEL_ML = {
    "glass": (250.0, 60.0), "mug": (300.0, 70.0), "can": (355.0, 30.0),
    "bottle": (500.0, 150.0), "shot": (44.0, 5.0),
}


def vessel_volume(unit_text: str) -> Optional[tuple]:
    """(name, ml, ± ml) for a named drink vessel, or None.

    The NAME is returned because the caller cannot recover it from the phrase:
    "large glass" leads with the size word, and taking the first token recorded
    the vessel as "large". The size word belongs to the volume, not the name, so
    it is applied here — a large glass is more than a glass, which is the whole
    reason the user said it.

    Plurals count: "two bottles" is two vessels, and matching only the singular
    sent it down the unweighable-count path.
    """
    text = (unit_text or "").lower()
    for name in sorted(VESSEL_ML, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}e?s?\b", text):
            per, spread = VESSEL_ML[name]
            factor = next((f for mod, f in sorted(_SIZE_MODIFIERS.items(),
                                                  key=lambda kv: -len(kv[0]))
                           if re.search(rf"\b{re.escape(mod)}\b", text)), 1.0)
            return name, round(per * factor, 1), round(spread * factor, 1)
    return None


def beverage_density(food_name: str) -> Optional[tuple]:
    """(density, drink) for a named drink, or None.

    Longest fragment wins, for the same reason it does in `food_category`:
    "coconut milk beverage" is a carton at 1.02 and "coconut milk" is a tin at
    0.98, and a shorter match would answer for both. It is also what keeps
    "oat milk" from being read as "milk" — though the failure that made this
    function necessary was the other direction, `oats` at 0.38.
    """
    try:
        from skills.nutrition.portions import _stem_matches
    except Exception:
        return None
    name = (food_name or "").lower()
    best, best_len = None, 0
    for fragment, density in BEVERAGE_DENSITY_G_PER_ML.items():
        if len(fragment) > best_len and _stem_matches(name, fragment):
            best, best_len = (density, fragment), len(fragment)
    return best


def volume_to_grams(milliliters: float, food_name: str) -> Optional[tuple]:
    """(grams, density, what_it_matched) for this food, or None when we have no
    density for it. None means the volume stays a volume.

    Drinks are asked first. The portion ontology underneath is a table of what
    a cup of a DRY food weighs, so letting it answer for a beverage is how a
    glass of oat milk came to weigh what the same volume of loose rolled oats
    does.
    """
    drink = beverage_density(food_name)
    if drink is not None:
        density, matched = drink
        return round(milliliters * density, 1), density, matched
    try:
        from skills.nutrition.portions import food_category
    except Exception:
        return None
    category = food_category(food_name)
    density = VOLUME_DENSITY_G_PER_ML.get(category)
    if density is None:
        return None
    return round(milliliters * density, 1), density, category


def _from_ontology(raw: str, unit_text: str, food_name: str, amount: float
                   ) -> Optional[NormalizedQuantity]:
    """The portion ontology's answer for a vague measure, or None.

    normalize's own piece weights are tried first — they are per-FOOD and
    tighter. This is the tier below: category- and form-specific distributions
    for the measures people actually use ("a bowl", "a handful", "a plate"),
    which is what keeps those phrases from degrading to an unscalable count.
    """
    try:
        from skills.nutrition.portions import convert
    except Exception:
        return None
    result = convert(f"{amount} {unit_text}".strip(), food_name)
    if result.mass_equivalent_g is None or not result.distribution:
        return None
    dist = result.distribution
    return NormalizedQuantity(
        amount=amount, unit=result.unit, grams=result.mass_equivalent_g,
        # A vague measure by construction — but "1 bowl" of a burrito bowl still
        # counts the product, so the food name gets the same say it gets above.
        count=amount, count_basis=_count_basis(result.unit, food_name),
        unit_is_fraction=_unit_is_fraction(result.unit, food_name),
        unit_label=raw or f"{_fmt(amount)} {result.unit}",
        uncertainty_g=dist.uncertainty_g,
        assumptions=(f"{result.unit} estimated at "
                     f"{_fmt(result.mass_equivalent_g)}g "
                     f"({result.conversion_source})",))


#: Volume tokens whose mass the portion ontology can speak to. Only `cup` is
#: here; see _volume() for why the spoon measures are not.
_VOL_MEASURE = {"cup": "cup", "cups": "cup"}


def _ontology_mass(food_name: str, measure: str, unit_text: str,
                   amount: float) -> Optional[tuple]:
    """(grams, uncertainty_g, source) from the portion ontology, or None."""
    try:
        from skills.nutrition.portions import (detect_form, detect_modifier,
                                               distribution_for)
    except Exception:
        return None
    dist = distribution_for(measure, food_name, detect_modifier(unit_text),
                            form=(detect_form(f"{unit_text} {food_name}")
                                  or None))
    if dist is None:
        return None
    scaled = dist.scaled(amount) if amount != 1.0 else dist
    source = f"ontology:{scaled.specificity.value}:{scaled.category}"
    if scaled.form:
        source = f"{source}:{scaled.form}"
    return scaled.median_g, scaled.uncertainty_g, source


def _volume(raw: str, unit_text: str, food_name: str, amount: float, ml: float,
            token: str, vessel_note: str = "",
            count: Optional[float] = None,
            count_basis: str = "") -> NormalizedQuantity:
    """A volume portion, with a mass alongside it where we can honestly state
    one.

    DIMENSION INVARIANT (root fix 0803, prod fe#2705): `(amount, unit)` must
    denominate ONE measurement. This constructor used to return amount=<count of
    cups> beside unit="ml" — a broken pair whose f"{amount} {unit}" recombination
    ("1 cup" -> "1 ml") re-entered a later turn and honestly priced a cup of rice
    as ~0.7 g -> 1 cal (committed; the interpreter's 205 was discarded). `unit`
    now carries the SURFACE token the user said ("cup", "glass", "tbsp"); the
    canonical volume rides `milliliters`, which is what scaling reads. Every
    round-trip re-normalizes to the same grams.

    The volume is exact as a volume. The mass is not, and without it a per-100g
    source cannot answer at all — which used to mean the resolver kept the
    source's per-100g row verbatim and logged a teaspoon of sugar as 387
    calories. So: density first (a stated assumption), then the portion
    ontology for the solids a cup says little about, then volume alone.
    """
    label = raw or f"{_fmt(amount)} {token}"
    # A named vessel is itself an assumption — the user said "a glass", not
    # 250 ml — and it has to be disclosed whether or not a mass follows.
    notes = (vessel_note,) if vessel_note else ()
    bridged = volume_to_grams(ml, food_name)
    if bridged is not None:
        grams, density, category = bridged
        return NormalizedQuantity(
            amount=amount, unit=token, milliliters=ml, grams=grams,
            count=count, count_basis=count_basis, unit_label=label,
            uncertainty_g=round(grams * 0.15, 1),
            assumptions=notes + (f"{_fmt(ml)}ml estimated at {_fmt(grams)}g "
                                 f"(density {density} g/ml for {category})",))
    # A cup of a solid is a volume the food answers, not the measuring jug: a
    # cup of broccoli and a cup of nuts differ by four times. Restricted to
    # `cup` on purpose — a teaspoon and a tablespoon share the ontology's one
    # "spoonful" row, and borrowing it would make them the same portion.
    if _VOL_MEASURE.get(token) == "cup":
        solid = _ontology_mass(food_name, "cup", unit_text, amount)
        if solid is not None:
            grams, uncertainty, source = solid
            return NormalizedQuantity(
                amount=amount, unit=token, milliliters=ml, grams=grams,
                count=count, count_basis=count_basis, unit_label=label,
                uncertainty_g=uncertainty,
                assumptions=notes + (f"{_fmt(amount)} cup estimated at "
                                     f"{_fmt(grams)}g ({source})",))
    # Volume only. That is a complete answer for a per-100ml source and an
    # unknown for a per-100g one — which the resolver reports rather than
    # papering over with water density.
    return NormalizedQuantity(
        amount=amount, unit=token, milliliters=ml, count=count,
        count_basis=count_basis,
        unit_label=label, assumptions=notes)


#: Foods whose default piece weight IS a size, and which size it is. The 50 g
#: in PIECE_WEIGHTS_G is a LARGE egg, and nothing said so — the card read "2
#: eggs, 100 g" as though the user had specified. An assumption the user did
#: not make must arrive as an assumption they can correct, not as a fact. Only
#: fires when they stated no size of their own.
_ASSUMED_SIZE = {
    "egg": "large", "banana": "medium", "apple": "medium", "orange": "medium",
    "bagel": "standard", "cookie": "medium",
}

#: Size words a user actually types. Theirs — recorded, never invented.
_SIZE_WORDS = {
    "large", "big", "jumbo", "extra large", "xl", "small", "mini", "tiny",
    "medium", "regular", "standard", "grande", "venti", "tall",
    "double", "king", "personal",
}

#: How much to trust the mass, by how it was arrived at. An oz→g conversion is
#: arithmetic; a bowl is a guess with a name. These travelled as the same
#: `grams` float, which is how an estimate got presented like a measurement.
_NORM_CONFIDENCE = {
    "mass_conversion": 1.0,
    "volume_conversion": 0.95,
    "vessel": 0.6,
    "piece_weight": 0.7,
    "ontology": 0.5,
    "none": 0.2,
}


def _stated_amount(low: str):
    """The number the user ACTUALLY stated, or None when they stated none.

    `_parse_amount` defaults to 1.0 so the arithmetic has something to work
    with, and that default is indistinguishable downstream from a user who
    said "one". They are not the same claim, and only one of them is safe to
    quote back.
    """
    if not low:
        return None
    m = _QTY_RE.match(low)
    if m and (m.group("frac") or m.group("uni") or m.group("dec")
              or m.group("whole")):
        return _parse_amount(low)[0]
    if _lead_words(low) is not None:
        return _parse_amount(low)[0]
    return None


def _size_descriptor(low: str) -> str:
    """A size word the user typed — read from what FOLLOWS the amount.

    Scanning the whole string made "half a bagel" report a size descriptor of
    "half", which is the fraction, already consumed and already counted. A
    descriptor is a claim about the piece; the amount is a claim about how many.
    """
    _, rest = _parse_amount(low)
    for word in rest.replace(",", " ").split():
        if word in _SIZE_WORDS:
            return word
    return ""


def _infer_source(q: NormalizedQuantity) -> str:
    """The normalization method, read off what the construction produced.

    Only ever used as a floor for construction sites that did not declare one;
    a site that knows its own method says so and this never overrides it.
    """
    if q.normalization_source:
        return q.normalization_source
    if q.grams is None and q.milliliters is None:
        return "none"
    if q.unit == "g":
        return "mass_conversion"
    if q.milliliters is not None:
        return "vessel" if any("estimated at" in a for a in q.assumptions) \
            else "volume_conversion"
    if any("ontology:" in a for a in q.assumptions):
        return "ontology"
    if any("estimated per" in a for a in q.assumptions):
        return "piece_weight"
    return "none"


def _unit_names_the_food(unit_word: str, food_name: str) -> bool:
    """True when the unit word is part of the FOOD'S NAME, not a measure of it.

    "Cup Noodles" is a product. "1 cup" of it is one package, and converting
    that word to 236 ml gives 140 g of nothing — a mass basis with no relation
    to the 64 g package, from which every calorie, macro and micronutrient is
    then scaled. That is how a correctly identified Nissin Cup Noodles logged
    at 220 calories against 320, with the whole nutrient panel wrong beneath it.

    `_count_basis` already carries this exception for VAGUE units — "1 bowl" of
    a Chipotle burrito bowl counts the product, not a helping. But mass and
    volume conversion happens EARLIER in `normalize_quantity` and returns
    before that check is ever reached, so the exception could not apply to the
    case that needed it most.

    The discriminator is "of". In "cup of coffee" the cup measures the coffee;
    in "Cup Noodles" it names them. A measure introduces its food and a name
    modifies it, and that difference is visible in the word order without
    knowing anything about either product.
    """
    unit = _singular((unit_word or "").strip().lower())
    name = (food_name or "").strip().lower()
    if not unit or not name:
        return False
    for match in re.finditer(rf"\b{re.escape(unit)}s?\b", name):
        tail = name[match.end():].lstrip()
        if not tail.startswith("of "):
            return True
    return False


def confident_lower_mass(raw: str, food_name: str = "") -> Optional[float]:
    """The SMALLEST mass this portion could plausibly be, or None if we cannot
    say — `grams - uncertainty_g`.

    For a REFUSAL, the point estimate is the wrong number to reason from. A
    portion is often a range wearing a single figure: "some" normalizes to 80 g
    with an uncertainty of 85 g, which is to say we do not know. Judging energy
    density against 80 would let a bound refuse a food on the strength of our
    own guess about how much of it there was.

    So refusals take the most generous reading available. Below the lower bound
    there is no portion left to argue about, and "even at the smallest mass this
    could be, it carries no energy" is a claim about the FOOD rather than about
    our estimate of the portion.

    Returns None when the lower bound collapses to nothing (uncertainty >= the
    mass), which is the honest answer for a vague measure and the reason "some
    lettuce" is never refused.
    """
    q = normalize_quantity(raw, food_name)
    grams = getattr(q, "grams", None)
    if not grams or grams <= 0:
        return None
    low = float(grams) - float(getattr(q, "uncertainty_g", 0) or 0)
    return low if low > 0 else None


def normalize_quantity(raw: str, food_name: str = "") -> NormalizedQuantity:
    """A portion, plus the record of how it became one (§2, §10).

    The normalization itself is `_normalize_quantity`. This wrapper is what
    keeps the user's own words attached to the result: once a portion had been
    reduced to `amount` and `unit`, every layer downstream had to paraphrase it
    back, and "half a bagel" returned to the user as "0.5 bagel" — their
    sentence, rewritten by us, in a message that was supposed to be about
    something else.
    """
    q = _normalize_quantity(raw, food_name)
    low = (raw or "").strip().lower().replace("-", " ")
    source = _infer_source(q)
    stated = _stated_amount(low)
    descriptor = _size_descriptor(low)


    assumptions = list(q.assumptions)
    # Disclose an assumed size. The 50 g default IS a large egg; presenting it
    # without saying so is the same offence as a confident calorie number with
    # no source — it is a decision we made, wearing the user's authority.
    if not descriptor and source == "piece_weight":
        key = next((k for k in _ASSUMED_SIZE
                    if _head_matches((food_name or "").lower(), k)), "")
        if key:
            note = f"assumed {_ASSUMED_SIZE[key]} {key} — say otherwise and I'll rescale"
            if note not in assumptions:
                assumptions.append(note)

    return replace(
        q,
        original_user_wording=(raw or "").strip(),
        user_stated_amount=stated,
        user_stated_unit=_user_stated_unit(low),
        size_descriptor=descriptor,
        normalization_source=source,
        normalization_confidence=_NORM_CONFIDENCE.get(source, 0.2),
        assumptions=tuple(assumptions),
    )


def _user_stated_unit(low: str) -> str:
    """The unit word as the user wrote it, before any canonicalisation.

    `unit` is ours: "6 oz" becomes unit="g" because grams are the scaling
    currency. That is correct arithmetic and the wrong thing to quote back —
    the user said ounces.
    """
    _, rest = _parse_amount(low)
    for token in rest.split():
        if token in _SIZE_WORDS or token in ("of", "a", "an"):
            continue
        return token
    return ""


def _normalize_quantity(raw: str, food_name: str = "") -> NormalizedQuantity:
    """A portion, in a form the scaler can use — or one that honestly says it
    cannot be scaled by mass."""
    raw = (raw or "").strip()
    amount, rest = _parse_amount(raw)
    unit_text = rest.strip().lower()
    assumptions = []

    # THE UNIT MAY BE THE PRODUCT'S NAME. Checked BEFORE the conversions,
    # because they return immediately and the food-name exception downstream
    # would never be reached — which is exactly how "1 cup" of Cup Noodles
    # became 236 ml.
    # ONLY for MEASURE words. A count unit that appears in the food name is
    # already handled correctly further down — "2 cookies" of a cookie gets a
    # piece weight there, and intercepting it here would throw that away. The
    # bug is specific to units that CONVERT: a measure word silently becomes a
    # mass, and the conversion returns before anything can notice the word was
    # the product's name.
    _head = unit_text.split()[0] if unit_text.split() else ""
    # VOLUME words only. A mass unit is never a product name — nothing is
    # called "Oz", and "6 oz steak" must convert as the measurement it is.
    # Volume words are the ambiguous ones because containers get their names
    # from them: Cup Noodles, a bowl, a pint.
    _converts = _head in _VOL_ML
    if _head and _converts and _unit_names_the_food(_head, food_name):
        return NormalizedQuantity(
            amount=amount, unit=_singular(_head), count=amount,
            count_basis=COUNT_BASIS_UNIT,
            unit_label=raw or f"{_fmt(amount)} {_head}",
            assumptions=(MASS_UNKNOWN,))

    # Mass and volume are conversions, not estimates.
    for token, grams_per in _MASS_G.items():
        if re.match(rf"^{re.escape(token)}\b", unit_text):
            return NormalizedQuantity(
                amount=amount, unit="g", grams=round(amount * grams_per, 1),
                unit_label=raw or f"{amount} {token}")
    for token, ml_per in sorted(_VOL_ML.items(), key=lambda kv: -len(kv[0])):
        if re.match(rf"^{re.escape(token)}\b", unit_text):
            return _volume(raw, unit_text, food_name, amount,
                           round(amount * ml_per, 1), token)

    # A named drink vessel is a volume too — the size belongs to the glass.
    vessel = vessel_volume(unit_text)
    if vessel is not None:
        name, per, spread = vessel
        # `count` stays set: "a can" is one container as well as 355 ml, and a
        # per-serving source scales by the count. Dropping it turned every
        # canned food with a per-serving label into an unscalable portion.
        #
        # But only a SEALED container is the label's unit. A glass is drinkware
        # the user poured into, so its count is an estimate of a helping and the
        # volume is the honest currency.
        basis = _count_basis(name, food_name)
        surface = next((t for t in unit_text.split()
                        if t.rstrip("s") == name), name)
        return _volume(raw, unit_text, food_name, amount,
                       round(amount * per, 1), name, count=amount,
                       count_basis=basis,
                       vessel_note=(f"{surface} estimated at {_fmt(per)}ml "
                                    f"(± {_fmt(spread)}ml)"))

    # Countable: the mass, if we can estimate it, comes from the FOOD.
    # The count word is not always first — "6 thin slices" leads with a size
    # modifier, and reading only the head token drops the whole portion.
    tokens = unit_text.split()
    head = next((t for t in tokens if t in _COUNT_UNITS),
                tokens[0] if tokens else "")
    # A food is often its own unit — "1 banana", "2 bagels", "3 wings". The
    # count-unit list can never be complete, so a unit word that appears in
    # the food name is a count of that food.
    food_words = set(re.findall(r"[a-z]+", (food_name or "").lower()))
    food_as_unit = bool(tokens) and any(
        t.rstrip("s") in {w.rstrip("s") for w in food_words} for t in tokens)
    countable = head in _COUNT_UNITS or food_as_unit or not unit_text
    if countable:
        est = piece_weight(food_name, unit_text)
        if est is None:
            # No per-food piece weight. Before giving up, ask the portion
            # ontology — "a handful", "a scoop", "a bowl" are distributions it
            # knows by category and form.
            from_ontology = _from_ontology(raw, unit_text, food_name, amount)
            if from_ontology is not None:
                return from_ontology
            # Still nothing. Say so — a made-up gram figure here is exactly the
            # kind of confident wrong number this layer exists to prevent.
            return NormalizedQuantity(
                amount=amount, unit=(head or "serving"), count=amount,
                count_basis=_count_basis(head, food_name),
                unit_is_fraction=_unit_is_fraction(head, food_name),
                unit_label=raw or f"{amount} {head or 'serving'}",
                assumptions=(MASS_UNKNOWN,))
        grams, spread = est
        assumptions.append(
            f"{_fmt(amount)} × {_fmt(grams)}g estimated per "
            f"{head or 'piece'}")
        return NormalizedQuantity(
            amount=amount, unit=(head or "piece"),
            grams=round(amount * grams, 1), count=amount,
            count_basis=_count_basis(head, food_name),
                unit_is_fraction=_unit_is_fraction(head, food_name),
            unit_label=raw or f"{amount} {head or 'piece'}",
            uncertainty_g=round(amount * spread, 1),
            assumptions=tuple(assumptions))

    # An unrecognized unit. It may still be a measure the ontology knows —
    # "a bowl", "a plate", "some" are not count units and have no piece weight,
    # but they do have distributions.
    from_ontology = _from_ontology(raw, unit_text, food_name, amount)
    if from_ontology is not None:
        return from_ontology
    return NormalizedQuantity(
        amount=amount, unit=head or "serving", count=amount,
        count_basis=_count_basis(head, food_name),
                unit_is_fraction=_unit_is_fraction(head, food_name),
        unit_label=raw or food_name,
        assumptions=("unrecognized unit, treated as a serving",))


def _fmt(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"
