"""Backfill micronutrients_json on existing food_entries.

Context: until 803acd9 we mapped only 7 macros + 3 minerals out of USDA and never
persisted the micro panel, so micronutrients_json was empty on every historical
entry. The code fix forward-fills new logs (and self-heals the memory cache via
e084483), but rows logged before the fix stay blank. This re-runs USDA enrichment
for them.

Approach: one USDA lookup per DISTINCT food name (best_candidate, same matcher the
live path uses), then scale the per-100g micro panel to EACH row's own portion via
the same cal/cal100 ratio analyze() uses. Idempotent — only touches rows whose
micronutrients_json is NULL/empty.

MUST run where the real USDA_API_KEY lives (prod/Render env) — DEMO_KEY rate-limits
at ~30/hr and can't cover a real backfill. DRY-RUN by default; writes a backup JSON
of every (id, old_value) before any write.

  python scripts/backfill_food_micros.py            # preview
  python scripts/backfill_food_micros.py --apply    # commit
  python scripts/backfill_food_micros.py --apply --days 90 --all-users
"""
import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv
load_dotenv(".env", override=True)

from sqlalchemy import text
from db.database import AsyncSessionLocal
from api import usda
from core.food_intelligence import best_candidate

DANNY_IDS = (2, 20, 26)   # canonical + linked
BACKUP = "food_micros_backfill_backup.json"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--all-users", action="store_true", help="fleet-wide (default: Danny only)")
    args = ap.parse_args()

    if not usda._key() or usda._key() == "DEMO_KEY":
        print("⚠️  No real USDA_API_KEY in env (got "
              f"{usda._key()!r}). DEMO_KEY rate-limits — run this on prod.", file=sys.stderr)

    user_filter = "" if args.all_users else f"AND d.user_id IN {DANNY_IDS}"
    window = f"AND f.timestamp > now() - interval '{args.days} days'"

    async with AsyncSessionLocal() as db:
        foods = (await db.execute(text(f"""
            SELECT lower(parsed_food_name) AS nm, count(*) AS n, max(f.timestamp) AS recent
            FROM food_entries f JOIN daily_logs d ON f.daily_log_id = d.id
            WHERE (f.micronutrients_json IS NULL OR f.micronutrients_json IN ('','{{}}'))
              AND f.calories > 0 AND f.parsed_food_name IS NOT NULL
              {user_filter} {window}
            GROUP BY lower(parsed_food_name)
            ORDER BY recent DESC
        """))).mappings().all()
        print(f"{len(foods)} distinct foods to enrich "
              f"(scope={'all users' if args.all_users else 'Danny'}, {args.days}d, apply={args.apply})\n")

        backup, updates = [], []   # updates: (id, new_json)
        matched = skipped = 0
        for f in foods:
            nm = f["nm"]
            try:
                cands = await usda.search_food(nm, page_size=8)
            except Exception as e:
                print(f"  ✗ {nm!r}: USDA error {e}"); skipped += 1; continue
            best, conf = best_candidate(nm, cands)
            p = (best or {}).get("per100g") or {}
            cal100 = p.get("calories")
            micros100 = {k: p[k] for k in usda.MICRO_KEYS if p.get(k) is not None}
            if not best or not cal100 or not micros100:
                print(f"  – {nm!r}: no usable USDA match ({f['n']} rows)"); skipped += 1; continue
            matched += 1

            rows = (await db.execute(text(f"""
                SELECT f.id, f.calories, f.micronutrients_json
                FROM food_entries f JOIN daily_logs d ON f.daily_log_id = d.id
                WHERE lower(f.parsed_food_name) = :nm
                  AND (f.micronutrients_json IS NULL OR f.micronutrients_json IN ('','{{}}'))
                  AND f.calories > 0 {user_filter} {window}
            """), {"nm": nm})).mappings().all()
            for r in rows:
                ratio = r["calories"] / cal100
                scaled = {k: round(v * ratio, 2) for k, v in micros100.items()}
                backup.append({"id": r["id"], "old": r["micronutrients_json"]})
                updates.append((r["id"], json.dumps(scaled)))
            print(f"  ✓ {nm!r}  [{best.get('data_type')}, {conf}]  {len(micros100)} micros → {len(rows)} rows")

        print(f"\nmatched {matched} / {len(foods)} foods, {len(updates)} rows; skipped {skipped}")
        if not args.apply:
            print("DRY-RUN — re-run with --apply to commit"); return

        with open(BACKUP, "w") as fh:
            json.dump(backup, fh)
        print(f"backup → {BACKUP}")
        for rid, js in updates:
            await db.execute(
                text("UPDATE food_entries SET micronutrients_json = :j WHERE id = :i"),
                {"j": js, "i": rid})
        await db.commit()
        print(f"COMMITTED {len(updates)} rows")


if __name__ == "__main__":
    asyncio.run(main())
