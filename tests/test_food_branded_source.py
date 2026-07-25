"""A named product answered by a generic row (transcripts, 2026-07-25).

    Logged Peanut M&Ms — 135 cal
    From the USDA database

A standard label puts 12 pieces at 140 calories, so 15 is near 175. The tier
order was never the problem — `resolver.py` has ranked a branded label above a
generic row since it was written. Three things upstream of that ranking were:

  1. NOTHING RECOGNISED THE PRODUCT. `tool_executor._looks_branded` matched a
     capitalised token followed by a package noun, but the noun alternation was
     lowercase and case-SENSITIVE while the interpreter emits Title Case. The
     safety net had been dead for every name it was written for, so OFF (the
     branded label database) and the web-label lane were never consulted and a
     generic row won unopposed.

  2. THE RESOLVER WAS BLIND THE SAME WAY, SEPARATELY. Its `_is_branded_request`
     accepted only an explicit brand, the is_packaged flag, or a product-family
     rule — so the "generic data standing in for a named product" disclosure
     never fired on the transcript it was written for.

  3. THE SERVING PANEL WAS FETCHED AND DISCARDED. OFF asked for `serving_size`
     and dropped it; USDA never asked. Without it, "15 pieces" of a per-100g
     row has no mass, scaling is refused, `promotable()` declines, and the
     interpreter's own guess is committed — wearing the database's name.

Together: a guess, presented as a database answer, for a product whose label
was one lookup away.
"""
import pytest

from skills.nutrition.branded import (STRONG, WEAK, names_a_product,
                                      names_a_specific_product, product_signal)
from skills.nutrition.normalize import (count_units_compatible,
                                        serving_unit_mass)
from skills.nutrition.promotion import promotable
from skills.nutrition.shadow import resolve_from_live


# The label, expressed the way a source actually carries it: a per-100g panel
# plus the serving it was measured over. 140 cal / 35 g is 400 cal per 100 g,
# so every number below is DERIVED from these two facts. There is deliberately
# no 175 constant anywhere in this file — that is the value under test.
LABEL_SERVING_TEXT = "35 g (12 pieces)"
PEANUT_MM_LABEL = {
    "name": "M&M's Peanut", "brand": "M&M's", "_match": "exact",
    "serving_text": LABEL_SERVING_TEXT,
    "per100g": {"calories": 400, "protein": 9.4, "carbs": 58, "fat": 26},
}
#: USDA's generic stand-in — a real row, for a different food.
GENERIC_CHOCOLATE_PEANUTS = {
    "description": "Candies, chocolate coated peanuts", "fdc_id": 19125,
    "per100g": {"calories": 520, "protein": 14, "carbs": 45, "fat": 34},
}


def _resolve(quantity, *, name="Peanut M&Ms", **sources):
    return resolve_from_live(name, {"quantity": quantity}, **sources)


# ── 1. the product is recognised at all ──────────────────────────────────────
@pytest.mark.parametrize("name", [
    "Peanut M&Ms", "Peanut M&M's",              # ampersand
    "Barebells Salty Peanut Protein Bar",       # long product-line name
    "Reese's Cups",                             # possessive
    "Quest Bar", "Fairlife Core Power",         # product family
])
def test_a_named_product_reaches_the_branded_sources(name):
    """The gate that decides whether OFF is consulted at all."""
    from handlers.tool_executor import _looks_branded
    assert _looks_branded(name), f"{name!r} would never reach a branded source"


def test_the_title_case_regression_itself():
    """The exact shape that was dead: the old pattern wanted "bar" and the
    interpreter said "Bar", so the whole safety net silently never fired."""
    from handlers.tool_executor import _looks_branded
    assert _looks_branded("Barebells Salty Peanut Protein Bar")
    assert _looks_branded("Quest Protein Bar")


@pytest.mark.parametrize("name", [
    "Banana", "chicken breast", "white rice", "Chicken Breast",
    "protein bar", "a shake", "Oatmeal", "Scrambled Eggs", "Honey",
])
def test_a_generic_food_is_not_sent_to_a_branded_database(name):
    """The gate has to stay narrow, or every generic food pays an OFF lookup
    and every plain food gets a brand caveat."""
    from handlers.tool_executor import _looks_branded
    assert not _looks_branded(name)
    assert not names_a_specific_product(name)


def test_worth_a_lookup_is_a_lower_bar_than_worth_a_caveat():
    """The two gates ask different questions and must not collapse into one.

    "Peanut Butter" is worth checking a branded database for — the cost of
    being wrong is one lookup that identity validation discards. It is NOT
    worth telling the user their peanut butter came from generic data.
    """
    assert names_a_product("Peanut Butter")
    assert not names_a_specific_product("Peanut Butter")
    assert product_signal("Peanut Butter").strength == WEAK
    assert product_signal("Peanut M&Ms").strength == STRONG


