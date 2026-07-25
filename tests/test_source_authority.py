"""Source authority per food class, and provenance that tells the truth (§4–§8).

Pinned against a shipped meal. The user logged a Thomas' everything bagel thin
with Philadelphia scallion cream cheese, smoked salmon, tomato and onion, half a
Starbucks turkey bacon sandwich and a few fries. Arnie logged 560 calories; the
published labels put it at 420. Two items account for 105 of the 140-calorie
overcount:

    Philadelphia scallion cream cheese   100  vs   60   (Philadelphia's label)
    Starbucks turkey bacon sandwich ½    180  vs  115   (Starbucks' published)

Both are named products with a published label that was never consulted, because
selection was a fixed ladder — memory, then USDA, then OFF, then web — for every
food. The bagel and the salmon, which needed no branded lookup, were both right.
"""
import pytest

from skills.nutrition.authority import (BRANDED_RUNGS, FALLBACK_RUNGS,
                                        FoodClass, LADDERS, classify,
                                        display_detail, needs_branded_lookup,
                                        provenance_for, select)


# ── §4: the ladder depends on what the food IS ────────────────────────────────
@pytest.mark.parametrize("name,kwargs,expected", [
    ("Philadelphia scallion cream cheese", {"brand": "Philadelphia"},
     FoodClass.MANUFACTURED),
    ("Thomas' Everything Bagel Thin", {}, FoodClass.MANUFACTURED),
    ("Reese's Pieces", {}, FoodClass.MANUFACTURED),
    ("Starbucks turkey bacon sandwich", {}, FoodClass.RESTAURANT),
    ("turkey bacon sandwich", {"restaurant": "Starbucks"}, FoodClass.RESTAURANT),
    ("smoked salmon", {}, FoodClass.GENERIC),
    ("fries", {}, FoodClass.GENERIC),
])
def test_food_class_decides_the_ladder(name, kwargs, expected):
    assert classify(name, **kwargs) is expected


def test_a_menu_item_does_not_go_down_the_manufactured_ladder():
    """A branded FOOD database does not carry a chain's menu, so a menu item
    sent down the manufactured ladder lands on the generic fallback — which is
    how half a Starbucks sandwich shipped at 180 against a published 115."""
    assert classify("Starbucks turkey bacon sandwich") is FoodClass.RESTAURANT
    rungs = LADDERS[FoodClass.RESTAURANT]
    assert "restaurant_page" in rungs
    assert "usda_generic" not in rungs


def test_the_brand_the_interpreter_supplied_is_decisive():
    """`names_a_product` reads caps, possessives and marks — it catches
    "Thomas'" and misses "Philadelphia". A heuristic miss must not be able to
    demote a product the interpreter already named."""
    assert classify("Philadelphia scallion cream cheese") is FoodClass.GENERIC
    assert classify("Philadelphia scallion cream cheese",
                    brand="Philadelphia") is FoodClass.MANUFACTURED


# ── §8: selection is by ladder, not by a fixed source order ───────────────────
def test_a_manufacturer_label_outranks_usda_for_a_named_product():
    rung, _ = select({"usda_generic": {"cal": 100}, "manufacturer": {"cal": 60}},
                     FoodClass.MANUFACTURED)
    assert rung == "manufacturer"


def test_usda_wins_for_a_generic_whole_food():
    rung, _ = select({"usda_exact": {"cal": 70}, "estimate": {"cal": 90}},
                     FoodClass.GENERIC)
    assert rung == "usda_exact"


def test_a_user_correction_outranks_every_database():
    """Above every database on all three ladders. On the manufactured ladder a
    barcode and a user-entered label sit above it — that is the directive's own
    ordering, since both are the label in the user's hand rather than a memory
    of one."""
    for food_class in (FoodClass.MANUFACTURED, FoodClass.GENERIC,
                       FoodClass.RESTAURANT):
        rung, _ = select({"user_correction": {"c": 1}, "manufacturer": {"c": 2},
                          "usda_exact": {"c": 3}, "restaurant_page": {"c": 4}},
                         food_class)
        assert rung == "user_correction", food_class


def test_a_present_but_empty_candidate_still_occupies_its_rung():
    """Presence, not truthiness. Testing truthiness silently skipped a rung
    that was there — the same class of bug as the fixed ladder."""
    rung, _ = select({"manufacturer": {}, "usda_generic": {"cal": 100}},
                     FoodClass.MANUFACTURED)
    assert rung == "manufacturer"


