"""Canonical portion weights — a sanity net for the grams-from-calories trick.

food_intelligence backs a portion's gram weight out of the LLM's calories and
the database's per-100g density (grams = cal / cal_100 * 100). That's robust to
unit chaos, but a bad calorie estimate silently becomes a bad portion — and
every derived nutrient (fiber/sugar/sodium/micros) scales with it.

This module answers "what SHOULD that quantity roughly weigh?" from the stated
quantity string. When the backed-out grams and the expected grams disagree
wildly, the analysis surfaces a portion-check note so the model can ask or
self-correct — we never silently mutate the logged values (calories stay the
anchor by design).

Weights are USDA FoodData Central medians for common household measures.
Deliberately small and maintainable — generic staples only; branded items go
through label enrichment where portions are printed on the box.
"""
from __future__ import annotations

import re
from typing import Optional

# True mass units → grams. These are GROUND TRUTH for a food's weight.
_TRUE_MASS_UNITS = {
    "g": 1.0, "gram": 1.0, "grams": 1.0, "gr": 1.0,
    "kg": 1000.0, "kilo": 1000.0, "kilos": 1000.0,
    "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
    "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6,
}
# Mass + volume → grams (volume assumes water-ish density; only close enough for
# the 2x-tolerance sanity check, NOT for ground-truth calorie computation).
_MASS_UNITS = {
    **_TRUE_MASS_UNITS,
    "ml": 1.0, "milliliter": 1.0, "milliliters": 1.0,
    "l": 1000.0, "liter": 1000.0, "liters": 1000.0,
}

# Grams per cup, by food keyword (cooked where ambiguous — that's what people
# log). "default" covers unlisted foods at a middle-of-the-road density.
_CUP_GRAMS = {
    "rice": 186, "oat": 81, "oatmeal": 234, "yogurt": 245, "milk": 244,
    "berr": 148, "strawberr": 152, "blueberr": 148, "broccoli": 91,
    "spinach": 30, "pasta": 140, "quinoa": 185, "bean": 172, "lentil": 198,
    "cottage": 226, "egg white": 243, "granola": 111, "cereal": 40,
    "soup": 245, "default": 200,
}

# Grams per slice, by food keyword.
_SLICE_GRAMS = {
    "bread": 30, "toast": 30, "pizza": 107, "cheese": 21, "ham": 28,
    "turkey": 28, "bacon": 12, "tomato": 20, "avocado": 30, "default": 30,
}

# Grams per scoop, by food keyword.
_SCOOP_GRAMS = {
    "protein": 31, "whey": 31, "casein": 34, "creatine": 5, "ice cream": 66,
    "default": 31,
}

# Grams per PIECE of the food itself ("1 apple", "2 eggs", "a banana") —
# USDA medium sizes.
_PIECE_GRAMS = {
    "apple": 182, "banana": 118, "orange": 131, "peach": 150, "pear": 178,
    "plum": 66, "kiwi": 75, "mango": 336, "avocado": 150, "egg": 50,
    "potato": 213, "sweet potato": 130, "carrot": 61, "cucumber": 301,
    "tomato": 123, "bell pepper": 119, "onion": 110, "bagel": 105,
    "tortilla": 45, "pita": 60, "croissant": 57, "muffin": 113,
    "pancake": 38, "waffle": 75, "chicken breast": 174, "chicken thigh": 116,
    "drumstick": 105, "burger": 226, "hot dog": 76, "sausage": 68,
    "meatball": 30, "shrimp": 12, "date": 24, "fig": 50,
}

_UNIT_TABLES = {
    "cup": _CUP_GRAMS, "cups": _CUP_GRAMS,
    "slice": _SLICE_GRAMS, "slices": _SLICE_GRAMS,
    "scoop": _SCOOP_GRAMS, "scoops": _SCOOP_GRAMS,
}
_SPOON_GRAMS = {"tbsp": 15.0, "tablespoon": 15.0, "tablespoons": 15.0,
                "tsp": 5.0, "teaspoon": 5.0, "teaspoons": 5.0}

