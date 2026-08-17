"""⭐ P17d — OFF IS A PRODUCT PRODUCER, NEVER A PRODUCT RUNG.

§P17-SA, frozen before this producer existed: an OFF record may produce PRODUCT
evidence ONLY when exact product identity is mechanically established. Provider
match labels, string similarity and model confidence establish nothing — OFF
once called an unrelated chicken pizza `_match: "exact"`.

⭐ THE ENVELOPE BELOW IS THE PROBED ONE, NOT AN IMAGINED ONE. Fetched live
2026-08-17, code 70004199: serving stated as a MASS ('55.0g'), NO unit noun
anywhere in the record, `rev` + `last_modified_t` as the only versioning — and
the content itself wrong (200 kcal/100 g for a ~364 kcal/100 g bar; per-bar
values entered as per-100 g, internally consistent so reconciliation passes).
Identity is mechanical; content is crowd-sourced.
"""
from __future__ import annotations

import pytest

from core.canonical_pricing import PricingRefused, Rung, price
from skills.nutrition.models import COUNT_BASIS_UNIT, NormalizedQuantity
from skills.nutrition.off import fetch_product, product_evidence_from_off

#: The live envelope, verbatim shape. Numbers per the record — wrong about the
#: bar, consistent with themselves, which is exactly the point.
BAREBELLS = {
    "code": "70004199",
    "product_name": "Barebell salty peanut protein bar",
    "brands": "Barebell",
    "serving_size": "55.0g",
    "serving_quantity": 55,
    "rev": 1,
    "last_modified_t": 1724712330,
    "nutrition_data_per": "100g",
    "nutriments": {
        "energy-kcal_100g": 200, "proteins_100g": 20,
        "carbohydrates_100g": 18, "fat_100g": 7.3,
        "energy-kcal_serving": 110, "proteins_serving": 11,
        "carbohydrates_serving": 9.9, "fat_serving": 4,
    },
}


def _count(n, unit):
    return NormalizedQuantity(amount=n, unit=unit, count=float(n),
                              unit_label=unit, count_basis=COUNT_BASIS_UNIT)


def test_an_exact_record_with_a_caller_supplied_unit_prices_counts():
    """The full capability: identity from the barcode, unit noun from the
    caller (a binding step — OFF itself names none), counts identity-gated."""
    ev = product_evidence_from_off(BAREBELLS, serving_unit="bar")
    assert ev is not None and ev.identifier == "off:70004199"
    assert ev.source_id == "off:70004199#rev:1@1724712330", (
        "OFF has no releases — rev + last_modified_t ARE the record version, "
        "and dropping them leaves a citation to a moving target")

    priced = price(entity="Barebells bar", consumed=_count(2, "bar"),
                   product=ev)
    assert priced.rung is Rung.PRODUCT
    assert priced.calories == pytest.approx(220.0)  # 2 x the record's serving
    with pytest.raises(PricingRefused):
        price(entity="Barebells bar", consumed=_count(2, "bottle"), product=ev)


def test_without_a_unit_noun_the_capability_narrows_rather_than_ungates():
    """⛔⛔ THE HOLE THIS REFUSES TO REOPEN. OFF states no unit noun, and a
    per-serving basis with an empty unit_id would let "2 bottles" multiply a
    bar label — the exact P17b.1 blocker. So without a unit the producer emits
    per-100 g + the serving mass as a CONVERSION INPUT: gram portions price,
    bare counts do not."""
    ev = product_evidence_from_off(BAREBELLS)
    assert ev.per_serving is None and ev.per100g is not None
    assert ev.serving_grams == pytest.approx(55.0)

    priced = price(entity="Barebells bar",
                   consumed=NormalizedQuantity(amount=110, unit="g",
                                               grams=110.0), product=ev)
    assert priced.calories == pytest.approx(220.0)  # 110 g via per-100 g
    with pytest.raises(PricingRefused):
        price(entity="Barebells bar", consumed=_count(2, "bar"), product=ev)


def test_a_record_without_its_code_produces_nothing():
    """⛔ A name-search hit stripped of its barcode is the fuzzy input §P17-SA
    forbids, whatever else it contains."""
    stripped = {k: v for k, v in BAREBELLS.items() if k != "code"}
    assert product_evidence_from_off(stripped, serving_unit="bar") is None


def test_a_millilitre_serving_never_becomes_grams():
    """⛔ 240 ml is not 240 g — that equality is a density assumption wearing a
    unit, and the serving mass stays None for a drink."""
    drink = dict(BAREBELLS, serving_size="240 ml", serving_quantity=240)
    ev = product_evidence_from_off(drink)
    assert ev.serving_grams is None


