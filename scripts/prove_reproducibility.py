"""PHASE 0 STEPS 6-8 — FREEZE, POISON, AND PROVE.

⭐ THE POISON IS THE WHOLE PROOF. A rebuild that merely *happens* not to call
the resolver proves nothing: it might be reusing annotations, or the resolver
might have been quietly unreachable, and both look identical from the outside.
So the resolver is replaced with a function that RAISES, and the build has to
produce the same artifact anyway. `resolved_this_build == 0` then means "it
could not have asked" rather than "it did not happen to".

⭐⭐ AND A COUNTER IS NOT ENOUGH. Reading `resolved_this_build == 0` alone
would be the same trap this migration keeps finding — a number that reads
clean when the instrument is silent. The poison is verified to BITE first: one
deliberate call must raise `ResolverPoisoned` before any conclusion is drawn
from its absence. An unpoisoned run that returned zero would otherwise pass.

⭐⭐⭐ THE COMPARISON IS PRE-RETENTION AND EXACT. Retention exists to carry
forward candidates a build cannot account for — which means it is capable of
MANUFACTURING the agreement this proof is trying to measure. So the artifact
is compared before retention runs, field by field, with no tolerance:
identity, source-qualified evidence, membership, ORDER, annotations, winner,
winner state, policy version, price. Anything less would let a rescue read as
a reproduction.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import sys

from scripts import freeze_winner_accounting as fz
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa
from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

PROOF_PATH = (pathlib.Path(__file__).resolve().parents[1]
              / "data" / "baseline" / "phase_0_reproducibility_proof.json")


class ResolverPoisoned(RuntimeError):
    """The resolver was invoked during a run that must not need it."""


async def _poisoned(*_args, **_kwargs):
    raise ResolverPoisoned(
        "the resolver was called during the poisoned rebuild — the store was "
        "supposed to answer this without asking anyone")


def _snapshot(document, store) -> dict:
    """Everything the proof compares, computed PRE-RETENTION."""
    rows = []
    with ranking_regime(PHASE_0_REGIME) as regime:
        import core.food_intelligence as fi
        from core.canonical_pricing import _ranker_query

        for identity, entry in sorted((document.get("entries") or {}).items()):
            candidates = list(entry.get("candidates") or ())
            if not candidates:
                continue
            # ORDER is part of the fact, not an accident of iteration
            evidence_ids = [art.candidate_evidence_id(c) for c in candidates]
            annotations = [
                (e, (a.relationship if (a := store.get(identity, e)) else None),
                 sa.disposition(store.get(identity, e)),
                 sa.eligible(store.get(identity, e)))
                for e in evidence_ids]
            # ⭐ A REVIEWED PIN IS AN EXPLICIT OVERRIDE (2026-09-03). The
            # artifact records which seeds are held on a reviewed candidate
            # set; for those the store's eligibility is not the authority —
            # the hold is, and it says so in `pinned_seed_identities`.
            pinned_here = identity in (document.get("pinned_seed_identities") or {})
            eligible = candidates if pinned_here else [
                c for c in candidates
                if sa.eligible(store.get(identity, art.candidate_evidence_id(c)))]
            entity, _, preparation = identity.partition("|")
            winner, conf = fi.best_candidate(
                _ranker_query(entity, preparation), eligible or candidates)
            per100g = (winner or {}).get("per100g") or {}
            rows.append({
                "identity_key": identity,
                "pinned": pinned_here,
                "evidence_ids": evidence_ids,
                "annotations": annotations,
                "winner_evidence_id":
                    None if winner is None else art.candidate_evidence_id(winner),
                "winner_confidence": conf,
                "ranking_policy_version": regime,
                "calories": per100g.get("calories"),
                "protein": per100g.get("protein"),
                "carbs": per100g.get("carbs"),
                "fat": per100g.get("fat"),
            })
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    return {"rows": rows,
            "raw_fingerprint": hashlib.sha256(blob.encode()).hexdigest()}


async def prove(runs: int = 3) -> dict:
    document = json.loads(art.ARTIFACT_PATH.read_text())
    stored = (document.get("meta") or {}).get("annotations") or {}
    if not stored:
        raise SystemExit("the store is empty — populate before proving")

    # ── the poison must BITE before its silence means anything ───────────
    import skills.nutrition.evidence_qualification as eq
    poison_bites = False
    try:
        await _poisoned("probe", [])
    except ResolverPoisoned:
        poison_bites = True

    original = eq.qualify_usda_rows
    eq.qualify_usda_rows = _poisoned
    try:
        snapshots = []
        for _ in range(runs):
            store = sa.Store.from_payload(stored)
            outstanding = [
                (identity, art.candidate_evidence_id(c))
                for identity, entry in (document.get("entries") or {}).items()
                for c in (entry.get("candidates") or ())
                if store.needs_resolution(identity,
                                          art.candidate_evidence_id(c))]
            # ⛔ the moment of truth: anything outstanding would have to ask
            for identity, evidence in outstanding:
                await eq.qualify_usda_rows(identity, [])
            snapshots.append({
                "resolved_this_build": len(store.resolved_this_build),
                "outstanding": len(outstanding),
                **_snapshot(document, store),
            })
    finally:
        eq.qualify_usda_rows = original

    first = snapshots[0]
    failures = []
    if not poison_bites:
        failures.append("the poison does not raise — its silence proves "
                        "nothing")
    for index, snapshot in enumerate(snapshots):
        if snapshot["resolved_this_build"] != 0:
            failures.append(f"run {index}: resolved_this_build="
                            f"{snapshot['resolved_this_build']}, must be 0")
        if snapshot["outstanding"] != 0:
            failures.append(f"run {index}: {snapshot['outstanding']} pairs "
                            f"would have needed the resolver")
        if snapshot["raw_fingerprint"] != first["raw_fingerprint"]:
            failures.append(f"run {index}: raw fingerprint differs from run 0")
        if snapshot["rows"] != first["rows"]:
            differing = [r["identity_key"] for r, f in
                         zip(snapshot["rows"], first["rows"]) if r != f]
            failures.append(f"run {index}: rows differ: {differing[:5]}")

    # ── and the frozen winners must be what the proof reproduces ─────────
    frozen = json.loads(fz.FREEZE_PATH.read_text())
    frozen_by_identity = {r["identity_key"]: r["winner_evidence_id"]
                          for r in frozen["rows"]}
    for row in first["rows"]:
        expected = frozen_by_identity.get(row["identity_key"])
        if expected is None:
            failures.append(f"{row['identity_key']}: not in the frozen "
                            f"accounting")
        elif row["winner_evidence_id"] != expected:
            failures.append(f"{row['identity_key']}: reproduced "
                            f"{row['winner_evidence_id']}, frozen {expected}")

    return {"regime": PHASE_0_REGIME, "runs": runs,
            "poison_bites": poison_bites,
            "resolved_this_build": [s["resolved_this_build"] for s in snapshots],
            "raw_fingerprint": first["raw_fingerprint"],
            "identities": len(first["rows"]),
            "failures": failures}


if __name__ == "__main__":
    result = asyncio.run(prove())
    print(f"  POISONED REBUILD x{result['runs']} · regime {result['regime']}\n")
    print(f"    poison bites (verified first)   {result['poison_bites']}")
    print(f"    resolved_this_build per run     {result['resolved_this_build']}")
    print(f"    identities compared             {result['identities']}")
    print(f"    raw fingerprint                 {result['raw_fingerprint'][:32]}")
    for failure in result["failures"]:
        print(f"    ⛔ {failure}")
    if result["failures"]:
        raise SystemExit(1)
    print(f"\n  ✅ identical across {result['runs']} runs, pre-retention, "
          f"no tolerance,")
    print(f"     with a resolver that would have RAISED if consulted")
    if "--write" in sys.argv:
        PROOF_PATH.write_text(json.dumps(result, indent=1) + "\n")
        print(f"\n  -> {PROOF_PATH.name}")