_COUNT_WORDS = {"a": 1.0, "an": 1.0, "one": 1.0, "two": 2.0, "three": 3.0,
                "four": 4.0, "five": 5.0, "six": 6.0, "half": 0.5}


def _lookup(table: dict, food_name: str) -> Optional[float]:
    n = (food_name or "").lower()
    best = None
    for key, grams in table.items():
        if key != "default" and key in n and (best is None or len(key) > best[0]):
            best = (len(key), float(grams))          # longest key wins ("oatmeal" > "oat")
    if best:
        return best[1]
    return float(table["default"]) if "default" in table else None


def mass_grams(quantity: str) -> Optional[float]:
    """Grams ONLY when the quantity is an explicit mass/weight ("200g", "6 oz",
    "1.5 lb", "150 ml") — the ground-truth case where the portion is KNOWN, not
    estimated. Returns None for counts, cups, pieces, or vague amounts, where the
    gram weight is itself a guess and shouldn't override the LLM's estimate.

    Used to decide when to compute a food's calories FORWARD from grams × the
    database per-100g density (killing the LLM's ~19% calorie undercount) instead
    of backing grams out of the LLM's calories.
    """
    q = (quantity or "").strip().lower().replace("×", "x")
    if not q:
        return None
    # A bare mass: optional count/fraction then a mass unit, nothing trailing.
    m = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+)\s*([a-z]+)$", q)      # "1/2 lb"
    if m:
        count, unit = float(m.group(1)) / float(m.group(2)), m.group(3)
    else:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-z]+)$", q)              # "200g", "6 oz"
        if not m:
            return None
        count, unit = float(m.group(1)), m.group(2)
    grams = _TRUE_MASS_UNITS.get(unit)
    return count * grams if grams else None


def expected_grams(food_name: str, quantity: str) -> Optional[float]:
    """Rough expected gram weight for a stated quantity of a food, or None when
    the quantity is too vague to check ("some", "a serving", "1 order")."""
    q = (quantity or "").strip().lower().replace("×", "x")
    if not q:
        return None
    # count: leading number ("2", "1.5", "1/2") or a count word ("a", "two")
    count = 1.0
    m = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+)\s*(.*)$", q)      # "1/2 cup"
    if m:
        count, rest = float(m.group(1)) / float(m.group(2)), m.group(3)
    else:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*x?\s*(.*)$", q)          # "2 cups", "200g"
        if m:
            count, rest = float(m.group(1)), m.group(2)
        else:
            parts = q.split(None, 1)
            if parts and parts[0] in _COUNT_WORDS:
                count, rest = _COUNT_WORDS[parts[0]], (parts[1] if len(parts) > 1 else "")
            else:
                rest = q
    rest = rest.strip()
    unit = rest.split()[0] if rest else ""

    if unit in _MASS_UNITS:
        return count * _MASS_UNITS[unit]
    if unit in _SPOON_GRAMS:
        return count * _SPOON_GRAMS[unit]
    if unit in _UNIT_TABLES:
        per = _lookup(_UNIT_TABLES[unit], food_name)
        return count * per if per else None

    # No unit → the count refers to pieces of the food itself ("2 eggs",
    # "1 apple"). Only check foods we have a canonical piece weight for.
    n = (food_name or "").lower()
    best = None
    for key, grams in _PIECE_GRAMS.items():
        if key in n and (best is None or len(key) > best[0]):
            best = (len(key), float(grams))
    return count * best[1] if best else None


def portion_check(food_name: str, quantity: str,
                  implied_grams: Optional[float]) -> Optional[str]:
    """Compare the grams implied by calories/density against the stated
    quantity's canonical weight. Returns a short warning string when they
    disagree by more than ~2x either way, else None."""
    if not implied_grams or implied_grams <= 0:
        return None
    exp = expected_grams(food_name, quantity)
    if not exp or exp <= 0:
        return None
    ratio = implied_grams / exp
    if ratio > 2.2 or ratio < 0.45:
        return (f"portion check: calories imply ~{implied_grams:.0f}g but "
                f"'{quantity}' is typically ~{exp:.0f}g — double-check the "
                f"amount or calorie estimate")
    return None


