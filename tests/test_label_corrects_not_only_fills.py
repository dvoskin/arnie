"""A label may correct a number, not only fill an empty one.

Six live logs, one root cause. Every item in them — Royo bagel, Ezekiel bread,
LikeAir puffs, Lunchables pizza, mayo, cheese, jalapenos — had its lookup run,
match, and get seated on the ladder, and still committed the model's macros.
The receipt even said "From the product label" over numbers no label produced.

The estimate path is where it happens. With no stated mass it back-derives the
portion from the MODEL's calories:

    grams = cal / cal100 * 100          # cal is the model's guess
    ratio = grams / 100.0
    fiber = per100["fiber"] * ratio     # label
    sugar = per100["sugar"] * ratio     # label
    sodium = per100["sodium"] * ratio   # label
    micros = {...}                      # label
    if not protein and per100.get("protein"):   # <- label, ONLY IF EMPTY
        protein = per100["protein"] * ratio

So the row was a MIXTURE: calories from the model, fibre and sodium and micros
from the label, protein from whichever spoke first. A label could supply what
the model omitted and could never fix what the model got wrong — and a wrong
number is the failure mode, not a missing one.

Nothing downstream could detect it, because one row cannot say that two of its
numbers disagree about what the food is.

What this does NOT fix, and it is the deeper half: the calories are still the
model's, and the mass is derived from them, so the label is scaled to fit the
guess rather than correcting it. The profile just stops compounding it.
"""
from core.food_intelligence import analyze

#: A real branded record: exact name match, full per-100g panel, no serving
#: size (the common shape — see test_serving_size_is_fetched_not_inferred).
_LABEL = {"per100g": {"calories": 250.0, "protein": 13.0, "carbs": 43.0,
                      "fat": 1.5, "fiber": 6.0, "sodium": 170.0},
          "_match": "exact", "fdc_id": "label"}

#: A weak USDA text match. Explicitly NOT trustworthy enough to overrule the
#: model — that is the wrong-cousin class ("lean chicken" for a shawarma).
_WEAK_USDA = {"per100g": {"calories": 250.0, "protein": 13.0},
              "_match": "likely", "fdc_id": "usda-row"}


def test_a_wrong_model_macro_is_corrected_by_the_label():
    """The shipped case. 1 g of protein in a slice of Ezekiel bread."""
    result = analyze("Ezekiel Bread", "1 slice", 80, 1, 15, 0.5,
                     off_candidate=_LABEL, is_packaged=True)
    assert result.protein == 4.2, "the label's protein at this portion"
    assert result.protein != 1, "the model's protein must not survive a label"


def test_every_macro_comes_from_the_same_portion_of_the_same_source():
    """The defect was a mixture, so the fix is asserted as a whole profile."""
    result = analyze("Ezekiel Bread", "1 slice", 80, 1, 15, 0.5,
                     off_candidate=_LABEL, is_packaged=True)
    ratio = result.calories / _LABEL["per100g"]["calories"]
    for field, key in (("protein", "protein"), ("carbs", "carbs"),
                       ("fat", "fat")):
        expected = round(_LABEL["per100g"][key] * ratio, 1)
        assert abs(getattr(result, field) - expected) < 0.15, field


def test_the_derived_profile_stays_consistent_with_the_calories_on_the_card():
    """The ratio is unchanged, so a card cannot show macros that contradict its
    own calorie figure."""
    result = analyze("Ezekiel Bread", "1 slice", 80, 1, 15, 0.5,
                     off_candidate=_LABEL, is_packaged=True)
    implied = 4 * result.protein + 4 * result.carbs + 9 * result.fat
    assert abs(implied - result.calories) / result.calories < 0.30


def test_an_absent_macro_is_still_filled():
    """The old behaviour was not wrong, only incomplete."""
    result = analyze("Ezekiel Bread", "1 slice", 80, 0, 0, 0,
                     off_candidate=_LABEL, is_packaged=True)
    assert result.protein == 4.2


def test_a_weak_text_match_still_does_not_overrule_the_model():
    """Correcting from a source we do not trust is how a shawarma becomes lean
    chicken. The trust gate is the same one the ground-truth path uses."""
    result = analyze("some bread", "1 slice", 80, 1, 15, 0.5,
                     usda_candidate=_WEAK_USDA)
    assert result.protein == 1.0, "the model's number stands against a weak match"


def test_no_source_at_all_changes_nothing():
    result = analyze("mystery pastry", "1 piece", 200, 5, 30, 7)
    assert (result.calories, result.protein) == (200, 5.0)


def test_the_provenance_does_not_start_claiming_the_label():
    """The calories are still the model's. A profile derived from the label at
    a mass the model implied is not "from the product label", and saying so
    would be the same lie in a new place."""
    from skills.nutrition import authority
    result = analyze("Ezekiel Bread", "1 slice", 80, 1, 15, 0.5,
                     off_candidate=_LABEL, is_packaged=True)
    assert result.provenance.macros_are_estimated
    assert "estimate" in authority.display_detail(result.provenance).lower()