def test_selection_reports_the_rung_it_used():
    """The cache records this rung, so a written row can never claim an
    authority the selection did not actually use."""
    rung, candidate = select({"usda_generic": {"id": "u"}},
                             FoodClass.MANUFACTURED)
    assert (rung, candidate["id"]) == ("usda_generic", "u")


def test_an_empty_candidate_set_selects_nothing():
    assert select({}, FoodClass.GENERIC) == ("", None)


# ── §5: strict may not let a generic stand in for a named product ─────────────
@pytest.mark.parametrize("food_class,rung", [
    (FoodClass.MANUFACTURED, "usda_generic"),
    (FoodClass.MANUFACTURED, "estimate"),
    (FoodClass.MANUFACTURED, ""),
    (FoodClass.RESTAURANT, "component_estimate"),
])
def test_strict_re_attempts_branded_when_only_a_fallback_is_held(food_class, rung):
    assert needs_branded_lookup(food_class, rung, strict=True) is True


@pytest.mark.parametrize("rung", sorted(BRANDED_RUNGS))
def test_a_real_branded_answer_needs_no_further_lookup(rung):
    assert needs_branded_lookup(FoodClass.MANUFACTURED, rung,
                                strict=True) is False


def test_a_generic_food_never_triggers_a_branded_lookup():
    """There is no label to go and find for smoked salmon."""
    assert needs_branded_lookup(FoodClass.GENERIC, "usda_exact") is False
    assert needs_branded_lookup(FoodClass.GENERIC, "estimate",
                                strict=True) is False


# ── §7: attribution names who determined the DISPLAYED numbers ────────────────
def test_usda_attribution_requires_usda_to_have_determined_the_macros():
    honest = provenance_for(rung="usda_exact", food_class=FoodClass.GENERIC)
    assert display_detail(honest) == "From the USDA database"


def test_micronutrient_help_is_not_a_macro_attribution():
    """The model's calories were kept and USDA supplied only sodium. Saying
    "From the USDA database" attributes numbers USDA never produced."""
    supplemented = provenance_for(
        rung="usda_exact", food_class=FoodClass.GENERIC,
        macros_from_source=False, micronutrient_source="usda_exact")
    out = display_detail(supplemented)
    assert out == ("Portion estimated · nutrition profile supplemented with "
                   "USDA data")
    assert "From the USDA database" not in out


def test_a_generic_standing_in_for_a_product_says_so():
    fallback = provenance_for(rung="usda_generic",
                              food_class=FoodClass.MANUFACTURED)
    assert fallback.is_fallback
    assert "standing in" in display_detail(fallback)


def test_the_provenance_roles_are_separately_recorded():
    """One field could not tell the truth: a turn can identify a product from a
    branded database, size the portion from the user's words, take macros from
    the model and fill micros from USDA."""
    p = provenance_for(rung="branded_exact", food_class=FoodClass.MANUFACTURED,
                       portion_source="user_stated",
                       micronutrient_source="usda_exact",
                       macros_from_source=False)
    d = p.as_dict()
    assert d["identity_source"] == "branded_exact"
    assert d["portion_source"] == "user_stated"
    assert d["primary_macro_source"] == "estimate"
    assert d["micronutrient_source"] == "usda_exact"
    assert p.macros_are_estimated is True


def test_every_ladder_ends_in_a_disclosed_fallback():
    """A ladder whose last rung is not a fallback would fail silently when
    nothing above it matched."""
    for food_class, rungs in LADDERS.items():
        assert rungs[-1] in FALLBACK_RUNGS, food_class


# ── The wiring: the ladder has to be what the live path actually walks ───────
#
# The module above can be perfect and change nothing. These pin the three
# seams where the old fixed order lived: which candidate `analyze()` seats,
# which row the cache writes, and what the card then claims.

def test_usda_is_not_placed_on_the_restaurant_ladder():
    """USDA has no row for a chain's menu item, so against one it is not a
    weaker answer — it is not an answer. Half a Starbucks turkey bacon sandwich
    shipped at 180 calories against a published 115 because it was allowed to
    compete."""
    from skills.nutrition.authority import candidate_map
    usda = {"per100g": {"calories": 250}, "_match": "likely"}
    seated = candidate_map(food_class=FoodClass.RESTAURANT, usda_candidate=usda)
    assert seated == {}


