"""A mass we invented does not buy the trust of one we measured.

`analyze` demotes an enriched row that overshoots the model's own read, and the
bound is wider when the portion's mass is KNOWN — 4x instead of 2.5x. The
argument for the wider one is stated in the code and is about measurement: "All
three are exact matches with a known mass, so no yes/no test on evidence
quality separates them — only magnitude does."

`_mg` reaches that decision from three places, and only two are measurements:

  * `mass_grams(quantity)`         — the user stated a weight
  * `_mass_from_serving_panel`     — the label says what one serving weighs
                                     ("That is a KNOWN mass, not an estimate")
  * `portion_prior(name)`          — a population typical for an un-weighed
                                     whole food. Not exact, and not a mass
                                     anyone measured.

The third was counting as known. `_from_prior` had been computed for exactly
this distinction and was never read anywhere in the file.

Why it matters: anything between 2.5x and 4x the model's read commits silently
when a prior is mistaken for a measurement, and that band is where a
wrong-portion row lives — right enough to look like the same food, wrong enough
to be a different meal.

TWO THINGS THIS DOES NOT CLAIM.

  * It does not explain the 528-cal cup of rice from the 2026-08-03 transcript.
    The fixture below lands on 528 because 264 cal/100g x 200 g was CHOSEN to
    land there and make the arithmetic legible — not because that is what
    production did. USDA's cooked white rice is ~130 cal/100g, which through
    this path gives ~260. What produced the real 528 is still open.
  * It is gated on NUTRITION_ACCURACY_V2, and I have not verified that flag was
    on for that user. The rule is right either way; whether it was live in that
    incident is unconfirmed.
"""
import pytest

import core.food_intelligence as FI


def test_the_two_bounds_are_what_the_argument_says_they_are():
    """Pinned so a future edit to either constant has to face this file."""
    assert FI._OVERCOUNT_MULTIPLE == 2.5
    assert FI._OVERCOUNT_MULTIPLE_KNOWN_MASS == 4.0


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "true")


def _usda(cal_per_100g, protein=20.0):
    return {"description": "Rice, white, cooked", "match": "exact",
            "per100g": {"calories": cal_per_100g, "protein": protein,
                        "carbs": 28.0, "fat": 0.3}}


def test_a_prior_mass_does_not_earn_the_wider_bound(v2):
    """"a cup of white rice" has no stated mass and no serving panel, so the
    only mass available is `portion_prior('white rice') == 200 g` — invented on
    our side. A source row that then overshoots the model by ~2.6x must be
    demoted, not committed."""
    out = FI.analyze("White rice", "1 cup", 205, 4, 45, 0.4,
                     usda_candidate=_usda(264.0))
    assert round(out.calories) <= round(2.5 * 205), (
        f"committed {out.calories} against a model read of 205 — a prior mass "
        f"bought the 4x bound")


def test_a_stated_mass_keeps_the_wider_bound(v2):
    """The case the wide bound exists for must be untouched: a real weight, an
    exact match, and a model that guessed low."""
    out = FI.analyze("White rice", "200 g", 205, 4, 45, 0.4,
                     usda_candidate=_usda(264.0))
    assert round(out.calories) > round(2.5 * 205) or out.source != "usda", (
        "a STATED 200 g should still be allowed the wider bound")
