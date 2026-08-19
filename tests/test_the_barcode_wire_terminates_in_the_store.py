"""⭐ P17f.5 — THE EXACT-PRODUCT ACQUISITION WIRE, backend half.

    scan -> raw barcode (SEPARATE from prose) -> ingress acquisition
         -> exact OFF fetch -> append immutable snapshot -> snapshot id
         -> bound to the turn's single item -> assemble() loads LOCALLY

The board's checklist, as tests: the barcode is never reconstructed from
prose · acquisition performs the exact-ID fetch · evidence persists BEFORE
settlement · settlement performs zero provider calls · a scan binds one
product to one item, never several.
"""
from __future__ import annotations

import pytest

from tests.test_a_scan_is_binding import _fake_ev

from skills.nutrition.product_acquisition import (SCANNED_PRODUCT_EVIDENCE,
                                                  acquire_product_evidence)

BAREBELLS = {
    "code": "70004199", "product_name": "Barebell salty peanut protein bar",
    "brands": "Barebell", "serving_size": "55.0g", "serving_quantity": 55,
    "serving_quantity_unit": "g", "rev": 1, "last_modified_t": 1724712330,
    "nutrition_data_per": "100g",
    "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                   "carbohydrates_100g": 18, "fat_100g": 7.3,
                   "energy-kcal_serving": 110, "proteins_serving": 11,
                   "carbohydrates_serving": 9.9, "fat_serving": 4},
}


@pytest.mark.asyncio
async def test_acquisition_fetches_once_and_persists_the_snapshot(db, monkeypatch):
    """The happy path: exact fetch, append, id returned — and the snapshot is
    already durable when settlement later loads it."""
    import skills.nutrition.product_acquisition as acq

    async def _fetch(code):
        assert code == "70004199", "acquisition must fetch the EXACT code"
        return dict(BAREBELLS)
    import skills.nutrition.off as off_mod
    monkeypatch.setattr(off_mod, "fetch_product", _fetch)

    snapshot_id = await acquire_product_evidence(db, "0070004199")
    assert snapshot_id is not None

    from skills.nutrition.product_store import load_product_evidence
    evidence = await load_product_evidence(db, snapshot_id)
    assert evidence.identifier == "off:70004199"
    # ⭐ THE P17b.1 NARROWING, VISIBLE AT THE WIRE: no caller-supplied unit
    # noun means NO per-serving basis — an ungated per-serving would let
    # "2 bottles" multiply a bar label. The snapshot is per-100g plus the
    # serving mass as a CONVERSION INPUT: gram portions price now; bare counts
    # wait for a binding step to say what the thing is called.
    assert evidence.per_serving is None
    assert evidence.per100g["calories"] == pytest.approx(200.0)
    assert evidence.serving_grams == pytest.approx(55.0)


@pytest.mark.asyncio
async def test_a_dead_provider_falls_back_to_the_newest_local_snapshot(db, monkeypatch):
    """⭐ Yesterday's evidence is evidence. A network flake must not turn a
    scanned product into an estimate when a snapshot already exists."""
    from skills.nutrition.product_store import append_product_evidence
    row = await append_product_evidence(db, record=BAREBELLS)

    import skills.nutrition.off as off_mod

    async def _down(code):
        raise RuntimeError("OFF is down")
    monkeypatch.setattr(off_mod, "fetch_product", _down)

    assert await acquire_product_evidence(db, "70004199") == row.id


@pytest.mark.asyncio
async def test_nothing_anywhere_yields_none_never_an_error(db, monkeypatch):
    import skills.nutrition.off as off_mod

    async def _miss(code):
        return None
    monkeypatch.setattr(off_mod, "fetch_product", _miss)
    assert await acquire_product_evidence(db, "9999999999") is None


@pytest.mark.asyncio
async def test_a_malformed_code_never_reaches_the_network(db, monkeypatch):
    import skills.nutrition.off as off_mod

    async def _boom(code):                                # pragma: no cover
        raise AssertionError("a malformed code reached the network")
    monkeypatch.setattr(off_mod, "fetch_product", _boom)
    for bad in ("", "abc", "12345", "1" * 15):
        assert await acquire_product_evidence(db, bad) is None


# ── THE BARCODE IS NEVER RECONSTRUCTED FROM PROSE ───────────────────────────

