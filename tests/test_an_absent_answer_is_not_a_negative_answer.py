"""A ROW THE MODEL DECLINED TO JUDGE MUST NOT BECOME A CONFIDENT NEGATIVE.

⛔ THE DEFECT. `qualify_usda_rows` treats only an ALL-abstain batch as an
outage. A PARTIAL abstention — some rows assessed, some not — returns
`disposition="qualified"`, and the unjudged rows simply fall out of `kept`.
`build_one` then computed `judged = {ids in q.rows}` and wrote
`DIFFERENT_IDENTITY` at confidence 0.95 for everything else, on the stated
reasoning that "anything it saw and did not keep is a judged negative".

That reasoning is false for an abstention. The result was a durable, confident
verdict about a row NOBODY ASSESSED — and because `needs_resolution` sees a
resolved annotation, the row was never reopened. Afterwards it is
indistinguishable from a real rejection, so nothing downstream can even count
how often it happened.

This is `541ed12` one layer down. That commit stopped the QUALIFIER deleting
evidence on an absent answer; the store write underneath it kept doing so.

⭐ AND THE DISTINCTION IS THE WHOLE POINT. A judged rejection must still be a
negative — the fix must not turn every non-kept row into "ask again", which
would make the resolver's actual verdicts unrecordable and re-bill them on
every rebuild.
"""
from __future__ import annotations

import pytest

import api.usda as usda
import scripts.build_pricing_artifact as bp
import skills.nutrition.evidence_qualification as eq
import skills.nutrition.semantic_annotations as sa
from core.semantic_evidence import ABSTAIN, SemanticAssessment
from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

IDENTITY = "beef|roasted"

#: Three rows that all SURVIVE the mechanical veto, so what reaches the store
#: is decided by qualification alone. (A mushroom row would be refused for
#: base-food mismatch before the resolver, which would test the wrong layer.)
ROWS = [
    {"fdc_id": 1, "description": "Beef, chuck, cooked, roasted",
     "data_type": "sr legacy",
     "per100g": {"calories": 250, "protein": 26, "carbs": 0, "fat": 15}},
    {"fdc_id": 2, "description": "Beef, ribeye, cooked, roasted",
     "data_type": "sr legacy",
     "per100g": {"calories": 291, "protein": 24, "carbs": 0, "fat": 21}},
    {"fdc_id": 3, "description": "Beef, cured, corned beef, cooked",
     "data_type": "sr legacy",
     "per100g": {"calories": 251, "protein": 18, "carbs": 0, "fat": 19}},
]


@pytest.fixture
def replayed(monkeypatch):
    async def _search(*_a, **_k):
        return list(ROWS)
    monkeypatch.setattr(usda, "_search", _search)


async def _build(store):
    with ranking_regime(PHASE_0_REGIME):
        return await bp.build_one("beef", "roasted", store=store,
                                  identity_key=IDENTITY)


def _partial_abstention(monkeypatch):
    """KEPT row 1 · ABSTAINED row 2 · JUDGED-AND-REJECTED row 3."""
    async def _qualify(_food, _rows, *_a, **_k):
        return eq.Qualification(
            rows=(ROWS[0],), disposition="qualified", raw_count=3,
            kept_count=1, resolver_version="stub-v1",
            abstained=(ROWS[1],))
    monkeypatch.setattr(eq, "qualify_usda_rows", _qualify)


# ── the store write ───────────────────────────────────────────────────────

async def test_an_abstained_row_is_not_recorded_as_a_negative(replayed,
                                                              monkeypatch):
    _partial_abstention(monkeypatch)
    store = sa.Store()
    await _build(store)

    abstained = store.get(IDENTITY, "usda:2")
    assert abstained.relationship == sa.UNRESOLVED, (
        "the model declined to judge this row and it was recorded as a "
        "confident statement that the row is not the food")
    assert abstained.confidence == 0.0


async def test_an_abstained_row_stays_revisitable(replayed, monkeypatch):
    """⭐ THE HALF THAT MADE IT PERMANENT. A negative verdict is `resolved`,
    so `needs_resolution` refuses to re-ask and the row never gets a second
    chance from any later populate or rebuild."""
    _partial_abstention(monkeypatch)
    store = sa.Store()
    await _build(store)

    assert store.needs_resolution(IDENTITY, "usda:2"), (
        "an unjudged row must remain askable")
    assert not store.needs_resolution(IDENTITY, "usda:1")
    assert not store.needs_resolution(IDENTITY, "usda:3")


