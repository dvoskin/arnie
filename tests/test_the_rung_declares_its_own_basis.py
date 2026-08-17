"""⭐ P17b — AN EVIDENCE-BACKED RUNG CAN PRICE A SERVING, AND PROVES IT ON
SYNTHETIC EVIDENCE, BEFORE ANY PRODUCER EXISTS.

P17a moved the basis decision out of `price()` and into the rung builders. That
refactor left the suite byte-for-byte identical, which is exactly why it proves
nothing on its own: a `source_basis` that were ignored would also leave the
suite identical. This file is the half that can fail.

⛔⛔ THE DEFECT BEING CLOSED IS AN INVERSION. `price()` used to pick the basis by
asking WHICH RUNG it held — `PerServing` for ESTIMATE, `Per100g` for everything
else. So the one rung with no evidence authority was the only one that could
express a serving, and `ProductEvidence.serving_grams` sat dead in the source:
one occurrence in the whole repository, its own declaration. A count-only
portion was therefore priceable only by GUESSING, which `decide()` correctly
refuses — the 12.6 .. 36.5 recoverable-ownership band P16b measured.

⛔ AND THE TRAP THIS FILE EXISTS TO KEEP SHUT: A BASIS MUST DESCRIBE THE NUMBERS
BESIDE IT, never merely a fact that happens to be true about the food. The first
draft of P17a declared `PerServing(serving_mass_g=55)` over `per100g` numbers,
which reads "these numbers describe one serving" — two bars would have committed
728 kcal against a label that says 400.

⚠ NO PRODUCER IS EXERCISED HERE. Every piece of evidence below is constructed in
the test. That is deliberate: the contract has to be provable independently of
retrieval, or the first producer's bugs and the contract's bugs arrive together.
"""
from __future__ import annotations

import pytest

from core.canonical_pricing import (ArtifactEvidence, EstimateEvidence,
                                    MemoryEvidence, PricingRefused,
                                    ProductEvidence, Rung, price)
from skills.nutrition.models import NormalizedQuantity

#: A label that states its serving and nothing else — the Barebells shape.
BAR = ProductEvidence(
    identifier="off:7340001234567",
    per_serving={"calories": 200.0, "protein": 20.0, "carbs": 16.0, "fat": 6.0},
    serving_grams=55.0, serving_unit="bar")

#: The same product expressed the old way: per 100 g, no serving numbers.
BAR_PER100G = ProductEvidence(
    identifier="off:7340001234567",
    per100g={"calories": 364.0, "protein": 36.0, "carbs": 30.0, "fat": 11.0},
    serving_grams=55.0)

CHICKEN_PER100G = {"calories": 165.0, "protein": 31.0, "carbs": 0.0, "fat": 3.6}


def _g(grams: float) -> NormalizedQuantity:
    return NormalizedQuantity(amount=grams, unit="g", grams=grams)


def _count(n: float, unit: str = "bar", *, fraction: bool = False,
           serving_compatible: bool = True) -> NormalizedQuantity:
    """A count with its BASIS, because a count alone cannot say what it counts.

    `count_basis` is what separates "one bottle of Fairlife" — a discrete unit
    of the product — from "one plate of pasta", which is a container someone
    estimated a mass for. `count_is_serving_compatible` is false for the latter.
    """
    from skills.nutrition.models import (COUNT_BASIS_ESTIMATE,
                                         COUNT_BASIS_UNIT)

    return NormalizedQuantity(
        amount=n, unit=unit, count=float(n), unit_label=unit,
        count_basis=COUNT_BASIS_UNIT if serving_compatible
        else COUNT_BASIS_ESTIMATE,
        unit_is_fraction=fraction)


# ── THE CAPABILITY THAT DID NOT EXIST ───────────────────────────────────────

def test_a_label_that_states_a_serving_prices_a_count_of_servings_exactly():
    """⭐⭐ THE POINT OF THE WHOLE TRANCHE. "1 bar = 200 kcal", user ate 2 bars,
    canonical commits 400 — with no gram conversion anywhere in the path.

    Before P17a this was unreachable: PRODUCT was forced through `Per100g`,
    which needs a mass, and a count-only portion has none.
    """
    priced = price(entity="Barebells bar", consumed=_count(2), product=BAR)

    assert priced.rung is Rung.PRODUCT
    assert priced.calories == pytest.approx(400.0), (
        "two of a 200 kcal serving is 400 kcal — any other number means the "
        "basis did not describe the numbers it was attached to")
    assert priced.protein == pytest.approx(40.0)
    assert priced.basis == "per_serving"


def test_one_serving_is_the_label_unchanged():
    priced = price(entity="Barebells bar", consumed=_count(1), product=BAR)
    assert priced.calories == pytest.approx(200.0)


def test_a_fraction_of_an_evidenced_serving_scales_that_serving():
    """FRACTION never prices alone — it modifies an EVIDENCED parent. Here the
    parent is the label's own bar, so half of it is a defensible 100 kcal."""
    priced = price(entity="Barebells bar", consumed=_count(0.5), product=BAR)
    assert priced.calories == pytest.approx(100.0)


def test_a_gram_portion_still_resolves_against_a_serving_label():
    """The serving mass is a CONVERSION INPUT, and this is the one place it is
    allowed to act: grams stated, serving mass known, so 110 g is two bars."""
    priced = price(entity="Barebells bar", consumed=_g(110.0), product=BAR)
    assert priced.calories == pytest.approx(400.0)


# ── THE TRAP: THE BASIS MUST DESCRIBE THE NUMBERS BESIDE IT ─────────────────

