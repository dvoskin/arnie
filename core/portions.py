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

# Mass/volume units → grams (volume assumes water-ish density; close enough
# for a 2x-tolerance sanity check).
_MASS_UNITS = {
    "g": 1.0, "gram": 1.0, "grams": 1.0, "gr": 1.0,
    "kg": 1000.0, "kilo": 1000.0, "kilos": 1000.0,
    "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
    "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6,
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
