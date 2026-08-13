"""PHASE 1.5 — THE BASELINE FREEZE, and what must remain true about it.

The freeze converts 77 hand-adjudicated pairs into durable semantic facts. The
gates here protect the two ways that could be undone quietly:

  1. THE POPULATION STOPS RECONCILING. The narrative report of this review
     claimed a set of categories that did not sum to the population, and eight
     rows described in prose as rejected were never signed. Prose cannot audit
     itself, so `accounting()` recomputes from the worksheet.

  2. A REBUILD RE-ASKS A SIGNED ROW. Three pairs were signed UNRESOLVED on
     purpose — a reviewer read the record and declined to rule. `UNRESOLVED`
     is also what the system writes when nobody has looked, so without a
     review status a rebuild would hand a considered refusal back to a model
     and overwrite it with a sampled opinion, every single build.

⭐ AND THE GATES THEMSELVES ARE CHECKED. A gate over hand-written data can
pass because the data is right or because the gate cannot see. Each mutation
test below breaks one specific thing and asserts the gate names it — proving
the check is load-bearing rather than decorative.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts import baseline_signatures as bs
from skills.nutrition import semantic_annotations as sa

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "baseline"


@pytest.fixture
def worksheet():
    return json.loads((_DATA / "phase_1_5_worksheet.json").read_text())


@pytest.fixture
def frozen(worksheet):
    store = sa.Store()
    bs.freeze(store, worksheet)
    return store


# ── 1. the population reconciles ──────────────────────────────────────────

def test_the_signed_baseline_reconciles_against_the_worksheet(worksheet):
    assert bs.accounting(worksheet) == ()


def test_every_row_carries_exactly_one_terminal_disposition(worksheet):
    signed = bs.by_pair()
    pairs = {(r["identity_key"], r["evidence_id"]) for r in worksheet}
    assert set(signed) == pairs
    assert all(d in bs.TERMINAL for d, *_ in signed.values())
    assert len(signed) == len(bs.SIGNATURES) == bs.EXPECTED_POPULATION


@pytest.mark.parametrize("break_it, expected", [
    # a row silently dropped from the sheet
    (lambda rows: rows[:-1], "population is 76"),
    # the same pair signed twice
    (lambda rows: rows + [dict(rows[0])], "duplicate pairs"),
    # a pair on the sheet that nobody signed
    (lambda rows: rows + [{"identity_key": "kiwi|", "evidence_id": "usda:1"}],
     "unsigned"),
])
def test_the_accounting_gate_can_actually_fail(worksheet, break_it, expected):
    """⭐ ANTI-VACUITY. A green gate over static data proves nothing until the
    gate has been shown to go red for the reason it claims to check."""
    failures = bs.accounting(break_it(list(worksheet)))
    assert any(expected in f for f in failures), failures


def test_a_signature_that_contradicts_its_own_disposition_is_refused():
    """An ADMIT whose relationship cannot price is an unreadable signature."""
    original = bs.SIGNATURES
    identity, evidence, _, _, reason, note = original[0]
    try:
        bs.SIGNATURES = ((identity, evidence, bs.ADMIT, sa.DIFFERENT_IDENTITY,
                          reason, note),) + original[1:]
        failures = bs.accounting(
            [{"identity_key": i, "evidence_id": e}
             for i, e, *_ in original])
        assert any("cannot price" in f for f in failures), failures
    finally:
        bs.SIGNATURES = original


# ── 2. the review survives ────────────────────────────────────────────────

def test_no_signed_row_is_re_asked_by_a_rebuild(frozen):
    reasked = [(i, e) for i, e, *_ in bs.SIGNATURES
               if frozen.needs_resolution(i, e)]
    assert reasked == [], (
        f"{len(reasked)} signed rows would be handed back to the model, "
        f"replacing a human judgement with a sampled one")


def test_a_signed_refusal_to_rule_is_settled_not_pending(frozen):
    """⭐ THE DISTINCTION THIS GATE EXISTS FOR. Both spell UNRESOLVED."""
    signed_open = [(i, e) for i, e, d, *_ in bs.SIGNATURES
                   if d == bs.UNRESOLVED]
    assert len(signed_open) == 3

    for identity, evidence in signed_open:
        annotation = frozen.get(identity, evidence)
        assert sa.reviewed(annotation)
        assert not frozen.needs_resolution(identity, evidence)
        # settled does NOT mean priceable — it means nobody re-rolls it
        assert not sa.eligible(annotation)
        assert sa.disposition(annotation) == "unresolved_reviewed"

    never_seen = sa.Store()
    assert never_seen.needs_resolution("kiwi|", "usda:1")
    assert sa.disposition(None) == "unresolved_never_annotated"


def test_an_unsigned_unresolved_row_is_still_re_asked():
    """The review status is what settles a row — not the relationship. Absent
    a signature, UNRESOLVED means exactly what it always meant."""
    store = sa.Store()
    store.record(sa.Annotation("kiwi|", "usda:1", sa.UNRESOLVED))
    assert store.needs_resolution("kiwi|", "usda:1")
    assert sa.disposition(store.get("kiwi|", "usda:1")) == "unresolved"


def test_a_changed_source_still_reopens_a_signed_row(worksheet):
    """A signature is about the row AS IT STOOD. Republished content is a
    different row, and `source_changed` is the attributable cause."""
    store = sa.Store()
    identity, evidence, *_ = bs.SIGNATURES[0]
    store.record(sa.Annotation(identity, evidence, sa.SAME_IDENTITY,
                               confidence=0.9, source_fingerprint="before"))
    bs.freeze(store, worksheet)

    assert store.get(identity, evidence).source_fingerprint == "before"
    assert not store.needs_resolution(identity, evidence, "before")
    assert store.needs_resolution(identity, evidence, "after")
    assert store.stale_source(identity, evidence, "after")


# ── 3. a signature is not an invalidation ─────────────────────────────────

def test_the_freeze_does_not_invalidate_the_rows_it_admits(frozen):
    """⚠ THE TRAP THIS GATE PINS DOWN. `baseline_migration` is the CAUSE
    authorising replacement, not a property of the resulting annotation.
    Writing it into `invalidation_reason` would make every admitted row
    ineligible and empty the artifact the review exists to populate."""
    admitted = [(i, e) for i, e, d, *_ in bs.SIGNATURES if d == bs.ADMIT]
    assert len(admitted) == 29

    for identity, evidence in admitted:
        annotation = frozen.get(identity, evidence)
        assert annotation.invalidation_reason == ""
        assert sa.eligible(annotation)
        assert sa.disposition(annotation) == "priceable"

    assert sum(1 for a in frozen.by_key.values() if sa.eligible(a)) == 29


def test_a_rejected_row_is_kept_and_explained_never_deleted(frozen):
    rejected = [(i, e) for i, e, d, *_ in bs.SIGNATURES if d == bs.REJECT]
    assert len(rejected) == 45
    for identity, evidence in rejected:
        annotation = frozen.get(identity, evidence)
        assert annotation is not None, "evidence was deleted, not explained"
        assert not sa.eligible(annotation)
        assert sa.disposition(annotation) == "different_identity"


def test_the_same_record_can_be_admitted_for_one_request_and_rejected_for_another(frozen):
    """⭐⭐⭐ Identity is a RELATION between a request and a record. Breaded
    shrimp legitimately describes `shrimp|fried` and does not describe bare
    `shrimp|` — so a table keyed on the record alone could not hold both."""
    breaded = "usda:171970"
    assert sa.eligible(frozen.get("shrimp|fried", breaded))
    assert not sa.eligible(frozen.get("shrimp|", breaded))


# ── 4. the migration closes behind itself ─────────────────────────────────

def test_baseline_migration_is_unavailable_once_the_freeze_completes(frozen):
    assert not sa.baseline_migration_open()
    identity, evidence, *_ = bs.SIGNATURES[0]
    with pytest.raises(sa.AnnotationReplacementRefused) as caught:
        frozen.record(sa.Annotation(identity, evidence, sa.DIFFERENT_IDENTITY),
                      cause=sa.BASELINE_MIGRATION)
    assert "admissible only while" in str(caught.value)


def test_an_ordinary_rebuild_cannot_overwrite_a_signature(frozen):
    identity, evidence, *_ = bs.SIGNATURES[0]
    with pytest.raises(sa.AnnotationReplacementRefused):
        frozen.record(sa.Annotation(identity, evidence, sa.DIFFERENT_IDENTITY))


def test_a_signature_records_a_human_not_a_model(frozen):
    for identity, evidence, *_ in bs.SIGNATURES:
        annotation = frozen.get(identity, evidence)
        assert annotation.resolver_model == bs.REVIEWER
        assert annotation.review_status == sa.BASELINE_REVIEWED
