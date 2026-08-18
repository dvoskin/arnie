"""⭐ P17-UA — WHAT "BAR" MEANS FOR ONE EXACT BARCODE IS EVIDENCE, NEVER A GUESS
*(Danny, 2026-08-18)*.

The snapshot knows `1 serving = 55 g`. It must not invent `1 bar = 1 serving`.
That second equality is a fact only when EVIDENCE establishes it, keyed to the
exact snapshot it is about:

    manufacturer_label / catalog_serving_text   "1 bar (55 g)"
    package_facts                               quantity "1 bar" & 55 g == 55 g
    user_confirmed                              this consumption only

Then pricing is mechanical: 2 bars x 1 serving/bar x 55 g/serving = 110 g,
every edge sourced. OFF 70004199 as it really is ("55.0g", no quantity) yields
NO alias — and "2 bars" against it still refuses. That negative is the point.
"""
from __future__ import annotations

import pytest

PROD_70004199 = {
    "code": "70004199", "product_name": "Barebell salty peanut protein bar",
    "brands": "Barebell", "serving_size": "55.0g", "serving_quantity": "55",
    "serving_quantity_unit": "g", "rev": 1, "last_modified_t": 1724712330,
    "nutrition_data_per": "100g",
    "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                   "carbohydrates_100g": 18, "fat_100g": 8}}

LABELLED = dict(PROD_70004199, code="70004200", serving_size="1 bar (55 g)")
PACKAGED = dict(PROD_70004199, code="70004201", quantity="1 bar",
                product_quantity="55", product_quantity_unit="g")


# ── the producer: sources 2/3 from the record ALONE, deterministically ──────

def test_the_real_off_record_yields_no_alias():
    from skills.nutrition.off import consumer_unit_alias_from_off
    assert consumer_unit_alias_from_off(PROD_70004199) is None


def test_structured_serving_text_names_the_unit():
    from skills.nutrition.off import consumer_unit_alias_from_off
    unit, ups, prov, ref = consumer_unit_alias_from_off(LABELLED)
    assert (unit, ups, prov) == ("bar", 1.0, "catalog_serving_text")
    assert ref["text"] == "1 bar (55 g)"
    unit, ups, prov, _ = consumer_unit_alias_from_off(
        dict(LABELLED, serving_size="2 cookies (30 g)", serving_quantity="30"))
    assert (unit, ups, prov) == ("cookie", 2.0, "catalog_serving_text")


def test_package_facts_name_the_unit_only_when_the_masses_agree():
    from skills.nutrition.off import consumer_unit_alias_from_off
    unit, ups, prov, ref = consumer_unit_alias_from_off(PACKAGED)
    assert (unit, ups, prov) == ("bar", 1.0, "package_facts")
    # a 110 g package with a 55 g serving is TWO servings — no 1:1 alias
    assert consumer_unit_alias_from_off(dict(PACKAGED, product_quantity="110")) is None
    # a mass word is never a consumer unit
    assert consumer_unit_alias_from_off(dict(PACKAGED, quantity="55 g")) is None
    assert consumer_unit_alias_from_off(dict(LABELLED, serving_size="1 serving (55 g)")) is None


# ── the store: append-only, provenance-typed, scope-honest ───────────────────

@pytest.mark.asyncio
async def test_unit_evidence_is_append_only_typed_and_a_confirmation_is_never_global(db):
    from skills.nutrition.product_store import (append_product_evidence,
                                                append_unit_evidence,
                                                unit_aliases_for)
    snap = await append_product_evidence(db, record=dict(PROD_70004199))
    a = await append_unit_evidence(db, product_evidence_id=snap.id, consumer_unit="bar",
                                   units_per_serving=1, provenance="catalog_serving_text",
                                   source_reference={"text": "1 bar (55 g)"})
    again = await append_unit_evidence(db, product_evidence_id=snap.id, consumer_unit="bar",
                                       units_per_serving=1, provenance="catalog_serving_text",
                                       source_reference={"text": "1 bar (55 g)"})
    assert again.id == a.id, "the same fact must land on the same row"
    with pytest.raises(ValueError):
        await append_unit_evidence(db, product_evidence_id=snap.id, consumer_unit="bar",
                                   units_per_serving=1, provenance="vibes",
                                   source_reference={})
    with pytest.raises(ValueError):          # a mass word is not a consumer unit
        await append_unit_evidence(db, product_evidence_id=snap.id, consumer_unit="g",
                                   units_per_serving=1, provenance="package_facts",
                                   source_reference={})
    with pytest.raises(ValueError):          # a confirmation is consumption-scoped, named
        await append_unit_evidence(db, product_evidence_id=snap.id, consumer_unit="bar",
                                   units_per_serving=1, provenance="user_confirmed",
                                   source_reference={}, scope="snapshot")
    conf = await append_unit_evidence(db, product_evidence_id=snap.id, consumer_unit="bar",
                                      units_per_serving=1, provenance="user_confirmed",
                                      source_reference={"turn": "t1"}, scope="consumption",
                                      user_id=7, entry_id=99)
    await db.commit()
    # snapshot scope only, by default: the confirmation is NOT a product fact
    assert [x.evidence_id for x in await unit_aliases_for(db, snap.id)] == [a.id]
    # the confirmation appears ONLY for its user AND entry
    both = await unit_aliases_for(db, snap.id, user_id=7, entry_id=99)
    assert sorted(x.evidence_id for x in both) == sorted([a.id, conf.id])
    assert [x.evidence_id for x in await unit_aliases_for(db, snap.id, user_id=7, entry_id=100)] == [a.id]
    assert [x.evidence_id for x in await unit_aliases_for(db, snap.id, user_id=8, entry_id=99)] == [a.id]


# ── acquisition persists the alias beside the snapshot; settlement loads it ──

@pytest.mark.asyncio
async def test_acquisition_enriches_a_labelled_record_and_not_the_bare_one(db, monkeypatch):
    import skills.nutrition.off as off_mod
    from skills.nutrition.product_acquisition import acquire_product_evidence
    from skills.nutrition.product_store import load_product_evidence

    async def fetch_labelled(code):
        return dict(LABELLED)
    monkeypatch.setattr(off_mod, "fetch_product", fetch_labelled)
    sid = await acquire_product_evidence(db, "70004200")
    ev = await load_product_evidence(db, sid)
    assert [(a.unit, a.units_per_serving, a.provenance) for a in ev.unit_aliases] == \
        [("bar", 1.0, "catalog_serving_text")]

    async def fetch_bare(code):
        return dict(PROD_70004199)
    monkeypatch.setattr(off_mod, "fetch_product", fetch_bare)
    sid2 = await acquire_product_evidence(db, "70004199")
    ev2 = await load_product_evidence(db, sid2)
    assert ev2.unit_aliases == ()


# ── the pricer: an alias is a SOURCED conversion; no alias, no "bar" ────────

@pytest.mark.asyncio
async def test_two_bars_price_mechanically_with_an_alias_and_refuse_without(db, monkeypatch):
    import skills.nutrition.off as off_mod
    from core.canonical_pricing import PricingRefused, price
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.product_acquisition import acquire_product_evidence
    from skills.nutrition.product_store import load_product_evidence

    async def fetch_labelled(code): return dict(LABELLED)
    monkeypatch.setattr(off_mod, "fetch_product", fetch_labelled)
    with_alias = await load_product_evidence(db, await acquire_product_evidence(db, "70004200"))
    async def fetch_bare(code): return dict(PROD_70004199)
    monkeypatch.setattr(off_mod, "fetch_product", fetch_bare)
    without = await load_product_evidence(db, await acquire_product_evidence(db, "70004199"))

    two_bars = normalize_quantity("2 bars", "Barebell salty peanut protein bar")
    priced = price(entity="Barebell", consumed=two_bars, product=with_alias, bound=True)
    assert priced.rung.value == "product"
    assert priced.calories == pytest.approx(220.0)
    assert priced.resolved_grams == pytest.approx(110.0)        # 2 x 1 x 55 g
    assert any(str(i).startswith("unit_evidence:") for i in priced.conversion_evidence_ids), \
        priced.conversion_evidence_ids
    with pytest.raises(PricingRefused):
        price(entity="Barebell", consumed=two_bars, product=without, bound=True)
    # and half a bar, and a foreign noun against the aliased snapshot
    half = price(entity="Barebell", consumed=normalize_quantity("half a bar", "x"),
                 product=with_alias, bound=True)
    assert half.calories == pytest.approx(55.0)
    with pytest.raises(PricingRefused):
        price(entity="Barebell", consumed=normalize_quantity("2 bottles", "x"),
              product=with_alias, bound=True)


@pytest.mark.asyncio
async def test_a_bound_settle_of_two_bars_carries_the_alias_evidence_on_the_row(
        db, make_user, monkeypatch):
    """Through the predicate and settlement: Supported('product'), the row's
    receipt names the snapshot AND the unit-evidence conversion."""
    import skills.nutrition.off as off_mod
    from core.general_settlement import Supported, coverage_for
    from db.models import FoodEntry
    from sqlalchemy import select
    from skills.nutrition.product_acquisition import acquire_product_evidence
    from tests.test_a_scan_is_binding import _log, _native

    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    async def fetch_labelled(code): return dict(LABELLED)
    monkeypatch.setattr(off_mod, "fetch_product", fetch_labelled)
    sid = await acquire_product_evidence(db, "70004200")
    await db.commit()
    verdict = await coverage_for(db, user_id=user.id, items=[
        {"food_name": "Barebells bar", "quantity": "2 bars", "product_evidence_id": sid}])
    assert isinstance(verdict, Supported) and verdict.expected_source == "product"

    log = await _log(db, user)
    ops = [{"name": "log_food", "input": {"food_name": "Barebells bar", "quantity": "2 bars",
                                          "calories": 400.0}}]
    execution, response = await _native(db, user, log, "2 barebells bars", sid, ops, monkeypatch)
    assert execution.calls[0].committed
    row = (await db.execute(select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    assert row.product_evidence_id == sid and row.calories == pytest.approx(220.0)
    assert row.resolved_grams == pytest.approx(110.0)
    assert "unit_evidence:" in (row.conversion_evidence_ids_json or "")
