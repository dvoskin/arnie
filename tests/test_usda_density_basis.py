"""A drink is a liquid, and a USDA row is per 100 grams.

Those two sentences were in disagreement, and the disagreement was invisible
because each half was written down in a different place:

  • `api/usda.py` returned nutrients under a key called `per100g` and said
    nothing about what they described. `candidates.usda_candidates` then wrote
    `basis=Per100g()` as a CONSTANT — this module answering a question about a
    record it had never seen.
  • the gold set answered the same question differently, declaring
    `basis="per_100ml"` on thirteen USDA rows. No live code path can produce
    that basis for USDA, so those cases exercised arithmetic production never
    ran.

The mislabel had a price on the one case where it was checked against a number:
`olive-oil-tbsp` expected 128-134 calories for a tablespoon, which is what you
get by reading an 884 cal/100 g row as per 100 ml. USDA's own portion table
(13.5 g/tbsp) and the bottle both say ~120.

And it was LOAD-BEARING. Declaring the source per-100ml is what let a drink
scale at all, because `VOLUME_DENSITY_G_PER_ML` had no drinks in it — it is
keyed by `portions.food_category`, an ontology built to say what a cup of a DRY
food weighs. So on the live path:

    "240ml of milk"      → source seated, calories NULL
    "240ml of orange juice" → source seated, calories NULL
    "240ml of oat milk"  → 41 calories, because `food_category("oat milk")` is
                           `oats` and that row is 0.38 g/ml — the packing
                           density of loose rolled oats in a measuring cup

Covered here:
  • drinks resolve to a drink's density, not a dry solid's
  • the density table's solids are untouched (oatmeal is still 0.38)
  • the live USDA path prices a glass of milk, juice and oat milk
  • a tablespoon of olive oil agrees with USDA's own portion table
  • an ml-stated serving panel is no longer discarded
  • every basis the gold set declares is one a live adapter can produce
"""
import pytest

from skills.nutrition.normalize import (BEVERAGE_DENSITY_G_PER_ML,
                                        VOLUME_DENSITY_G_PER_ML,
                                        beverage_density, normalize_quantity,
                                        volume_to_grams)


# ── a drink gets a drink's density ───────────────────────────────────────────

@pytest.mark.parametrize("drink,expected", [
    ("milk", "milk"), ("2% milk", "milk"), ("whole milk", "whole milk"),
    ("oat milk", "oat milk"), ("almond milk", "almond milk"),
    ("orange juice", "orange juice"), ("fruit smoothie", "smoothie"),
    ("chicken broth", "broth"), ("beef stock", "stock"),
    ("iced coffee", "coffee"), ("green tea", "tea"), ("beer", "beer"),
])
def test_a_drink_resolves_to_a_drink(drink, expected):
    matched = beverage_density(drink)
    assert matched is not None, f"{drink!r} has no density"
    assert matched[1] == expected


def test_oat_milk_is_not_oats():
    """The specific failure. `food_category("oat milk")` is `oats`, whose
    density is the packing density of the dry flake — so a glass of oat milk
    weighed 91 g and logged at 41 calories against a true ~110."""
    from skills.nutrition.portions import food_category

    assert food_category("oat milk") == "oats"        # unchanged, and correct
    grams, density, matched = volume_to_grams(240, "oat milk")
    assert matched == "oat milk" and density == 1.03
    assert 240 <= grams <= 255, f"240 ml of oat milk weighed {grams} g"


def test_the_dry_solids_keep_their_own_density():
    """The other half: a beverage table that swallowed the solids would be the
    same bug pointing the other way. Oatmeal is still a dry flake."""
    for solid, category in (("oatmeal", "oats"), ("rolled oats", "oats"),
                            ("white rice", "rice"), ("olive oil", "oil")):
        grams, density, matched = volume_to_grams(240, solid)
        assert matched == category, f"{solid!r} matched {matched!r}"
        assert density == VOLUME_DENSITY_G_PER_ML[category]


def test_a_food_with_no_density_still_has_none():
    """The table's founding rule survives: absent means absent, and the volume
    stays a volume rather than being papered over with water."""
    assert volume_to_grams(240, "cheese") is None
    assert volume_to_grams(240, "chicken breast") is None


def test_every_beverage_density_is_physically_plausible():
    """Drinks are mostly water. Sugar and fat move them a little; nothing here
    is a syrup or a powder, so nothing may sit far from 1.0."""
    for drink, density in BEVERAGE_DENSITY_G_PER_ML.items():
        assert 0.9 <= density <= 1.15, f"{drink}: {density} g/ml"


# ── the live path, end to end ────────────────────────────────────────────────

def _resolve(food, quantity, description, **per100):
    """One USDA row in the exact shape `api.usda.search_food` returns, through
    the real adapter and the real resolver."""
    from skills.nutrition.candidates import usda_candidates
    from skills.nutrition.models import FoodResolutionRequest
    from skills.nutrition.resolver import resolve
    from api.usda import USDA_BASIS

    rows = [{"fdc_id": 1, "description": description, "per100g": per100,
             "data_type": "SR Legacy", "basis": USDA_BASIS, "brand": "",
             "serving_text": "", "serving_mass_g": None, "serving_ml": None}]
    return resolve(FoodResolutionRequest(food_name=food,
                                         raw_quantity=quantity),
                   usda_candidates(rows))


