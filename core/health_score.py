"""Day-level nutrition-quality score (0–100) for the Coach Health Score card.

Two lanes, deliberately explainable (each driver is surfaced to the client):

  NUTRIENT PROFILE (dominant) — everything normalized per 1000 kcal so portion
  size doesn't skew the read:
    • protein density   (satiety + recomposition support)
    • fiber density     (14 g / 1000 kcal — IOM guideline)
    • sugar load        (penalty past ~25 g / 1000 kcal; sugar from whole foods
                         is discounted 50% — USDA reports TOTAL sugar, and fruit
                         is not Skittles)
    • sodium load       (penalty past ~1150 mg / 1000 kcal ≈ 2300 mg on 2000)
    • micronutrient breadth (distinct vitamins/minerals captured across the day)

    COVERAGE-AWARE: fiber/sugar/sodium are null (not zero) on entries that never
    got a database/LLM enrichment. Treating null as 0 both inflates (no sugar or
    sodium penalty) and deflates (no fiber credit) the score. Instead, densities
    are computed over the CALORIES THAT ACTUALLY CARRY DATA, and each lane's
    points are scaled by that coverage — a day where only 30% of calories are
    enriched can only move 30% of the lane's points. Coverage is surfaced in the
    payload so the card can tag low-confidence days.

  PROCESSING (modifier) — NOVA-style classification weighted by each item's
  CALORIE SHARE of the day: ultra-processed calories penalize hardest, lightly-
  processed staples a little, whole-food calories earn a small bonus. The
  entry's explicit `processing_level` (classified by the model at log time)
  wins; food-name keywords are the fallback for older rows. Keyword-classified
  calories get their influence damped (×0.7) — the keyword proxy is crude by
  design, and a misread name shouldn't be able to swing the score as hard as a
  deliberate classification.

Pure functions over the /day food-entry dicts (name, calories, protein, fiber,
sugar, sodium, micros, processing_level) — no DB, trivially testable.
"""
import re
from typing import Optional

# NOVA-4-ish markers — ultra-processed, penalize by calorie share.
_ULTRA = (
    "chips", "crisps", "soda", "cola", "candy", "cookie", "donut", "doughnut",
    "pastry", "croissant", "ice cream", "fries", "nugget", "hot dog", "corn dog",
    "instant noodle", "ramen", "energy drink", "milkshake", "pop tart", "gummy",
    "mcdonald", "burger king", "wendy", "taco bell", "kfc", "domino", "doritos",
    "cheetos", "oreo", "snickers", "m&m", "skittles", "twix", "kitkat",
    "monster", "red bull", "pizza", "white bread", "sweet roll", "brownie",
    "cake", "frosting", "cinnamon roll",
    # RU — high-frequency ultra-processed
    "чипсы", "газировка", "кола", "конфеты", "печенье", "шоколад",
    "мороженое", "пицца", "торт", "булочка", "фастфуд", "вафли",
    "пирожное", "сухарики",
)
# Processed-but-defensible staples — small penalty (they carry additives /
# refined bases but often earn their place in a tracked diet).
_PROCESSED = (
    "protein bar", "bar", "shake", "protein powder", "whey", "casein", "deli",
    "sausage", "bacon", "jerky", "canned", "wrap", "tortilla", "bread",
    "cracker", "granola", "cereal", "pretzel", "lunch meat", "ham", "salami",
    "pepperoni", "frozen meal", "meal prep",
    # RU — processed staples
    "хлеб", "сыр", "колбаса", "сосиски", "батончик", "лаваш",
    "консервы", "протеиновый",
)
# Whole-food hints — small bonus by calorie share.
_WHOLE = (
    "chicken", "beef", "steak", "turkey", "salmon", "tuna", "fish", "shrimp",
    "egg", "rice", "potato", "sweet potato", "oat", "oatmeal", "yogurt",
    "greek", "skyr", "cottage", "fruit", "apple", "banana", "berry", "berries",
    "blueberr", "strawberr", "raspberr", "blackberr", "orange",
    "melon", "grape", "vegetable", "broccoli", "salad", "greens", "spinach",
    "cucumber", "tomato", "pepper", "carrot", "avocado", "nut", "almond",
    "walnut", "peanut", "milk", "quinoa", "bean", "lentil", "chickpea",
    "hummus", "tofu", "edamame", "gyro", "bowl", "pork", "lamb", "cod",
    "tilapia", "sardine", "olive", "zucchini", "asparagus", "cauliflower",
    "onion", "mushroom", "kale", "mango", "peach", "pear", "pineapple",
    "watermelon",
    # RU — whole-leaning (prefix matching covers inflections: "кури" hits
    # курица/куриное/куриного; "помидор" hits помидоры/помидоров)
    "курица", "куриное", "куриная", "индейка", "говядина", "рыба", "лосось",
    "яйцо", "яйца", "омлет", "творог", "гречка", "овсянка", "картофель",
    "помидор", "огурец", "огурцы", "овощи", "фрукты", "яблоко", "банан",
    "салат", "капуста", "морковь", "орехи",
)

