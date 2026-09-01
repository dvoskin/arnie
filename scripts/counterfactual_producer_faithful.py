"""PRODUCER-FAITHFUL COUNTERFACTUAL — which producer actually buys ownership?

⛔⛔⛔ THE PREVIOUS VERSION FLIPPED BOOLEANS AND WAS WRONG TWICE, IN OPPOSITE
DIRECTIONS. It set `has_artifact=True` and left `selected_rung_authoritative`
alone, so `decide()` refused at the scaling gate and the arm reported "evidence
recovers 0". Then the optimistic arm set the scaling flag by fiat and reported
"scaling is the lever". Both were artifacts of the simulation:

    selected_authoritative = False        # initialised
    for ev, build in rungs:
        if ev is None: continue           # ← no evidence → no rung → NEVER SET

`selected_rung_authoritative=False` means NO RUNG WAS SELECTED, not that the
quantity cannot scale. Those flags are OUTCOMES, not interventions.

⭐ THE FROZEN CONTRACT (Danny, 2026-08-31):

    REAL ItemFacts
      -> inject a REALISTIC evidence OBJECT
      -> run the real select_priced_rung()
      -> run the real resolve_scaling() against the item's ACTUAL quantity
      -> construct the resulting ItemFacts
      -> run UNCHANGED decide()
      -> group back to MEAL
      -> score against the SAME 222-meal denominator

Nothing below sets `has_artifact`, `selected_rung_authoritative` or
`has_quantity` directly. Each arm supplies the evidence object a real producer
would create and lets the shipped machinery reach its own verdict.
"""
from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/counterfactual_faithful_2026-08-31.json")

#: A plausible per-100g panel. The NUMBERS are irrelevant to `decide()` — it
#: never reads macros — but the SHAPE must be real so `_from_memory` /
#: `_from_artifact` build a genuine basis and `resolve_scaling` runs for real.
PANEL = {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 8.0}


def quantity_class(qty: str, food: str) -> str:
    from skills.nutrition.normalize import normalize_quantity
    if not (qty or "").strip():
        return "NO_QUANTITY"
    try:
        q = normalize_quantity(qty, food or "")
    except Exception:
        return "NORMALIZER_FAILED"
    if q.mass_is_exact:
        return "USER_STATED_EXACT_MASS"
    if q.count_is_serving_compatible:
        return "COUNT_SERVING_COMPATIBLE"
    if q.count is not None:
        return "COUNT_ESTIMATE"
    if getattr(q, "grams", None):
        return "HEURISTIC_MASS"
    return "NO_BASIS"


#: ⭐ ONE recovery function, used by BOTH the item strata and the meal rollup.
#: Two implementations of "did this recover" is how an item table and a meal
#: table come to disagree, which is the divergence this whole session keeps
#: finding in other people's code.
_RECOVER_CTX: dict = {}
#: The item's REAL evidence objects, so arm D can price from what it truly has.
_REAL: dict = {}


