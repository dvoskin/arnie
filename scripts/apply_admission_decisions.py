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

        fdc = evidence.split(":", 1)[-1]
        keep = [c for c in (entry.get("candidates") or ())
                if str(c.get("fdc_id")) != fdc]
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

    # the successor under the regime Phase 0 freezes against
    import os
    previous = os.environ.get("NUTRITION_ACCURACY_V2")
    os.environ["NUTRITION_ACCURACY_V2"] = "1"
    try:
        import importlib
        import core.food_intelligence as fi
        importlib.reload(fi)
        from core.canonical_pricing import _ranker_query
        for identity, _evidence, _reason in report["removed"]:
            entity, _, preparation = identity.partition("|")
            winner, conf = fi.best_candidate(
                _ranker_query(entity, preparation),
                list((entries.get(identity) or {}).get("candidates") or ()))
            report["successors"][identity] = (
                None if winner is None else
                (f"usda:{winner.get('fdc_id')}",
                 (winner.get("per100g") or {}).get("calories"),
                 winner.get("description"), conf))
    finally:
        if previous is None:
            os.environ.pop("NUTRITION_ACCURACY_V2", None)
        else:
            os.environ["NUTRITION_ACCURACY_V2"] = previous

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