def test_per_100g_numbers_are_never_read_as_a_serving():
    """⛔⛔ THE 728-KCAL BUG, PINNED. Same product, numbers stated per 100 g and
    a serving mass known. Two bars must be 400 kcal via grams — NOT 2 x 364."""
    priced = price(entity="Barebells bar", consumed=_g(110.0),
                   product=BAR_PER100G)
    assert priced.basis == "per_100g"
    assert priced.calories == pytest.approx(400.4, abs=1.0)
    assert priced.calories < 500, (
        "per-100 g numbers were multiplied by a serving count — the basis was "
        "attached to a fact about the food rather than to its numbers")


def test_a_count_against_per_100g_evidence_is_still_refused():
    """⛔ THE P16b BLOCKER IS INTACT, AND MUST BE. P17a did not widen coverage;
    a per-100 g rung still cannot price a bare count, and the honest answer is
    a refusal rather than an invented mass."""
    with pytest.raises(PricingRefused):
        price(entity="Egg", consumed=_count(2, "piece"),
              memory=MemoryEvidence(per100g=CHICKEN_PER100G))


def test_a_piece_of_a_source_with_no_serving_panel_is_refused():
    """The sushi-roll invariant, prod fe#2719: "1 piece" against a source that
    states no panel must not be read as one whole roll. Inherited from the
    scaling engine — asserted here so P17c cannot regress it."""
    no_panel = ProductEvidence(identifier="roll",
                               per_serving={"calories": 460.0})
    with pytest.raises(PricingRefused):
        price(entity="Special roll",
              consumed=_count(1, "piece", fraction=True), product=no_panel)


# ── FAIL CLOSED, NEVER DEFAULT ──────────────────────────────────────────────

def test_a_product_with_no_numbers_fails_closed_rather_than_defaulting():
    """⛔ NO `basis or Per100g()`. A rung with nothing to price is DROPPED and
    the ladder continues; it does not acquire a per-100 g basis over an empty
    dict, because that is how "missing metadata" comes to mean "per 100 g"."""
    empty = ProductEvidence(identifier="off:nothing")
    priced = price(entity="Mystery bar", consumed=_g(55.0), product=empty,
                   estimate=EstimateEvidence(calories=180.0, basis_grams=55.0))
    assert priced.rung is Rung.ESTIMATE, (
        "an evidence-free PRODUCT rung was allowed to win")


def test_a_basis_less_estimate_is_still_not_scaled():
    """The third state survives: no basis means "already a statement about the
    portion", which is NOT the same as per-100 g and must not become it."""
    priced = price(entity="Bowl of pasta", consumed=_g(400.0),
                   estimate=EstimateEvidence(calories=520.0))
    assert priced.calories == pytest.approx(520.0), (
        "a basis-less estimate was rescaled — 520 kcal described the portion "
        "already, and treating it as per-100 g would report 2080")
    assert priced.basis == "per_portion"


# ── THE MUTATION HALF: THE DECLARED BASIS IS LOAD-BEARING ───────────────────

def test_removing_a_declared_basis_changes_the_price(monkeypatch):
    """⚠ ANTI-VACUITY, AND THE REASON THIS FILE EXISTS. If `source_basis` were
    ignored, every assertion above would still pass on a pricer that had
    silently reverted to the old behaviour. So: strip the basis the builder
    declares and require the number to MOVE."""
    import core.canonical_pricing as cp

    before = price(entity="Chicken breast", consumed=_g(200.0),
                   memory=MemoryEvidence(per100g=CHICKEN_PER100G))
    assert before.calories == pytest.approx(330.0)

    real = cp._from_memory
    monkeypatch.setattr(cp, "_from_memory", lambda ev: (*real(ev)[:4], None))
    after = price(entity="Chicken breast", consumed=_g(200.0),
                  memory=MemoryEvidence(per100g=CHICKEN_PER100G))

    assert after.calories != before.calories, (
        "removing the declared basis changed nothing — `source_basis` is "
        "decorative and the pricer is not reading it")
    assert after.calories == pytest.approx(165.0)


def test_swapping_the_serving_basis_for_per_100g_is_caught(monkeypatch):
    """The other direction: force PRODUCT back to a per-100 g basis while its
    numbers stay per serving, and two bars must stop being 400 kcal. This is
    the exact mutation that would re-introduce the 728 defect."""
    import core.canonical_pricing as cp
    from skills.nutrition.scaling import Per100g

    real = cp._from_product
    monkeypatch.setattr(cp, "_from_product",
                        lambda ev: (*real(ev)[:4], Per100g()))
    with pytest.raises(PricingRefused):
        # per-100 g needs a mass; a bare count of bars no longer resolves.
        price(entity="Barebells bar", consumed=_count(2), product=BAR)


# ── WHAT P17c STILL OWES, ASSERTED AS A GAP RATHER THAN ASSUMED ─────────────

def test_a_sourced_piece_to_grams_conversion_is_not_wired_yet():
    """⛔ THE REMAINING HALF OF THE BAND, NAMED. A generic food priced per 100 g
    with a sourced measure ("1 large egg = 50 g") should let "2 eggs" resolve to
    100 g. That is a CONVERSION applied to the CONSUMED quantity, not a basis
    swap on the evidence — declaring `PerUnit` over per-100 g numbers would be
    the 728 bug again.

    ArtifactEvidence carries no conversion today, so this still refuses. The
    test asserts the gap so that closing it is a deliberate, visible change
    rather than something discovered by a coverage number moving.
    """
    with pytest.raises(PricingRefused):
        price(entity="Egg", consumed=_count(2, "piece", serving_compatible=False),
              artifact=ArtifactEvidence(candidates=(
                  {"fdc_id": "1", "description": "Egg, whole, cooked",
                   "per100g": {"calories": 155.0, "protein": 13.0}},)))
