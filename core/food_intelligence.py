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
    if q == d or q in d:
        return "exact"
    overlap = len(qa & da) / max(1, len(qa))
    if overlap >= 0.6:
        return "likely"
    return "estimated"


# Processed/altered forms that usually AREN'T what a user means by a bare food name.
_FORM_PENALTY = (
    "breaded", "fried", "dehydrated", "dried", "powder", "flour", "canned",
    "juice", "fortified", "infant", "baby", "pickled", "smoked", "cured",
    "candied", "syrup", "sauce", "concentrate",
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
    if carb_fat_cal > 0:
        scale = remaining / carb_fat_cal
        carbs = round(carbs * scale, 1)
        fat = round(fat * scale, 1)
    elif remaining > 0:
        # No carb/fat data — put residual in carbs (safe fallback)
        carbs = round(remaining / 4, 1)

    return cal, protein, carbs, fat


def analyze(name, quantity, llm_cal, llm_protein, llm_carbs, llm_fat,
            usda_candidate=None, memory_match=None,
            web_candidate=None, off_candidate=None) -> FoodAnalysis:
    """
    Build a FoodAnalysis. Priority for the nutrient profile:
      memory_match (user's recurring food)
        > web_candidate (label-accurate web lookup for packaged products)
        > usda_candidate
        > LLM-only.
    The LLM's calories/protein anchor the portion; the enrichment source fills
    in fiber/sugar/sodium and confidence. web_candidate carries the same shape
    as usda_candidate ({"fdc_id": …, "per100g": {...}, "_match": "exact|likely"}).
    """
    cal = float(llm_cal or 0)
    protein = float(llm_protein or 0)
    carbs = float(llm_carbs or 0)
    fat = float(llm_fat or 0)

    # Enforce macro/calorie consistency before USDA enrichment.
    # Invalid macros (protein*4 + carbs*4 + fat*9 ≠ calories) mislead the coaching
    # note and confuse the LLM on follow-up turns.
    cal, protein, carbs, fat = reconcile_macros(cal, protein, carbs, fat)
    fiber = sugar = sodium = None
    fdc_id = None
    confidence = "estimated"
    source = "estimate"
    per100 = {}
    micros: dict = {}
    _implied_grams = None

    # Ladder priority (Danny 2026-07-22): own-log/memory > USDA > OFF > web.
    # USDA wins for generics (it has them); OFF fills branded items USDA misses;
    # web is the last resort. All carry the same {per100g, _match} shape.
    src = memory_match or usda_candidate or off_candidate or web_candidate
    computed_forward = False
    if src:
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
        _trustworthy = confidence in ("exact", "likely", "user-confirmed")
        if _mg and cal100 and cal100 > 0 and _trustworthy:
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
            # refine protein if enrichment disagrees notably and LLM gave none
            if not protein and per100.get("protein"):
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
    )
