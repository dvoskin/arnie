"""Day-level nutrition-quality score (0–100) for the Coach Health Score card.

Two lanes, deliberately explainable (each driver is surfaced to the client):

  NUTRIENT PROFILE (dominant) — everything normalized per 1000 kcal so portion
  size doesn't skew the read:
    • protein density   (satiety + recomposition support)
    • fiber density     (14 g / 1000 kcal — IOM guideline)
    • sugar load        (penalty past ~25 g / 1000 kcal)
    • sodium load       (penalty past ~1150 mg / 1000 kcal ≈ 2300 mg on 2000)
    • micronutrient breadth (distinct vitamins/minerals captured across the day)

  PROCESSING (modifier) — a NOVA-style proxy from food-name keywords, weighted
  by each item's CALORIE SHARE of the day: ultra-processed calories penalize
  hardest, lightly-processed staples (bars, shakes, deli) a little, whole-food
  calories earn a small bonus. Keyword matching is crude by design — it's a
  proxy, honest and cheap; a full classification model can replace _processing
  later without touching the score contract.

Pure functions over the /day food-entry dicts (name, calories, protein, fiber,
sugar, sodium, micros) — no DB, trivially testable.
"""
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
)
# Processed-but-defensible staples — small penalty (they carry additives /
# refined bases but often earn their place in a tracked diet).
_PROCESSED = (
    "protein bar", "bar", "shake", "protein powder", "whey", "casein", "deli",
    "sausage", "bacon", "jerky", "canned", "wrap", "tortilla", "bread",
    "cracker", "granola", "cereal", "pretzel", "lunch meat", "ham", "salami",
    "frozen meal", "meal prep",
)
# Whole-food hints — small bonus by calorie share.
_WHOLE = (
    "chicken", "beef", "steak", "turkey", "salmon", "tuna", "fish", "shrimp",
    "egg", "rice", "potato", "sweet potato", "oat", "yogurt", "greek", "skyr",
    "cottage", "fruit", "apple", "banana", "berr", "orange", "melon", "grape",
    "vegetable", "broccoli", "salad", "greens", "spinach", "cucumber", "tomato",
    "pepper", "carrot", "avocado", "nut", "almond", "walnut", "peanut", "milk",
    "quinoa", "bean", "lentil", "chickpea", "hummus", "tofu", "edamame", "gyro",
    "bowl",
)


def _processing_class(name: str) -> int:
    """0 = whole-leaning, 1 = processed staple, 2 = ultra-processed."""
    n = (name or "").lower()
    if any(k in n for k in _ULTRA):
        return 2
    if any(k in n for k in _PROCESSED):
        return 1
    if any(k in n for k in _WHOLE):
        return 0
    return 1        # unknown → middle of the road, never assume pristine


def _scale(value: float, lo: float, hi: float, points: float) -> float:
    """Linear 0→points as value moves lo→hi, clamped."""
    if hi <= lo:
        return 0.0
    t = (value - lo) / (hi - lo)
    return points * max(0.0, min(1.0, t))


def compute_health_score(entries: list) -> Optional[dict]:
    """Score a day's logged foods. None when there's too little signal to be
    honest about (< 300 kcal logged) — the card hides itself.

    Returns {"score", "band", "drivers": [{"label", "delta"}...], "processed_pct"}.
    Drivers carry the SIGNED point impact of each lane so the card can show WHY.
    """
    entries = [e for e in (entries or []) if (e.get("calories") or 0) > 0]
    kcal = sum(float(e.get("calories") or 0) for e in entries)
    if kcal < 300:
        return None

    per1000 = 1000.0 / kcal
    protein = sum(float(e.get("protein") or 0) for e in entries) * per1000
    fiber = sum(float(e.get("fiber") or 0) for e in entries) * per1000
    sugar = sum(float(e.get("sugar") or 0) for e in entries) * per1000
    sodium = sum(float(e.get("sodium") or 0) for e in entries) * per1000

    # Micronutrient breadth — distinct micros with a real value across the day.
    micro_keys = set()
    for e in entries:
        micros = e.get("micros") or {}
        if isinstance(micros, dict):
            micro_keys.update(k for k, v in micros.items() if (v or 0) > 0)

    # Processing shares by calorie weight.
    ultra_kcal = sum(float(e.get("calories") or 0) for e in entries
                     if _processing_class(e.get("name") or "") == 2)
    whole_kcal = sum(float(e.get("calories") or 0) for e in entries
                     if _processing_class(e.get("name") or "") == 0)
    proc_kcal = kcal - ultra_kcal - whole_kcal
    u, p, w = ultra_kcal / kcal, proc_kcal / kcal, whole_kcal / kcal

    drivers = []

    def lane(label: str, delta: float):
        if abs(delta) >= 0.5:
            drivers.append({"label": label, "delta": round(delta)})
        return delta

    score = 50.0
    score += lane("Protein density", _scale(protein, 25, 55, 16))
    score += lane("Fiber", _scale(fiber, 4, 14, 14))
    score += lane("Added sugar", -_scale(sugar, 25, 75, 15))
    score += lane("Sodium", -_scale(sodium, 1150, 2300, 8))
    score += lane("Micronutrient breadth", _scale(float(len(micro_keys)), 2, 12, 8))
    score += lane("Whole foods", 12 * w)
    score += lane("Ultra-processed load", -(26 * u + 6 * p))

    score = int(round(max(0.0, min(100.0, score))))
    band = ("excellent" if score >= 80 else
            "good" if score >= 65 else
            "fair" if score >= 45 else "poor")
    drivers.sort(key=lambda d: -abs(d["delta"]))
    return {
        "score": score,
        "band": band,
        "drivers": drivers[:4],
        "processed_pct": int(round(100 * (u + p))),
    }
