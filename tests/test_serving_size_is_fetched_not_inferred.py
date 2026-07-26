"""A missing serving size is a fact to fetch, not a number to infer.

`tests/test_release_transcripts.py` pinned the residual half of the
serving-basis seam: a branded candidate carrying per-100g figures and NO
serving size wins IDENTITY — the rung reads branded_exact — while the macros
stay the model's, because a count portion ("1 bagel") has no mass to scale by.
That is how 190/17 shipped against a published 210/20.

The obvious fix is wrong. The portion ontology holds 105 g for a bagel, and a
Royo bagel is 57 g; a branded product is frequently and deliberately unlike its
generic — that is the entire proposition of a high-protein low-calorie bagel.
Multiplying a generic mass by a branded density would nearly double the error
while looking more authoritative than the guess it replaced.

So the lane opens instead. And when it comes back, it fills the missing field
rather than replacing the identity that was already validated.
"""
import skills.nutrition.authority as A
from core.portions import expected_grams


def _exact(cal, serving=""):
    out = {"_match": "exact", "per100g": {"calories": cal}}
    if serving:
        out["serving_text"] = serving
    return out


def _seated_without_serving(off, food_class=A.FoodClass.MANUFACTURED):
    cands = A.candidate_map(food_class=food_class, off_candidate=off)
    return (cands.get("branded_exact") is off
            and not str((off or {}).get("serving_text") or "").strip())


# ── why the ontology is not the answer ────────────────────────────────────────
def test_the_generic_mass_is_nothing_like_the_branded_one():
    """The number that would have been used, against the number on the box."""
    generic_bagel = expected_grams("Royo Bagel, Plain", "1 bagel")
    assert generic_bagel is not None
    royo_bagel = 57.0
    assert generic_bagel > royo_bagel * 1.7, (
        f"generic {generic_bagel}g vs branded {royo_bagel}g — applying one to "
        "the other's density is not a fallback, it is a different food")


def test_the_ontology_does_not_even_know_most_branded_formats():
    """It would not have rescued the transcript it was proposed for."""
    for name, qty in (("Legendary Sweet Roll", "1 roll"),
                      ("Barebells Bar", "1 bar"),
                      ("Nissin Cup Noodles", "1 container")):
        assert expected_grams(name, qty) is None, name


# ── the condition that opens the lane ─────────────────────────────────────────
def test_a_seated_candidate_missing_its_serving_is_detected():
    assert _seated_without_serving(_exact(123))


def test_a_seated_candidate_with_its_serving_is_complete():
    assert not _seated_without_serving(_exact(123, "1 bagel (57 g)"))


def test_an_unseated_candidate_is_not_this_case():
    """A loose match was never going to determine the macros anyway; it is the
    branded-lookup condition, not the serving-size one."""
    assert not _seated_without_serving({"_match": "estimated",
                                        "per100g": {"calories": 123}})


def test_a_generic_food_is_not_this_case():
    assert not _seated_without_serving(_exact(123),
                                       food_class=A.FoodClass.GENERIC)


# ── the serving size, once fetched, completes the resolution ──────────────────
def test_grafting_the_serving_lets_the_label_determine_the_macros():
    """The graft is the whole point: same validated identity, one missing fact
    filled, and the model's number stops being the answer."""
    from core.food_intelligence import analyze

    without = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                      off_candidate=_exact(123), is_packaged=True)
    assert without.provenance.primary_macro_source == "estimate"
    assert without.calories == 80, "the model's number"

    grafted = dict(_exact(123))
    grafted["serving_text"] = "1 bagel (57 g)"
    with_serving = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                           off_candidate=grafted, is_packaged=True)
    assert with_serving.provenance.primary_macro_source == "branded_exact"
    assert with_serving.calories != 80, "the label's number"
