"""Validation before commit (review 2026-07-25, work order step 8).

Every incident this system has had shares a shape: a candidate that was
plausible on the axis anyone checked, and wrong on an axis nobody did. A USDA
cousin with the right name and the wrong preparation. A seasoning matched to a
sauce, carrying 20,378 mg of sodium per 100 g. A per-package panel read as
per-serving.

So validation is layered and each layer answers one question:

  identity      is this the same FOOD?
  energy        do the macros add up to the calories?
  serving       is the basis coherent and the portion possible?
  bounds        is any single nutrient outside what this category can be?
  agreement     do two high-confidence sources disagree materially?

A validator returns a verdict, never a mutation. Downgrade, reject and ask are
policy decisions made by the resolver with the mode in hand — the validators
only establish the facts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from skills.nutrition.models import (ATWATER, MACRO_FIELDS,
                                     NormalizedQuantity, NutrientProfile)
from skills.nutrition.provenance import MatchGrade

logger = logging.getLogger(__name__)

REJECT = "reject"
DOWNGRADE = "downgrade"
PASS = "pass"


@dataclass(frozen=True)
class Verdict:
    outcome: str                 # pass | downgrade | reject
    reason: str = ""
    detail: str = ""
    field: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == PASS


PASSED = Verdict(PASS)


# ── identity ──────────────────────────────────────────────────────────────────
#: Preparations that change the number materially. A candidate carrying one of
#: these when the request carries a different one is a different food, however
#: well the names overlap.
_PREPARATIONS = ("raw", "cooked", "roasted", "grilled", "fried", "baked",
                 "boiled", "steamed", "dried", "dehydrated", "canned",
                 "frozen", "powdered", "concentrate", "syrup")

#: Forms whose per-100g numbers are wildly unlike the food people mean. A
#: "garlic powder" match for "garlic" is the sodium-bomb failure class.
_CONCENTRATED_FORMS = ("powder", "powdered", "concentrate", "extract",
                       "seasoning", "bouillon", "dried", "dehydrated",
                       "granules", "paste")


def _tokens(text: str) -> set:
    """Word set for overlap checks, crudely singularized.

    Without this, "onion" and "Onions, raw" share no tokens and the correct
    candidate is rejected as unrelated — a plural is not a different food.
    Deliberately crude: over-stemming risks a false MATCH, so only a trailing
    's' comes off, and only from words long enough for it to be a plural.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    return {w[:-1] if (len(w) > 3 and w.endswith("s") and not w.endswith("ss"))
            else w for w in words}


