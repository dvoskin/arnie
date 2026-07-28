"""Source authority, per food class, with honest provenance (directive §4–§8).

Three defects share one cause, and it is a single field called `source`.

**The ladder was fixed, and wrong for products.** Selection was
`memory or usda or off or web` — a constant order, so USDA answered for named
manufactured goods it has no label for. A shipped meal put Philadelphia scallion
cream cheese at 100 calories against a 60-calorie label and half a Starbucks
turkey bacon sandwich at 180 against 115, and those two items alone were 75% of
that meal's 33% overcount. The bagel and the salmon, which needed no branded
lookup, were both right. Authority has to depend on WHAT the food is.

**One field could not tell the truth.** `source` answered "who filled this row",
and every consumer read it as "who determined the calories". When the model's
calories were kept and USDA supplied only sodium, the card still said "From the
USDA database" — an attribution for numbers USDA never produced. Provenance is
per-ROLE here: who identified the product, who sized the portion, who determined
the macros, who filled the micros.

**The cache extended authority it never had.** The winner was recomputed as
`usda or off or web` at cache time, so the row written could disagree with the
row used, and a generic cache re-entered resolution claiming more than it had.

Nothing here fetches. It ranks what was fetched, and says truthfully where each
part of the answer came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

#: Everything that is not a letter or a digit, so a brand and the text it is
#: looked for in are compared on words rather than on characters.
_NON_WORD = re.compile(r"[^a-z0-9]+")


class FoodClass(str, Enum):
    """What KIND of thing this is, which decides which ladder applies."""
    MANUFACTURED = "manufactured"    # a named packaged product with a label
    RESTAURANT = "restaurant"        # a named menu item
    GENERIC = "generic"              # a whole food


#: §4, verbatim as ordered ladders. First available rung wins.
#:
#: The rungs are SOURCE KINDS, not the modules that produce them, so a new
#: fetcher slots in by declaring what kind of evidence it carries rather than by
#: being inserted at the right line of an if-chain.
LADDERS = {
    FoodClass.MANUFACTURED: (
        "barcode",            # exact barcode or user-entered label
        "user_label",
        "user_correction",    # confirmed user correction
        "manufacturer",       # official manufacturer nutrition page
        "branded_exact",      # exact verified branded database match
        "saved_product",      # verified saved product, compatible serving basis
        "usda_generic",       # generic fallback — DISCLOSED, never silent
        "estimate",
    ),
    FoodClass.GENERIC: (
        "user_correction",
        "user_label",
        "usda_exact",         # exact USDA / FoodData Central match
        "portion_ontology",   # category-specific portion ontology
        "estimate",           # disclosed
    ),
    FoodClass.RESTAURANT: (
        "user_correction",
        "restaurant_exact",   # exact restaurant AND exact menu item
        "restaurant_page",    # verified restaurant nutrition page
        "saved_restaurant",   # restaurant-specific saved food
        "component_estimate",  # component estimate WITH a range
    ),
}

#: Rungs that are a disclosed fallback rather than an answer. Reaching one is
#: not a failure, but presenting it silently is — §4 and §5 both turn on this.
FALLBACK_RUNGS = frozenset({"usda_generic", "estimate", "component_estimate",
                            "portion_ontology"})

#: Rungs that constitute a real branded answer for a manufactured product. In
#: strict mode a generic cache may never stand in for one of these without a
#: fresh lookup having been attempted first (§5).
BRANDED_RUNGS = frozenset({"barcode", "user_label", "manufacturer",
                           "branded_exact"})


@dataclass(frozen=True)
class SourceProvenance:
    """Who determined WHICH PART of the answer (§6).

    Separate fields because they are separately true. A turn can legitimately
    identify a product from a branded database, size the portion from the user's
    own words, take macros from the model, and fill micros from USDA — and there
    is no single string that describes that without lying about three of them.
    """
    identity_source: str = ""
    portion_source: str = ""
    primary_macro_source: str = ""
    micronutrient_source: str = ""
    display_source: str = ""
    confidence: float = 0.0
    food_class: str = FoodClass.GENERIC.value
    rung: str = ""

    @property
    def is_fallback(self) -> bool:
        return self.rung in FALLBACK_RUNGS

    @property
    def macros_are_estimated(self) -> bool:
        """The displayed calories and macros came from a model estimate rather
        than from any label or database."""
        return self.primary_macro_source in ("estimate", "llm", "")

    def as_dict(self) -> dict:
        return {
            "identity_source": self.identity_source,
            "portion_source": self.portion_source,
            "primary_macro_source": self.primary_macro_source,
            "micronutrient_source": self.micronutrient_source,
            "display_source": self.display_source,
            "confidence": round(float(self.confidence or 0.0), 3),
            "food_class": self.food_class,
            "rung": self.rung,
        }


def classify(food_name: str, *, brand: Optional[str] = None,
             is_packaged: bool = False,
             restaurant: Optional[str] = None) -> FoodClass:
    """Which ladder this food is judged on.

    Restaurant beats manufactured: "half a Starbucks turkey bacon sandwich" is a
    menu item, and the manufactured ladder would send it to a branded database
    that does not carry it.
    """
    if restaurant:
        return FoodClass.RESTAURANT
    name = (food_name or "")
    if _names_a_restaurant(name) or _names_a_restaurant(brand or ""):
        return FoodClass.RESTAURANT
    # The BRAND the interpreter supplied is the primary signal. `names_a_product`
    # reads caps, possessives and marks, which catches "Thomas'" and "M&Ms" and
    # misses a plain Title Case brand like "Philadelphia" — so a heuristic miss
    # must not be able to demote a product the interpreter already named.
    try:
        from skills.nutrition.branded import names_a_product
        product = bool(brand) or is_packaged or names_a_product(name)
    except Exception:
        product = bool(brand) or is_packaged
    return FoodClass.MANUFACTURED if product else FoodClass.GENERIC


#: Chains whose menu items have published nutrition. Data, not code: the
#: restaurant ladder differs from the manufactured one — a branded FOOD database
#: does not carry a chain's menu, so sending a menu item down the manufactured
#: ladder lands it on the generic fallback, which is how half a Starbucks turkey
#: bacon sandwich shipped at 180 calories against a published 115.
RESTAURANT_BRANDS = frozenset({
    "starbucks", "chipotle", "cava", "sweetgreen", "panera", "chick-fil-a",
    "chickfila", "mcdonald's", "mcdonalds", "subway", "dunkin", "wendy's",
    "wendys", "taco bell", "shake shack", "five guys", "in-n-out", "popeyes",
    "kfc", "domino's", "dominos", "pizza hut", "papa john's", "burger king",
    "olive garden", "cheesecake factory", "panda express", "qdoba",
})


def _words(text: str) -> str:
    """Lowercased, space-padded, punctuation flattened to single spaces.

    Both the haystack and the needle go through this, which is the only way a
    hyphenated or possessive brand survives the comparison: "chick-fil-a" and
    "mcdonald's" become "chick fil a" and "mcdonald s" on BOTH sides, so they
    still match, while "cava" stops matching inside "cavatappi".
    """
    return " " + _NON_WORD.sub(" ", (text or "").lower()).strip() + " "


def _names_a_restaurant(text: str) -> bool:
    """Does this name a chain whose menu has published nutrition?

    A BARE SUBSTRING TEST, WHICH MATCHED INSIDE WORDS.

    "cava" is a substring of cavatappi, cavatelli and cavatini, so a bowl of
    homemade cavatappi classified as RESTAURANT — and `candidate_map`
    deliberately seats USDA on NO rung for a restaurant food, because a branded
    food database has no row for a chain's menu item. The consequence is not a
    slightly worse match: it is USDA dropped entirely from a plain pasta dish
    that USDA answers exactly, leaving the model's estimate to commit.

    Same failure shape as the one this file already fixed for grocery brands,
    where `branded._named_grocery_brand` pads with spaces for exactly this
    reason. This is that fix, applied to the list that did not get it.
    """
    haystack = _words(text)
    return any(_words(brand) in haystack for brand in RESTAURANT_BRANDS)


def select(candidates: Mapping[str, Any], food_class: FoodClass) -> Tuple[
        str, Optional[Any]]:
    """`(rung, candidate)` — the highest rung this food's ladder actually has.

    Replaces `memory or usda or off or web`, which was one order for every food.
    A rung with no candidate is skipped; the returned rung name is what the
    disclosure and the cache both record, so the row written can never claim an
    authority the selection did not use.
    """
    for rung in LADDERS.get(food_class, LADDERS[FoodClass.GENERIC]):
        candidate = candidates.get(rung)
        # `is not None`, not truthiness: presence is the question, and a
        # candidate can legitimately be falsy. Testing truthiness silently
        # skipped a rung that was there, which is the same class of bug as the
        # fixed ladder — the answer coming from somewhere other than where the
        # ordering said it should.
        if candidate is not None:
            return rung, candidate
    return "", None


#: How a stored `user_food_matches.origin_tier` re-enters the ladder. A cache
#: row is a cache of OUR OWN earlier answer unless the user corrected it, so it
#: re-enters at the authority that produced it and never above.
_MEMORY_RUNG_BY_ORIGIN = {
    "user_label": "user_label",
    "user_regular": "user_correction",
    "branded_exact": "saved_product",
}


def branded_by_evidence(*, usda_candidate: Optional[Mapping[str, Any]] = None,
                        off_candidate: Optional[Mapping[str, Any]] = None
                        ) -> bool:
    """Do the LOOKUPS say this is a named product, whatever the name looked like?

    Deciding brandedness from the shape of a string is the weakest link in this
    whole path. "Milky Way Minis" carries no package noun, no trademark mark,
    no ampersand and no possessive, so every heuristic missed it — and being
    classified GENERIC meant `candidate_map` would not seat its Open Food Facts
    match on ANY rung, because OFF is only placed for MANUFACTURED. The receipt
    read "Checked Open Food Facts — found a match" directly above "Portion
    estimated", and both lines were accurate.

    Two independent sources settle it better than any regex over the name. A
    branded index matching well, while USDA's CURATED index cannot answer it
    exactly, is a named product. The generics hold their ground because USDA is
    exactly where they live: "white rice", "grilled chicken" and "chicken
    breast" are all exact there and stay generic, while a candy bar is in
    neither Foundation nor SR Legacy and is exact in OFF.

    Classification revised by evidence, not a wider guess about the string.
    """
    if off_candidate is None:
        return False
    if str(off_candidate.get("_match") or "") not in ("exact", "likely"):
        return False
    return str((usda_candidate or {}).get("_match") or "") != "exact"


def candidate_map(
    *,
    food_class: FoodClass,
    memory_match: Optional[Mapping[str, Any]] = None,
    usda_candidate: Optional[Mapping[str, Any]] = None,
    off_candidate: Optional[Mapping[str, Any]] = None,
    web_candidate: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Place each fetched candidate on the rung its evidence actually earns.

    Both the resolver and the cache write call this, which is the whole point of
    it existing: the winner recorded in `user_food_matches` is then the winner
    that was used, and cannot be a second, differently-computed answer (§8).

    A source absent from a class's ladder is not placed at all. USDA has no row
    for a chain's menu item, so on the restaurant ladder it is not a weaker
    answer — it is not an answer, and letting it compete is how half a Starbucks
    sandwich shipped at 180 calories against a published 115. It stays available
    as a micronutrient supplement; it just stops determining the calories.
    """
    out: dict = {}

    if memory_match is not None:
        origin = str(memory_match.get("origin_tier") or "").strip().lower()
        confirmed = bool(memory_match.get("user_confirmed")) or (
            memory_match.get("confidence") == "user-confirmed")
        if confirmed:
            rung = "user_correction"
        elif food_class is FoodClass.RESTAURANT:
            rung = "saved_restaurant"
        elif food_class is FoodClass.GENERIC:
            # A remembered generic is a cache of a USDA-grade answer, no more.
            rung = "usda_exact"
        else:
            # MANUFACTURED. A cache whose origin we cannot establish, or whose
            # origin was itself generic, is a generic standing in for a named
            # product — a DISCLOSED fallback, not a product answer. This is the
            # rung that let one generic lookup for "Peanut M&Ms" keep winning.
            rung = _MEMORY_RUNG_BY_ORIGIN.get(origin, "usda_generic")
        out[rung] = memory_match

    # One placement rule, in `rung_for_lane`. It used to be restated here and
    # derived differently by `promotion`, which is how a web answer could be
    # seated at `manufacturer` by the ladder and reported as `branded_exact` by
    # the promoted row's provenance.
    for lane, candidate in (("web_label", web_candidate),
                            ("off", off_candidate),
                            ("usda", usda_candidate)):
        if candidate is None:
            continue
        rung = rung_for_lane(lane, food_class,
                             match_grade=str(candidate.get("_match") or ""))
        if rung:
            out.setdefault(rung, candidate)

    return out


