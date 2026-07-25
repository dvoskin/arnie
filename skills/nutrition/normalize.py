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
from typing import Optional

from skills.nutrition.models import NormalizedQuantity

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
}

_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "dozen": 12, "couple": 2, "few": 3, "several": 4,
}

_FRACTIONS = {
    "half": 0.5, "quarter": 0.25, "third": 1 / 3, "three quarters": 0.75,
    "½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3,
}

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
    "banana": (118.0, 20.0),
    "apple": (182.0, 35.0),
    "orange": (131.0, 25.0),
    "slice": (28.0, 10.0),          # last resort for an unqualified "slice"
}

#: Adjectives that shift a piece weight. Small effect, large in aggregate over
#: six slices — and cheap to honour.
_SIZE_MODIFIERS = {
    "thin": 0.7, "thick": 1.4, "small": 0.75, "large": 1.35, "big": 1.35,
    "extra large": 1.6, "jumbo": 1.6, "mini": 0.5, "medium": 1.0,
}

_QTY_RE = re.compile(
    r"^\s*(?P<num>\d+(?:\.\d+)?|\d+\s*/\s*\d+)?\s*(?P<rest>.*)$", re.I)


def _word_amount(text: str) -> Optional[float]:
    t = text.strip().lower()
    for phrase, val in _FRACTIONS.items():
        if t.startswith(phrase):
            return val
    first = t.split()[0] if t.split() else ""
    return _WORD_NUMBERS.get(first)


def _parse_amount(text: str) -> tuple:
    """(amount, remainder). Handles digits, fractions and number words."""
    t = (text or "").strip().lower()
    if not t:
        return 1.0, ""
    m = _QTY_RE.match(t)
    raw = (m.group("num") or "").strip() if m else ""
    rest = (m.group("rest") or "").strip() if m else t
    if raw:
        if "/" in raw:
            try:
                num, den = raw.split("/")
                return float(num) / float(den), rest
            except (ValueError, ZeroDivisionError):
                return 1.0, rest
        try:
            return float(raw), rest
        except ValueError:
            return 1.0, rest
    word = _word_amount(t)
    if word is not None:
        parts = t.split()
        for phrase in _FRACTIONS:
            if t.startswith(phrase):
                return word, t[len(phrase):].strip().lstrip("aof ").strip()
        return word, " ".join(parts[1:]).strip()
    return 1.0, t


def piece_weight(food_name: str, unit_text: str = "") -> Optional[tuple]:
    """(grams, uncertainty_g) for one piece of this food, or None when we have
    no basis for a guess. None is a legitimate answer — it becomes an unknown
    mass, which downstream can ask about."""
    name = f"{unit_text} {food_name}".strip().lower()
    match = None
    for key in sorted(PIECE_WEIGHTS_G, key=len, reverse=True):
        if key in name:
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


def normalize_quantity(raw: str, food_name: str = "") -> NormalizedQuantity:
    """A portion, in a form the scaler can use — or one that honestly says it
    cannot be scaled by mass."""
    raw = (raw or "").strip()
    amount, rest = _parse_amount(raw)
    unit_text = rest.strip().lower()
    assumptions = []

    # Mass and volume are conversions, not estimates.
    for token, grams_per in _MASS_G.items():
        if re.match(rf"^{re.escape(token)}\b", unit_text):
            return NormalizedQuantity(
                amount=amount, unit="g", grams=round(amount * grams_per, 1),
                unit_label=raw or f"{amount} {token}")
    for token, ml_per in sorted(_VOL_ML.items(), key=lambda kv: -len(kv[0])):
        if re.match(rf"^{re.escape(token)}\b", unit_text):
            return NormalizedQuantity(
                amount=amount, unit="ml",
                milliliters=round(amount * ml_per, 1),
                unit_label=raw or f"{amount} {token}")

    # Countable: the mass, if we can estimate it, comes from the FOOD.
    # The count word is not always first — "6 thin slices" leads with a size
    # modifier, and reading only the head token drops the whole portion.
    tokens = unit_text.split()
    head = next((t for t in tokens if t in _COUNT_UNITS),
                tokens[0] if tokens else "")
    countable = head in _COUNT_UNITS or not unit_text
    if countable:
        est = piece_weight(food_name, unit_text)
        if est is None:
            # No basis for a mass. Say so — a made-up gram figure here is
            # exactly the kind of confident wrong number this layer exists to
            # prevent.
            return NormalizedQuantity(
                amount=amount, unit=(head or "serving"), count=amount,
                unit_label=raw or f"{amount} {head or 'serving'}",
                assumptions=("portion mass unknown",))
        grams, spread = est
        assumptions.append(
            f"{_fmt(amount)} × {_fmt(grams)}g estimated per "
            f"{head or 'piece'}")
        return NormalizedQuantity(
            amount=amount, unit=(head or "piece"),
            grams=round(amount * grams, 1), count=amount,
            unit_label=raw or f"{amount} {head or 'piece'}",
            uncertainty_g=round(amount * spread, 1),
            assumptions=tuple(assumptions))

    # An unrecognized unit is a count of something we can't weigh.
    return NormalizedQuantity(
        amount=amount, unit=head or "serving", count=amount,
        unit_label=raw or food_name,
        assumptions=("unrecognized unit, treated as a serving",))


def _fmt(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"
