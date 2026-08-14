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
from skills.nutrition import preparation_ontology as prep_onto
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
        # ⭐ NAMED BY THE REAL PRODUCER, NOT BY A RESTATEMENT OF IT.
        # `build_one` spells the identity with `prep_onto.name_with`. Writing
        # that transform out again here would make this gate a SECOND
        # implementation of the notion it exists to check — and two
        # implementations of one notion is the defect family that produced
        # the thin capture in the first place.
        entity, _, preparation = identity.partition("|")
        name = prep_onto.name_with(entity, preparation) if preparation \
            else entity
        expected = {shape.format(identity=name) for shape in art.QUERY_SHAPES}

        # ⛔ THE ASSERTION THIS GATE WAS MISSING. `expected` was computed and
        # then never compared against anything. The docstring promised "the
        # recorded queries must be the ones the CONTRACT produces" while the
        # body only counted the records and read their metadata — so a
        # capture holding the RIGHT NUMBER of the WRONG QUERIES passed. That
        # is exactly the capture this gate was written to reject.
        assert {record["query"] for record in records} == expected, identity

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
    assert len(ledger["rows"]) == len(hr._eligibility_decisions())
    for row in ledger["rows"]:
        # ⛔ `source_fingerprint` WAS THE ONE ATTRIBUTABLE FIELD MISSING FROM
        # THIS TUPLE, and it was "" on all six rows. The gate checked every
        # field that was populated and none that was not, which is how a
        # commit could claim the six carry "was / now / reviewer / cause /
        # source fingerprint / round" with five of six true.
        for field in ("identity_key", "evidence_id", "was", "now", "reviewer",
                      "cause", "reason", "source_fingerprint"):
            assert str(row.get(field) or "").strip(), row
        # ⚠ THIS ASSERTED `was == DIFFERENT_IDENTITY` and was too specific.
        # It was true only while every row was an ADMISSION of something the
        # model had rejected. The potato rejection is the mirror image — the
        # model had said SAME_IDENTITY — and hardcoding one direction would
        # have made the gate refuse the very symmetry it should protect.
        # The real invariant is that the round MOVED something.
        assert row["was"] in sa.RELATIONSHIPS
        assert row["now"] != row["was"]
        assert row["cause"] == sa.MANUAL_INVALIDATION
        assert ":" in row["evidence_id"]


def test_every_human_admission_is_bound_to_the_row_it_reviewed(store, capture):
    """⛔ A REVIEW THAT IS NOT BOUND TO ITS EVIDENCE CANNOT BE INVALIDATED BY
    THE EVIDENCE MOVING. `stale_source()` compares fingerprints only when BOTH
    sides carry one, so a blank fingerprint does not weaken the binding — it
    removes it, silently and permanently, for exactly the six rows a human
    took the trouble to adjudicate."""
    derived = hr.fingerprints_from_capture(capture)

    for identity, evidence, *_ in wr.ADMISSION_OVERRIDES:
        annotation = store.get(identity, evidence)
        assert annotation.source_fingerprint, (identity, evidence)
        assert annotation.source_fingerprint == derived[(identity, evidence)], (
            f"{identity}/{evidence} is bound to a fingerprint the capture "
            f"does not produce")
        assert not store.stale_source(identity, evidence,
                                      derived[(identity, evidence)])


def test_one_evidence_id_with_two_row_fingerprints_is_refused(capture):
    """⭐ CAUSAL, and it is about which failure is SAFE. An evidence id found
    twice with different content means one source-qualified id is describing
    two rows. Taking whichever came first would bind a human decision to an
    arbitrary one of them and record it as though it were considered."""
    identity, evidence, *_ = wr.ADMISSION_OVERRIDES[0]
    forged = json.loads(json.dumps(capture))

    for record in forged["queries"][identity]:
        for row in record["rows"]:
            if f"usda:{row.get('fdc_id')}" == evidence:
                row["description"] = row.get("description", "") + " (ALTERED)"
                break
        break

    with pytest.raises(hr.SourceFingerprintUnavailable) as caught:
        hr.fingerprints_from_capture(forged)
    assert "DIFFERENT row fingerprints" in str(caught.value)


