"""Build the preparation materiality artifact from REAL provider evidence.

    python scripts/build_materiality_artifact.py            # the seed set
    python scripts/build_materiality_artifact.py chicken egg # named identities
    python scripts/build_materiality_artifact.py --dry-run   # report, write nothing

THE RULE, and it has no override:

    provider/retrieval failure  ->  build FAILS, nothing written or replaced
    resolver batch failure      ->  build FAILS for that food, and no
                                    authoritative negative result is written

THE ONLY THING THAT MAY ACQUIRE EVIDENCE FOR THIS CLAIM. The turn path reads
the artifact and nothing else — no provider call, no model call, no web
lookup. That split is the entire point: the answer is a universal fact, and
computing it inside a request cost 9–16 s and still opened nothing.

ONE PROJECTION, NOT TWO. This script calls the same
`food.preparation_evidence` and the same `pa.space_is_material` the turn
path calls.
A generator with its own notion of "material" would drift from the predicate
that opens the field, and the drift would be silent — entries written for
foods the predicate then declines, or foods skipped that it would have opened.

REPORTS EVERY IDENTITY, INCLUDING THE FAILURES. A food that yields no material
space is printed with its reason. "Chicken did not make it" has to be visible
here, at build time, rather than as production silence — which is how the
unreachable-field defect survived a week.
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

#: THE THREE OUTCOMES A BUILD CAN REACH FOR ONE FOOD, and the rule that only
#: two of them may be written.
#:
#:   MATERIAL    evidence establishes a separated space  -> entry written
#:   IMMATERIAL  evidence is COMPLETE and shows no gap   -> no entry, and that
#:                                                          absence is a fact
#:   FAILED      evidence never arrived, or the resolver
#:               could not judge it                      -> BUILD FAILS
#:
#: The distinction that matters is the second versus the third. Both produce
#: an empty space, and at runtime "no entry" is read as "this food has no
#: material preparations" — an authoritative negative. Writing that because a
#: provider 503'd or a model reply would not parse asserts a fact nobody
#: established, and it would stand for ninety days.
MATERIAL, IMMATERIAL, FAILED = "material", "immaterial", "failed"

#: Records per `resolve` call. Measured 2026-08-07: 8 and 12 parse, 16 did not.
_RESOLVE_BATCH = 8

#: The identities prewarmed by default: common foods plus everything the
#: B-1.5 production matrix drives. NOT a curated claim about which foods need
#: preparation — the resolver decides that per food from evidence, and a food
#: listed here that yields no material space simply gets no entry. Extending
#: this list asks a question; it does not answer one.
SEED = ("chicken", "potato", "egg", "beef", "salmon", "rice", "shrimp",
        "tofu", "cauliflower", "mushrooms")


class _CountUsdaFailures(logging.Handler):
    """⭐ THE ONLY HONEST SIGNAL THAT A QUERY FAILED.

    `api.usda._search` swallows every non-200: it logs `USDA search 503: …` at
    WARNING and returns `[]`. Correct for the turn path, which must degrade
    rather than crash — and completely invisible to a caller checking for
    exceptions. The first version of this counter used
    `isinstance(batch, Exception)` and could never have fired, which is the
    same shape as every other instrument that lied by silence today: it was
    written to detect a failure the failure could not produce.

    So the count comes from the warning the client already emits. Coupled to a
    log string, which is fragile — but a fragile signal that CAN fire beats a
    clean one that cannot, and the gate below turns a miscount into a refusal
    to write rather than a silent bad artifact.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.failures = 0

    def emit(self, record):
        if "USDA search" in str(record.getMessage()):
            self.failures += 1