def validate_identity(requested: str, candidate_name: str,
                      requested_brand: Optional[str] = None,
                      candidate_brand: Optional[str] = None,
                      requested_variant: Optional[str] = None,
                      candidate_variant: Optional[str] = None) -> Verdict:
    """Same food, or a cousin wearing its name?"""
    if requested_brand and candidate_brand:
        if _tokens(requested_brand).isdisjoint(_tokens(candidate_brand)):
            return Verdict(REJECT, "brand_conflict",
                           f"{requested_brand!r} vs {candidate_brand!r}")
    if requested_variant and candidate_variant:
        if _tokens(requested_variant).isdisjoint(_tokens(candidate_variant)):
            return Verdict(REJECT, "variant_conflict",
                           f"{requested_variant!r} vs {candidate_variant!r}")

    req, cand = (requested or "").lower(), (candidate_name or "").lower()

    # A concentrated form the user did not ask for is the single most
    # dangerous mismatch: the identity looks right and the numbers are 20×.
    # Gated on the REQUEST naming no concentrate at all — someone asking for
    # garlic powder is already asking for a concentrate, and "powder" vs
    # "dried" is a wording difference, not a category error.
    if not any(f in req for f in _CONCENTRATED_FORMS):
        for form in _CONCENTRATED_FORMS:
            if form in cand:
                return Verdict(REJECT, "concentrated_form",
                               f"candidate is a {form}, request is not")

    req_prep = {p for p in _PREPARATIONS if re.search(rf"\b{p}\b", req)}
    cand_prep = {p for p in _PREPARATIONS if re.search(rf"\b{p}\b", cand)}
    if req_prep and cand_prep and req_prep.isdisjoint(cand_prep):
        return Verdict(DOWNGRADE, "preparation_mismatch",
                       f"{sorted(req_prep)} vs {sorted(cand_prep)}")

    if _tokens(req) and _tokens(cand) and _tokens(req).isdisjoint(_tokens(cand)):
        return Verdict(REJECT, "no_shared_terms", f"{requested!r} vs {candidate_name!r}")

    # A NAMED PRODUCT with extra qualifying words is a different SKU.
    #
    # "Peanut M&Ms" and "Peanut Butter M&Ms" share enough tokens to pass, and
    # the second was being accepted as an EXACT match for the first — a
    # near-neighbour failure with a brand name on it, and a 40-calorie-per-27g
    # difference between two products sitting next to each other on a shelf.
    #
    # Branded only. A generic request legitimately matches a fuller database
    # name — "chicken breast" against "Chicken breast, roasted, skinless" is
    # the database being more specific, not a different food — so applying this
    # to generics would reject the ordinary case.
    if requested_brand:
        extra = {t for t in _tokens(cand) - _tokens(req) - _tokens(requested_brand)
                 if len(t) >= 3 and t not in _NEUTRAL_QUALIFIERS}
        if extra:
            return Verdict(DOWNGRADE, "extra_product_qualifier",
                           f"candidate adds {sorted(extra)}")
    return PASSED


#: Words that make a product name longer without making it a different product.
#: Packaging, format and marketing words — as opposed to "butter" in "Peanut
#: Butter M&Ms", which names a different sweet entirely.
_NEUTRAL_QUALIFIERS = frozenset({
    "the", "and", "with", "original", "classic", "regular", "standard",
    "pack", "packet", "bag", "box", "single", "serve", "size", "sized",
    "count", "piece", "pieces", "bar", "bars", "share", "sharing", "share",
    "new", "improved", "brand", "inc", "ltd", "co", "company", "usa",
})


# ── energy consistency ────────────────────────────────────────────────────────
#: Fibre, sugar alcohols, alcohol itself and label rounding all move this, so
#: the tolerance is generous. It is a nonsense detector, not an audit.
ENERGY_TOLERANCE = 0.30
ENERGY_HARD_TOLERANCE = 0.60


def validate_energy(profile: NutrientProfile) -> Verdict:
    """Do protein×4 + carbs×4 + fat×9 land near the stated calories?

    Skipped entirely when any macro is UNKNOWN — computing the sum with
    unknowns treated as zero would flag every partially-known profile, which
    teaches everyone to ignore the check.
    """
    cal = profile.amount("calories")
    if cal is None or cal <= 0:
        return PASSED
    parts = {k: profile.amount(k) for k in ATWATER}
    if any(v is None for v in parts.values()):
        return PASSED
    implied = sum(parts[k] * ATWATER[k] for k in ATWATER)
    if implied <= 0:
        return PASSED
    drift = abs(implied - cal) / cal
    if drift > ENERGY_HARD_TOLERANCE:
        return Verdict(REJECT, "energy_mismatch",
                       f"macros imply {implied:.0f} kcal, stated {cal:.0f}")
    if drift > ENERGY_TOLERANCE:
        return Verdict(DOWNGRADE, "energy_drift",
                       f"macros imply {implied:.0f} kcal, stated {cal:.0f}")
    return PASSED


# ── serving basis ─────────────────────────────────────────────────────────────
#: A single serving outside this range is almost always a package total or a
#: per-100g figure mislabelled.
MIN_SERVING_G = 1.0
MAX_SERVING_G = 1500.0


