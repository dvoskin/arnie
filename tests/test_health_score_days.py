"""Canonical-day regression suite for the Health Score.

Representative days with hand-checked expectations, asserting BANDS and driver
signs rather than exact scores — constant tuning may nudge numbers, but a clean
bulk day dropping out of "good/excellent" or a fast-food day climbing out of
"poor" is a regression, not a tune.

Also pins the accuracy semantics added 2026-07-03:
  • coverage-aware lanes (null ≠ zero for fiber/sugar/sodium)
  • micro breadth weighted by micro coverage
  • explicit processing_level beats the keyword proxy; keyword calls are damped
  • whole-food sugar discounted 50% (intrinsic vs added)
  • token-based keyword matching (no more "bar" ⊂ "barbecue")
"""
from core.health_score import compute_health_score, _processing_class


def _e(name, cal, protein=0, fiber=0, sugar=0, sodium=0, micros=None,
       processing_level=None, unenriched=False):
    e = {"name": name, "calories": cal, "protein": protein,
         "micros": micros or {}, "processing_level": processing_level}
    if unenriched:
        # An entry that never got USDA/web/LLM enrichment stores NULLs.
        e.update({"fiber": None, "sugar": None, "sodium": None})
    else:
        e.update({"fiber": fiber, "sugar": sugar, "sodium": sodium})
    return e


# ── canonical days ──────────────────────────────────────────────────────────

def test_clean_bulk_day_is_excellent():
    day = [
        _e("Eggs and oatmeal with blueberries", 600, protein=35, fiber=8, sugar=12,
           sodium=300, micros={"iron": 3, "folate": 90, "potassium": 500}),
        _e("Grilled chicken, rice, broccoli", 800, protein=60, fiber=6, sodium=500,
           micros={"zinc": 3, "vitamin_c": 60, "magnesium": 80, "niacin": 12}),
        _e("Greek yogurt with almonds", 350, protein=25, fiber=3, sugar=9, sodium=90,
           micros={"calcium": 300, "vitamin_b12": 1.1, "riboflavin": 0.4}),
        _e("Salmon with sweet potato", 700, protein=45, fiber=5, sodium=400,
           micros={"vitamin_d": 12, "vitamin_b6": 0.9, "phosphorus": 350}),
    ]
    s = compute_health_score(day)
    assert s["band"] in ("good", "excellent")
    assert s["score"] >= 75
    assert s["coverage"]["nutrients"] == 100
    deltas = {d["label"]: d["delta"] for d in s["drivers"]}
    assert deltas.get("Protein density", 0) > 0


def test_fast_food_day_is_poor():
    day = [
        _e("McDonald's Big Mac", 590, protein=25, fiber=3, sugar=9, sodium=1050),
        _e("McDonald's fries", 480, protein=6, fiber=4, sodium=400),
        _e("Coca Cola", 300, sugar=75),
        _e("Oreo cookies", 320, protein=2, sugar=28, sodium=190),
    ]
    s = compute_health_score(day)
    assert s["band"] == "poor"
    assert s["processed_pct"] >= 80
    deltas = {d["label"]: d["delta"] for d in s["drivers"]}
    assert deltas.get("Ultra-processed load", 0) < 0


def test_low_log_day_hides_card():
    assert compute_health_score([_e("Black coffee", 5), _e("Apple", 95)]) is None


# ── coverage honesty ────────────────────────────────────────────────────────

def test_unenriched_day_moves_no_nutrient_lanes():
    # All-null fiber/sugar/sodium: the old code read them as ZERO — free pass
    # on sugar/sodium, no fiber credit. Now those lanes simply don't move.
    day = [
        _e("Restaurant burrito", 900, protein=40, unenriched=True),
        _e("Takeout pad thai", 800, protein=30, unenriched=True),
    ]
    s = compute_health_score(day)
    assert s["coverage"]["nutrients"] == 0
    labels = {d["label"] for d in s["drivers"]}
    assert not labels & {"Fiber", "Sugar load", "Sodium"}


def test_sodium_penalty_not_diluted_by_unenriched_calories():
    # 800 enriched kcal carrying heavy sodium + 800 unenriched kcal. The old
    # math divided sodium by ALL calories (diluting the density) — the new
    # math reads the density off the covered sample and scales the lane by
    # coverage, so heavy sodium still registers.
    day = [
        _e("Deli sandwich", 800, protein=35, fiber=4, sugar=6, sodium=2400),
        _e("Mystery takeout", 800, protein=30, unenriched=True),
    ]
    s = compute_health_score(day)
    deltas = {d["label"]: d["delta"] for d in s["drivers"]}
    assert deltas.get("Sodium", 0) < 0
    assert s["coverage"]["nutrients"] == 50


