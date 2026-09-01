"""⛔⛔⛔ THE COUNTERFACTUAL MUST SIMULATE A PRODUCER, NOT ITS OUTCOME.

This harness produced two confident, opposite, WRONG conclusions before it was
right, and both came from the same shortcut: setting the booleans a producer
would CAUSE instead of supplying the evidence that causes them.

    v1  set has_artifact=True, left selected_rung_authoritative alone
        -> decide() refused at the scaling gate
        -> reported "evidence recovers 0; scaling is the lever"
    v1b set selected_rung_authoritative=True by fiat
        -> reported "477/480 recover; scaling is the lever"

Both were artifacts of the simulation:

    selected_authoritative = False        # initialised in select_priced_rung
    for ev, build in rungs:
        if ev is None: continue           # ← no evidence → no rung → NEVER SET

`selected_rung_authoritative=False` means NO RUNG WAS SELECTED, not that the
quantity cannot scale. These are OUTCOMES, and an arm that writes them is
measuring its own fixture.

⭐ THE FROZEN CONTRACT: real ItemFacts -> inject a realistic evidence OBJECT ->
real `select_priced_rung()` -> real `resolve_scaling()` against the item's
actual quantity -> resulting ItemFacts -> UNCHANGED `decide()` -> group to MEAL
-> score against the same 222-meal denominator.
"""
from __future__ import annotations

import pathlib

import pytest

SCRIPT = (pathlib.Path(__file__).resolve().parent.parent /
          "scripts" / "counterfactual_producer_faithful.py")


def test_the_harness_never_writes_an_outcome_flag():
    """⛔ THE STRUCTURAL GUARD. `has_artifact=True`, `has_memory=True` and
    `selected_rung_authoritative=True` are things a producer CAUSES. An arm that
    assigns them is simulating its conclusion."""
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("ARMS = {"):]
    for forbidden in ("selected_rung_authoritative=True",
                      "product_scales=True",
                      "has_quantity=True"):
        assert forbidden not in body, (
            f"an arm sets {forbidden!r} — that is an OUTCOME, not an "
            "intervention. Supply the evidence object and let "
            "select_priced_rung/resolve_scaling reach it.")


def test_it_runs_the_real_selector_and_the_real_scaler():
    src = SCRIPT.read_text(encoding="utf-8")
    for required in ("select_priced_rung", "normalize_quantity", "decide("):
        assert required in src, f"the harness does not call {required}"
    assert "unchanged" in src.lower() or "UNCHANGED" in src


def test_a_conversion_measure_MUST_carry_provenance():
    """⛔⛔ ARM E RETURNED EXACTLY ARM B's NUMBER because its `SourcedMeasure`
    had no `record_version`: `as_basis_conversion()` raised, the harness caught
    it, and every count item failed on a FIXTURE DEFECT. The exact-mass items
    take `resolve_scaling` path 1 and never reach the conversion, so the two
    arms matched to the meal — an implausible exact equality was the only tell.

    ⭐ The provenance contract refusing an unreproducible citation is the guard
    WORKING. This pins that the fixture satisfies it, so the arm can never
    again be silently inert."""
    from skills.nutrition.scaling import SourcedMeasure
    good = SourcedMeasure(unit_text="egg", grams_per_unit=50.0,
                          source_id="sim", dataset_id="sim",
                          dataset_version="1", record_key="k",
                          record_version="1", immutable_within_version=True)
    good.as_basis_conversion()                      # must not raise

    bad = SourcedMeasure(unit_text="egg", grams_per_unit=50.0,
                         source_id="sim", dataset_id="sim",
                         dataset_version="1", record_key="k")
    with pytest.raises(ValueError, match="record_version|reproduced"):
        bad.as_basis_conversion()

    src = SCRIPT.read_text(encoding="utf-8")
    assert "immutable_within_version=True" in src, (
        "the harness's conversion fixture would raise and be swallowed again")


def test_the_conversion_actually_CHANGES_a_verdict():
    """⭐ MUTATION VALIDITY. An intervention that changes nothing may be INERT
    rather than ineffective — which is exactly how arm E's void result read as
    a finding. The conversion must be shown to flip a real verdict."""
    from core.canonical_pricing import (MemoryEvidence, _from_memory,
                                        select_priced_rung)
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.scaling import SourcedMeasure

    ev = MemoryEvidence(per100g={"calories": 200.0, "protein": 10.0,
                                 "carbs": 20.0, "fat": 8.0},
                        source_id="sim", confidence=0.9)
    consumed = normalize_quantity("1 egg", "Boiled egg")
    m = (SourcedMeasure(unit_text="egg", grams_per_unit=50.0, source_id="sim",
                        dataset_id="sim", dataset_version="1", record_key="k",
                        record_version="1", immutable_within_version=True),)

    def wrap(fn):
        def build(e):
            out = fn(e)
            if not out:
                return out
            pr, rg, eid, raw, basis, _ = out
            return pr, rg, eid, raw, basis, m
        return build

    none = ((None, lambda e: None), (None, lambda e: None))
    without = select_priced_rung(entity="egg", preparation="", consumed=consumed,
                                 rungs=((ev, _from_memory), *none), bound=False)
    with_ = select_priced_rung(entity="egg", preparation="", consumed=consumed,
                               rungs=((ev, wrap(_from_memory)), *none), bound=False)
    assert without.authoritative is False
    assert with_.authoritative is True, (
        "the sourced conversion does not change the verdict — the arm is inert")
