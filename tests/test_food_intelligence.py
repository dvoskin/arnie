"""Pure-logic tests for food name handling — the generic-food gate that this
session shipped to stop silent memory reuse."""
import pytest
from core.food_intelligence import (
    normalize_name, is_generic_food_name, score_match, normalize_food_logging_mode,
    analyze,
)


@pytest.mark.parametrize("raw,expected", [
    ("Oikos Triple Zero Vanilla", "oikos triple zero vanilla"),
    ("a banana", "a banana"),            # normalize doesn't strip articles
    ("Chicken Breast 6oz", "chicken breast"),  # strips quantity
    ("  Built  Bar  ", "built bar"),
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("name", [
    "protein bar", "a protein bar", "the protein bar", "shake", "protein shake",
    "smoothie", "some smoothie", "a bowl", "snack", "trail mix", "energy drink",
    "milkshake", "cappuccino", "burrito", "taco", "pizza", "burger", "ramen",
    "oatmeal", "toast", "bagel", "cookies", "a cocktail", "beer", "leftovers",
])
def test_generic_names_flagged(name):
    assert is_generic_food_name(name) is True, name


@pytest.mark.parametrize("name", [
    "banana", "a banana", "chicken breast", "2 eggs", "built bar",
    "oikos shake", "barebells caramel", "rxbar chocolate", "quest bar",
    "dark chocolate", "chocolate banana", "grilled chicken", "white rice",
    "almond milk", "greek yogurt", "peanut butter", "chicken burrito",
    "beef taco", "margherita pizza", "starbucks latte", "apple", "salmon",
    "the usual shake", "my usual bar",
])
def test_specific_names_not_flagged(name):
    assert is_generic_food_name(name) is False, name


def test_score_match():
    assert score_match("banana", "banana, raw") == "exact"
    assert score_match("chicken breast", "chicken, breast, grilled") in ("likely", "exact")
    assert score_match("banana", "battery acid") == "estimated"


@pytest.mark.parametrize("value,current,expected", [
    # exact tier names pass through
    ("quick", "moderate", "quick"),
    ("moderate", "quick", "moderate"),
    ("strict", "moderate", "strict"),
    # UI synonyms for the default
    ("balanced", "strict", "moderate"),
    ("default", "quick", "moderate"),
    # relative steps from current tier
    ("less", "moderate", "quick"),
    ("more", "moderate", "strict"),
    ("less", "strict", "moderate"),
    ("more", "quick", "moderate"),
    # relative never overshoots the ladder ends
    ("less", "quick", "quick"),
    ("more", "strict", "strict"),
    # natural-language synonyms
    ("careful", "moderate", "strict"),
    ("just log it", "strict", "moderate"),  # unrecognized → safe default
    ("", "strict", "moderate"),
    (None, "quick", "moderate"),
])
def test_normalize_food_logging_mode(value, current, expected):
    assert normalize_food_logging_mode(value, current) == expected


# ── micronutrient capture ────────────────────────────────────────────────────

def test_analyze_scales_micros_to_portion():
    """USDA per-100g micros are scaled to the logged portion and returned on
    .micros (→ micronutrients_json). 200 kcal against a 100-kcal/100g basis is a
    2× portion, so every micro doubles."""
    cand = {
        "fdc_id": "X", "_match": "likely",
        "per100g": {
            "calories": 100, "protein": 5, "carbs": 10, "fat": 3,
            "fiber": 2, "sugar": 1, "sodium": 50,
            "calcium": 120, "iron": 2.0, "potassium": 300, "magnesium": 40,
            "vitamin_c": 9, "vitamin_d": 1.5, "vitamin_b12": 0.8, "saturated_fat": 1.2,
        },
    }
    a = analyze("test food", "1 cup", 200, 10, 20, 6, usda_candidate=cand)
    assert a.micros["calcium"] == 240.0       # 120 × 2
    assert a.micros["iron"] == 4.0            # 2.0 × 2
    assert a.micros["potassium"] == 600.0
    assert a.micros["vitamin_b12"] == 1.6
    # macros stay in their own columns, not duplicated into micros
    assert "calories" not in a.micros and "protein" not in a.micros


def test_analyze_no_micros_without_enrichment():
    """LLM-only estimate (no USDA/web/memory match) → empty micros, so the
    handler writes micronutrients_json=NULL rather than '{}'."""
    a = analyze("mystery dish", "1 plate", 500, 20, 50, 25)
    assert a.micros == {}


# Chicken breast per-100g (USDA-ish): 165 kcal, 31g protein, 0 carbs, 3.6g fat.
_CHICKEN = {
    "fdc_id": "C", "_match": "exact",
    "per100g": {"calories": 165, "protein": 31, "carbs": 0, "fat": 3.6,
                "fiber": 0, "sugar": 0, "sodium": 74, "potassium": 256},
}


def test_mass_stated_match_computes_calories_forward():
    """Mass-stated quantity + trustworthy density → calories come from
    grams × density (ground truth), NOT the LLM's undercounted estimate.
    200g chicken = 330 kcal even though the model guessed a low 270."""
    a = analyze("chicken breast", "200g", 270, 50, 0, 6, usda_candidate=_CHICKEN)
    assert a.calories == 330          # 165 × 2, not the LLM's 270
    assert a.protein == 62.0          # 31 × 2 — scales with the real portion
    assert a.fat == 7.2               # 3.6 × 2
    assert a.micros["potassium"] == 512.0
    assert a.source == "usda" and a.confidence == "exact"


def test_mass_stated_ounces_forward():
    """Ounces are ground truth too — 6 oz ≈ 170g → 165×1.7≈281 kcal."""
    a = analyze("chicken breast", "6 oz", 220, 40, 0, 5, usda_candidate=_CHICKEN)
    assert a.calories == round(165 * 170.1 / 100)   # ≈ 281, from grams not the LLM's 220


def test_non_mass_quantity_falls_back_to_estimate():
    """A count/cup/vague amount has no reliable grams → keep trusting the LLM's
    calories (back grams out of them), unchanged from before."""
    a = analyze("chicken breast", "1 breast", 270, 50, 0, 6, usda_candidate=_CHICKEN)
    assert a.calories == 270          # LLM estimate honored — no ground-truth grams


def test_volume_ml_is_not_treated_as_ground_truth():
    """ml is volume, not mass — density-assumption, so it must NOT trigger the
    forward path (falls back to the LLM's calories)."""
    a = analyze("olive oil", "15 ml", 120, 0, 0, 14, usda_candidate={
        "fdc_id": "O", "_match": "likely",
        "per100g": {"calories": 884, "protein": 0, "carbs": 0, "fat": 100}})
    assert a.calories == 120          # not 884 × 0.15


def test_pure_estimate_unaffected_by_forward_path():
    """No match at all → the LLM's numbers stand, even for a mass-stated amount
    (nothing to compute from). Accurate foods stay put; no overcorrection."""
    a = analyze("grandma's stew", "300g", 420, 25, 30, 20)
    assert a.calories == 420
    assert a.source == "estimate"


def test_disagreement_demotion_keeps_model_read_on_lean_usda_mismatch():
    """Danny 2026-07-23: "chicken shawarma" 4 oz — model read 220 cal, the USDA
    text-match was plain lean chicken (122 cal/100g) and the mass path wrote 138.
    Two independent reads disagreeing >30% downward = LOW confidence: keep the
    model's numbers, demote to source="estimate" so the web lane fires."""
    from core.food_intelligence import analyze
    lean = {"fdc_id": 1, "_match": "exact",
            "per100g": {"calories": 122, "protein": 17.4, "carbs": 2, "fat": 2.7}}
    r = analyze("Chicken shawarma", "4 oz", 220, 28, 2, 11, usda_candidate=lean)
    assert r.calories == 220, f"model read must survive; got {r.calories}"
    assert r.source == "estimate" and r.confidence == "estimated"
    # Upward correction is untouched: a lean model read on plain chicken still
    # gets the USDA forward-compute (the ~19% undercount fix).
    r2 = analyze("Chicken breast", "4 oz", 110, 20, 0, 2, usda_candidate=lean)
    assert r2.calories == round(122 * 1.1339)  # 4 oz = 113.39g forward-computed
    assert r2.source == "usda"
