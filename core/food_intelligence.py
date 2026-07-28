"""
Food intelligence — turns a logged food into a coaching-grade analysis.

Combines the LLM's portion estimate with USDA FoodData Central nutrition data:
  - LLM is good at portion reasoning (calories/protein for the stated amount)
  - USDA is good at the exact nutrient profile (fiber, sugar, sodium, density)
We use the LLM's calories + USDA's per-100g calorie density to back out the
gram weight (no fragile quantity parsing), then derive the nutrients the LLM
usually omits, plus quality/satiety/density metrics for coaching.

Per-user 'food memory': confident matches are stored so a user's staples
(their usual Oikos shake, ground turkey, etc.) are recognized and reused.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Single-entry sodium plausibility bound, shared by every path that writes
# entry sodium (analyze() below, the Haiku micro-estimator fallback, and the
# serving-edit rescale in db.queries). A very salty restaurant meal tops out
# around 3-3.5g; one food entry beyond 4g means a bad match or a mis-scaled
# basis, not food. Was 5000 — tightened 2026-07-18 after garbage values in
# the 4-5g band slipped through (low-cal/100g salty foods × a big implied
# portion land there).
SODIUM_IMPLAUSIBLE_MG = 4000

#: How far an enriched row may EXCEED the model's own read before it is treated
#: as a wrong match rather than a correction.
#:
#: Deliberately loose. The model undercounts by ~19% on average (2026-07-03),
#: so upward correction is normally the enrichment doing its job and a tight
#: bound would undo it. 2.5x is not a correction of a 19% bias — it is a
#: different food. "Kazunori Hand Roll Set (6 piece)" committed at 4,404 cal
#: against the model's own ~1,200, and nothing looked up.
#:
#: Same multiple `promotion.LOUD_DELTA_MULTIPLE` already uses to flag a large
#: move, because it is the same judgement about the same kind of jump.
_OVERCOUNT_MULTIPLE = 2.5


# ── Food logging mode ──────────────────────────────────────────────────────────
# How aggressively Arnie confirms amounts/prep before logging. Three tiers:
#   quick     — log immediately, estimate freely, only ask on extreme variance
#   moderate  — the static FOOD_ACCURACY default (ask when it swings >120 cal)
#   strict    — always confirm cook method + quantity before logging anything ambiguous
# Maps a model- or user-written value (incl. relative "less"/"more" and synonyms)
# onto one of the three tiers. Unknown values fall back to "moderate".
_FOOD_MODES = {"quick", "moderate", "strict"}
_FOOD_QUICKER = {"quick", "quicker", "fast", "faster", "less", "fewer", "minimal",
                 "relaxed", "loose", "lenient", "lower", "easygoing", "chill"}
_FOOD_STRICTER = {"strict", "stricter", "careful", "more", "precise", "accurate",
                  "thorough", "higher", "exact", "detailed", "rigorous"}


def normalize_food_logging_mode(value, current: str = "moderate") -> str:
    """Map a model/user value onto a valid food-logging tier (quick/moderate/strict).

    Exact tier name → returned as-is. "balanced"/"default"/"normal" → moderate.
    Relative "less"/"more" (and synonyms) → one step toward quick/strict from the
    user's CURRENT tier, so "ask me less" always relaxes and never tightens.
    Anything unrecognized → moderate (the safe default)."""
    v = str(value or "").strip().lower()
    if v in _FOOD_MODES:
        return v
    if v in ("balanced", "default", "normal", "standard"):
        return "moderate"
    ladder = ["quick", "moderate", "strict"]
    cur = str(current or "moderate").strip().lower()
    if cur not in ladder:
        cur = "moderate"
    idx = ladder.index(cur)
    if v in _FOOD_QUICKER:
        return ladder[max(0, idx - 1)]
    if v in _FOOD_STRICTER:
        return ladder[min(len(ladder) - 1, idx + 1)]
    return "moderate"


def normalize_name(name: str) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"\b(\d+\s*(g|oz|cups?|tbsp|tsp|ml|servings?|slices?|pieces?))\b", "", n)
    n = re.sub(r"[^a-z0-9 ]", "", n).strip()
    return re.sub(r"\s+", " ", n)


# Generic food categories whose calories swing wildly by brand/recipe. A name made
# up ONLY of these words ("protein bar", "shake", "smoothie") is ambiguous — we must
# NOT silently reuse a previously-logged specific item or a USDA guess for it; the
# coach falls back to its own estimate (and, for brand-dependent items, asks which
# one first per the prompt). A name with any other (brand/qualifier) token —
# "built bar", "oikos shake", "chicken breast", "dark chocolate" — is specific
# enough to resolve normally, so it never lands here.
_GENERIC_FOOD = {
    # bars / packaged snacks (brand swings 100-400 cal)
    "bar", "protein", "granola", "energy", "cereal", "snack", "snacks",
    "cookie", "cookies", "brownie", "muffin", "donut", "doughnut", "pastry",
    "chips", "crackers", "cracker", "popcorn", "pretzels", "pretzel", "jerky",
    "candy", "chocolate", "gummies", "gummy", "nuts", "trail", "mix",
    "supplement", "supplements", "preworkout", "creatine", "powder", "scoop",
    # drinks (brand / prep dependent)
    "shake", "smoothie", "drink", "juice", "soda", "coffee", "tea", "latte",
    "cappuccino", "mocha", "americano", "macchiato", "espresso", "frappe",
    "frappuccino", "milkshake", "kombucha", "lemonade", "milk", "beer", "wine",
    "cocktail", "margarita", "alcohol", "creamer",
    # composite dishes (recipe dependent — USDA averages are meaningless here)
    "sandwich", "wrap", "bowl", "salad", "burrito", "taco", "quesadilla",
    "nachos", "burger", "pizza", "pasta", "noodles", "ramen", "curry", "soup",
    "stew", "stirfry", "sushi", "poke", "omelette", "omelet", "scramble",
    "toast", "bagel", "pancakes", "pancake", "waffles", "waffle", "oatmeal",
    "porridge", "casserole", "fries", "quiche", "dumplings", "bread", "roll",
    "biscuit", "scone", "patty",
    # dairy & dairy-adjacent (brand drives macros — Chobani 100 vs Fage 220)
    "yogurt", "yoghurt", "cheese", "cottage", "ricotta",
    # frozen desserts (Halo Top 280/pint vs Häagen-Dazs 1,200/pint)
    "ice", "cream", "icecream", "gelato", "sorbet", "sherbet", "froyo",
    # baked desserts (cheesecake vs angel food = ~5x range)
    "cake", "cupcake", "pie", "tart", "pudding", "mousse", "custard",
    # spreads / condiments / sauces (200-400 cal range from "a drizzle")
    "syrup", "jam", "jelly", "preserves", "spread", "spreads", "dip", "dips",
    "sauce", "sauces", "dressing", "dressings", "butter",
    "mayo", "mayonnaise", "hummus", "guac", "guacamole",
    # vague meal references
    "meal", "lunch", "dinner", "breakfast", "brunch", "food", "dish",
    "leftovers", "combo", "platter", "takeout", "serving", "piece", "plate",
    "cup", "handful", "portion", "plate",
}


_FOOD_FILLER = {"a", "an", "the", "some", "my", "of", "with", "1", "one", "2", "two"}


def is_generic_food_name(name: str) -> bool:
    """
    True if a food label is too generic to safely resolve from memory/USDA without
    clarifying (every meaningful token is a generic category word). "protein bar",
    "a shake", "some smoothie" → True; "built bar", "oikos", "banana" → False.
    Filler articles ("a", "the", "some") are ignored when deciding.
    """
    norm = normalize_name(name)
    if not norm:
        return False
    tokens = [t for t in norm.split() if t not in _FOOD_FILLER]
    if not tokens:
        return False
    return all(t in _GENERIC_FOOD for t in tokens)


def score_match(query: str, description: str) -> str:
    """exact | likely | estimated — how well a USDA result matches the query."""
    q = normalize_name(query)
    d = normalize_name(description)
    if not q or not d:
        return "estimated"
    qa, da = set(q.split()), set(d.split())
    if q == d:
        return "exact"
    # Containment counts as exact ONLY when the description adds almost
    # nothing: "roast turkey breast" inside "roast turkey breast and gravy,
    # frozen meal" is a composite dish wearing the query's name — the single
    # most consistent USDA wrong-row source (Danny 2026-07-24).
    if q in d and len(da) - len(qa) <= 1:
        return "exact"
    if q in d:
        return "likely"
    overlap = len(qa & da) / max(1, len(qa))
    if overlap >= 0.6:
        return "likely"
    return "estimated"


# Processed/altered forms that usually AREN'T what a user means by a bare food name.
_FORM_PENALTY = (
    "breaded", "fried", "dehydrated", "dried", "powder", "flour", "canned",
    "juice", "fortified", "infant", "baby", "pickled", "smoked", "cured",
    "candied", "syrup", "sauce", "concentrate",
    # Composite-dish markers: a bare food query must never match a full meal.
    "gravy", "frozen", "meal", "dinner", "casserole", "stuffed", "sandwich",
)


def best_candidate(query: str, candidates: list[dict]) -> tuple[Optional[dict], str]:
    """
    Pick the most canonical USDA match for a query and return (candidate, confidence).
    Favors high token-overlap + short/simple descriptions; penalizes processed
    forms not named in the query. Returns (None, 'estimated') if nothing is a
    good enough match (caller should then fall back to the LLM estimate).
    """
    if not candidates:
        return None, "estimated"
    q = normalize_name(query)
    qa = set(q.split())
    best, best_score = None, -999.0
    for c in candidates:
        d = normalize_name(c.get("description", ""))
        da = set(d.split())
        overlap = len(qa & da) / max(1, len(qa))
        score = overlap * 3.0
        score -= 0.15 * max(0, len(da) - len(qa))          # prefer concise descriptions
        for w in _FORM_PENALTY:
            if w in da and w not in qa:
                score -= 1.2                                # processed form not asked for
        if score > best_score:
            best, best_score = c, score
    conf = score_match(query, best.get("description", "")) if best else "estimated"
    # Gate: if even the best match is weak, don't trust USDA — fall back to estimate.
    if best_score < 1.2:
        return None, "estimated"
    return best, conf


@dataclass
class FoodAnalysis:
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    fdc_id: Optional[str] = None
    confidence: str = "estimated"          # exact|likely|estimated|user-confirmed
    source: str = "estimate"               # usda|memory|estimate|web_label
    protein_density: Optional[float] = None  # g protein per 100 kcal
    satiety: Optional[str] = None          # low|moderate|high
    quality: Optional[str] = None          # low|solid|excellent
    per100: dict = field(default_factory=dict)
    micros: dict = field(default_factory=dict)  # per-PORTION micronutrients → micronutrients_json
    micros_estimated: bool = False  # micros came from the LLM fallback, not a DB match
    coach_note: str = ""                   # the analysis line surfaced to the LLM
    enrichment_source: Optional[str] = None  # "memory" | "usda" | "web_label" | None
    #: Per-ROLE provenance (skills.nutrition.authority.SourceProvenance): who
    #: identified the food, who sized the portion, who determined the macros,
    #: who filled the micros. `source` above stays as the coarse legacy label
    #: the storage layer and the trend math already key on; the display reads
    #: THIS, because only this can distinguish a label that set the calories
    #: from a database that contributed sodium.
    provenance: Optional[object] = None


#: The word-grade confidences the enrichment path speaks in, as the number the
#: provenance record carries. Kept coarse on purpose — these are four states,
#: not a continuum, and inventing precision here would be the same offence the
#: rest of this module exists to stop.
_CONF_NUM = {
    "user-confirmed": 0.98,
    "exact": 0.9,
    "likely": 0.7,
    "estimated": 0.4,
}


def _derive(cal, protein, carbs, fat, fiber, sugar) -> tuple:
    """protein density, satiety tier, quality tier — simple, explainable heuristics."""
    pd = round((protein * 4 / cal) * 100, 0) if cal else None  # % of cal from protein
    # Satiety: protein + fiber drive fullness; sugar/fat dilute it per calorie.
    score = 0
    if cal:
        score += (protein / cal) * 1000          # protein per cal
        score += ((fiber or 0) / cal) * 1500      # fiber per cal
        score -= ((sugar or 0) / cal) * 400       # sugar penalty
    satiety = "high" if score >= 6 else ("moderate" if score >= 3 else "low")
    # Quality: protein density + fiber, minus heavy sugar.
    q = 0
    if pd and pd >= 30: q += 2
    elif pd and pd >= 18: q += 1
    if (fiber or 0) >= 4: q += 1
    if (sugar or 0) >= 25: q -= 1
    quality = "excellent" if q >= 3 else ("solid" if q >= 1 else "low")
    return pd, satiety, quality


def reconcile_macros(cal: float, protein: float, carbs: float, fat: float) -> tuple:
    """
    Enforce caloric consistency: protein*4 + carbs*4 + fat*9 must ≈ total calories.
    The LLM often submits internally inconsistent macros (e.g. 500 cal but macros
    that sum to 720 cal). Strategy: trust calories and protein (most diet-critical),
    then rebalance carbs/fat proportionally to fill the remaining caloric budget.
    Returns corrected (cal, protein, carbs, fat).
    """
    if cal <= 0 or (protein == 0 and carbs == 0 and fat == 0):
        return cal, protein, carbs, fat

    macro_cal = protein * 4 + carbs * 4 + fat * 9
    if macro_cal <= 0:
        return cal, protein, carbs, fat

    # If macros are within 15% of stated calories, accept as-is (small rounding ok)
    if abs(macro_cal - cal) / cal <= 0.15:
        return cal, protein, carbs, fat

    # Macros are inconsistent — trust calories and protein, rescale carbs+fat.
    protein_cal = protein * 4
    remaining = cal - protein_cal
    if remaining < 0:
        # Protein alone exceeds calories — protein must be wrong too; scale everything
        scale = cal / macro_cal
        protein = round(protein * scale, 1)
        carbs = round(carbs * scale, 1)
        fat = round(fat * scale, 1)
        return cal, protein, carbs, fat

    carb_fat_cal = carbs * 4 + fat * 9
    # A ZERO MACRO IS AN ABSENCE, NOT A MEASUREMENT.
    #
    # The rebalance below is multiplicative, so `fat * scale` keeps a zero at
    # zero for every scale, and the entire shortfall is pushed into whichever
    # macro happened to be non-zero. A chocolate sweet roll submitted at 210
    # cal / 20 P / 24 C / 0 F came back (210, 20, 32.5, 0.0): 34 unexplained
    # calories — about 3.8 g of fat — became carbohydrate, and the item stayed
    # fat-free on a product that cannot be.
    #
    # This is the butter-at-zero-calories shape (aad3416) one level down. That
    # fix taught the system to doubt a zero CALORIE count; a zero MACRO had the
    # same hole, and `sanity.check_values` bounds energy density from above
    # only, so a too-low macro passes every check we have.
    #
    # Placed only when the shortfall is worth at least a whole gram, and only
    # when exactly one of the two is missing: with both zero the `elif` below
    # already places the residual, and with neither zero, scaling is the right
    # answer. A genuinely fat-free food is protected by the 15% band above —
    # this branch is only reachable once the macros are already inconsistent.
    unexplained = remaining - carb_fat_cal
    if carb_fat_cal > 0 and fat == 0 and carbs > 0 and unexplained >= 9:
        fat = round(unexplained / 9, 1)
    elif carb_fat_cal > 0 and carbs == 0 and fat > 0 and unexplained >= 4:
        carbs = round(unexplained / 4, 1)
    elif carb_fat_cal > 0:
        scale = remaining / carb_fat_cal
        carbs = round(carbs * scale, 1)
        fat = round(fat * scale, 1)
    elif remaining > 0:
        # No carb/fat data — put residual in carbs (safe fallback)
        carbs = round(remaining / 4, 1)

    return cal, protein, carbs, fat


def _mass_from_serving_panel(quantity, src, food_name: str):
    """Grams implied by eating N of the SOURCE'S OWN serving unit, or None.

    The gap this closes is the reason a Legendary Foods sweet roll logged at
    190 calories against a published 210. `analyze` only used a source's
    numbers when the quantity was an explicit MASS — "200g", "6 oz" — and took
    the estimate path for everything else, keeping the model's calories and
    borrowing only micros. But "1 roll" and "1 bar" are not vague portions.
    They are exactly one of the thing the label describes, and a label consumed
    at one serving determines the answer completely.

    So most branded logging — which is done in whole servings, because that is
    how packaged food is eaten — was resolving as an estimate with a label
    fetched, consulted for sodium, and discarded for calories.

    Two conditions, both necessary:

      * the portion is a COUNT on a UNIT basis. `count_basis` is the gate from
        the count-as-serving work: a bar is the label's own unit, a bowl is a
        helping we estimated a mass for, and only the first may be multiplied
        by a serving.
      * the panel's count unit answers the portion's. "15 pieces" against a
        panel of "12 pieces" is the same object; "15 pieces" against "1 bar" is
        not, and scaling one by the other turns a portion into a package.

    Returns None whenever either is unmet — which leaves the estimate path
    exactly as it was, rather than inventing a mass.
    """
    try:
        from skills.nutrition.models import COUNT_BASIS_UNIT
        from skills.nutrition.normalize import (count_units_compatible,
                                                normalize_quantity,
                                                serving_unit_mass)
        panel = (src or {}).get("serving_text") or ""
        package = (src or {}).get("package_text") or ""
        if not panel and not package:
            return None
        q = normalize_quantity(quantity or "", food_name)
        if q.count is None or q.count <= 0:
            return None
        if q.count_basis != COUNT_BASIS_UNIT:
            return None
        if not panel:
            # NO SERVING PANEL, BUT A NET WEIGHT. For a single-serve product
            # the package is the serving, which is why so many of them publish
            # no panel. N of the product's own unit is therefore N package
            # weights — the same reasoning as a "1 roll (57 g)" panel, reached
            # from the other field. A multipack ("6 x 44 g") does not parse to
            # a single mass and so returns None rather than guessing.
            from core.portions import mass_grams
            whole = mass_grams(package)
            if whole is None or whole <= 0:
                return None
            return round(float(q.count) * float(whole), 1)

        per_unit = serving_unit_mass(panel)
        if per_unit is not None:
            # The panel enumerates its serving — "35 g (12 pieces)". Scaling is
            # only valid when its count unit answers the portion's: 15 pieces
            # against 12 pieces is the same object, 15 pieces against 1 bar is
            # not, and multiplying one by the other turns a portion into a
            # package.
            grams, panel_unit = per_unit
            if not count_units_compatible(q.unit or "", panel_unit or ""):
                return None
            return round(float(q.count) * float(grams), 1)

        # A SINGLE-SERVING PANEL. "1 roll (57 g)", "57g" — the serving IS one
        # unit, so there is no count to match against and none needed.
        # `serving_unit_mass` returns None here by design: it enumerates, and
        # there is nothing to enumerate.
        #
        # This is the common branded shape and the reason a Legendary Foods
        # sweet roll stayed an estimate. `_serving_count` only recognises units
        # it has a word for, and "roll" is not one — but the panel does not
        # need to name the unit for "one serving weighs 57 g" to be true.
        from skills.nutrition.normalize import _SERVING_MASS_RE, _serving_count
        found = _SERVING_MASS_RE.search(panel)
        if not found:
            return None
        enumerated = _serving_count(panel)
        if enumerated is not None and enumerated[0] != 1:
            return None
        mass = float(found.group(1))
        if mass <= 0:
            return None
        return round(float(q.count) * mass, 1)
    except Exception:
        return None


def _per_serving_for(quantity, src, food_name: str):
    """The label's per-serving panel scaled by the number of servings eaten,
    or None when this portion is not a count of the product's own units.

    The gate is the same one `_mass_from_serving_panel` uses and for the same
    reason: `count_basis` distinguishes a bar (the label's unit, multipliable
    by a serving) from a bowl (a helping we estimated a mass for, not
    multipliable). Without that gate "1 bowl of cereal" would silently become
    one 30 g serving.
    """
    try:
        panel = (src or {}).get("per_serving")
        if not isinstance(panel, dict) or not panel:
            return None
        from skills.nutrition.models import COUNT_BASIS_UNIT
        from skills.nutrition.normalize import normalize_quantity
        q = normalize_quantity(quantity or "", food_name)
        if q.count is None or q.count <= 0:
            return None
        if q.count_basis != COUNT_BASIS_UNIT:
            return None
        n = float(q.count)
        out = {}
        for key, value in panel.items():
            if value is None:
                continue
            scaled = value * n
            out[key] = round(scaled) if key == "sodium" else round(scaled, 1)
        for required in ("calories", "protein", "carbs", "fat"):
            if required not in out:
                return None
        out["calories"] = round(out["calories"])
        return out
    except Exception:
        return None


def analyze(name, quantity, llm_cal, llm_protein, llm_carbs, llm_fat,
            usda_candidate=None, memory_match=None,
            web_candidate=None, off_candidate=None,
            is_packaged=False, brand=None, restaurant=None) -> FoodAnalysis:
    """
    Build a FoodAnalysis. Which source answers depends on WHAT THE FOOD IS —
    `skills.nutrition.authority` holds one ladder per food class and this
    function walks the one that applies (directive §4).

    The old order was a constant, `memory or usda or off or web`, for every food
    alike. USDA has no label for a named manufactured good and no row at all for
    a chain's menu item, so on both it answered from the nearest generic: a
    shipped meal put Philadelphia scallion cream cheese at 100 calories against
    a 60-calorie label and half a Starbucks turkey bacon sandwich at 180 against
    a published 115, and those two lines alone were three quarters of that
    meal's 33% overcount. The bagel and the salmon, needing no branded lookup,
    were both right — which is the tell that the ladder, not the lookup, was
    what failed.

    A candidate the ladder does not seat still fills fiber/sugar/sodium and the
    micronutrient panel; it just stops determining the calories, and the
    provenance says so per role rather than through one `source` string that
    could only be true about one of them (§6, §7).

    The LLM's calories/protein anchor the portion unless the quantity is an
    explicit mass and the winner is trustworthy. web_candidate carries the same
    shape as usda_candidate ({"fdc_id": …, "per100g": {...}, "_match": …}).
    """
    from skills.nutrition import authority
    cal = float(llm_cal or 0)
    protein = float(llm_protein or 0)
    carbs = float(llm_carbs or 0)
    fat = float(llm_fat or 0)

    # Enforce macro/calorie consistency before USDA enrichment.
    # Invalid macros (protein*4 + carbs*4 + fat*9 ≠ calories) mislead the coaching
    # note and confuse the LLM on follow-up turns.
    cal, protein, carbs, fat = reconcile_macros(cal, protein, carbs, fat)
    # The model's independent read, pre-enrichment — the disagreement demotion
    # below compares the database read against it.
    _llm0 = (cal, protein, carbs, fat)
    fiber = sugar = sodium = None
    fdc_id = None
    confidence = "estimated"
    source = "estimate"
    per100 = {}
    micros: dict = {}
    _implied_grams = None

    # Which ladder, then which rung. `select` skips a rung with no candidate and
    # returns the name of the one it took, so the disclosure, the cache row and
    # the numbers all name the same winner.
    food_class = authority.classify(name, brand=brand, is_packaged=is_packaged,
                                    restaurant=restaurant)
    _cands = authority.candidate_map(
        food_class=food_class, memory_match=memory_match,
        usda_candidate=usda_candidate, off_candidate=off_candidate,
        web_candidate=web_candidate)
    rung, src = authority.select(_cands, food_class)
    # Nothing the ladder would seat. A candidate it refused — USDA against a
    # Starbucks sandwich, say — may still fill the nutrient panel; it just does
    # not get to set the calories, and `macros_from_source=False` is what keeps
    # the card from crediting it with numbers it did not produce.
    macros_from_source = src is not None
    if src is None:
        src = authority.off_ladder(None, usda_candidate, off_candidate,
                                   web_candidate)
    micro_rung = rung if macros_from_source else (
        "usda_generic" if src is usda_candidate else
        "branded_exact" if src is off_candidate else
        "manufacturer" if src is web_candidate else "")
    computed_forward = False
    if src is not None:
        per100 = src.get("per100g") or {
            "calories": src.get("cal_100"), "protein": src.get("protein_100"),
            "carbs": src.get("carbs_100"), "fat": src.get("fat_100"),
            "fiber": src.get("fiber_100"), "sugar": src.get("sugar_100"),
            "sodium": src.get("sodium_100"),
        }
        cal100 = per100.get("calories")
        fdc_id = src.get("fdc_id")
        # Identity-based so the label matches the winner under the new priority.
        if src is memory_match:
            source = "memory"
            confidence = "user-confirmed" if memory_match.get("user_confirmed") else (memory_match.get("confidence") or "likely")
        elif src is usda_candidate:
            source = "usda"
            confidence = src.get("_match", "likely")
        elif src is off_candidate:
            source = "off"                      # Open Food Facts label data
            confidence = src.get("_match", "likely")
        else:
            source = "web_label"
            # Web hits for packaged products are typically the actual label data.
            confidence = src.get("_match", "likely")

        from api.usda import MICRO_KEYS as _MICRO_KEYS

        # GROUND-TRUTH PATH — when the quantity is an explicit mass ("200g",
        # "6 oz") AND we have a trustworthy per-100g density, the whole nutrient
        # profile is DETERMINED (grams × density); there's nothing to estimate.
        # Compute it forward and IGNORE the LLM's calories/macros — calibration
        # (2026-07-03) showed the model undercounts calories ~19% even when
        # confident, and backing grams out of that low number propagated the
        # miss into every derived nutrient. This only fires when we actually
        # have the grams + a solid match, so pure-estimate foods (already
        # accurate) are untouched — no blanket multiplier, no overcorrection.
        from core.portions import mass_grams
        _mg = mass_grams(quantity)
        # No stated mass, but the source may know what one of its own servings
        # weighs — and the user may have eaten exactly N of them. That is a
        # KNOWN mass, not an estimate, and treating it as one is what lets a
        # label's calories reach the card for "1 bar".
        _from_panel = False
        if not _mg:
            _mg = _mass_from_serving_panel(quantity, src, name)
            _from_panel = _mg is not None
        # USDA text-matches must be NEAR-IDENTICAL to override the model (Danny
        # 2026-07-23: "don't use USDA unless there's an almost identical name
        # match") — a "likely" 0.6-token-overlap hit is exactly the wrong-cousin
        # class (lean chicken for "chicken shawarma"). Label-grade sources
        # (memory / OFF / web) keep their "likely" trust; a demoted USDA item
        # still feeds the estimate path (fiber/sodium scaled to the model's
        # calories) and stays eligible for the web-label lane.
        _trustworthy = macros_from_source and (
            confidence in ("exact", "user-confirmed")
            or (confidence == "likely" and src is not usda_candidate))
        # ── N SERVINGS OF A PRODUCT THAT PUBLISHES ITS SERVING ──────────────
        #
        # Checked FIRST, because when it applies there is nothing to compute.
        # "1 bar", "1 bagel", "1 set", "2 slices" of a labelled product is
        # count x the label's own per-serving panel — no mass, no density, no
        # ratio, and so nothing for the model's calorie guess to anchor.
        #
        # That guess anchoring the mass is the root defect under every wrong
        # branded number in this file's history: with no serving size to scale
        # by, `grams` came out of the model's calories and the label was then
        # scaled to FIT the guess rather than correct it. This removes the
        # derivation entirely for the case that covers most branded logging,
        # because packaged food is eaten in whole servings.
        #
        # Same gate as the serving-panel path: a COUNT on a UNIT basis. A bowl
        # is a helping we estimated a mass for and may not be multiplied by a
        # serving; a bar is the label's own unit and may.
        _ps = _per_serving_for(quantity, src, name) if _trustworthy else None
        if _ps is not None:
            cal, protein, carbs, fat = _ps["calories"], _ps["protein"], \
                _ps["carbs"], _ps["fat"]
            fiber = _ps.get("fiber", fiber)
            sugar = _ps.get("sugar", sugar)
            sodium = _ps.get("sodium", sodium)
            computed_forward = True
        elif _mg and cal100 and cal100 > 0 and _trustworthy:
            grams = _mg
            ratio = grams / 100.0
            _implied_grams = grams
            cal = round(cal100 * ratio)
            if per100.get("protein") is not None: protein = round(per100["protein"] * ratio, 1)
            if per100.get("carbs") is not None:   carbs = round(per100["carbs"] * ratio, 1)
            if per100.get("fat") is not None:      fat = round(per100["fat"] * ratio, 1)
            if per100.get("fiber") is not None:   fiber = round(per100["fiber"] * ratio, 1)
            if per100.get("sugar") is not None:   sugar = round(per100["sugar"] * ratio, 1)
            if per100.get("sodium") is not None:  sodium = round(per100["sodium"] * ratio, 0)
            for _mk in _MICRO_KEYS:
                _v = per100.get(_mk)
                if _v is not None:
                    micros[_mk] = round(_v * ratio, 2)
            computed_forward = True
            # DISAGREEMENT DEMOTION (Danny 2026-07-23 — "chicken shawarma" 4 oz:
            # model read 220 cal, USDA text-match was a plain lean chicken record
            # and the mass path confidently wrote 138). The forward-computed value
            # and the model's estimate are two INDEPENDENT reads; when the USDA
            # read UNDERCUTS the model by >30%, the matched density almost
            # certainly belongs to a leaner cousin of the dish — two disagreeing
            # reads = LOW confidence. Keep the model's numbers, demote to
            # source="estimate", and the web-enrich lane (tool_executor fires on
            # source=="estimate") fetches a label-grade read. Applies ONLY to
            # USDA text-matches: the user's own history and label-grade web/OFF
            # data stay authoritative, and upward correction stays (the model
            # undercounts ~19%, 2026-07-03).
            # PROFILE-FLIP GUARD (Danny 2026-07-24, entry 2283): 6.5 oz roast
            # turkey enriched to 614 cal / 0g protein / 123g carbs — a wrong
            # USDA row turned a protein food into a grain. A match that
            # COLLAPSES the dominant macro is a wrong row, whatever its name
            # score: protein >=15g in the model's read shrinking below 30%
            # triggers the same demotion as a low-calorie disagreement.
            _profile_flip = (_llm0[1] >= 15 and protein < 0.3 * _llm0[1])
            # ── THE GUARD ONLY EVER LOOKED DOWN, AND ONLY AT USDA ───────────
            #
            # A shipped meal put "Kazunori Hand Roll Set (6 piece)" on the
            # board at 4,404 cal and 0 g PROTEIN — six hand rolls, against a
            # true ~1,200 and ~54 g. The coaching was then written FROM that
            # row: "that sashimi was mostly fat", which is what 0 g protein
            # means. When the user pushed back the model answered 1,200 / 54
            # immediately, so the right number was never in doubt; the write
            # path preferred the wrong one.
            #
            # Neither half of this guard could catch it:
            #
            #   * `cal < 0.7 * model` tests ONE DIRECTION. A row that
            #     OVERSTATES by 4x was committed in silence. The asymmetry was
            #     deliberate once — the model undercounts ~19%, so upward
            #     correction is usually right — but "usually right" stops
            #     applying somewhere, and 3x is well past it. No estimate is
            #     improved by tripling it.
            #   * `src is usda_candidate` scoped BOTH halves to USDA. A
            #     collapsed dominant macro is evidence of a wrong ROW, and a
            #     row is no likelier to be right because it came from a
            #     branded index or a scraped page — the web lane in particular
            #     has a documented history of finding the wrong product.
            #
            # So: the profile flip now applies to whoever supplied the numbers,
            # and the calorie test is two-sided. The undercount bound stays
            # USDA-only, keeping the "model undercounts" asymmetry exactly
            # where it was argued for.
            _overshoot = cal > _OVERCOUNT_MULTIPLE * _llm0[0]
            if (_llm0[0] > 0
                    and (_profile_flip
                         or _overshoot
                         or (src is usda_candidate and cal < 0.7 * _llm0[0]))):
                logger.info(
                    f"enrichment demoted: {source} {cal} cal / {protein}g protein "
                    f"vs model {_llm0[0]} / {_llm0[1]}g for {(name or '')!r} — "
                    f"{'profile flip' if _profile_flip else 'overcount' if _overshoot else 'undercount'}"
                    f", keeping estimate + web lane")
                cal, protein, carbs, fat = _llm0
                grams = cal / cal100 * 100
                _implied_grams = grams
                ratio = grams / 100.0
                fiber = round(per100["fiber"] * ratio, 1) if per100.get("fiber") is not None else None
                sugar = round(per100["sugar"] * ratio, 1) if per100.get("sugar") is not None else None
                sodium = round(per100["sodium"] * ratio, 0) if per100.get("sodium") is not None else None
                micros = {mk: round(per100[mk] * ratio, 2)
                          for mk in _MICRO_KEYS if per100.get(mk) is not None}
                confidence, source = "estimated", "estimate"
                computed_forward = False
        elif cal100 and cal100 > 0 and cal <= 0:
            # A ZERO IS AN ABSENCE, NOT A MEASUREMENT.
            #
            # Every branch here needed `cal > 0`, so a model that reported no
            # calories fell through ALL of them and the row committed at zero
            # — with `source` still naming whoever won the ladder. Butter
            # logged as 0 calories on a card reading "From the USDA database",
            # while the USDA row sat right there at 717 per 100 g. The number
            # was not enriched, not estimated and not refused; it was simply
            # never touched.
            #
            # Nothing downstream could catch it either. `sanity.check_values`
            # bounds energy density from ABOVE — the 588-calorie tablespoon of
            # peanut butter — and zero passes every check it makes, correctly,
            # because water and black coffee are real foods that really are
            # zero. What makes THIS zero impossible is not the number on its
            # own: it is a zero standing next to a source that says otherwise.
            #
            # So the source answers. Its per-100g and a mass fully determine
            # the portion, and `normalize_quantity` reaches masses `mass_grams`
            # cannot — piece weights, densities, the portion ontology — which
            # is what makes "1 tbsp" answerable at all.
            _zero_g = None
            try:
                from skills.nutrition.normalize import normalize_quantity as _nq
                _zero_g = _nq(quantity or "", name or "").grams
            except Exception:
                _zero_g = None
            if _zero_g and _trustworthy:
                ratio = _zero_g / 100.0
                _implied_grams = _zero_g
                cal = round(cal100 * ratio)
                if per100.get("protein") is not None: protein = round(per100["protein"] * ratio, 1)
                if per100.get("carbs") is not None:   carbs = round(per100["carbs"] * ratio, 1)
                if per100.get("fat") is not None:     fat = round(per100["fat"] * ratio, 1)
                if per100.get("fiber") is not None:   fiber = round(per100["fiber"] * ratio, 1)
                if per100.get("sugar") is not None:   sugar = round(per100["sugar"] * ratio, 1)
                if per100.get("sodium") is not None:  sodium = round(per100["sodium"] * ratio, 0)
                for _mk in _MICRO_KEYS:
                    _v = per100.get(_mk)
                    if _v is not None:
                        micros[_mk] = round(_v * ratio, 2)
                computed_forward = True
                logger.info(
                    "zero-calorie read for %r replaced from %s: %.0f g x "
                    "%.0f cal/100g = %d", name, source, _zero_g, cal100, cal)
            else:
                # No mass to price it with, so we still do not know. What we
                # must NOT do is keep the source's NAME on a number it did not
                # produce — "From the USDA database" over a zero is the card
                # telling the user to trust it. Say estimate, and let the
                # enrichment lanes and the ask ladder treat it as open.
                logger.warning(
                    "zero-calorie read for %r and no mass to price it "
                    "(quantity=%r, %s had %.0f cal/100g) — refusing to "
                    "attribute the zero", name, quantity, source, cal100)
                source, confidence = "estimate", "estimated"
        elif cal100 and cal100 > 0 and cal > 0:
            # ESTIMATE PATH — no reliable grams (a count/cup/vague amount), so
            # trust the LLM's calories and back the portion out of them, then
            # derive the nutrients the model usually omits.
            grams = cal / cal100 * 100
            _implied_grams = grams
            ratio = grams / 100.0
            if per100.get("fiber") is not None:  fiber = round(per100["fiber"] * ratio, 1)
            if per100.get("sugar") is not None:  sugar = round(per100["sugar"] * ratio, 1)
            if per100.get("sodium") is not None: sodium = round(per100["sodium"] * ratio, 0)
            # Scale the micronutrient panel to the portion (same ratio). Stored in
            # micronutrients_json so the Daily Log reveal can break it down.
            for _mk in _MICRO_KEYS:
                _v = per100.get(_mk)
                if _v is not None:
                    micros[_mk] = round(_v * ratio, 2)
            # A LABEL MAY CORRECT, NOT ONLY FILL.
            #
            # This read `if not protein`, so a trustworthy source could supply
            # a macro the model OMITTED and could never fix one the model got
            # WRONG — and a wrong number is the failure mode, not a missing
            # one. "Ezekiel Bread, 1 slice" committed the model's 1 g of
            # protein while the seated label said 4.2 g for that same portion,
            # and every other nutrient on the row came from the label.
            #
            # The profile was a MIXTURE: calories from the model, fibre and
            # sodium and micros from the label, protein from whichever spoke
            # first. Nothing downstream could tell, because one row cannot say
            # that two of its numbers disagree about what the food is.
            #
            # One portion, one source, for every macro that source can supply.
            # The ratio is unchanged, so the derived profile stays arithmetically
            # consistent with the calories on the card.
            #
            # The calories are still the MODEL's, and that is the deeper
            # problem: the mass is back-derived from them, so the label is
            # scaled to fit the guess rather than correcting it. Not this
            # change — but the profile no longer compounds it.
            # A CORRECTION MAY NOT DELETE THE DOMINANT MACRO.
            #
            # This is where "Kazunori Hand Roll Set (6 piece)" lost its
            # protein. The estimate path keeps the model's CALORIES — so the
            # 4,404 on that card came from elsewhere — but this block then
            # overwrote its 54 g of protein with the matched row's 0 g,
            # unconditionally, because the row was label-grade and therefore
            # `_trustworthy`. The coaching was written from the result: "that
            # sashimi was mostly fat" is what 0 g protein means.
            #
            # The mass path above already refuses a match that collapses the
            # dominant macro (`_profile_flip`) — it is the strongest signal
            # there is that a row describes a different food. This path had no
            # such check, so the same wrong row was refused when it arrived
            # with a mass and accepted when it arrived without one.
            #
            # Refusing is per-FIELD and deliberately narrow: fibre, sugar,
            # sodium and the micro panel above are untouched, and a row that
            # merely disagrees keeps its correction. Only the erasure of a
            # macro the model reported substantially is refused.
            _erases_protein = (per100.get("protein") is not None
                               and _llm0[1] >= 15
                               and round(per100["protein"] * ratio, 1)
                               < 0.3 * _llm0[1])
            if _erases_protein:
                logger.warning(
                    "%r: refusing a %s row that zeroes protein — model read "
                    "%.0fg, row implies %.1fg for this portion",
                    name, source, _llm0[1], per100["protein"] * ratio)
            if _trustworthy and not _erases_protein:
                for _field in ("protein", "carbs", "fat"):
                    if per100.get(_field) is not None:
                        _scaled = round(per100[_field] * ratio, 1)
                        if _field == "protein":
                            protein = _scaled
                        elif _field == "carbs":
                            carbs = _scaled
                        else:
                            fat = _scaled
            elif not _erases_protein and not protein and per100.get("protein"):
                protein = round(per100["protein"] * ratio, 1)

    # Plausibility clamp: a single logged item should never carry >4000mg sodium.
    # When it does (corn at 20,378mg — Danny 2026-06-23), the USDA lookup matched a
    # salt-like/seasoning record or mis-scaled the per-100g basis; the estimate
    # path can also blow up the multiplier (LLM calories ÷ a tiny cal/100g for
    # broth/pickles → 15× portions). Drop the bogus value rather than store it
    # AND surface a false "high sodium" flag in the coaching note. Real foods
    # (even salty restaurant meals at 2-3.5g) clear the bound; only bad
    # matches/scales don't.
    if sodium is not None and sodium > SODIUM_IMPLAUSIBLE_MG:
        logger.warning(
            f"implausible sodium {sodium:.0f}mg for {(name or '')!r} "
            f"(cal={cal}, source={source}, fdc_id={fdc_id}) — dropping enrichment"
        )
        sodium = None

    # A source that only supplemented the panel never names itself as the
    # answer. Before the split fields existed this was the one place the lie got
    # in: the row was filled by one party, the calories determined by another,
    # and a single `source` string had to pick one and be wrong about the other.
    if src is not None and not macros_from_source:
        source, confidence = "estimate", "estimated"
        rung = "component_estimate" if food_class is authority.FoodClass.RESTAURANT \
            else "estimate"

    # ── §9 SANITY, ON THE PATH THAT ACTUALLY COMMITS ────────────────────────
    #
    # These checks lived only inside the resolver, which had never run on a
    # real turn — so the rule that refuses a 588-calorie tablespoon of peanut
    # butter was unreachable from the code that writes the row.
    #
    # An IMPOSSIBLE result is not committed as a number. Falling back to the
    # model's own read is the honest move: it is the only other estimate we
    # have, and it was produced without the wrong density that caused this.
    # A SUSPECT one is left alone and logged — oils and nut butters sit at the
    # energy ceiling legitimately, and refusing there would cost more than it
    # saves.
    try:
        from skills.nutrition import sanity as _sanity
        _findings = _sanity.check_values(
            calories=cal, protein=protein, carbs=carbs, fat=fat,
            fiber=fiber, grams=_implied_grams)
        _fatal = [f for f in _findings if f.is_fatal]
        if _fatal:
            logger.warning(
                "sanity refusal for %r: %s — falling back to the model's read",
                name, "; ".join(f.code for f in _fatal))
            cal, protein, carbs, fat = _llm0
            _implied_grams = None
            computed_forward = False
            source, confidence = "estimate", "estimated"
        elif _findings:
            logger.info("sanity note for %r: %s", name,
                        ",".join(f.code for f in _findings))
    except Exception as _se:
        logger.warning(f"sanity check skipped for {name!r}: {_se}")

    pd, satiety, quality = _derive(cal, protein, carbs, fat, fiber, sugar)

    # Build the coaching note the LLM uses to actually coach (not just acknowledge)
    bits = []
    if pd is not None:
        bits.append(f"protein density {pd:.0f}% of cals ({'strong' if pd>=30 else 'moderate' if pd>=18 else 'low'})")
    if fiber is not None:
        bits.append(f"~{fiber:.0f}g fiber ({'good' if fiber>=4 else 'low'})")
    if sugar is not None and sugar >= 15:
        bits.append(f"~{sugar:.0f}g sugar")
    if sodium is not None and sodium >= 600:
        bits.append(f"~{sodium:.0f}mg sodium (high)")
    bits.append(f"satiety {satiety}, quality {quality}")
    # Portion sanity net: when the grams implied by calories/density disagree
    # wildly with the stated quantity's canonical weight, tell the model — it
    # can re-estimate or ask. Never silently mutate the logged values. Skipped
    # when we computed forward from a mass-stated quantity — the grams are known,
    # not implied, so there's nothing to sanity-check.
    if not computed_forward:
        try:
            from core.portions import portion_check
            _pc = portion_check(name, quantity, _implied_grams)
            if _pc:
                logger.info(f"{_pc} ({name!r})")
                bits.append(_pc)
        except Exception:
            pass
    note = "; ".join(bits)
    conf_note = {
        "exact": "label exact match" if source == "web_label" else "USDA exact match",
        "likely": "label match" if source == "web_label" else "USDA likely match",
        "user-confirmed": "your usual (confirmed)",
        "estimated": "estimate",
    }.get(confidence, confidence)

    return FoodAnalysis(
        calories=round(cal), protein=round(protein, 1), carbs=round(carbs, 1),
        fat=round(fat, 1), fiber=fiber, sugar=sugar, sodium=sodium,
        fdc_id=fdc_id, confidence=confidence, source=source,
        protein_density=pd, satiety=satiety, quality=quality, per100=per100,
        micros=micros,
        coach_note=f"{note} [{conf_note}]",
        enrichment_source=(source if source != "estimate" else None),
        provenance=authority.provenance_for(
            rung=rung or "estimate", food_class=food_class,
            portion_source=("computed_mass" if computed_forward
                            else "user_stated"),
            micronutrient_source=(micro_rung if (micros or sodium is not None
                                                 or fiber is not None) else ""),
            confidence=_CONF_NUM.get(confidence, 0.4),
            # Honest switch: the winner determined the calories only when we
            # computed them forward from its density. Everywhere else the
            # model's numbers are the ones on the card, and saying otherwise is
            # how "From the USDA database" ended up under numbers USDA never
            # produced.
            macros_from_source=computed_forward,
        ),
    )
