"""PHASE 0 STEP 5 — POPULATE THE SEMANTIC STORE ONCE, UNPOISONED.

⭐ THIS DOES NOT RE-RETRIEVE, AND THAT IS THE WHOLE DESIGN. "Populate the
store" means give every candidate ALREADY IN THE FROZEN ARTIFACT a durable
semantic annotation. Re-running retrieval would move the candidate universe,
and the winner accounting was frozen against a specific universe one commit
ago — every one of its 27 `candidate_universe_fingerprint` values would go
stale in the same breath that claimed to populate them. A creation run that
invalidates the thing it is creating evidence for is not a creation run.

⭐⭐ THIS RUN IS NOT REPRODUCIBILITY EVIDENCE, and says so. It CALLS the
resolver — `resolved_this_build > 0` is required, not tolerated — because a
population run that resolved nothing would mean the store was already full and
the whole exercise was a no-op. The proof comes later, from a POISONED rebuild
that must resolve zero. Confusing the two would let a creation run's success
stand in for a determinism claim it cannot make.

⭐⭐⭐ AND THE 77 HUMAN SIGNATURES ARE LOADED FIRST. A reviewer's judgement
outranks the resolver's, so those pairs are in the store before a single call
is made and `needs_resolution` refuses to re-ask them. Populating over the top
of human review would quietly replace decisions with samples — which is the
defect `needs_resolution` was taught to refuse in the first place.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from scripts import baseline_signatures as bs
from scripts import freeze_winner_accounting as fz
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa
from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

RUN_RECORD = (pathlib.Path(__file__).resolve().parents[1]
              / "data" / "baseline" / "phase_0_population_run.json")


def _pairs(document):
    """Every (identity, source-qualified evidence, row) in the frozen universe."""
    for identity, entry in sorted((document.get("entries") or {}).items()):
        for candidate in (entry.get("candidates") or ()):
            yield identity, art.candidate_evidence_id(candidate), candidate


def _seeded_store(document):
    """The store as it must stand BEFORE any resolver call.

    Existing annotations, then the human signatures on top — so review is the
    thing the population runs around, not the thing it runs over.
    """
    stored = (document.get("meta") or {}).get("annotations") \
        or document.get("annotations") or {}
    store = sa.Store.from_payload(stored)
    worksheet = json.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "data" / "baseline"
         / "phase_1_5_worksheet.json").read_text())
    bs.freeze(store, worksheet)
    return store


async def _resolve(identity, rows):
    from skills.nutrition.evidence_qualification import qualify_usda_rows
    entity, _, preparation = identity.partition("|")
    query = f"{entity}, {preparation}" if preparation else entity
    return await qualify_usda_rows(query, rows)


async def populate(dry_run: bool = True) -> dict:
    document = json.loads(art.ARTIFACT_PATH.read_text())
    store = _seeded_store(document)

    universe = list(_pairs(document))
    outstanding = {}
    for identity, evidence, candidate in universe:
        if store.needs_resolution(identity, evidence):
            outstanding.setdefault(identity, []).append((evidence, candidate))

    report = {
        "regime": PHASE_0_REGIME,
        "candidate_universe": len(universe),
        "seeded_annotations": len(store.by_key),
        "human_signatures": len(bs.SIGNATURES),
        "outstanding": sum(len(v) for v in outstanding.values()),
        "identities_needing_resolution": len(outstanding),
        "resolved_this_build": 0,
        "is_reproducibility_evidence": False,
    }
    if dry_run:
        report["plan"] = {k: len(v) for k, v in sorted(outstanding.items())}
        return report

    from skills.nutrition.evidence_semantics import RESOLVER_MODEL
    for identity, items in sorted(outstanding.items()):
        rows = [candidate for _evidence, candidate in items]
        qualification = await _resolve(identity, rows)
        usable = qualification is not None and not (
            getattr(qualification, "disposition", "") ==
            "resolver_down_no_candidates" and not qualification.rows)
        kept = {str(r.get("fdc_id"))
                for r in ((qualification.rows if qualification else None) or ())}
        for evidence, candidate in items:
            if not usable:
                # ⛔ AN OUTAGE IS NOT A NEGATIVE. Recording UNRESOLVED keeps
                # the evidence revisitable instead of writing "not this food".
                store.record(sa.Annotation(
                    identity_key=identity, evidence_id=evidence,
                    relationship=sa.UNRESOLVED, confidence=0.0,
                    resolver_model=RESOLVER_MODEL))
                continue
            hit = str(candidate.get("fdc_id")) in kept
            store.record(sa.Annotation(
                identity_key=identity, evidence_id=evidence,
                relationship=(sa.SAME_IDENTITY if hit
                              else sa.DIFFERENT_IDENTITY),
                confidence=0.95, resolver_model=RESOLVER_MODEL,
                resolver_version=getattr(qualification, "resolver_version", "")
                or ""))
            store.resolved_this_build.append((identity, evidence))

    report["resolved_this_build"] = len(store.resolved_this_build)
    report["annotations"] = len(store.by_key)
    report["failures"] = _verify(document, store, universe)

    if not report["failures"]:
        document.setdefault("meta", {})["annotations"] = store.to_payload()
        art.ARTIFACT_PATH.write_text(json.dumps(document, indent=1) + "\n")
        RUN_RECORD.write_text(json.dumps(report, indent=1) + "\n")
    return report


def _verify(document, store, universe) -> list:
    """What must be true before this population may be written down."""
    failures = []

    unannotated = [(i, e) for i, e, _c in universe if store.get(i, e) is None]
    if unannotated:
        failures.append(f"{len(unannotated)} candidates left with no "
                        f"annotation: {unannotated[:5]}")

    # ⭐ THE SIGNATURES MUST HAVE SURVIVED. If a population run can overwrite
    # human review, the review was decoration.
    for identity, evidence, disposition, *_ in bs.SIGNATURES:
        annotation = store.get(identity, evidence)
        if annotation is None or not sa.reviewed(annotation):
            failures.append(f"{identity}/{evidence}: signature lost")
            break

    # ⭐⭐ AND THE FROZEN WINNERS MUST STILL WIN. Annotations change which
    # evidence is ELIGIBLE, so a population run can move a winner — and a
    # moved winner invalidates the accounting frozen one commit ago.
    frozen = json.loads(fz.FREEZE_PATH.read_text()) if fz.FREEZE_PATH.exists() \
        else {"rows": []}
    with ranking_regime(PHASE_0_REGIME):
        import core.food_intelligence as fi
        from core.canonical_pricing import _ranker_query
        entries = document.get("entries") or {}
        for row in frozen.get("rows") or []:
            identity = row["identity_key"]
            entry = entries.get(identity) or {}
            candidates = [c for c in (entry.get("candidates") or ())
                          if sa.eligible(store.get(
                              identity, art.candidate_evidence_id(c)))]
            if not candidates:
                failures.append(f"{identity}: no eligible evidence after "
                                f"population — the winner would vanish")
                continue
            entity, _, preparation = identity.partition("|")
            winner, _conf = fi.best_candidate(
                _ranker_query(entity, preparation), candidates)
            if winner is None:
                failures.append(f"{identity}: prices from nothing after "
                                f"population")
            elif art.candidate_evidence_id(winner) != row["winner_evidence_id"]:
                failures.append(
                    f"{identity}: frozen winner {row['winner_evidence_id']} "
                    f"-> {art.candidate_evidence_id(winner)}")
    return failures


if __name__ == "__main__":
    write = "--write" in sys.argv
    result = asyncio.run(populate(dry_run=not write))
    print(f"  {'POPULATION RUN' if write else 'DRY RUN'} · regime "
          f"{result['regime']}\n")
    for field in ("candidate_universe", "seeded_annotations",
                  "human_signatures", "outstanding",
                  "identities_needing_resolution", "resolved_this_build"):
        print(f"    {field:<32} {result[field]}")
    if not write:
        print(f"\n    would resolve, by identity:")
        for identity, n in sorted(result["plan"].items()):
            print(f"      {identity:<20} {n}")
    else:
        for failure in result.get("failures") or ():
            print(f"    ⛔ {failure}")
        if result.get("failures"):
            raise SystemExit(1)
        print(f"\n  ✅ written · NOT reproducibility evidence "
              f"(that is the POISONED rebuild)")
