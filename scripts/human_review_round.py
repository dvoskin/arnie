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


def apply(store, *, source_fingerprints=None) -> list:
    """Write this round into `store`, returning the ledger of what moved."""
    source_fingerprints = source_fingerprints or {}
    ledger = []

    sa.open_baseline_migration()
    try:
        for identity, evidence, disposition, reason, note in \
                wr.ADMISSION_OVERRIDES:
            previous = store.get(identity, evidence)
            was = previous.relationship if previous else None
            if disposition != wr.bs.ADMIT:
                raise SystemExit(
                    f"{identity}/{evidence}: this round only ADMITS; a "
                    f"rejection belongs to the round that can explain it")

            store.record(sa.Annotation(
                identity_key=identity,
                evidence_id=evidence,
                relationship=_ADMIT_RELATIONSHIP,
                confidence=1.0,
                resolver_model=REVIEWER,
                resolver_version=reason,
                source_fingerprint=(source_fingerprints.get((identity, evidence))
                                    or getattr(previous, "source_fingerprint",
                                               "") or ""),
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
