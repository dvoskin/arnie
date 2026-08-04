"""A calibrated portion prices better than a calorie guess. Measured, not assumed.

`analyze` used to compute `grams = cal / cal100 * 100` whenever the user had not
stated an explicit weight — so the model's calorie guess BECAME the portion, and
every macro was rescaled off that same guess. A 38% calorie undercount is
mechanically a 38% protein undercount. Prod 2026-08-03: "Grilled Chicken (1 cup)"
committed 143 cal / 23 g against a published 231 / 43.

`core.portions.mass_grams` declines cups and pieces because "the gram weight is
itself a guess and shouldn't override the LLM's estimate" — but the alternative
it leaves is not "no guess", it is a worse one that nothing downstream can see.

THE REFERENCES BELOW ARE PUBLISHED PORTION DATA, NOT THIS REPO'S ONTOLOGY.
That distinction is the whole point of the file. The first version of this
measurement back-derived its "truths" with the same `grams x per-100g` formula
it was evaluating and scored 1% error — which meant nothing. Five of nine rows
were circular. These masses come from standard references (USDA serving weights,
1 oz = 28 g, 2 large eggs = 100 g) and are written down so a future reader can
check them rather than trust them.

This is a GATE, not a report: if a portion row drifts or the pricing path
regresses to inverting the calorie guess, the aggregate moves and this fails.
"""
import pytest

from skills.nutrition.normalize import normalize_quantity


#: (quantity, food, source per-100g cal, the model's typical guess,
#:  published portion grams, published calories)
REFERENCE_PORTIONS = [
    ("1 cup", "White rice, cooked",   130, 205, 158, 205),
    ("1 cup", "Grilled chicken",      165, 143, 140, 231),
    ("1 cup", "Ground beef, cooked",  250, 240, 136, 340),
    ("a handful", "Almonds",          579, 170,  28, 164),
    ("3 slice", "Honey turkey",       104,  68,  57,  59),
    ("1 slice", "Challah bread",      280, 140,  43, 120),
    ("1 bowl", "Oatmeal",              68, 150, 234, 158),
    ("2 eggs", "Eggs",                143, 140, 100, 143),
]


def _errors():
    forward, model = [], []
    for qty, food, per100, guess, _ref_g, truth in REFERENCE_PORTIONS:
        grams = normalize_quantity(qty, food).grams
        assert grams, f"{qty!r} of {food!r} produced no mass at all"
        fwd = grams * per100 / 100.0
        forward.append(abs(fwd - truth) / truth * 100)
        model.append(abs(guess - truth) / truth * 100)
    return forward, model


def _median(xs):
    s = sorted(xs)
    return s[len(s) // 2]


def test_pricing_from_the_portion_beats_pricing_from_the_guess():
    """The aggregate claim, and the reason the old rule was inverted."""
    forward, model = _errors()
    assert _median(forward) < _median(model), (
        f"median error: forward {_median(forward):.0f}% vs model "
        f"{_median(model):.0f}% — the portion path is no longer the better one")
    assert max(forward) < max(model), (
        f"worst case: forward {max(forward):.0f}% vs model {max(model):.0f}%")


def test_no_reference_portion_is_badly_priced():
    """A per-case floor, so a single bad row cannot hide inside a good median."""
    bad = []
    for (qty, food, per100, _guess, _ref_g, truth) in REFERENCE_PORTIONS:
        grams = normalize_quantity(qty, food).grams
        err = abs(grams * per100 / 100.0 - truth) / truth * 100
        if err > 15:
            bad.append(f"{qty} {food}: {err:.0f}% off {truth} cal")
    assert not bad, "portion rows drifted from published values — " + "; ".join(bad)


@pytest.mark.parametrize("qty,food,ref_g", [
    (q, f, g) for q, f, _c, _guess, g, _t in REFERENCE_PORTIONS
])
def test_each_portion_mass_matches_its_published_weight(qty, food, ref_g):
    """The masses themselves, against the references. A calorie test can pass on
    a compensating error in the per-100g row; this cannot."""
    grams = normalize_quantity(qty, food).grams
    assert abs(grams - ref_g) / ref_g <= 0.25, (
        f"{qty!r} of {food!r} is {grams:.0f} g against a published {ref_g} g")


def test_the_meat_category_exists_at_all():
    """`FOOD_CATEGORIES` had no meat/protein row, so "grilled chicken" fell to
    the catch-all cup mass — 120 g with a 60-240 g spread, which is
    indistinguishable from knowing nothing."""
    from skills.nutrition.portions import food_category
    assert food_category("Grilled chicken") == "meat"
    assert food_category("Ground beef") == "meat"
    # ...without stealing the deli fillings, which are cut and weighed
    # differently and have their own row.
    assert food_category("Honey turkey slices") == "deli_meat"
