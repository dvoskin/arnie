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
    """A user-stated mass. ⚠ `normalization_source` IS NOT DECORATION: it is what
    marks the mass EXACT rather than assumed, and production always sets it.
    Omitting it here made a stated "100 g" look like a piece-weight guess."""
    return NormalizedQuantity(amount=grams, unit="g", grams=grams,
                              normalization_source="mass_conversion")


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


# ── P17b.1 — A COUNT MUST COUNT THE THING THE EVIDENCE DESCRIBES ────────────
#
# ⛔⛔ THE HOLE THIS CLOSES, FOUND ON REVIEW. P17b declared `serving_unit` and
# then threw it away: `_from_product` built a `PerServing` carrying only a mass,
# and `_factor` asks `count_is_serving_compatible`, which answers about the
# COUNT ALONE and cannot see what the source counts. So a label reading
# "1 bar = 200 kcal" would happily price "2 bottles" at 400.
#
# It also set `as_served=True` on a manufacturer label. That flag means "the
# dish AS SERVED" — a restaurant estimate or a saved regular — and it WIDENS
# `countable`, so it made the mismatch easier rather than harder.

def test_a_count_of_a_different_unit_cannot_multiply_a_serving():
    """⛔⛔ THE BLOCKER. Two BOTTLES against a label that states one BAR."""
    with pytest.raises(PricingRefused):
        price(entity="Barebells bar", consumed=_count(2, "bottle"),
              product=BAR)


def test_a_piece_of_the_bar_is_not_one_bar():
    """⛔ A PART OF THE UNIT IS NOT ONE OF THE UNIT, panel or no panel.

    The older sushi guard only refused a fractional unit when the source stated
    NO panel — so the moment `serving_grams=55` existed, "1 piece of the bar"
    became acceptable. Knowing the whole bar weighs 55 g says nothing about what
    one piece of it weighs.
    """
    with pytest.raises(PricingRefused):
        price(entity="Barebells bar",
              consumed=_count(1, "piece", fraction=True), product=BAR)


def test_a_mass_needs_no_unit_name_because_mass_reconciles_the_bases():
    """⭐ AND THE IDENTITY GATE MUST NOT OVERREACH. 110 g against a 55 g serving
    is two servings by arithmetic — no unit word is involved, so naming the
    portion "bottle" cannot make a gram measurement wrong."""
    priced = price(entity="Barebells bar",
                   consumed=NormalizedQuantity(amount=110, unit="bottle",
                                               grams=110.0),
                   product=BAR)
    assert priced.calories == pytest.approx(400.0)


def test_a_product_stating_two_contradictory_bases_is_refused_at_construction():
    """⛔ ONE RECORD CANNOT HOLD TWO DIFFERENT CLAIMS ABOUT ONE FOOD. Caught
    where a producer would trip it, not where a meal would inherit it."""
    with pytest.raises(ValueError, match="two different claims"):
        ProductEvidence(identifier="off:bad",
                        per_serving={"calories": 200.0},
                        per100g={"calories": 900.0}, serving_grams=55.0)


def test_bases_that_agree_within_panel_rounding_are_accepted():
    """Panels round. 364 kcal/100 g x 55 g = 200.2, and a label saying 200 is
    the same claim, not a contradiction."""
    ProductEvidence(identifier="off:ok", per_serving={"calories": 200.0},
                    per100g={"calories": 364.0}, serving_grams=55.0)


def test_a_basis_with_no_identifier_is_a_loud_bug_not_a_silent_per_portion():
    """⚠ THE PROVENANCE TRAP THE REVIEW CAUGHT. `_basis_name` used to map class
    NAMES, so a basis added to `scaling` would price correctly and then be
    PERSISTED as `per_portion` — corrupting exactly the field a later correction
    reads. It now asks the basis, and an unnamed one raises."""
    import core.canonical_pricing as cp

    class Nameless:
        pass

    assert cp._basis_name(None) == "per_portion"
    with pytest.raises(ValueError, match="declares no"):
        cp._basis_name(Nameless())


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
    monkeypatch.setattr(cp, "_from_memory",
                        lambda ev: (*real(ev)[:4], None, ()))
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
                        lambda ev: (*real(ev)[:4], Per100g(), ()))
    with pytest.raises(PricingRefused):
        # per-100 g needs a mass; a bare count of bars no longer resolves.
        price(entity="Barebells bar", consumed=_count(2), product=BAR)


