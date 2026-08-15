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

#: The same bound where the PORTION is known — a mass the user stated, or one
#: the source's own panel supplies — and the match is trustworthy. There the
#: arithmetic is `mass x label density` and the thing it disagrees with is the
#: model's guess, which is the weakest evidence in the turn and the reason the
#: lookup ran at all. A bagel guessed at 80 and labelled 250 is a bad guess; a
#: row seven times the estimate is a different food (audit N-2).
_OVERCOUNT_MULTIPLE_KNOWN_MASS = 4.0


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


def normalize_name(name: str, split_separators: bool = False) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"\b(\d+\s*(g|oz|cups?|tbsp|tsp|ml|servings?|slices?|pieces?))\b", "", n)
    if split_separators:
        # V2 tokenisation: a separator is a word BOUNDARY, not deletable. The
        # legacy branch strips punctuation in place, gluing "steak/roast" into
        # "steakroast" and "grass-fed" into "grassfed" — so USDA's own "ribeye
        # steak/roast" loses the token "steak" and its real ribeye row fell below
        # the identity gate. Splitting recovers it. Kept behind the flag so v1's
        # token sets are byte-identical.
        n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    else:
        n = re.sub(r"[^a-z0-9 ]", "", n).strip()
    return re.sub(r"\s+", " ", n)


#: A normalized key carries semantic content only if something ALPHABETIC
#: survived normalization. Deliberately `a-z` and not `str.isalpha()`: `'п'`
#: IS alpha to Python, and writing the check that way would accept a raw
#: Cyrillic string while `normalize_name` is about to delete every character
#: of it — a predicate that answers about a string nobody will ever key on.
_HAS_SEMANTIC_CONTENT = re.compile(r"[a-z]")


def memory_key_is_addressable(name_norm: str) -> bool:
    """May this normalized name address durable per-user food memory?

    ⛔ THE DEFECT THIS CLOSES WAS LIVE, AND IT MISPRICED A REAL MEAL.
    `normalize_name` keeps `[a-z0-9 ]`, so a food named in any non-Latin script
    normalizes to whatever DIGITS it happened to contain:

        'Творог 5%'                    -> '5'
        'Молоко (2.5%)'                -> '25'
        'Кукуруза варёная (2 початка)' -> '2'
        'Омлет из 2 яиц'               -> '2'

    Measured in production 2026-08-14 over 180 days: 361 distinct non-English
    foods, 300 normalizing to EMPTY and 6 KEYS each shared by several DIFFERENT
    foods of the same user — one key carrying nine. On 2026-08-04 a user's
    `Творог 2%` (2% cottage cheese) was priced from their
    `Кукуруза варёная (2 початка)` (boiled corn) row: 54.0 kcal and 3.33 g
    protein per 100 g, all four macros identical to the corn cache, committed
    at roughly a fifth of cottage cheese's real protein.

    ⭐ THE PREDICATE IS ABOUT KEY QUALITY, NOT LANGUAGE (Danny, 2026-08-14).
    There is no Cyrillic here and no script test — a key that lost all of its
    letters is non-addressable whoever wrote it, which is why this also catches
    a hypothetical `'2'` from an English name and generalizes to every locale
    normalization has not been taught yet.

    ⭐⭐ AND IT FAILS TOWARD NO EVIDENCE. Refusing the lookup costs some
    non-English foods a memory hit they were getting by accident; it cannot
    return another food's numbers. In this layer no evidence is strictly better
    than wrong evidence — the same rule that makes `PricingRefused` an
    exception rather than a zero.

    ⚠ THIS IS CONTAINMENT, NOT THE FIX. The real correction is the
    interpretation boundary: identity derived from interpreted meaning rather
    than from surviving bytes, so these foods become addressable instead of
    merely safe.
    """
    return bool(_HAS_SEMANTIC_CONTENT.search(name_norm or ""))


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
    # ⭐ THE SAME FOLD THE RANKER USES, for the same reason. `best_candidate`
    # picks the winner on folded tokens; if this labelled it on unfolded ones
    # the two would disagree about what a match IS, and a correctly-matched
    # food would be reported as "estimated" — measured on "eggs" against
    # "Egg, whole, cooked, poached", where the ranker seats the row and the
    # label calls it a guess. `tool_executor` shows that label to the pricing
    # path, so the disagreement is not cosmetic.
    #
    # Containment above stays on the RAW strings deliberately: it is a
    # stricter test that already behaves, and folding a whole phrase would
    # change what "contains" means rather than what "matches" means.
    overlap = len(_folded(qa) & _folded(da)) / max(1, len(_folded(qa)))
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


def portion_pricing_enabled() -> bool:
    """Whether a CALIBRATED portion may price a per-100g row forward.

    ON by default, and a kill switch rather than an opt-in: the behaviour it
    replaces — backing the portion out of the model's calorie guess whenever no
    explicit weight was stated — is the one this exists to stop, so shipping it
    dark would leave the defect live. `FOOD_PORTION_PRICING=false` reverts to
    the old estimate path without a deploy, which is the same shape every other
    risky change in this lane carries.

    Deliberately NOT gated on NUTRITION_ACCURACY_V2. This is not an accuracy
    experiment, it is a correction to which number is treated as evidence, and
    it should not wait on a canary that has its own separate rollout.
    """
    import os
    return os.getenv("FOOD_PORTION_PRICING", "true").lower() in (
        "1", "true", "yes")


def _nutrition_accuracy_v2() -> bool:
    """The unified accuracy capability (docs/NUTRITION_ACCURACY_REDESIGN.md).

    Off unless the global flag `NUTRITION_ACCURACY_V2` is set (everyone) OR the
    ambient turn user is in `NUTRITION_ACCURACY_V2_ALLOWLIST` — the per-user
    canary, so V2 can be trialled on one account before the whole fleet. Decision
    lives in skills/nutrition/v2_gate; run_turn binds the user for the turn."""
    try:
        from skills.nutrition.v2_gate import v2_active
        return v2_active()
    except Exception:                                        # pragma: no cover
        import os
        return os.getenv("NUTRITION_ACCURACY_V2", "").lower() in ("1", "true", "yes")


