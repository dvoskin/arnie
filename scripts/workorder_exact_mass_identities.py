"""THE PHASE 1B WORK ORDER — identities inside the 68 exact-mass meals.

⭐ PHASE 1B IS *AUTHORITATIVE EVIDENCE ACQUISITION* for these identities, and
materializing a canonical artifact ONLY where source authority is established.
It is NOT "generate artifacts for 68 meals": an artifact written from a legacy
estimate would manufacture authority out of a guess, which is the one thing the
whole settlement architecture exists to prevent.

⛔ RANKED BY MEALS UNLOCKED, NEVER BY ITEM COUNT. Ownership is a meal rate and
one uncovered item sinks its meal, so an identity appearing 6 times across 6
meals that each contain another uncovered food is worth ZERO, while one
appearing twice in two otherwise-complete meals is worth 2. Item frequency
cannot see that; this ordering can.

The arithmetic this serves:
    baseline                        20 / 222  =  9.0%
    all 68 exact-mass meals         88 / 222  = 39.6%
    the fixed gate                  89 / 222  = 40.0%
-> one meal BEYOND the exact-mass population crosses it, which is why a single
   clean identity-bound count case is worth as much as the whole tail.
"""
from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/phase1b_workorder_2026-08-31.json")


async def main() -> int:
    import core.general_settlement as GS
    from core.general_settlement import Supported, decide
    from scripts import measure_settlement_coverage as M
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import (evidence_for, split_identity)

    meals: list = []
    _look, _cov = GS.look, GS.coverage_for

    async def look_spy(db, *, user_id, item):
        f = await _look(db, user_id=user_id, item=item)
        if meals:
            meals[-1].append((dict(item), f))
        return f

    async def cov_spy(db, *, user_id, items):
        meals.append([])
        return await _cov(db, user_id=user_id, items=items)
    GS.look, GS.coverage_for = look_spy, cov_spy
    try:
        pop = json.loads(pathlib.Path(
            "data/corpus/population_p16b_0817.json").read_text())
        rep = await M.measure(days=30, limit=2000, population=pop)
    finally:
        GS.look, GS.coverage_for = _look, _cov

    base, now = rep["C_ownership_rate_pct"], rep["supported_structured_meals"]
    denom = round(now / (base / 100.0)) if base else 0

    # the 68: every DECLINING item in the meal is exact-mass
    target = []
    for g in meals:
        if not g:
            continue
        decl = [(i, f) for i, f in g if not isinstance(decide(f), Supported)]
        if not decl:
            continue
        ok = True
        for item, _f in decl:
            qty = str(item.get("quantity") or "").strip()
            try:
                ok = ok and bool(qty) and normalize_quantity(
                    qty, str(item.get("food_name") or "")).mass_is_exact
            except Exception:
                ok = False
            if not ok:
                break
        if ok:
            target.append(decl)
    print(f"baseline {base}%  ({now}/{denom})   exact-mass meals: {len(target)}")

    # identity -> the meals it appears in
    by_ident: dict = collections.defaultdict(set)
    freq = collections.Counter()
    meta: dict = {}
    for mi, decl in enumerate(target):
        for item, _f in decl:
            raw = str(item.get("food_name") or item.get("food") or "").strip()
            ent, prep = split_identity(raw)
            key = f"{ent}|{prep}"
            by_ident[key].add(mi)
            freq[key] += 1
            meta.setdefault(key, {"raw": raw, "entity": ent, "prep": prep,
                                  "artifact_now": bool(evidence_for(ent, prep))})

    # ⭐ GREEDY BY MEALS UNLOCKED: a meal counts only when EVERY identity in it
    # is covered, so marginal yield is what matters, not membership.
    need = {mi: {k for k in by_ident if mi in by_ident[k]} for mi in range(len(target))}
    covered: set = set()
    order = []
    while True:
        best, gain = None, 0
        for k in by_ident:
            if k in covered:
                continue
            trial = covered | {k}
            g = sum(1 for mi, ks in need.items() if ks <= trial) - \
                sum(1 for mi, ks in need.items() if ks <= covered)
            if g > gain:
                best, gain = k, g
        if not best:
            break
        covered.add(best)
        total = sum(1 for mi, ks in need.items() if ks <= covered)
        order.append({"identity": best, "meals_unlocked_marginal": gain,
                      "meals_cumulative": total,
                      "ownership_pct": round(100.0 * (now + total) / denom, 1),
                      "items": freq[best], "artifact_now": meta[best]["artifact_now"],
                      "example": meta[best]["raw"][:52]})

    print(f"\n{len(by_ident)} distinct identities across the {len(target)} meals\n")
    print(f"{'#':>3} {'identity':<40}{'+meals':>7}{'cum':>5}{'own%':>7}{'items':>6}")
    for n, r in enumerate(order[:30], 1):
        print(f"{n:>3} {r['identity'][:38]:<40}{r['meals_unlocked_marginal']:>7}"
              f"{r['meals_cumulative']:>5}{r['ownership_pct']:>7}{r['items']:>6}")
    singles = sum(1 for k in by_ident if freq[k] == 1)
    print(f"\n  identities appearing once: {singles}/{len(by_ident)}")
    print(f"  identities WITH artifact today: "
          f"{sum(1 for k in meta if meta[k]['artifact_now'])}")
    OUT.write_text(json.dumps({"baseline_pct": base, "denominator": denom,
                               "supported_now": now,
                               "exact_mass_meals": len(target),
                               "distinct_identities": len(by_ident),
                               "work_order": order}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