# ── P17c — THE SOURCED MEASURE, WHICH MOVES THE QUANTITY NOT THE BASIS ──────

def _egg(serving_text="1 large egg", serving_mass_g=50.0):
    """A generic per-100 g artifact record that also states its own measure.

    ⚠ These fields were being FETCHED AND DISCARDED. `api.usda` has extracted
    `serving_text` / `serving_mass_g` all along — with a comment saying they are
    carried so a COUNT portion can be given a mass — and the artifact builder
    dropped all three. Measured before P17c: 0 of 124 committed candidates
    carried a panel.
    """
    return ArtifactEvidence(candidates=(
        {"fdc_id": "1", "description": "Egg, whole, cooked",
         "per100g": {"calories": 155.0, "protein": 13.0},
         "serving_text": serving_text, "serving_mass_g": serving_mass_g},))


def test_a_sourced_measure_gives_a_bare_count_a_mass():
    """⭐⭐ "2 eggs" -> 100 g -> the per-100 g rung scales normally.

    The conversion moves the QUANTITY. The evidence's basis is untouched, which
    is what keeps this from being the 728 bug: `PerUnit` over per-100 g numbers
    would claim they describe ONE EGG and price two eggs at 310.
    """
    priced = price(entity="Egg", consumed=_count(2, "egg"), artifact=_egg())

    assert priced.rung is Rung.ARTIFACT
    assert priced.basis == "per_100g", (
        "the evidence is still per-100 g — a sourced measure must not rewrite "
        "what the numbers describe")
    assert priced.calories == pytest.approx(155.0, abs=1.0), (
        "2 eggs x 50 g = 100 g, and 100 g of a 155 kcal/100 g record is 155")


def test_the_panel_count_is_read_not_assumed():
    """"2 cookies = 30 g" means ONE cookie is 15 g. Reading the mass as
    per-unit would double every portion of a multi-unit panel."""
    cookies = ArtifactEvidence(candidates=(
        {"fdc_id": "9", "description": "Cookie", "per100g": {"calories": 400.0},
         "serving_text": "2 cookies", "serving_mass_g": 30.0},))
    priced = price(entity="Cookie", consumed=_count(2, "cookie"),
                   artifact=cookies)
    assert priced.calories == pytest.approx(120.0, abs=1.0), (
        "2 cookies is 30 g, not 60 g — the panel's own count was ignored")


def test_a_measure_for_a_different_unit_is_refused():
    """⛔⛔ THE SUSHI-ROLL INVARIANT, NOW AT THE CONVERSION LAYER. A measure for
    one whole ROLL may not give a mass to one PIECE of it. Prod fe#2719
    committed 460 cal over the interpreter's own correct 130-190 by exactly
    this substitution."""
    roll = ArtifactEvidence(candidates=(
        {"fdc_id": "7", "description": "Sushi roll",
         "per100g": {"calories": 200.0},
         "serving_text": "1 roll", "serving_mass_g": 230.0},))
    with pytest.raises(PricingRefused):
        price(entity="Special roll", consumed=_count(1, "piece"),
              artifact=roll)


def test_a_record_with_no_panel_still_refuses_a_count():
    """No measure means no conversion. The portion stays exactly as
    unpriceable as it was — the honest outcome, and the one that keeps a
    guessed mass from ever becoming canonical authority."""
    with pytest.raises(PricingRefused):
        price(entity="Egg", consumed=_count(2, "egg"),
              artifact=_egg(serving_text="", serving_mass_g=None))


def test_the_measure_is_a_last_resort_and_cannot_change_a_priced_meal():
    """⭐ THE SAFETY PROPERTY. The conversion is consulted ONLY after the scaler
    has already refused, so a portion that priced before must price identically
    now. This is what makes P17c incapable of moving an existing number."""
    with_panel = price(entity="Egg", consumed=_g(100.0), artifact=_egg())
    without = price(entity="Egg", consumed=_g(100.0),
                    artifact=_egg(serving_text="", serving_mass_g=None))
    assert with_panel.calories == without.calories == pytest.approx(155.0)


