"""A / B / C — is the correct SKU absent, unretrieved, or retrieved and LOST?

The previous probe recorded only the WINNER, so it could not tell three very
different populations apart:

    A  SOURCE COVERAGE      the correct product is not in OFF at all
    B  RETRIEVAL RECALL     it exists but is not in the candidate pool
    C  CANDIDATE SELECTION  it IS in the pool and `_overlap` promotes another

⭐ C IS THE INTERESTING BUCKET: the existing identity machinery may already
solve it, with no new evidence source. `_overlap` measures QUERY-TOKEN COVERAGE
and is used as an identity proxy — it prices the loss of a SKU discriminator
exactly like the loss of a redundant word, and charges nothing at all for
tokens the CANDIDATE adds:

    'Muscle Milk Pro Series Vanilla' -> 'Muscle Milk pro series'      0.80
    'Muscle Milk Pro Series Vanilla' -> 'Pro Series Vanilla Powder'   0.60
    'Oreo'                           -> 'Oreo Double Stuf'            1.00

So the better SKU can rank BELOW the worse one and the ordering is still
"correct" for the metric. This probe reads the whole pool so that claim becomes
a measurement instead of an example.

⛔ NO REPAIR IS AUTHORIZED FROM THIS. It sizes the buckets; it does not design
the fix. And it is a probe, not prevalence — the forward census owns that.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/off_candidate_pool_2026-08-31.json")

#: ⭐ THE SUPERSET FAMILY, as its own fixture class. The candidate contains MORE
#: words than the query, and those extra words change nutrition identity —
#: which query-anchored coverage fundamentally cannot represent, because it
#: only ever divides by the QUERY's tokens.
SUPERSETS = [
    ("Oreo", "Oreo Double Stuf"),
    ("Cheerios", "Honey Nut Cheerios"),
    ("Muscle Milk", "Muscle Milk Pro Series"),
    ("Barebells", "Barebells Soft Protein Bar"),
    ("Coke", "Coke Zero"),
]

#: The variant the user named must appear in the candidate for it to RESOLVE
#: the SKU. Deliberately crude and declared: this is a probe instrument, and a
#: token check that is wrong is visible in the output rather than hidden in a
#: score.
def _resolves(query: str, cand_name: str, brands: str = "") -> bool:
    """⛔⛔ THIS CHECKED THE PRODUCT NAME ONLY, AND THE BRAND LIVES IN A
    DIFFERENT FIELD. `_overlap` unions name AND brands; this did not, so
    'Pro Series Vanilla Protien Powder' (brands='Muscle Milk') scored as NOT
    resolving 'Muscle Milk Pro Series Vanilla' -- a record this session had
    already retrieved by barcode 0660016534113. The probe reported
    NOT_FOUND for a product it had held in its hand an hour earlier.
    Caught only by contradicting an EARLIER result; nothing in the run said so.
    """
    from skills.nutrition.off import _tokens
    q = _tokens(query)
    c = _tokens(cand_name) | _tokens(brands)
    return not (q - c)          # every query token present in name OR brands


async def main() -> int:
    from skills.nutrition import off
    from skills.nutrition.off import _overlap, _per100g, _tokens

    queries = sorted({c["intent"] for c in json.loads(
        pathlib.Path("data/corpus/branded_identity_truth_v1.json").read_text())["cases"]})

    print("=== SUPERSET FAMILY — what does coverage charge for added words? ===")
    for q, cand in SUPERSETS:
        print(f"  ov={_overlap(q, cand, ''):.2f}  {q!r} -> {cand!r}   "
              f"(candidate adds {sorted(_tokens(cand) - _tokens(q))})")
    print("  ⭐ every one scores 1.00: specialization is FREE under query-anchoring\n")

    rows = []
    for q in queries:
        pool = None
        for backend, fn in (("legacy", off._search_legacy), ("sal", off._search_sal)):
            try:
                pool = await asyncio.wait_for(fn(q, 8), timeout=45)
            except Exception:
                pool = None
            if pool:
                break
        if not pool:
            rows.append({"query": q, "backend": "-", "pool_size": 0,
                         "bucket": "A_or_B_no_pool", "candidates": []})
            print(f"  {q[:36]:<36} POOL EMPTY")
            continue
        scored = []
        for p in pool:
            nm = (p.get("product_name") or "").strip()
            if not nm:
                continue
            scored.append({"name": nm[:64], "code": str(p.get("code") or "") or None,
                           "ov": round(_overlap(q, nm, p.get("brands") or ""), 3),
                           "priceable": _per100g(p.get("nutriments") or {}) is not None,
                           "resolves_sku": _resolves(q, nm, p.get("brands") or "")})
        scored.sort(key=lambda x: -x["ov"])
        winner = next((c for c in scored if c["priceable"]), None)
        resolving = [c for c in scored if c["resolves_sku"] and c["priceable"]]
        bucket = ("C_selection" if resolving and winner and not winner["resolves_sku"]
                  else "resolved" if winner and winner["resolves_sku"]
                  else "B_recall_no_resolving_candidate")
        rows.append({"query": q, "backend": backend, "pool_size": len(scored),
                     "winner": winner, "n_resolving": len(resolving),
                     "best_resolving_rank": (scored.index(resolving[0]) + 1) if resolving else None,
                     "bucket": bucket, "candidates": scored[:8]})
        print(f"  {q[:36]:<36} {backend:<6} pool={len(scored):<2} "
              f"resolving={len(resolving)} rank={rows[-1]['best_resolving_rank'] or '-':<3} "
              f"{bucket}")
    OUT.write_text(json.dumps({"rows": rows}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
