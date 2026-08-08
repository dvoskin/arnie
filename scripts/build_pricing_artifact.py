"""Build the qualified PRICING evidence artifact from real provider records.

    python scripts/build_pricing_artifact.py             # the seed identities
    python scripts/build_pricing_artifact.py chicken     # named entities
    python scripts/build_pricing_artifact.py --dry-run

THE ONLY THING THAT MAY ACQUIRE PRICING EVIDENCE. The runtime reader loads and
nothing else — no provider, no model, no generation on miss — which is what
lets `canonical_pricing.price()` be synchronous and still honest.

STORES THE QUALIFIED CANDIDATE SET, NOT A WINNER. `best_candidate` ranks at
runtime, deterministically. Committing a chosen record would move ranking
authority into whichever record the model preferred on generation day, and the
defect being fixed is precisely that a fresh qualification changed the winner:
"Chicken, fried" 120 g priced 295 kcal, then 329 kcal.

THE SAME FAILURE RULE AS THE MATERIALITY GENERATOR, for the same reason:

    provider/retrieval failure  ->  build FAILS, nothing written or replaced
    resolver batch failure      ->  build FAILS for that identity, and no
                                    authoritative negative result is written

An identity absent from the artifact is READ as "no qualified pricing evidence
exists", which sends pricing to the estimate rung. Writing that because USDA
503'd would be asserting a fact nobody established.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(message)s")
for _noisy in ("httpx", "httpcore", "anthropic", "openai", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

#: Rows per qualification call. The bound is on the model's OUTPUT,
#: which USDA's verbose descriptions inflate — see build_one.
_QUALIFY_BATCH = 3

#: Attempts per batch. Truncation is per-reply, so a retry usually
#: parses; a batch that fails all attempts fails the identity.
_QUALIFY_ATTEMPTS = 3

MATERIAL, EMPTY, FAILED = "ok", "no_evidence", "failed"

#: Identities to prewarm: each seed entity crossed with "" (no preparation)
#: and every registered preparation. NOT a claim about which foods matter —
#: the qualifier decides what survives, and an entity that yields nothing
#: simply gets no entry.
SEED = ("chicken", "potato", "egg", "beef", "salmon", "rice", "shrimp",
        "tofu", "cauliflower", "mushrooms", "mackerel", "tilapia",
        "asparagus", "broccoli", "oats", "banana")


class _CountUsdaFailures(logging.Handler):
    """`api.usda._search` swallows every non-200 and returns []. The only
    honest signal a query failed is the warning it already emits."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.failures = 0

    def emit(self, record):
        if "USDA search" in str(record.getMessage()):
            self.failures += 1


