"""Backfix the 3 sets dropped from Danny's 2026-06-25 shoulder session (log179).

Reconciled from the conversation transcript (turns #4854-#4880) against the logged
exercise_entries. Three sets Danny performed never made it to the DB:

  1. Overhead Press 130×12 — the 2nd "And 130x12" (#4855) was collapsed by the
     per-tool dedup as "already on the board" though it was a distinct set. Arnie
     confirmed "Three sets at 130 done" but only 2 rows exist (id 506,507).
  2. Upright Row 100×15 — Danny did "3 sets of 15" (#4880) but id515 stored sets=2.
  3. Rear Delt Cable Fly unilateral L11/R13 @40 — the model acknowledged it
     ("Unilateral, noted", #4863) but fired NO log_exercise; the resend (#4865)
     then got a false "already on the board".

Fix: INSERT the missing shoulder-press + rear-delt sets, and bump the upright-row
row to 3 sets. Exercise entries don't feed daily_log calorie/protein totals, so no
aggregate update is needed. A 'backfill 2026-06-25' marker in notes makes this
idempotent (won't double-apply) and reversible.

DRY-RUN by default; --apply to commit. Backs up the upright-row pre-state.
"""
import asyncio
import json
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(".env", override=True)
from sqlalchemy import text
from db.database import AsyncSessionLocal

APPLY = "--apply" in sys.argv
LOG_ID = 179
UPRIGHT_ID = 515
MARKER = "backfill 2026-06-25 missing-set"
BACKUP = "backfix_danny_0625_missing_sets_backup.json"

# 130lb=58.96696kg, 100lb=45.3592kg, 40lb=18.14368kg (matches existing rows)
OHP = dict(name="Overhead Press", sets=1, reps="12", weight=58.96696,
           ts="2026-06-25 22:06:30",
           notes=f"{MARKER}: 3rd shoulder-press set 130x12, deduped in error (#4855)")
RDF = dict(name="Rear Delt Cable Fly", sets=1, reps="11", weight=18.14368,
           ts="2026-06-25 22:18:30",
           notes=f"{MARKER}: unilateral set L11/R13 @40lb; model acknowledged, never logged (#4863)")


async def main():
    async with AsyncSessionLocal() as db:
        # idempotency guard — bail if marker rows already present
        existing = (await db.execute(text(
            "SELECT id, exercise_name FROM exercise_entries "
            "WHERE daily_log_id=:l AND notes LIKE :m"
        ), {"l": LOG_ID, "m": f"%{MARKER}%"})).mappings().all()
        if existing:
            print(f"ALREADY APPLIED — marker rows present: "
                  f"{[(r['id'], r['exercise_name']) for r in existing]}")
            return

        upright = (await db.execute(text(
            "SELECT id, sets, reps, weight FROM exercise_entries WHERE id=:i"
        ), {"i": UPRIGHT_ID})).mappings().first()
        print("planned changes:")
        print(f"  INSERT {OHP['name']} {OHP['sets']}x{OHP['reps']} @130lb")
        print(f"  INSERT {RDF['name']} {RDF['sets']}x{RDF['reps']} @40lb (unilateral L11/R13)")
        print(f"  UPDATE id{UPRIGHT_ID} Upright Row sets {upright['sets']}->3 "
              f"reps {upright['reps']!r}->'15,15,15'")

        with open(BACKUP, "w") as f:
            json.dump({"upright_pre": dict(upright), "marker": MARKER}, f, indent=2, default=str)
        print(f"backup written: {BACKUP}")

        if not APPLY:
            print("\nDRY-RUN — re-run with --apply to commit.")
            return

        for e in (OHP, RDF):
            await db.execute(text(
                "INSERT INTO exercise_entries "
                "(daily_log_id, timestamp, occurred_at, exercise_name, sets, reps, "
                " weight, source_type, notes) "
                "VALUES (:l, :ts, :ts, :n, :s, :r, :w, 'text', :notes)"
            ), {"l": LOG_ID, "ts": e["ts"], "n": e["name"], "s": e["sets"],
                "r": e["reps"], "w": e["weight"], "notes": e["notes"]})
        await db.execute(text(
            "UPDATE exercise_entries SET sets=3, reps='15,15,15', "
            "notes = COALESCE(notes,'') || :m WHERE id=:i"
        ), {"i": UPRIGHT_ID, "m": f" | {MARKER}: filled 3rd set 100x15 (#4880 stored only 2)"})
        await db.commit()
        print("APPLIED — 2 sets inserted, upright row bumped to 3.")


if __name__ == "__main__":
    asyncio.run(main())
