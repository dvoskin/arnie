"""⭐⭐⭐ THE OPEN-WORLD VERTICAL SLICE — a food Arnie has never seen settles.

Before this tranche the effective logic was:

    food -> look() -> do I already hold admissible local evidence? -> NO -> legacy

and "NO" was permanent, because the artifact rung reads a COMMITTED FILE. Its
own docstrings say so — "Generation happens outside the turn, by the script, or
not at all this turn", "a file read; never a fetch". A running process that
learns a new food had nowhere to put it. The catalog held 27 foods seeded from
a list whose generator admits "seems likely someone will log this" is NOT a
criterion, and everything outside it fell to legacy forever no matter how many
users logged it. THAT ceiling is the 9.0%.

These tests prove the ceiling is gone, and prove it WITHOUT weakening anything:
the same `coverage_for`, the same rung ladder, the same `decide()`.
"""
from __future__ import annotations

import datetime as dt

import pytest

# A previously unseen identity. Deliberately NOT one of the 54 in the frozen
# corpus: this proves the MECHANISM, and a fixture drawn from the evaluation
# set would be the memorisation the directive forbids.
UNSEEN = "cod"

CANDIDATE = {
    "evidence_id": "usda:171955", "source": "usda", "fdc_id": 171955,
    "description": "Fish, cod, Atlantic, raw", "data_type": "SR Legacy",
    "per100g": {"calories": 82.0, "protein": 17.81, "carbs": 0.0, "fat": 0.67},
    "measures": [],
}


def _acquired(identity="cod|", candidates=(CANDIDATE,), fingerprint="sf-1"):
    from skills.nutrition.acquisition import AcquiredEvidence, SOURCED_COMPOSITION
    return AcquiredEvidence(
        canonical_identity=identity,
        identity_evidence={"verdict": "SAME_IDENTITY", "confidence": 0.97},
        nutrition_evidence=tuple(candidates), source_type="usda",
        source_identifier="171955", authority_grade=SOURCED_COMPOSITION,
        nutrition_basis="per_100g", serving_basis=(),
        quantity_compatibility=frozenset({"mass"}),
        provenance={"dataset_id": "usda_fdc", "dataset_version": "2025-04",
                    "source_fingerprint": fingerprint})


def _item(name=UNSEEN, qty="180 g"):
    return {"food_name": name, "quantity": qty, "calories": 999.0, "protein": 1.0}


# ── THE SLICE ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unseen_food_is_unsupported_before_acquisition(db, make_user):
    """The baseline, asserted rather than assumed.

    ⛔ Without this the next test proves nothing: a food that was ALREADY
    supported would pass it while the acquisition path lay dead. An
    intervention that changes nothing may be inert, not effective.
    """
    from core.general_settlement import Supported, coverage_for
    user = await make_user()
    verdict = await coverage_for(db, user_id=user.id, items=[_item()])
    assert not isinstance(verdict, Supported), \
        f"{UNSEEN!r} was already supported — this fixture cannot prove anything"


@pytest.mark.asyncio
async def test_acquired_evidence_settles_it_through_the_unchanged_gates(db, make_user):
    """⭐ THE WHOLE TRANCHE IN ONE ASSERTION. Unseen identity + exact user mass
    + evidence established at first encounter -> Supported("artifact").

    Note WHICH rung: `artifact`. Acquisition did not invent a rung, did not set
    a boolean, and did not touch `decide()`. It wrote evidence, and the ladder
    that was always there priced it.
    """
    from core.acquired_evidence_store import remember
    from core.general_settlement import Supported, coverage_for
    user = await make_user()
    assert await remember(db, _acquired()) is True
    await db.commit()

    verdict = await coverage_for(db, user_id=user.id, items=[_item()])
    assert isinstance(verdict, Supported), f"still unsupported: {verdict}"
    assert verdict.expected_source == "artifact", \
        f"settled on {verdict.expected_source!r}, not artifact"