# ── THE RAW-VS-COOKED AXIS, THREE-VALUED ON PURPOSE ───────────────────────
#
# The cooked preference used to read `cooking_yield(query) > 1.0`, and a table
# miss returns exactly 1.0 — so "we have never been told about this food" and
# "this food does not concentrate when cooked" produced the identical ranking
# outcome. That is absence representable as an answer, the defect this whole
# phase exists to remove, one layer further down than anyone had looked.
#
# Naming the third state does NOT decide the hard question — a bare request
# for an unknown food still gets no cooked preference, which is the same
# BEHAVIOUR as before. What changes is that the state is now VISIBLE, so the
# winner it produces can be held out of a frozen baseline instead of being
# signed as though the axis had been decided.
COOKED_PREFERRED = "cooked_preferred"
COOKED_NOT_PREFERRED = "yield_states_no_concentration"
COOKED_AXIS_UNDECIDED = "yield_unknown_for_this_food"


def cooked_preference_state(query: str) -> str:
    """Whether a cooked row should be preferred for `query`, or nobody knows.

    ⭐ `COOKED_AXIS_UNDECIDED` IS NOT A SOFTER "no". It says the raw-vs-cooked
    axis was never established for this food, which is a statement about OUR
    KNOWLEDGE rather than about the food — and a winner chosen while it holds
    is not a winner anyone decided on.
    """
    from core.portions import cooking_yield_known

    stated = cooking_yield_known(query)
    if stated is None:
        return COOKED_AXIS_UNDECIDED
    return COOKED_PREFERRED if stated > 1.0 else COOKED_NOT_PREFERRED


def _as_eaten_preference() -> bool:
    """The as-eaten PREFERENCE, split out of V2 and off by default.

    ⭐ SPLIT BECAUSE V2 IS TWO BEHAVIOURS OF DIFFERENT MATURITY. V2's
    structural half — folded morphology, the identity gate, cross-food
    refusal, cooked-by-default — only ever declines a wrong row or reaches a
    right one, and is what the frozen baseline should rest on. This term is a
    ±0.4 tie-break, and a tie-break can only decide a NEAR-TIE, so the row it
    seats differs from the runner-up in dimensions it never evaluated: it
    picked striploin-with-fat over knuckle (+123 kcal, mostly CUT) and a
    BATTERED chicken row over meat-only (+7.7 g carbs of added food).

    A rule named for trim must not decide cut. Until cut and coating are
    separately modelled this rides its own flag and its own canary, so that
    27 winners are never signed under a selector known to mix them.
    """
    try:
        from skills.nutrition.v2_gate import as_eaten_active
        return as_eaten_active()
    except Exception:                                        # pragma: no cover
        import os
        return os.getenv("NUTRITION_AS_EATEN_PREFERENCE",
                         "").lower() in ("1", "true", "yes")


# Preparation / cooking-method words. They describe HOW a food was made, not
# WHAT it is, so the identity gate ignores them: "grilled chicken thigh" is the
# same food as USDA's "chicken thigh, cooked, roasted" — the prep is handled by
# cooking-yield and the prep logic, not by demanding "grilled" appear in USDA's
# text (it says "roasted", and the mismatch was dropping coverage below the gate).
_PREP_TOKENS = frozenset({
    "raw", "cooked", "grilled", "fried", "roasted", "baked", "broiled",
    "braised", "steamed", "boiled", "sauteed", "seared", "pan", "grill",
    "poached", "smoked", "cured", "fresh", "frozen",
})

# SPECIES is identity. A bare meat query implies its default animal; a candidate
# naming a DIFFERENT animal is a different food however well its cut and prep line
# up — "ribeye steak" must not seat "Game meat, bison, ribeye". Only penalised
# when the animal is NOT in the query (so "bison ribeye" the query still matches
# its bison row, and "beef", the default, is never penalised).
# NB: not "game" — it is USDA's CATEGORY prefix ("Game meat, bison, ..."), not a
# species, so it fires falsely on a query that names the animal ("bison ribeye").
# The specific animals below already catch every game row that matters.
_SPECIES_TOKENS = frozenset({
    "bison", "buffalo", "venison", "elk", "deer", "goat", "mutton",
    "lamb", "veal", "pork", "chicken", "turkey", "duck", "ostrich", "emu",
    "rabbit", "boar", "horse", "kangaroo",
})

# CUT NARROWERS: a sub-cut that is not the cut asked for. "ribeye cap" (spinalis)
# and "sirloin cap" (picanha) are distinct cuts, leaner and priced differently,
# from the "ribeye"/"sirloin" a person means. Penalised like a species mismatch.
_CUT_NARROWERS = frozenset({"cap", "tip"})

# Words that mean a row is already COOKED. One list, read by the matcher (prefer
# a cooked row) and by analyze (don't apply cooking-yield to it). It must be
# COMPLETE: "rotisserie" and "bbq" were missing, so USDA's cooked rotisserie
# thigh read as raw and took the raw->cooked yield a second time (+35%).
_COOKED_MARKERS = frozenset({
    "cooked", "grilled", "roasted", "broiled", "braised", "baked", "fried",
    "rotisserie", "bbq", "barbecue", "barbecued", "smoked", "seared",
    "sauteed", "steamed", "boiled", "poached", "stewed", "griddled",
})


