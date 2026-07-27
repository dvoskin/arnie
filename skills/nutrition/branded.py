"""Does this name identify a PRODUCT, or a food? (review 2026-07-25)

From the shipped transcript: "15 peanut m&m" was logged at 135 calories "from
the USDA database". A standard label puts 12 pieces at 140, so 15 is near 175.

The tier order was not the problem — `resolver.py` already ranks a branded
label above a generic row. The problem is one step earlier: **nothing ever
recognised "Peanut M&Ms" as a product**, so OpenFoodFacts (the branded label
database) and the web-label lane were never consulted, a generic row won
unopposed, and the resolver's own "generic standing in for a named product"
disclosure stayed silent too.

Two separate pieces of code were each blind in their own way:

  • `tool_executor._looks_branded` matched a capitalised token followed by a
    package noun — but the noun alternation was case-SENSITIVE and lowercase,
    while the interpreter emits Title Case. "Barebells Salty Peanut Protein
    Bar" did not match, because the pattern wanted "bar" and got "Bar". The
    safety net had been dead for every Title-Cased name it was written for.
  • `resolver._is_branded_request` asked only for an explicit brand, the
    is_packaged flag, or a product-family rule. "Peanut M&Ms" carries none of
    those, so the disclosure never fired.

Both now ask here, which is the point of the module: a product either is named
or it is not, and two layers disagreeing about that is how a named product gets
answered by a category average and presented with a label's confidence.

STRENGTH is the second half of the design, because the two callers are asking
different questions:

    WEAK+    which sources are worth consulting.  Being wrong costs one
             lookup that validation then discards.
    STRONG   whether to TELL the user a generic row is standing in for their
             product, and how wide to open the doubt band.  Being wrong here
             puts a false caveat on plain peanut butter.

A title-cased word in front of "butter" is enough to go look. It is not enough
to claim the user named a brand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: Signal strengths, ordered.
WEAK = 1
STRONG = 2


@dataclass(frozen=True)
class ProductSignal:
    """Why we think this is a product. Carried rather than reduced to a bool so
    a resolution log can say WHICH signal fired — "we searched OFF for chicken
    breast" is only debuggable if the reason travels."""
    reason: str
    strength: int
    detail: str = ""

    def __bool__(self) -> bool:
        return True


#: Package/format nouns. A brand-shaped token in front of one of these is worth
#: a branded lookup. Matched case-INSENSITIVELY — the bug this module exists to
#: fix was a lowercase alternation meeting Title Case input.
#: SINGULAR STEMS ONLY — both inflections are generated below. The old list
#: was written by hand in whatever form came to mind, so it carried "bagels"
#: without "bagel", "crackers" without "cracker", "tortillas" without
#: "tortilla" and "wrap" without "wraps". Half of every one of those pairs was
#: a silent miss, and "Royo Everything Bagel" is what that costs: no product
#: signal, no branded lookup, generic bagel macros on a named product.
_PACKAGE_NOUNS = (
    "bar", "shake", "drink", "protein", "yogurt", "yoghurt", "cereal", "oat",
    "granola", "sauce", "spread", "butter", "milk", "powder", "chip", "crisp",
    "cookie", "cracker", "bite", "puff", "cup", "pod", "seltzer", "soda",
    "juice", "creamer", "kombucha", "jerky", "wrap", "tortilla", "bread",
    "bagel", "waffle", "pancake", "ice cream", "gummy", "candy",
    # Bakery and noodle formats the hand-written list never reached. Each of
    # these arrived as a shipped miss on a correctly-named product:
    # "Legendary Cinnamon Roll", "Nissin Cup Noodles".
    "roll", "bun", "muffin", "croissant", "donut", "doughnut", "pretzel",
    "popcorn", "noodle", "ramen", "pasta", "burrito", "pizza", "oatmeal",
    "patty", "nugget", "sausage", "pastry", "brownie", "toaster pastry",
)


def _inflect(noun: str) -> tuple:
    """Both forms of one stem, so the list can never again be half-written."""
    if noun.endswith("y"):
        return (noun, noun[:-1] + "ies")
    if noun.endswith(("s", "x", "ch", "sh")):
        return (noun, noun + "es")
    return (noun, noun + "s")


