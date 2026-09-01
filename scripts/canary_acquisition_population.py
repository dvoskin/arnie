#!/usr/bin/env python
"""THE ACQUISITION CANARY — one proof is not a rate.

⭐⭐⭐ `cod` settled canonically in production on 2026-09-01. That closed the
question "does the flywheel turn". It says NOTHING about how often it turns, for
which foods, or how fast — and the decision that follows (bulk preload vs. more
adapters vs. quantity authority) depends entirely on those numbers.

⛔⛔ EVERY IDENTITY HERE IS DELIBERATELY OUTSIDE THE FROZEN 222-MEAL CORPUS. The
corpus is an EVALUATION INSTRUMENT, never the backlog: measuring acquisition on
foods drawn from the population it will later be scored against is the
memorisation this project has already caught itself doing once.

⛔ AND IT NEVER WRITES A FOOD ENTRY. This runs the ACQUISITION path only —
`acquire()` then `coverage_for()` — against a scratch user. Logging real meals to
measure a producer would put fabricated food in someone's diary, and the
measurement would be indistinguishable from the thing it measures.

STRATA, chosen so each answers a different question:
    easy_generic     does the common case work at all
    uncommon_generic does coverage thin out past the obvious foods
    branded          is SKU/flavour identity admissible (formulation matters)
    non_latin        ⭐ THE ONE THAT DECIDES PHASE 2 — half the frozen tail is
                     Russian and no USDA English description can match it
    expected_refuse  does a food nobody holds refuse CLEANLY, by NAME
Every case carries an exact mass so QUANTITY is never the confound: this
instrument measures evidence acquisition, and a count-blocked item would decline
for a reason that has nothing to do with the producer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

POPULATION = [
    # stratum,          identity,                         exact mass
    ("easy_generic",    "cod",                            "180 g"),
    ("easy_generic",    "lentils",                        "250 g"),
    ("easy_generic",    "brown rice",                     "200 g"),
    ("easy_generic",    "sweet potato",                   "150 g"),
    ("easy_generic",    "cottage cheese",                 "200 g"),
    ("easy_generic",    "pork tenderloin",                "170 g"),
    ("uncommon_generic", "monkfish",                      "160 g"),
    ("uncommon_generic", "celeriac",                      "120 g"),
    ("uncommon_generic", "freekeh",                       "90 g"),
    ("uncommon_generic", "kefir",                         "250 g"),
    ("uncommon_generic", "tempeh",                        "100 g"),
    ("branded",         "Fage Total 0% Greek Yogurt",     "170 g"),
    ("branded",         "Quest Bar Chocolate Brownie",    "60 g"),
    ("branded",         "Muscle Milk Pro Series Vanilla", "330 g"),
    ("branded",         "Kodiak Cakes Buttermilk Mix",    "53 g"),
    # ⭐ THE STRATUM THAT DECIDES WHETHER USDA ALONE CAN FINISH THE JOB.
    ("non_latin",       "творог",                         "200 g"),
    ("non_latin",       "гречка",                         "150 g"),
    ("non_latin",       "сметана 20%",                    "50 g"),
    ("non_latin",       "шакшука",                        "300 g"),
    ("non_latin",       "онигири",                        "110 g"),
    ("non_latin",       "плов",                           "300 g"),
    # Should refuse by NAME, not crash and not silently succeed on a wrong food.
    ("expected_refuse", "my grandmother's secret stew",   "300 g"),
    ("expected_refuse", "zzzqqx not a food at all",       "100 g"),
]


async def _one(db, stratum, identity, quantity):
    from core.general_settlement import Supported, acquirable, coverage_for, look
    from skills.nutrition.acquisition import (ACQUIRE_TURN_BUDGET_S,
                                              AcquisitionRefused, acquire)

    item = {"food_name": identity, "quantity": quantity, "calories": 999.0}
    row = {"stratum": stratum, "identity": identity, "quantity": quantity}

    facts = await look(db, user_id=0, item=item)
    pre = await coverage_for(db, user_id=0, items=[item])
    row["pre_supported"] = isinstance(pre, Supported)
    row["acquirable"] = acquirable(facts)
    if row["pre_supported"] or not row["acquirable"]:
        row["disposition"] = "skipped_already_held" if row["pre_supported"] \
            else "not_acquirable"
        return row

    t0 = time.monotonic()
    try:
        got = await acquire(db, identity=identity, deadline_s=ACQUIRE_TURN_BUDGET_S)
        row["elapsed_s"] = round(time.monotonic() - t0, 2)
        row["acquired"] = True
        row["evidence_id"] = got.source_identifier
        row["candidates"] = len(got.nutrition_evidence)
        row["authority_grade"] = got.authority_grade
    except AcquisitionRefused as refused:
        row["elapsed_s"] = round(time.monotonic() - t0, 2)
        row["acquired"] = False
        row["refusal"] = refused.reason
    except Exception as exc:                             # noqa: BLE001
        row["elapsed_s"] = round(time.monotonic() - t0, 2)
        row["acquired"] = False
        row["refusal"] = f"EXC:{type(exc).__name__}"
        row["detail"] = str(exc)[:120]

    # ⭐ SAME-TURN is elapsed <= the budget AND the settlement actually flips.
    # "Evidence persisted" is not "canonical owns it" — the read path and the
    # rung ladder still decide, and conflating the two is exactly the
    # bypass this architecture refuses.
    post = await coverage_for(db, user_id=0, items=[item])
    row["post_supported"] = isinstance(post, Supported)
    row["settled_rung"] = getattr(post, "expected_source", "") or ""
    row["same_turn"] = bool(row.get("acquired")
                            and row["elapsed_s"] <= ACQUIRE_TURN_BUDGET_S
                            and row["post_supported"])
    row["disposition"] = ("same_turn" if row["same_turn"]
                          else "deferred" if row.get("acquired")
                          else "refused")
    return row


async def main(out_path, limit):
    from db.database import AsyncSessionLocal

    rows = []
    for stratum, identity, qty in POPULATION[:limit]:
        async with AsyncSessionLocal() as db:
            try:
                r = await _one(db, stratum, identity, qty)
                await db.commit()
            except Exception as exc:                     # noqa: BLE001
                await db.rollback()
                r = {"stratum": stratum, "identity": identity,
                     "disposition": "harness_error", "detail": str(exc)[:160]}
        rows.append(r)
        print(f"  {r['disposition']:22} {stratum:17} {identity[:30]:32} "
              f"{r.get('elapsed_s','-'):>6}s  {r.get('refusal','')}")

    n = len(rows)
    acq = [r for r in rows if r.get("acquired")]
    lat = sorted(r["elapsed_s"] for r in rows if "elapsed_s" in r)
    pct = lambda p: lat[min(int(len(lat) * p), len(lat) - 1)] if lat else None
    summary = {
        "n": n,
        "same_turn_pct": round(100 * sum(r.get("same_turn", False) for r in rows) / n, 1),
        "acquired_pct": round(100 * len(acq) / n, 1),
        "settled_pct": round(100 * sum(r.get("post_supported", False) for r in rows) / n, 1),
        "p50_s": pct(0.50), "p95_s": pct(0.95),
        "refusals": {},
        "by_stratum": {},
        # ⛔ THE HARD SAFETY GATE. Any nonzero value stops the lane.
        "wrong_canonical_settlements": sum(
            1 for r in rows
            if r.get("post_supported") and r["stratum"] == "expected_refuse"),
    }
    for r in rows:
        if r.get("refusal"):
            summary["refusals"][r["refusal"]] = summary["refusals"].get(r["refusal"], 0) + 1
        s = summary["by_stratum"].setdefault(
            r["stratum"], {"n": 0, "acquired": 0, "settled": 0})
        s["n"] += 1
        s["acquired"] += bool(r.get("acquired"))
        s["settled"] += bool(r.get("post_supported"))

    pathlib.Path(out_path).write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False))
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["wrong_canonical_settlements"]:
        print("\n⛔ WRONG CANONICAL SETTLEMENT — the hard gate. STOP.")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/canary_acquisition_2026-09-01.json")
    ap.add_argument("--limit", type=int, default=len(POPULATION))
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    raise SystemExit(asyncio.run(main(a.out, a.limit)))
