"""P17d.0 — OFF EXACT-PRODUCT PROBE. RECONNAISSANCE, NOT IMPLEMENTATION.

No canonical behaviour change, no producer, no fuzzy search. The ENTIRE raw
response is saved per code before any adapter is trusted, because every
provider contract this migration has written from assumption has been wrong in
at least one load-bearing way (abridged-vs-full, the missing release version,
the bare "large" unit).

Questions this probe answers, per Danny's P17d.0 spec:
  REQUEST IDENTITY   what code did we ask / what code came back / does OFF
                     transform UPC-A <-> EAN-13 leading-zero forms?
  RECORD VERSION     rev? last_modified_t? ETag? anything else?
  NUTRITION          per-100g / per-serving / units / serving text+quantity /
                     package quantity / servings per package?
  PRODUCT IDENTITY   name / brand / variant / quantity / code?
  FAILURE SHAPES     nonexistent · malformed · one-digit mutation of a valid
                     code · incomplete nutrition · serving text with no basis

    ../arnie/.venv/bin/python -m scripts.probe_off_product
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OUT = (pathlib.Path(__file__).resolve().parent.parent
       / "data" / "corpus" / "off_probe_0817")
UA = {"User-Agent": "Arnie/1.0 (nutrition coach; contact: support@tryarnie.com)"}
URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"

#: code -> why it is in the probe. Adversarial controls included on purpose.
CODES = {
    "70004199":       "known-real Barebells (probed once already)",
    "7340001805604":  "Barebells salty peanut, EAN-13 form from search",
    "070004199":      "the known-real code with a LEADING ZERO added",
    "0070004199":     "two leading zeros",
    "70004198":       "ONE-DIGIT MUTATION of the known-real code (bad check digit)",
    "0000000000000":  "nonexistent, well-formed",
    "abc123":         "malformed",
    "049000042566":   "Coca-Cola 12-pack UPC — drink, serving likely ml",
    "0049000042566":  "same Coca-Cola code as EAN-13 zero-padded form",
    "811620021036":   "Fairlife Core Power 26g UPC — drink + package",
    "0811620021036":  "same Fairlife code zero-padded",
}

INTERESTING = (
    "code", "id", "_id", "product_name", "brands", "quantity",
    "product_quantity", "product_quantity_unit", "serving_size",
    "serving_quantity", "serving_quantity_unit", "nutrition_data_per",
    "nutrition_data_prepared_per", "rev", "last_modified_t", "created_t",
    "no_nutrition_data", "states")


async def probe() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    async with httpx.AsyncClient(timeout=30.0, headers=UA) as http:
        for code, why in CODES.items():
            try:
                resp = await http.get(URL.format(code=code))
                body = resp.json() if resp.content else {}
            except Exception as exc:                       # noqa: BLE001
                summary[code] = {"why": why, "error": str(exc)[:120]}
                continue
            # THE ENTIRE RAW RESPONSE, before any adapter shapes it.
            (OUT / f"{code or 'empty'}.json").write_text(
                json.dumps(body, indent=1, ensure_ascii=False))
            product = body.get("product") or {}
            nutriments = product.get("nutriments") or {}
            summary[code] = {
                "why": why,
                "http": resp.status_code,
                "etag": resp.headers.get("etag"),
                "status": body.get("status"),
                "returned_code": product.get("code"),
                "fields": {k: product.get(k) for k in INTERESTING
                           if product.get(k) is not None},
                "per100g_keys": sorted(k for k in nutriments
                                       if k.endswith("_100g"))[:10],
                "per_serving_keys": sorted(k for k in nutriments
                                           if k.endswith("_serving"))[:10],
                "unit_keys": sorted(k for k in nutriments
                                    if k.endswith("_unit"))[:8],
            }
            print(f"  {code:15} http={resp.status_code} "
                  f"status={body.get('status')!r} "
                  f"returned={product.get('code')!r}  ({why})")
    (OUT / "SUMMARY.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False))
    print(f"\n  raw responses -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(probe()))
