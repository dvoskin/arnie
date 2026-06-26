"""Backfill mislabeled PROACTIVE conversation rows (fleet-wide).

Root cause (fixed in scheduler/proactive_scheduler.py _log_proactive): proactive
sends were logged without platform=, defaulting the column to "telegram". So a
morning check-in / preworkout / day-report delivered to an iOS device via APNs or
to iMessage was tagged "telegram" and showed a wrong chip in cross-platform chat
history. This corrects the historical rows the code fix can't reach.

Scope (conservative): only rows with source_type='proactive' AND platform='telegram'
whose OWNING identity's telegram_id is ios:/apple: (→ios) or im: (→imessage).
Genuine Telegram proactive rows (numeric identity) are left untouched.

DRY-RUN by default. Writes a backup JSON of every (id, old_platform) before any
write. Pass --apply to commit.

  python scripts/fix_proactive_platform_labels.py          # preview
  python scripts/fix_proactive_platform_labels.py --apply  # commit
"""
import asyncio
import json
import sys
from dotenv import load_dotenv
load_dotenv(".env", override=True)
from sqlalchemy import text
from db.database import AsyncSessionLocal

APPLY = "--apply" in sys.argv
BACKUP = "proactive_platform_backfill_backup.json"


async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT c.id,
                   CASE WHEN u.telegram_id LIKE 'ios:%' OR u.telegram_id LIKE 'apple:%'
                          THEN 'ios'
                        WHEN u.telegram_id LIKE 'im:%' THEN 'imessage'
                   END AS new_platform
            FROM conversation_logs c JOIN users u ON u.id = c.user_id
            WHERE c.source_type = 'proactive' AND c.platform = 'telegram'
              AND (u.telegram_id LIKE 'ios:%' OR u.telegram_id LIKE 'apple:%'
                   OR u.telegram_id LIKE 'im:%')
            ORDER BY c.id
        """))).mappings().all()

        by_new = {}
        for r in rows:
            by_new.setdefault(r["new_platform"], []).append(r["id"])
        print(f"proactive rows to relabel: {len(rows)}")
        for k, v in by_new.items():
            print(f"  telegram → {k}: {len(v)} rows")

        if not rows:
            print("nothing to do.")
            return

        with open(BACKUP, "w") as f:
            json.dump([{"id": r["id"], "old": "telegram", "new": r["new_platform"]}
                       for r in rows], f, indent=2)
        print(f"backup written: {BACKUP}")

        if not APPLY:
            print("\nDRY-RUN — re-run with --apply to commit.")
            return

        for new_platform, ids in by_new.items():
            idlist = ",".join(str(i) for i in ids)
            await db.execute(text(
                f"UPDATE conversation_logs SET platform = :p WHERE id IN ({idlist})"
            ), {"p": new_platform})
        await db.commit()
        print(f"APPLIED — {len(rows)} rows relabeled.")


if __name__ == "__main__":
    asyncio.run(main())