# ── MORPHOLOGICAL FOLDING, and why it is a CANONICALISATION not a lemmatiser ──
#
# Measured 2026-08-13: `banana|` and `potato|` scored an overlap of EXACTLY
# ZERO against "Bananas, raw" and "Potatoes, raw, skin". The artifact held the
# evidence, the eligibility layer admitted it, a person reviewed it — and
# `best_candidate` could not see it, because "banana" is not the string
# "bananas". `_from_artifact` then returned None and the turn priced from a
# lower rung in silence. USDA writes its headings in the plural; people write
# food in the singular. Nothing else was wrong.
#
# ⭐ SYMMETRY IS THE PROPERTY, CORRECTNESS IS NOT. Both the query and the
# record go through this same fold, so a linguistically WRONG stem is
# harmless as long as it is the same on both sides: "leaves" folding to
# "leave" still matches "leaves". That is why this can be a handful of suffix
# rules rather than a dictionary — it is not trying to know English, only to
# agree with itself. A food-name list would be the opposite: knowledge that
# has to be maintained, and the thing this codebase refuses.
#
# ⭐⭐ AND IT IS APPLIED ONLY TO COVERAGE. `_FORM_PENALTY`, `_SPECIES_TOKENS`,
# `_CUT_NARROWERS`, `_PREP_TOKENS` and `_COOKED_MARKERS` are literal-token
# sets; folding the sets they are tested against would silently stop "chips"
# matching `_FORM_PENALTY`. So the raw token sets are kept for every penalty
# and preference, and the fold is used for the two overlap ratios and nothing
# else. The blast radius is the coverage measurement, by construction.

#: Endings where a trailing "s" is part of the WORD, not a plural marker —
#: asparagus, molasses, couscous, bass. Checked before any rule fires.
_NOT_A_PLURAL = ("ss", "us", "is", "os")

#: Below this length a trailing "s" is more likely to be the word than a
#: plural ("gas", "ras"), and the tokens that matter here are all longer.
_MIN_FOLDABLE = 4


def _singular(token: str) -> str:
    """One token, folded toward its singular form. Deterministic and total."""
    if len(token) < _MIN_FOLDABLE or token.endswith(_NOT_A_PLURAL):
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"                      # berries -> berry
    if token.endswith(("oes", "ches", "shes", "xes", "zes", "sses")):
        return token[:-2]                            # potatoes -> potato
    if token.endswith("s"):
        return token[:-1]                            # bananas -> banana
    return token


def _folded(tokens) -> set:
    return {_singular(t) for t in tokens}


