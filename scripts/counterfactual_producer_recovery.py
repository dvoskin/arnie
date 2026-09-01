"""WHICH EVIDENCE PRODUCER ACTUALLY BUYS OWNERSHIP?

⛔ BLOCKER COUNT IS NOT RECOVERY. 261 items carry NO_LOCAL_EVIDENCE and 159 are
sole-blocked by it — but `decide()` checks `selected_rung_authoritative` BEFORE
it ever looks at an evidence flag:

    has_identity -> has_quantity -> ⭐ selected_rung_authoritative ->
    selected_rung -> has_memory -> has_artifact -> Unsupported

So manufacturing admissible evidence can recover NOTHING if the quantity still
scales only heuristically. The overlap between "no evidence" and "cannot scale"
is the number that decides the first producer, and it has never been measured.

⭐ THE METHOD: record the REAL `ItemFacts` the shipped instrument computes, then
replay UNCHANGED `decide()` over counterfactual variants of those facts. The
producer is simulated by changing FACTS ONLY — no rule is weakened, no branch
is edited. A recovery that needs `decide()` to change is not a recovery.

⚠ AND THE OPTIMISTIC ARMS ARE LABELLED AS UPPER BOUNDS. Granting both evidence
AND authoritative scaling assumes a producer that always lands a sourced
conversion or an exact basis, which no real producer will. The gap between the
evidence-only arm and the optimistic arm IS the scaling problem, quantified.
"""
from __future__ import annotations

import asyncio
import collections
import dataclasses
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/counterfactual_producer_recovery_2026-08-31.json")

#: Each arm changes ONLY the facts a producer would create.
ARMS = {
    "artifact_evidence_only":
        dict(has_artifact=True),
    "memory_evidence_only":
        dict(has_memory=True),
    "product_bound_only":
        dict(product_bound=True),
    # ── upper bounds: evidence AND the scaling a perfect producer would give ──
    "artifact_PLUS_authoritative_scaling":
        dict(has_artifact=True, selected_rung="artifact",
             selected_rung_authoritative=True),
    "memory_PLUS_authoritative_scaling":
        dict(has_memory=True, selected_rung="memory",
             selected_rung_authoritative=True),
    "product_bound_AND_scales":
        dict(product_bound=True, product_scales=True),
}


async def main() -> int:
    import core.general_settlement as GS
    from core.general_settlement import Supported
    from scripts import measure_settlement_coverage as M

    # ⭐ RECORD, NEVER RE-DERIVE. Wrapping `decide` captures the exact facts the
    # shipped instrument computed on the exact population it selected, so the
    # counterfactual cannot disagree with the baseline it is measured against.
    # ⛔⛔ MEALS, NOT ITEMS. Ownership is a MEAL rate and ONE unsupported item
    # declines the whole meal, so recovered ITEMS overstate recovered MEALS.
    # The first version of this script reported 480 item-decisions as though
    # they were the recovery, which is the instrument's own documented warning
    # ("item counts are not ownership points") arriving from the other side.
    #
    # `coverage_for` is the meal boundary: it calls look()+decide() per item of
    # ONE meal, so wrapping it groups the facts correctly without re-deriving
    # the population.
    meals_facts: list = []
    _decide = GS.decide
    # `measure()` does `from core.general_settlement import coverage_for`
    # INSIDE the function, so the name resolves at call time — patching the
    # SOURCE module works and patching the script module does not.
    _coverage_for = GS.coverage_for

    def spy(facts):
        v = _decide(facts)
        if meals_facts:
            meals_facts[-1].append(facts)
        return v

    async def cov(db, *, user_id, items):
        meals_facts.append([])
        return await _coverage_for(db, user_id=user_id, items=items)

    GS.decide = spy
    M.decide = spy
    GS.coverage_for = cov
    try:
        pop = json.loads(pathlib.Path(
            "data/corpus/population_p16b_0817.json").read_text())
        report = await M.measure(days=30, limit=2000, population=pop)
    finally:
        GS.decide = _decide
        M.decide = _decide
        GS.coverage_for = _coverage_for

    base_own = report["C_ownership_rate_pct"]
    structured = report["structured_meals"]
    supported_now = report["supported_structured_meals"]
    # C = supported / ordinary-food-chat meals, so the denominator is derivable
    denom = round(supported_now / (base_own / 100.0)) if base_own else 0
    print(f"baseline ownership {base_own}%  ({supported_now}/{denom} ordinary "
          f"meals, {structured} structured)")

    groups = [g for g in meals_facts if g]
    declining_meals = [g for g in groups
                       if any(not isinstance(_decide(f), Supported) for f in g)]
    print(f"recorded {len(groups)} meals, {sum(len(g) for g in groups)} items; "
          f"{len(declining_meals)} meals declining\n")

    print(f"{'ARM':<40}{'meals':>7}{'items':>8}{'new own %':>11}")
    rows = {}
    for name, patch in ARMS.items():
        rec_meals, rec_items, blocked = 0, 0, collections.Counter()
        for g in declining_meals:
            all_ok = True
            for facts in g:
                if isinstance(_decide(facts), Supported):
                    continue
                v = _decide(dataclasses.replace(facts, **patch))  # UNCHANGED decide()
                if isinstance(v, Supported):
                    rec_items += 1
                else:
                    all_ok = False
                    blocked[getattr(v, "reason", "?")[:58]] += 1
            if all_ok:
                rec_meals += 1
        new_own = round(100.0 * (supported_now + rec_meals) / denom, 1) if denom else None
        rows[name] = {"recovered_meals": rec_meals, "recovered_items": rec_items,
                      "theoretical_ownership_pct": new_own,
                      "still_blocked": dict(blocked)}
        print(f"  {name:<38}{rec_meals:>7}{rec_items:>8}{str(new_own):>11}")
    print()
    print("=== what still blocks, after the best arm ===")
    best = max(rows, key=lambda k: rows[k]["recovered_items"])
    for r, c in sorted(rows[best]["still_blocked"].items(), key=lambda x: -x[1])[:5]:
        print(f"  {c:5d}  {r}")
    OUT.write_text(json.dumps(
        {"baseline_ownership_pct": base_own, "denominator_meals": denom,
         "supported_now": supported_now, "declining_meals": len(declining_meals),
         "arms": rows}, indent=1, default=str) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