def test_micro_breadth_weighted_by_micro_coverage():
    micros = {"iron": 3, "zinc": 2, "vitamin_c": 40, "calcium": 200,
              "potassium": 600, "magnesium": 90, "folate": 120,
              "vitamin_d": 10, "vitamin_b12": 1.5, "niacin": 10,
              "vitamin_a": 300, "vitamin_k": 60}
    full = [_e("Chicken and vegetables", 1000, protein=60, fiber=8, micros=micros),
            _e("Salmon and rice", 1000, protein=50, fiber=4, micros={"vitamin_d": 10})]
    half = [_e("Chicken and vegetables", 1000, protein=60, fiber=8, micros=micros),
            _e("Salmon and rice", 1000, protein=50, fiber=4, micros={})]
    s_full = compute_health_score(full)
    s_half = compute_health_score(half)
    d_full = {d["label"]: d["delta"] for d in s_full["drivers"]}
    d_half = {d["label"]: d["delta"] for d in s_half["drivers"]}
    assert d_full.get("Micronutrient breadth", 0) > d_half.get("Micronutrient breadth", 0)
    assert s_full["coverage"]["micros"] == 100
    assert s_half["coverage"]["micros"] == 50


# ── processing classification ───────────────────────────────────────────────

def test_explicit_processing_level_beats_keywords():
    # "Pizza" keywords say ultra — but a homemade pizza the model classified
    # as 'processed' should not eat the full ultra penalty.
    kw = [_e("Homemade pizza", 900, protein=40, fiber=5, sodium=900)]
    explicit = [_e("Homemade pizza", 900, protein=40, fiber=5, sodium=900,
                   processing_level="processed")]
    assert compute_health_score(explicit)["score"] > compute_health_score(kw)["score"]


def test_explicit_classification_gets_full_weight_keywords_damped():
    # Same whole-food day; explicit classification earns a larger whole-food
    # bonus than the damped keyword call.
    kw = [_e("Chicken and rice", 1000, protein=70, fiber=5)]
    explicit = [_e("Chicken and rice", 1000, protein=70, fiber=5,
                   processing_level="whole")]
    d_kw = {d["label"]: d["delta"] for d in compute_health_score(kw)["drivers"]}
    d_ex = {d["label"]: d["delta"] for d in compute_health_score(explicit)["drivers"]}
    assert d_ex.get("Whole foods", 0) > d_kw.get("Whole foods", 0)


def test_keyword_token_matching_fixes_collisions():
    assert _processing_class("Barbecue chicken") == 0        # "bar" ⊄ "barbecue"
    assert _processing_class("Hamburger steak") == 0          # "ham" ⊄ "hamburger"; steak wins
    assert _processing_class("Ham sandwich") == 1             # exact "ham" still hits
    assert _processing_class("Protein bar") == 1
    assert _processing_class("Built bars") == 1               # plural still hits
    assert _processing_class("Pepperoni slices") == 1         # cured meat, not "pepper"→whole
    assert _processing_class("Blueberries") == 0              # berry family
    assert _processing_class("Mixed berries") == 0
    assert _processing_class("McDonalds nuggets") == 2        # prefix + plural
    assert _processing_class("Oatmeal with honey") == 0


# ── sugar semantics ─────────────────────────────────────────────────────────

def test_whole_food_sugar_discounted_vs_candy():
    # Same total sugar grams — fruit day (whole-classified) should outscore
    # the candy day because intrinsic sugar is discounted 50%.
    fruit = [_e("Fruit salad with banana and berries", 800, protein=8,
                fiber=10, sugar=90, processing_level="whole")]
    candy = [_e("Skittles and gummy bears", 800, protein=0,
                fiber=0, sugar=90, processing_level="ultra_processed")]
    s_fruit = compute_health_score(fruit)
    s_candy = compute_health_score(candy)
    assert s_fruit["score"] > s_candy["score"]
    d_fruit = {d["label"]: d["delta"] for d in s_fruit["drivers"]}
    d_candy = {d["label"]: d["delta"] for d in s_candy["drivers"]}
    assert d_candy.get("Sugar load", 0) < d_fruit.get("Sugar load", 0)


def test_payload_contract():
    s = compute_health_score([_e("Chicken bowl", 700, protein=50, fiber=6)])
    assert set(s) == {"score", "band", "drivers", "processed_pct", "coverage"}
    assert set(s["coverage"]) == {"nutrients", "micros"}
    assert all(set(d) == {"label", "delta"} for d in s["drivers"])
    assert 0 <= s["score"] <= 100
