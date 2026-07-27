"""Pricing a composite dish from its parts (directive §4, the `component_estimate` rung).

`component_estimate` has been the last rung of the RESTAURANT ladder since the
ladders were written, and `COMPONENT_BREAKDOWN` has been in the ambiguity enum
just as long. Neither had anything behind it. `authority.candidate_map` seated
no candidate on that rung — ever — so the only way to reach it was
`food_intelligence` RELABELLING an ordinary estimate on line 764: an item the
ladder had refused got the name `component_estimate` purely because it was a
restaurant food. The rung named a method nobody had implemented, and the
disclosure under it — "Estimated from its components" — described work that had
not happened.

The cost was measured, not assumed: composite totals drift 18-21% across modes
(b835700), which also named the fix and left it unbuilt.

**What is ours and what is not.** The decomposition is OURS — a taco is a
tortilla, some meat, onion, salsa — and so are the gram assumptions. Those are
assumptions and this module says so, which is why every result carries a range
rather than a point. What is NOT ours is the nutrition: each component is
priced from USDA generics, and that is the external authority the rung has
always claimed and never had. USDA carries no row for "two carnitas tacos". It
carries excellent rows for corn tortillas, cooked pork shoulder, white onion
and salsa.

**Nothing here fetches**, the same rule `authority` follows and for the same
reason: the arithmetic is then testable without a network or an API key, and
the fetch stays in the one layer that already owns concurrency
(`handlers/tool_executor`). `price()` takes rows that someone else obtained.

**A partial answer is refused, not padded.** If the components we could
actually price do not account for `MIN_PRICED_MASS_FRACTION` of the assumed
mass, there is no estimate — the caller falls back to exactly what it did
before. What we can price but only partly widens the range instead of quietly
shrinking the dish.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


#: How much of a recipe's assumed mass must actually price before we will
#: report a number. Below this the "estimate from its components" is mostly an
#: estimate from the components we could not find, which is the failure this
#: module exists to stop being invisible.
MIN_PRICED_MASS_FRACTION = 0.85

#: What a component candidate declares its per-100g figures to mean. Same
#: constant `api.usda` states for its own rows, because that is literally where
#: these numbers came from.
COMPOSITE_BASIS = "per_100g"

#: The match grade a component estimate claims. Deliberately not "exact": this
#: is a construction, not a row anybody published. "likely" is what the
#: enrichment path reads as trustworthy-but-not-identical, which is the honest
#: reading — and unlike a USDA text match it is not competing on name
#: similarity, so it does not carry that grade's failure mode.
COMPOSITE_MATCH = "likely"


@dataclass(frozen=True)
class Component:
    """One part of a dish, and how sure we are of how much of it there is.

    `query` is what USDA is asked for, so it has to be a GENERIC that USDA's
    curated indexes (Foundation, SR Legacy) actually carry. "carnitas" is not
    one; "pork shoulder, cooked" is.

    `spread_g` is the honest half-width of the gram assumption, not a
    decoration. A taco's tortilla is a manufactured disc and barely varies; the
    meat on it varies enormously between a street cart and a sit-down plate.
    Encoding that difference per component is what makes the summed range mean
    something.
    """
    role: str
    query: str
    grams: float
    spread_g: float

    @property
    def low_g(self) -> float:
        return max(0.0, self.grams - self.spread_g)

    @property
    def high_g(self) -> float:
        return self.grams + self.spread_g


@dataclass(frozen=True)
class Recipe:
    """One build of one dish, for ONE of it.

    `unit_noun` is what a single one is called, so the candidate can publish a
    serving panel ("1 taco") that the existing count-scaling path already knows
    how to multiply. That is the whole reason this fits without new scaling
    code: `_per_serving_for` in `food_intelligence` turns "2 tacos" into
    2 x the panel, exactly as it does for "2 bars" of a labelled product.
    """
    dish: str
    unit_noun: str
    components: tuple[Component, ...]
    assumption: str

    @property
    def assumed_mass_g(self) -> float:
        return sum(c.grams for c in self.components)


# ── the protein slot ──────────────────────────────────────────────────────────
#
# "carnitas taco", "chicken taco" and "carne asada taco" are the same build with
# a different filling, and pricing all three off one default would make the
# dish name decorative. The slot is filled from what the user actually said;
# the recipe's own default applies only when they said nothing.
#
# Values are USDA-answerable generics, not menu words.
_PROTEIN_SLOT = {
    "carnitas": "pork shoulder cooked",
    "al pastor": "pork shoulder cooked",
    "pastor": "pork shoulder cooked",
    "pork": "pork shoulder cooked",
    "carne asada": "beef steak cooked",
    "asada": "beef steak cooked",
    "steak": "beef steak cooked",
    "barbacoa": "beef chuck cooked",
    "birria": "beef chuck cooked",
    "ground beef": "ground beef cooked",
    "beef": "ground beef cooked",
    "chicken": "chicken breast roasted",
    "pollo": "chicken breast roasted",
    "turkey": "turkey breast roasted",
    "fish": "cod cooked",
    "shrimp": "shrimp cooked",
    "tofu": "tofu firm",
    "bean": "pinto beans cooked",
    "beans": "pinto beans cooked",
    "veggie": "pinto beans cooked",
    "vegetarian": "pinto beans cooked",
}

#: Longest first, so "ground beef" and "carne asada" are matched before "beef"
#: and "asada" can claim them.
_PROTEIN_KEYS = tuple(sorted(_PROTEIN_SLOT, key=len, reverse=True))

#: The role name a filled protein slot carries. Read by `price()` to know which
#: component to substitute.
PROTEIN_ROLE = "protein"


# ── the table ─────────────────────────────────────────────────────────────────
#
# Data, not code, so a dish is added by writing down its parts rather than by
# touching any of the arithmetic. It is deliberately SMALL: every row here is a
# claim about what is in a dish, and a short table of builds that are actually
# canonical is worth more than a long one of guesses. A dish absent from it
# gets no component estimate and the caller behaves exactly as it did before —
# which is the correct outcome for "I do not know what is in this", and the
# outcome the previous relabelling never allowed.
#
# Masses are standard reference portions: a 6" corn tortilla is 26 g, a 10"
# flour tortilla 72 g, a hamburger bun 52 g, a slice of American cheese 19 g.
_RECIPES: tuple[Recipe, ...] = (
    Recipe(
        dish="taco",
        unit_noun="taco",
        components=(
            Component("base", "corn tortilla", 26.0, 3.0),
            Component(PROTEIN_ROLE, "pork shoulder cooked", 55.0, 15.0),
            Component("vegetable", "onion raw", 8.0, 4.0),
            Component("sauce", "salsa", 15.0, 8.0),
        ),
        assumption="a street-style taco: one corn tortilla, about 55 g of "
                   "filling, onion and salsa",
    ),
    Recipe(
        dish="burrito",
        unit_noun="burrito",
        components=(
            Component("base", "flour tortilla", 72.0, 8.0),
            Component(PROTEIN_ROLE, "chicken breast roasted", 85.0, 25.0),
            Component("grain", "white rice cooked", 90.0, 30.0),
            Component("legume", "pinto beans cooked", 70.0, 25.0),
            Component("cheese", "cheddar cheese", 28.0, 10.0),
            Component("sauce", "salsa", 30.0, 15.0),
        ),
        assumption="a mission-style burrito: a 10-inch flour tortilla with "
                   "rice, beans, filling, cheese and salsa",
    ),
    Recipe(
        dish="burrito bowl",
        unit_noun="bowl",
        components=(
            Component(PROTEIN_ROLE, "chicken breast roasted", 85.0, 25.0),
            Component("grain", "white rice cooked", 120.0, 40.0),
            Component("legume", "pinto beans cooked", 80.0, 30.0),
            Component("cheese", "cheddar cheese", 28.0, 12.0),
            Component("sauce", "salsa", 45.0, 20.0),
            Component("vegetable", "lettuce raw", 30.0, 15.0),
        ),
        assumption="a burrito bowl: the burrito's fillings without the "
                   "tortilla, in a slightly larger portion",
    ),
    Recipe(
        dish="quesadilla",
        unit_noun="quesadilla",
        components=(
            Component("base", "flour tortilla", 72.0, 10.0),
            Component("cheese", "cheddar cheese", 56.0, 20.0),
        ),
        assumption="a plain cheese quesadilla: one large flour tortilla "
                   "folded over about 56 g of cheese",
    ),
    Recipe(
        dish="cheeseburger",
        unit_noun="burger",
        components=(
            Component("base", "hamburger bun", 52.0, 6.0),
            Component(PROTEIN_ROLE, "ground beef cooked", 85.0, 25.0),
            Component("cheese", "american cheese", 19.0, 6.0),
            Component("vegetable", "lettuce raw", 10.0, 5.0),
            Component("vegetable_2", "tomato raw", 20.0, 10.0),
            Component("sauce", "ketchup", 15.0, 10.0),
        ),
        assumption="a quarter-pound cheeseburger: one bun, an 85 g cooked "
                   "patty, a slice of cheese and the usual garnish",
    ),
    Recipe(
        dish="hamburger",
        unit_noun="burger",
        components=(
            Component("base", "hamburger bun", 52.0, 6.0),
            Component(PROTEIN_ROLE, "ground beef cooked", 85.0, 25.0),
            Component("vegetable", "lettuce raw", 10.0, 5.0),
            Component("vegetable_2", "tomato raw", 20.0, 10.0),
            Component("sauce", "ketchup", 15.0, 10.0),
        ),
        assumption="a quarter-pound hamburger: one bun, an 85 g cooked patty "
                   "and the usual garnish, no cheese",
    ),
    Recipe(
        dish="grilled cheese",
        unit_noun="sandwich",
        components=(
            Component("base", "white bread", 56.0, 8.0),
            Component("cheese", "american cheese", 38.0, 14.0),
            Component("fat", "butter", 14.0, 7.0),
        ),
        assumption="a grilled cheese: two slices of bread, two slices of "
                   "cheese, and butter on the pan",
    ),
)

#: Names that mean an existing recipe. Kept apart from the table so a synonym
#: is never mistaken for a second, differently-built dish.
_ALIASES = {
    "burger": "hamburger",
    "beef burger": "hamburger",
    "hamburguesa": "hamburger",
    "cheese burger": "cheeseburger",
    "chipotle bowl": "burrito bowl",
    "rice bowl": "burrito bowl",
    "grilled cheese sandwich": "grilled cheese",
    "toasted cheese": "grilled cheese",
    "quesadillas": "quesadilla",
}

_BY_DISH = {r.dish: r for r in _RECIPES}

#: Dish names longest first: "burrito bowl" must win over "burrito", or every
#: bowl gets a tortilla it never had.
_DISH_KEYS = tuple(sorted(
    tuple(_BY_DISH) + tuple(_ALIASES), key=len, reverse=True))

_WORD = re.compile(r"[a-z]+")


def _tokens(text: str) -> str:
    """Lowercased words with punctuation and digits dropped, space-padded so a
    substring test cannot match inside a longer word — "tacos" must find
    "taco", but "tacoma" must not."""
    return " " + " ".join(_WORD.findall((text or "").lower())) + " "


def _mentions(haystack: str, needle: str) -> bool:
    """Whole-word (or whole-phrase) containment, tolerating a plural `s`."""
    return (f" {needle} " in haystack) or (f" {needle}s " in haystack)


def match_recipe(food_name: str) -> Optional[Recipe]:
    """The build this dish name names, with its protein slot filled, or None.

    None is the common and correct answer. This table knows a handful of
    dishes; everything else must fall through to the behaviour that existed
    before this module, which is why nothing here guesses from a partial match.
    """
    text = _tokens(food_name)
    if text.strip() == "":
        return None
    for key in _DISH_KEYS:
        if not _mentions(text, key):
            continue
        recipe = _BY_DISH[_ALIASES.get(key, key)]
        return _fill_protein(recipe, text)
    return None


def _fill_protein(recipe: Recipe, text: str) -> Recipe:
    """Swap the recipe's default filling for the one the name states.

    Only the query changes. The gram assumption belongs to the DISH — a taco
    holds about as much chicken as it holds pork — so substituting the meat
    must not quietly resize the taco.
    """
    slot = next((c for c in recipe.components if c.role == PROTEIN_ROLE), None)
    if slot is None:
        return recipe
    for key in _PROTEIN_KEYS:
        if not _mentions(text, key):
            continue
        query = _PROTEIN_SLOT[key]
        if query == slot.query:
            return recipe
        swapped = tuple(
            Component(c.role, query, c.grams, c.spread_g)
            if c.role == PROTEIN_ROLE else c
            for c in recipe.components)
        return Recipe(recipe.dish, recipe.unit_noun, swapped,
                      recipe.assumption)
    return recipe


def component_queries(recipe: Recipe) -> tuple[str, ...]:
    """What the caller has to look up, de-duplicated and order-stable.

    Order-stable so the fetch lane's logging and its cache keys are
    reproducible; de-duplicated so a dish using the same generic twice is one
    request, not two.
    """
    seen: list[str] = []
    for c in recipe.components:
        if c.query not in seen:
            seen.append(c.query)
    return tuple(seen)


def _per100(row: Mapping) -> dict:
    """A row's per-100g figures, whatever shape the adapter handed back."""
    per100 = row.get("per100g")
    return dict(per100) if isinstance(per100, dict) else {}