# ── P17c.1 — ONE RESOLVER, AND A CANONICAL CONVERSION ───────────────────────

def test_a_sourced_measure_becomes_a_canonical_basis_conversion():
    """⭐ THE ADAPTER SHAPE TRANSLATES INTO THE CONTRACT THAT ALREADY EXISTS.
    `SourcedMeasure` is what a provider hands over; `BasisConversion` is what
    the repository already defines for "this basis became that one, and here is
    what licensed it". P17 must not grow a second conversion vocabulary."""
    from skills.nutrition.scaling import SourcedMeasure

    measure = SourcedMeasure(
        unit_text="large egg", grams_per_unit=50.0, source_id="usda:173423",
        dataset_id="usda_fdc", dataset_version="2025-04", record_key="173423",
        record_version="sr-legacy-1", immutable_within_version=True)
    conversion = measure.as_basis_conversion()

    assert conversion is not None
    assert float(conversion.factor) == 50.0
    assert conversion.source.record_key == "173423"
    assert conversion.from_basis.value == "count"
    assert conversion.to_basis.value == "mass"


def test_a_measure_without_provenance_licenses_no_conversion():
    """⛔ AND IT MUST NOT FABRICATE ONE. `BasisConversion` refuses a cross-basis
    factor with no source — "an unsourced factor is an invented density" — so a
    measure lacking provenance yields None rather than a conversion that cites
    nothing."""
    from skills.nutrition.scaling import SourcedMeasure

    assert SourcedMeasure(unit_text="bar",
                          grams_per_unit=55.0).as_basis_conversion() is None


def test_can_scale_never_disagrees_with_what_pricing_does():
    """⛔⛔ THE P17g GUARANTEE, ASSERTED BEFORE P17g EXISTS.

    The predicate will ask `can_scale`; the pricer acts on `resolve_scaling`.
    If those could differ, coverage would promise a meal pricing then refuses —
    the drift the blunt `has_mass` rule was written to prevent. They are one
    call, and this keeps them so.
    """
    from core.canonical_pricing import _candidate_measures
    from skills.nutrition.scaling import Per100g, can_scale

    egg = _egg()
    measures = _candidate_measures({"fdc_id": "1", "serving_text": "1 large egg",
                                    "serving_mass_g": 50.0})

    for portion, expected in ((_count(2, "egg"), True),
                              (_count(2, "bottle"), False),
                              (_g(100.0), True),
                              (_count(1, "piece", fraction=True), False)):
        mechanical = can_scale(Per100g(), portion, measures,
                               authoritative_only=False)
        try:
            price(entity="Egg", consumed=portion, artifact=egg)
            priced = True
        except PricingRefused:
            priced = False
        assert mechanical == priced == expected, (
            f"can_scale said {mechanical} and pricing said {priced} for "
            f"{portion.unit!r} — the predicate and the pricer must not be able "
            f"to hold different views of scalability")


def test_authoritative_eligibility_is_stricter_than_mere_scalability():
    """⭐⭐ P17c.2 — NORMALIZATION MAY ESTIMATE WHAT THE USER PROBABLY MEANT; IT
    MAY NOT OUTRANK EVIDENCE WHEN CANONICAL OWNERSHIP IS DECIDED.

    A heuristic piece-weight mass still SCALES — an estimate may use it — and it
    must never make canonical eligibility true. So the two questions separate.
    """
    from skills.nutrition.models import COUNT_BASIS_UNIT
    from skills.nutrition.scaling import Per100g, can_scale, resolve_scaling

    heuristic = NormalizedQuantity(
        amount=2, unit="eggs", count=2.0, unit_label="2 eggs", grams=100.0,
        count_basis=COUNT_BASIS_UNIT, normalization_source="piece_weight")

    assert can_scale(Per100g(), heuristic, (), authoritative_only=False), (
        "a heuristic mass must still be usable — an estimate may price on it")
    assert not can_scale(Per100g(), heuristic, ()), (
        "a piece-weight table granted canonical eligibility — that is the "
        "assumption layer outranking the evidence layer")
    assert resolve_scaling(Per100g(), heuristic, ()).path == \
        "heuristic:piece_weight"


