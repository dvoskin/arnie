"""One serving of a labelled product is a KNOWN mass, not an estimate.

From the shipped transcript: a Legendary Foods Milk Chocolate Sweet Roll logged
at 190 cal / 17g protein against a published 210 / 20, with the card reading
"Portion estimated · nutrition profile supplemented with USDA data".

`analyze()` only used a source's numbers when the quantity was an explicit MASS
— "200g", "6 oz". Everything else took the estimate path, which keeps the
model's calories and borrows only fibre, sugar, sodium and micros. But "1 roll"
and "1 bar" are not vague portions: they are exactly one of the thing the label
describes, and a label consumed at one serving determines the answer completely.

So most branded logging — which is done in whole servings, because that is how
packaged food is eaten — resolved as an estimate with a label fetched,
consulted for sodium, and discarded for calories. Fixing the lookup alone would
not have fixed the number; fixing the label alone would not have fixed it
either.
"""
import pytest

from core.food_intelligence import _mass_from_serving_panel, analyze
from skills.nutrition.authority import display_detail

ROLL = {"per100g": {"calories": 368, "protein": 35, "carbs": 33, "fat": 12},
        "_match": "exact", "serving_text": "1 roll (57 g)", "fdc_id": "w1"}


def test_the_shipped_case_now_reads_the_label():
    """190/17 was the model's guess. 210/20 is the label."""
    r = analyze("Legendary Foods Milk Chocolate Sweet Roll Protein", "1 roll",
                190, 17, 19, 7, web_candidate=ROLL, is_packaged=True)
    assert r.calories == 210
    assert r.protein == pytest.approx(19.9, abs=0.2)
    assert display_detail(r.provenance) == "From the manufacturer's label"


def test_a_single_serving_panel_needs_no_count_unit():
    """"1 roll (57 g)" — the serving IS one unit, so there is nothing to
    enumerate. `serving_unit_mass` returns None here by design, and
    `_serving_count` has no word for "roll" anyway. The panel does not need to
    name the unit for "one serving weighs 57 g" to be true."""
    assert _mass_from_serving_panel("1 roll", ROLL, "sweet roll") == 57.0
    assert _mass_from_serving_panel(
        "2 rolls", ROLL, "sweet roll") == 114.0


def test_an_enumerated_panel_must_match_the_portion_s_unit():
    """"35 g (12 pieces)" against "15 pieces" is the same object. Against
    "1 bar" it is not, and multiplying one by the other turns a portion into a
    package."""
    panel = {"serving_text": "35 g (12 pieces)"}
    assert _mass_from_serving_panel("15 pieces", panel, "peanut m&ms") == \
        pytest.approx(43.75, abs=0.1)
    assert _mass_from_serving_panel("1 bar", panel, "peanut m&ms") is None


def test_a_vague_helping_is_never_multiplied_by_a_serving():
    """The count-basis gate from the count-as-serving work. A bar is the
    label's own unit; a bowl is a helping we estimated a mass for, and one
    bowl is not one serving of anything."""
    panel = {"serving_text": "1 serving (40 g)"}
    assert _mass_from_serving_panel("1 bowl", panel, "granola") is None


def test_no_panel_leaves_the_estimate_path_exactly_as_it_was():
    """The change must cost nothing where there is nothing to read."""
    no_panel = {"per100g": {"calories": 368, "protein": 35}, "_match": "exact"}
    r = analyze("some protein roll", "1 roll", 190, 17, 19, 7,
                web_candidate=no_panel, is_packaged=True)
    assert r.calories == 190          # the model's number, untouched
    assert _mass_from_serving_panel("1 roll", no_panel, "roll") is None


def test_a_stated_mass_still_wins_over_the_panel():
    """"57 g" is a measurement. The panel is only consulted when the user gave
    no mass of their own."""
    r = analyze("Legendary Foods Sweet Roll", "114g", 190, 17, 19, 7,
                web_candidate=ROLL, is_packaged=True)
    assert r.calories == 420          # 114g x 3.68 cal/g, from the mass


def test_a_malformed_panel_never_raises():
    for junk in ("", "one serving", "N/A", None):
        assert _mass_from_serving_panel(
            "1 bar", {"serving_text": junk}, "bar") is None