def best_candidate(query: str, candidates: list[dict]) -> tuple[Optional[dict], str]:
    """
    Pick the most canonical USDA match for a query and return (candidate, confidence).
    Favors high token-overlap; penalizes processed/composite forms not named in
    the query. Returns (None, 'estimated') if nothing is a good enough match
    (caller then falls back to the LLM estimate).

    V2 (NUTRITION_ACCURACY_V2, Part 1): the gate is IDENTITY, not brevity. The
    legacy path subtracts 0.15 per extra description token, which rejects USDA's
    own verbose rows — "skirt steak" vs "Beef, plate steak, boneless, inside
    skirt, separable lean and fat, trimmed to 0\" fat, choice, raw" scores 1.05
    against a 1.2 gate despite a PERFECT token match, so it seats nothing and the
    LLM's low guess stands. V2 keeps the length term only as a tiny tie-break
    (concise still wins ties), and gates on QUERY COVERAGE: accept when the
    query's tokens are (nearly) all present — the same food, described verbosely
    — and reject when one is missing (a different food / wrong cousin). Composite
    dishes are still rejected by `_FORM_PENALTY` (gravy, frozen, meal…) dragging
    the score under the floor, so "turkey breast" never seats a gravy meal.
    """
    if not candidates:
        return None, "estimated"
    v2 = _nutrition_accuracy_v2()
    q = normalize_name(query, split_separators=v2)
    qa = set(q.split())
    # Identity tokens = the food nouns, prep words removed. The v2 gate measures
    # coverage of THESE, so a prep word in the query ("grilled") that USDA spells
    # differently ("roasted") can't drop a real match below the gate.
    qa_id = (qa - _PREP_TOKENS) or qa
    # Cooked-by-default (v2, Part 2a): only for foods normally eaten cooked (a
    # non-1.0 cooking yield — meats/fish, never nuts or salad) and only when the
    # user didn't say "raw". Prefer a cooked row so the density is right at the
    # source, and cooking-yield only has to rescue foods USDA carries raw-only
    # (skirt steak). Without this, yield was applied to a raw row when a cooked
    # one existed, and overshot.
    # ⭐ UNKNOWN IS NOT "NO PREFERENCE". `cooking_yield` returns 1.0 both for a
    # food that genuinely does not concentrate AND for one the table has never
    # heard of, so reading `> 1.0` silently converted MISSING KNOWLEDGE into a
    # decision — and `mackerel|`/`tilapia|` seated raw rows while `salmon|`
    # seated cooked. The state is now three-valued and the undecided case is
    # named, so a winner produced under it can be held rather than frozen.
    _cooked_pref = False
    if v2 and "raw" not in qa:
        state = cooked_preference_state(query)
        _cooked_pref = state == COOKED_PREFERRED
    # As-eaten over trimmed (v2): a person eats the thigh with its skin and the
    # steak with its fat unless they say otherwise, so "meat and skin" / "lean
    # and fat" is the right basis and "meat only" / "lean only" / "skinless" is a
    # reference sample, not the meal — the same "as logged" principle as cooked-
    # default. Suppressed when the query itself asks for the trimmed form.
    # ⭐ ITS OWN POLICY, AND NO LONGER A SCORING TERM — it applies AFTER
    # ranking, inside a comparability class. See the refinement below.
    _as_eaten = (v2 and _as_eaten_preference()
                 and not (qa & {"skinless", "lean", "trimmed"}))
    # Folded ONCE per call, for coverage only. `qa` and `qa_id` stay raw below,
    # because every penalty and preference tests literal membership.
    qa_f, qa_id_f = _folded(qa), _folded(qa_id)
    best, best_score, best_overlap = None, -999.0, 0.0
    for c in candidates:
        d = normalize_name(c.get("description", ""), split_separators=v2)
        da = set(d.split())
        da_f = _folded(da)
        overlap = len(qa_f & da_f) / max(1, len(qa_f))
        id_overlap = len(qa_id_f & da_f) / max(1, len(qa_id_f))
        score = overlap * 3.0
        # Length term: a tie-break in v2 (0.02), the rejection lever in v1 (0.15).
        score -= (0.02 if v2 else 0.15) * max(0, len(da) - len(qa))
        for w in _FORM_PENALTY:
            if w in da and w not in qa:
                score -= 1.2                                # processed/composite form not asked for
        if v2:
            # IDENTITY BEFORE PREPARATION, sized from the constants already here.
            # A different ANIMAL is not the food: 2.5 drops even a perfect-overlap
            # cooked row (3.0 + 0.6) below the 1.2 trust floor, so a lone bison row
            # for "ribeye" falls back to an estimate rather than logging a bison
            # density for beef. A different SUB-CUT is the same animal, so 1.5 —
            # above the cooked/raw swing (±0.6), so a cooked ribeye-CAP never
            # outranks the raw ribeye that cooking-yield corrects, but low enough
            # that a cap still seats if it is the only ribeye on the shelf. Counted
            # once per axis — "game meat, bison" is one wrong species, not three.
            if any(w in da and w not in qa for w in _SPECIES_TOKENS):
                score -= 2.5
            if any(w in da and w not in qa for w in _CUT_NARROWERS):
                score -= 1.5
        if _cooked_pref:
            if da & _COOKED_MARKERS:
                score += 0.6                                # a cooked row for a cooked food
            if "raw" in da:
                score -= 0.6                                # avoid the raw reference row
        if score > best_score:
            best, best_score, best_overlap = c, score, id_overlap
    conf = score_match(query, best.get("description", "")) if best else "estimated"

    # ⭐⭐ THE PREFERENCE, AS A REFINEMENT INSIDE A COMPARABILITY CLASS.
    #
    # It used to be a ±0.4 term in the loop above, and a ±0.4 term can only
    # overturn a NEAR-TIE — so it decided CUT (knuckle -> striploin, +123 kcal)
    # and COATING (meat only -> battered, +7.7 g carbs), dimensions it never
    # evaluated. A bigger number would only move the same wrong rows further.
    #
    # So it runs AFTER ranking and may only exchange the winner for a row that
    # is IDENTICAL EXCEPT IN ITS OWN DIMENSION. Comparability is defined by
    # SUBTRACTION rather than by a cut vocabulary: strip the tokens the
    # preference governs from both descriptions and require the remainder to
    # match, so a differing cut or a batter blocks it by simply surviving.
    # The guarantee is structural — nobody has to enumerate what a cut is.
    if _as_eaten and best is not None:
        from skills.nutrition.preference_dimensions import prefer_as_eaten
        refined = prefer_as_eaten(best, candidates)
        if refined is not best:
            best = refined
            conf = score_match(query, best.get("description", ""))
    if v2:
        # Identity gate: the food nouns must be (nearly) fully covered — a
        # descriptive row for the SAME food — AND survive the composite penalty.
        # A missing IDENTITY token means a different food; a tanked score means a
        # composite. Prep words never gate (see _PREP_TOKENS).
        if best_overlap < 0.75 or best_score < 1.2:
            return None, "estimated"
        return best, conf
    # Legacy gate: if even the best match is weak, don't trust USDA.
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
    #: THE WINNING SOURCE'S OWN SERVING PANEL — "28 g (about 15 chips)".
    #: Read during analysis and then dropped, which is the same discard as the
    #: rest of the resolution (cause B): it is the only thing that knows what
    #: one piece of THIS product weighs, so a later "just 9 chips" had nothing
    #: to convert with and took the model's guess. Carried, not re-derived —
    #: no table of food-shaped averages knows a Sun Chip from a tortilla chip.
    serving_text: str = ""
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
    """Enforce caloric consistency. Returns corrected (cal, protein, carbs, fat).

    The four-value contract, unchanged for every existing caller. Use
    `reconcile_macros_traced` when you need to know what was moved — and
    something always should, see its docstring.
    """
    cal, protein, carbs, fat, _ = reconcile_macros_traced(cal, protein, carbs, fat)
    return cal, protein, carbs, fat