async def build_one(entity: str, preparation: str) -> dict:
    """The qualified candidate set for one (entity, preparation)."""
    import api.usda as usda
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition.evidence_qualification import qualify_usda_rows
    from skills.nutrition import preparation_ontology as prep_onto

    identity = prep_onto.name_with(entity, preparation) if preparation \
        else entity
    queries = [s.format(identity=identity) for s in art.QUERY_SHAPES]

    counter = _CountUsdaFailures()
    usda.logger.addHandler(counter)
    try:
        batches = await asyncio.gather(
            *(usda._search(q, list(art.DATA_TYPES), art.ROWS_PER_SHAPE)
              for q in queries), return_exceptions=True)
    finally:
        usda.logger.removeHandler(counter)

    failed = counter.failures
    rows, seen = [], set()
    for batch in batches:
        if isinstance(batch, Exception):
            failed += 1
            continue
        for row in batch or ():
            fid = str(row.get("fdc_id") or row.get("description"))
            if fid in seen:
                continue
            seen.add(fid)
            rows.append(row)

    if failed:
        return {"identity": identity, "status": FAILED,
                "reason": f"{failed}/{len(queries)} provider queries failed"}
    if not rows:
        return {"identity": identity, "status": EMPTY,
                "reason": "no curated rows"}

    # QUALIFICATION IS THE EXPENSIVE STEP, and moving it here is the entire
    # point: measured 6,538-13,546 ms per call on the settle path.
    #
    # ⭐ BATCHED, because the failure mode is OUTPUT LENGTH, not record count.
    # Measured 2026-08-08: eight mackerel rows produced a reply truncated
    # mid-string — `JSONDecodeError: Unterminated string` — after 30,958 ms,
    # and `resolve` correctly abstained the WHOLE batch. That is the root
    # cause of entry 2932: qualification kept nothing, USDA contributed
    # nothing, and the legacy ladder priced 80 g of mackerel at 0.0 kcal.
    # Long USDA descriptions ("Fish, mackerel, Atlantic, raw") make the reply
    # longer per record, so a fixed record cap cannot bound it — smaller
    # batches can, and offline they are free.
    kept, seen_ids = [], set()
    for start in range(0, len(rows), _QUALIFY_BATCH):
        chunk = rows[start:start + _QUALIFY_BATCH]
        # BOUNDED RETRY, because truncation is a property of THIS reply, not
        # of the food: the same chunk usually parses on a second attempt. The
        # rule is unchanged — a batch that still fails after retries fails the
        # identity rather than being written as "no evidence". Without this,
        # 64 identities × one transient failure makes the artifact
        # unbuildable, which would be the rule defeating its own purpose.
        q = None
        for attempt in range(_QUALIFY_ATTEMPTS):
            try:
                q = await qualify_usda_rows(identity, chunk)
            except Exception as exc:                        # pragma: no cover
                return {"identity": identity, "status": FAILED,
                        "reason": f"qualification raised: {exc}"}
            if not (getattr(q, "disposition", "") ==
                    "resolver_down_no_candidates" and not q.rows):
                break
        if getattr(q, "disposition", "") == "resolver_down_no_candidates" \
                and not q.rows:
            # SEMANTIC_RESOLVER_DOWN != RAW_EVIDENCE_AUTHORIZED, and it also
            # does not mean "this identity has no evidence". FAILED, not
            # EMPTY — a truncated reply must never be written as a negative.
            return {"identity": identity, "status": FAILED,
                    "reason": "semantic resolver unavailable after "
                              f"{_QUALIFY_ATTEMPTS} attempts "
                              f"(batch {start // _QUALIFY_BATCH + 1})"}
        for r in (q.rows or ()):
            fid = str(r.get("fdc_id"))
            if fid not in seen_ids:
                seen_ids.add(fid)
                kept.append(r)

    kept = [{"fdc_id": r.get("fdc_id"), "description": r.get("description"),
             "per100g": r.get("per100g") or {}}
            for r in kept if (r.get("per100g") or {}).get("calories")]
    if not kept:
        return {"identity": identity, "status": EMPTY,
                "reason": f"0 of {len(rows)} rows qualified"}
    return {"identity": identity, "status": MATERIAL, "candidates": kept,
            "raw": len(rows)}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("entities", nargs="*", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    for candidate in (pathlib.Path.home() / "Code Learn/arnie/.env",
                      pathlib.Path(__file__).resolve().parent.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
    if not os.getenv("USDA_API_KEY"):
        print("USDA_API_KEY is not set — every query would return nothing and "
              "the artifact would be silently empty.", file=sys.stderr)
        return 2

    from core.semantic_fields import spec_for, _ensure_installed
    from skills.nutrition import pricing_artifact as art

    _ensure_installed()
    preparations = ("",) + tuple(spec_for("preparation").vocabulary)
    entities = [art.normalize(e) for e in (args.entities or SEED)]

    results, entries = [], {}
    for entity in entities:
        for preparation in preparations:
            r = await build_one(entity, preparation)
            r["key"] = art.key(entity, preparation)
            results.append(r)
            if r["status"] == MATERIAL:
                entries[r["key"]] = {"candidates": r["candidates"]}

    print(f"\n{'key':34} {'status':12} candidates")
    print("-" * 70)
    for r in results:
        n = len(r.get("candidates") or ())
        print(f"{r['key']:34} {r['status']:12} "
              f"{n if n else r.get('reason','')}")

    failed = [r for r in results if r["status"] == FAILED]
    if failed:
        print(f"\n{len(failed)}/{len(results)} identities FAILED — refusing to "
              f"write. A failure is not an authoritative negative:",
              file=sys.stderr)
        for r in failed:
            print(f"    {r['key']:34} {r['reason']}", file=sys.stderr)
        return 3

    document = {
        "resolver_version": art.resolver_version(),
        "vocabulary_fingerprint": art.vocabulary_fingerprint(),
        "retrieval_fingerprint": art.retrieval_fingerprint(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0)
                                .isoformat().replace("+00:00", "Z"),
        "entries": dict(sorted(entries.items())),
    }
    print(f"\n{len(entries)}/{len(results)} identities carry qualified evidence")
    if args.dry_run:
        print("--dry-run: nothing written")
        return 0
    art.ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    art.ARTIFACT_PATH.write_text(json.dumps(document, indent=2) + "\n",
                                 encoding="utf-8")
    print(f"wrote {art.ARTIFACT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