def test_the_request_validator_sanitizes_never_parses():
    """The field carries the code or the code does not exist. Prose stays
    presentation — there is no text-mining fallback to 'find' a barcode."""
    from api.chat import ChatRequest

    assert ChatRequest(message="hi", barcode="0070004199").barcode == "0070004199"
    assert ChatRequest(message="hi", barcode="70-0041-99").barcode == "70004199"
    assert ChatRequest(message="hi", barcode="abc").barcode is None
    scan_prose = ChatRequest(
        message="I scanned a barcode — Barebells 70004199, 200 kcal")
    assert scan_prose.barcode is None, (
        "a barcode inside the MESSAGE must not become a barcode — the field "
        "is the only channel")


def test_acquisition_module_contains_no_prose_parsing():
    """⛔ Structural: the acquisition module must never grow a text-mining
    path. It may know about barcodes; it may not know about messages."""
    import inspect

    import skills.nutrition.product_acquisition as acq

    source = inspect.getsource(acq)
    for forbidden in ("message", "prose_text", "scanned a barcode"):
        assert forbidden not in source.replace(
            "SEPARATE from prose", "").replace(
            "prose, and must never be", "").replace(
            "presentation/context only", "").replace(
            'scan message ("I scanned a barcode', ""), (
            f"acquisition references {forbidden!r} — the wire is growing a "
            f"text-mining path")


# ── SETTLEMENT PERFORMS ZERO PROVIDER CALLS ─────────────────────────────────

