"""Pricing a composite dish from its parts, against an external authority.

`component_estimate` has been the bottom rung of the RESTAURANT ladder since
`authority.py` was written, and `candidate_map` has never seated anything on
it. `COMPONENT_BREAKDOWN` has been in the ambiguity enum just as long, with
nothing producing one. `b835700` named the gap — *"pricing a dish from its
parts is the fix, and it is unbuilt"* — and measured what it costs: composite
totals drift 18-21% across logging modes, because there is nothing to drift
AGAINST. A dish falls to the model's estimate and the estimate is the only read
in the room.

The reason a composite has no authority is that no index has a row for it. USDA
has no taco. It has a corn tortilla, cooked pork shoulder, queso fresco and
salsa — all four measured, all four curated. **The dish is absent; its parts are
not.** So the authority for a composite is USDA, reached one ingredient at a
time.

What is ours and what is theirs is the whole design:

    ours    WHAT IS IN IT and ROUGHLY HOW MUCH — the table below. An
            assumption, disclosed as one, and the reason every recipe carries a
            light and a heavy mass rather than a single number.
    theirs  WHAT THOSE THINGS WEIGH PER CALORIE — fetched, never written down
            here. There is not one calorie figure in this file, and there must
            never be: the moment a number is hardcoded, "estimated from its
            components" stops being an external authority and becomes our guess
            wearing USDA's name.

That split is also why the output is a RANGE. Summing four typical masses
produces one number and the confidence of a measurement, which a dish does not
have. Summing the light ends and the heavy ends produces the two numbers that
are actually true — and that span is the thing the ask ladder has been missing
for `is_generic_food_name("burger")`, which is True and which nothing consults.

FAIL CLOSED. A recipe whose required parts cannot all be priced returns None
and seats nothing, leaving the model's estimate exactly as it was. A partial
sum is not a cheaper answer; it is a systematic UNDERCOUNT wearing a
provenance line that says four sources agreed. Half a taco priced as a taco is
worse than a taco we admit we guessed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

#: Everything that is not a letter or a digit, so a query and a USDA
#: description are compared on words rather than on characters.
_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Component:
    """One part of a dish, and the USDA generic that prices it.

    `query` is written in USDA's OWN house style — "Tortillas, corn", not "corn
    tortilla" — because that is what the index answers. USDA's curated
    descriptions read "Tortillas, ready-to-bake or -fry, corn", and a query
    phrased the way a person speaks scores 0.5 token coverage against it while
    the same words in USDA's order score 1.0. The table is addressed to the
    database, not to the user; `role` is the word the user sees.

    Three masses, not one. `grams` is the typical build, `light` and `heavy`
    are the same part at the ends of how it is actually made — and an OPTIONAL
    part is simply one whose light end is zero, which is how "might have
    cheese" is expressed without a second mechanism for it.
    """
    role: str
    query: str
    grams: float
    light: float
    heavy: float
    #: This part's identity follows a word in the dish name — "carnitas taco"
    #: is pork, "chicken taco" is chicken — resolved through `_PROTEIN_QUERIES`
    #: and falling back to `query` when the name says nothing.
    follows_name: bool = False
    #: The typical and light masses when the dish name NAMES this part. A plain
    #: quesadilla is cheese and tortilla; a chicken quesadilla has chicken in
    #: it, and the name saying so is the difference between a part that is
    #: usually absent and one that is certainly there. Without this the default
    #: build would have to be wrong in one direction for every dish that can go
    #: either way — and the LIGHT end matters just as much, or a named part
    #: still reads as possibly-absent and "chicken quesadilla" comes back with
    #: the identical range to "quesadilla".
    grams_when_named: Optional[float] = None
    light_when_named: Optional[float] = None

    @property
    def may_be_absent(self) -> bool:
        """A light end of zero IS the statement that this part might not be
        there — which is how "might have cheese" is expressed without a second
        mechanism for it. Distinct from contributing nothing to the DEFAULT
        build (`grams` of zero); a taco's salsa may be absent and is still part
        of the typical one."""
        return self.light <= 0


@dataclass(frozen=True)
class Recipe:
    """What one of a dish is made of.

    `garnish_g` is mass that carries no meaningful calories — lettuce, tomato,
    onion, cilantro, raw cabbage. It is here rather than as four more
    components because paying a network round-trip to learn that shredded
    lettuce is 15 cal/100g buys nothing, while leaving the mass out entirely
    would inflate the dish's per-100g density by a fifth. It contributes to
    what the dish WEIGHS and to nothing else.
    """
    key: str
    unit: str
    components: tuple
    garnish_g: float = 0.0

    @property
    def queries(self) -> tuple:
        return tuple(dict.fromkeys(c.query for c in self.components))


#: The protein a dish name names. Keyed on a word that appears in the food
#: name; the value is what USDA is asked for. A dish whose name says nothing
#: about the protein keeps the recipe's stated default, and the assumption line
#: says which one was used — an unnamed taco IS a beef taco to most people, and
#: pretending otherwise by refusing to price it helps nobody.
#: Every query is phrased to hit a CURATED row. USDA's SR Legacy names a
#: hamburger bun "Rolls, hamburger or hotdog, plain" — a query of "Bread,
#: hamburger roll" shares no head noun with it and would have matched nothing.
#: More specific first: "tuna" and "salmon" ahead of "fish", so a tuna poke
#: bowl is not priced as cod.
_PROTEIN_QUERIES = {
    "carnitas": "Pork, shoulder, cooked",
    "al pastor": "Pork, shoulder, cooked",
    "carnita": "Pork, shoulder, cooked",
    "pulled pork": "Pork, shoulder, cooked",
    "pork": "Pork, shoulder, cooked",
    "barbacoa": "Beef, chuck, cooked",
    "brisket": "Beef, brisket, cooked",
    "carne asada": "Beef, top sirloin, steak, cooked",
    "asada": "Beef, top sirloin, steak, cooked",
    "steak": "Beef, top sirloin, steak, cooked",
    "beef": "Beef, ground, cooked",
    "chicken": "Chicken, breast, meat only, cooked, roasted",
    "pollo": "Chicken, breast, meat only, cooked, roasted",
    "turkey": "Turkey, breast, meat only, cooked, roasted",
    "shrimp": "Crustaceans, shrimp, cooked",
    "salmon": "Fish, salmon, Atlantic, cooked",
    "tuna": "Fish, tuna, yellowfin, raw",
    "fish": "Fish, cod, Atlantic, cooked",
    "tofu": "Tofu, raw, firm",
    "bacon": "Pork, cured, bacon, cooked",
    "ham": "Ham, sliced",
    "falafel": "Falafel, home-prepared",
    "egg": "Egg, whole, raw, fresh",
}

#: Words that make a dish MEATLESS, so the protein component is not silently
#: priced as beef. Checked before `_PROTEIN_QUERIES`, because "veggie burrito"
#: contains no protein word and no reason to assume one.
_MEATLESS = ("veggie", "vegetarian", "vegan", "black bean", "bean", "tofu")

_TORTILLA_CORN = Component("corn tortilla", "Tortillas, corn", 26, 24, 48)
_TORTILLA_FLOUR = Component("flour tortilla", "Tortillas, flour", 72, 58, 95)
_RICE = Component("rice", "Rice, white, cooked", 120, 80, 190)
_BLACK_BEANS = Component("beans", "Beans, black, cooked", 85, 0, 130)
_CHEDDAR = Component("cheese", "Cheese, cheddar", 28, 0, 48)
_QUESO_FRESCO = Component("cheese", "Cheese, queso fresco", 12, 0, 22)
_AMERICAN = Component("cheese", "Cheese, pasteurized process, American", 21, 0, 42)
_SALSA = Component("salsa", "Salsa", 25, 0, 45)
_SOUR_CREAM = Component("sour cream", "Cream, sour, cultured", 28, 0, 55)
_GUACAMOLE = Component("avocado", "Avocados, raw", 30, 0, 60)
_MAYO = Component("spread", "Mayonnaise", 12, 0, 26)
_BUTTER = Component("cooking fat", "Butter, salted", 7, 0, 14)


def _protein(query: str, grams: float, light: float, heavy: float,
             when_named: Optional[float] = None,
             light_when_named: Optional[float] = None) -> Component:
    """The part whose identity the dish name decides."""
    return Component("protein", query, grams, light, heavy,
                     follows_name=True, grams_when_named=when_named,
                     light_when_named=light_when_named)


#: The table. Keys are matched as PHRASES against the food name, longest first,
#: so "burrito bowl" beats "burrito" and "cheeseburger" beats "burger".
#:
#: Nine dishes, not ninety. Every one of them decomposes into parts USDA's
#: curated sets actually carry, and every mass here is a build someone could
#: argue with — which is the point of the light/heavy pair. A dish with no
#: entry simply has no composite candidate and behaves exactly as it does
#: today; adding one is a table edit, not a code change.
_RECIPES: tuple = (
    Recipe("burrito bowl", "bowl", (
        _RICE,
        _BLACK_BEANS,
        _protein("Chicken, breast, meat only, cooked, roasted", 110, 85, 155),
        _CHEDDAR,
        _SALSA,
        _SOUR_CREAM,
        _GUACAMOLE,
    ), garnish_g=45),

    Recipe("burrito", "burrito", (
        _TORTILLA_FLOUR,
        _RICE,
        _BLACK_BEANS,
        _protein("Chicken, breast, meat only, cooked, roasted", 110, 85, 155),
        _CHEDDAR,
        _SALSA,
        _SOUR_CREAM,
    ), garnish_g=30),

    Recipe("quesadilla", "quesadilla", (
        Component("flour tortilla", "Tortillas, flour", 72, 55, 115),
        Component("cheese", "Cheese, cheddar", 55, 38, 90),
        _protein("Chicken, breast, meat only, cooked, roasted", 0, 0, 100,
                 when_named=75, light_when_named=50),
        _SALSA,
    ), garnish_g=15),

    Recipe("taco", "taco", (
        _TORTILLA_CORN,
        _protein("Beef, ground, cooked", 50, 38, 75),
        _QUESO_FRESCO,
        _SALSA,
    ), garnish_g=20),

    Recipe("cheeseburger", "burger", (
        Component("bun", "Rolls, hamburger", 50, 43, 72),
        _protein("Beef, ground, cooked", 85, 60, 155),
        Component("cheese", "Cheese, pasteurized process, American",
                  21, 21, 42),
        _MAYO,
    ), garnish_g=35),

    Recipe("burger", "burger", (
        Component("bun", "Rolls, hamburger", 50, 43, 72),
        _protein("Beef, ground, cooked", 85, 60, 155),
        _AMERICAN,
        _MAYO,
    ), garnish_g=35),

    Recipe("sandwich", "sandwich", (
        Component("bread", "Bread, white, commercially prepared", 56, 45, 92),
        _protein("Turkey, breast, meat only, cooked, roasted", 60, 40, 115),
        Component("cheese", "Cheese, cheddar", 21, 0, 42),
        _MAYO,
    ), garnish_g=25),

    Recipe("wrap", "wrap", (
        _TORTILLA_FLOUR,
        _protein("Chicken, breast, meat only, cooked, roasted", 85, 60, 130),
        _CHEDDAR,
        _MAYO,
    ), garnish_g=40),

    Recipe("omelette", "omelette", (
        Component("eggs", "Egg, whole, raw, fresh", 150, 100, 200),
        _BUTTER,
        _CHEDDAR,
    ), garnish_g=30),

    Recipe("poke bowl", "bowl", (
        _RICE,
        _protein("Fish, tuna, yellowfin, raw", 110, 80, 170),
        _GUACAMOLE,
        _MAYO,
    ), garnish_g=60),
)

#: Spellings that mean a dish already in the table. Data, not more recipes, so
#: the two can never drift apart.
_ALIASES = {
    "omelet": "omelette",
    "hamburger": "burger",
    "poke": "poke bowl",
    "quesedilla": "quesadilla",
}

_BY_KEY = {r.key: r for r in _RECIPES}
#: Longest phrase first — "burrito bowl" must be tried before "burrito", and
#: "cheeseburger" before "burger", or the shorter key steals the dish.
_MATCH_ORDER = tuple(sorted(
    list(_BY_KEY) + list(_ALIASES), key=lambda k: (-len(k), k)))


def _words(text: str) -> str:
    """Lowercased, punctuation flattened, space-padded on both ends.

    Both sides of every comparison go through this, which is what keeps
    "taco" from matching inside "tacos al pastor"'s neighbours by accident and,
    more importantly, keeps a phrase key like "burrito bowl" matching a name
    that punctuates it differently.
    """
    return " " + _NON_WORD.sub(" ", (text or "").lower()).strip() + " "


def _singular(word: str) -> str:
    """Crude, and correct on the words this module compares."""
    if word.endswith(("ses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set:
    return {_singular(w) for w in _words(text).split() if w}


def recipe_for(food_name: str) -> Optional[Recipe]:
    """The dish this name names, or None.

    Phrase matching against the padded name, longest key first. A name with no
    entry gets no composite candidate at all — which is the current behaviour
    for every food, and stays the behaviour for every food this table does not
    claim to know.
    """
    haystack = _words(food_name)
    for key in _MATCH_ORDER:
        if _words(key) in haystack or _words(key + "s") in haystack:
            return _BY_KEY[_ALIASES.get(key, key)]
    return None


def names_a_protein(food_name: str) -> bool:
    """Does the dish name say what is in it?

    "chicken quesadilla" does; "quesadilla" does not, and the difference
    decides whether the protein is part of the default build or merely
    possible.
    """
    haystack = _words(food_name)
    return any(_words(w) in haystack
               for w in list(_PROTEIN_QUERIES) + list(_MEATLESS))


def resolve_component(component: Component, food_name: str) -> str:
    """What to actually ask USDA for this part of THIS dish.

    A fixed part answers with its own query. The protein follows the name, so
    "two carnitas tacos" is priced on pork and "chicken tacos" on chicken —
    without which every taco in the table would be a beef taco and the whole
    exercise would be a more elaborate way of being wrong.
    """
    if not component.follows_name:
        return component.query
    haystack = _words(food_name)
    if any(_words(w) in haystack for w in _MEATLESS):
        return "Beans, black, cooked"
    for word, query in _PROTEIN_QUERIES.items():
        if _words(word) in haystack:
            return query
    return component.query


def component_grams(component: Component, food_name: str) -> tuple:
    """`(typical, light, heavy)` for this part in THIS dish."""
    named = component.follows_name and names_a_protein(food_name)
    grams = (component.grams_when_named
             if named and component.grams_when_named is not None
             else component.grams)
    light = (component.light_when_named
             if named and component.light_when_named is not None
             else component.light)
    return grams, light, component.heavy


#: Description words that mark a form nobody asked for. A component query is a
#: bare generic, so any of these appearing UNASKED is usually a different food:
#: "Chicken, breast, meat only, cooked, roasted" must not be answered by a
#: breaded row.
#:
#: What belongs here is a word that names a DIFFERENT FOOD, and what does not
#: is USDA's category for the right one. Both mistakes were made getting to
#: this list and each was silent in a different direction:
#:
#:   too wide   "sauce" and "salad" rejected the table's own components, because
#:              USDA files salsa under "Sauce, salsa, ready-to-serve" and
#:              mayonnaise under "Salad dressing, mayonnaise, regular". A dish
#:              that cannot price a part is not seated, so this failure looks
#:              exactly like a dish with no recipe.
#:   too narrow "Snacks, tortilla chips, plain, white corn" answers every word
#:              of "Tortillas, corn" and is 508 cal/100 g against a tortilla's
#:              218. It scored HIGHER than the real row — its description is one
#:              word shorter — and put 75 calories of corn chips in every taco.
#:              Coverage cannot catch it: "tortilla" there is a modifier on
#:              "chips", and no amount of token overlap knows that.
_WRONG_FORM = (
    # a different food that borrowed the word
    "chip", "chips", "snack", "snacks", "cracker", "crackers", "flour",
    "juice", "concentrate", "soup", "gravy", "casserole", "sandwich",
    "dinner", "stuffed", "pie", "imitation", "substitute", "powder",
    "powdered",
    # a different preparation
    "breaded", "battered", "batter", "fried", "canned", "dried", "dehydrated",
    "pickled", "candied", "infant", "baby",
    # a different formulation. The queries never ask for these, so blocking
    # them makes the full-fat row win by rule instead of by tie-break.
    "light", "lowfat", "low fat", "fat free", "nonfat", "reduced fat",
)

#: How much of the query's own vocabulary a row has to answer. Below this it is
#: a different food that shares a word.
_MIN_COVERAGE = 0.6
_MIN_SCORE = 1.5


def match_component_row(query: str, rows: Sequence[Mapping]) -> Optional[dict]:
    """The USDA row that actually answers this component query, or None.

    `food_intelligence.best_candidate` is the wrong tool here and failing to
    notice would have shipped this whole feature dark. Its length penalty is
    0.15 per unmatched description word, tuned for a user's phrasing against a
    curated description — and USDA's curated descriptions are LONG. "Tortillas,
    ready-to-bake or -fry, corn" carries five words the query never said, which
    costs 0.75 against a 1.2 floor before the match is even scored. A component
    table would have priced almost nothing and returned None all day, and None
    is indistinguishable from "this dish has no recipe".

    So the scoring here is tuned for the query this module actually sends: a
    bare generic in USDA's own word order, against a curated row.

      * the HEAD noun is mandatory. Coverage alone would let "Pork, shoulder,
        cooked" be answered by "Pork, ground, cooked" at two thirds — the same
        cut is not the same food, and the head is the part that cannot be
        traded away.
      * coverage of the remaining query words, so "shoulder" still has to be
        there.
      * a light length penalty, because a long curated description is normal
        rather than evidence of a bad match.
      * an unasked-for form is disqualifying, not merely expensive.
    """
    qt = _tokens(query)
    if not qt:
        return None
    head = _singular(_words(query).split()[0])
    best, best_score = None, 0.0
    for row in rows or []:
        description = str((row or {}).get("description") or "")
        per100 = (row or {}).get("per100g") or {}
        if per100.get("calories") is None:
            continue
        dt = _tokens(description)
        if head not in dt:
            continue
        coverage = len(qt & dt) / len(qt)
        if coverage < _MIN_COVERAGE:
            continue
        # Applied whatever the coverage. Exempting a perfect-coverage row was
        # the obvious way to protect "Salad dressing, mayonnaise, regular" from
        # the word "salad", and it let corn chips answer for a corn tortilla at
        # full coverage. The protection belongs in the LIST — a category word is
        # not a wrong form — not in a coverage exemption that also waves through
        # the rows this filter exists to stop.
        haystack, asked = _words(description), _words(query)
        if any(_words(f) in haystack and _words(f) not in asked
               for f in _WRONG_FORM):
            continue
        score = coverage * 3.0 - 0.03 * max(0, len(dt) - len(qt))
        if score > best_score:
            best, best_score = row, score
    return best if best_score >= _MIN_SCORE else None


@dataclass(frozen=True)
class PricedComponent:
    """One part, with the row that priced it. The row is kept so the receipt
    can name it — "cheese: Cheese, queso fresco" is checkable and "cheese: 38
    cal" is not."""
    role: str
    query: str
    matched: str
    grams: float
    light: float
    heavy: float
    calories_per_100g: float
    fdc_id: Optional[Any] = None

    def _at(self, grams: float) -> float:
        return self.calories_per_100g * grams / 100.0

    @property
    def calories(self) -> float:
        return self._at(self.grams)