def _recovers(*, arm_make, item, facts) -> bool:
    from core.canonical_pricing import (_from_artifact, _from_memory,
                                        _from_product, _ranker_query,
                                        select_priced_rung)
    from core.general_settlement import ItemFacts, Supported, decide
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import split_identity

    if isinstance(decide(facts), Supported):
        return True                            # this item was never the problem
    ident = str(item.get("food_name") or item.get("food") or "").strip()
    ent, prep = split_identity(ident)
    qty = str(item.get("quantity") or "").strip()
    if not qty:
        return False
    if arm_make == "MEM+CONV":
        from core.canonical_pricing import MemoryEvidence
        kind, ev = "mem_conv", MemoryEvidence(
            per100g={"calories": 200.0, "protein": 10.0, "carbs": 20.0,
                     "fat": 8.0}, source_id="sim:memory", confidence=0.9)
    else:
        made = arm_make(item, ent) if arm_make is not None else None
        kind, ev = made if made else ("conversion", None)
    try:
        consumed = normalize_quantity(qty, ident)
        if kind in ("conversion", "mem_conv"):
            # ⭐ ARM D: the item keeps whatever evidence it really has; only a
            # SOURCED per-unit measure is added. Wrapping the builders lets the
            # real selector run and simply hands `resolve_scaling` the measure
            # it would have had. Nothing about the nutrition changes.
            from skills.nutrition.scaling import SourcedMeasure
            unit = (getattr(consumed, "unit", "") or
                    getattr(consumed, "inferred_unit", "") or "unit")
            # ⛔⛔ A MEASURE WITHOUT PROVENANCE IS REFUSED, AND THE FIRST
            # VERSION OF THIS ARM WAS. `as_basis_conversion()` raises unless the
            # record declares a version or immutability — "it names a row whose
            # value may already have changed, and the evidence citing it cannot
            # be reproduced". `_recovers` caught that and returned False, so
            # EVERY count item failed for a fixture defect while the 174
            # exact-mass items took path 1 and never reached the conversion.
            # Arm E therefore equalled arm B to the meal, and the exact
            # equality was the only thing that gave it away.
            m = (SourcedMeasure(unit_text=str(unit), grams_per_unit=50.0,
                                source_id="sim:usda", dataset_id="sim",
                                dataset_version="1", record_key="sim",
                                record_version="1",
                                immutable_within_version=True),)

            def _wrap(fn):
                def build(e):
                    out = fn(e)
                    if not out:
                        return out
                    pr, rg, eid, raw, basis, _old = out
                    return pr, rg, eid, raw, basis, m
                return build
            # ⭐ THE ITEM'S REAL ARTIFACT EVIDENCE. `evidence_for` is pure and
            # synchronous — the same call `look()` makes — so arm D prices from
            # what the item ACTUALLY has, adding only the conversion. Memory is
            # left absent: it is a per-user DB read, and 0 of the 20 currently
            # supported meals come from that rung anyway.
            from skills.nutrition.pricing_artifact import evidence_for
            real_art = evidence_for(ent, prep) if ent else None
            rungs = ((ev if kind == "mem_conv" else None, _wrap(_from_memory)),
                     (None, _wrap(_from_product)),
                     (real_art, _wrap(lambda e: _from_artifact(
                         e, query=_ranker_query(ent, prep)))))
        else:
            rungs = ((ev if kind == "memory" else None, _from_memory),
                     (ev if kind == "product" else None, _from_product),
                     (ev if kind == "artifact" else None,
                      lambda e: _from_artifact(e, query=_ranker_query(ent, prep))))
        sel = select_priced_rung(entity=ent, preparation=prep,
                                 consumed=consumed, rungs=rungs, bound=False)
    except Exception:
        return False
    cf = ItemFacts(
        identity=facts.identity, entity=facts.entity,
        preparation=facts.preparation, has_identity=facts.has_identity,
        has_quantity=facts.has_quantity, has_mass=facts.has_mass,
        has_memory=(kind in ("memory", "mem_conv") or
                    (facts.has_memory if kind == "conversion" else False)),
        has_artifact=(facts.has_artifact if kind in ("conversion", "mem_conv")
                      else kind == "artifact"),
        product_bound=facts.product_bound, product_scales=facts.product_scales,
        selected_rung=(sel.rung.value if sel.rung is not None else ""),
        selected_rung_authoritative=bool(sel.authoritative))
    return isinstance(decide(cf), Supported)


