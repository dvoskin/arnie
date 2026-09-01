"""WHICH ENTITIES WOULD AN ARTIFACT EXPANSION HAVE TO COVER, AND WHAT DOES EACH BUY?

`build_pricing_artifact.SEED` is 21 entities -> 27 artifact entries, and its own
comment forbids growing it on intuition:

    "Seems likely someone will log this" is NOT a criterion. It turns a curated
    set into an intuition-driven catalog, and the directive's own rule is
    measure before generalize.

⭐ THIS IS THAT MEASUREMENT. It ranks entities by MEALS RECOVERED, not by item
frequency, and it does so through the real machinery: artifact evidence is
granted ONLY to items whose entity is in the candidate seed, then
`select_priced_rung` + `resolve_scaling` + unchanged `decide()` run, and meals
are scored whole — one uncovered item still sinks its meal.

⚠ So a frequent entity buys nothing if it always appears beside an uncovered
one. That is the property a frequency ranking cannot see and a meal-level curve
can.
"""
from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/artifact_demand_curve_2026-08-31.json")
PANEL = {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 8.0}


async def main() -> int:
    import core.general_settlement as GS
    from core.canonical_pricing import (ArtifactEvidence, _from_artifact,
                                        _from_memory, _from_product,
                                        _ranker_query, select_priced_rung)
    from core.general_settlement import ItemFacts, Supported, decide
    from scripts import measure_settlement_coverage as M
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import split_identity

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

    base = rep["C_ownership_rate_pct"]
    now = rep["supported_structured_meals"]
    denom = round(now / (base / 100.0)) if base else 0
    print(f"baseline {base}%  ({now}/{denom})\n")

    def recovers(item, facts, covered: set) -> bool:
        if isinstance(decide(facts), Supported):
            return True
        ident = str(item.get("food_name") or item.get("food") or "").strip()
        ent, prep = split_identity(ident)
        qty = str(item.get("quantity") or "").strip()
        if not qty or ent.lower() not in covered:
            return False
        ev = ArtifactEvidence(candidates=(
            {"description": ent, "per100g": dict(PANEL),
             "fdc_id": f"sim:{ent}", "_match": "exact"},), fingerprint="sim")
        try:
            sel = select_priced_rung(
                entity=ent, preparation=prep,
                consumed=normalize_quantity(qty, ident),
                rungs=((None, _from_memory), (None, _from_product),
                       (ev, lambda e: _from_artifact(
                           e, query=_ranker_query(ent, prep)))),
                bound=False)
        except Exception:
            return False
        return isinstance(decide(ItemFacts(
            identity=facts.identity, entity=facts.entity,
            preparation=facts.preparation, has_identity=facts.has_identity,
            has_quantity=facts.has_quantity, has_mass=facts.has_mass,
            has_memory=False, has_artifact=True,
            product_bound=facts.product_bound,
            product_scales=facts.product_scales,
            selected_rung=(sel.rung.value if sel.rung is not None else ""),
            selected_rung_authoritative=bool(sel.authoritative))), Supported)

    declining_meals = [g for g in meals if g and
                       any(not isinstance(decide(f), Supported) for _, f in g)]
    ents = collections.Counter()
    for g in declining_meals:
        for item, f in g:
            if isinstance(decide(f), Supported):
                continue
            e, _ = split_identity(str(item.get("food_name") or "").strip())
            if e:
                ents[e.lower()] += 1
    print(f"{len(declining_meals)} declining meals · "
          f"{len(ents)} distinct entities · top by ITEM frequency:")
    for e, n in ents.most_common(12):
        print(f"   {n:>4}  {e[:44]}")

    # ⭐ GREEDY MEAL-LEVEL CURVE: at each step add the entity that unlocks the
    # most ADDITIONAL whole meals. Frequency ranking cannot do this, because an
    # entity is worth nothing until every OTHER item in its meals is covered too.
    covered: set = set()
    curve = []
    pool = [e for e, _ in ents.most_common()]
    for step in range(1, 41):
        best, best_gain = None, 0
        cur = sum(1 for g in declining_meals
                  if all(recovers(i, f, covered) for i, f in g))
        for e in pool:
            if e in covered:
                continue
            trial = covered | {e}
            gain = sum(1 for g in declining_meals
                       if all(recovers(i, f, trial) for i, f in g)) - cur
            if gain > best_gain:
                best, best_gain = e, gain
        if not best:
            break
        covered.add(best)
        tot = cur + best_gain
        pct = round(100.0 * (now + tot) / denom, 1) if denom else None
        curve.append({"step": step, "entity": best, "meals": tot, "pct": pct})
        print(f"  +{step:>2} {best[:34]:<36} meals={tot:>4}  ownership={pct}%")
    OUT.write_text(json.dumps({"baseline_pct": base, "denominator": denom,
                               "entity_item_frequency": dict(ents.most_common()),
                               "greedy_curve": curve}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