def price(recipe: Recipe, rows: Mapping[str, Optional[Mapping]],
          *, micro_keys: Sequence[str] = ()) -> Optional[dict]:
    """A candidate for ONE of `recipe`, priced from `rows`, or None.

    `rows` maps a component query to the USDA row that answered it — `None` or
    absent for a component that could not be priced. Every nutrient here comes
    from those rows; the only thing this function contributes is the grams, and
    the grams are what the range is a range OVER.

    Returns None when too little of the dish priced (see
    `MIN_PRICED_MASS_FRACTION`). Returning a short-weight dish would be worse
    than returning nothing: it would be confidently low, seated on a rung that
    outranks the estimate, and carrying USDA's name on the shortfall.
    """
    assumed = recipe.assumed_mass_g
    if assumed <= 0:
        return None

    priced_g = 0.0
    totals: dict = {}
    lo_cal = hi_cal = 0.0
    breakdown: list[dict] = []
    unpriced: list[str] = []

    for c in recipe.components:
        row = rows.get(c.query)
        per100 = _per100(row) if row else {}
        cal100 = per100.get("calories")
        if not row or not cal100:
            unpriced.append(c.query)
            continue

        priced_g += c.grams
        ratio = c.grams / 100.0
        for key, value in per100.items():
            if value is None:
                continue
            if key == "calories" or key in ("protein", "carbs", "fat",
                                            "fiber", "sugar", "sodium") \
                    or key in micro_keys:
                totals[key] = totals.get(key, 0.0) + value * ratio

        # The range is a MASS range, priced at this component's own density.
        # Summing the extremes across components is deliberately the widest
        # honest reading: we do not get to assume our errors cancel.
        lo_cal += cal100 * (c.low_g / 100.0)
        hi_cal += cal100 * (c.high_g / 100.0)
        breakdown.append({
            "role": c.role,
            "query": c.query,
            "grams": round(c.grams, 1),
            "calories": round(cal100 * ratio),
            "fdc_id": row.get("fdc_id"),
            "description": row.get("description", ""),
        })

    fraction = priced_g / assumed
    if fraction < MIN_PRICED_MASS_FRACTION:
        logger.info(
            "event=component_estimate dish=%r outcome=refused priced=%.0f%% "
            "unpriced=%s", recipe.dish, fraction * 100, ",".join(unpriced))
        return None

    if not totals.get("calories"):
        return None

    # WHAT DID NOT PRICE STILL WIDENS THE ANSWER. The missing mass is real
    # food; dropping it silently is how a component sum comes out low and
    # confident. It cannot raise the total — we have no density for it — but it
    # must not be allowed to make the estimate look tighter than it is.
    if unpriced:
        density = totals["calories"] / priced_g if priced_g else 0.0
        hi_cal += density * (assumed - priced_g)

    mass = round(priced_g, 1)
    serving = {k: (round(v) if k in ("calories", "sodium") else round(v, 1))
               for k, v in totals.items()}
    per100g = {k: (round(v * 100.0 / mass, 1) if k != "calories"
                   else round(v * 100.0 / mass))
               for k, v in totals.items()} if mass > 0 else {}

    logger.info(
        "event=component_estimate dish=%r outcome=priced parts=%d "
        "mass=%.0fg cal=%d range=%d-%d", recipe.dish, len(breakdown),
        mass, serving["calories"], round(lo_cal), round(hi_cal))

    return {
        "fdc_id": None,
        "description": f"{recipe.dish} (estimated from its components)",
        "data_type": "component_estimate",
        "_match": COMPOSITE_MATCH,
        "basis": COMPOSITE_BASIS,
        "per100g": per100g,
        # The panel that makes "2 tacos" scale through the existing count path
        # without a line of new scaling code.
        "per_serving": serving,
        "serving_text": f"1 {recipe.unit_noun}",
        "serving_mass_g": mass,
        "serving_ml": None,
        # What this is an estimate OF, carried so the disclosure can say it and
        # the range can be shown rather than implied.
        "component_breakdown": breakdown,
        "component_unpriced": tuple(unpriced),
        "component_assumption": recipe.assumption,
        "calorie_low": round(lo_cal),
        "calorie_high": round(hi_cal),
    }