_PACKAGE_NOUN_FORMS = sorted(
    {form for noun in _PACKAGE_NOUNS for form in _inflect(noun)},
    key=len, reverse=True)

#: The brand-shaped token must ACTUALLY be capitalised; only the package noun
#: is matched case-insensitively. A module-wide `re.I` applied to `[A-Z]` too,
#: so the capitalisation requirement had been void — "everything bagel", typed
#: in lowercase by a user who meant a plain bagel, matched the same pattern as
#: "Royo Everything Bagel". It went unnoticed only because the noun list was
#: missing half its inflections; completing the list surfaced it immediately.
_PACKAGE_NOUN_RE = re.compile(
    r"\b(?:[A-Z][\w'’]+\s+){1,4}(?i:" + "|".join(
        re.escape(n) for n in _PACKAGE_NOUN_FORMS) + r")\b")

#: An ampersand joining two word characters. M&M, Ben&Jerry, Barnes&Noble.
#: Essentially never occurs in a generic food name.
_AMPERSAND_RE = re.compile(r"\w\s*&\s*\w")

#: A possessive on a capitalised token: Reese's, Hershey's, Trader Joe's,
#: McDonald's, Thomas'. Strong, because generic foods do not own themselves.
_POSSESSIVE_RE = re.compile(r"\b([A-Z][\w’']*?)['’]s?\b")

#: Dishes whose name is possessive without naming a manufacturer. Without this
#: the possessive rule would put a "generic data for a named product" caveat on
#: shepherd's pie. Data, not code — a new one is a new entry.
_GENERIC_POSSESSIVES = {
    "shepherd", "shepherds", "cottage", "farmer", "farmers", "baker",
    "bakers", "devil", "angel", "hunter", "fisherman", "sailor", "cook",
    "confectioner", "grandma", "grandmas", "mom", "moms",
}

#: ALL-CAPS tokens that are units, abbreviations or shouting — not brands.
_CAPS_STOPWORDS = {
    "BBQ", "OJ", "PB", "PBJ", "AM", "PM", "XL", "L", "ML", "G", "KG", "OZ",
    "LB", "LBS", "TBSP", "TSP", "CAL", "KCAL", "IPA", "GF", "DF", "MCT",
    "AND", "OR", "WITH", "THE", "A", "I", "II", "III", "V",
}

_CAPS_RE = re.compile(r"\b[A-Z][A-Z0-9&'’.\-]{1,}\b")

#: Trademark and registered marks. If it is on the name, it is a product.
_MARK_RE = re.compile(r"[™®©]")

#: Token count at which a name ending in a package noun reads as a product LINE
#: rather than a description. Mirrors `api.usda._looks_branded`, which already
#: routes a query this long to USDA's Branded index first.
_PRODUCT_LINE_TOKENS = 4


def _all_caps_brand(name: str) -> Optional[str]:
    """An ALL-CAPS token that reads as a brand (KIND, RXBAR, GOLO, ONE).

    Requires the name to carry something else too: a bare "MILK" is someone
    shouting, not a product line.
    """
    tokens = name.split()
    if len(tokens) < 2:
        return None
    for token in tokens:
        bare = token.strip(".,()").upper()
        if bare in _CAPS_STOPWORDS or len(bare) < 2:
            continue
        if _CAPS_RE.fullmatch(token.strip(".,()")) and token.strip(".,()").isupper():
            return bare
    return None


def _possessive_brand(name: str) -> Optional[str]:
    for match in _POSSESSIVE_RE.finditer(name):
        stem = match.group(1)
        if stem.lower() in _GENERIC_POSSESSIVES:
            continue
        return stem
    return None


def _family_rule(brand: Optional[str], food_name: str):
    try:
        from skills.nutrition.families import rule_for
        return rule_for(brand, food_name)
    except Exception:
        return None