# ── THE SAFEGUARDS ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acquisition_cannot_reprice_a_food_the_catalog_already_covers(db):
    """⛔⛔ THE FROZEN BASELINE MUST NOT MOVE UNDERNEATH THE INSTRUMENT.

    Merging acquired candidates into a seeded identity would re-run
    `best_candidate` over a larger pool and could pick differently — silently
    repricing foods that are IN the 222-meal measurement. The 9.0% figure is
    only worth having because it does not move, so the catalog answers first
    and its answer is final.
    """
    from core.acquired_evidence_store import evidence_for, remember
    from skills.nutrition import pricing_artifact as art

    seeded = next((k for k in (art._artifact().entries or {})), None)
    if seeded is None:
        pytest.skip("no committed artifact entries to defend")
    entity, _, prep = seeded.partition("|")
    assert art.evidence_for(entity, prep) is not None, "fixture is not seeded"

    await remember(db, _acquired(identity=seeded, candidates=(
        {**CANDIDATE, "evidence_id": "usda:999999", "per100g":
         {"calories": 1.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}},)))
    await db.commit()
    assert await evidence_for(db, entity, prep) is None, \
        "acquired evidence reached a seeded identity — the baseline can move"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("resolver_version", "a-resolver-nobody-runs"),
    ("retrieval_fingerprint", "a-vocabulary-nobody-runs"),
])
async def test_a_row_from_a_dead_instrument_is_never_served(db, field, value):
    """⛔⛔ THE CACHE MUST NOT BECOME THE WAY TO EVADE THE FRESHNESS RULE.

    The file artifact is verified against `resolver_version`,
    `vocabulary_fingerprint` and an age. If acquired rows escaped that, a row
    written once would outlive the vocabulary that qualified it and keep
    pricing meals under a resolver nobody runs any more.
    """
    from sqlalchemy import select
    from core.acquired_evidence_store import evidence_for, remember
    from db.models import AcquiredEvidenceRecord

    await remember(db, _acquired())
    row = (await db.execute(select(AcquiredEvidenceRecord))).scalars().one()
    setattr(row, field, value)
    await db.commit()
    assert await evidence_for(db, UNSEEN, "") is None, \
        f"a row with a stale {field} was served"


@pytest.mark.asyncio
async def test_a_row_older_than_the_artifact_age_limit_is_never_served(db):
    """Acquired evidence ages by the SAME rule seeded evidence does."""
    from sqlalchemy import select
    from core.acquired_evidence_store import evidence_for, remember
    from core.materiality_artifact import MAX_ARTIFACT_AGE_DAYS
    from db.models import AcquiredEvidenceRecord

    await remember(db, _acquired())
    row = (await db.execute(select(AcquiredEvidenceRecord))).scalars().one()
    row.acquired_at = (dt.datetime.now(dt.timezone.utc)
                       - dt.timedelta(days=MAX_ARTIFACT_AGE_DAYS + 1))
    await db.commit()
    assert await evidence_for(db, UNSEEN, "") is None, "stale row was served"
    # and it is DECLINED, not DELETED — "what priced this, at the time" must
    # stay answerable after the instrument moves.
    assert (await db.execute(select(AcquiredEvidenceRecord))).scalars().all()


@pytest.mark.asyncio
async def test_reacquiring_the_same_fact_writes_one_row(db):
    """Idempotent on the FACT, not on the fetch — two turns racing to acquire
    the same food under the same instrument leave one row, and the duplicate is
    a normal outcome rather than an error surfaced at the user."""
    from sqlalchemy import select
    from core.acquired_evidence_store import remember
    from db.models import AcquiredEvidenceRecord

    assert await remember(db, _acquired()) is True
    assert await remember(db, _acquired()) is False
    await db.commit()
    rows = (await db.execute(select(AcquiredEvidenceRecord))).scalars().all()
    assert len(rows) == 1, f"{len(rows)} rows for one fact"


@pytest.mark.asyncio
async def test_an_acquired_row_with_no_candidate_is_not_a_rung_hit(db):
    """A hit that prices nothing is worse than a miss — guarded on BOTH sides,
    because a guard whose protected input never occurs is a guard nobody has."""
    from sqlalchemy import select
    from core.acquired_evidence_store import evidence_for, remember
    from db.models import AcquiredEvidenceRecord

    await remember(db, _acquired())
    row = (await db.execute(select(AcquiredEvidenceRecord))).scalars().one()
    row.candidates = []
    await db.commit()
    assert await evidence_for(db, UNSEEN, "") is None