#: What a composite sums. Sodium is NOT here and must not be: a dish's sodium
#: lives in the seasoning, the brine and the sauce, none of which this table
#: models, so a sum over the parts we DO know would be a confident undercount
#: of the one nutrient people restrict for medical reasons. The gold set
#: already says composite micros and sodium stay unknown; this is that rule
#: applied at the point the numbers are made.
_SUMMED = ("calories", "protein", "carbs", "fat", "fiber")


def price(recipe: Recipe, food_name: str,
          rows_by_query: Mapping[str, Sequence[Mapping]]) -> Optional[dict]:
    """Sum a dish from its priced parts, or None if any required part is missing.

    Returns a candidate in the SAME SHAPE the USDA and OFF adapters produce —
    `per100g`, `per_serving`, `serving_text`, `serving_mass_g` — so nothing
    downstream needs a special case for it. `analyze()` already knows how to
    treat "N of a thing that publishes its serving"; a composite publishes one,
    and the publisher is us saying so out loud.

    The extra keys are the honesty: `calorie_low` and `calorie_high` are the
    light and heavy builds of the SAME recipe, and `components` is the itemised
    list that lets a receipt show its working.
    """
    priced: list = []
    for component in recipe.components:
        query = resolve_component(component, food_name)
        grams, light, heavy = component_grams(component, food_name)
        row = match_component_row(query, rows_by_query.get(query) or ())
        if row is None:
            # A part with no mass in the default build — a plain quesadilla's
            # chicken — contributes nothing to price, so failing to price it
            # costs only the heavy end of the range. Everything else fails the
            # dish closed.
            if grams <= 0:
                continue
            logger.info(
                "event=composite_unpriced dish=%s role=%s query=%r — no USDA "
                "row answered it, so the dish is not seated",
                recipe.key, component.role, query)
            return None
        per100 = row.get("per100g") or {}
        priced.append((component, row, per100, grams, light, heavy))

    if not priced:
        return None

    mass = sum(p[3] for p in priced) + recipe.garnish_g
    if mass <= 0:
        return None

    per_serving = {}
    for key in _SUMMED:
        total = 0.0
        seen = False
        for _component, _row, per100, grams, _l, _h in priced:
            value = per100.get(key)
            if value is None:
                continue
            seen = True
            total += float(value) * grams / 100.0
        if seen:
            per_serving[key] = (round(total) if key == "calories"
                                else round(total, 1))
    if not all(k in per_serving for k in ("calories", "protein", "carbs", "fat")):
        # A part priced with no protein figure at all is a row we misread, not
        # a food with no protein. Refusing here is the same fail-closed rule as
        # a missing component.
        logger.info("event=composite_incomplete dish=%s keys=%s",
                    recipe.key, sorted(per_serving))
        return None

    low = sum((per100.get("calories") or 0) * light / 100.0
              for _c, _row, per100, _g, light, _h in priced)
    high = sum((per100.get("calories") or 0) * heavy / 100.0
               for _c, _row, per100, _g, _l, heavy in priced)

    components = tuple(
        PricedComponent(
            role=component.role,
            query=resolve_component(component, food_name),
            matched=str(row.get("description") or ""),
            grams=grams, light=light, heavy=heavy,
            calories_per_100g=float(per100.get("calories") or 0),
            fdc_id=row.get("fdc_id"))
        for component, row, per100, grams, light, heavy in priced)

    ratio = 100.0 / mass
    return {
        # No `fdc_id`: this is not a USDA record and must never be cached as
        # one. Four records answered it and none of them is the dish.
        "fdc_id": None,
        "description": f"{recipe.key} (estimated from its components)",
        "per100g": {k: round(v * ratio, 1) for k, v in per_serving.items()},
        "per_serving": dict(per_serving),
        "basis": "per_100g",
        "serving_text": f"1 {recipe.unit} ({round(mass)} g)",
        "serving_mass_g": round(mass, 1),
        # Never "exact". A dish assembled from four generics is a good estimate
        # and is not a measurement, and "likely" is the grade that says so
        # while still being trusted enough to determine the calories.
        "_match": "likely",
        "_composite": True,
        "dish": recipe.key,
        "unit": recipe.unit,
        "calorie_low": round(low),
        "calorie_high": round(high),
        "components": components,
    }


