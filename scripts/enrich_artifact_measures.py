"""P17c — ADD USDA'S OWN MEASURES TO THE COMMITTED ARTIFACT. ADDITIVE ONLY.

    "2 eggs"  +  USDA: 1 large egg = 50 g  ->  100 g  ->  the per-100 g rung
                                                          scales as it always has

⛔⛔ WHY THIS IS AN ENRICHMENT AND NOT A REBUILD. `build_pricing_artifact` re-runs
retrieval and re-ranks, so it can legitimately return a DIFFERENT candidate set —
and that would change committed prices while claiming to add a serving measure.
The determinism gate exists precisely because "Chicken, fried" once priced 295
and then 329 kcal from a re-qualified candidate set. So this script:

    * never adds, removes or reorders a candidate
    * never touches `per100g`, `description`, `data_type` or `evidence_id`
    * only ever writes the `measures` key, keyed by the fdc_id already committed

It is therefore safe to run against a live artifact, and its diff is reviewable
by inspection rather than by trusting a rebuild.

⭐ AND IT RUNS AT BUILD TIME, NOT SETTLE TIME. `assemble()` stays
LOAD-NEVER-BUILD: a measure is only visible to pricing once it is committed
evidence in this file. Gate B is untouched.

    USDA_API_KEY=... ../arnie/.venv/bin/python -m scripts.enrich_artifact_measures
    ../arnie/.venv/bin/python -m scripts.enrich_artifact_measures --write
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "data" / "pricing_evidence_v1.json"

#: Keys this script is permitted to write. Anything else changing is a bug, and
#: the check below is what makes "additive only" a fact rather than an intent.
WRITABLE = {"measures"}


def _immutable(candidate: dict) -> dict:
    return {k: v for k, v in candidate.items() if k not in WRITABLE}


def fingerprint(measure: dict, fdc_id) -> str:
    """A hash of the EXACT normalized facts committed for this measure.

    ⛔ `fdc_id + "usda_fdc"` DOES NOT DESCRIBE WHAT ARNIE SAW. The FDC API serves
    the current database and its data types move at different cadences —
    Foundation periodically, Branded monthly, SR Legacy final — so an id plus a
    dataset name names a MOVING TARGET. The fingerprint pins the facts
    themselves, which is what a later correction must reproduce.
    """
    payload = json.dumps({"fdc_id": str(fdc_id),
                          "unit_text": measure.get("unit_text"),
                          "amount": measure.get("amount"),
                          "grams": measure.get("grams"),
                          "portion_id": measure.get("portion_id")},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def enrich(*, write: bool, release: str) -> int:
    from api import usda
    from dotenv import load_dotenv

    for env in (pathlib.Path.home() / "Code Learn/arnie/.env", ROOT / ".env"):
        if env.exists():
            load_dotenv(env)

    if not ARTIFACT.exists():
        raise SystemExit(f"no committed artifact at {ARTIFACT}")
    doc = json.loads(ARTIFACT.read_text())
    entries = doc.get("entries") or {}

    before = {key: [_immutable(c) for c in (e.get("candidates") or ())]
              for key, e in entries.items()}

    total = enriched = portions = 0
    for key, entry in sorted(entries.items()):
        for candidate in entry.get("candidates") or ():
            total += 1
            fdc_id = candidate.get("fdc_id")
            if not fdc_id:
                continue
            measures = await usda.food_portions(fdc_id)
            if not measures:
                continue
            for measure in measures:
                # ⛔⛔ THE RELEASE IS STAMPED FROM THE CALLER, NEVER DERIVED.
                # The record itself carries no release version — probed, not
                # assumed — and deriving one from today's date would put a
                # fabricated identity into a durable audit record.
                measure["dataset_version"] = release
                measure["fingerprint"] = fingerprint(measure, fdc_id)
            candidate["measures"] = measures
            enriched += 1
            portions += len(measures)
            print(f"  {key:32.32} {str(fdc_id):10} "
                  f"{len(measures)} measure(s): "
                  f"{', '.join(m['unit_text'] for m in measures[:3])}")

    # ⛔ THE ADDITIVE CLAIM IS CHECKED, NOT ASSERTED. If any non-`measures` field
    # moved, the artifact is not what it was and this script has exceeded its
    # mandate — refuse rather than write.
    after = {key: [_immutable(c) for c in (e.get("candidates") or ())]
             for key, e in entries.items()}
    if after != before:
        raise SystemExit(
            "⛔ REFUSING TO WRITE — a field outside `measures` changed, so this "
            "run is a rebuild wearing an enrichment's name")

    print(f"\n  {enriched} of {total} committed candidates gained a measure "
          f"({portions} portions total)")
    if write:
        ARTIFACT.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        print(f"  written -> {ARTIFACT}")
    else:
        print("  DRY RUN — pass --write to commit these to the artifact")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    # ⛔ REQUIRED, WITH NO DEFAULT. "committed_artifact" was very nearly baked
    # into 259 durable conversion records as the version a correction cites.
    parser.add_argument(
        "--fdc-release", required=True, metavar="VERSION",
        help="the FoodData Central release these records were read from, e.g. "
             "15.3. Look it up; it is NOT in the record and must not be "
             "guessed or derived from the date.")
    args = parser.parse_args()
    if not str(args.fdc_release).strip():
        raise SystemExit("--fdc-release may not be empty")
    return asyncio.run(enrich(write=args.write,
                              release=str(args.fdc_release).strip()))


if __name__ == "__main__":
    raise SystemExit(main())
