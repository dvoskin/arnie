"""Category-aware portion ontology (build order 16, 17).

"A handful" is not a number. It is a distribution, and which distribution
depends entirely on the food: a handful of blueberries is ~45 g, a handful of
almonds is ~30 g, and a handful of popcorn is ~8 g. Mapping all three to one
constant produces a number that is confidently wrong in two cases out of
three.

Same for every other vague measure people actually use — a slice of turkey and
a slice of pizza differ by a factor of six; a tablespoon of peanut butter and
a spoonful of rice differ by half.

So portions resolve through a distribution with a median, a plausible range and
a confidence, and the RANGE is the useful part: it is what the materiality
score reads to decide whether the vagueness is worth a question. Collapsing to
the median throws away the only signal that says "ask about this one".

The second half is conversion honesty. Count-to-mass is never exact unless the
product defines a unit weight. "6 deli slices" records count=6, an estimated
mass, and a confidence — not a bare 54 g that reads like a measurement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional


class UnitKind(str, Enum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"
    PACKAGE = "package"
    SERVING = "serving"
    FRACTION = "fraction"
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True)
class QuantityDistribution:
    """What a vague portion could plausibly be.

    `lower_g`/`upper_g` are not error bars on a measurement — nothing was
    measured. They are the range of portions a reasonable person might have
    meant, which is why they drive the ask decision rather than being hidden.
    """
    median_g: float
    lower_g: float
    upper_g: float
    confidence: float = 0.6
    category: str = ""

    @property
    def spread_g(self) -> float:
        return round(self.upper_g - self.lower_g, 1)

    @property
    def uncertainty_g(self) -> float:
        """Half-spread, for symmetric use by the scaler."""
        return round(self.spread_g / 2.0, 1)

    def scaled(self, count: float) -> "QuantityDistribution":
        """N of them. Spread scales with count — six uncertain slices are six
        times as uncertain as one, which is exactly why "6 thin slices" earns a
        question that "1 thin slice" does not."""
        return replace(self, median_g=round(self.median_g * count, 1),
                       lower_g=round(self.lower_g * count, 1),
                       upper_g=round(self.upper_g * count, 1))


@dataclass(frozen=True)
class ConversionResult:
    """A normalized amount, with how much to trust the mass.

    `conversion_confidence` of 1.0 means arithmetic (oz → g). Anything less
    means we estimated, and `conversion_source` says on what basis.
    """
    amount: float
    unit: str
    unit_kind: UnitKind
    mass_equivalent_g: Optional[float] = None
    conversion_confidence: float = 0.0
    conversion_source: str = ""
    distribution: Optional[QuantityDistribution] = None
    count: Optional[float] = None

    @property
    def is_exact(self) -> bool:
        return self.conversion_confidence >= 0.999


# ── the ontology ──────────────────────────────────────────────────────────────
#: (median_g, lower_g, upper_g, confidence) per (measure, food category).
#: Sourced from typical serving references and deliberately wide where real
#: variation is wide. Wrong-but-narrow is worse than right-but-wide: a narrow
#: range suppresses the question that would have fixed it.
PORTION_ONTOLOGY = {
    "handful": {
        "berries":      (45.0, 30.0, 65.0, 0.68),
        "nuts":         (30.0, 20.0, 42.0, 0.70),
        "chips":        (28.0, 18.0, 40.0, 0.62),
        "popcorn":      (8.0, 5.0, 14.0, 0.60),
        "cereal":       (30.0, 20.0, 45.0, 0.60),
        "greens":       (25.0, 15.0, 40.0, 0.55),
        "dried_fruit":  (35.0, 22.0, 50.0, 0.62),
        "default":      (35.0, 20.0, 55.0, 0.50),
    },
    "slice": {
        "bread":        (28.0, 22.0, 36.0, 0.78),
        "deli_meat":    (18.0, 12.0, 26.0, 0.70),
        "cheese":       (21.0, 15.0, 28.0, 0.75),
        "pizza":        (107.0, 75.0, 145.0, 0.60),
        "cake":         (80.0, 55.0, 120.0, 0.55),
        "bacon":        (12.0, 8.0, 17.0, 0.72),
        "tomato":       (20.0, 14.0, 28.0, 0.70),
        "default":      (28.0, 15.0, 60.0, 0.45),
    },
    "spoonful": {
        "nut_butter":   (16.0, 12.0, 22.0, 0.70),
        "rice":         (35.0, 25.0, 48.0, 0.62),
        "sauce":        (18.0, 12.0, 26.0, 0.62),
        "yogurt":       (30.0, 22.0, 42.0, 0.65),
        "sugar":        (12.0, 8.0, 16.0, 0.72),
        "default":      (20.0, 12.0, 32.0, 0.50),
    },
    "scoop": {
        "protein_powder": (32.0, 28.0, 38.0, 0.80),
        "ice_cream":      (66.0, 50.0, 90.0, 0.62),
        "rice":           (90.0, 65.0, 120.0, 0.58),
        "default":        (45.0, 25.0, 75.0, 0.45),
    },
    "drizzle": {
        "oil":          (7.0, 4.0, 12.0, 0.58),
        "sauce":        (12.0, 6.0, 20.0, 0.55),
        "syrup":        (15.0, 8.0, 25.0, 0.55),
        "default":      (10.0, 5.0, 18.0, 0.45),
    },
    "bite": {
        "default":      (20.0, 10.0, 35.0, 0.45),
    },
    "some": {
        # Deliberately very wide. "Some" carries almost no information, and a
        # confident narrow range here is the fake precision this module exists
        # to refuse.
        "default":      (80.0, 30.0, 200.0, 0.30),
    },
    "little": {
        "default":      (30.0, 12.0, 60.0, 0.35),
    },
    "bowl": {
        "cereal":       (45.0, 30.0, 70.0, 0.55),
        "soup":         (300.0, 220.0, 420.0, 0.60),
        "rice":         (200.0, 140.0, 280.0, 0.58),
        "salad":        (150.0, 100.0, 250.0, 0.50),
        "default":      (250.0, 150.0, 400.0, 0.40),
    },
    "plate": {
        "default":      (400.0, 250.0, 650.0, 0.35),
    },
}

#: Food name fragments → ontology category. Longest match wins, so
#: "peanut butter" beats "butter".
FOOD_CATEGORIES = {
    "blueberr": "berries", "raspberr": "berries", "strawberr": "berries",
    "blackberr": "berries", "grape": "berries", "cherr": "berries",
    "almond": "nuts", "cashew": "nuts", "walnut": "nuts", "pecan": "nuts",
    "peanut": "nuts", "pistachio": "nuts", "nut": "nuts",
    "peanut butter": "nut_butter", "almond butter": "nut_butter",
    "nut butter": "nut_butter", "tahini": "nut_butter",
    "potato chip": "chips", "tortilla chip": "chips", "chip": "chips",
    "popcorn": "popcorn",
    "cereal": "cereal", "granola": "cereal", "oat": "cereal",
    "spinach": "greens", "kale": "greens", "lettuce": "greens",
    "arugula": "greens", "salad green": "greens",
    "raisin": "dried_fruit", "dried apricot": "dried_fruit",
    "date": "dried_fruit", "dried": "dried_fruit",
    "bread": "bread", "toast": "bread", "bagel": "bread", "bun": "bread",
    "turkey": "deli_meat", "ham": "deli_meat", "salami": "deli_meat",
    "deli": "deli_meat", "prosciutto": "deli_meat", "bologna": "deli_meat",
    "cheese": "cheese", "cheddar": "cheese", "provolone": "cheese",
    "pizza": "pizza", "cake": "cake", "bacon": "bacon", "tomato": "tomato",
    "rice": "rice", "yogurt": "yogurt", "sugar": "sugar",
    "protein powder": "protein_powder", "whey": "protein_powder",
    "ice cream": "ice_cream", "gelato": "ice_cream",
    "olive oil": "oil", "oil": "oil", "syrup": "syrup", "honey": "syrup",
    "sauce": "sauce", "dressing": "sauce", "salsa": "sauce",
    "soup": "soup", "stew": "soup", "salad": "salad",
}

#: The vague measures we recognize, longest first so "small handful" resolves
#: to "handful" rather than failing.
_MEASURE_PATTERNS = (
    ("handful", r"\bhand\s?fuls?\b"),
    ("spoonful", r"\b(?:spoon\s?fuls?|table\s?spoons?|tbsp|tea\s?spoons?|tsp)\b"),
    ("scoop", r"\bscoops?\b"),
    ("drizzle", r"\b(?:drizzles?|splash(?:es)?|dash(?:es)?)\b"),
    ("slice", r"\bslices?\b"),
    ("bite", r"\bbites?\b"),
    ("bowl", r"\bbowls?\b"),
    ("plate", r"\bplates?\b"),
    ("little", r"\b(?:a\s+)?little\b|\ba\s+bit\b|\bsmall\s+amount\b"),
    ("some", r"\bsome\b|\ba\s+few\b|\bcouple\s+of\b"),
)

#: Size words that shift a portion. Applied to the median AND the bounds, so a
#: "small handful" stays proportionally uncertain.
SIZE_MODIFIERS = {"tiny": 0.5, "small": 0.72, "little": 0.72, "medium": 1.0,
                  "normal": 1.0, "regular": 1.0, "big": 1.35, "large": 1.35,
                  "huge": 1.7, "generous": 1.3, "heaping": 1.4, "thin": 0.7,
                  "thick": 1.4, "extra large": 1.6, "jumbo": 1.6}


def food_category(food_name: str) -> str:
    """Which ontology row applies. Longest fragment wins so "peanut butter"
    does not resolve as "nuts"."""
    n = (food_name or "").lower()
    best, best_len = "default", 0
    for fragment, category in FOOD_CATEGORIES.items():
        if fragment in n and len(fragment) > best_len:
            best, best_len = category, len(fragment)
    return best


def detect_measure(text: str) -> Optional[str]:
    """The vague measure in this text, if any."""
    t = (text or "").lower()
    for measure, pattern in _MEASURE_PATTERNS:
        if re.search(pattern, t, re.I):
            return measure
    return None


def distribution_for(measure: str, food_name: str = "",
                     modifier: str = "") -> Optional[QuantityDistribution]:
    """The distribution for this measure of this food, size-adjusted."""
    rows = PORTION_ONTOLOGY.get((measure or "").lower())
    if not rows:
        return None
    category = food_category(food_name)
    median, lower, upper, confidence = rows.get(category, rows["default"])
    factor = SIZE_MODIFIERS.get((modifier or "").lower().strip(), 1.0)
    return QuantityDistribution(
        median_g=round(median * factor, 1), lower_g=round(lower * factor, 1),
        upper_g=round(upper * factor, 1), confidence=confidence,
        category=f"{category}_{measure}")


def detect_modifier(text: str) -> str:
    t = (text or "").lower()
    for modifier in sorted(SIZE_MODIFIERS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(modifier)}\b", t):
            return modifier
    return ""


# ── exact conversions ─────────────────────────────────────────────────────────
MASS_TO_G = {"g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0,
             "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
             "lb": 453.592, "lbs": 453.592, "pound": 453.592,
             "pounds": 453.592}

VOLUME_TO_ML = {"ml": 1.0, "l": 1000.0, "liter": 1000.0, "litre": 1000.0,
                "cup": 236.588, "cups": 236.588, "tbsp": 14.787,
                "tsp": 4.929, "floz": 29.574, "fl oz": 29.574,
                "pint": 473.176, "quart": 946.353}


def convert(text: str, food_name: str = "", *,
            unit_mass_g: Optional[float] = None) -> ConversionResult:
    """Normalize a portion phrase, honestly.

    A mass or volume unit converts exactly (confidence 1.0). A vague measure
    resolves through the ontology and carries its distribution. A count with a
    known product unit weight converts at high confidence; a count without one
    reports the count and NO mass, because inventing one is the fake precision
    the directive forbids.
    """
    raw = (text or "").strip()
    lowered = raw.lower()
    amount, remainder = _split_amount(lowered)

    for token, per in sorted(MASS_TO_G.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(token)}\b", remainder):
            return ConversionResult(
                amount=amount, unit="g", unit_kind=UnitKind.MASS,
                mass_equivalent_g=round(amount * per, 1),
                conversion_confidence=1.0, conversion_source="exact_mass")
    for token, per in sorted(VOLUME_TO_ML.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(token)}\b", remainder):
            # Volume is exact as volume. It is NOT a mass — density is an
            # assumption, and the scaler refuses that conversion by design.
            return ConversionResult(
                amount=round(amount * per, 1), unit="ml",
                unit_kind=UnitKind.VOLUME, conversion_confidence=1.0,
                conversion_source="exact_volume")

    measure = detect_measure(lowered)
    if measure:
        dist = distribution_for(measure, food_name, detect_modifier(lowered))
        if dist is not None:
            scaled = dist.scaled(amount) if amount != 1.0 else dist
            return ConversionResult(
                amount=amount, unit=measure, unit_kind=UnitKind.DESCRIPTIVE,
                mass_equivalent_g=scaled.median_g,
                conversion_confidence=scaled.confidence,
                conversion_source=f"ontology:{scaled.category}",
                distribution=scaled, count=amount)

    if unit_mass_g:
        return ConversionResult(
            amount=amount, unit="count", unit_kind=UnitKind.COUNT,
            mass_equivalent_g=round(amount * float(unit_mass_g), 1),
            conversion_confidence=0.95,
            conversion_source="product_unit_weight", count=amount)

    # A count with no basis for a mass. Say so.
    return ConversionResult(
        amount=amount, unit=(remainder.split()[0] if remainder.split()
                             else "serving"),
        unit_kind=UnitKind.COUNT, mass_equivalent_g=None,
        conversion_confidence=0.0, conversion_source="unknown_unit_weight",
        count=amount)


_NUM_WORDS = {"a": 1.0, "an": 1.0, "one": 1.0, "two": 2.0, "three": 3.0,
              "four": 4.0, "five": 5.0, "six": 6.0, "seven": 7.0,
              "eight": 8.0, "nine": 9.0, "ten": 10.0, "twelve": 12.0,
              "dozen": 12.0, "half": 0.5, "quarter": 0.25}


def _split_amount(text: str) -> tuple:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(.*)$", text)
    if m:
        return float(m.group(1)), m.group(2).strip()
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*(.*)$", text)
    if m:
        try:
            return float(m.group(1)) / float(m.group(2)), m.group(3).strip()
        except ZeroDivisionError:
            pass
    words = text.split()
    if words and words[0] in _NUM_WORDS:
        return _NUM_WORDS[words[0]], " ".join(words[1:]).strip()
    return 1.0, text.strip()
