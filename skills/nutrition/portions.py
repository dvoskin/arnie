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


class Specificity(str, Enum):
    """Which tier of the ontology answered.

    Recorded on every distribution so "where is the broad fallback still being
    hit?" is a query rather than a guess. That is what makes replacing the
    fallbacks progressive instead of aspirational — production tells you which
    (measure, category, form) to write next.
    """
    FORM = "form"            # category AND form: "a handful of cooked spinach"
    CATEGORY = "category"    # category only: "a handful of spinach"
    FALLBACK = "fallback"    # the measure's broad default

    @property
    def is_fallback(self) -> bool:
        return self is Specificity.FALLBACK


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
    form: str = ""
    specificity: Specificity = Specificity.FALLBACK

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
        # A "scoop" of peanut butter is a SPOON, not an ice-cream scoop — one
        # to two tablespoons. Falling through to the 45 g default put it at
        # nearly three, which is 270 calories of peanut butter for a phrase
        # that usually means one heaped spoonful.
        #
        # Encoded as a category row rather than an override somewhere else on
        # purpose: the ontology is the single source of truth for what a vague
        # measure weighs, and a second place that adjusts the answer afterwards
        # is how two implementations of the same rule start disagreeing.
        "nut_butter":     (24.0, 16.0, 34.0, 0.55),
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
        #
        # WIDE IS NOT THE SAME AS UNIFORM, though, and for a long time this row
        # was the only one — so "some ranch dressing" and "some chicken" were
        # both asked about as "closer to 30g or 200g?". 200 g of ranch is most
        # of a bottle. A question whose own range is absurd for the food reads
        # as a system that does not know what it is holding, and the user
        # cannot answer it honestly either way.
        #
        # The category machinery below already existed and already classified
        # these correctly; "some" simply had no rows to select. Each stays wide
        # WITHIN its category — the point is not precision, it is that the two
        # ends are both plausible amounts of THAT food.
        "sauce":        (35.0, 15.0, 80.0, 0.35),
        "dressing":     (30.0, 15.0, 60.0, 0.35),
        "oil":          (14.0, 5.0, 30.0, 0.35),
        "condiment":    (18.0, 6.0, 45.0, 0.35),
        "cheese":       (30.0, 14.0, 60.0, 0.35),
        "nut_butter":   (32.0, 16.0, 64.0, 0.35),
        "rice":         (150.0, 80.0, 260.0, 0.32),
        "pasta":        (150.0, 80.0, 260.0, 0.32),
        "leafy":        (60.0, 25.0, 120.0, 0.32),
        "berries":      (100.0, 50.0, 180.0, 0.32),
        "nuts":         (35.0, 15.0, 70.0, 0.35),
        "chips":        (35.0, 15.0, 70.0, 0.35),
        "meat":         (120.0, 60.0, 220.0, 0.32),
        "default":      (80.0, 30.0, 200.0, 0.30),
    },
    "little": {
        # Same shape one step smaller — "a little olive oil" is a teaspoon or
        # two, not 12-60 g of it.
        "sauce":        (18.0, 8.0, 40.0, 0.38),
        "dressing":     (15.0, 7.0, 30.0, 0.38),
        "oil":          (8.0, 4.0, 15.0, 0.38),
        "condiment":    (10.0, 4.0, 22.0, 0.38),
        "cheese":       (15.0, 7.0, 30.0, 0.38),
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
    # ── the hand portions the prompt already asks in ─────────────────────────
    #
    # `core/prompts/arnie.py` teaches the clarifying question "palm-sized,
    # plate-sized, or huge?" — and until now `plate` was the only one of the
    # three this table could read. So Arnie asked in palms, the user answered
    # in palms, nothing could turn a palm into mass, and the interpreter was
    # left to improvise: a schnitzel came back as "0.5 palm-size cutlet", a
    # fractional count of a unit invented on the spot, at calories that
    # matched a whole palm.
    #
    # Asking in a vocabulary the resolver cannot read is the same defect as
    # every other in this lane — two lists describing one thing — and it is
    # worse here because the ask is the part the user answers.
    #
    # A palm is the standard protein-portion gesture: the flat of the hand,
    # roughly a deck of cards, ~110 g of cooked meat. Breaded and fried runs
    # heavier for the same visual size, hence the separate row.
    # Keyed only on categories this table can actually REACH. There is no meat
    # or protein category — `food_category` sends chicken, salmon and steak all
    # to "default" — so the default here IS the protein number rather than an
    # average over foods nobody measures in palms. Writing a "protein" row that
    # `food_category` can never return would look more informed than it is,
    # which the note above `FORM_DISTRIBUTIONS` already warns against.
    "palm": {
        "cheese":       (40.0, 28.0, 55.0, 0.55),
        "deli_meat":    (55.0, 40.0, 75.0, 0.55),
        "default":      (110.0, 80.0, 145.0, 0.50),
    },
    #: A closed fist is the carb/veg gesture — about a cup.
    "fist": {
        "greens":       (40.0, 25.0, 60.0, 0.55),
        "rice":         (150.0, 110.0, 200.0, 0.58),
        "pasta":        (140.0, 100.0, 190.0, 0.55),
        "cereal":       (40.0, 28.0, 55.0, 0.55),
        "default":      (145.0, 100.0, 200.0, 0.45),
    },
    #: A thumb is the fat gesture — about a tablespoon.
    "thumb": {
        "cheese":       (20.0, 14.0, 28.0, 0.60),
        "nut_butter":   (16.0, 12.0, 22.0, 0.65),
        "oil":          (13.0, 9.0, 18.0, 0.70),
        "default":      (15.0, 10.0, 21.0, 0.55),
    },
    "cup": {
        # A cup is an exact VOLUME and an inexact mass, and which one matters
        # depends on the food. For anything with a density we use the density;
        # these rows are for the solids where 236 ml says very little — a cup
        # of broccoli florets and a cup of flour differ by three times.
        "greens":       (30.0, 20.0, 45.0, 0.60),
        "berries":      (145.0, 120.0, 170.0, 0.72),
        "cereal":       (35.0, 25.0, 50.0, 0.62),
        "chips":        (30.0, 20.0, 45.0, 0.55),
        "popcorn":      (10.0, 7.0, 15.0, 0.60),
        "nuts":         (130.0, 110.0, 150.0, 0.70),
        "dried_fruit":  (150.0, 120.0, 175.0, 0.65),
        "default":      (120.0, 60.0, 240.0, 0.40),
    },
}