def test_no_settle_path_module_imports_acquisition_or_the_off_client():
    """⛔⛔ THE BOUNDARY THE WIRE MUST NOT REOPEN. Acquisition is an INGRESS
    concern; the settle path loads snapshots and nothing else. An import here
    is how network-at-settlement comes back."""
    import ast
    import pathlib

    settle_path = ["core/general_settlement.py", "core/canonical_pricing.py",
                   "core/canonical_pricing_inputs.py",
                   "core/canonical_writer.py"]
    root = pathlib.Path(__file__).resolve().parent.parent
    for module in settle_path:
        tree = ast.parse((root / module).read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert "product_acquisition" not in name, (
                    f"{module} imports acquisition — ingress leaked into "
                    f"settlement")
                assert not name.endswith("nutrition.off"), (
                    f"{module} imports the OFF client — a provider call is "
                    f"one call away from the settle path")


# ── THE BINDING: ONE SCAN, ONE PRODUCT, ONE ITEM, ONE VIEW ──────────────────

def _ops(*names):
    return [{"name": "log_food", "input": {"food_name": n}} for n in names]



def _Plan(ops=(), ambiguities=(), intent="log", **producer):
    """A REAL plan, through the real normaliser. Builds an interpreter-shaped
    dict — the producer's own keys — and lifts it with
    `plan_from_interpretation`, so `food_subjects` is exactly what production
    would carry. Extra producer keys (`deferred_calls`, `questions`,
    `b1_material`, `points`) pass straight through."""
    from core.turns.stages.food import plan_from_interpretation
    out = {"action": intent, "tool_calls": list(ops), "say": ""}
    if intent == "ask":
        # the primary ask origin's shape: no top-level items/ambiguities
        out.setdefault("questions", [])
    for amb in ambiguities:
        # legacy fixture shape {"items": [...], "ambiguities": [...]} — kept
        # readable for tests that still use it, but the SUBJECTS come from the
        # dict's own keys via the normaliser, never from a max() over views
        if isinstance(amb, dict):
            out.setdefault("items", []).extend(amb.get("items") or [])
            out.setdefault("ambiguities", []).extend(amb.get("ambiguities") or [])
    out.update(producer)
    return plan_from_interpretation(out)

def _decide(ops=(), message="I had some of this"):
    from core.scan_authority import decide_from_plan, evidence as _evidence
    out = _Plan(ops)
    d = decide_from_plan(out if out.source and out.source.get("_message") else
                         __import__("dataclasses").replace(
                             out, source={**(out.source or {}), "_message": message}),
                         _evidence())
    return d.outcome if d is not None else None


def test_a_single_item_turn_binds_the_snapshot():
    from core.turns.stages.execute_native import (_bind_scanned_product,
                                                  _food_inputs)

    # ⭐ CF5b review — THE BINDER STAMPS WHAT THE DECISION SAYS. Attachment
    # alone no longer binds, so the real composition is exercised here:
    # attach -> decide from the turn's ops -> stamp.
    from skills.nutrition.product_acquisition import attach, begin_turn

    begin_turn()
    attach(_fake_ev(42))
    ops = _ops("Barebells bar")
    _decide(ops)
    try:
        items = _bind_scanned_product(_food_inputs(ops))
        assert items[0]["product_evidence_id"] == 42
    finally:
        begin_turn()


def test_a_multi_item_turn_binds_nothing():
    """A scan names ONE product — smearing its evidence across a meal of
    several foods would price chicken from a protein-bar label."""
    from core.turns.stages.execute_native import (_bind_scanned_product,
                                                  _food_inputs)

    # ⚠ AND THIS TEST MUST BE ABLE TO FAIL. Once attachment stopped binding,
    # asserting "no stamp" with no decision made passed vacuously — nothing
    # stamps without a decision. So the decision is made here exactly as the
    # stage makes it, and the single-item twin above proves stamping DOES
    # happen when the decision says bound.
    from skills.nutrition.product_acquisition import attach, begin_turn

    begin_turn()
    attach(_fake_ev(42))
    ops = _ops("Barebells bar", "banana")
    _decide(ops)
    try:
        items = _bind_scanned_product(_food_inputs(ops))
        assert all("product_evidence_id" not in i for i in items)
    finally:
        begin_turn()


def test_no_scan_no_binding():
    from core.turns.stages.execute_native import (_bind_scanned_product,
                                                  _food_inputs)

    assert SCANNED_PRODUCT_EVIDENCE.get() is None
    items = _bind_scanned_product(_food_inputs(_ops("Barebells bar")))
    assert "product_evidence_id" not in items[0]


# ── END TO END, PROVIDER POISONED AT THE SETTLEMENT SIDE ────────────────────

@pytest.mark.asyncio
async def test_the_whole_wire_prices_two_bars_with_settlement_offline(
        db, make_user, monkeypatch):
    """acquisition (network HERE) -> snapshot -> binding -> assemble (LOCAL)
    -> price. The OFF client dies after acquisition, proving the settle side
    needs nothing from it."""
    import skills.nutrition.off as off_mod
    from core.canonical_pricing import Rung, price
    from core.canonical_pricing_inputs import assemble
    from core.turns.stages.execute_native import (_bind_scanned_product,
                                                  _food_inputs)
    from skills.nutrition.models import COUNT_BASIS_UNIT, NormalizedQuantity

    user = await make_user()

    async def _fetch(code):
        return dict(BAREBELLS)
    monkeypatch.setattr(off_mod, "fetch_product", _fetch)
    snapshot_id = await acquire_product_evidence(db, "70004199",
                                                 serving_unit="bar")
    assert snapshot_id is not None

    # The provider dies. Everything after this line is the settle side.
    async def _dead(*a, **kw):                            # pragma: no cover
        raise AssertionError("the settle side reached the provider")
    monkeypatch.setattr(off_mod, "fetch_product", _dead)
    monkeypatch.setattr(off_mod, "_get_json", _dead)

    from skills.nutrition.product_acquisition import attach_acquired, begin_turn

    # ⛔ begin_turn() would clear the evidence acquisition just built; the
    # production ingress order is begin_turn -> acquire -> attach_acquired.
    attach_acquired(snapshot_id)       # the VERIFIED evidence acquisition built
    _ops_single = _ops("Barebells bar")
    _decide(_ops_single, message="I had 2 barebells bars")
    try:
        items = _bind_scanned_product(_food_inputs(_ops_single))
        evidence = await assemble(db, user_id=user.id, entity="barebells bar",
                                  preparation="", identity="Barebells bar",
                                  item=items[0])
        assert evidence["product"] is not None
        priced = price(entity="Barebells bar",
                       consumed=NormalizedQuantity(
                           amount=2, unit="bar", count=2.0, unit_label="bar",
                           count_basis=COUNT_BASIS_UNIT),
                       product=evidence["product"])
        assert priced.rung is Rung.PRODUCT
        assert priced.calories == pytest.approx(220.0)
    finally:
        begin_turn()
