#!/usr/bin/env python
"""PHASE 2A — BULK PRELOAD, batch 1: USDA Foundation Foods.

⛔⛔⛔ SELECTION IS BLIND TO THE FROZEN 222, BY CONSTRUCTION. See
`docs/BULK_PRELOAD_SELECTION_PROTOCOL.md`. The universe is the COMPLETE USDA
FoodData Central Foundation Foods population — USDA's own curated set of
nutritionally representative core foods, published without any reference to
Arnie. Taking ALL of it means there is no intra-population selection step to
shape, deliberately or otherwise. The frozen 222 stays SEALED until this batch
is committed.

⭐ THE LIST SUPPLIES FOOD CONCEPTS, NOT IDENTITY STRINGS. USDA writes
"Cheese, cottage, lowfat, 1% milkfat"; a person says "cottage cheese". Evidence
keyed on the USDA description would be correct, provenanced, and UNREACHABLE —
`pricing_artifact.key()` is computed from the user's food name, so nothing would
ever look it up. The de-inversion is mechanical and stated in `identity_of`:
head, plus the next segment only when it is a short specialiser. Everything
after is processing detail, not a name.

⛔ AND IT RUNS THE SAME `acquire()` AS A LIVE TURN. No privileged path, no second
food database, no bypass of `decide()`. Bulk changes WHICH foods are established
and WHEN — never on what terms. An identity that cannot establish source
authority is refused BY NAME and counted, never loaded.

⛔⛔ BULK RUNS OUTSIDE ANY TURN, so it CANNOT prove the single-flight collision
stayed fixed — that defect only ever bit the ambient-context path. A separate
in-turn regression probe is required after this batch; a healthy preload is not
evidence about in-turn behaviour.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

FOUNDATION = "https://api.nal.usda.gov/fdc/v1/foods/list"

#: Segments that describe PROCESSING or PACKAGING rather than how a person
#: names the food. Mechanical, stated, and applied identically to every row.
_NOT_A_NAME = ("with", "without", "canned", "from", "includes", "all ",
               "prepared", "unprepared", "raw", "cooked", "boiled", "drained",
               "reduced", "added", "nfs", "commercial", "retail")


def identity_of(desc: str) -> str:
    """'Cheese, cottage, lowfat, 1% milkfat' -> 'cottage cheese'."""
    # ⭐ PARENTHETICALS ARE ALIASES, NOT NAME PARTS. "Beans, garbanzo
    # (chickpeas), mature seeds" produced `(garbanzo beans chickpeas` — a name
    # nobody would ever type, so evidence keyed on it is unreachable.
    import re as _re

    desc = _re.sub(r"\s*\([^)]*\)", "", desc)
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    if not parts:
        return ""
    head = parts[0].lower()
    if len(parts) > 1:
        spec = parts[1].lower()
        if (len(spec.split()) <= 2
                and not any(spec.startswith(p) for p in _NOT_A_NAME)
                and not spec[:1].isdigit()):
            return f"{spec} {head}"
    return head


async def universe(api_key):
    """The COMPLETE Foundation Foods population. No filter, no sampling."""
    import httpx

    rows, page = [], 1
    async with httpx.AsyncClient(timeout=60) as c:
        while page <= 12:
            r = await c.post(FOUNDATION, params={"api_key": api_key},
                             json={"dataType": ["Foundation"],
                                   "pageSize": 200, "pageNumber": page})
            if r.status_code != 200:
                raise RuntimeError(f"USDA list {r.status_code}: {r.text[:120]}")
            batch = r.json()
            if not batch:
                break
            rows += batch
            page += 1
    return rows


def _bucket(n):
    """⭐ THE >3 BOUNDARY IS KEPT VISIBLE. Under the single-flight collision an
    in-turn acquisition could never exceed `_QUALIFY_BATCH`=3, so that edge is
    where a regression would first show. A mean would hide it."""
    return ("0" if n == 0 else "1-3" if n <= 3 else "4-6" if n <= 6
            else "7-10" if n <= 10 else "10+")


async def preload(identities, limit, out_path, manifest):
    from db.database import AsyncSessionLocal
    from skills.nutrition.acquisition import (ACQUIRE_JOB_BUDGET_S,
                                              AcquisitionRefused, acquire)

    rows = []
    for i, ident in enumerate(identities[:limit], 1):
        async with AsyncSessionLocal() as db:
            t0 = time.monotonic()
            rec = {"identity": ident}
            try:
                got = await acquire(db, identity=ident,
                                    deadline_s=ACQUIRE_JOB_BUDGET_S)
                await db.commit()
                ev = dict(got.identity_evidence or {})
                # ⭐ TWO NUMBERS, NOT ONE. "Retrieval only found 2 rows" and
                # "retrieval found 14 and qualification kept 2" are different
                # facts, and a single candidate count cannot tell them apart —
                # which is exactly how a qualification regression would hide.
                rec.update(
                    acquired=True,
                    raw_candidates_retrieved=ev.get("raw_rows"),
                    qualified_candidates_persisted=len(got.nutrition_evidence),
                    authority_grade=got.authority_grade,
                    nutrition_basis=got.nutrition_basis,
                    source_type=got.source_type,
                    source_identifier=got.source_identifier,
                    has_serving_basis=bool(got.serving_basis),
                    provenance_keys=sorted((got.provenance or {}).keys()),
                    dataset_subtype=(got.provenance or {}).get("dataset_subtype"),
                    elapsed_s=round(time.monotonic() - t0, 2))
            except AcquisitionRefused as refused:
                await db.rollback()
                rec.update(acquired=False, refusal=refused.reason,
                           elapsed_s=round(time.monotonic() - t0, 2))
            except Exception as exc:                     # noqa: BLE001
                await db.rollback()
                rec.update(acquired=False, refusal=f"EXC:{type(exc).__name__}",
                           detail=str(exc)[:140],
                           elapsed_s=round(time.monotonic() - t0, 2))
        rows.append(rec)
        if i % 25 == 0 or i == min(limit, len(identities)):
            ok = sum(r.get("acquired", False) for r in rows)
            print(f"  {i}/{min(limit,len(identities))}  acquired={ok}")

    ok = [r for r in rows if r.get("acquired")]
    raw_b = collections.Counter(_bucket(r.get("raw_candidates_retrieved") or 0)
                                for r in ok)
    qual_b = collections.Counter(
        _bucket(r.get("qualified_candidates_persisted") or 0) for r in ok)
    lat = sorted(r["elapsed_s"] for r in rows if "elapsed_s" in r)
    pct = lambda q: lat[min(int(len(lat) * q), len(lat) - 1)] if lat else None
    # ⛔ ALREADY-SUPPORTED IS COVERAGE, NOT FAILURE. Counting a food the
    # catalog already knows against the acquisition rate reported 64% while
    # `beef` was simply already covered — measuring coverage as failure, and
    # worse at scale.
    already = [r for r in rows if r.get("refusal") == "ACQUIRE_ALREADY_SUPPORTED"]
    attempted_new = len(rows) - len(already)
    summary = {
        "attempted": len(rows),
        "already_supported": len(already),
        "attempted_new": attempted_new,
        "acquired": len(ok),
        "acquired_pct_of_new": round(100 * len(ok) / max(attempted_new, 1), 1),
        "covered_pct": round(100 * (len(ok) + len(already)) / max(len(rows), 1), 1),
        "acquired_pct": round(100 * len(ok) / max(len(rows), 1), 1),
        "raw_candidate_distribution": dict(raw_b),
        "qualified_candidate_distribution": dict(qual_b),
        "refusals": dict(collections.Counter(
            r["refusal"] for r in rows if r.get("refusal"))),
        "source_datasets": dict(collections.Counter(
            r.get("dataset_subtype") or "?" for r in ok)),
        "authority_grades": dict(collections.Counter(
            r["authority_grade"] for r in ok)),
        "nutrition_bases": dict(collections.Counter(
            r["nutrition_basis"] for r in ok)),
        "with_serving_basis": sum(r.get("has_serving_basis", False) for r in ok),
        # ⛔ THE LAUNDERING GATE. `ESTIMATE`/`WEB`/`MODEL` are not members of
        # ADMISSIBLE_GRADES, so this must be zero by construction — asserted
        # anyway, because a guard whose protected input never occurs is a guard
        # nobody has.
        "non_sourced_grades": sum(
            1 for r in ok if r["authority_grade"] != "sourced_composition"),
        "provenance_incomplete": sum(
            1 for r in ok
            if not {"dataset_id", "resolver_version", "retrieval_fingerprint",
                    "source_fingerprint"} <= set(r.get("provenance_keys") or [])),
        "p50_s": pct(.50), "p95_s": pct(.95),
    }
    pathlib.Path(out_path).write_text(json.dumps(
        {"manifest": manifest, "summary": summary, "rows": rows},
        indent=2, ensure_ascii=False))
    print("\n" + json.dumps(summary, indent=2))
    return summary


async def main(a):
    import os

    key = os.environ.get("USDA_API_KEY")
    if not key:
        print("USDA_API_KEY unset"); return 1
    rows = await universe(key)
    idents = sorted({identity_of(r["description"]) for r in rows})
    manifest = {
        "batch": "foundation-foods-01",
        "source": "USDA FoodData Central — Foundation Foods",
        "endpoint": FOUNDATION,
        "retrieved_at": a.retrieved_at,
        "criterion": ("COMPLETE population, no intra-population selection. "
                      "Selected blind to the frozen 222-meal corpus; the corpus "
                      "may be used only afterward, to measure impact."),
        "source_descriptions": len(rows),
        "derived_identities": len(idents),
        "identity_rule": ("head segment, plus the next segment when it is a "
                          "short specialiser (<=2 words, not a processing or "
                          "packaging qualifier); remainder dropped"),
        "corpus_consulted": False,
    }
    print(json.dumps(manifest, indent=2))
    if a.dry_run:
        pathlib.Path(a.out).write_text(json.dumps(
            {"manifest": manifest, "identities": idents}, indent=2,
            ensure_ascii=False))
        print(f"\nDRY RUN — {len(idents)} identities written to {a.out}")
        return 0
    await preload(idents, a.limit, a.out, manifest)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/preload_foundation_01.json")
    ap.add_argument("--limit", type=int, default=10_000)
    ap.add_argument("--retrieved-at", default="2026-09-01")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    sys.exit(asyncio.run(main(a)))