async def _records_for(food_name: str, preparations, shapes, data_types,
                       rows_per_shape: int):
    """Every curated row any shape reaches, pooled and de-duplicated."""
    import api.usda as usda
    from skills.nutrition import evidence_semantics as food

    queries = [shape.format(food=food_name, prep=prep)
               for prep in preparations for shape in shapes]
    counter = _CountUsdaFailures()
    usda.logger.addHandler(counter)
    try:
        batches = await asyncio.gather(
            *(usda._search(q, list(data_types), rows_per_shape)
              for q in queries),
            return_exceptions=True)
    finally:
        usda.logger.removeHandler(counter)

    # ⭐ A FAILED QUERY IS COUNTED, NEVER SWALLOWED. Measured 2026-08-07: USDA
    # returned a 503 partway through a build, and because failures were simply
    # skipped the run still "succeeded" — with fewer rows, so foods silently
    # came out immaterial and were written as though the evidence said so. An
    # artifact built during an outage is not a weaker artifact, it is a WRONG
    # one, and it would then be authoritative for ninety days.
    rows, seen = [], set()
    failed = counter.failures            # HTTP failures, from the log above
    for batch in batches:
        if isinstance(batch, Exception):  # transport errors, which DO raise
            failed += 1
            continue
        for row in batch or ():
            key = str(row.get("fdc_id") or row.get("description"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return food.from_usda(rows), len(queries), failed


async def build_one(food_name: str) -> dict:
    """One identity's entry, or a refusal carrying its reason."""
    from core.semantic_evidence import ABSTAIN, resolve
    from core.semantic_fields import spec_for
    from skills.nutrition import evidence_semantics as food
    from skills.nutrition import preparation_activation as pa
    from skills.nutrition import preparation_artifact as art
    from skills.nutrition.evidence_qualification import _default_complete

    registered = tuple(spec_for("preparation").vocabulary)
    records, query_count, failed_queries = await _records_for(
        food_name, registered, art.QUERY_SHAPES, art.DATA_TYPES,
        art.ROWS_PER_SHAPE)
    if failed_queries:
        # ⭐ THE PARTIAL OUTAGE, which is the dangerous one. A build where
        # EVERY query fails is obvious — no records, nothing to judge. A build
        # where three of nine fail still has records, still resolves, still
        # produces a space, and that space is missing exactly the evidence
        # that did not arrive. It then reads as an authoritative "not
        # material" for ninety days. Any failed query fails the food.
        return {"food": food_name, "status": FAILED,
                "reason": f"{failed_queries}/{query_count} provider queries "
                          f"failed — evidence is incomplete",
                "queries": query_count, "records": len(records),
                "failed_queries": failed_queries}
    if not records:
        # NO ROWS AT ALL is a retrieval outcome, not an evidence outcome:
        # every shape came back empty, which a provider fault produces exactly
        # as a genuinely unknown food does. FAILED, never an authoritative no.
        return {"food": food_name, "status": FAILED,
                "reason": "no curated rows from any shape",
                "queries": query_count, "records": 0,
                "failed_queries": failed_queries}

    # BOUNDED BATCHES, and the bound is measured rather than assumed.
    # `resolve` truncates to MAX_RECORDS=16 and abstains the ENTIRE batch when
    # the reply will not parse — correct fail-closed behaviour, but measured
    # 2026-08-07 the reply for 23 pooled chicken rows came back malformed, so
    # chicken resolved to nothing at all. Eight parses reliably (9.0 s) and
    # twelve did too (15.8 s); sixteen did not. Batching is free here because
    # this is build time, and it is the ONLY place record count is unbounded —
    # the pricing path passes at most eight candidates.
    intent = food.FoodIntent(base_identity=food_name)
    assessments, failures = [], 0
    for start in range(0, len(records), _RESOLVE_BATCH):
        chunk = records[start:start + _RESOLVE_BATCH]
        try:
            batch = await resolve(food.DOMAIN, intent, chunk,
                                  _default_complete)
        except Exception:                                 # pragma: no cover
            failures += 1
            continue
        # An abstained batch is indistinguishable from a refused record here,
        # so count it: a build where every batch abstained must not read as a
        # food that simply has no material space.
        if all(a.relationship == ABSTAIN for a in batch):
            failures += 1
        assessments.extend(batch)
    # ⭐ A RESOLVER FAILURE IS NOT A NEGATIVE RESULT. An abstained batch and a
    # food whose evidence genuinely shows no material spread are the same
    # thing here — both produce an empty space — and they must never be the
    # same thing in the artifact. "No entry" is READ at runtime as "this food
    # has no material preparations", which is an authoritative claim; writing
    # it because the model's reply would not parse is asserting a fact we
    # never established. FAILED, so the build refuses rather than records it.
    if failures:
        return {"food": food_name, "status": FAILED,
                "reason": f"resolver abstained/failed {failures} batch(es)",
                "queries": query_count, "records": len(records),
                "failed_queries": failed_queries}

    # THE TURN PATH'S OWN PROJECTION, imported not reimplemented.
    space, evidence_ids = {}, []
    for evidence in food.preparation_evidence(
            assessments, records,
            minimum_confidence=food.MINIMUM_IDENTITY_CONFIDENCE):
        # REGISTERED STATES ONLY. The resolver may extract "cooked" or
        # "baked"; neither is offerable, so neither may establish materiality
        # — a space the field cannot render is a question we cannot ask.
        if evidence.preparation_id not in registered:
            continue
        if evidence.kcal_per_100g is None and evidence.preparation_id in space:
            continue
        space.setdefault(evidence.preparation_id, evidence.kcal_per_100g)
        evidence_ids.append(evidence.evidence_id)

    material = pa.space_is_material(space)
    return {"food": food_name, "status": MATERIAL if material else IMMATERIAL,
            "material": material, "space": space,
            "evidence_ids": sorted(set(evidence_ids)),
            "queries": query_count, "records": len(records),
            "failed_queries": failed_queries,
            "reason": "" if material else "space is not materially separated"}


def assemble_document(results, *, now=None) -> dict:
    """The artifact document, from build results. Pure, so the assembly has its
    own proof (tests/test_the_materiality_builder_assembles_what_the_reader_verifies.py).

    ⛔ THE ASSEMBLY THIS WRITE NEEDED (found 2026-09-03): `document` was never
    built — a refactor kept the write and dropped the assembly, so every run
    gathered evidence for minutes and died on a NameError at the end.
    Stamped with the LIVE resolver (what this build actually used); the reader
    verifies against its certified pin, so a build under a newer resolver is
    refused until someone certifies and bumps the pin. Only MATERIAL foods get
    an entry — the reader treats "no entry" as "no material preparations".
    """
    from datetime import datetime, timezone
    from skills.nutrition import preparation_artifact as art
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "resolver_version": art.live_resolver_version(),
        "vocabulary_fingerprint": art.vocabulary_fingerprint(),
        "retrieval_fingerprint": art.retrieval_fingerprint(),
        "entries": {r["food"]: {"space": r["space"], "evidence_ids": r["evidence_ids"],
                                "material": r["material"]}
                    for r in results if r["status"] == MATERIAL},
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("identities", nargs="*", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge", action="store_true",
                        help="keep existing entries not rebuilt in this run")
    args = parser.parse_args()

    from dotenv import load_dotenv
    for candidate in (pathlib.Path.home() / "Code Learn/arnie/.env",
                      pathlib.Path(__file__).resolve().parent.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
    if not os.getenv("USDA_API_KEY"):
        print("USDA_API_KEY is not set — every query would return nothing "
              "and the artifact would be silently empty.", file=sys.stderr)
        return 2

    from skills.nutrition import preparation_artifact as art

    identities = [art.normalize(x) for x in (args.identities or SEED)]
    results = [await build_one(name) for name in identities]

    print(f"\n{'identity':<14} {'outcome':<11} {'space / reason'}")
    print("-" * 76)
    for r in results:
        space = ", ".join(f"{k} {v:.0f}" if v else f"{k} —"
                          for k, v in sorted((r.get("space") or {}).items()))
        print(f"{r['food']:<14} {r['status']:<11} "
              f"{space or r.get('reason', '')}")

    # ══ THE GENERATOR RULE, ENFORCED ═══════════════════════════════════════
    #
    #   provider/retrieval failure  -> build FAILS, nothing written/replaced
    #   resolver batch failure      -> build FAILS for that food, and NO
    #                                  authoritative negative is written
    #
    # Both collapse to the same action because of how the artifact is READ. A
    # food with no entry yields `{}`, and `{}` means "this food has no
    # material preparations" — a claim. There is no way to write "we could not
    # tell", so the only honest response to not being able to tell is to write
    # nothing at all and leave whatever was already there standing.
    #
    # That last clause is why this refuses the WHOLE build rather than
    # skipping the food: a normal run replaces the document, so silently
    # omitting a failed food would DELETE its previous good entry — turning a
    # transient 503 into a permanent negative. Refusing to write preserves it.
    failed = [r for r in results if r["status"] == FAILED]
    if failed:
        print(f"\n{len(failed)}/{len(results)} identities FAILED — refusing to "
              f"write. A failure is not a negative result:", file=sys.stderr)
        for r in failed:
            print(f"    {r['food']:<14} {r['reason']}", file=sys.stderr)
        print("\nNothing was written or replaced. Re-run when the provider "
              "and resolver are healthy.", file=sys.stderr)
        return 3

    kept = sum(1 for r in results if r["status"] == MATERIAL)
    print(f"\n{kept}/{len(results)} identities produced a material space; "
          f"{len(results) - kept} are authoritatively immaterial")

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0
    document = assemble_document(results)
    art.ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    art.ARTIFACT_PATH.write_text(json.dumps(document, indent=2,
                                            sort_keys=False) + "\n",
                                 encoding="utf-8")
    print(f"wrote {art.ARTIFACT_PATH} ({len(document['entries'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