def test_the_web_label_lane_asks_for_more_than_the_database_lane():
    """The two lanes do not carry the same risk. OFF is a structured index and
    its answer still has to survive identity validation; the web lane parses a
    label out of search results and has found the wrong product before."""
    from handlers.tool_executor import _looks_branded, _names_a_product

    assert _looks_branded("Peanut Butter")          # check the database
    assert not _names_a_product("Peanut Butter")    # do not go find a packet
    assert _names_a_product("Peanut M&Ms")
    assert _names_a_product("anything at all", is_packaged=True)


def test_a_possessive_dish_is_not_a_brand():
    """Shepherd's pie owns itself. Without this the possessive rule would put
    a manufacturer caveat on a category of home cooking."""
    assert not names_a_specific_product("Shepherd's Pie")


def test_the_signal_says_which_rule_fired():
    """A gate that cannot explain itself cannot be debugged when it is wrong —
    "we searched OFF for chicken breast" needs a reason attached."""
    assert product_signal("Ben & Jerry's Half Baked").reason == "brand_mark"
    assert product_signal("Quest Bar").reason == "product_family"
    assert product_signal("Peanut Butter").reason == "package_noun"
    # M&M's now has a family rule, and a rule is better evidence than a mark —
    # the strongest true reason is the one reported.
    assert product_signal("Peanut M&Ms").reason == "product_family"


# ── 2. the label outranks the generic row, and produces the label's number ────
def test_the_branded_label_wins_over_the_generic_row():
    out = _resolve("15 pieces", usda=GENERIC_CHOCOLATE_PEANUTS,
                   off=PEANUT_MM_LABEL)
    assert out.source == "off", "a generic row answered a named product"
    assert out.tier.label == "branded_exact"


def test_fifteen_pieces_is_not_one_hundred_and_thirty_five():
    """The shipped number. 135 came from the interpreter's guess surviving as
    the committed value because nothing else could be scaled."""
    out = _resolve("15 pieces", usda=GENERIC_CHOCOLATE_PEANUTS,
                   off=PEANUT_MM_LABEL)
    assert out.nutrients.amount("calories") != 135


def test_the_total_is_derived_from_the_selected_record():
    """15 pieces at the label's own 35 g / 12 pieces and 400 cal / 100 g.

    Asserted against the arithmetic, not against a remembered 175: a
    reformulation or a different variant must move this number, and a
    hardcoded constant would hide exactly that.
    """
    grams_per_piece = 35.0 / 12
    expected = round(15 * grams_per_piece / 100 * 400)
    out = _resolve("15 pieces", off=PEANUT_MM_LABEL)
    assert out.nutrients.amount("calories") == expected


def test_the_labels_own_serving_reproduces_the_labels_own_calories():
    """12 pieces has one right answer and the label states it. If this drifts,
    the piece-mass derivation is wrong regardless of what 15 comes to."""
    out = _resolve("12 pieces", off=PEANUT_MM_LABEL)
    assert out.nutrients.amount("calories") == 140


def test_a_variant_carries_its_own_piece_mass():
    """Plain M&M's are roughly a third of a Peanut M&M per piece. Nothing may
    be shared between them but the brand — which is why the mass comes from
    the selected record rather than a food-shaped average."""
    plain = {"name": "M&M's Milk Chocolate", "brand": "M&M's", "_match": "exact",
             "serving_text": "42 g (about 50 pieces)",
             "per100g": {"calories": 492, "protein": 4.3, "carbs": 71, "fat": 21}}
    peanut = _resolve("15 pieces", off=PEANUT_MM_LABEL).nutrients.amount("calories")
    plain_cal = _resolve("15 pieces", off=plain).nutrients.amount("calories")
    assert plain_cal < peanut / 2, (plain_cal, peanut)


def test_the_meal_total_moves_with_the_peanut_butter_answer():
    """One tablespoon versus two is ~95 calories, which is why it was worth a
    question. If the answer does not move the total, the question was theatre.
    """
    peanut_butter = {"name": "Peanut Butter", "_match": "likely",
                     "per100g": {"calories": 588, "protein": 25, "carbs": 20,
                                 "fat": 50}}
    one = _resolve("1 tbsp", name="Peanut Butter", off=peanut_butter)
    two = _resolve("2 tbsp", name="Peanut Butter", off=peanut_butter)
    assert one.nutrients.amount("calories") is not None
    assert two.nutrients.amount("calories") == pytest.approx(
        2 * one.nutrients.amount("calories"), rel=0.02)


# ── 3. the serving panel, which used to be fetched and thrown away ────────────
@pytest.mark.parametrize("text,mass,expected", [
    ("35 g (12 pieces)", None, (35 / 12, "piece")),
    ("12 pieces (35g)", None, (35 / 12, "piece")),
    ("12 pieces", 35.0, (35 / 12, "piece")),
    ("1 bar (55 g)", None, (55.0, "bar")),
])
def test_a_serving_panel_yields_a_unit_mass(text, mass, expected):
    grams, unit = serving_unit_mass(text, mass)
    assert grams == pytest.approx(expected[0], rel=1e-3)
    assert unit == expected[1]