def test_an_unsourced_measure_cannot_grant_canonical_authority():
    """⛔ AN UNSOURCED FACTOR IS AN INVENTED DENSITY. It may still produce a
    number; it may never settle a canonical rung."""
    from skills.nutrition.models import COUNT_BASIS_UNIT
    from skills.nutrition.scaling import (Per100g, SourcedMeasure, can_scale,
                                          resolve_scaling)

    portion = NormalizedQuantity(amount=2, unit="egg", count=2.0,
                                 unit_label="2 eggs",
                                 count_basis=COUNT_BASIS_UNIT)
    unsourced = (SourcedMeasure(unit_text="egg", grams_per_unit=50.0),)
    sourced = (SourcedMeasure(unit_text="egg", grams_per_unit=50.0,
                              dataset_id="usda_fdc", dataset_version="2025-04",
                              record_key="173423",
                              immutable_within_version=True),)

    assert resolve_scaling(Per100g(), portion, unsourced).resolved_grams == 100.0
    assert not can_scale(Per100g(), portion, unsourced)
    assert can_scale(Per100g(), portion, sourced)


def test_the_sourced_measure_is_load_bearing(monkeypatch):
    """⚠ ANTI-VACUITY for P17c: disable the conversion and "2 eggs" must go
    back to being unpriceable. Otherwise the assertions above would pass on a
    build where the panel was still being dropped.

    ⚠ AND THE SEAM MOVED ONCE ALREADY. This patched
    `canonical_pricing.mass_from_measures` until P17c.1 moved the resolver into
    `scaling`, and then `scaling.mass_from_measures` until P17c.2 made the
    resolver call `_matching_measure` directly. BOTH TIMES the mutation went
    inert and this test went RED, which is the anti-vacuity check doing exactly
    its job on code that moved out from under it.
    """
    import skills.nutrition.scaling as sc

    assert price(entity="Egg", consumed=_count(2, "egg"),
                 artifact=_egg()).calories > 0
    monkeypatch.setattr(sc, "_matching_measure", lambda *a, **k: None)
    with pytest.raises(PricingRefused):
        price(entity="Egg", consumed=_count(2, "egg"), artifact=_egg())


# ── P17c.2 — DRIVEN THROUGH THE REAL NORMALIZER, NOT A HAND-BUILT SHAPE ─────
#
# ⛔⛔ EVERY TEST ABOVE CONSTRUCTS ITS OWN `NormalizedQuantity`, AND THAT HID THE
# SEAM THAT DECIDES THIS TRANCHE. Production normalization of "2 eggs" already
# returns grams=100 from a PIECE-WEIGHT TABLE and stores the raw wording in
# `unit_label`. Under the original ordering `_factor` succeeded on that heuristic
# mass immediately, so the USDA conversion was never consulted and P17 would have
# been DECORATIVE on exactly the foods it was built for.

def _sourced(grams_per_unit: float, unit_text: str = "large egg"):
    from skills.nutrition.scaling import SourcedMeasure
    return (SourcedMeasure(unit_text=unit_text, grams_per_unit=grams_per_unit,
                           source_id="usda:173423", dataset_id="usda_fdc",
                           dataset_version="2025-04", record_key="173423",
                           immutable_within_version=True),)


def test_production_normalization_of_two_eggs_is_a_heuristic_mass():
    """The premise, executed rather than assumed."""
    from skills.nutrition.normalize import normalize_quantity

    q = normalize_quantity("2 eggs", "Egg")
    assert q.grams == pytest.approx(100.0)
    assert q.normalization_source == "piece_weight"
    assert not q.mass_is_exact
    assert q.unit_label == "2 eggs", (
        "unit_label holds the user's RAW WORDING — matching a source unit "
        "against it asks whether '2 eggs' is the same unit as 'large egg'")