async def test_a_judged_rejection_is_still_a_negative(replayed, monkeypatch):
    """The fix must not over-correct. A row the resolver ASSESSED and did not
    keep is a real verdict — recording it as 'ask again' would make the
    resolver's negatives unrecordable and re-bill them every rebuild."""
    _partial_abstention(monkeypatch)
    store = sa.Store()
    await _build(store)

    rejected = store.get(IDENTITY, "usda:3")
    assert rejected.relationship == sa.DIFFERENT_IDENTITY
    assert rejected.confidence == 0.95


async def test_an_abstention_is_not_counted_as_resolved_work(replayed,
                                                             monkeypatch):
    """A population run reports `resolved_this_build`. Counting an abstention
    would let it claim work it did not do."""
    _partial_abstention(monkeypatch)
    store = sa.Store()
    await _build(store)

    assert len(store.resolved_this_build) == 2, store.resolved_this_build
    assert (IDENTITY, "usda:2") not in store.resolved_this_build


async def test_ignoring_the_abstained_field_reintroduces_the_defect(
        replayed, monkeypatch):
    """⭐ CAUSAL. A `Qualification` that reports NO abstentions is exactly the
    pre-fix world — the same partial batch, with the unjudged row invisible.
    It must produce the confident false negative again, or this suite is not
    testing the thing that was wrong."""
    async def _qualify_without_abstentions(_food, _rows, *_a, **_k):
        return eq.Qualification(
            rows=(ROWS[0],), disposition="qualified", raw_count=3,
            kept_count=1, resolver_version="stub-v1")
    monkeypatch.setattr(eq, "qualify_usda_rows", _qualify_without_abstentions)

    store = sa.Store()
    await _build(store)

    assert store.get(IDENTITY, "usda:2").relationship == sa.DIFFERENT_IDENTITY
    assert not store.needs_resolution(IDENTITY, "usda:2")


# ── the qualifier half ────────────────────────────────────────────────────

async def test_qualification_carries_the_rows_the_model_declined(monkeypatch):
    """The information existed inside `qualify_usda_rows` and never left it:
    `kept` was computed from the assessments and the abstentions were dropped
    on the floor, so no caller could tell the two kinds of non-kept apart."""
    async def _classify(_food, rows, _complete=None):
        assessments = (
            SemanticAssessment(evidence_id="usda:1",
                               relationship="SAME_IDENTITY", confidence=0.95,
                               resolver_version="stub-v1"),
            SemanticAssessment(evidence_id="usda:2", relationship=ABSTAIN,
                               confidence=0.0, resolver_version="stub-v1"),
            SemanticAssessment(evidence_id="usda:3",
                               relationship="DIFFERENT_IDENTITY",
                               confidence=0.9, resolver_version="stub-v1"),
        )
        return (), assessments
    monkeypatch.setattr(eq, "classify_rows", _classify)

    result = await eq.qualify_usda_rows("beef, roasted", ROWS)

    assert result.disposition == "qualified", (
        "a PARTIAL abstention is not an outage — only an all-abstain batch is, "
        "which is precisely why this case looked like a completed operation")
    assert [r["fdc_id"] for r in result.abstained] == [2]
    assert [r["fdc_id"] for r in result.rows] == [1]


async def test_an_all_abstain_batch_reports_every_row_as_unjudged(monkeypatch):
    """The outage path already returns no rows. It must also say that NOTHING
    was judged, or a caller sees an empty `abstained` and infers the rows were
    considered and rejected."""
    async def _classify(_food, rows, _complete=None):
        return (), tuple(
            SemanticAssessment(evidence_id=f"usda:{r['fdc_id']}",
                               relationship=ABSTAIN, confidence=0.0,
                               resolver_version="stub-v1") for r in rows)
    monkeypatch.setattr(eq, "classify_rows", _classify)

    result = await eq.qualify_usda_rows("beef, roasted", ROWS)

    assert result.disposition == "resolver_down_no_candidates"
    assert result.rows == ()
    assert len(result.abstained) == len(ROWS)


async def test_a_resolver_exception_reports_every_row_as_unjudged(monkeypatch):
    async def _classify(_food, _rows, _complete=None):
        raise RuntimeError("the resolver fell over")
    monkeypatch.setattr(eq, "classify_rows", _classify)

    result = await eq.qualify_usda_rows("beef, roasted", ROWS)

    assert result.disposition == "resolver_down_no_candidates"
    assert len(result.abstained) == len(ROWS)
