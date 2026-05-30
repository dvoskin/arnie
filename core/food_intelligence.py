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


def normalize_name(name: str) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"\b(\d+\s*(g|oz|cups?|tbsp|tsp|ml|servings?|slices?|pieces?))\b", "", n)
    n = re.sub(r"[^a-z0-9 ]", "", n).strip()
    return re.sub(r"\s+", " ", n)


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