def test_a_sourced_conversion_outranks_the_piece_weight_prior():
    """⭐⭐ THE TRANCHE'S REASON FOR EXISTING. Not because the numbers differ —
    here they would not — but because one is EVIDENCE and one is an ASSUMPTION."""
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, resolve_scaling

    resolution = resolve_scaling(Per100g(), normalize_quantity("2 eggs", "Egg"),
                                 _sourced(50.0))
    assert resolution.path == "sourced_conversion"
    assert resolution.resolved_grams == pytest.approx(100.0)
    assert resolution.authoritative
    assert resolution.conversion is not None


def test_when_the_source_disagrees_with_the_prior_the_source_wins():
    """⛔⛔ IF THIS RETURNS 100 g, P17 IS DECORATIVE. USDA says 56 g/egg; the
    piece-weight table says 50. Two eggs is 112 g, not 100."""
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, resolve_scaling

    resolution = resolve_scaling(Per100g(), normalize_quantity("2 eggs", "Egg"),
                                 _sourced(56.0))
    assert resolution.resolved_grams == pytest.approx(112.0), (
        "the heuristic 100 g won over a sourced 112 g — normalization outranked "
        "evidence, which is the precedence this tranche exists to invert")
    assert resolution.factor == pytest.approx(1.12)


def test_a_user_stated_mass_is_never_reinterpreted_by_a_source():
    """⛔ PRECEDENCE 1. The user measured it. A per-unit conversion may not
    second-guess a quantity they stated outright."""
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, resolve_scaling

    q = normalize_quantity("100 g", "Egg")
    assert q.mass_is_exact
    resolution = resolve_scaling(Per100g(), q, _sourced(56.0))
    assert resolution.path == "user_stated_exact"
    assert resolution.resolved_grams is None
    assert resolution.factor == pytest.approx(1.0)


# ── P17c.3a — SOURCE SNAPSHOT IDENTITY, BEFORE ANY DURABLE RECORD EXISTS ────
#
# ⛔⛔ THE PLACEHOLDER THAT WAS ALMOST BAKED IN. `dataset_version` defaulted to
# the literal "committed_artifact", and that string would have been stamped into
# 259 durable conversion records as the version a later correction CITES — while
# also asserting `immutable_within_version=True` about a version nobody had
# identified. Fixing it after hydration would have been a data migration; today
# it is a dark-path edit.

def _measure(**over):
    from skills.nutrition.scaling import SourcedMeasure
    base = dict(unit_text="large egg", grams_per_unit=50.0,
                source_id="usda:173423", dataset_id="usda_fdc",
                dataset_version="15.3", record_key="173423#portion:83012",
                record_version="4/1/2019", data_type="SR Legacy",
                source_fingerprint="abc123", immutable_within_version=True)
    base.update(over)
    return SourcedMeasure(**base)


def test_a_measure_with_no_release_version_is_not_authoritative():
    """⛔ FAIL CLOSED. A source whose VERSION was never identified cannot
    license a conversion, because claiming immutability about an unnamed
    version is the weakest possible link in an audit trail."""
    assert _measure(dataset_version="").as_basis_conversion() is None
    assert _measure().as_basis_conversion() is not None


def test_the_same_record_under_two_releases_is_two_distinguishable_sources():
    """⭐⭐ THE POINT OF A SNAPSHOT IDENTITY. USDA serves the CURRENT database
    and its data types move at different cadences, so `fdc_id + usda_fdc` names
    a moving target. Two releases of one record must not collapse into one
    citation — otherwise a correction six months later cannot tell which facts
    were actually committed."""
    old = _measure(dataset_version="15.2").as_basis_conversion()
    new = _measure(dataset_version="15.3").as_basis_conversion()

    assert old.source != new.source, (
        "two FDC releases of the same record produced one SourceReference — "
        "the snapshot is not part of the identity")
    assert old.source.dataset_version == "15.2"
    assert new.source.dataset_version == "15.3"
    assert old.source.record_key == new.source.record_key


def test_the_portion_id_makes_the_record_key_exact():
    """An fdc_id names a FOOD; a food states several portions. "1 large" is not
    "1 cup", so the conversion cites the portion it actually used."""
    conversion = _measure().as_basis_conversion()
    assert conversion.source.record_key == "173423#portion:83012"


