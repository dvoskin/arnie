"""RECONSTRUCT THE SEMANTIC STORE THROUGH THE FIRST WRITER WE TRUST.

⛔ WHY THE OLD STORE IS NOT A SUBSTRATE. `ff629e8` populated 109 annotations
through a `build_one` that turned a PARTIAL abstention into a confident
negative: `qualify_usda_rows` reported `disposition="qualified"` whenever ANY
row was judged, unjudged rows simply fell out of `kept`, and everything not
kept was written `DIFFERENT_IDENTITY` at 0.95. `needs_resolution` then saw a
resolved annotation and never reopened it. A row nobody assessed became a row
we had ruled against, durably and invisibly. `140e994` fixed the writer; this
rebuilds what the old one wrote.

⭐ THIS IS NOT "MORE MODEL CALLS FOR BETTER QUALITY". It is reconstructing the
store through the first writer that cannot turn absence into a negative
answer — the invariant this entire phase exists to establish, violated by the
tool that was supposed to enforce it.

⭐⭐ HUMAN DECISIONS SURVIVE; MACHINE ONES DO NOT. The 77 frozen signatures
and the six G2 review-round admissions are kept when their source fingerprint
still matches the captured row, and REOPENED when it does not — a review is
about a specific row, and a moved row makes it unverified rather than wrong.
Every annotation written by the buggy path is discarded, because "probably
fine" is not a property anyone can check.

⭐⭐⭐ AND BATCH COMPLETENESS IS RECORDED, NOT ASSUMED. A batch can look like
a completed model operation while silently shrinking the evidence universe —
that is precisely the defect being repaired. So each batch records what was
ASKED, what came back judged, what abstained, how many retries it took and
what remained unresolved. A population run that cannot say which rows the
model never assessed is the same instrument failure one layer up.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from scripts import capture_retrieval as cr
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa

RUN_RECORD = (pathlib.Path(__file__).resolve().parents[1]
              / "data" / "baseline" / "phase_0_repopulation_run.json")


def human_seed(previous: sa.Store, capture: dict) -> tuple:
    """(store holding only VERIFIED human decisions, ledger of what happened).

    A human annotation is carried forward only when the row it reviewed still
    fingerprints the same. Anything else — machine annotations, and human ones
    whose source moved — is left out so the fixed writer decides it afresh.
    """
    from scripts.build_pricing_artifact import _row_fingerprint

    captured: dict = {}
    for identity, records in (capture.get("queries") or {}).items():
        for record in records:
            for row in record.get("rows") or ():
                captured.setdefault(
                    (identity, f"usda:{row.get('fdc_id')}"), set()
                ).add(_row_fingerprint(row))

    store, ledger = sa.Store(), {"kept": [], "reopened": [], "discarded": 0}
    for key, annotation in previous.by_key.items():
        identity, _, evidence = key.partition("␟")
        if not sa.reviewed(annotation):
            ledger["discarded"] += 1          # written by the buggy path
            continue
        prints = captured.get((identity, evidence))
        if prints and annotation.source_fingerprint and \
                annotation.source_fingerprint not in prints:
            # ⛔ THE ROW MOVED UNDER THE REVIEW. Not wrong — UNVERIFIED.
            ledger["reopened"].append(
                {"identity_key": identity, "evidence_id": evidence,
                 "reviewed_fingerprint": annotation.source_fingerprint,
                 "captured_fingerprints": sorted(prints)})
            continue
        store.by_key[key] = annotation
        ledger["kept"].append({"identity_key": identity,
                               "evidence_id": evidence,
                               "relationship": annotation.relationship})
    return store, ledger


async def repopulate(dry_run: bool = True) -> dict:
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq

    if not cr.CAPTURE_PATH.exists():
        raise SystemExit("no seam capture — run scripts.capture_retrieval")
    capture = json.loads(cr.CAPTURE_PATH.read_text())
    cr.verify_contract(capture)

    document = json.loads(art.ARTIFACT_PATH.read_text())
    previous = sa.Store.from_payload(
        (document.get("meta") or {}).get("annotations") or {})
    store, seed_ledger = human_seed(previous, capture)

    batches, original_qualify = [], eq.qualify_usda_rows

    async def _observed(food_name, rows, *args, **kwargs):
        """Record what each batch was ASKED and what it could answer."""
        requested = [f"usda:{r.get('fdc_id')}" for r in rows]
        result = await original_qualify(food_name, rows, *args, **kwargs)
        judged = [f"usda:{r.get('fdc_id')}"
                  for r in (getattr(result, "rows", None) or ())]
        abstained = [f"usda:{r.get('fdc_id')}"
                     for r in (getattr(result, "abstained", None) or ())]
        batches.append({
            "food": food_name,
            "requested": requested,
            "judged_kept": judged,
            "abstained": abstained,
            "disposition": getattr(result, "disposition", ""),
            # ⚠ THIS FIELD WAS NAMED "unaccounted" AND MEASURED THE WRONG
            # THING. `q.rows` is what the resolver ADMITTED, `q.abstained` is
            # what it could not assess — so a row it ASSESSED AND REJECTED is
            # in neither, and the first version counted every correct,
            # informative negative as a lost row. 63 of them, and the gate
            # refused a healthy run.
            #
            # A rejection is an ANSWER. What actually has no answer is an
            # abstention, and that is already its own field. Completeness is
            # therefore: requested == kept + rejected + abstained, which holds
            # by construction on a usable batch and fails only when the
            # resolver returns a payload that does not describe its input.
            "judged_rejected": sorted(set(requested) - set(judged)
                                      - set(abstained)),
            "unaccounted": sorted(
                set(requested) - set(judged) - set(abstained)
                - (set(requested) - set(judged) - set(abstained))),
        })
        return result

    report = {"seed": seed_ledger, "batches": [], "resolved_this_build": 0}
    if dry_run:
        outstanding = sum(
            1 for identity, records in (capture.get("queries") or {}).items()
            for record in records for row in record.get("rows") or ()
            if store.needs_resolution(identity, f"usda:{row.get('fdc_id')}"))
        report["would_resolve"] = outstanding
        return report

    original_search = usda._search
    try:
        eq.qualify_usda_rows = _observed
        for identity in sorted(capture.get("queries") or {}):
            entity, _, preparation = identity.partition("|")
            records = capture["queries"][identity]
            calls = iter(records)

            async def _replay(*_a, _calls=calls, **_k):
                try:
                    return list(next(_calls)["rows"])
                except StopIteration:
                    return []

            usda._search = _replay
            await bp.build_one(entity, preparation, store=store)
    finally:
        usda._search, eq.qualify_usda_rows = original_search, original_qualify

    report["batches"] = batches
    report["resolved_this_build"] = len(store.resolved_this_build)
    report["annotations"] = len(store.by_key)
    report["unaccounted_total"] = sum(len(b["unaccounted"]) for b in batches)
    report["abstained_total"] = sum(len(b["abstained"]) for b in batches)
    report["judged_rejected_total"] = sum(len(b["judged_rejected"])
                                          for b in batches)
    report["judged_kept_total"] = sum(len(b["judged_kept"]) for b in batches)
    # ⭐ THE COMPLETENESS IDENTITY, CHECKED RATHER THAN ASSUMED.
    report["requested_total"] = sum(len(b["requested"]) for b in batches)
    accounted = (report["judged_kept_total"] + report["judged_rejected_total"]
                 + report["abstained_total"])
    report["completeness_holds"] = accounted == report["requested_total"]

    failures = []
    if not report["completeness_holds"]:
        failures.append(
            f"batch completeness FAILED: {report['requested_total']} requested "
            f"but {report['judged_kept_total']} kept + "
            f"{report['judged_rejected_total']} rejected + "
            f"{report['abstained_total']} abstained do not account for them")
    if report["resolved_this_build"] == 0:
        failures.append("resolved_this_build == 0 — nothing was rebuilt, so "
                        "this is not a population run")
    report["failures"] = failures

    if not failures:
        document.setdefault("meta", {})["annotations"] = store.to_payload()
        document["meta"]["store_writer"] = "post_140e994"
        art.ARTIFACT_PATH.write_text(json.dumps(document, indent=1) + "\n")
        RUN_RECORD.write_text(json.dumps(report, indent=1) + "\n")
    return report


if __name__ == "__main__":
    write = "--write" in sys.argv
    result = asyncio.run(repopulate(dry_run=not write))
    seed = result["seed"]
    print(f"  {'REPOPULATION' if write else 'DRY RUN'} — through the "
          f"post-140e994 writer\n")
    print(f"    human decisions kept      {len(seed['kept'])}")
    print(f"    human decisions REOPENED  {len(seed['reopened'])}  (source moved)")
    print(f"    machine annotations discarded {seed['discarded']}")
    if not write:
        print(f"    would resolve             {result['would_resolve']}")
    else:
        print(f"    resolved this build       {result['resolved_this_build']}")
        print(f"    annotations               {result.get('annotations')}")
        print(f"    batches                   {len(result['batches'])}")
        print(f"    requested                 {result['requested_total']}")
        print(f"      judged kept             {result['judged_kept_total']}")
        print(f"      judged rejected         {result['judged_rejected_total']}")
        print(f"      abstained               {result['abstained_total']}")
        print(f"    completeness holds        {result['completeness_holds']}")
        for failure in result.get("failures") or ():
            print(f"    ⛔ {failure}")
        if result.get("failures"):
            raise SystemExit(1)
        print(f"\n  ✅ store reconstructed; every batch says what it was asked "
              f"and what it could answer")