def test_a_cached_generic_re_enters_as_a_generic_for_a_named_product():
    """The row is written after every successful lookup, so most rows are a
    cache of our own answer. Seating one as a product answer is what let a
    single generic lookup for a named product keep winning forever."""
    from skills.nutrition.authority import candidate_map
    memory = {"per100g": {"calories": 300}, "origin_tier": "generic_exact"}
    seated = candidate_map(food_class=FoodClass.MANUFACTURED, memory_match=memory)
    assert "usda_generic" in seated and "saved_product" not in seated
    # ...and one the user actually corrected is not demoted with it.
    corrected = candidate_map(food_class=FoodClass.MANUFACTURED,
                              memory_match={"per100g": {}, "user_confirmed": True})
    assert "user_correction" in corrected


def test_a_named_product_on_a_generic_rung_still_warrants_the_lookup():
    """§5. The cached-generic case is the same failure made permanent."""
    from skills.nutrition.authority import needs_branded_lookup
    assert needs_branded_lookup(FoodClass.MANUFACTURED, "usda_generic") is True
    assert needs_branded_lookup(FoodClass.MANUFACTURED, "branded_exact") is False
    assert needs_branded_lookup(FoodClass.GENERIC, "estimate") is False


def test_analyze_walks_the_class_ladder_not_a_fixed_order():
    """`memory or usda or off or web` was one order for every food."""
    from core.food_intelligence import analyze
    usda = {"per100g": {"calories": 250, "protein": 10, "sodium": 400},
            "_match": "exact", "fdc_id": "u1"}
    r = analyze("Starbucks turkey bacon sandwich", "half", 115, 12, 10, 3,
                usda_candidate=usda)
    # USDA is off this food's ladder, so it never sets the calories...
    assert r.calories == 115
    assert r.provenance.primary_macro_source != "usda_exact"
    # ...but it is not thrown away either; it fills the panel.
    assert r.provenance.micronutrient_source == "usda_generic"


def test_a_generic_food_still_takes_usda(monkeypatch):
    """The fix must not cost the cases that were already right — the bagel and
    the salmon in that same meal needed no branded lookup and were both fine."""
    from core.food_intelligence import analyze
    usda = {"per100g": {"calories": 200, "protein": 20, "fat": 12},
            "_match": "exact", "fdc_id": "u2"}
    r = analyze("salmon", "150g", 250, 22, 0, 14, usda_candidate=usda)
    assert r.provenance.food_class == "generic"
    assert r.provenance.rung == "usda_exact"
    assert r.calories == 300          # computed forward from 150g × density
    assert r.provenance.primary_macro_source == "usda_exact"


def test_the_card_does_not_credit_usda_for_numbers_it_did_not_produce():
    """§7. When the model's calories were kept and USDA supplied only sodium,
    the card still said 'From the USDA database'."""
    from core.food_intelligence import analyze
    from skills.nutrition.authority import display_detail
    usda = {"per100g": {"calories": 250, "sodium": 500}, "_match": "likely"}
    r = analyze("chicken shawarma", "1 wrap", 600, 40, 50, 25,
                usda_candidate=usda)
    detail = display_detail(r.provenance)
    assert "From the USDA database" not in detail
    assert "supplemented" in detail


def test_the_cache_records_the_row_the_resolution_used():
    """§8. The winner was recomputed at cache time, so the row written could
    disagree with the row used."""
    from skills.nutrition.authority import candidate_map, select, classify
    usda = {"per100g": {"calories": 250}, "_match": "likely", "fdc_id": "u"}
    web = {"per100g": {"calories": 60}, "_match": "exact", "fdc_id": "w"}
    fc = classify("Philadelphia scallion cream cheese", is_packaged=True)
    rung, hit = select(candidate_map(food_class=fc, usda_candidate=usda,
                                     web_candidate=web), fc)
    assert rung == "manufacturer" and hit is web
    # The old `usda or off or web` would have cached the 250-cal generic under
    # the product's name while the 60-cal label answered the turn.
    assert (usda or web) is usda


def test_confidence_alone_cannot_seat_a_cache_at_a_branded_rung():
    """The origin column decides, never the grade. A USDA text match is graded
    'exact' too, which is how the first backfill promoted cached generics to
    `branded_exact` — where `needs_branded_lookup` stops firing and the stale
    row keeps suppressing the very enrichment the column was added to restore
    (alembic a1f4c7d2b8e3)."""
    from skills.nutrition.authority import candidate_map, needs_branded_lookup
    row = {"per100g": {"calories": 300}, "confidence": "exact",
           "origin_tier": "generic_exact"}
    seated = candidate_map(food_class=FoodClass.MANUFACTURED, memory_match=row)
    assert "saved_product" not in seated
    rung = next(iter(seated))
    assert needs_branded_lookup(FoodClass.MANUFACTURED, rung) is True