def rung_for_lane(lane: str, food_class: FoodClass, *,
                  match_grade: str = "") -> Optional[str]:
    """Which rung a candidate from this LANE earns, or None if it seats nowhere.

    The placement rule, stated once. `candidate_map` above applies it to
    fetched candidate dicts; `promotion` applies it to a resolution that
    already picked a winner and has only the lane's name. Both were deriving it
    separately, and they disagreed:

        a web_label answer carries tier BRANDED_EXACT, so a tier-keyed mapping
        called it `branded_exact` — "From the product label" — while the ladder
        seats a web candidate on `manufacturer`, "From the manufacturer's
        label". One answer, two sentences, decided by which module was asked.

    That is audit T-3 in miniature, and the reason this is a function rather
    than a second table: a lane's rung depends on the FOOD CLASS and, for Open
    Food Facts, on the match grade. USDA is the clearest case — the same lane
    is the answer on a generic food, a disclosed fallback on a manufactured
    one, and seats nowhere at all on a restaurant item.
    """
    lane = (lane or "").strip().lower()
    if lane in ("user_label", "barcode"):
        return lane
    if lane in ("history", "user_correction", "user_regular"):
        return "user_correction"
    if lane == "web_label":
        return ("restaurant_page" if food_class is FoodClass.RESTAURANT
                else "manufacturer")
    if lane == "off":
        # A branded index earns branded authority on a good match only; a weak
        # name hit is a guess wearing a database's name.
        if food_class is FoodClass.MANUFACTURED and \
                str(match_grade or "").lower() in ("exact", "likely"):
            return "branded_exact"
        return None
    if lane == "usda":
        if food_class is FoodClass.GENERIC:
            return "usda_exact"
        if food_class is FoodClass.MANUFACTURED:
            return "usda_generic"          # present, and disclosed for what it is
        return None                        # RESTAURANT: deliberately unplaced
    if lane in ("estimate", "provisional", "unresolved", ""):
        return "estimate"
    return None