# Explicit model classification (log_food.processing_level) → class int.
_EXPLICIT_LEVELS = {"whole": 0, "processed": 1, "ultra_processed": 2}

# Keyword-classified calories get damped influence in the processing lane —
# the name proxy is crude; only a deliberate classification earns full weight.
_KEYWORD_DAMP = 0.7


def _tokens(s: str) -> list:
    # Latin + Cyrillic — a third of the beta logs food in Russian, and a
    # Latin-only tokenizer reduced every RU name to zero tokens (= unknown).
    return re.findall(r"[a-zа-яё0-9&]+", (s or "").lower())


def _token_matches(name_tok: str, kw_tok: str) -> bool:
    """One name token vs one keyword token. Exact or simple plural always;
    prefix only for keywords ≥4 chars (so "berr"→"berries" and
    "mcdonald"→"mcdonalds" hit, but "bar" can't catch "barbecue" and
    "ham" can't catch "hamburger")."""
    if name_tok == kw_tok or name_tok == kw_tok + "s" or name_tok == kw_tok + "es":
        return True
    return len(kw_tok) >= 4 and name_tok.startswith(kw_tok)


def _kw_in(name_toks: list, kw_toks: tuple) -> bool:
    """Keyword tokens appear as a consecutive run inside the name tokens."""
    n, k = len(name_toks), len(kw_toks)
    for i in range(n - k + 1):
        if all(_token_matches(name_toks[i + j], kw_toks[j]) for j in range(k)):
            return True
    return False


_ULTRA_T = tuple(tuple(_tokens(k)) for k in _ULTRA)
_PROCESSED_T = tuple(tuple(_tokens(k)) for k in _PROCESSED)
_WHOLE_T = tuple(tuple(_tokens(k)) for k in _WHOLE)


def _processing_class(name: str) -> int:
    """0 = whole-leaning, 1 = processed staple, 2 = ultra-processed,
    -1 = UNKNOWN (no keyword hit). Unknown must stay unknown: the keyword
    lists are English-only, so defaulting no-match to "processed" scored
    Denys's omelet/chicken/tomato day (Russian names, no explicit levels)
    as processed_pct=100 — the "100% processed on whole foods" report."""
    toks = _tokens(name)
    if not toks:
        return -1
    if any(_kw_in(toks, k) for k in _ULTRA_T):
        return 2
    if any(_kw_in(toks, k) for k in _PROCESSED_T):
        return 1
    if any(_kw_in(toks, k) for k in _WHOLE_T):
        return 0
    return -1


def _scale(value: float, lo: float, hi: float, points: float) -> float:
    """Linear 0→points as value moves lo→hi, clamped."""
    if hi <= lo:
        return 0.0
    t = (value - lo) / (hi - lo)
    return points * max(0.0, min(1.0, t))