@pytest.mark.parametrize("food,quantity,description,per100,lo,hi", [
    # USDA's own portion for 2% milk is 1 cup / 244 g / 122 cal.
    ("milk", "240ml", "Milk, 2%", {"calories": 50, "protein": 3.4}, 120, 128),
    # Raw orange juice, 1 cup / 248 g / 112 cal.
    ("orange juice", "240ml", "Orange juice, raw",
     {"calories": 45, "protein": 0.7}, 108, 118),
    # The one that returned 41.
    ("oat milk", "240ml", "Oat milk, unsweetened",
     {"calories": 45, "protein": 1}, 105, 118),
])
def test_a_drink_in_ml_gets_calories(food, quantity, description, per100,
                                     lo, hi):
    """Before this, the first two resolved with USDA seated and `calories`
    None — a glass of milk logged as a glass of nothing — and the third
    resolved at a third of the truth."""
    out = _resolve(food, quantity, description, **per100)
    assert out.source == "usda", f"{food} resolved as {out.source}"
    calories = out.nutrients.amount("calories")
    assert calories is not None, f"{food} resolved with no calories at all"
    assert lo <= calories <= hi, f"{food} {quantity} → {calories} cal"


def test_a_tablespoon_of_olive_oil_agrees_with_usdas_own_portion():
    """884 cal/100 g × 13.5 g/tbsp is 119. The gold set expected 128-134 until
    2026-07-27, which is that row read as per 100 ml."""
    out = _resolve("olive oil", "1 tbsp", "Oil, olive", calories=884, fat=100)
    assert 118 <= out.nutrients.amount("calories") <= 122


def test_the_density_is_disclosed_as_an_assumption():
    """A density is a decision made on the user's behalf. It arrives as one."""
    quantity = normalize_quantity("240ml", "oat milk")
    assert any("density" in a and "1.03" in a for a in quantity.assumptions), (
        f"density not disclosed: {quantity.assumptions}")


# ── the serving panel's ml is no longer thrown away ──────────────────────────

def test_an_ml_serving_panel_survives_the_adapter():
    """`api.usda._search` kept `servingSize` only when the unit was grams and
    dropped it otherwise, though `PerServing` has carried a `serving_ml` the
    whole time and `scaling._factor` already divides ml by it."""
    from skills.nutrition.candidates import usda_candidates

    rows = [{"fdc_id": 7, "description": "Almond milk", "brand": "Some Brand",
             "per100g": {"calories": 17, "protein": 0.6},
             "basis": "per_100g", "serving_text": "1 cup",
             "serving_mass_g": None, "serving_ml": 240.0}]
    candidate = usda_candidates(rows)[0]
    assert candidate.serving_ml == 240.0
    assert candidate.serving_mass_g is None


# ── the guard: the gold set may not declare a basis nothing can produce ──────

#: Sources whose gold cases still declare a basis their live adapter cannot
#: emit. `off` is the remaining one, and it is a REAL gap of the same shape:
#: Open Food Facts stores a liquid's nutriments under the same `*_100g` keys it
#: uses for solids, `skills/nutrition/off.py` passes them through as per-100g,
#: and `candidates.off_candidate` hardcodes `Per100g()` — while the gold set
#: declares `per_100ml` for every branded drink in it, correctly, because a
#: Fairlife bottle's label IS per serving of a volume.
#:
#: Deciding when an OFF row is per-100ml needs OFF's own serving/quantity
#: fields and is its own change. Naming it here is the point: the exemption is
#: visible, and a NEW unreachable basis fails this test the day it is added.
_KNOWN_UNREACHABLE = {"off"}


def _bases_the_adapters_can_produce():
    """Every `basis` string the live candidate adapters actually emit, by
    source. Built by CALLING them, so it cannot drift from what they do."""
    from skills.nutrition.candidates import usda_candidates
    from api.usda import USDA_BASIS

    row = {"fdc_id": 1, "description": "x", "per100g": {"calories": 100},
           "basis": USDA_BASIS, "serving_text": "", "serving_mass_g": None,
           "serving_ml": None}
    return {"usda": {c.basis.basis for c in usda_candidates([row])}}


def test_no_gold_case_declares_a_basis_its_source_cannot_produce():
    """The seam this whole change closed. A gold case that names a basis no
    adapter emits is not testing the system — it is testing a system, and the
    two had diverged by 10% on a tablespoon of olive oil."""
    from tests.gold.nutrition_cases import ALL_CASES

    producible = _bases_the_adapters_can_produce()
    offenders = []
    for case in ALL_CASES:
        for spec in case["candidates"]:
            source, basis = spec["source"], spec.get("basis", "per_100g")
            if source in _KNOWN_UNREACHABLE or source not in producible:
                continue
            if basis not in producible[source]:
                offenders.append((case["id"], source, basis))
    assert not offenders, (
        "gold cases declare a basis their source cannot produce: "
        f"{offenders}")


def test_usda_declares_its_basis_in_exactly_one_place():
    """The constant the adapters read. If a future change makes USDA's basis
    per-record, this is the name that has to become a function — not a literal
    rewritten in `candidates.py` where the record is not in scope."""
    from api.usda import USDA_BASIS

    assert USDA_BASIS == "per_100g"