def off_ladder(winner: Any, *fetched: Any) -> Optional[Any]:
    """The best fetched candidate that the ladder did NOT pick, if any.

    It lost the right to determine the calories. It did not lose the right to
    fill in sodium and the micronutrient panel — those are separate fields
    because they are separately true (§6), and dropping the panel to punish the
    row for being off-ladder would trade one inaccuracy for another.
    """
    for candidate in fetched:
        if candidate is None or candidate is winner:
            continue
        per100 = candidate.get("per100g") or {}
        if per100.get("calories"):
            return candidate
    return None


def needs_branded_lookup(food_class: FoodClass, rung: str, *,
                         strict: bool = False) -> bool:
    """Whether a fresh branded/manufacturer lookup must still run (§5, §6).

    Gated on the ROLE the current answer plays, never on a single coarse
    `source` field — that gate is what let an exact-looking USDA text match
    block an official manufacturer label.

    In strict mode a manufactured product that has only a fallback rung ALWAYS
    warrants the lookup, cache or no cache: a generic standing in for a named
    product is the failure this exists to prevent, and a cached one is the same
    failure made permanent.
    """
    if food_class is FoodClass.GENERIC:
        return False
    if rung in BRANDED_RUNGS:
        return False
    if strict:
        return True
    return rung in FALLBACK_RUNGS or not rung


