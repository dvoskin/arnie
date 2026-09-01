"""WHICH AUTHORITATIVE SCALING BASIS COULD WE REALISTICALLY SUPPLY?

The counterfactual showed evidence producers recover ZERO and evidence+scaling
recovers nearly everything — but that arm grants the hard capability by fiat.
This asks the honest question underneath it:

    for each item canonical currently declines, WHICH of the three
    authoritative paths could actually be obtained?

`resolve_scaling` admits exactly three, in order (skills/nutrition/scaling.py):

    1  USER_STATED_EXACT_MASS      consumed.mass_is_exact
    2  DIRECTLY_COMPATIBLE_BASIS   a count of the label's OWN units, tested by
                                   stripping any heuristic mass so a piece-weight
                                   prior cannot masquerade as a direct match
    3  SOURCED_CONVERSION          ConversionEvidence, e.g. USDA 1 large egg = 50 g
    -  HEURISTIC                   piece_weight / vessel / ontology — scales, but
                                   is an ASSUMPTION and never settles

⛔ CLASSIFICATION IS FROM THE USER'S OWN QUANTITY PHRASE, and it is a HYPOTHESIS
about obtainability, not a promise. "2 eggs" is classifiable as
SOURCED_COUNT_TO_MASS because USDA publishes egg weights; whether a producer
can actually source every such item is the producer's problem to prove.

⚠ READ-ONLY. No repair, no rule weakened. It records what the population is
made of so the first scaling producer is chosen by measured opportunity rather
than by which phrase-shape feels most tractable.
"""
from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/scaling_basis_census_2026-08-31.json")

def classify(qty: str, food: str) -> str:
    """⛔⛔ CLASSIFIED BY THE PRODUCT'S OWN NORMALIZER, NOT BY A REGEX.

    The first version of this census matched quantity phrases with regexes and
    reported 112 items as USER_STATED_EXACT_MASS with `already authoritative =
    0` in EVERY bucket — an impossible pairing, and the tell that the buckets
    were not measuring what `resolve_scaling` measures. Two causes, both
    invisible in the totals:

        '300 г Окрошка…'          the mass regex matched Latin `g`, not
                                  Cyrillic `г`, so real stated masses landed
                                  in OTHER
        '1 piece (~120g) …'       `~` marks the mass APPROXIMATE; the regex
                                  called it exact

    `mass_is_exact` is a property of `NormalizedQuantity` — `normalization_
    source in ("mass_conversion", "volume_conversion")` — and
    `count_is_serving_compatible` is likewise the product's own test. Asking
    them directly cannot disagree with the gate this census exists to explain.
    """
    from skills.nutrition.normalize import normalize_quantity
    raw = (qty or "").strip()
    if not raw:
        return "NO_QUANTITY_AT_ALL"
    try:
        q = normalize_quantity(raw, food or "")
    except Exception:
        return "NORMALIZER_FAILED"
    if q.mass_is_exact:
        return "1_USER_STATED_EXACT_MASS"
    if q.count_is_serving_compatible:
        return "2_COUNT_serving_compatible_needs_LABEL_or_SOURCED_basis"
    if q.count is not None:
        return "3_COUNT_estimate_basis_needs_SOURCED_conversion"
    if getattr(q, "grams", None):
        return "4_HEURISTIC_MASS_only_needs_a_sourced_replacement"
    return "5_NO_BASIS_no_count_no_mass"


async def main() -> int:
    import core.general_settlement as GS
    from core.general_settlement import Supported
    from scripts import measure_settlement_coverage as M

    seen: list = []
    _look, _decide = GS.look, GS.decide

    async def look_spy(db, *, user_id, item):
        facts = await _look(db, user_id=user_id, item=item)
        seen.append((dict(item), facts))
        return facts
    GS.look = look_spy
    try:
        pop = json.loads(pathlib.Path(
            "data/corpus/population_p16b_0817.json").read_text())
        rep = await M.measure(days=30, limit=2000, population=pop)
    finally:
        GS.look = _look

    print(f"baseline {rep['C_ownership_rate_pct']}%  "
          f"({rep['supported_structured_meals']}/{rep['structured_meals']} structured)")
    declining = [(i, f) for i, f in seen if not isinstance(_decide(f), Supported)]
    print(f"recorded {len(seen)} item looks, {len(declining)} declining\n")

    buckets = collections.Counter()
    already = collections.Counter()
    examples: dict = {}
    for item, facts in declining:
        qty = str(item.get("quantity") or item.get("amount") or "")
        food = str(item.get("food_name") or item.get("food") or "")
        b = classify(qty, food)
        buckets[b] += 1
        examples.setdefault(b, f"{qty} {food}".strip()[:52])
        if facts.selected_rung_authoritative:
            already[b] += 1

    print(f"{'OBTAINABLE BASIS':<46}{'items':>7}{'already auth':>14}")
    for b, n in buckets.most_common():
        print(f"  {b:<44}{n:>7}{already[b]:>14}   e.g. {examples[b]!r}")
    OUT.write_text(json.dumps(
        {"baseline_pct": rep["C_ownership_rate_pct"],
         "declining_items": len(declining),
         "buckets": dict(buckets), "already_authoritative": dict(already),
         "examples": examples}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
