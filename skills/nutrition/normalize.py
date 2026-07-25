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
VOLUME_DENSITY_G_PER_ML = {
    "oil": 0.92, "syrup": 1.37, "sauce": 1.03, "yogurt": 1.03,
    "nut_butter": 0.95, "sugar": 0.85, "soup": 1.0, "rice": 0.67,
    "pasta": 0.59, "oats": 0.38, "cereal": 0.13, "berries": 0.63,
    "ice_cream": 0.55, "protein_powder": 0.45, "salad": 0.25,
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
    """(ml, ± ml) for a named drink vessel, or None. Plurals count: "two
    bottles" is two vessels, and matching only the singular sent it down the
    unweighable-count path."""
    text = (unit_text or "").lower()
    for name in sorted(VESSEL_ML, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}e?s?\b", text):
            return VESSEL_ML[name]
    return None


def volume_to_grams(milliliters: float, food_name: str) -> Optional[tuple]:
    """(grams, density, category) for this food, or None when we have no
    density for it. None means the volume stays a volume."""
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
        count=amount, unit_label=raw or f"{_fmt(amount)} {result.unit}",
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
            count: Optional[float] = None) -> NormalizedQuantity:
    """A volume portion, with a mass alongside it where we can honestly state
    one.

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
            amount=amount, unit="ml", milliliters=ml, grams=grams,
            count=count, unit_label=label,
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
                amount=amount, unit="ml", milliliters=ml, grams=grams,
                count=count, unit_label=label, uncertainty_g=uncertainty,
                assumptions=notes + (f"{_fmt(amount)} cup estimated at "
                                     f"{_fmt(grams)}g ({source})",))
    # Volume only. That is a complete answer for a per-100ml source and an
    # unknown for a per-100g one — which the resolver reports rather than
    # papering over with water density.
    return NormalizedQuantity(
        amount=amount, unit="ml", milliliters=ml, count=count,
        unit_label=label, assumptions=notes)


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
            return _volume(raw, unit_text, food_name, amount,
                           round(amount * ml_per, 1), token)

    # A named drink vessel is a volume too — the size belongs to the glass.
    vessel = vessel_volume(unit_text)
    if vessel is not None:
        per, spread = vessel
        name = unit_text.split()[0]
        # `count` stays set: "a can" is one container as well as 355 ml, and a
        # per-serving source scales by the count. Dropping it turned every
        # canned food with a per-serving label into an unscalable portion.
        return _volume(raw, unit_text, food_name, amount,
                       round(amount * per, 1), name, count=amount,
                       vessel_note=(f"{name} estimated at {_fmt(per)}ml "
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

    # An unrecognized unit. It may still be a measure the ontology knows —
    # "a bowl", "a plate", "some" are not count units and have no piece weight,
    # but they do have distributions.
    from_ontology = _from_ontology(raw, unit_text, food_name, amount)
    if from_ontology is not None:
        return from_ontology
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