def reconcile_macros_traced(cal, protein, carbs, fat) -> tuple:
    """As above, plus a note describing any material change. Five-tuple.

    Enforce caloric consistency: protein*4 + carbs*4 + fat*9 must ≈ total
    calories. The LLM often submits internally inconsistent macros (e.g. 500 cal
    but macros that sum to 720 cal). Strategy: trust calories and protein (most
    diet-critical), then rebalance carbs/fat proportionally to fill the
    remaining caloric budget.

    WHY IT REPORTS (audit T-4, item 10). This is the only thing in the lane that
    can see a macro inconsistency, and it used to resolve one silently. The
    downstream detector cannot cover for it: `sanity`'s Atwater check fires at
    30% drift and this fires at 15%, so everything in the 15–30% band is
    normalised here and no other layer ever hears about it. The transcript's
    chocolate sweet roll sits in that band at 16.2% — measured — which is why
    "nothing in the system can doubt it" was literally true.

    Moving the Atwater check earlier does not reach this case; 16.2% is under a
    30% rule wherever it runs. Reporting does.

    ABSENT IS NOT ZERO. `None` means nobody supplied the macro; `0` means a
    source claimed it. Only an ABSENT macro may receive the residual — placing
    3.8 g of fat over a label that says zero invents a fact against evidence,
    which is the same error as leaving it at zero, pointed the other way. A
    stated zero is scaled as it always was, and the note says the gap is still
    open.
    """
    absent = {name for name, value in
              (("protein", protein), ("carbs", carbs), ("fat", fat))
              if value is None}
    protein = float(protein or 0)
    carbs = float(carbs or 0)
    fat = float(fat or 0)
    cal = float(cal or 0)

    if cal <= 0 or (protein == 0 and carbs == 0 and fat == 0):
        return cal, protein, carbs, fat, ""

    macro_cal = protein * 4 + carbs * 4 + fat * 9
    if macro_cal <= 0:
        return cal, protein, carbs, fat, ""

    # If macros are within 15% of stated calories, accept as-is (small rounding ok)
    if abs(macro_cal - cal) / cal <= 0.15:
        return cal, protein, carbs, fat, ""

    # Macros are inconsistent — trust calories and protein, rescale carbs+fat.
    protein_cal = protein * 4
    remaining = cal - protein_cal
    if remaining < 0:
        # Protein alone exceeds calories — protein must be wrong too; scale everything
        scale = cal / macro_cal
        protein = round(protein * scale, 1)
        carbs = round(carbs * scale, 1)
        fat = round(fat * scale, 1)
        return (cal, protein, carbs, fat,
                f"protein exceeded the calorie total; all macros scaled by "
                f"{scale:.2f}")

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
    # Placed only when the shortfall is worth at least a whole gram, only when
    # exactly one of the two is missing, and only when NOBODY STATED IT. A
    # source that says "fat: 0" has made a claim; overwriting it with 3.8 g is
    # inventing a fact against evidence — the same error as trusting the zero,
    # aimed the other way. With both zero the `elif` below already places the
    # residual, and with neither zero, scaling is right. A genuinely fat-free
    # food is protected by the 15% band above; this branch is reachable only
    # once the macros are already inconsistent.
    unexplained = remaining - carb_fat_cal
    note = ""
    if carb_fat_cal > 0 and fat == 0 and carbs > 0 and unexplained >= 9 \
            and "fat" in absent:
        fat = round(unexplained / 9, 1)
        note = (f"fat was not given; estimated {fat} g to close a "
                f"{round(unexplained)} cal gap")
    elif carb_fat_cal > 0 and carbs == 0 and fat > 0 and unexplained >= 4 \
            and "carbs" in absent:
        carbs = round(unexplained / 4, 1)
        note = (f"carbs were not given; estimated {carbs} g to close a "
                f"{round(unexplained)} cal gap")
    elif carb_fat_cal > 0:
        scale = remaining / carb_fat_cal
        before = (carbs, fat)
        carbs = round(carbs * scale, 1)
        fat = round(fat * scale, 1)
        # A STATED ZERO SURVIVES, AND SAYS SO. Scaling cannot move it, so the
        # gap is still open — and this is the one place that knows.
        if unexplained >= 9 and (fat == 0 or carbs == 0):
            note = (f"{round(unexplained)} cal unaccounted for; "
                    f"{'fat' if fat == 0 else 'carbs'} was stated as zero and "
                    f"left alone")
        elif abs(before[0] - carbs) >= 1 or abs(before[1] - fat) >= 1:
            note = (f"carbs {before[0]}->{carbs}, fat {before[1]}->{fat} "
                    f"to match the stated calories")
    elif remaining > 0:
        # No carb/fat data — put residual in carbs (safe fallback)
        carbs = round(remaining / 4, 1)
        note = f"no carb or fat data; put {carbs} g of carbs against the gap"

    return cal, protein, carbs, fat, note


#: Above this, a package is a multipack rather than one serving. A 100 g bar or
#: a 500 ml bottle is a real single serve; a 227 g bag of fun size bars is not,
#: and `package_text` cannot tell them apart on its own.
_SINGLE_SERVE_MAX_G = 200.0


