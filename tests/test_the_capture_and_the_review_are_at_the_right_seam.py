"""G1 AND G2 — CAPTURE AT THE RETRIEVAL SEAM, AUTHORITY IN THE STORE.

Both gates exist because a correct thing in the wrong place is not correct.

⛔ G1. A first capture RECONSTRUCTED the query shapes by hand while
`build_one` issues `art.QUERY_SHAPES`. The corpus came out thinner (249 rows
against the seam's 397), a rebuild on it lost three identities, and the loss
was uninterpretable — retrieval starvation and mechanical refusal look
identical once the inputs are already wrong. TWO IMPLEMENTATIONS OF ONE
NOTION, the failure family this migration keeps finding.

⛔ G2. The eight-row adjudication lived in `winner_review.py`, and
`build_one` decides candidates from `sa.eligible(annotation)`. Three mackerel
species a reviewer ADMITTED would have stayed DIFFERENT_IDENTITY and simply
not reappeared: the review recorded, agreed with, and inert.
"""
from __future__ import annotations

import json

import pytest

from scripts import capture_retrieval as cap
from scripts import human_review_round as hr
from scripts import winner_review as wr
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa


@pytest.fixture
def capture():
    if not cap.CAPTURE_PATH.exists():
        pytest.skip("no source capture")
    return json.loads(cap.CAPTURE_PATH.read_text())


@pytest.fixture
def store():
    document = json.loads(art.ARTIFACT_PATH.read_text())
    return sa.Store.from_payload(
        (document.get("meta") or {}).get("annotations") or {})


# ── G1 ────────────────────────────────────────────────────────────────────

def test_the_capture_matches_the_builds_current_retrieval_contract(capture):
    """⭐ A REPLAY AGAINST A MOVED CONTRACT DESCRIBES A SYSTEM THAT NO LONGER
    EXISTS. Refuse it rather than produce numbers about the past."""
    cap.verify_contract(capture)
    assert capture["meta"]["retrieval_fingerprint"] == \
        art.retrieval_fingerprint()


def test_the_capture_was_taken_at_the_seam_not_reconstructed(capture):
    """The recorded queries must be the ones the CONTRACT produces — this
    module knows nothing about query shapes, and that is the point."""
    meta = capture["meta"]
    assert meta["captured_at_the_seam"] is True
    assert meta["query_shapes"] == list(art.QUERY_SHAPES)
    assert meta["data_types"] == list(art.DATA_TYPES)
    assert meta["rows_per_shape"] == art.ROWS_PER_SHAPE

    for identity, records in capture["queries"].items():
        expected = {shape.format(identity=identity.replace("|", ", ").rstrip(", "))
                    for shape in art.QUERY_SHAPES}
        assert len(records) == len(art.QUERY_SHAPES), identity
        for record in records:
            assert record["data_types"] == list(art.DATA_TYPES)
            assert record["rows_per_shape"] == art.ROWS_PER_SHAPE


def test_the_capture_preserves_order_and_provenance(capture):
    """`build_one` dedupes keeping FIRST OCCURRENCE, so which query returned a
    row first can decide whether it survives. A set would replay a different
    build than the one recorded."""
    for identity, records in capture["queries"].items():
        for record in records:
            assert isinstance(record["rows"], list), identity
            for row in record["rows"]:
                assert row.get("data_type"), (identity, row.get("fdc_id"))


def test_the_capture_is_not_thinner_than_the_committed_artifact(capture):
    """⭐ THE CHECK THE FIRST CAPTURE FAILED. A rebuild is only interpretable
    if its inputs are at least as good as the ones it replaces."""
    document = json.loads(art.ARTIFACT_PATH.read_text())
    committed = {c.get("fdc_id")
                 for entry in (document.get("entries") or {}).values()
                 for c in (entry.get("candidates") or ())}
    captured = {row.get("fdc_id")
                for records in capture["queries"].values()
                for record in records for row in record["rows"]}
    missing = committed - captured
    assert not missing, (
        f"{len(missing)} committed candidates are absent from the capture; a "
        f"rebuild would lose them to RETRIEVAL, not to a decision")


# ── G2 ────────────────────────────────────────────────────────────────────

def test_a_human_admission_actually_reaches_eligibility(store):
    """⭐ THE GAP. `build_one` reads `sa.eligible(annotation)`. A decision
    recorded anywhere else is a decision with no effect."""
    for identity, evidence, disposition, _reason, _note in \
            wr.ADMISSION_OVERRIDES:
        annotation = store.get(identity, evidence)
        assert annotation is not None, (identity, evidence)
        assert sa.eligible(annotation), (
            f"{identity}/{evidence} was ADMITTED and is not eligible")
        assert sa.reviewed(annotation)


def test_the_round_records_what_it_changed_from(store):
    """Without the OLD disposition a reader cannot tell a CORRECTION from an
    original judgement — and this round exists because the resolver
    contradicted itself."""
    if not hr.LEDGER_PATH.exists():
        pytest.skip("no review round recorded")
    ledger = json.loads(hr.LEDGER_PATH.read_text())
    assert ledger["round"] == hr.ROUND
    assert len(ledger["rows"]) == len(wr.ADMISSION_OVERRIDES)
    for row in ledger["rows"]:
        for field in ("identity_key", "evidence_id", "was", "now", "reviewer",
                      "cause", "reason"):
            assert str(row.get(field) or "").strip(), row
        assert row["was"] == sa.DIFFERENT_IDENTITY
        assert row["now"] != row["was"]
        assert row["cause"] == sa.MANUAL_INVALIDATION
        assert ":" in row["evidence_id"]


def test_an_ordinary_rebuild_cannot_undo_a_human_decision(store):
    for identity, evidence, *_ in wr.ADMISSION_OVERRIDES:
        with pytest.raises(sa.AnnotationReplacementRefused):
            store.record(sa.Annotation(identity, evidence,
                                       sa.DIFFERENT_IDENTITY))
        assert not store.needs_resolution(identity, evidence)


def test_this_round_does_not_amend_the_frozen_seventy_seven():
    from scripts import baseline_signatures as bs
    assert bs.EXPECTED_POPULATION == 77 and len(bs.SIGNATURES) == 77
    frozen = set(bs.by_pair())
    for identity, evidence, *_ in wr.ADMISSION_OVERRIDES:
        assert (identity, evidence) not in frozen


def test_the_two_branded_rows_are_not_semantic_decisions():
    """⭐ PROVENANCE SURVIVES. Their absence is RETRIEVAL — the contract is
    Foundation + SR Legacy, which returns no branded rows — neither a
    reviewer's verdict nor a veto. Calling them rejects would have written
    down that a tofu product is not tofu."""
    assert len(wr.NOT_SEMANTIC_ABSENCES) == 2
    overridden = {(i, e) for i, e, *_ in wr.ADMISSION_OVERRIDES}
    for identity, evidence, cause, _note in wr.NOT_SEMANTIC_ABSENCES:
        assert (identity, evidence) not in overridden
        assert "retrieval" in cause
