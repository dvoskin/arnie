"""N servings of a product that publishes its serving needs no mass at all.

The anchor defect, stated plainly: with no serving size to scale by, `analyze`
derived the portion mass from the MODEL's calories —

    grams = cal / cal100 * 100

— and then scaled the label to fit that number. The label could never correct
the calories; it could only be rescaled around them. Every wrong branded figure
in this file's history traces back to it.

Open Food Facts publishes the label's own per-SERVING panel alongside per-100g,
and only `*_100g` was ever read. So the field that makes the derivation
unnecessary was being fetched and discarded — for the case that covers most
branded logging, because packaged food is eaten in whole servings.

    Royo Plain Bagel, "1 bagel"
      before:  80 cal, 8g protein   (the model's guess, label rescaled to it)
      after:   70 cal, 9g protein   (the published label, nothing derived)
"""
import pytest
from core.food_intelligence import analyze
from skills.nutrition import authority
from skills.nutrition.off import _per_serving

#: A branded record carrying both panels, as OFF returns.
_LABEL = {
    "per100g": {"calories": 250.0, "protein": 13.0, "carbs": 43.0, "fat": 1.5},
    "per_serving": {"calories": 70.0, "protein": 9.0, "carbs": 13.0,
                    "fat": 1.0, "fiber": 4.0, "sodium": 135},
    "_match": "exact", "fdc_id": "label"}


def _no_panel():
    out = dict(_LABEL)
    out.pop("per_serving")
    return out


# ── the parser ────────────────────────────────────────────────────────────────
def test_the_serving_panel_is_read_from_the_nutriments():
    panel = _per_serving({"energy-kcal_serving": 70, "proteins_serving": 9,
                          "carbohydrates_serving": 13, "fat_serving": 1,
                          "fiber_serving": 4, "sodium_serving": 0.135})
    assert panel == {"calories": 70.0, "protein": 9.0, "carbs": 13.0,
                     "fat": 1.0, "fiber": 4.0, "sodium": 135}


def test_kilojoules_are_accepted_when_calories_are_absent():
    panel = _per_serving({"energy-kj_serving": 293, "proteins_serving": 9,
                          "carbohydrates_serving": 13, "fat_serving": 1})
    assert panel and 69 <= panel["calories"] <= 71


def test_a_panel_missing_a_macro_is_unusable():
    assert _per_serving({"energy-kcal_serving": 70,
                         "proteins_serving": 9}) is None


def test_a_serving_is_not_bounded_like_100g():
    """A serving is legitimately a 5-calorie pickle or a 900-calorie meal;
    the per-100g plausibility window would reject real labels."""
    assert _per_serving({"energy-kcal_serving": 5, "proteins_serving": 0,
                         "carbohydrates_serving": 1, "fat_serving": 0})
    assert _per_serving({"energy-kcal_serving": 950, "proteins_serving": 40,
                         "carbohydrates_serving": 90, "fat_serving": 45})


# ── the resolution ────────────────────────────────────────────────────────────
def test_one_serving_is_the_label_verbatim():
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_LABEL, is_packaged=True)
    assert (result.calories, result.protein) == (70, 9.0)
    assert not result.provenance.macros_are_estimated
    assert "label" in authority.display_detail(result.provenance).lower()


def test_the_model_number_does_not_survive_a_published_serving():
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_LABEL, is_packaged=True)
    assert result.calories != 80


def test_a_fraction_and_a_multiple_both_scale():
    half = analyze("Royo Bagel, Plain", "0.5 bagel", 80, 8, 12, 1,
                   off_candidate=_LABEL, is_packaged=True)
    two = analyze("Royo Bagel, Plain", "2 bagel", 80, 8, 12, 1,
                  off_candidate=_LABEL, is_packaged=True)
    assert (half.calories, half.protein) == (35, 4.5)
    assert (two.calories, two.protein) == (140, 18.0)


def test_the_numbers_are_the_panel_verbatim_not_a_derivation():
    """The whole point: nothing is computed, so nothing can be computed wrong.
    Every field equals the label's own, unscaled by any mass."""
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_LABEL, is_packaged=True)
    panel = _LABEL["per_serving"]
    assert result.calories == panel["calories"]
    assert result.protein == panel["protein"]
    assert result.carbs == panel["carbs"]
    assert result.fat == panel["fat"]
    assert result.fiber == panel["fiber"]


def test_a_real_high_fibre_label_is_not_called_suspect():
    """Royo's published bagel is 70 cal against 9P/13C/1F — an Atwater sum of
    97 and a 39% "disagreement" with its own label, because 4 g of that carb is
    fibre. Counting fibre at 4 cal/g would have flagged every product in the
    category this whole path exists for."""
    from skills.nutrition import sanity
    assert not sanity.check_values(calories=70, protein=9, carbs=13, fat=1,
                                   fiber=4)
    assert sanity.check_values(calories=70, protein=9, carbs=13, fat=1)


def test_a_genuinely_broken_row_is_still_caught():
    from skills.nutrition import sanity
    findings = sanity.check_values(calories=200, protein=30, carbs=50, fat=20,
                                   fiber=2)
    assert any(f.code == "macro_energy_disagreement" for f in findings)


# ── what must NOT take the label's serving ────────────────────────────────────
def test_a_helping_is_not_the_labels_unit():
    """"1 bowl of cereal" is a helping we would have to estimate a mass for,
    not one 30 g serving. Same `count_basis` gate the mass path uses."""
    result = analyze("cereal", "1 bowl", 300, 8, 60, 3,
                     off_candidate=_LABEL, is_packaged=True)
    assert result.calories == 300, "the model's number stands for a helping"