def _is_basis_not_serving(panel: str) -> bool:
    """Whether a "serving" is really the per-100 basis wearing a serving's name.

    Open Food Facts publishes `serving_size: 100g` for products with no panel.
    Read as a serving it turns any count into hundreds of grams, which is how a
    fun size candy bar reached 439 calories.

    Exactly 100 g or 100 ml, and nothing else: a genuine 100 g serving does
    exist, but a source that also reports per-100 g values cannot distinguish
    one from the other — and between over-reading a real 100 g serving and
    multiplying a small item fivefold, the safe error is to fall through to the
    estimate.
    """
    text = (panel or "").strip().lower().replace(" ", "")
    return text in ("100g", "100.0g", "100ml", "100.0ml",
                    "100gram", "100grams", "100millilitres", "100milliliters")


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
        # A "SERVING" OF 100 g IS THE BASIS RESTATED, NOT A SERVING.
        #
        # Open Food Facts publishes `serving_size: 100g` when a product has no
        # real panel — it is the per-100 g row wearing a serving's name. Taken
        # literally, "1 bar" became one hundred grams: a fun size Milky Way
        # committed 439 calories against a real 80, whenever the model's own
        # guess was high enough that the overcount guard did not demote it.
        #
        # The guard was the only thing standing in front of this, which means
        # the number depended on how badly the model guessed.
        if _is_basis_not_serving(panel):
            panel = ""
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
            # ...AND A BAG IS NOT A BAR. The reasoning above holds for a
            # SINGLE-SERVE product, where the package really is the serving.
            # A 227 g sharing bag of fun size bars is not one bar, and nothing
            # in `package_text` distinguishes the two — "227g" reads the same
            # either way.
            #
            # Above this weight a countable confection is a multipack, not a
            # piece. The bound is deliberately generous: a large single-serve
            # bar or bottle stays under it, and everything above is a package
            # the user ate one of, not the whole of.
            if float(whole) > _SINGLE_SERVE_MAX_G:
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
            estimate_candidate=None,
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
    # ABSENT STAYS ABSENT UNTIL RECONCILE HAS SEEN IT (audit T-4, item 9).
    # `float(x or 0)` collapsed "nobody said" into "someone said zero" one line
    # before the only code that could tell them apart — so `analyze(fat=None)`
    # and `analyze(fat=0)` returned identical rows and a zero was unfalsifiable.
    # `_log_call` already omits a macro the interpreter never supplied; this is
    # where that distinction was being thrown away.
    protein = llm_protein if llm_protein is not None else None
    carbs = llm_carbs if llm_carbs is not None else None
    fat = llm_fat if llm_fat is not None else None

    # Enforce macro/calorie consistency before USDA enrichment.
    # Invalid macros (protein*4 + carbs*4 + fat*9 ≠ calories) mislead the coaching
    # note and confuse the LLM on follow-up turns.
    cal, protein, carbs, fat, _macro_note = reconcile_macros_traced(
        cal, protein, carbs, fat)
    if _macro_note:
        # THE ONLY LAYER THAT CAN SEE THIS. `sanity`'s Atwater check fires at
        # 30% drift and reconcile at 15%, so the whole 15–30% band is resolved
        # here and nowhere else hears about it. The transcript's roll sits at
        # 16.2%, which is why "nothing in the system can doubt it" was true.
        logger.info("event=macro_reconcile food=%r note=%s", name, _macro_note)
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
    # LAST, AND ONLY WHEN NOTHING ELSE ANSWERED (B-1.75). The interpreter's own
    # estimate, normalised to per-100g against the quantity it described. It
    # exists so that a food nobody has a row for can still be REPRICED when the
    # user states the amount: without a density there is nothing to multiply,
    # and a clarified estimate-path meal committed either the pre-answer
    # calories or none at all.
    #
    # `macros_from_source` stays FALSE deliberately. This is a density, not a
    # lookup — the provenance must keep saying `estimated`, the card must not
    # claim a source, and `estimated_flag` must stay True. It earns the right
    # to scale, not the right to be believed.
    if src is None and estimate_candidate:
        src = estimate_candidate
    micro_rung = rung if macros_from_source else (
        "usda_generic" if src is usda_candidate else
        "branded_exact" if src is off_candidate else
        "manufacturer" if src is web_candidate else "")
    computed_forward = False
    _v2 = _nutrition_accuracy_v2()
    if src is not None:
        per100 = src.get("per100g") or {
            "calories": src.get("cal_100"), "protein": src.get("protein_100"),
            "carbs": src.get("carbs_100"), "fat": src.get("fat_100"),
            "fiber": src.get("fiber_100"), "sugar": src.get("sugar_100"),
            "sodium": src.get("sodium_100"),
        }
        cal100 = per100.get("calories")
        fdc_id = src.get("fdc_id")
        # COOKING YIELD (v2, Part 2b): USDA often carries only a RAW reference
        # row for a cut eaten cooked (all 8 "skirt steak" rows are raw). Cooking
        # drives off water, so per-100g calories rise; apply the family yield to
        # the density when the seated row reads raw and no cooked row was
        # available. A concentration factor with provenance, not a blanket
        # multiplier — it fires only on a raw row for a normally-cooked food.
        if _v2 and src is usda_candidate and cal100:
            from core.portions import cooking_yield as _cook_yield
            _desc = (src.get("description") or "").lower()
            _is_raw = "raw" in _desc or not any(w in _desc for w in _COOKED_MARKERS)
            _y = _cook_yield(name)
            if _is_raw and _y > 1.0:
                per100 = {k: (round(v * _y, 3) if isinstance(v, (int, float)) else v)
                          for k, v in per100.items()}
                cal100 = per100.get("calories")
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
        # A CALIBRATED PORTION BEATS A CALORIE GUESS WEARING ONE. With no mass
        # at all this function computes `grams = cal / cal100 * 100` — the
        # model's guess BECOMES the portion, and every macro is rescaled off
        # that same guess, so a 38% calorie undercount is mechanically a 38%
        # protein undercount. `mass_grams` declines cups and pieces because
        # "the gram weight is itself a guess"; the alternative it leaves is not
        # no guess, it is a worse one that nothing downstream can see.
        #
        # `portion_mass_for_pricing` answers only where the mass is known to
        # within 30% (a cup of rice, a cup of meat, two eggs, a scoop) and
        # stays silent for "some" and "a bowl", which keeps those on the
        # estimate path where they belong.
        # GENERIC FOODS ONLY, and the failures that taught me the boundary.
        # Applied to every source, this broke four real invariants at once:
        # a mug of soup lost its calories entirely, a label's protein came back
        # as the portion-scaled 3.6 instead of its published 4.2, and
        # `macros_are_estimated` went False on a row whose PORTION we had
        # guessed — the receipt claiming a label for a number we estimated.
        #
        # The distinction is whether the food has a manufacturer-defined unit.
        # A packaged product does: "1 bowl" or "1 slice" of it is a helping we
        # sized, not one of its servings, and the per-serving panel above owns
        # that case — `test_per_serving_is_the_answer` is named for it. A
        # generic whole food has no unit at all, and grams x per-100g is
        # exactly the right model for it.
        _from_measure = False
        if (not _mg and portion_pricing_enabled()
                and src is usda_candidate):
            from skills.nutrition.normalize import portion_mass_for_pricing
            _mg = portion_mass_for_pricing(quantity, name)
            _from_measure = _mg is not None
        # PORTION PRIOR (v2, Part 3): an un-weighed whole food with no serving
        # panel had its grams backed out of the model's ~19%-low calorie guess.
        # A typical as-eaten serving is a better prior than that guess — use it,
        # so the portion stops inheriting the undercount. Only when we still have
        # no mass, so a stated weight or a label serving always wins.
        _from_prior = False
        if _v2 and not _mg:
            from core.portions import portion_prior as _portion_prior
            _pp = _portion_prior(name)
            if _pp:
                _mg, _from_prior = _pp, True
        # USDA text-matches must be NEAR-IDENTICAL to override the model (Danny
        # 2026-07-23: "don't use USDA unless there's an almost identical name
        # match") — a "likely" 0.6-token-overlap hit is exactly the wrong-cousin
        # class (lean chicken for "chicken shawarma"). Label-grade sources
        # (memory / OFF / web) keep their "likely" trust; a demoted USDA item
        # still feeds the estimate path (fiber/sodium scaled to the model's
        # calories) and stays eligible for the web-label lane.
        _trustworthy = macros_from_source and (
            confidence in ("exact", "user-confirmed")
            or (confidence == "likely" and src is not usda_candidate)
            # v2 (Part 1/2): best_candidate's identity gate already required full
            # query coverage before seating a USDA row, so a covered "likely"
            # USDA match is trustworthy for the density. The legacy clause
            # demanded exact name equality — which rejected every verbose USDA
            # whole-food row and let the guess stand.
            or (_v2 and src is usda_candidate))
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
            # A STATED MASS IS NOT AN OVERCOUNT (audit N-2).
            #
            # The overcount bound catches a WRONG FOOD — a cousin match whose
            # numbers multiply the portion. It cannot tell that from a right
            # food whose numbers the MODEL got wrong, and when the user stated
            # an explicit gram weight those are not close calls: 100 g against
            # an exact label at 250 cal/100 g is 250, and the model's 80 is the
            # weakest evidence in the room. It is the reason the lookup ran.
            #
            # So the label's answer was thrown away for disagreeing with the
            # guess it was fetched to replace, and the same product committed
            # 250 or 80 depending on how close the guess happened to be — which
            # is what `test_a_labelled_product_lands_on_the_same_number_
            # whatever_was_guessed` says must never happen. Both red tests were
            # this one line.
            #
            # The discriminator is MATCH QUALITY, not where the mass came from.
            # A single-serve package's net weight is a known mass too — this
            # file argues exactly that a few hundred lines up ("That is a KNOWN
            # mass, not an estimate") — and scoping the exemption to
            # user-stated masses left "1 bar" against an exact label committing
            # 90 or 240 depending on the guess.
            #
            # What still protects a wrong product is `_profile_flip`, which
            # applies unconditionally and is the better-evidenced detector: a
            # collapsed dominant macro is evidence about the ROW. A weak match
            # gets the full guard, and so does a portion with no known mass at
            # all — a helping we had to estimate is exactly where the model's
            # number deserves to win.
            # The bound RISES with a known mass; it does not disappear. Both
            # sides of this are real:
            #
            #   100 g x 250 cal/100g vs a guess of 80   3.1x   a bad guess
            #    60 g x 400 cal/100g vs a guess of 90   2.7x   a bad guess
            #   600 g x 500 cal/100g vs a guess of 400  7.5x   a different food
            #
            # All three are exact matches with a known mass, so no yes/no test
            # on evidence quality separates them — only magnitude does. Removing
            # the guard entirely committed the 7.5x row, which is the case
            # `test_an_enriched_row_may_not_multiply_the_estimate` exists for.
            #
            # Above 4x the arithmetic stops being "the model guessed badly
            # about the right food": a 19% undercount is what the loose bound
            # was argued for, and nothing in that argument stretches to seven
            # times. `_profile_flip` still applies unconditionally, so a wrong
            # row that also collapses a dominant macro is caught either way.
            # A FABRICATED MASS IS NOT A KNOWN ONE. `_mg` reaches here from
            # three places and only two of them are measurements: a stated
            # weight, a label's own serving panel ("That is a KNOWN mass, not
            # an estimate" — see where `_from_panel` is set), and
            # `portion_prior(name)`, which is a population typical for an
            # un-weighed whole food. The wider 4x bound is argued directly from
            # "all three are exact matches with a known mass"; a prior is
            # neither exact nor a mass anyone measured, so it must not buy the
            # extra room. `_from_prior` was computed for this and never read.
            _known_mass = bool(_mg) and not _from_prior and not _from_measure
            _bound = (_OVERCOUNT_MULTIPLE_KNOWN_MASS
                      if (_known_mass and _trustworthy)
                      else _OVERCOUNT_MULTIPLE)
            _overshoot = cal > _bound * _llm0[0]
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
        # NOT "component_estimate". That rung used to be assigned here purely
        # because the food was RESTAURANT-classed, and it renders to the user
        # as "Estimated from its components" — under `display_detail`'s own
        # rule that the line must be true. No components were ever computed;
        # nothing has ever seated on that rung (the engine exists on two
        # unmerged branches, 40d4d9b / e4d651d). A provenance line is a
        # citation, and a false citation is worse than a plain "estimate".
        # The rung stays in the ladder for the engine to claim when it lands.
        rung = "estimate"

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
        # THE STATED PORTION, NOT THE DERIVED ONE. `_implied_grams` is set from
        # `cal / cal100 * 100` on the estimate path (see above), so
        # `calories / _implied_grams` is identically `cal100/100` — a constant.
        # Measuring density against it cannot detect a portion error in either
        # direction, which is why one cup of rice committed at 1 cal with the
        # density check live and silent. `normalize_quantity` reaches masses
        # `mass_grams` cannot ("1 cup" -> 158 g), which is the same reason the
        # zero-calorie branch above reaches for it.
        # The LOWER BOUND, not the point estimate: this feeds a refusal, and a
        # refusal should rest on the most generous reading of the portion. A
        # vague measure ("some", 80g +/- 85g) returns None and is judged only
        # by the checks that need no mass.
        # ...and the UPPER bound alongside it, because the ceiling wants the
        # opposite end. Passing the pessimistic lower mass to both made "some
        # olive oil" compute as denser than pure fat and lose its exact USDA
        # row — a legitimately dense food punished for a hedged portion.
        _stated_g = _stated_hi = None
        try:
            from skills.nutrition.normalize import (confident_lower_mass,
                                                    confident_upper_mass)
            _stated_g = confident_lower_mass(quantity or "", name or "")
            _stated_hi = confident_upper_mass(quantity or "", name or "")
        except Exception:
            _stated_g = _stated_hi = None
        _findings = _sanity.check_values(
            calories=cal, protein=protein, carbs=carbs, fat=fat,
            fiber=fiber, grams=(_stated_g or _implied_grams),
            grams_upper=(_stated_hi or _implied_grams), name=name)
        _fatal = [f for f in _findings if f.is_fatal]
        # THE MODEL'S READ IS NOT A REMEDY WHEN THE MODEL IS THE PROBLEM.
        #
        # Every other fatal finding means a SOURCE row was scaled wrongly, so
        # reverting to `_llm0` is the right escape — the model's number was
        # produced without that bad basis. `energy_density_negligible` is the
        # opposite: the row says a real portion carries no energy, and when the
        # model is what supplied the near-zero, `_llm0` IS the number that
        # failed. Reverting to it made the refusal a no-op:
        #
        #     analyze("White rice", "1 cup", llm_cal=1)  -> committed 1
        #     analyze("White rice", "1 cup", llm_cal=0)  -> committed 206
        #
        # Two cases one calorie apart, opposite outcomes — the zero-calorie
        # branch further up catches `cal <= 0` and reprices, and nothing caught
        # the 1. So when we have a source density and a stated mass, price it
        # forward here for the same reason that branch does.
        _negligible_only = bool(_fatal) and all(
            f.code == "energy_density_negligible" for f in _fatal)
        # THE POINT ESTIMATE HERE, not the lower bound. `_stated_g` is
        # deliberately pessimistic because it decides a REFUSAL; using it as
        # the replacement VALUE priced a cup of rice at its smallest plausible
        # mass (135g -> 175 cal instead of 158g -> 206). One number answers
        # "should we refuse", a different one answers "what instead".
        _reprice_g = None
        _reprice_per100 = locals().get("per100") or {}
        _reprice_cal100 = _reprice_per100.get("calories")
        if _negligible_only:
            try:
                from skills.nutrition.normalize import portion_mass_for_pricing
                _reprice_g = portion_mass_for_pricing(quantity or "", name or "")
            except Exception:
                _reprice_g = None
        if (_negligible_only and _reprice_g
                and _reprice_cal100 and _reprice_cal100 > 0):
            cal100, per100 = _reprice_cal100, _reprice_per100
            _ratio = _reprice_g / 100.0
            cal = round(cal100 * _ratio)
            if per100.get("protein") is not None:
                protein = round(per100["protein"] * _ratio, 1)
            if per100.get("carbs") is not None:
                carbs = round(per100["carbs"] * _ratio, 1)
            if per100.get("fat") is not None:
                fat = round(per100["fat"] * _ratio, 1)
            # THE WHOLE PANEL, not just the macros. Rescaling four fields and
            # leaving fibre, sugar, sodium and the micros at values derived
            # from the mass we just REJECTED is worse than not repricing: the
            # row then carries a correct calorie count beside a fabricated
            # panel, under `micronutrient_source="usda_exact"`. Measured on
            # black beans "1 cup" at llm_cal=1 — 158 cal committed correctly
            # with fibre 0.1 g and sodium 2 mg against a real 10.4 g / 286 mg,
            # and the coach note flipped from "good fibre" to "~0g fiber
            # (low)". Nothing downstream heals it, because
            # `handlers/tool_executor.py` backfills only when the field is
            # None and 0.0 is not None.
            if per100.get("fiber") is not None:
                fiber = round(per100["fiber"] * _ratio, 1)
            if per100.get("sugar") is not None:
                sugar = round(per100["sugar"] * _ratio, 1)
            if per100.get("sodium") is not None:
                sodium = round(per100["sodium"] * _ratio, 0)
            for _mk in _MICRO_KEYS:
                _mv = per100.get(_mk)
                if _mv is not None:
                    micros[_mk] = round(_mv * _ratio, 2)
            _implied_grams = _reprice_g
            computed_forward = True
            logger.warning(
                "sanity refusal for %r: %s — the model supplied the near-zero, "
                "so repriced from the source at %.0fg -> %s cal",
                name, "; ".join(f.code for f in _fatal), _reprice_g, cal)
        elif _fatal:
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

    # ADDED FAT / MARINADE (v2, Part 4): oil, butter, marinade, dressing NAMED in
    # the food are not in any base-food row and USDA never carries them. Add an
    # explicit, quantified term (and its fat grams) to the committed calories.
    # The phrase keys target ADDITIONS ("in butter", "with ranch"), not cooking
    # methods, so a base row that already includes the fat is not double-counted.
    _added_fat_note = ""
    if _v2 and source != "estimate":
        # Only add on a SEATED base density: the base row is the plain food, so a
        # named fat is genuinely on top. On the estimate path the model's guess
        # already folds the whole dish in, and adding again double-counts. The
        # common case — butter/marinade NOT in the food name at all — is Part 5's
        # job to ELICIT; this only catches a fat the name happens to state.
        from core.portions import added_fat_calories as _added_fat
        _afc, _afl = _added_fat(name)
        if _afc:
            cal = round((cal or 0) + _afc)
            fat = round((fat or 0) + _afc / 9.0, 1)
            _added_fat_note = f"added {_afl} (+{_afc} cal)"

    pd, satiety, quality = _derive(cal, protein, carbs, fat, fiber, sugar)

    # Build the coaching note the LLM uses to actually coach (not just acknowledge)
    bits = []
    if _added_fat_note:
        bits.append(_added_fat_note)
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
    # `web_estimate` is a search result read by a model, not a panel — so it
    # gets neither the label wording nor USDA's. Saying "label match" over it
    # is the same overclaim the receipt string carried.
    if source == "web_estimate":
        conf_note = {
            "exact": "typical published numbers",
            "likely": "typical published numbers",
            "user-confirmed": "your usual (confirmed)",
            "estimated": "estimate",
        }.get(confidence, confidence)
    else:
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
        serving_text=str((src or {}).get("serving_text") or ""),
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
