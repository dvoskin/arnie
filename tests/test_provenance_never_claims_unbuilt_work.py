"""A provenance line may not describe work that did not happen.

`component_estimate` renders to the user as "Estimated from its components" —
under `display_detail`'s own docstring rule that the line "must be true". The
rung was assigned by a class check alone: any RESTAURANT-classed food whose
macros the ladder did not seat got the label, and no component pricing has ever
run in production (the engine exists only on two unmerged branches,
`40d4d9b` / `e4d651d`). Until the engine is seated, an unseated restaurant
estimate says "estimate".

Behavioural: `analyze()` is driven through the exact configuration that used to
produce the false label — a restaurant dish whose ladder seats nothing while an
off-ladder candidate supplements the panel — and the rung is read off the
returned analysis.
"""
from core.food_intelligence import analyze
from skills.nutrition import authority


def _weak_usda():
    """A USDA generic against a restaurant dish: the RESTAURANT ladder refuses
    it for macros, `off_ladder` still lets it fill the panel — which is the
    `src is not None and not macros_from_source` shape the relabel keyed on."""
    return {"fdc_id": "999999", "_match": "weak",
            "per100g": {"calories": 180.0, "protein": 12.0, "carbs": 10.0,
                        "fat": 9.0, "sodium": 400.0}}


def test_an_unseated_restaurant_estimate_says_estimate_not_components():
    result = analyze(
        "Chicken shawarma platter", "1 platter",
        700, 45, 50, 30,
        usda_candidate=_weak_usda(),
        restaurant="Corner Shawarma")
    rung = result.provenance.rung
    assert rung != "component_estimate", (
        "'Estimated from its components' would render for work nothing "
        "performed — no component pricing has ever run")
    assert rung == "estimate"
    assert result.confidence == "estimated"
    assert "components" not in authority.display_detail(result.provenance).lower()


def test_the_component_rung_still_exists_for_the_engine_to_claim():
    """The ladder keeps the rung and its label — deleting capability on
    zero-caller reasoning is the `meal_resolution` mistake. Only the false
    ASSIGNMENT went."""
    assert "component_estimate" in authority.FALLBACK_RUNGS
    assert authority.display_detail.__doc__  # the "must be true" contract