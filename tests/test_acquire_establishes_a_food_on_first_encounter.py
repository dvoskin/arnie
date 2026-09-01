"""ACQUIRE — the producer, with the provider stubbed.

⛔ NO NETWORK. `build_one` is the REAL producer and is exercised for real by the
artifact build; what these tests own is the boundary around it — what acquire
does with each outcome it can return, and the outcomes it must refuse to even
attempt.
"""
from __future__ import annotations

import asyncio

import pytest

from skills.nutrition import acquisition as acq

CANDIDATE = {
    "evidence_id": "usda:171955", "source": "usda", "fdc_id": 171955,
    "description": "Fish, cod, Atlantic, raw", "data_type": "SR Legacy",
    "per100g": {"calories": 82.0, "protein": 17.81, "carbs": 0.0, "fat": 0.67},
    "measures": [],
}


def _stub(monkeypatch, result=None, *, hang=False, boom=False, calls=None):
    """Replace the provider. `calls` records that it was reached at all."""
    import scripts.build_pricing_artifact as b

    async def fake(entity, preparation, store=None, identity_key=""):
        if calls is not None:
            calls.append(identity_key or entity)
        if boom:
            raise RuntimeError("provider exploded")
        if hang:
            await asyncio.sleep(30)
        return result
    monkeypatch.setattr(b, "build_one", fake)


# ── WHAT IT REFUSES TO EVEN ATTEMPT ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_bound_item_never_acquires(db, monkeypatch):
    """⛔ A SCAN CONSTRAINS THE EVIDENCE UNIVERSE. Retrieving a generic
    composition record for a food the user SCANNED would reintroduce exactly
    the rung the binding exists to exclude — and "never consulted" is only true
    mechanically when the call never happens."""
    calls = []
    _stub(monkeypatch, {"status": "ok", "candidates": [CANDIDATE]}, calls=calls)
    with pytest.raises(acq.AcquisitionRefused) as e:
        await acq.acquire(db, identity="cod", item={"product_evidence_id": 7})
    assert e.value.reason == acq.NO_IDENTITY
    assert calls == [], "the provider was reached for a bound item"


@pytest.mark.asyncio
async def test_a_food_already_held_is_not_reacquired(db, monkeypatch):
    """⭐ THE CACHE HALF OF THE FLYWHEEL — first encounter pays, later ones are
    a local read. Also why the 27 seeded foods are never touched."""
    from core.acquired_evidence_store import remember
    calls = []
    _stub(monkeypatch, {"status": "ok", "candidates": [CANDIDATE]}, calls=calls)

    await remember(db, acq.AcquiredEvidence(
        canonical_identity="cod|", identity_evidence={},
        nutrition_evidence=(CANDIDATE,), source_type="usda",
        source_identifier="171955", authority_grade=acq.SOURCED_COMPOSITION,
        nutrition_basis="per_100g", serving_basis=(),
        quantity_compatibility=frozenset({"mass"}),
        provenance={"source_fingerprint": "sf-1"}))
    await db.commit()

    with pytest.raises(acq.AcquisitionRefused):
        await acq.acquire(db, identity="cod")
    assert calls == [], "re-acquired a food already held"


@pytest.mark.asyncio
async def test_an_empty_identity_is_refused_before_any_call(db, monkeypatch):
    calls = []
    _stub(monkeypatch, {"status": "ok", "candidates": [CANDIDATE]}, calls=calls)
    with pytest.raises(acq.AcquisitionRefused) as e:
        await acq.acquire(db, identity="   ")
    assert e.value.reason == acq.NO_IDENTITY
    assert calls == []


# ── OUTAGE IS NOT ABSENCE ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("kw,result", [
    ({"boom": True}, None),
    ({}, {"status": "failed", "reason": "3/3 provider queries failed"}),
])
async def test_a_provider_outage_is_not_an_absence_of_evidence(
        db, monkeypatch, kw, result):
    """⛔⛔ ROUTING THE TWO TO THE SAME OUTCOME IS HOW AN OUTAGE BECOMES "this
    food does not exist" — the rule `look()`'s memory read already obeys, and
    the reason the whole `matched: 0` class of finding exists."""
    _stub(monkeypatch, result, **kw)
    with pytest.raises(acq.AcquisitionRefused) as e:
        await acq.acquire(db, identity="cod")
    assert e.value.reason == acq.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_slow_provider_expires_rather_than_hanging_the_turn(
        db, monkeypatch):
    """The user is sitting there. Unbounded retrieval is a turn that hangs."""
    _stub(monkeypatch, None, hang=True)
    with pytest.raises(acq.AcquisitionRefused) as e:
        await acq.acquire(db, identity="cod", deadline_s=0.05)
    assert e.value.reason == acq.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_food_the_provider_does_not_hold_is_a_COUNTABLE_outcome(
        db, monkeypatch):
    """⭐ NOT the same reason as an outage. This is the count that tells the
    next tranche which adapter is missing: no USDA English description will
    ever match `окрошка на айране с курицей`, and half the frozen corpus's
    tail is Russian."""
    _stub(monkeypatch, {"status": "no_evidence", "reason": "no curated rows"})
    with pytest.raises(acq.AcquisitionRefused) as e:
        await acq.acquire(db, identity="окрошка на айране с курицей")
    assert e.value.reason == acq.IDENTITY_UNQUALIFIED


# ── THE SUCCESS PATH, END TO END ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acquisition_makes_an_unseen_food_settle_canonically(
        db, make_user, monkeypatch):
    """⭐⭐⭐ PHASE 1 EXIT: an identity absent from artifacts and memory before
    the turn acquires evidence, passes the NORMAL canonical gates, and settles."""
    from core.general_settlement import Supported, coverage_for
    user = await make_user()
    item = {"food_name": "cod", "quantity": "180 g", "calories": 999.0}

    before = await coverage_for(db, user_id=user.id, items=[item])
    assert not isinstance(before, Supported), "fixture proves nothing"

    _stub(monkeypatch, {"status": "ok", "candidates": [CANDIDATE], "raw": 5,
                        "unresolved": ()})
    got = await acq.acquire(db, identity="cod")
    await db.commit()

    assert got.canonical_identity == "cod|"
    assert got.authority_grade == acq.SOURCED_COMPOSITION
    after = await coverage_for(db, user_id=user.id, items=[item])
    assert isinstance(after, Supported), f"still unsupported: {after}"
    assert after.expected_source == "artifact"


@pytest.mark.asyncio
async def test_what_acquire_returns_carries_no_verdict(db, monkeypatch):
    """It hands back FACTS. There is no field on the result a caller could
    mistake for a settlement, which is why it cannot bypass `decide()`."""
    from dataclasses import fields
    _stub(monkeypatch, {"status": "ok", "candidates": [CANDIDATE]})
    got = await acq.acquire(db, identity="cod")
    names = {f.name for f in fields(got)}
    assert not any(n.startswith(("has_", "is_")) for n in names)
    assert not (names & {"supported", "authoritative", "priced", "settled"})