def test_a_self_contradictory_record_is_refused_not_raised():
    """⛔ Crowd data WILL contradict itself; the producer answers 'no evidence
    from this record' rather than crashing acquisition."""
    bad = dict(BAREBELLS)
    bad["nutriments"] = dict(BAREBELLS["nutriments"],
                             **{"energy-kcal_serving": 300})  # vs 200*0.55=110
    assert product_evidence_from_off(bad, serving_unit="bar") is None


@pytest.mark.asyncio
async def test_fetch_refuses_an_identity_swap(monkeypatch):
    """⛔ The identity handed back must be the identity asked for. A redirect
    returning a DIFFERENT code would bind evidence to the wrong product with a
    mechanically-clean-looking citation."""
    import skills.nutrition.off as off_mod

    async def _swapped(url, params, **kw):
        return {"status": 1, "product": dict(BAREBELLS, code="9999999999")}
    monkeypatch.setattr(off_mod, "_get_json", _swapped)
    assert await fetch_product("70004199") is None


@pytest.mark.asyncio
async def test_fetch_requires_something_barcode_shaped(monkeypatch):
    import skills.nutrition.off as off_mod

    async def _boom(*a, **kw):                            # pragma: no cover
        raise AssertionError("fetch_product hit the network for a non-barcode")
    monkeypatch.setattr(off_mod, "_get_json", _boom)
    assert await fetch_product("") is None
    assert await fetch_product("bar") is None


# ── P17d.0 FINDINGS, PINNED — codified from observation, not designed ────────

@pytest.mark.asyncio
async def test_offs_own_canonical_zero_form_is_accepted(monkeypatch):
    """⭐ PROBED: OFF resolves equivalent UPC-A/EAN-13 forms to ITS stored
    canonical code, BOTH directions (070004199 -> '70004199'; 049000042566 ->
    '0049000042566'). Exact digit-string comparison — the first draft's guard —
    would refuse correct responses."""
    import skills.nutrition.off as off_mod

    async def _zero_added(url, params, **kw):
        return {"status": 1, "product": dict(BAREBELLS, code="0070004199")}
    monkeypatch.setattr(off_mod, "_get_json", _zero_added)
    assert await fetch_product("70004199") is not None

    async def _zero_stripped(url, params, **kw):
        return {"status": 1, "product": dict(BAREBELLS, code="70004199")}
    monkeypatch.setattr(off_mod, "_get_json", _zero_stripped)
    assert await fetch_product("0070004199") is not None


@pytest.mark.asyncio
async def test_zero_insensitivity_is_not_looseness(monkeypatch):
    """⛔ The equivalence is leading zeros and NOTHING ELSE — a different code
    with the same tail is still a swap, and all-zeros matches nothing."""
    import skills.nutrition.off as off_mod

    async def _different(url, params, **kw):
        return {"status": 1, "product": dict(BAREBELLS, code="170004199")}
    monkeypatch.setattr(off_mod, "_get_json", _different)
    assert await fetch_product("70004199") is None


def test_a_per_100ml_record_makes_no_per_100g_claim():
    """⛔⛔ PROBED ON FAIRLIFE: `nutrition_data_per='100ml'`, and the *_100g
    nutriment keys then hold PER-100-ML values. Reading them as Per100g is the
    mislabel class that priced a tablespoon of oil at 131 kcal. The per-serving
    panel still stands — a serving is a serving."""
    drink = dict(BAREBELLS, nutrition_data_per="100ml",
                 serving_size="240 ml", serving_quantity=240,
                 serving_quantity_unit="ml")
    ev = product_evidence_from_off(drink, serving_unit="bottle")
    assert ev is not None
    assert ev.per100g is None, (
        "per-100-ml numbers were published as per-100-g — a basis lie")
    assert ev.per_serving is not None
    assert ev.serving_grams is None


def test_the_explicit_serving_unit_field_decides_grams():
    """PROBED: `serving_quantity_unit` states 'g' or 'ml' outright; the text
    form is only a fallback."""
    ev = product_evidence_from_off(dict(BAREBELLS, serving_quantity_unit="g"))
    assert ev.serving_grams == pytest.approx(55.0)
    ml = dict(BAREBELLS, serving_quantity_unit="ml", serving_size="55 ml")
    assert product_evidence_from_off(ml).serving_grams is None