def assumption_line(candidate: Mapping) -> str:
    """The sentence that discloses what we assumed, for the receipt.

    Names the PARTS, not the arithmetic. "Estimated from its components" alone
    is a provenance label; this is the thing a user can disagree with, which is
    the only kind of disclosure worth printing.
    """
    components = candidate.get("components") or ()
    if not components:
        return ""
    parts = ", ".join(f"{c.role} {round(c.grams)}g" for c in components)
    low, high = candidate.get("calorie_low"), candidate.get("calorie_high")
    span = f" — {low}-{high} cal depending on the build" if (
        low is not None and high is not None and high > low) else ""
    return f"Priced as {parts}{span}"


async def price_from_usda(food_name: str, *, search) -> Optional[dict]:
    """Fetch every part of this dish concurrently and sum them, or None.

    `search` is injected — the same shape as `api.usda.search_food` — so this
    is testable without a network and so retrieval policy stays with the
    caller. A dish with no recipe costs one dict lookup and no round-trips,
    which is what makes it safe to ask this of every food.
    """
    import asyncio

    recipe = recipe_for(food_name)
    if recipe is None:
        return None
    queries = tuple(dict.fromkeys(
        resolve_component(c, food_name) for c in recipe.components))

    async def _one(query: str):
        try:
            return query, await search(query, page_size=8)
        except Exception as e:
            logger.warning("composite component lookup failed for %r: %s",
                           query, e)
            return query, []

    pairs = await asyncio.gather(*(_one(q) for q in queries))
    return price(recipe, food_name, dict(pairs))