def test_a_differing_fingerprint_marks_differing_committed_facts():
    """The fingerprint pins the FACTS, not the id — what a later reprice must
    be able to reproduce."""
    assert _measure(source_fingerprint="aaa") != _measure(
        source_fingerprint="bbb")


# ── P17c.3b — THE IMPLICIT SUBJECT, FOUND END-TO-END AGAINST THE HYDRATED
# ARTIFACT, NOT IN REVIEW ───────────────────────────────────────────────────
#
# ⛔⛔ USDA STATES THE EGG PORTION AS `modifier="large"` WITH
# `measureUnit="undetermined"` — a bare SIZE, no entity noun, because the
# subject is the record itself. So `unit_matches("eggs", "large")` failed, the
# sourced conversion never fired, and "2 eggs" — THE TRANCHE'S NAMESAKE —
# silently fell to the piece-weight heuristic with authoritative=False. Every
# synthetic panel had said "large egg"; only the committed artifact said
# "large".

def _fried_egg_measures():
    from core.canonical_pricing import _candidate_measures
    return _candidate_measures({
        "fdc_id": "173423", "description": "Egg, whole, cooked, fried",
        "dataset_version": "15.3",
        "measures": [{"unit_text": "large", "amount": 1.0, "grams": 46.0,
                      "portion_id": 92497, "data_type": "SR Legacy",
                      "publication_date": "4/1/2019",
                      "dataset_version": "15.3", "fingerprint": "cc14"}]})


def test_a_bare_size_measure_inherits_the_records_subject():
    """"large" on an egg record means "large EGG", and real "2 eggs" must reach
    it: sourced, authoritative, 92 g — not the piece-weight prior's 100."""
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, resolve_scaling

    r = resolve_scaling(Per100g(), normalize_quantity("2 eggs", "Egg"),
                        _fried_egg_measures())
    assert r.path == "sourced_conversion"
    assert r.authoritative
    assert r.resolved_grams == pytest.approx(92.0)


def test_a_stated_size_matching_the_measure_binds_to_it():
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, resolve_scaling

    r = resolve_scaling(Per100g(), normalize_quantity("3 large eggs", "Egg"),
                        _fried_egg_measures())
    assert r.resolved_grams == pytest.approx(138.0), (
        "3 large eggs is 3 x 46 g by USDA's own measure — the heuristic table "
        "said 67.5 g/egg, a 32% error the source exists to correct")


def test_a_stated_size_conflicting_with_the_measure_does_not_bind():
    """⛔ "2 medium eggs" shares the token "egg" with the large-egg measure, and
    binding would price medium eggs while citing a record about large ones. It
    falls to the heuristic and is NOT canonically eligible."""
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, resolve_scaling

    r = resolve_scaling(Per100g(), normalize_quantity("2 medium eggs", "Egg"),
                        _fried_egg_measures())
    assert r.path.startswith("heuristic:")
    assert not r.authoritative


def test_the_subject_is_never_appended_to_a_real_unit_noun():
    """⛔ THE OVERREACH GUARD. An "oz" measure on a salmon record must not
    become "oz salmon" — or "2 salmon" would price two salmon at 56 grams."""
    from core.canonical_pricing import _candidate_measures
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import Per100g, ScalingRefused, resolve_scaling

    measures = _candidate_measures({
        "fdc_id": "175168", "description": "Salmon, sockeye, cooked",
        "dataset_version": "15.3",
        "measures": [{"unit_text": "oz", "amount": 1.0, "grams": 28.35,
                      "portion_id": 1, "dataset_version": "15.3"}]})
    assert all("salmon" not in m.unit_text for m in measures)
    with pytest.raises(ScalingRefused):
        resolve_scaling(Per100g(), normalize_quantity("2 salmon", "Salmon"),
                        measures)


# ── P17e — PACKAGE + FRACTION, THROUGH THE BASIS'S OWN DATA ─────────────────
#
# ⭐ Package/fraction describes CONSUMPTION; it never establishes nutrition
# authority. PRODUCT nutrition + a stated package relation + a consumed
# fraction = a priceable amount. "half bottle" of a bottle whose size nobody
# stated remains unpriceable, exactly as before.