#: §7. Keyed by who determined the DISPLAYED calories and primary macros — not
#: by whoever contributed something to the row.
_MACRO_SOURCE_DETAIL = {
    "user_label": "From the label you gave me",
    "user_correction": "From your correction",
    "barcode": "From the product barcode",
    "manufacturer": "From the manufacturer's label",
    "branded_exact": "From the product label",
    "restaurant_exact": "From the restaurant's published nutrition",
    "restaurant_page": "From the restaurant's published nutrition",
    "saved_product": "From your saved product",
    "saved_restaurant": "From your saved restaurant item",
    "usda_exact": "From the USDA database",
    "usda_generic": "Generic USDA data standing in for this product",
    "portion_ontology": "Portion estimated from typical serving sizes",
    "component_estimate": "Estimated from its components",
    "estimate": "Best estimate from the description",
}


def display_detail(provenance: SourceProvenance) -> str:
    """The one line shown under an item, and it must be true (§7).

    "From the USDA database" is reserved for the case where USDA determined the
    displayed calories and primary macros. When the model's numbers were kept
    and USDA only supplied micronutrients, that sentence is an attribution for
    numbers USDA never produced — so the supplement is described as a supplement.
    """
    macro = provenance.primary_macro_source
    micro = provenance.micronutrient_source

    if provenance.macros_are_estimated:
        if micro and micro not in ("estimate", "llm"):
            supplier = "USDA" if micro.startswith("usda") else "label"
            return (f"Portion estimated · nutrition profile supplemented with "
                    f"{supplier} data")
        return _MACRO_SOURCE_DETAIL["estimate"]

    detail = _MACRO_SOURCE_DETAIL.get(macro, "")
    if not detail:
        return ""
    # A generic answering for a named product is disclosed on the face of it,
    # never left to the confidence number to imply.
    if provenance.is_fallback and provenance.food_class != FoodClass.GENERIC.value:
        return detail
    return detail


def provenance_for(*, rung: str, food_class: FoodClass,
                   portion_source: str = "", micronutrient_source: str = "",
                   confidence: float = 0.0,
                   macros_from_source: bool = True) -> SourceProvenance:
    """Build the record from what the resolution actually did.

    `macros_from_source` is the honest switch: False means the winning source
    identified the food but its numbers were NOT used for the displayed
    calories and macros, which is exactly the case the old single field
    reported as though it were.
    """
    return SourceProvenance(
        identity_source=rung,
        portion_source=portion_source or "user_stated",
        primary_macro_source=rung if macros_from_source else "estimate",
        micronutrient_source=micronutrient_source,
        display_source=rung,
        confidence=confidence,
        food_class=food_class.value if isinstance(food_class, FoodClass)
        else str(food_class),
        rung=rung,
    )
