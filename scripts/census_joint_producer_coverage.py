"""JOINT PRODUCER COVERAGE — what is REALLY available, intersected at MEAL level.

⛔⛔ COVERAGE DOES NOT MULTIPLY. If memory covers 60% of foods and count
conversion covers 60% of count foods, recovery is NOT 36%: the two may overlap
heavily, barely, or land on DIFFERENT ITEMS OF THE SAME MEAL — and one
unsupported item still sinks the whole meal. Ownership is a meal rate, so the
only honest question is the JOINT one, per meal.

The counterfactual established CAPABILITY COMPLEMENTARITY (memory 65 + conversion
0 -> 163 meals). It assumed evidence for every item. This measures what actually
exists on the frozen population, so the first producer is chosen on REAL
recoverable meals rather than a theoretical ceiling.

⚠ WHAT THIS CANNOT DO. "Could acquire from normal use" and "has a defensible
sourced per-unit basis available today" are questions about the WORLD, not about
this database. This reports what is present NOW plus the unit distribution that
tells us whether count conversion is one producer or five wearing one label.
"""
from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/joint_producer_coverage_2026-08-31.json")


async def main() -> int:
    import core.general_settlement as GS
    from core.canonical_pricing_inputs import _memory
    from core.general_settlement import Supported, decide
    from scripts import measure_settlement_coverage as M
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    meals: list = []
    _look, _cov = GS.look, GS.coverage_for

    async def look_spy(db, *, user_id, item):
        f = await _look(db, user_id=user_id, item=item)
        if meals:
            meals[-1]["items"].append((dict(item), f))
        return f

    async def cov_spy(db, *, user_id, items):
        meals.append({"user_id": user_id, "items": [], "db": db})
        return await _cov(db, user_id=user_id, items=items)
    GS.look, GS.coverage_for = look_spy, cov_spy
    try:
        pop = json.loads(pathlib.Path(
            "data/corpus/population_p16b_0817.json").read_text())
        rep = await M.measure(days=30, limit=2000, population=pop)
    finally:
        GS.look, GS.coverage_for = _look, _cov

    base = rep["C_ownership_rate_pct"]
    supported_now = rep["supported_structured_meals"]
    denom = round(supported_now / (base / 100.0)) if base else 0
    print(f"baseline {base}%  ({supported_now}/{denom})\n")

    units = collections.Counter()
    have = collections.Counter()
    per_meal = []
    for m in meals:
        if not m["items"]:
            continue
        decl = [(i, f) for i, f in m["items"] if not isinstance(decide(f), Supported)]
        if not decl:
            continue
        rec = {"n_items": len(m["items"]), "n_declining": len(decl), "items": []}
        for item, facts in decl:
            ident = str(item.get("food_name") or item.get("food") or "").strip()
            ent, prep = split_identity(ident)
            qty = str(item.get("quantity") or "").strip()
            art = bool(evidence_for(ent, prep)) if ent else False
            prod = bool(item.get("product_evidence_id"))
            mem = bool(facts.has_memory)
            klass, unit = "NO_QUANTITY", ""
            if qty:
                try:
                    q = normalize_quantity(qty, ident)
                    unit = str(getattr(q, "unit", "") or
                               getattr(q, "inferred_unit", "") or "")
                    klass = ("EXACT_MASS" if q.mass_is_exact else
                             "COUNT_COMPAT" if q.count_is_serving_compatible else
                             "COUNT_EST" if q.count is not None else
                             "HEURISTIC" if getattr(q, "grams", None) else "NO_BASIS")
                except Exception:
                    klass = "NORMALIZER_FAILED"
            if klass in ("COUNT_COMPAT", "COUNT_EST") and unit:
                units[unit.lower()] += 1
            have[f"artifact={art}"] += 1
            have[f"memory={mem}"] += 1
            have[f"product={prod}"] += 1
            rec["items"].append({"class": klass, "unit": unit, "artifact": art,
                                 "memory": mem, "product": prod})
        per_meal.append(rec)

    print("=== REAL evidence availability on declining items ===")
    tot = sum(r["n_declining"] for r in per_meal)
    for k in sorted(have):
        print(f"  {k:<18}{have[k]:>5}   ({100*have[k]/max(tot,1):.0f}%)")
    print(f"\n  declining items: {tot}   declining meals: {len(per_meal)}")

    print("\n=== ⭐ UNIT DISTRIBUTION of count items — one producer, or five? ===")
    for u, n in units.most_common(14):
        print(f"  {n:>4}  {u}")
    print(f"  ({len(units)} distinct units across "
          f"{sum(units.values())} count items)")

    print("\n=== MEAL-LEVEL: could EVERY declining item in the meal be covered? ===")
    for label, ok in (
        ("artifact only", lambda it: it["artifact"]),
        ("memory only", lambda it: it["memory"]),
        ("artifact OR memory", lambda it: it["artifact"] or it["memory"]),
        ("artifact and EXACT_MASS", lambda it: it["artifact"] and it["class"] == "EXACT_MASS"),
    ):
        n = sum(1 for r in per_meal if all(ok(i) for i in r["items"]))
        newp = round(100.0 * (supported_now + n) / denom, 1) if denom else None
        print(f"  {label:<28}{n:>5} meals   -> {newp}%")

    OUT.write_text(json.dumps({"baseline_pct": base, "denominator": denom,
                               "declining_items": tot,
                               "declining_meals": len(per_meal),
                               "availability": dict(have),
                               "count_units": dict(units.most_common()),
                               "meals": per_meal}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
