#!/usr/bin/env python
"""PRE-TURN PREFLIGHT for the in-turn collision regression probe.

⛔⛔ "NOT ON THE PRELOAD MANIFEST" IS NOT THE CLAIM WE NEED. The evidence store
is moving while the 328 preload runs, so absence from a list written earlier
proves nothing about the moment the turn happens. The causal statement the probe
must support is:

    unsupported IMMEDIATELY BEFORE the turn
      -> that same turn created >3 qualified candidates
      -> canonical settlement

so all four sources of prior coverage are checked mechanically, now:

    1. coverage_for(...) is Unsupported
    2. no acquired_evidence_record for the identity
    3. not present in the seeded (committed) artifact
    4. no acquisition job, pending or completed, that could supply it
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


async def check(identity, grams):
    from sqlalchemy import select, text

    from core.general_settlement import Supported, coverage_for
    from db.database import AsyncSessionLocal
    from db.models import AcquiredEvidenceRecord
    from skills.nutrition import pricing_artifact as art

    entity, prep = art.split_identity(identity)
    key = art.key(entity, prep)
    item = {"food_name": identity, "quantity": f"{grams} g", "calories": 999.0}
    out = {"identity": identity, "key": key}

    async with AsyncSessionLocal() as db:
        verdict = await coverage_for(db, user_id=0, items=[item])
        out["1_unsupported"] = not isinstance(verdict, Supported)
        out["verdict"] = type(verdict).__name__

        rows = (await db.execute(
            select(AcquiredEvidenceRecord).where(
                AcquiredEvidenceRecord.canonical_identity == key))).scalars().all()
        out["2_no_acquired_row"] = not rows

        out["3_not_seeded"] = art.evidence_for(entity, prep) is None

        jobs = (await db.execute(text(
            "select count(*) from background_jobs where kind='acquire_evidence'"
            " and dedup_key = :k"), {"k": f"acquire:{identity}"})).scalar()
        out["4_no_acquisition_job"] = not jobs

    out["READY"] = all(out[k] for k in
                       ("1_unsupported", "2_no_acquired_row", "3_not_seeded",
                        "4_no_acquisition_job"))
    return out


async def main(foods):
    ok = True
    for spec in foods:
        grams, _, name = spec.partition(":")
        r = await check(name, grams)
        mark = "READY" if r["READY"] else "NOT READY"
        print(f"\n{name!r} ({grams} g)  ->  {mark}")
        for k in ("1_unsupported", "2_no_acquired_row", "3_not_seeded",
                  "4_no_acquisition_job"):
            print(f"    {k:24} {r[k]}")
        print(f"    settlement verdict now   {r['verdict']}")
        ok &= r["READY"]
    print("\n" + ("ALL PROBES READY — log them now, nothing else in between"
                  if ok else
                  "⛔ AT LEAST ONE PROBE IS ALREADY COVERED — it cannot prove "
                  "an in-turn acquisition. Pick another food."))
    return 0 if ok else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("foods", nargs="*",
                    default=["200:turkey breast", "180:chicken thigh",
                             "200:salmon fillet"])
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    sys.exit(asyncio.run(main(a.foods)))