#: A label: 120 kcal per serving (a "scoop"), 2 servings per bottle.
TUB = ProductEvidence(
    identifier="off:900123", per_serving={"calories": 120.0, "protein": 26.0},
    serving_unit="scoop", package_unit="bottle", servings_per_package=2.0)


def test_a_count_of_packages_multiplies_by_the_stated_relation():
    """1 bottle = 2 servings = 240 kcal — the field P17b carried as inert
    metadata is now load-bearing data on the basis."""
    priced = price(entity="Core Power", consumed=_count(1, "bottle"),
                   product=TUB)
    assert priced.calories == pytest.approx(240.0)
    assert priced.basis == "per_serving"


def test_a_fraction_of_a_package_is_a_fraction_of_the_relation():
    """half bottle -> 0.5 x 2 servings = 120 kcal."""
    priced = price(entity="Core Power", consumed=_count(0.5, "bottle"),
                   product=TUB)
    assert priced.calories == pytest.approx(120.0)


def test_a_count_of_servings_still_prices_directly():
    """The serving path is untouched by the package path: 2 scoops = 240."""
    priced = price(entity="Core Power", consumed=_count(2, "scoop"),
                   product=TUB)
    assert priced.calories == pytest.approx(240.0)


def test_a_package_count_with_no_stated_relation_is_refused():
    """⛔ ONE PACKAGE = ONE SERVING IS A FACT, NOT A DEFAULT. A source that
    names the package but not how many servings it holds REFUSES — assuming
    parity would silently halve every multi-serving bottle."""
    unstated = ProductEvidence(
        identifier="off:900124", per_serving={"calories": 120.0},
        serving_unit="scoop", package_unit="bottle")
    with pytest.raises(PricingRefused):
        price(entity="Core Power", consumed=_count(1, "bottle"),
              product=unstated)


def test_a_count_of_neither_unit_is_still_refused():
    """The identity gates compose: "2 cans" is neither the scoop nor the
    bottle, and the package path must not have loosened anything."""
    with pytest.raises(PricingRefused):
        price(entity="Core Power", consumed=_count(2, "can"), product=TUB)


def test_the_package_relation_derives_only_from_agreeing_units():
    """⭐ PROBED ON COCA-COLA: product_quantity 355 ml beside a 354.882 ml
    serving -> spp 1.0003, sourced arithmetic from one record. A package in ml
    against a serving in g derives NOTHING — that would be a density guess."""
    from skills.nutrition.off import product_evidence_from_off

    can = {"code": "0049000042566", "product_quantity": 355,
           "product_quantity_unit": "ml", "serving_quantity": 354.882,
           "serving_quantity_unit": "ml", "rev": 155,
           "last_modified_t": 1786673920, "nutrition_data_per": "100g",
           "nutriments": {"energy-kcal_100g": 0.5, "proteins_100g": 0.0,
                          "carbohydrates_100g": 0.1, "fat_100g": 0.0,
                          "energy-kcal_serving": 1.0, "proteins_serving": 0.0,
                          "carbohydrates_serving": 0.4, "fat_serving": 0.0}}
    ev = product_evidence_from_off(can, serving_unit="serving",
                                   package_unit="can")
    assert ev.servings_per_package == pytest.approx(1.0003, abs=1e-3)

    mixed = dict(can, product_quantity_unit="g")
    assert product_evidence_from_off(
        mixed, serving_unit="serving").servings_per_package is None


def test_the_package_path_is_data_not_a_branch(monkeypatch):
    """⚠ ANTI-VACUITY: blank the relation on the SAME basis and the same
    portion must refuse — proving the multiplication came from the data, not
    from anything shaped like a product-specific branch."""
    import dataclasses

    from core.canonical_pricing import _from_product
    import core.canonical_pricing as cp

    real = _from_product
    def _stripped(ev):
        out = real(ev)
        basis = dataclasses.replace(out[5 - 1], servings_per_package=None)
        return (*out[:4], basis, out[5])
    monkeypatch.setattr(cp, "_from_product", _stripped)
    with pytest.raises(PricingRefused):
        price(entity="Core Power", consumed=_count(1, "bottle"), product=TUB)
