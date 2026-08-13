"""Remove REJECTED evidence from the artifact, and say who removed it and why.

⭐ THIS IS A DESTRUCTIVE OPERATION AND IS TREATED AS ONE. Dropping a candidate
is the mechanism that makes an artifact disagree with its own history, and the
whole pricing spine is built on the rule that a change must be ATTRIBUTABLE.
So each removal is written into the artifact next to the entry it left, with
the identity, the evidence, the round that decided it and the stated reason —
a rebuild that leaves no trace is indistinguishable from silent drift.

⭐⭐ AND THE SUCCESSOR IS REPORTED, NEVER ASSUMED. Removing "Potatoes, raw,
SKIN" does not promote boiled flesh at 87; the ladder rises to "skin with
salt" at 132, a row already signed ADMIT. Rejecting a part-of-food record is
an ADMISSION fix and does not by itself produce a good winner — so this prints
the new winner and leaves signing it to the winner review.
"""
from __future__ import annotations

import json
import sys

from scripts import baseline_signatures as bs
from scripts import winner_review as wr
from skills.nutrition import pricing_artifact as art

ROUND = "phase_0.9_winner_review"


def apply(dry_run: bool = True) -> dict:
    document = json.loads(art.ARTIFACT_PATH.read_text())
    entries = document.get("entries") or {}
    removed = list(document.get("removed_evidence") or ())
    already = {(r["identity"], r["evidence_id"]) for r in removed}
    report = {"removed": [], "successors": {}, "skipped": []}

    for identity, evidence, disposition, reason, note in wr.ADMISSION_DECISIONS:
        if disposition != bs.REJECT:
            continue
        if (identity, evidence) in already:
            report["skipped"].append((identity, evidence, "already removed"))
            continue
        entry = entries.get(identity)
        if not entry:
            report["skipped"].append((identity, evidence, "identity absent"))
            continue

        # ⛔ NEVER `evidence.split(":")[-1]`. That discarded the source
        # namespace at the exact point the operation becomes irreversible, so
        # a rejection naming `usda:123` would also have deleted `ciqual:123`.
        # The portability invariant proves the ANNOTATION STORE keeps those
        # apart; this is the tool that has to honour it.
        keep = [c for c in (entry.get("candidates") or ())
                if art.candidate_evidence_id(c) != evidence]
        if len(keep) == len(entry.get("candidates") or ()):
            report["skipped"].append((identity, evidence, "candidate absent"))
            continue
        if not keep:
            # ⛔ REFUSED. An identity with no candidates prices from NOTHING,
            # which is the exact failure `artifact_candidates_present_but_
            # ranker_returned_none` was added to make visible. Emptying an
            # entry to honour a rejection would trade a wrong price for no
            # price without anyone deciding that trade was acceptable.
            raise SystemExit(
                f"{identity}: rejecting {evidence} would empty the entry. "
                f"Refusing — that is a retrieval decision, not an admission one")

        entry["candidates"] = keep
        removed.append({"identity": identity, "evidence_id": evidence,
                        "reason": reason, "note": note, "round": ROUND})
        report["removed"].append((identity, evidence, reason))

    document["removed_evidence"] = removed

    # ⭐ THE REGIME IS DECLARED, NOT ASSEMBLED HERE. This used to set
    # NUTRITION_ACCURACY_V2 by hand and INHERIT the as-eaten preference from
    # whatever the caller's shell carried — so a developer with the flag
    # exported would have computed a different successor, silently, in a tool
    # that writes to the production artifact.
    from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime
    with ranking_regime(PHASE_0_REGIME):
        import core.food_intelligence as fi
        from core.canonical_pricing import _ranker_query
        for identity, _evidence, _reason in report["removed"]:
            entity, _, preparation = identity.partition("|")
            winner, conf = fi.best_candidate(
                _ranker_query(entity, preparation),
                list((entries.get(identity) or {}).get("candidates") or ()))
            report["successors"][identity] = (
                None if winner is None else
                (art.candidate_evidence_id(winner),
                 (winner.get("per100g") or {}).get("calories"),
                 winner.get("description"), conf))
        report["ranking_policy_version"] = PHASE_0_REGIME

    if not dry_run:
        art.ARTIFACT_PATH.write_text(json.dumps(document, indent=1) + "\n")
    return report


if __name__ == "__main__":
    write = "--write" in sys.argv
    result = apply(dry_run=not write)
    print(f"  {'WRITING' if write else 'DRY RUN'}\n")
    for identity, evidence, reason in result["removed"]:
        print(f"  removed  {identity:<14} {evidence:<14} {reason}")
        successor = result["successors"].get(identity)
        if successor is None:
            print("           ⛔ NO SUCCESSOR — the identity now prices from nothing")
        else:
            eid, kcal, description, conf = successor
            print(f"           successor {eid} {kcal} kcal [{conf}]")
            print(f"                     {description}")
    for identity, evidence, why in result["skipped"]:
        print(f"  skipped  {identity:<14} {evidence:<14} {why}")
    if not result["removed"]:
        print("  nothing to remove")
