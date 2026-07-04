"""Remove duplicated Cable Crunch first-sets from Danny's live-workout logs.

Bug class: set-by-set logging → the session-state layer re-flushes the full
accumulating exercise as a NEW multi-set row while leaving the earlier single-set
row in place, so set 1 is counted twice (the same class repaired in
cleanup_danny_dup_shrugs.py — still recurring, so the forward fix was incomplete).

Two instances found live on 2026-07-03:
  • log 226 (2026-07-03): id 595 (sets=1, reps='15')  ⊂ id 596 (sets=2, reps='15,14')
  • log 193 (2026-06-27): id 535 (sets=1, reps='15')  ⊂ id 536 (sets=2, reps='15,15')

For each pair we delete the SUBSET row (the orphaned single-set) and keep the
SUPERSET row (which already contains that set plus the later ones). Same weight,
same daily_log, first-set reps match — verified before delete.

DRY-RUN by default; backs up every deleted row to JSON. Pass --apply to commit.
Aborts the whole run if any pair no longer matches its expected signature
(prod is live — state may have changed since detection).
"""
import asyncio
import json
import sys
from dotenv import load_dotenv
load_dotenv(".env", override=True)
from sqlalchemy import text
from db.database import AsyncSessionLocal

APPLY = "--apply" in sys.argv
BACKUP = "danny_dup_cable_crunch_backup.json"

# (drop_id, keep_id) — drop the single-set subset, keep the multi-set superset.
# NOTE: 06-27 pair (535,536) was investigated and is NOT a duplicate — 535 is a
# set at 150lb, 536 is two sets at 160lb (legit progression, different load). The
# weight guard rejects it; left out here on purpose.
PAIRS = [(595, 596)]


async def main():
    async with AsyncSessionLocal() as db:
        to_delete = []
        for drop_id, keep_id in PAIRS:
            rows = (await db.execute(text(
                "SELECT id, daily_log_id, exercise_name, sets, reps, weight, weights, timestamp "
                "FROM exercise_entries WHERE id IN (:a, :b) ORDER BY id"
            ), {"a": drop_id, "b": keep_id})).mappings().all()
            by_id = {r["id"]: r for r in rows}
            drop, keep = by_id.get(drop_id), by_id.get(keep_id)

            print(f"\n=== pair drop={drop_id} keep={keep_id} ===")
            if not drop or not keep:
                print(f"ABORT: one/both rows missing (drop={bool(drop)}, keep={bool(keep)}) — "
                      "state changed, not safe.")
                return
            for tag, r in (("KEEP", keep), ("DROP", drop)):
                print(f"  {tag} id={r['id']} log{r['daily_log_id']} {r['exercise_name']} "
                      f"sets={r['sets']} reps={r['reps']!r} w={r['weight']} ts={r['timestamp']}")

            # Guards: same log, same exercise, subset relationship, single-set victim.
            keep_reps = (keep["reps"] or "").replace(" ", "")
            drop_reps = (drop["reps"] or "").replace(" ", "")
            ok = (
                drop["daily_log_id"] == keep["daily_log_id"]
                and (drop["exercise_name"] or "").lower() == (keep["exercise_name"] or "").lower()
                and drop["sets"] == 1
                and (keep["sets"] or 0) > 1
                and keep_reps.split(",")[0] == drop_reps          # first set matches
                and drop["weight"] == keep["weight"]              # same load
            )
            if not ok:
                print("  ABORT: pair is not a clean single-set-subset duplicate — not safe.")
                return
            to_delete.append(dict(drop))

        with open(BACKUP, "w") as f:
            json.dump([{k: (str(v) if k == "timestamp" else v) for k, v in r.items()}
                       for r in to_delete], f, indent=2)
        print(f"\nbackup written: {BACKUP} ({len(to_delete)} rows)")

        if not APPLY:
            print("\nDRY-RUN — re-run with --apply to delete ids "
                  f"{[r['id'] for r in to_delete]}.")
            return

        for r in to_delete:
            await db.execute(text("DELETE FROM exercise_entries WHERE id = :i"), {"i": r["id"]})
        await db.commit()
        print(f"APPLIED — deleted {len(to_delete)} duplicate cable-crunch rows: "
              f"{[r['id'] for r in to_delete]}.")


if __name__ == "__main__":
    asyncio.run(main())