#: FORM-SPECIFIC distributions: (category, form) → (median, lower, upper, conf).
#:
#: This table sits ABOVE the category table and never replaces it — the broad
#: rows stay as the safety net for everything not yet written down. Adding a
#: row here is purely additive: nothing else changes, and the lookup starts
#: preferring it immediately.
#:
#: A form earns a row when it moves the portion MATERIALLY. Raw spinach wilts
#: to roughly a third of its volume, so a handful of cooked spinach is nearly
#: three times the mass of a raw one; dry oats and cooked oats differ by five
#: times. Shredded and cubed cheese differ enough to matter over a handful.
#: Forms that barely move the number are deliberately absent — a row that
#: duplicates its category fallback is noise that makes the table look more
#: informed than it is, and a test enforces that.
FORM_DISTRIBUTIONS = {
    "handful": {
        ("greens", "cooked"):     (68.0, 48.0, 95.0, 0.55),
        ("nuts", "chopped"):      (34.0, 24.0, 46.0, 0.66),
        ("rice", "cooked"):       (55.0, 40.0, 78.0, 0.55),
        ("cereal", "granola"):    (44.0, 32.0, 60.0, 0.64),
        ("cereal", "flakes"):     (17.0, 11.0, 25.0, 0.60),
        ("cheese", "shredded"):   (28.0, 20.0, 38.0, 0.68),
        ("cheese", "cubed"):      (38.0, 27.0, 52.0, 0.62),
        ("berries", "dried"):     (40.0, 28.0, 55.0, 0.62),
    },
    "spoonful": {
        ("sugar", "packed"):      (14.5, 11.0, 19.0, 0.72),
        ("nut_butter", "melted"): (19.0, 14.0, 26.0, 0.66),
        ("yogurt", "greek"):      (34.0, 26.0, 45.0, 0.68),
    },
    "scoop": {
        ("ice_cream", "softened"): (78.0, 58.0, 105.0, 0.58),
        ("protein_powder", "whey"): (32.0, 29.0, 36.0, 0.84),
    },
    "bowl": {
        ("oats", "dry"):        (48.0, 36.0, 62.0, 0.68),
        ("oats", "cooked"):     (255.0, 185.0, 340.0, 0.58),
        ("cereal", "granola"):  (62.0, 45.0, 85.0, 0.60),
        ("cereal", "flakes"):   (32.0, 22.0, 45.0, 0.58),
        ("greens", "raw"):      (85.0, 55.0, 130.0, 0.52),
        ("soup", "chunky"):     (340.0, 250.0, 460.0, 0.58),
    },
    "slice": {
        ("bread", "sourdough"): (48.0, 36.0, 64.0, 0.68),
        ("deli_meat", "shaved"): (12.0, 8.0, 18.0, 0.66),
        ("deli_meat", "roast"): (32.0, 22.0, 45.0, 0.62),
    },
    "drizzle": {
        ("oil", "cooking"):     (9.0, 5.0, 15.0, 0.56),
        ("syrup", "thick"):     (17.0, 10.0, 27.0, 0.55),
    },
}