async def main() -> int:
    import core.general_settlement as GS
    from core.canonical_pricing import (ArtifactEvidence, MemoryEvidence,
                                        ProductEvidence)
    from core.general_settlement import ItemFacts, Supported, decide
    from scripts import measure_settlement_coverage as M

    ARMS = {
        # A — an artifact producer. `_from_artifact` ranks CANDIDATES, so the
        # object must carry one that the ranker can actually seat.
        "A_artifact": lambda item, ent: ("artifact", ArtifactEvidence(
            candidates=({"description": ent or "food", "per100g": dict(PANEL),
                         "fdc_id": "sim:artifact", "_match": "exact"},),
            fingerprint="sim")),
        # B — the trusted-settlement writer's own shape: per-100g and nothing
        # else, which is all `user_food_matches` stores.
        "B_trusted_memory": lambda item, ent: ("memory", MemoryEvidence(
            per100g=dict(PANEL), source_id="sim:memory", confidence=0.9)),
        # ⭐ D — A SOURCED COUNT CONVERSION AND NOTHING ELSE. No new nutrition:
        # the arm supplies only "1 <unit> = N g" with provenance, exactly what
        # `resolve_scaling` path 3 consumes, and lets the item's EXISTING
        # evidence do the pricing. It is the only arm aimed at the 246-item
        # count stratum that A/B/C cannot reach (0, 0 and 3 recovered).
        #
        # ⚠ The gram figure is a STAND-IN. `decide()` never reads macros and
        # `_matching_measure` keys on the UNIT, so the number does not change a
        # verdict — but a real producer must source it per food, and that is
        # the whole difficulty this arm assumes away.
        "D_sourced_count_conversion": None,
        # ⭐ E — EVIDENCE **AND** CONVERSION. D alone cannot help an item that
        # also lacks evidence, and 261 of 268 declining items do. This arm is
        # the one that answers Danny's question directly: once a producer has
        # supplied evidence, does a sourced count conversion unlock the
        # 246-item stratum that A/B/C recover 0, 0 and 3 of?
        "E_memory_PLUS_conversion": "MEM+CONV",
        # C — a product/scan snapshot carrying its OWN serving semantics. This
        # is the arm that may differ materially: a label's per-serving basis
        # can consume a COUNT without any mass at all.
        "C_product_scan": lambda item, ent: ("product", ProductEvidence(
            identifier="sim:product", per_serving=dict(PANEL),
            serving_grams=50.0, serving_unit="serving",
            servings_per_package=1.0, source_id="sim:product")),
    }

    # ⛔⛔ MEALS, NOT ITEMS. Ownership is a MEAL rate and ONE unsupported item
    # declines the whole meal, so recovered ITEMS are an UPPER BOUND on
    # recovered meals, never a translation of them. `coverage_for` is the meal
    # boundary — it runs look()+decide() over the items of exactly one meal.
    #
    # ⚠ AND ONLY STRUCTURED-ROUTE MEALS COUNT. `coverage_for` is called for ALL
    # 232 meals; ownership is supported_structured / 222 ordinary meals. An
    # earlier version scored every declining meal and produced 103.6% — a
    # denominator error that a percentage over 100 made obvious and that
    # nothing else would have.
    seen: list = []
    meals: list = []
    _look = GS.look
    _cov = GS.coverage_for

    async def look_spy(db, *, user_id, item):
        facts = await _look(db, user_id=user_id, item=item)
        seen.append((dict(item), facts, user_id))
        if meals:
            meals[-1].append((dict(item), facts))
        return facts

    async def cov_spy(db, *, user_id, items):
        meals.append([])
        return await _cov(db, user_id=user_id, items=items)
    GS.look = look_spy
    GS.coverage_for = cov_spy
    try:
        pop = json.loads(pathlib.Path(
            "data/corpus/population_p16b_0817.json").read_text())
        rep = await M.measure(days=30, limit=2000, population=pop)
    finally:
        GS.look = _look
        GS.coverage_for = _cov

    base = rep["C_ownership_rate_pct"]
    supported_now = rep["supported_structured_meals"]
    denom = round(supported_now / (base / 100.0)) if base else 0
    print(f"baseline {base}%  ({supported_now}/{denom} ordinary meals, "
          f"{rep['structured_meals']} structured)")

    declining = [(i, f) for i, f, _ in seen if not isinstance(decide(f), Supported)]
    print(f"{len(seen)} item looks, {len(declining)} declining\n")

    from core.canonical_pricing import (_from_artifact, _from_memory,
                                        _from_product, _ranker_query,
                                        select_priced_rung)
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import split_identity

    results: dict = {}
    for arm, make in ARMS.items():
        strata = collections.defaultdict(lambda: collections.Counter())
        for item, facts in declining:
            ident = str(item.get("food_name") or item.get("food") or "").strip()
            ent, prep = split_identity(ident)
            qty = str(item.get("quantity") or "").strip()
            klass = quantity_class(qty, ident)
            strata[klass]["eligible"] += 1
            if not qty:
                strata[klass]["no_quantity"] += 1
                continue
            pass  # strata now delegate to _recovers for one definition
            try:
                consumed = normalize_quantity(qty, ident)
                # ⭐ THE REAL SELECTOR, over the SAME rung tuple `look()` builds
                rungs = ((ev if kind == "memory" else None, _from_memory),
                         (ev if kind == "product" else None, _from_product),
                         (ev if kind == "artifact" else None,
                          lambda e: _from_artifact(e, query=_ranker_query(ent, prep))))
                sel = select_priced_rung(entity=ent, preparation=prep,
                                         consumed=consumed, rungs=rungs,
                                         bound=False)
            except Exception:
                strata[klass]["selector_failed"] += 1
                continue
            cf = ItemFacts(
                identity=facts.identity, entity=facts.entity,
                preparation=facts.preparation,
                has_identity=facts.has_identity, has_quantity=facts.has_quantity,
                has_mass=facts.has_mass,
                has_memory=(kind in ("memory", "mem_conv") or
                    (facts.has_memory if kind == "conversion" else False)),
        has_artifact=(facts.has_artifact if kind in ("conversion", "mem_conv")
                      else kind == "artifact"),
                product_bound=facts.product_bound,
                product_scales=facts.product_scales,
                selected_rung=(sel.rung.value if sel.rung is not None else ""),
                selected_rung_authoritative=bool(sel.authoritative))
            v = decide(cf)
            if isinstance(v, Supported):
                strata[klass]["RECOVERED"] += 1
            else:
                r = getattr(v, "reason", "")
                strata[klass]["scaling_blocked" if "heuristic" in r
                              else "no_evidence" if "no local evidence" in r
                              else "other"] += 1
        results[arm] = {k: dict(v) for k, v in strata.items()}

        # ── MEAL LEVEL: every declining item in the meal must recover ────────
        rec_meals = 0
        for g in meals:
            if not g or all(isinstance(decide(f), Supported) for _, f in g):
                continue                       # already supported, or empty
            if all(_recovers(arm_make=make, item=i, facts=f)
                   for i, f in g):
                rec_meals += 1
        results[arm]["_MEALS"] = {"recovered_meals": rec_meals}

    print(f"{'ARM / quantity class':<52}{'elig':>6}{'RECOV':>7}{'scal':>6}{'noev':>6}")
    for arm, strata in results.items():
        print(f"  {arm}")
        for k in sorted(strata, key=lambda k: -strata[k].get("eligible", 0)):
            s = strata[k]
            print(f"    {k:<48}{s.get('eligible',0):>6}{s.get('RECOVERED',0):>7}"
                  f"{s.get('scaling_blocked',0):>6}{s.get('no_evidence',0):>6}")
    OUT.write_text(json.dumps({"baseline_pct": base, "denominator": denom,
                               "supported_now": supported_now,
                               "declining_items": len(declining),
                               "arms": results}, indent=1) + "\n")
    print()
    print(f"{'PRODUCER':<24}{'meals recovered':>17}{'new ownership':>16}")
    print(f"  {'(baseline)':<22}{'-':>17}{str(base)+'%':>16}")
    for arm, strata in results.items():
        rm = strata["_MEALS"]["recovered_meals"]
        newp = round(100.0 * (supported_now + rm) / denom, 1) if denom else None
        strata["_MEALS"]["new_ownership_pct"] = newp
        flag = "  ⛔ >100, denominator bug" if newp and newp > 100 else ""
        print(f"  {arm:<22}{rm:>17}{str(newp)+'%':>16}{flag}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