def compute_health_score(entries: list) -> Optional[dict]:
    """Score a day's logged foods. None when there's too little signal to be
    honest about (< 300 kcal logged) — the card hides itself.

    Returns {"score", "band", "drivers": [{"label", "delta"}...],
    "processed_pct", "coverage": {"nutrients": pct, "micros": pct}}.
    Drivers carry the SIGNED point impact of each lane so the card can show WHY.
    """
    entries = [e for e in (entries or []) if (e.get("calories") or 0) > 0]
    kcal = sum(float(e.get("calories") or 0) for e in entries)
    if kcal < 300:
        return None

    # Protein comes from the LLM on every log — full coverage by construction.
    protein = sum(float(e.get("protein") or 0) for e in entries) * 1000.0 / kcal

    # Per-entry processing class: the model's explicit call wins, keywords are
    # the fallback for older rows. Track how many calories were explicitly
    # classified — keyword-classified calories get damped influence.
    classed = []            # (entry_kcal, class, explicit)
    for e in entries:
        cal = float(e.get("calories") or 0)
        lvl = str(e.get("processing_level") or "").strip().lower()
        if lvl in _EXPLICIT_LEVELS:
            classed.append((cal, _EXPLICIT_LEVELS[lvl], True))
        else:
            classed.append((cal, _processing_class(e.get("name") or ""), False))
    whole_class = {id(e): c for e, (_, c, _x) in zip(entries, classed)}

    # ── Nutrient coverage: fiber/sugar/sodium are NULL (not zero) on entries
    # that never got enriched. Compute densities over the calories that carry
    # data, and scale each lane by that coverage share.
    covered = [e for e in entries
               if any(e.get(k) is not None for k in ("fiber", "sugar", "sodium"))]
    covered_kcal = sum(float(e.get("calories") or 0) for e in covered)
    nutrient_cov = covered_kcal / kcal if kcal else 0.0
    fiber = sugar_eff = sodium = 0.0
    if covered_kcal > 0:
        per1000c = 1000.0 / covered_kcal
        fiber = sum(float(e.get("fiber") or 0) for e in covered) * per1000c
        # Whole-food sugar is intrinsic (fruit/dairy), not added — USDA only
        # reports TOTAL sugar, so discount whole-classified entries 50%.
        sugar_eff = sum(
            float(e.get("sugar") or 0) * (0.5 if whole_class.get(id(e)) == 0 else 1.0)
            for e in covered) * per1000c
        sodium = sum(float(e.get("sodium") or 0) for e in covered) * per1000c

    # Micronutrient breadth — distinct micros with a real value across the day,
    # weighted by how much of the day's calories actually carry a micro panel
    # (so a badly-enriched day isn't punished for missing data).
    micro_keys = set()
    micro_kcal = 0.0
    for e in entries:
        micros = e.get("micros") or {}
        if isinstance(micros, dict) and micros:
            present = {k for k, v in micros.items() if (v or 0) > 0}
            if present:
                micro_keys.update(present)
                micro_kcal += float(e.get("calories") or 0)
    micro_cov = micro_kcal / kcal if kcal else 0.0

    # Processing shares by calorie weight, split by classification confidence:
    # explicit calories count fully, keyword-classified calories are damped.
    u = p = w = 0.0
    for cal, cls, explicit in classed:
        if cls < 0:
            continue                # unknown: no opinion, no penalty
        weight = (cal / kcal) * (1.0 if explicit else _KEYWORD_DAMP)
        if cls == 2:
            u += weight
        elif cls == 0:
            w += weight
        else:
            p += weight
    # Raw (undamped) shares for the processed_pct surface, computed over the
    # CLASSIFIED calories only — unknown food is a coverage fact, never a
    # verdict. classification coverage rides alongside so the card can say
    # "of what I can classify" honestly.
    classified_kcal = sum(cal for cal, cls, _x in classed if cls >= 0)
    class_cov = classified_kcal / kcal if kcal else 0.0
    if classified_kcal > 0:
        raw_u = sum(cal for cal, cls, _x in classed if cls == 2) / classified_kcal
        raw_w = sum(cal for cal, cls, _x in classed if cls == 0) / classified_kcal
        raw_p = max(0.0, 1.0 - raw_u - raw_w)
    else:
        raw_u = raw_w = raw_p = 0.0

    drivers = []

    def lane(label: str, delta: float):
        if abs(delta) >= 0.5:
            drivers.append({"label": label, "delta": round(delta)})
        return delta

    score = 50.0
    d_protein = lane("Protein density", _scale(protein, 25, 55, 16))
    d_fiber = lane("Fiber", _scale(fiber, 4, 14, 14) * nutrient_cov)
    d_sugar = lane("Sugar load", -_scale(sugar_eff, 25, 75, 15) * nutrient_cov)
    d_sodium = lane("Sodium", -_scale(sodium, 1150, 2300, 8) * nutrient_cov)
    d_micro = lane("Micronutrient breadth",
                   _scale(float(len(micro_keys)), 2, 12, 8) * micro_cov)
    d_whole = lane("Whole foods", 12 * w)
    d_ultra = lane("Ultra-processed load", -(26 * u + 6 * p))
    score += (d_protein + d_fiber + d_sugar + d_sodium
              + d_micro + d_whole + d_ultra)

    # The drivers show what MOVED — the headroom names the biggest ABSENT
    # lane, so a 79 is never a mystery ("why not higher?" has an answer).
    # Coverage-honest: a lane capped by missing data can only promise what
    # the data could actually earn.
    headrooms = [
        ("Fiber", 14 * nutrient_cov - d_fiber,
         "Fiber's the open lane — vegetables, fruit, oats"),
        ("Protein density", 16 - d_protein,
         "More protein per calorie"),
        ("Micronutrient breadth", 8 * micro_cov - d_micro,
         "More variety across vitamins and minerals"),
        ("Whole foods", 12 - d_whole,
         "More of the day from whole foods"),
        ("Sugar load", -d_sugar, "Easing sugar back"),
        ("Sodium", -d_sodium, "Going lighter on sodium"),
        ("Ultra-processed load", -d_ultra, "Swapping out ultra-processed"),
    ]
    _label, _pts, _hint = max(headrooms, key=lambda h: h[1])
    headroom = ({"label": _label, "points": int(round(_pts)),
                 "line": f"{_hint} — up to +{int(round(_pts))}."}
                if _pts >= 3 and score < 97 else None)

    score = int(round(max(0.0, min(100.0, score))))
    band = ("excellent" if score >= 80 else
            "good" if score >= 65 else
            "fair" if score >= 45 else "poor")
    drivers.sort(key=lambda d: -abs(d["delta"]))
    return {
        "score": score,
        "band": band,
        "drivers": drivers[:4],
        "processed_pct": int(round(100 * (raw_u + raw_p))),
        # The alarming fact is ULTRA-processed share — staples (sandwiches,
        # sushi, bread) are context, not a verdict. Clients should headline
        # ultra_pct and show whole/staple shares alongside.
        "ultra_pct": int(round(100 * raw_u)),
        "whole_pct": int(round(100 * raw_w)),
        # Data-honesty surface: how much of the day's calories carry enriched
        # nutrient data / a micro panel / a processing classification. The
        # card tags low-coverage days softer.
        "coverage": {"nutrients": int(round(100 * nutrient_cov)),
                     "micros": int(round(100 * micro_cov)),
                     "classified": int(round(100 * class_cov))},
        # The biggest absent lane (or None near the ceiling) — "what would
        # raise it". Clients render `line` as one quiet row under the drivers.
        "headroom": headroom,
    }