def test_a_stated_mass_still_wins():
    """An explicit gram weight is better evidence than a serving count."""
    result = analyze("Royo Bagel, Plain", "100g", 80, 8, 12, 1,
                     off_candidate=_LABEL, is_packaged=True)
    assert result.calories == 250, "100 g x the per-100g density"


def test_a_weak_match_cannot_supply_a_serving():
    weak = dict(_LABEL)
    weak["_match"] = "estimated"
    result = analyze("some bagel", "1 bagel", 80, 8, 12, 1,
                     usda_candidate=weak)
    assert result.calories == 80


def test_a_record_without_the_panel_behaves_exactly_as_before():
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_no_panel(), is_packaged=True)
    assert result.calories == 80


# ── the web lane discards the same field, for the same reason ────────────────
#
# `_web_lookup_packaged` parses a nutrition label out of search results — and
# those parsed numbers ARE the label's serving. It converted them straight to a
# per-100g density and dropped the serving values, so a "1 roll" portion went
# back to deriving a mass from the model's calories even when the manufacturer
# page had been read successfully.
#
# This is the Legendary Foods case PR #44 was built around: 190 cal / 17 g
# protein committed against a published 210 / 20.
_WEB_LABEL = {
    "fdc_id": None, "_match": "likely",
    "per100g": {"calories": 350.0, "protein": 33.3, "carbs": 40.0, "fat": 11.7,
                "fiber": None, "sugar": None, "sodium": None},
    "per_serving": {"calories": 210.0, "protein": 20.0, "carbs": 24.0,
                    "fat": 7.0},
    "serving_text": "60 g"}


def test_a_web_read_label_answers_a_count_portion_outright():
    result = analyze("Legendary Foods Milk Chocolate Sweet Roll", "1 roll",
                     190, 17, 19, 7, web_candidate=_WEB_LABEL,
                     is_packaged=True)
    assert (result.calories, result.protein) == (210, 20.0)
    assert (result.carbs, result.fat) == (24.0, 7.0)


def test_it_reaches_the_manufacturer_rung():
    """The string that had never been shown to a user."""
    result = analyze("Legendary Foods Milk Chocolate Sweet Roll", "1 roll",
                     190, 17, 19, 7, web_candidate=_WEB_LABEL,
                     is_packaged=True)
    assert result.provenance.rung == "manufacturer"
    assert "manufacturer" in authority.display_detail(result.provenance).lower()


def test_two_rolls_scale_from_the_label_not_the_guess():
    result = analyze("Legendary Foods Milk Chocolate Sweet Roll", "2 rolls",
                     380, 34, 38, 14, web_candidate=_WEB_LABEL,
                     is_packaged=True)
    assert (result.calories, result.protein) == (420, 40.0)


# ── a "serving" that is not one ───────────────────────────────────────────────

def test_a_hundred_gram_serving_is_the_basis_not_a_serving():
    """Open Food Facts publishes `serving_size: 100g` when a product has no
    real panel — the per-100g row wearing a serving's name. Read literally,
    "1 bar" became one hundred grams: a fun size Milky Way committed 439
    calories against a real 80.

    It only escaped notice because the overcount guard demoted it — so the
    committed number depended on how badly the model happened to guess. At a
    guess of 80 it looked correct; at 120 it shipped 439.
    """
    from core.food_intelligence import _mass_from_serving_panel
    junk = {"per100g": {"calories": 438.7, "protein": 3.3},
            "serving_text": "100.0g", "_match": "exact"}
    assert _mass_from_serving_panel("1 bar", junk, "Milky Way fun size") is None


@pytest.mark.parametrize("text", ["100g", "100.0g", "100 g", "100ml", "100.0ml"])
def test_every_spelling_of_the_basis_is_refused(text):
    from core.food_intelligence import _mass_from_serving_panel
    src = {"per100g": {"calories": 400.0}, "serving_text": text,
           "_match": "exact"}
    assert _mass_from_serving_panel("1 bar", src, "some bar") is None


def test_a_sharing_bag_is_not_one_serving():
    """A single-serve product's net weight IS its serving — that is why so many
    publish no panel. A 227 g bag of fun size bars is not one bar, and
    `package_text` reads "227g" either way."""
    from core.food_intelligence import _mass_from_serving_panel
    bag = {"per100g": {"calories": 438.7}, "serving_text": "",
           "package_text": "227g", "_match": "exact"}
    assert _mass_from_serving_panel("1 bar", bag, "Milky Way fun size") is None


def test_a_real_single_serve_package_still_answers():
    """The bound must not cost the case the package-as-serving path was built
    for — a 60 g bar that publishes no panel."""
    from core.food_intelligence import _mass_from_serving_panel
    single = {"per100g": {"calories": 400.0}, "serving_text": "",
              "package_text": "60g", "_match": "exact"}
    assert _mass_from_serving_panel("1 bar", single, "protein bar") == 60.0


def test_a_real_enumerated_panel_still_answers():
    from core.food_intelligence import _mass_from_serving_panel
    real = {"per100g": {"calories": 400.0}, "serving_text": "1 bar (60 g)",
            "_match": "exact"}
    assert _mass_from_serving_panel("1 bar", real, "protein bar") == 60.0
