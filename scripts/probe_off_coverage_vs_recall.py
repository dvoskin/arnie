"""B vs A — for the nine queries whose pool held NO resolving candidate,
does OFF CONTAIN the product at all?

    A  SOURCE COVERAGE   OFF does not have it -> retrieval work cannot help
    B  RETRIEVAL RECALL  OFF has it, the query did not surface it -> fixable

⭐ THE DISCRIMINATOR IS A SECOND QUERY, NOT A SECOND OPINION. The pool probe
asked OFF the USER'S phrase. This asks OFF for the PRODUCT — brand-anchored,
variant-explicit, and also each individual attribute — and looks in the RAW
pool rather than at whatever `_best_candidate` would seat. If a resolving
record appears under any phrasing, the record exists and the first query simply
failed to reach it.

⛔ A NEGATIVE HERE IS STILL WEAK. "Not found under four phrasings" is not "absent
from OFF" — it is bounded by the phrasings tried and by the fallback backend
that happened to answer. Reported as NOT_FOUND_UNDER_PROBE, never as absent.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = pathlib.Path("data/off_coverage_vs_recall_2026-08-31.json")

#: The nine from `data/off_candidate_pool_2026-08-31.json`, each with
#: alternative phrasings a human would try. Written out rather than generated,
#: so what was asked is on the record.
# ⚠ REDUCED FROM NINE TO FIVE after the `_resolves` brand-field bug was fixed:
# Chobani, Fairlife, Premier Protein and BOTH Muscle Milk entries turned out to
# have a resolving candidate at rank 1 all along. The four dropped queries were
# never coverage questions; they were instrument artefacts.
NINE = {
 "Ben & Jerry's Half Baked pint":      ["Ben & Jerry's Half Baked", "Half Baked ice cream", "Ben and Jerrys Half Baked"],
 "Coke Zero":                          ["Coca-Cola Zero Sugar", "Coca Cola Zero", "Coke Zero Sugar"],
 "Gatorade Zero Glacier Cherry":       ["Gatorade Zero Glacier Cherry", "Gatorade Zero Sugar Glacier Cherry", "Gatorade G Zero Glacier Cherry"],
 "Kind Bar Dark Chocolate Nuts & Sea Salt": ["KIND Dark Chocolate Nuts & Sea Salt", "KIND Nuts & Spices Dark Chocolate Nuts Sea Salt", "Kind dark chocolate sea salt"],
 "Muscle Milk Pro Series 40g Vanilla": ["Muscle Milk Pro Series Vanilla", "Muscle Milk Pro Series 40g", "Pro Series Vanilla Protein Powder"],
}


async def main() -> int:
    from skills.nutrition import off
    from skills.nutrition.off import _overlap, _per100g, _tokens

    def resolves(original: str, cand: str, brands: str = "") -> bool:
        """⛔⛔ THIS CHECKED THE PRODUCT NAME ONLY, AND THE BRAND LIVES IN A
    DIFFERENT FIELD. `_overlap` unions name AND brands; this did not, so
    'Pro Series Vanilla Protien Powder' (brands='Muscle Milk') scored as NOT
    resolving 'Muscle Milk Pro Series Vanilla' -- a record this session had
    already retrieved by barcode 0660016534113. The probe reported
    NOT_FOUND for a product it had held in its hand an hour earlier.
    Caught only by contradicting an EARLIER result; nothing in the run said so.
        """
        return not (_tokens(original) - (_tokens(cand) | _tokens(brands)))

    rows = []
    for original, alts in NINE.items():
        found = []
        for phrase in alts:
            pool = None
            for fn in (off._search_legacy, off._search_sal):
                try:
                    pool = await asyncio.wait_for(fn(phrase, 12), timeout=45)
                except Exception:
                    pool = None
                if pool:
                    break
            for p in (pool or []):
                nm = (p.get("product_name") or "").strip()
                if not nm:
                    continue
                if resolves(original, nm, p.get('brands') or '') and _per100g(p.get("nutriments") or {}) is not None:
                    found.append({"phrase": phrase, "name": nm[:64],
                                  "code": str(p.get("code") or "") or None,
                                  "ov_vs_original": round(_overlap(original, nm, p.get("brands") or ""), 3)})
        verdict = "B_RECALL_record_exists" if found else "NOT_FOUND_UNDER_PROBE"
        rows.append({"query": original, "phrases_tried": alts,
                     "verdict": verdict, "found": found[:3]})
        print(f"  {original[:40]:<40} {verdict}")
        for f in found[:2]:
            print(f"       via {f['phrase'][:38]!r} -> {f['name'][:42]!r} "
                  f"code={f['code']} ov_vs_original={f['ov_vs_original']}")
    OUT.write_text(json.dumps({"rows": rows}, indent=1) + "\n")
    b = sum(1 for r in rows if r["verdict"].startswith("B_"))
    print(f"\n  B (record exists, query missed it): {b}/9")
    print(f"  NOT FOUND under these phrasings   : {9-b}/9  ⛔ bounded by the "
          f"phrasings tried — NOT proof of absence")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
