"""LOCAL DIAGNOSTIC — where do identity confidences sit against human truth?

⛔⛔ THIS IS NOT PREVALENCE EVIDENCE. It answers "what SHAPE of problem should we
expect", never "how often do users hit it". The production forward census
(`event=identity_assessment`) is the only authority on prevalence, and the two
must never be merged into one percentage.

Labels were frozen in `data/corpus/branded_identity_truth_v1.json` BEFORE any
confidence was computed, so the distribution cannot have shaped the truth.

⭐ WHAT IT IS FOR. The first useful output is NOT an average confidence — an
average over a mixture of true matches and near neighbours means nothing. It is
the confusion distribution against the live 0.80 bar, so the next tranche can
be chosen rather than guessed:

    true matches lost below the bar        -> calibration is live
    true mismatches admitted if it moved   -> the cost of moving it
    losses concentrated at .75-.79         -> a bar problem
    losses spread everywhere               -> an evidence or model problem
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

CORPUS = pathlib.Path("data/corpus/branded_identity_truth_v1.json")
OUT = pathlib.Path("data/branded_identity_replay_2026-08-31.json")


async def main() -> int:
    from core.semantic_evidence import resolve
    from core.semantic_evidence import EvidenceRecord
    from skills.nutrition.evidence_qualification import _default_complete
    from skills.nutrition.evidence_semantics import (
        DOMAIN, IDENTITY_BEARING, MINIMUM_IDENTITY_CONFIDENCE, FoodIntent)

    corpus = json.loads(CORPUS.read_text())
    cases = corpus["cases"]
    print(f"corpus {corpus['name']} frozen {corpus['frozen_at']} — "
          f"{len(cases)} cases, threshold {MINIMUM_IDENTITY_CONFIDENCE}")

    rows = []
    for c in cases:
        # ONE candidate per intent, so the assessment is about exactly the pair
        # the human labelled — a batch would let the model rank rather than judge.
        rec = EvidenceRecord(
            evidence_id=f"corpus:{c['id']}", provider="off",
            title=c["candidate"], brand="", nutrition={},
            provider_record_id=str(c["id"]), provider_metadata={})
        try:
            assessments = await resolve(
                DOMAIN, FoodIntent(base_identity=c["intent"]), (rec,),
                _default_complete)
            a = assessments[0]
            rel, conf, abst = a.relationship, float(a.confidence or 0.0), bool(a.abstained)
        except Exception as e:
            rel, conf, abst = f"ERROR:{type(e).__name__}", 0.0, True
        eligible = rel in IDENTITY_BEARING and conf >= MINIMUM_IDENTITY_CONFIDENCE
        rows.append({**c, "relationship": rel, "confidence": round(conf, 3),
                     "abstained": abst, "qualified": eligible})
        print(f"  {c['id']:>2} {c['label']:<22} {rel:<26} {conf:.2f} "
              f"{'QUALIFIED' if eligible else 'refused'}  {c['intent'][:34]}")

    OUT.write_text(json.dumps({"corpus": corpus["name"],
                               "threshold": MINIMUM_IDENTITY_CONFIDENCE,
                               "rows": rows}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
