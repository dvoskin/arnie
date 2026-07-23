"""PROD data-coherence scan — every user, every food row, READ-ONLY.

The DB is the oracle: whatever the conversation looked like, what's in these
rows is what the dashboard shows, what enrichment matched against, and what
"what did I eat today?" replays. This scan walks food_entries (and the
daily_logs roll-ups above them) across ALL users and flags every row that
violates an invariant the logging stack promises:

  EDITABLE   quantity parses as one clean "amount unit" clause — never blank,
             never "~2 handfuls romaine, 3 strips chicken, few tbsp dressing"
             (the uneditable-quantity incident), never a bare "some"/"1 serving".
  COHERENT   calories ≈ 4·protein + 4·carbs + 9·fats within max(60, 20%) —
             edit rows included ("edit rows stay macro-coherent", 7c55538).
  BOUNDED    per-row physical bounds: 0 ≤ cal ≤ 5000, macros ≥ 0, protein ≤
             300g, sodium ≤ 4000mg (the SODIUM_IMPLAUSIBLE_MG clamp, enforced
             retroactively), alcohol_units ≤ 15.
  CLEAN NAME parsed_food_name present, ≤ 60 chars, no '?', and no machinery
             leaks: '[#', '[SYSTEM', '{batch_', '[TODAY]', 'YOUR REPLY',
             'log_food', 'update_food_entry'.
  NO DUPES   same daily_log + same name + same quantity within a 3-minute
             window = suspected phantom double-write (the re-fire class the
             turn-intent gate exists to block).
  ROLL-UP    daily_logs.total_calories / total_protein equal the sum of the
             day's rows within 1 cal/1g (drift means a write path skipped the
             recompute).

Findings print per class with user/entry ids and land in
audits/prod_coherence_<date>.md. Exit code 1 if anything CRITICAL (leak,
roll-up drift, dupe) is found, else 0.

STRICTLY read-only: SELECTs only, no session.commit() anywhere.

Run wherever DATABASE_URL points at the target DB (prod: run on the box or
over the tunnel; default falls back to the local sqlite dev DB):
    set -a; source .env; set +a
    .venv/bin/python scripts/prod_coherence_scan.py             # full scan
    .venv/bin/python scripts/prod_coherence_scan.py --days 30   # recent window
    .venv/bin/python scripts/prod_coherence_scan.py --user 26   # one user
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import DailyLog, FoodEntry, User

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

QTY_OK = re.compile(r"^~?\d+(\.\d+)?(\s*-\s*\d+(\.\d+)?)?\s*[A-Za-z(#%][\w()#%/. -]*$"
                    r"|^~?\d+(\.\d+)?$")
QTY_VAGUE = re.compile(r"^\s*(some|a\s+few|a\s+bit|1\s+serving|serving)\s*$", re.I)
LEAK = re.compile(r"\[#|\[SYSTEM|\{batch_|\[TODAY\]|YOUR REPLY|log_food|update_food_entry")
DUPE_WINDOW = dt.timedelta(minutes=3)
SODIUM_MAX = 4000.0


def _row_findings(e: FoodEntry) -> list[tuple[str, str]]:
    out = []
    name = (e.parsed_food_name or "").strip()
    qty = (e.quantity or "").strip()

    if not name:
        out.append(("CLEAN NAME", "empty parsed_food_name"))
    else:
        if len(name) > 60:
            out.append(("CLEAN NAME", f"name > 60 chars: {name!r}"))
        if "?" in name:
            out.append(("CLEAN NAME", f"'?' in name: {name!r}"))
    for field, val in (("name", name), ("quantity", qty)):
        if val and LEAK.search(val):
            out.append(("LEAK", f"machinery in {field}: {val!r}"))

    if not qty:
        out.append(("EDITABLE", "empty quantity"))
    elif QTY_VAGUE.match(qty):
        out.append(("EDITABLE", f"vague quantity: {qty!r}"))
    elif qty.count(",") >= 1 or not QTY_OK.match(qty):
        out.append(("EDITABLE", f"unparseable quantity: {qty!r}"))

    cal = e.calories
    p, c, f = e.protein or 0, e.carbs or 0, e.fats or 0
    if cal is None:
        out.append(("BOUNDED", "calories NULL"))
    else:
        if not (0 <= cal <= 5000):
            out.append(("BOUNDED", f"calories out of range: {cal}"))
        if any(v is not None and v < 0 for v in (e.protein, e.carbs, e.fats)):
            out.append(("BOUNDED", f"negative macro P{e.protein}/C{e.carbs}/F{e.fats}"))
        if (e.protein or 0) > 300:
            out.append(("BOUNDED", f"protein implausible: {e.protein}g"))
        if e.sodium is not None and e.sodium > SODIUM_MAX:
            out.append(("BOUNDED", f"sodium above clamp: {e.sodium}mg"))
        if e.alcohol_units is not None and e.alcohol_units > 15:
            out.append(("BOUNDED", f"alcohol_units implausible: {e.alcohol_units}"))
        if e.protein is not None and e.carbs is not None and e.fats is not None:
            implied = 4 * p + 4 * c + 9 * f
            if cal and abs(cal - implied) > max(60, 0.20 * cal):
                out.append(("COHERENT",
                            f"{cal:.0f} cal vs 4P+4C+9F={implied:.0f} "
                            f"(P{p:.0f}/C{c:.0f}/F{f:.0f})"))
    return out


async def scan(days: int | None, only_user: int | None):
    findings = defaultdict(list)   # class -> [(user_id, detail)]
    rows = users = logs = 0
    async with AsyncSessionLocal() as db:
        q = (select(FoodEntry, DailyLog.user_id, DailyLog.date,
                    DailyLog.total_calories, DailyLog.total_protein)
             .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
             .order_by(DailyLog.user_id, FoodEntry.daily_log_id, FoodEntry.timestamp))
        if days:
            q = q.where(DailyLog.date >= dt.date.today() - dt.timedelta(days=days))
        if only_user:
            q = q.where(DailyLog.user_id == only_user)
        res = (await db.execute(q)).all()

        seen_users = set()
        by_log: dict[int, list] = defaultdict(list)
        log_totals: dict[int, tuple] = {}
        for e, uid, day, tot_cal, tot_pro in res:
            rows += 1
            seen_users.add(uid)
            by_log[e.daily_log_id].append((e, uid, day))
            log_totals[e.daily_log_id] = (uid, day, tot_cal or 0, tot_pro or 0)
            for cls, detail in _row_findings(e):
                findings[cls].append(
                    (uid, f"user {uid} {day} entry #{e.id} "
                          f"[{(e.parsed_food_name or '')[:40]!r}]: {detail}"))

        users = len(seen_users)
        logs = len(by_log)

        # NO DUPES: same log + name + quantity inside the window
        for log_id, entries in by_log.items():
            entries.sort(key=lambda t: t[0].timestamp or dt.datetime.min)
            for i in range(1, len(entries)):
                e, uid, day = entries[i]
                pe = entries[i - 1][0]
                if ((e.parsed_food_name or "").lower() == (pe.parsed_food_name or "").lower()
                        and (e.quantity or "") == (pe.quantity or "")
                        and e.timestamp and pe.timestamp
                        and e.timestamp - pe.timestamp <= DUPE_WINDOW):
                    findings["NO DUPES"].append(
                        (uid, f"user {uid} {day} entries #{pe.id}/#{e.id} "
                              f"{e.parsed_food_name!r} × {e.quantity!r} "
                              f"{(e.timestamp - pe.timestamp).seconds}s apart"))

        # ROLL-UP: stored day totals vs sum of rows
        for log_id, (uid, day, tot_cal, tot_pro) in log_totals.items():
            sum_cal = sum((e.calories or 0) for e, _, _ in by_log[log_id])
            sum_pro = sum((e.protein or 0) for e, _, _ in by_log[log_id])
            if abs(sum_cal - tot_cal) > 1 or abs(sum_pro - tot_pro) > 1:
                findings["ROLL-UP"].append(
                    (uid, f"user {uid} {day}: stored {tot_cal:.0f} cal/"
                          f"{tot_pro:.0f}g vs row-sum {sum_cal:.0f}/{sum_pro:.0f}"))
    return findings, rows, users, logs


CRITICAL = {"LEAK", "ROLL-UP", "NO DUPES"}
ORDER = ["LEAK", "ROLL-UP", "NO DUPES", "EDITABLE", "COHERENT", "BOUNDED", "CLEAN NAME"]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="only scan the last N days")
    ap.add_argument("--user", type=int, default=None, help="only scan one user id")
    ap.add_argument("--max-print", type=int, default=25, help="rows shown per class")
    args = ap.parse_args()

    findings, rows, users, logs = await scan(args.days, args.user)
    stamp = dt.date.today().isoformat()
    print(f"{B}PROD data-coherence scan{X} — {rows} food rows, {logs} day-logs, "
          f"{users} users" + (f", last {args.days}d" if args.days else " (all time)"))

    report = [f"# Prod data-coherence scan — {stamp}",
              f"\n{rows} food rows / {logs} day-logs / {users} users"
              + (f", last {args.days} days" if args.days else ", all time"), ""]
    critical = 0
    for cls in ORDER:
        items = findings.get(cls, [])
        n = len(items)
        affected = len({u for u, _ in items})
        tag = f"{R}CRITICAL{X}" if cls in CRITICAL and n else (
            f"{Y}warn{X}" if n else f"{G}clean{X}")
        print(f"\n  {tag}  {B}{cls}{X}: {n} finding(s)"
              + (f" across {affected} user(s)" if n else ""))
        report.append(f"\n## {cls} — {n} finding(s)"
                      + (f" across {affected} user(s)" if n else " — clean"))
        if cls in CRITICAL:
            critical += n
        for _, detail in items[:args.max_print]:
            print(f"      {D}{detail}{X}")
            report.append(f"- {detail}")
        if n > args.max_print:
            print(f"      {D}… and {n - args.max_print} more (in the report file){X}")
            report += [f"- {d}" for _, d in items[args.max_print:]]

    out = Path(__file__).resolve().parent.parent / "audits" / f"prod_coherence_{stamp}.md"
    out.write_text("\n".join(report) + "\n")
    print(f"\n{D}report written to {out}{X}")
    total = sum(len(v) for v in findings.values())
    print(f"{B}{'CLEAN — every invariant holds' if not total else str(total) + ' total findings'}"
          f"{(', ' + str(critical) + ' critical') if critical else ''}{X}")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
