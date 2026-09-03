#!/usr/bin/env python
"""QUANTITY AUTHORITY — the census, before any implementation.

⭐⭐⭐ THE QUESTION THIS ANSWERS *(Danny, 2026-09-01)*: which SINGLE quantity
mechanism unlocks the largest additional share of real meals WITHOUT introducing
inference risk? Not "how many meals decline on quantity" — that number is
already known and is the wrong shape for choosing a tranche.

⛔⛔ AND IT MEASURES THE PURELY-QUANTITY-BLOCKED POPULATION DIRECTLY, rather than
inheriting the 156-meal decline figure. That figure is MEAL-level and attributed
to heuristic scaling; the item-level partition showed 242 of 257 declining items
had NO LOCAL EVIDENCE, and 150 of those already carried a mass. So an item can
decline "on scaling" while its real blocker is evidence. The two populations are
near-disjoint and conflating them would size the tranche wrong.

    evidence-blocked   no rung to scale       -> Identity Reachability (closed)
    quantity-blocked   rung exists, does NOT
                       scale authoritatively  -> THIS TRANCHE

⛔ DEV HALF ONLY. The 181-entry holdout stays sealed; there is nothing
publication-ready to validate.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

#: Quantity EXPRESSION classes. Ordered most-authoritative first, and matched in
#: that order so "1 cup (240 ml)" counts as the stated volume it carries rather
#: than the household measure it also mentions.
_CLASSES = (
    ("EXPLICIT_MASS",      r"\b\d+(\.\d+)?\s*(g|gram|grams|kg|oz|ounce|ounces|lb|г|гр|кг)\b"),
    ("EXPLICIT_VOLUME",    r"\b\d+(\.\d+)?\s*(ml|l|litre|liter|fl\s?oz|мл|л)\b"),
    ("COUNT",              r"^\s*\d+(\.\d+)?\s*(x\s*)?(egg|eggs|slice|slices|piece|pieces|bar|bars|"
                           r"shrimp|chip|chips|wing|wings|cookie|cookies|шт|штук)\b"),
    ("HOUSEHOLD_MEASURE",  r"\b(cup|cups|tbsp|tablespoon|tsp|teaspoon|scoop|scoops|"
                           r"стакан|ложка|ст\.?л|ч\.?л)\b"),
    ("PORTION_FRACTION",   r"\b(half|quarter|third|½|¼|⅓|полов|треть)\b"),
    ("PACKAGE_RESTAURANT", r"\b(bag|pack|packet|container|pot|bottle|can|tray|box|"
                           r"порция|упаковка)\b"),
    ("AMBIGUOUS_SERVING",  r"\b(serving|servings|bowl|plate|handful|portion|some|"
                           r"миска|тарелка)\b"),
)


def classify_quantity(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return "NO_QUANTITY_STATED"
    for name, pattern in _CLASSES:
        if re.search(pattern, t, re.I):
            return name
    if re.match(r"^\s*\d", t):
        return "COUNT_BARE"          # a number with an unrecognised unit
    return "UNCLASSIFIED"


async def main(population, out):
    from sqlalchemy import text as sql

    from core.general_settlement import look
    from db.database import AsyncSessionLocal

    ids = json.loads(pathlib.Path(
        f"data/corpus/population_{population}.json").read_text())

    rows_out = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql("""
            select fe.id, fe.parsed_food_name, fe.quantity, dl.user_id
            from food_entries fe join daily_logs dl on dl.id = fe.daily_log_id
            where fe.id = any(:ids) order by fe.id"""), {"ids": ids})).fetchall()

        for eid, name, qty, uid in rows:
            item = {"food_name": name or "", "quantity": qty or "",
                    "calories": 100.0}
            try:
                f = await look(db, user_id=uid, item=item)
            except Exception:                            # noqa: BLE001
                continue
            has_evidence = bool(f.has_artifact or f.has_memory)
            rows_out.append({
                "id": eid, "name": name, "quantity": qty,
                "quantity_class": classify_quantity(qty),
                "has_evidence": has_evidence,
                "has_mass": bool(f.has_mass),
                "scales": bool(f.selected_rung),
                # ⭐ THE POPULATION THIS TRANCHE OWNS: evidence EXISTS and the
                # rung still does not scale authoritatively. Everything else is
                # someone else's blocker.
                "quantity_blocked": has_evidence and not f.selected_rung,
            })

    qb = [r for r in rows_out if r["quantity_blocked"]]
    ev = [r for r in rows_out if r["has_evidence"]]
    print(f"dev entries          : {len(rows_out)}")
    print(f"  with local evidence: {len(ev)}")
    print(f"  QUANTITY-BLOCKED   : {len(qb)}   <- the tranche's population")
    print(f"  evidence-blocked   : {len(rows_out) - len(ev)}   (Identity Reachability, closed)")

    print(f"\n{'QUANTITY CLASS':22}{'ALL':>6}{'QTY-BLOCKED':>13}")
    allc = collections.Counter(r["quantity_class"] for r in rows_out)
    qbc = collections.Counter(r["quantity_class"] for r in qb)
    for k, n in allc.most_common():
        print(f"{k:22}{n:6}{qbc.get(k, 0):13}")

    if qb:
        print("\nquantity-blocked examples:")
        for r in qb[:20]:
            print(f"   {str(r['name'])[:30]:32} {str(r['quantity'])[:18]:20} "
                  f"{r['quantity_class']}")
    pathlib.Path(out).write_text(json.dumps(rows_out, indent=2, ensure_ascii=False))
    print(f"\nwritten -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", default="p16b_dev_0901")
    ap.add_argument("--out", default="/tmp/census_quantity_dev.json")
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    asyncio.run(main(a.population, a.out))
