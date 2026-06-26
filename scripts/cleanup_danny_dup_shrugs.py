"""Remove ONE duplicate Cable Shrugs block from Danny's 2026-06-25 session (log 179).

Evidence: exercise_entries 512 and 514 are byte-identical (Cable Shrugs, sets=3,
reps='14,14,15', weight≈86.18kg) created 10 min apart (22:28:31 and 22:38:30).
The shrugs were logged set-by-set, then the resend of "Got 15, doing upright rows
now" (turns #4875/#4876, 8s apart) double-wrote the full block — turn #4876 even
says "already logged" while skills_fired=log_exercise. Net: shrugs volume counted
twice (6 sets, not 3). The chat_service idempotency tightening prevents the class
going forward; this repairs the one row already written.

Deletes the LATER row (514), keeping the original accumulating row (512).
DRY-RUN by default; backs up the deleted row. Pass --apply to commit.
Guards: aborts unless exactly two matching rows exist with the expected signature.
"""
import asyncio
import json
import sys
from dotenv import load_dotenv
load_dotenv(".env", override=True)
from sqlalchemy import text
from db.database import AsyncSessionLocal

APPLY = "--apply" in sys.argv
KEEP_ID, DROP_ID = 512, 514
BACKUP = "danny_dup_shrugs_backup.json"


async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, daily_log_id, exercise_name, sets, reps, weight, timestamp "
            "FROM exercise_entries WHERE id IN (:a, :b) ORDER BY id"
        ), {"a": KEEP_ID, "b": DROP_ID})).mappings().all()

        print("matched rows:")
        for r in rows:
            print(f"  id={r['id']} log{r['daily_log_id']} {r['exercise_name']} "
                  f"sets={r['sets']} reps={r['reps']} w={r['weight']} ts={r['timestamp']}")

        # Safety: both must exist, same log, same name, same sets/reps — a true dup.
        if len(rows) != 2:
            print(f"ABORT: expected 2 rows, found {len(rows)} — data changed, not safe.")
            return
        a, b = rows
        if not (a["daily_log_id"] == b["daily_log_id"]
                and (a["exercise_name"] or "").lower() == (b["exercise_name"] or "").lower()
                and a["sets"] == b["sets"] and (a["reps"] or "") == (b["reps"] or "")):
            print("ABORT: rows are not an exact duplicate pair — not safe to delete.")
            return
        drop = next(r for r in rows if r["id"] == DROP_ID)

        with open(BACKUP, "w") as f:
            json.dump({k: (str(v) if k == "timestamp" else v) for k, v in drop.items()},
                      f, indent=2)
        print(f"backup written: {BACKUP} (the row to delete: id={DROP_ID})")

        if not APPLY:
            print("\nDRY-RUN — re-run with --apply to delete id "
                  f"{DROP_ID} (keeping {KEEP_ID}).")
            return

        await db.execute(text("DELETE FROM exercise_entries WHERE id = :i"),
                         {"i": DROP_ID})
        await db.commit()
        print(f"APPLIED — deleted duplicate exercise_entry id={DROP_ID}.")


if __name__ == "__main__":
    asyncio.run(main())