def test_an_admission_absent_from_the_capture_is_refused(capture):
    """The other half: a decision about a row the capture does not hold
    cannot be bound to anything, and must not default to blank."""
    stripped = json.loads(json.dumps(capture))
    identity, evidence, *_ = wr.ADMISSION_OVERRIDES[0]
    for record in stripped["queries"][identity]:
        record["rows"] = [row for row in record["rows"]
                          if f"usda:{row.get('fdc_id')}" != evidence]

    with pytest.raises(hr.SourceFingerprintUnavailable) as caught:
        hr.fingerprints_from_capture(stripped)
    assert "absent from the capture" in str(caught.value)


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


# ── the symmetry rule: BOTH directions live in the store ─────────────────

def test_every_human_eligibility_decision_lives_in_the_store(store):
    """⭐ THE OWNERSHIP RULE, ENFORCED IN BOTH DIRECTIONS.

        An eligibility-affecting human decision is authoritative ONLY when it
        lives in the semantic annotation store, is bound to the exact source
        fingerprint, and is consumed by `sa.eligible()`.

    `winner_review` may keep them as audit context; it must never be the ONLY
    place one exists. The round originally carried ADMITs alone, so six
    admissions reached the store and one rejection did not — and `usda:170032`,
    a part-of-food row a reviewer refused, came back the instant the seam
    capture re-retrieved it and the writer annotated it `SAME_IDENTITY`."""
    from scripts import baseline_signatures as bs

    for identity, evidence, disposition, *_ in hr._eligibility_decisions():
        annotation = store.get(identity, evidence)
        assert annotation is not None, (identity, evidence)
        assert sa.reviewed(annotation), (identity, evidence)
        assert sa.eligible(annotation) is (disposition == bs.ADMIT), (
            f"{identity}/{evidence}: reviewer said {disposition} and "
            f"sa.eligible says {sa.eligible(annotation)}")
        assert annotation.source_fingerprint, (
            f"{identity}/{evidence}: unbound — `stale_source` compares only "
            f"when both sides carry a value, so this review could never be "
            f"invalidated by its row moving")


def test_a_human_rejection_is_carried_not_just_an_admission():
    """ANTI-VACUITY. If the round ever silently drops REJECTs again, the
    counts diverge here before a rebuild can re-admit anything."""
    from scripts import baseline_signatures as bs

    decisions = hr._eligibility_decisions()
    rejects = [d for d in decisions if d[2] == bs.REJECT]
    admits = [d for d in decisions if d[2] == bs.ADMIT]
    assert rejects, "the round carries no rejection — the asymmetry is back"
    assert admits and len(decisions) == len(rejects) + len(admits)


def test_the_rejected_part_of_food_row_stays_out_attributably(store):
    """⛔ THE REGRESSION THIS CLOSES, pinned to its row. Its absence must be a
    NAMED HUMAN DECISION — not a veto, not a resolver verdict, not silence."""
    import json

    annotation = store.get("potato|", "usda:170032")
    assert annotation is not None
    assert annotation.relationship == sa.DIFFERENT_IDENTITY
    assert not sa.eligible(annotation)
    assert sa.reviewed(annotation)
    assert annotation.resolver_model.startswith("human:")
    assert annotation.resolver_version == "part_of_food_not_the_food"
    assert annotation.source_fingerprint

    document = json.loads(art.ARTIFACT_PATH.read_text())
    present = {art.candidate_evidence_id(c)
               for c in (document["entries"]["potato|"].get("candidates") or ())}
    assert "usda:170032" not in present


def test_a_reviewed_rejection_is_never_re_asked(store):
    """The writer must not re-annotate a row a human ruled on — which is how
    it became SAME_IDENTITY in the first place."""
    assert not store.needs_resolution("potato|", "usda:170032")
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(sa.Annotation("potato|", "usda:170032", sa.SAME_IDENTITY))