#: Text fragments → canonical form. Longest match wins, so "extra virgin olive
#: oil" does not resolve on a shorter accidental substring.
FORM_ALIASES = {
    "cooked": "cooked", "boiled": "cooked", "steamed": "cooked",
    "sauteed": "cooked", "sautéed": "cooked", "wilted": "cooked",
    "raw": "raw", "fresh": "raw", "uncooked": "dry", "dry": "dry",
    "dried": "dried", "dehydrated": "dried",
    "shredded": "shredded", "grated": "shredded",
    "cubed": "cubed", "diced": "cubed", "cubes": "cubed",
    "chopped": "chopped", "crushed": "chopped", "slivered": "chopped",
    "packed": "packed", "loose": "loose",
    "melted": "melted", "softened": "softened",
    "granola": "granola", "flakes": "flakes", "flake": "flakes",
    "greek": "greek", "deli": "deli", "shaved": "shaved", "roast": "roast",
    "sourdough": "sourdough", "sandwich": "sandwich",
    "broth": "broth", "brothy": "broth", "chunky": "chunky",
    "cooking oil": "cooking", "olive oil": "cooking",
    "whey": "whey", "thick": "thick",
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
    "cereal": "cereal", "granola": "cereal", "corn flake": "cereal",
    "oat": "oats", "oatmeal": "oats", "porridge": "oats",
    "pasta": "pasta", "spaghetti": "pasta", "penne": "pasta",
    "noodle": "pasta",
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
    # BUTTER IS A FAT, AND IT HAD NO CATEGORY AT ALL. `food_category("butter")`
    # returned "default", so butter had no density, a tablespoon of it had no
    # mass, and a per-100g source could not price the commonest way anyone
    # ever logs it. That is one of the three things that had to be true at
    # once for butter to commit at 0 calories.
    #
    # `nut_butter` is deliberately longer, so "peanut butter" and "almond
    # butter" still win it on the longest-fragment rule and keep 0.95.
    "butter": "oil", "ghee": "oil", "margarine": "oil", "lard": "oil",
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
    # The hand gestures. "palm size", "palm-sized", "the size of my palm" and
    # "a palm" all mean the same portion, and the prompt asks in exactly this
    # word — see the note on the `palm` ontology row.
    ("palm", r"\bpalms?(?:[\s-]?sized?)?\b"),
    ("fist", r"\bfists?(?:[\s-]?sized?)?\b"),
    ("thumb", r"\bthumbs?(?:[\s-]?sized?)?\b"),
    ("little", r"\b(?:a\s+)?little\b|\ba\s+bit\b|\bsmall\s+amount\b"),
    ("some", r"\bsome\b|\ba\s+few\b|\bcouple\s+of\b"),
)

#: Size words that shift a portion. Applied to the median AND the bounds, so a
#: "small handful" stays proportionally uncertain.
SIZE_MODIFIERS = {"tiny": 0.5, "small": 0.72, "little": 0.72, "medium": 1.0,
                  "normal": 1.0, "regular": 1.0, "big": 1.35, "large": 1.35,
                  "huge": 1.7, "generous": 1.3, "heaping": 1.4, "thin": 0.7,
                  "thick": 1.4, "extra large": 1.6, "jumbo": 1.6}


#: How much longer than the fragment the word containing it may be. The
#: fragments are deliberately truncated stems ("blueberr" covers blueberry and
#: blueberries), so a plain substring test is the only practical match — but an
#: unbounded one made "chipotle" a chip and "dates" a category for "update".
#: Three characters covers the inflections and excludes the different words.
_STEM_SLACK = 3


def _stem_matches(name: str, fragment: str) -> bool:
    """Whether `fragment` appears as the stem of a word in `name`."""
    tail = fragment.split()[-1]
    for match in re.finditer(rf"\b{re.escape(fragment)}", name):
        word = re.match(r"[a-z]*", name[match.start() + len(fragment) - len(tail):])
        if word and len(word.group(0)) - len(tail) <= _STEM_SLACK:
            return True
    return False


