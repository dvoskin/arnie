"""G2 — A HUMAN DECISION MUST ENTER THE STORE, NOT THE WINNER REVIEW.

⛔ THE GAP THIS CLOSES. The eight-row adjudication lived in
`winner_review.py`, and `build_one` decides candidates by reading
`sa.eligible(annotation)`. So three mackerel species a reviewer ADMITTED would
have stayed `DIFFERENT_IDENTITY` in the store and simply not reappeared — the
review would have been recorded, agreed with, and had no effect. A decision
that changes ELIGIBILITY has to be written where eligibility is read.

    winner_review.py   REPRESENTATIVENESS — is this the row we want to win?
    annotation store   ADMISSION — is this legitimately this food?

⭐ AND A REPLACEMENT MUST BE ATTRIBUTABLE, NOT MERELY POSSIBLE. Every row
records what it changed FROM, what it changed TO, who decided, under which
cause, against which source fingerprint, in which round. Without the old
disposition a future reader cannot tell a correction from an original
judgement, and the two carry very different weight — one of these rounds
exists precisely because the resolver contradicted itself.

⭐⭐ THE FROZEN 77 ARE NOT AMENDED. This is a NEW round, additive and named,
exactly as the Phase 0.9 admission decisions were. Editing a closed, gated,
migration-sealed population would make the record stop saying what was signed.
"""
from __future__ import annotations

import json
import pathlib
import sys

from scripts import winner_review as wr
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa

ROUND = "phase_0.9b_delta_review"
REVIEWER = "human:phase_0.9b_delta_review"

LEDGER_PATH = (pathlib.Path(__file__).resolve().parents[1]
               / "data" / "baseline" / "phase_0_9b_review_round.json")

#: The relationship a human ADMIT asserts. `COMPATIBLE_SPECIALIZATION` rather
#: than `SAME_IDENTITY` because every row in this round is a specialization —
#: a mackerel species, a battered form, a brined breast, a canned form — and
#: claiming exact identity would overstate what was actually reviewed.
_ADMIT_RELATIONSHIP = sa.COMPATIBLE_SPECIALIZATION


class SourceFingerprintUnavailable(SystemExit):
    """A review cannot be bound to a source row that cannot be identified."""


def fingerprints_from_capture(capture=None) -> dict:
    """`{(identity, evidence_id): row_fingerprint}` for every admitted pair.

    ⛔ THE DEFECT THIS REPLACES. `apply()` took `source_fingerprints` as an
    optional kwarg, `__main__` called `apply(store)` without it, and the value
    fell through to `""`. All six decisions shipped with a BLANK fingerprint —
    so a reviewed annotation was not bound to the row it reviewed, and
    `stale_source()` could never fire for them, because its comparison
    requires an existing fingerprint on both sides. An optional argument
    nobody passes is not a default; it is a hole.

    ⭐ AND EVERY OCCURRENCE IS CHECKED, NOT THE FIRST ONE FOUND. A row can be
    returned by more than one query shape, so the same source-qualified
    evidence id legitimately appears several times in the capture. Identical
    content must fingerprint identically. If it does not, the capture is
    telling us one evidence id describes two different rows — and taking
    whichever came first would bind the review to an arbitrary one of them.
    That is a refusal, not a tie-break.
    """
    from scripts import capture_retrieval as cr
    from scripts.build_pricing_artifact import _row_fingerprint

    if capture is None:
        if not cr.CAPTURE_PATH.exists():
            raise SourceFingerprintUnavailable(
                f"no seam capture at {cr.CAPTURE_PATH.name} — a review cannot "
                f"be bound to a source row without one")
        capture = json.loads(cr.CAPTURE_PATH.read_text())

    wanted = {(identity, evidence)
              for identity, evidence, *_ in wr.ADMISSION_OVERRIDES}
    found: dict = {}
    for identity, records in (capture.get("queries") or {}).items():
        for record in records:
            for row in record.get("rows") or ():
                evidence = f"usda:{row.get('fdc_id')}"
                if (identity, evidence) in wanted:
                    found.setdefault((identity, evidence), set()).add(
                        _row_fingerprint(row))

    fingerprints, failures = {}, []
    for pair in sorted(wanted):
        prints = found.get(pair)
        if not prints:
            failures.append(f"{pair[0]}/{pair[1]}: admitted by a reviewer and "
                            f"absent from the capture — the decision cannot "
                            f"be bound to a source row")
        elif len(prints) > 1:
            failures.append(f"{pair[0]}/{pair[1]}: {len(prints)} DIFFERENT row "
                            f"fingerprints for one evidence id "
                            f"({sorted(prints)}) — one id is describing two "
                            f"rows, and picking either would be arbitrary")
        else:
            fingerprints[pair] = next(iter(prints))

    if failures:
        raise SourceFingerprintUnavailable("\n  ".join(["", *failures]))
    return fingerprints


def _prior_dispositions() -> dict:
    """What each pair was BEFORE this round, from the committed ledger.

    ⭐ THE OLD DISPOSITION IS A HISTORICAL FACT, NOT A RE-READING OF THE STORE.
    Once the round is applied the store says `COMPATIBLE_SPECIALIZATION`, so
    re-deriving `was` from it would record that the reviewer changed nothing —
    erasing the very thing this round exists to show, that the resolver marked
    three mackerel species DIFFERENT_IDENTITY while admitting five salmon of
    the same class. When the ledger exists it is the authority for `was`.
    """
    if not LEDGER_PATH.exists():
        return {}
    ledger = json.loads(LEDGER_PATH.read_text())
    return {(row["identity_key"], row["evidence_id"]): row["was"]
            for row in (ledger.get("rows") or ())}


