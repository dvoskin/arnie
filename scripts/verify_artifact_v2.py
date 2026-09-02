#!/usr/bin/env python
"""PUBLICATION GATE for a rebuilt artifact.

⛔⛔ THE BIGGEST RISK IS NOT THE DECLINED SEED. v2 changed the identity prompt,
so a previously authoritative seed can select a DIFFERENT candidate — and a
rebuild has no catalog-wins protection, because it re-runs `best_candidate`
over the whole pool by construction. Those 27 entries are inside the frozen
222, so a silent reprice moves the baseline underneath the measurement it is
about to be compared against.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PRIOR = pathlib.Path("/tmp/artifact_pre_v2.json")
NOW = pathlib.Path("data/pricing_evidence_v1.json")


def winner(entry, key=""):
    """THE PRICED WINNER, VIA THE REAL RANKER — not `candidates[0]`.

    ⛔⛔ THE FIRST VERSION READ ARRAY POSITION. `ArtifactEvidence` stores
    QUALIFIED CANDIDATES, NOT A CHOSEN WINNER — its own docstring says so — and
    `_from_artifact` calls `best_candidate(query, candidates)` at pricing time.
    So a change in stored ORDER is not a reprice, and this gate BLOCKED four
    identities on a signal that never reaches the ledger. A gate that measures
    the wrong quantity is worse than no gate: it stops correct work and would
    wave through a real reprice that left position 0 untouched.
    """
    from core.food_intelligence import best_candidate

    cs = entry.get("candidates") or []
    if not cs:
        return None, None
    query = (key or "").split("|")[0] or (key or "")
    w, _conf = best_candidate(query, cs)
    if not w:
        return None, None
    p = w.get("per100g") or {}
    return w.get("evidence_id"), round(float(p.get("calories") or 0), 1)


def main():
    old = json.loads(PRIOR.read_text())
    new = json.loads(NOW.read_text())
    oe, ne = old["entries"], new["entries"]

    print("=== instrument identity ===")
    for k in ("resolver_version", "retrieval_fingerprint", "vocabulary_fingerprint"):
        print(f"  {k:24} {old.get(k)}  ->  {new.get(k)}")
    print(f"  {'entries':24} {len(oe)}  ->  {len(ne)}")

    dec = new.get("declined_seed_identities") or {}
    print(f"\n=== declined seed identities ({len(dec)}) ===")
    for k, v in dec.items():
        print(f"  {k}: {v.get('reason')} | pop={v.get('observed_candidate_fingerprint')}")

    buckets = {"UNCHANGED": [], "CHANGED_CANDIDATE_SAME_NUTRITION": [],
               "CHANGED_CANDIDATE_CHANGED_NUTRITION": [], "MISSING": [], "NEW": []}
    for k in sorted(set(oe) | set(ne)):
        if k not in ne:
            buckets["MISSING"].append((k, *winner(oe[k], k), None, None)); continue
        if k not in oe:
            buckets["NEW"].append((k, None, None, *winner(ne[k], k))); continue
        oid, ocal = winner(oe[k], k); nid, ncal = winner(ne[k], k)
        if oid == nid and ocal == ncal:
            buckets["UNCHANGED"].append((k, oid, ocal, nid, ncal))
        elif ocal == ncal:
            buckets["CHANGED_CANDIDATE_SAME_NUTRITION"].append((k, oid, ocal, nid, ncal))
        else:
            buckets["CHANGED_CANDIDATE_CHANGED_NUTRITION"].append((k, oid, ocal, nid, ncal))

    print("\n=== reprice diff over prior authoritative entries ===")
    for b, rows in buckets.items():
        print(f"  {b:38} {len(rows)}")
        for k, oid, ocal, nid, ncal in rows[:8]:
            if b != "UNCHANGED":
                print(f"      {k:26} {oid} {ocal} -> {nid} {ncal}")

    block = buckets["CHANGED_CANDIDATE_CHANGED_NUTRITION"] + buckets["MISSING"]
    print("\n" + "=" * 62)
    if block:
        print(f"⛔ BLOCKED — {len(block)} entr(ies) changed nutrition or vanished.")
        print("   A changed nutrition value on an existing authoritative seed is a")
        print("   STOP CONDITION until causally explained: those seeds are inside")
        print("   the frozen 222 and a silent reprice moves the baseline.")
        return 2
    if buckets["CHANGED_CANDIDATE_SAME_NUTRITION"]:
        print(f"⚠ {len(buckets['CHANGED_CANDIDATE_SAME_NUTRITION'])} candidate(s) "
              "changed with IDENTICAL nutrition — inspect, not automatically fatal.")
    print("✅ no repricing of previously authoritative entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