def validate_serving(serving_mass_g: Optional[float],
                     servings_per_package: Optional[float] = None,
                     quantity: Optional[NormalizedQuantity] = None) -> Verdict:
    if serving_mass_g is not None:
        if serving_mass_g <= 0:
            return Verdict(REJECT, "impossible_serving",
                           f"serving mass {serving_mass_g}")
        if serving_mass_g < MIN_SERVING_G or serving_mass_g > MAX_SERVING_G:
            return Verdict(REJECT, "implausible_serving",
                           f"serving mass {serving_mass_g} g")
    if servings_per_package is not None and servings_per_package <= 0:
        return Verdict(REJECT, "impossible_package",
                       f"{servings_per_package} servings per package")
    if quantity is not None and quantity.grams is not None:
        if quantity.grams <= 0:
            return Verdict(REJECT, "impossible_portion", f"{quantity.grams} g")
        if quantity.grams > 5000:
            return Verdict(DOWNGRADE, "implausible_portion",
                           f"{quantity.grams} g in one entry")
    return PASSED


# ── nutrient bounds ───────────────────────────────────────────────────────────
#: Per-100g ceilings by category. Deliberately loose — these catch the absurd
#: (20,378 mg of sodium), not the merely salty.
_BOUNDS_PER_100G = {
    "default": {"calories": (0, 900), "protein": (0, 92), "carbs": (0, 100),
                "fat": (0, 100), "fiber": (0, 80), "sugar": (0, 100),
                "sodium": (0, 8000), "saturated_fat": (0, 100),
                "cholesterol": (0, 3100), "potassium": (0, 5000)},
    "condiment": {"sodium": (0, 30000), "sugar": (0, 100)},
    "beverage": {"calories": (0, 450), "protein": (0, 30), "sodium": (0, 2000)},
}

_CONDIMENT_HINTS = ("sauce", "seasoning", "spice", "salt", "soy sauce",
                    "dressing", "bouillon", "stock", "extract", "vinegar")
_BEVERAGE_HINTS = ("juice", "soda", "coffee", "tea", "milk", "water",
                   "smoothie", "shake", "beer", "wine")


def category_for(food_name: str) -> str:
    n = (food_name or "").lower()
    if any(h in n for h in _CONDIMENT_HINTS):
        return "condiment"
    if any(h in n for h in _BEVERAGE_HINTS):
        return "beverage"
    return "default"


def validate_bounds(profile: NutrientProfile, food_name: str = "",
                    basis: str = "per_100g") -> tuple:
    """Per-nutrient sanity. Returns (verdict, offending_fields).

    Only meaningful on a per-100g basis — a portion legitimately carries any
    amount if it is large enough — so anything else passes untouched rather
    than being checked against the wrong yardstick.
    """
    if basis != "per_100g":
        return PASSED, ()
    limits = dict(_BOUNDS_PER_100G["default"])
    limits.update(_BOUNDS_PER_100G.get(category_for(food_name), {}))
    bad = []
    for name, (lo, hi) in limits.items():
        v = profile.amount(name)
        if v is None:
            continue                       # unknown is not out of bounds
        if v < lo or v > hi:
            bad.append(name)
    if not bad:
        return PASSED, ()
    # An impossible MACRO condemns the whole candidate. Macros are what the
    # food nutritionally is: 95 g of protein per 100 g does not describe a
    # chicken breast with one bad field, it describes the wrong record. A wild
    # MICRO condemns only that field — dropping good macros over one bad
    # sodium throws away a correct answer.
    macro_violations = [f for f in bad if f in MACRO_FIELDS]
    if macro_violations:
        return (Verdict(REJECT, "bounds_violation", ",".join(bad)),
                tuple(bad))
    return Verdict(DOWNGRADE, "micro_out_of_bounds", ",".join(bad)), tuple(bad)


def strip_out_of_bounds(profile: NutrientProfile, fields) -> NutrientProfile:
    """Drop impossible fields back to UNKNOWN. Not to zero — we learned the
    value was wrong, not that the product contains none."""
    if not fields:
        return profile
    return profile.with_values(**{f: None for f in fields})