# ── V2 accuracy capability (NUTRITION_ACCURACY_V2) ───────────────────────────
# Portion PRIOR, cooking YIELD, added FAT. Three named, auditable tables that
# replace three silent failures: grams from the model's low guess, a raw density
# for a cooked food, and an added fat nobody counted. Family-level medians, never
# per-food fudge; longest-keyword-wins like the tables above.

# Typical AS-EATEN serving mass (g) for a bare food name with no stated amount.
SERVING_PRIOR_G = {
    "skirt steak": 200, "ribeye": 225, "sirloin": 225, "steak": 200,
    "chicken breast": 170, "chicken thigh": 150, "chicken": 140,
    "salmon": 170, "tuna": 140, "shrimp": 85, "pork chop": 170,
    "ground beef": 113, "turkey": 120, "fish": 150,
    "almond": 28, "nut": 28, "peanut": 28, "walnut": 28, "cashew": 28,
    "rice": 200, "pasta": 200, "quinoa": 185, "potato": 173, "bean": 130,
    "salad": 200, "broccoli": 90, "vegetable": 90,
    "egg": 100, "oatmeal": 234, "yogurt": 170, "cheese": 30,
}

# Raw -> cooked per-100g CONCENTRATION (cooking drives off water). Applied only
# to a RAW reference density when the food is normally eaten cooked and no cooked
# row was seated. USDA raw-vs-cooked family medians.
_COOKING_YIELD = {
    "beef": 1.30, "steak": 1.30, "ribeye": 1.30, "sirloin": 1.30,
    "skirt": 1.30, "pork": 1.28, "lamb": 1.28,
    "chicken": 1.25, "turkey": 1.25, "poultry": 1.25,
    "fish": 1.20, "salmon": 1.20, "shrimp": 1.20,
}

# Calories a NAMED added fat / sauce / marinade contributes — not in any base
# row, and USDA never carries it. An explicit, quantified term, not a multiplier.
_ADDED_FAT_CAL = {
    "in butter": 100, "with butter": 100, "butter": 100,
    "olive oil": 120, "in oil": 120, "with oil": 120, "fried in": 120,
    "with ranch": 145, "ranch": 145, "blue cheese": 150, "caesar": 160,
    "vinaigrette": 90, "with dressing": 120, "dressing": 120,
    "with mayo": 90, "mayo": 90, "aioli": 100, "marinated": 60, "marinade": 60,
    "teriyaki": 70, "bbq sauce": 70, "gravy": 80, "cream sauce": 130, "alfredo": 180,
}

_ADDED_FAT_NEGATIONS = ("no dressing", "without", "undressed", "no sauce",
                        "no butter", "no oil", "dry", "plain")


def portion_prior(food_name: str) -> Optional[float]:
    """Typical as-eaten serving mass (g) for a bare food name, or None. The
    prior that replaces the model's calorie guess as the portion of an
    un-weighed whole food."""
    return _lookup(SERVING_PRIOR_G, food_name)


def cooking_yield(food_name: str) -> float:
    """Raw->cooked per-100g factor for a food eaten cooked, else 1.0."""
    return _lookup({**_COOKING_YIELD, "default": 1.0}, food_name) or 1.0


def added_fat_calories(text: str) -> tuple[int, str]:
    """(calories, label) for a NAMED added fat/sauce in the food text, else
    (0, ''). Longest phrase wins; a stated omission ('no dressing') scores 0."""
    t = (text or "").lower()
    if any(neg in t for neg in _ADDED_FAT_NEGATIONS):
        return 0, ""
    best = None
    for phrase, cal in _ADDED_FAT_CAL.items():
        if phrase in t and (best is None or len(phrase) > len(best[0])):
            best = (phrase, cal)
    return (best[1], best[0]) if best else (0, "")