def apply(store, *, source_fingerprints=None) -> list:
    """Write this round into `store`, returning the ledger of what moved."""
    # ⛔ DERIVED, NOT DEFAULTED TO EMPTY. See `fingerprints_from_capture`.
    if source_fingerprints is None:
        source_fingerprints = fingerprints_from_capture()
    prior = _prior_dispositions()
    ledger = []

    sa.open_baseline_migration()
    try:
        for identity, evidence, disposition, reason, note in \
                wr.ADMISSION_OVERRIDES:
            previous = store.get(identity, evidence)
            # the committed ledger outranks the store, which this round has
            # already moved — see `_prior_dispositions`
            was = prior.get((identity, evidence),
                            previous.relationship if previous else None)
            if disposition != wr.bs.ADMIT:
                raise SystemExit(
                    f"{identity}/{evidence}: this round only ADMITS; a "
                    f"rejection belongs to the round that can explain it")

            fingerprint = source_fingerprints.get((identity, evidence)) or ""
            if not fingerprint:
                # ⛔ NEVER "" AGAIN. A blank fingerprint is not a weaker
                # binding, it is the ABSENCE of one: `stale_source()` compares
                # only when both sides carry a value, so an unbound review can
                # never be invalidated by the row moving underneath it.
                raise SourceFingerprintUnavailable(
                    f"{identity}/{evidence}: no source fingerprint — refusing "
                    f"to write a review that is not bound to its row")

            store.record(sa.Annotation(
                identity_key=identity,
                evidence_id=evidence,
                relationship=_ADMIT_RELATIONSHIP,
                confidence=1.0,
                resolver_model=REVIEWER,
                resolver_version=reason,
                source_fingerprint=fingerprint,
                review_status=sa.BASELINE_REVIEWED,
            ), cause=sa.MANUAL_INVALIDATION)

            ledger.append({
                "round": ROUND,
                "identity_key": identity,
                "evidence_id": evidence,
                "was": was,
                "now": _ADMIT_RELATIONSHIP,
                "reviewer": REVIEWER,
                "cause": sa.MANUAL_INVALIDATION,
                "reason": reason,
                "note": note,
                "source_fingerprint": store.get(
                    identity, evidence).source_fingerprint,
            })
    finally:
        sa.close_baseline_migration()
    return ledger


def verify(store, ledger) -> tuple:
    failures = []
    if len(ledger) != len(wr.ADMISSION_OVERRIDES):
        failures.append(f"{len(ledger)} rows written, "
                        f"{len(wr.ADMISSION_OVERRIDES)} adjudicated")
    for row in ledger:
        annotation = store.get(row["identity_key"], row["evidence_id"])
        if annotation is None:
            failures.append(f"{row['identity_key']}: not in the store")
            continue
        if not sa.eligible(annotation):
            failures.append(f"{row['identity_key']}/{row['evidence_id']}: "
                            f"ADMITTED by a reviewer and still not eligible — "
                            f"the decision did not reach the layer that reads it")
        if not sa.reviewed(annotation):
            failures.append(f"{row['identity_key']}: no review status")
        if annotation.resolver_model != REVIEWER:
            failures.append(f"{row['identity_key']}: provenance is not human")
        # ⛔ BOUND TO THE ROW IT REVIEWED. All six shipped with "" — reviewed,
        # attributable in every other field, and floating free of the evidence.
        if not annotation.source_fingerprint:
            failures.append(f"{row['identity_key']}/{row['evidence_id']}: "
                            f"reviewed and NOT BOUND to a source row — "
                            f"stale_source() can never fire for it")
        if row["source_fingerprint"] != annotation.source_fingerprint:
            failures.append(f"{row['identity_key']}: ledger records "
                            f"{row['source_fingerprint']!r}, store holds "
                            f"{annotation.source_fingerprint!r}")
        if row["was"] == row["now"]:
            failures.append(f"{row['identity_key']}: recorded as changed but "
                            f"{row['was']} == {row['now']}")
        if ":" not in row["evidence_id"]:
            failures.append(f"{row['identity_key']}: evidence not "
                            f"source-qualified")
        # ⛔ AND AN ORDINARY REBUILD MUST NOT BE ABLE TO UNDO IT
        try:
            store.record(sa.Annotation(row["identity_key"], row["evidence_id"],
                                       sa.DIFFERENT_IDENTITY))
            failures.append(f"{row['identity_key']}: a rebuild overwrote a "
                            f"human decision without a cause")
        except sa.AnnotationReplacementRefused:
            pass
        if store.needs_resolution(row["identity_key"], row["evidence_id"]):
            failures.append(f"{row['identity_key']}: would be re-asked")
    return tuple(failures)


if __name__ == "__main__":
    document = json.loads(art.ARTIFACT_PATH.read_text())
    store = sa.Store.from_payload(
        (document.get("meta") or {}).get("annotations") or {})
    ledger = apply(store)
    failures = verify(store, ledger)

    print(f"  HUMAN REVIEW ROUND · {ROUND}\n")
    for row in ledger:
        print(f"    {row['identity_key']:<18} {row['evidence_id']:<14} "
              f"{str(row['was']):<26} -> {row['now']}")
    for failure in failures:
        print(f"    ⛔ {failure}")
    if failures:
        raise SystemExit(1)
    print(f"\n  ✅ {len(ledger)} decisions in the ANNOTATION STORE, "
          f"attributable, and unre-rollable by an ordinary rebuild")

    if "--write" in sys.argv:
        document.setdefault("meta", {})["annotations"] = store.to_payload()
        art.ARTIFACT_PATH.write_text(json.dumps(document, indent=1) + "\n")
        LEDGER_PATH.write_text(json.dumps(
            {"round": ROUND, "rows": ledger}, indent=1) + "\n")
        print(f"  -> {LEDGER_PATH.name} + artifact annotations")
