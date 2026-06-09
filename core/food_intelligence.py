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
    source: str = "estimate"               # usda|memory|estimate
    protein_density: Optional[float] = None  # g protein per 100 kcal
    satiety: Optional[str] = None          # low|moderate|high
    quality: Optional[str] = None          # low|solid|excellent
    per100: dict = field(default_factory=dict)
    coach_note: str = ""                   # the analysis line surfaced to the LLM


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
            usda_candidate=None, memory_match=None) -> FoodAnalysis:
    """
    Build a FoodAnalysis. Priority for the nutrient profile:
      memory_match (user's recurring food) > usda_candidate > LLM-only.
    The LLM's calories/protein anchor the portion; USDA/memory fill in
    fiber/sugar/sodium and confidence.
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

    src = memory_match or usda_candidate
    if src:
        per100 = src.get("per100g") or {
            "calories": src.get("cal_100"), "protein": src.get("protein_100"),
            "carbs": src.get("carbs_100"), "fat": src.get("fat_100"),
            "fiber": src.get("fiber_100"), "sugar": src.get("sugar_100"),
            "sodium": src.get("sodium_100"),
        }
        cal100 = per100.get("calories")
        if cal100 and cal100 > 0 and cal > 0:
            # back out grams from the LLM's calories + USDA calorie density
            grams = cal / cal100 * 100
            ratio = grams / 100.0
            if per100.get("fiber") is not None:  fiber = round(per100["fiber"] * ratio, 1)
            if per100.get("sugar") is not None:  sugar = round(per100["sugar"] * ratio, 1)
            if per100.get("sodium") is not None: sodium = round(per100["sodium"] * ratio, 0)
            # refine protein if USDA disagrees notably and LLM gave none
            if not protein and per100.get("protein"):
                protein = round(per100["protein"] * ratio, 1)
        fdc_id = src.get("fdc_id") or src.get("fdc_id")
        if memory_match:
            source = "memory"
            confidence = "user-confirmed" if memory_match.get("user_confirmed") else (memory_match.get("confidence") or "likely")
        else:
            source = "usda"
            confidence = src.get("_match", "likely")

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
    note = "; ".join(bits)
    conf_note = {
        "exact": "USDA exact match",
        "likely": "USDA likely match",
        "user-confirmed": "your usual (confirmed)",
        "estimated": "estimate",
    }.get(confidence, confidence)

    return FoodAnalysis(
        calories=round(cal), protein=round(protein, 1), carbs=round(carbs, 1),
        fat=round(fat, 1), fiber=fiber, sugar=sugar, sodium=sodium,
        fdc_id=fdc_id, confidence=confidence, source=source,
        protein_density=pd, satiety=satiety, quality=quality, per100=per100,
        coach_note=f"{note} [{conf_note}]",
    )