def _is_generic(food_name: str) -> bool:
    """A name whose every token is a category word ("protein bar", "a shake").

    Checked before any heuristic fires: "protein" is a package noun, so without
    this the WEAK rule would send every generic shake to a branded database.
    """
    try:
        from core.food_intelligence import is_generic_food_name
        return bool(is_generic_food_name(food_name))
    except Exception:
        return False


#: A SAFETY NET, NOT THE MECHANISM.
#:
#: The interpreter declares `branded` per item and does it in any language —
#: Простоквашино and Мираторг come back true, and it calls a Philadelphia
#: cheesesteak false by reasoning about the dish rather than matching a list.
#: That is where brand identification belongs: the model has world knowledge
#: and this file can only ever have the entries someone remembered to type.
#:
#: This list stays for the turns where the flag is missing — an older model, a
#: degraded parse, the fast path. It is a floor under those, and it should not
#: grow into a maintained brand database. If it starts needing regular
#: additions, the flag is not arriving and THAT is the bug to fix.
#:
#: Brands whose names are ORDINARY WORDS, so no shape heuristic can see them.
#:
#: `authority.classify`'s own docstring names the hole: the caps / possessive /
#: ampersand / trademark rules catch "Thomas'" and "M&Ms" and miss "a plain
#: Title Case brand like Philadelphia". The stated mitigation was that the
#: interpreter supplies `brand` or `is_packaged` — and when it does not, the
#: food is classified GENERIC, which has two consequences that look like broken
#: lookups:
#:
#:   • Open Food Facts is only SEATED for FoodClass.MANUFACTURED, so an exact
#:     OFF match is fetched, graded "exact", and then discarded.
#:   • the web lane is gated on `names_a_product`, so it never runs at all.
#:
#: A shipped turn: "Philadelphia Whipped Cream Cheese" — OFF returned the label
#: at 166.7 cal/100g, the ladder had no branded slot to put it in, and USDA's
#: generic answered instead.
#:
#: Data, not code, exactly like `authority.RESTAURANT_BRANDS` next door. Meant
#: to grow; a false positive costs one lookup that still has to survive
#: identity validation, a false negative costs the label entirely.
GROCERY_BRANDS = frozenset({
    # dairy / spreads
    "philadelphia", "breakstone", "tillamook", "sargento", "velveeta",
    "land o lakes", "chobani", "fage", "oikos", "yoplait", "activia",
    "silk", "oatly", "califia", "horizon", "organic valley", "daisy",
    # pantry / condiments
    "heinz", "hellmann", "skippy", "jif", "nutella", "smucker", "welch",
    "prego", "ragu", "classico", "barilla", "ronzoni", "goya", "hormel",
    "campbell", "progresso", "bushs", "rotel", "cholula", "tabasco",
    # snacks / cereal / bars
    "oreo", "cheerios", "pringles", "doritos", "cheetos", "ritz", "triscuit",
    "goldfish", "quaker", "kelloggs", "nature valley", "clif", "larabar",
    "pop tarts", "eggo", "nutrigrain", "wheat thins", "chex",
    # frozen / prepared
    "stouffer", "digiorno", "totino", "hot pockets", "lean cuisine",
    "birds eye", "green giant", "banza", "amy", "annie",
    # protein / drinks
    "gatorade", "powerade", "celsius", "zevia", "olipop", "poppi",
    "tropicana", "minute maid", "ocean spray", "la croix", "bubly",
    # meat / fish
    "tyson", "perdue", "applegate", "hillshire", "jimmy dean", "starkist",
    "bumble bee", "spam", "oscar mayer",
})


#: Brand names that are also PLACES or PEOPLE, and the dishes named after them.
#:
#: "Philadelphia cheesesteak" is a sandwich, not a Kraft product, and seating
#: the cream-cheese label on it would be a worse error than the generic it
#: replaces — a confident wrong number instead of a vague right one. The brand
#: only counts when the rest of the name is not naming a dish after the place.
_BRAND_IS_A_PLACE = {
    "philadelphia": ("cheesesteak", "cheese steak", "steak", "sub", "hoagie",
                     "sandwich", "roll", "pretzel"),
    "boston": ("cream pie", "lettuce"),
    "denver": ("omelet", "omelette"),
    "buffalo": ("wing", "wings", "sauce", "chicken"),
}