# ── cross-source agreement ────────────────────────────────────────────────────
#: What counts as a material disagreement. Below this, picking either is fine
#: and asking would be friction for nothing.
MATERIAL_CALORIE_DELTA = 0.20
MATERIAL_CALORIE_FLOOR = 40.0

#: An absolute gap this large is material regardless of how small it is
#: relatively (PR #31 calibration).
#:
#: The relative test alone silently pre-empted the ask ladder. Two granolas 65
#: calories apart on a 70 g serving are a 19% gap, so `sources_disagree`
#: reported agreement and no ambiguity was ever created — which meant strict
#: mode's 60-calorie threshold could not fire on a 65-calorie disagreement,
#: because there was nothing to fire on. Two gates in two modules, each
#: reasonable alone, and the looser-looking one winning.
#:
#: This module's job is to REPORT a disagreement; deciding whether it is worth
#: interrupting for belongs to the mode ladder. So the bar here is the tightest
#: threshold any mode uses — anything the strictest mode could act on gets
#: reported, and the ladder does the rest.
#:
#: Kept as a literal rather than imported from resolver.ASK_SPANS to avoid a
#: cycle; `test_food_calibration` fails if the two drift apart.
MATERIAL_CALORIE_ABSOLUTE = 60.0

#: The same test for protein, because a calorie-only test cannot see the
#: disagreement people actually care about here (PR #31 calibration).
#:
#: Whey isolate and a whey blend differ by 20 g of protein per 100 g and agree
#: on calories to within a rounding error. Under a calorie-only gate that is not
#: a disagreement at all — `sources_disagree` returned None, no ambiguity was
#: recorded, and no mode asked. For the users who log protein powder, the
#: protein number IS the reason they bought it.
#:
#: 6 g is roughly a large egg; below that the choice is genuinely free. 25% is
#: looser than the calorie delta on purpose: protein values are smaller, so the
#: same relative gap is a smaller absolute one.
MATERIAL_PROTEIN_DELTA = 0.25
MATERIAL_PROTEIN_FLOOR = 6.0


def sources_disagree(a: NutrientProfile, b: NutrientProfile) -> Optional[dict]:
    """The gap between two candidates, when it is big enough to matter.

    Material on EITHER calories or protein. The calorie-only version could not
    see a whey isolate against a whey blend — 20 g of protein apart, identical
    calories — and returned None, so no ambiguity existed and no mode asked.
    A macro tracker's most-watched number was the one the materiality test
    could not read.

    None when both agree closely enough that the choice is free.
    """
    ca, cb = a.amount("calories"), b.amount("calories")
    pa, pb = a.amount("protein"), b.amount("protein")

    calorie_span = (abs(ca - cb) if ca is not None and cb is not None
                    else None)
    protein_span = (abs(pa - pb) if pa is not None and pb is not None
                    else None)

    calories_differ = (
        calorie_span is not None
        and calorie_span >= MATERIAL_CALORIE_FLOOR
        and (calorie_span / max(ca, cb, 1.0) >= MATERIAL_CALORIE_DELTA
             or calorie_span >= MATERIAL_CALORIE_ABSOLUTE))
    protein_differs = (
        protein_span is not None
        and protein_span >= MATERIAL_PROTEIN_FLOOR
        and protein_span / max(pa, pb, 1.0) >= MATERIAL_PROTEIN_DELTA)

    if not (calories_differ or protein_differs):
        return None
    if ca is None or cb is None:
        # A protein-only disagreement between candidates that do not both
        # report calories. Real, and reportable — the options are the protein
        # values, since those are what differ.
        return {"calorie_span": 0.0, "protein_span": round(protein_span, 1),
                "options": (round(pa, 1), round(pb, 1)),
                "driver": "protein"}
    return {"calorie_span": round(calorie_span, 1),
            "protein_span": (round(protein_span, 1)
                             if protein_span is not None else 0.0),
            "options": (round(ca, 1), round(cb, 1)),
            "driver": ("calories" if calories_differ else "protein")}