def food_category(food_name: str) -> str:
    """Which ontology row applies. Longest fragment wins so "peanut butter"
    does not resolve as "nuts"."""
    n = (food_name or "").lower()
    best, best_len = "default", 0
    for fragment, category in FOOD_CATEGORIES.items():
        if len(fragment) > best_len and _stem_matches(n, fragment):
            best, best_len = category, len(fragment)
    return best


def detect_measure(text: str) -> Optional[str]:
    """The vague measure in this text, if any."""
    t = (text or "").lower()
    for measure, pattern in _MEASURE_PATTERNS:
        if re.search(pattern, t, re.I):
            return measure
    return None


def detect_form(text: str) -> str:
    """The preparation form named in this text, if any. Longest alias wins."""
    t = (text or "").lower()
    best, best_len = "", 0
    for fragment, form in FORM_ALIASES.items():
        if fragment in t and len(fragment) > best_len:
            best, best_len = form, len(fragment)
    return best


def distribution_for(measure: str, food_name: str = "", modifier: str = "",
                     form: Optional[str] = None
                     ) -> Optional[QuantityDistribution]:
    """The best available distribution, walking specific → broad.

        1. (category, form)  — "a handful of cooked spinach"
        2. category          — "a handful of spinach"
        3. the measure's broad default

    The fallback is never removed. It is what keeps an unwritten combination
    answerable, and every row added above it narrows the set of turns that
    reach it — which is the whole shape of "progressively replace".
    """
    measure = (measure or "").lower()
    rows = PORTION_ONTOLOGY.get(measure)
    if not rows:
        return None

    category = food_category(food_name)
    resolved_form = form if form is not None else detect_form(food_name)

    entry, specificity = None, Specificity.FALLBACK
    if resolved_form:
        entry = FORM_DISTRIBUTIONS.get(measure, {}).get(
            (category, resolved_form))
        if entry is not None:
            specificity = Specificity.FORM
    if entry is None and category != "default":
        # Guarded on `category != "default"` deliberately: food_category()
        # returns the literal "default" for an unrecognised food, which would
        # otherwise match the fallback row and be REPORTED as category-specific.
        # That would corrupt the one metric this tier exists to produce.
        entry = rows.get(category)
        if entry is not None:
            specificity = Specificity.CATEGORY
    if entry is None:
        entry = rows["default"]
        specificity = Specificity.FALLBACK

    median, lower, upper, confidence = entry
    factor = SIZE_MODIFIERS.get((modifier or "").lower().strip(), 1.0)
    return QuantityDistribution(
        median_g=round(median * factor, 1), lower_g=round(lower * factor, 1),
        upper_g=round(upper * factor, 1), confidence=confidence,
        category=f"{category}_{measure}",
        form=(resolved_form if specificity is Specificity.FORM else ""),
        specificity=specificity)


def ontology_coverage() -> dict:
    """How much of the ontology is form-specific yet.

    Progress on "progressively replace the fallbacks" is a number, not a
    feeling. Pair this with the production count of
    conversion_source=ontology:fallback:* to target the next rows at the
    combinations users actually hit.
    """
    form_rows = sum(len(rows) for rows in FORM_DISTRIBUTIONS.values())
    category_rows = sum(len([k for k in rows if k != "default"])
                        for rows in PORTION_ONTOLOGY.values())
    return {
        "measures": len(PORTION_ONTOLOGY),
        "category_rows": category_rows,
        "form_rows": form_rows,
        "measures_with_forms": len(FORM_DISTRIBUTIONS),
    }


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
        # The form may be named in the portion phrase ("a handful of cooked
        # spinach") or only in the food name — check both.
        form = detect_form(f"{lowered} {food_name}") or None
        dist = distribution_for(measure, food_name, detect_modifier(lowered),
                                form=form)
        if dist is not None:
            scaled = dist.scaled(amount) if amount != 1.0 else dist
            # The specificity is in the source string on purpose: counting
            # `ontology:fallback:` in production is how the next rows get
            # chosen.
            source = f"ontology:{scaled.specificity.value}:{scaled.category}"
            if scaled.form:
                source = f"{source}:{scaled.form}"
            return ConversionResult(
                amount=amount, unit=measure, unit_kind=UnitKind.DESCRIPTIVE,
                mass_equivalent_g=scaled.median_g,
                conversion_confidence=scaled.confidence,
                conversion_source=source,
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