def _named_grocery_brand(name: str) -> Optional[str]:
    """The grocery brand this name carries, if any.

    Word-boundary matched, so "philadelphia cream cheese" hits. A brand that is
    also a place is withdrawn when the name goes on to describe that place's
    dish — see `_BRAND_IS_A_PLACE`.
    """
    lowered = f" {(name or '').lower()} "
    for brand in GROCERY_BRANDS:
        if not (f" {brand} " in lowered or f" {brand}s " in lowered
                or lowered.startswith(f" {brand}")):
            continue
        dishes = _BRAND_IS_A_PLACE.get(brand)
        if dishes and any(d in lowered for d in dishes):
            continue        # the place, not the manufacturer
        return brand
    return None


def product_signal(food_name: str, brand: Optional[str] = None,
                   is_packaged: bool = False) -> Optional[ProductSignal]:
    """The strongest reason to believe this names a product, or None.

    Order is by how much the signal is worth, not by cost — every check here is
    a regex over a short string, and returning the strongest reason keeps the
    logged explanation the true one.
    """
    name = (food_name or "").strip()
    if not name:
        return None

    if is_packaged:
        return ProductSignal("is_packaged", STRONG,
                             "the interpreter marked it packaged")
    if (brand or "").strip():
        return ProductSignal("explicit_brand", STRONG, brand.strip())

    rule = _family_rule(brand, name)
    if rule is not None:
        return ProductSignal("product_family", STRONG, rule.brand)

    if _MARK_RE.search(name):
        return ProductSignal("trademark_mark", STRONG, name)

    # A known brand whose name is an ordinary word. Checked with the other
    # STRONG marks because it is the same KIND of evidence — the name carries
    # a manufacturer — and it is the only one that can see "Philadelphia".
    known = _named_grocery_brand(name)
    if known:
        return ProductSignal("known_brand", STRONG, known)

    # A generic name can still carry no product at all — but it is checked
    # AFTER the explicit signals, because "Quest protein bar" is generic by
    # token and branded by rule, and the rule is the better evidence.
    generic = _is_generic(name)

    if _AMPERSAND_RE.search(name) and not generic:
        return ProductSignal("brand_mark", STRONG, "ampersand in the name")

    caps = _all_caps_brand(name)
    if caps and not generic:
        return ProductSignal("brand_mark", STRONG, f"all-caps token {caps!r}")

    possessive = _possessive_brand(name)
    if possessive and not generic:
        return ProductSignal("brand_mark", STRONG, f"possessive {possessive!r}")

    if generic:
        return None

    if _PACKAGE_NOUN_RE.search(name):
        # A long Title-Cased name ending in a package noun is a product line,
        # not a description: "Barebells Salty Peanut Protein Bar" carries no
        # ampersand, no caps token and no family rule, and it is unmistakably
        # a product. The same length test USDA's own branded-query heuristic
        # uses, so the two agree about what a product name looks like.
        if len(name.split()) >= _PRODUCT_LINE_TOKENS:
            return ProductSignal("product_line_name", STRONG,
                                 "a long product-shaped name")
        return ProductSignal("package_noun", WEAK,
                             "a capitalised word before a package noun")
    return None


def names_a_product(food_name: str, brand: Optional[str] = None,
                    is_packaged: bool = False) -> bool:
    """WEAK+. Worth consulting the branded sources for.

    The cost of a false positive is one OpenFoodFacts lookup whose result then
    has to survive identity validation like any other candidate. The cost of a
    false negative is the transcript this module is named after.
    """
    return product_signal(food_name, brand, is_packaged) is not None


def names_a_specific_product(food_name: str, brand: Optional[str] = None,
                             is_packaged: bool = False) -> bool:
    """STRONG only. The user named a manufactured product.

    Gates the "generic data standing in for a named product" disclosure and the
    widened doubt band. A WEAK signal must not reach here: telling someone
    their peanut butter was answered by generic data is both true and useless,
    and a caveat that fires on everything stops being read.
    """
    signal = product_signal(food_name, brand, is_packaged)
    return signal is not None and signal.strength >= STRONG