@pytest.mark.parametrize("text,mass", [
    ("35 g", None),          # a mass with nothing to divide it by
    ("12 pieces", None),     # a count with no mass
    ("2 tbsp (32 g)", None), # a volume, which scaling already handles
    ("", 35.0),
])
def test_half_a_serving_panel_derives_nothing(text, mass):
    """A guessed unit mass is the confident wrong number this layer exists to
    prevent. Unscalable is a state the ask ladder can act on."""
    assert serving_unit_mass(text, mass) is None


def test_a_bar_panel_does_not_answer_a_piece_count():
    """"15 pieces" against a panel of "1 bar (55 g)" is 825 g of protein bar.
    Scaling one count unit by another is how a portion becomes a package."""
    assert not count_units_compatible("pieces", "bar")
    bar_panel = dict(PEANUT_MM_LABEL, serving_text="1 bar (55 g)")
    out = _resolve("15 pieces", off=bar_panel)
    assert out.quantity.grams is None
    assert out.nutrients.amount("calories") is None


def test_the_derived_mass_is_disclosed_and_replaces_the_unknown():
    """The user is told where the mass came from, and is not simultaneously
    told it is unknown — the two assumptions contradict each other."""
    out = _resolve("15 pieces", off=PEANUT_MM_LABEL)
    assert any("per piece" in a and "serving panel" in a
               for a in out.assumptions), out.assumptions
    assert "portion mass unknown" not in out.assumptions


def test_the_adapters_actually_carry_the_panel():
    """The panel existed in the OFF response fields all along and was dropped
    on the way out. Pinning the adapters, not just the parser."""
    from skills.nutrition.candidates import off_candidate, usda_candidates

    off = off_candidate(PEANUT_MM_LABEL)
    assert off.serving_text == LABEL_SERVING_TEXT

    usda = usda_candidates([dict(GENERIC_CHOCOLATE_PEANUTS,
                                 serving_text="1 cup", serving_mass_g=170.0)])
    assert usda[0].serving_text == "1 cup"
    assert usda[0].serving_mass_g == 170.0


# ── 4. when there is no label, say so ────────────────────────────────────────
def test_a_generic_answering_a_named_product_is_disclosed():
    """The branded source is unavailable and a generic row is all there is.
    That is a legitimate answer — it is not a legitimate SILENT answer."""
    out = _resolve("35 g", usda=GENERIC_CHOCOLATE_PEANUTS)
    assert out.source == "usda"
    assert any("generic data for a named product" in a
               for a in out.assumptions), out.assumptions


def test_the_generic_fallback_widens_the_doubt_band():
    """A category average for a specific product is a different KIND of answer,
    and the ask ladder has to be able to see that."""
    out = _resolve("35 g", usda=GENERIC_CHOCOLATE_PEANUTS)
    branded = [a for a in out.ambiguities if a.field == "branded_source"]
    assert branded, out.ambiguities
    assert branded[0].calorie_span > 0


def test_plain_food_gets_no_brand_caveat():
    """The disclosure has to stay rare enough to be read."""
    out = _resolve("1 medium", name="Banana",
                   usda={"description": "Bananas, raw", "fdc_id": 1,
                         "per100g": {"calories": 89, "protein": 1.1,
                                     "carbs": 23, "fat": 0.3}})
    assert not any("named product" in a for a in out.assumptions), out.assumptions


def test_a_cached_generic_does_not_outrank_the_manufacturer():
    """The conflicting-records case. The cache row was written automatically
    after a previous generic lookup; the label is the product itself."""
    cached_generic = {"per100g": GENERIC_CHOCOLATE_PEANUTS["per100g"],
                      "user_confirmed": False, "origin_tier": "generic_exact",
                      "confidence": "likely"}
    out = _resolve("15 pieces", memory=cached_generic, off=PEANUT_MM_LABEL)
    assert out.source == "off", (
        "a cache of our own generic answer beat the manufacturer's label")


def test_a_correction_the_user_made_still_wins():
    """The other side of the same rule: a row the user actually corrected is
    theirs, and a database must not overwrite it."""
    corrected = {"per100g": {"calories": 300, "protein": 10, "carbs": 40,
                             "fat": 12},
                 "user_confirmed": True, "origin_tier": "user_regular",
                 "confidence": "user-confirmed"}
    out = _resolve("100 g", memory=corrected, off=PEANUT_MM_LABEL)
    assert out.nutrients.amount("calories") == 300


# ── 5. the resolution stays committable ──────────────────────────────────────
def test_a_scaled_branded_resolution_is_promotable():
    """The end of the chain. An unscalable resolution is declined by
    `promote()` and the interpreter's guess is committed instead — which is
    how a guess came to be labelled "from the USDA database"."""
    assert promotable(_resolve("15 pieces", off=PEANUT_MM_LABEL))


def test_an_unscalable_resolution_is_still_refused():
    """Widening what can be scaled must not weaken the refusal. A panel that
    says nothing must still produce no number rather than a plausible one."""
    no_panel = {k: v for k, v in PEANUT_MM_LABEL.items()
                if k != "serving_text"}
    out = _resolve("15 pieces", off=no_panel)
    assert out.nutrients.amount("calories") is None
    assert not promotable(out)
