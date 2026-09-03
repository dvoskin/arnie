#!/usr/bin/env python
"""Per-mode reachability + consumed-form CONFLICTS for a pricing artifact.

Two publication questions, one read of the file:

  1. Which identities are unreachable with NUTRITION_ACCURACY_V2 OFF?
     The contract test enumerates the known v1-ranker artifacts (a length
     lever that rejects verbose fish rows). A NEW member of that class must be
     enumerated deliberately; a genuinely new failure must not be.

  2. Which unqualified identities have a raw/dry WINNER while a cooked row sits
     in the same pool? That is the consumed-form exposure query expansion
     opened (`oats|` -> dry, +434%). Reported as a LIST, not a count — a naive
     `raw` scan over-flagged 6 of 9 last time because USDA's `raw` is the fresh
     form blueberries are actually eaten in.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from contextlib import contextmanager

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

_PRECURSOR = {"raw", "dry", "dried", "uncooked", "unprepared"}


@contextmanager
def _v2(active: bool):
    prev = os.environ.get("NUTRITION_ACCURACY_V2")
    os.environ["NUTRITION_ACCURACY_V2"] = "1" if active else ""
    try:
        from core.food_intelligence import _nutrition_accuracy_v2
        assert _nutrition_accuracy_v2() is active, "flag did not take effect"
        yield
    finally:
        if prev is None:
            os.environ.pop("NUTRITION_ACCURACY_V2", None)
        else:
            os.environ["NUTRITION_ACCURACY_V2"] = prev


def main(path):
    from core.food_intelligence import best_candidate, _COOKED_MARKERS, normalize_name
    from skills.nutrition.preparation_ontology import name_with

    doc = json.loads(pathlib.Path(path).read_text())
    entries = {k: v for k, v in (doc.get("entries") or {}).items() if v.get("candidates")}
    print(f"artifact: {path}  resolver={doc.get('resolver_version')}  entries={len(entries)}")

    def q(key):
        ent, _, prep = key.partition("|")
        from core.canonical_pricing import _ranker_query
        return _ranker_query(ent, prep) if prep else ent

    unreach = {}
    for mode in (False, True):
        with _v2(mode):
            unreach[mode] = sorted(k for k, e in entries.items()
                                   if best_candidate(q(k), list(e["candidates"]))[0] is None)
    print(f"\nUNREACHABLE  V2 off: {unreach[False]}")
    print(f"UNREACHABLE  V2 on : {unreach[True]}")

    conflicts = []
    with _v2(True):
        for k, e in entries.items():
            ent, _, prep = k.partition("|")
            if prep:
                continue                                   # form was stated
            cands = list(e["candidates"])
            w, _ = best_candidate(ent, cands)
            if not w:
                continue
            wd = set(normalize_name(w.get("description", ""), split_separators=True).split())
            # ⛔ "dry heat" is a COOKING METHOD, not a precursor form. The first
            # run flagged `salmon|` — winner "Fish, salmon, cooked, dry heat" —
            # as a dry precursor. Same over-flagging class as the earlier
            # `\braw\b` scan that was wrong about 6 of 9.
            precursor = wd & _PRECURSOR
            if "dry" in precursor and "heat" in wd:
                precursor -= {"dry"}
            if not precursor or (wd & _COOKED_MARKERS):
                continue                                   # a cooked winner is not a precursor
            cooked = [c for c in cands if c is not w and
                      set(normalize_name(c.get("description", ""), split_separators=True).split())
                      & _COOKED_MARKERS]
            if cooked:
                conflicts.append((k, w.get("description", ""), len(cooked)))
    print(f"\nCONSUMED-FORM CONFLICTS (raw/dry winner, cooked row present, no prep stated): {len(conflicts)}")
    for k, d, n in conflicts:
        print(f"   {k:18} winner={d[:46]:48} cooked_alternatives={n}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default="data/pricing_evidence_v1.json")
    a = ap.parse_args()
    sys.exit(main(a.artifact))
