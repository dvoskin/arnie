"""Percentiles from turn_metrics — the numbers a launch gate is scored on.

`scripts/food_latency_report.py` parses log lines, which means it can only
answer questions asked inside the retention window. This reads the table, so
"did p95 regress after that deploy" survives the logs rotating away — the
question that went unanswered when a +54% p50 regression was flagged on
2026-07-30.

    python scripts/latency_report.py                 # last 24h
    python scripts/latency_report.py --hours 168     # a week
    python scripts/latency_report.py --by channel

Reads DATABASE_URL. Prints counts alongside every percentile, because a p95
over four requests is a number, not a measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

#: The directive's budgets, so the report says pass/fail rather than leaving
#: the reader to remember them.
BUDGET_P95_MS = {"log_food": 2500, "log_exercise": 2500, "log_weight": 2500}


def pct(values: list, p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(int(round((p / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return int(ordered[idx])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--by", default="command", choices=("command", "channel",
                                                        "build_sha"))
    args = ap.parse_args()

    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set — this reads the metrics table.")
        return 1
    url = re.sub(r"^[a-z]+\+[a-z0-9]+://", "postgresql://", url)

    import psycopg
    with psycopg.connect(url, connect_timeout=20) as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT {args.by}, outcome, total_ms, stages_json
            FROM turn_metrics
            WHERE created_at > now() - interval '{args.hours} hours'
        """)
        rows = cur.fetchall()

    if not rows:
        print(f"no turn_metrics rows in the last {args.hours}h — either nothing "
              f"ran or the writer is not deployed. UNKNOWN, not pass.")
        return 0

    totals = defaultdict(list)
    stages = defaultdict(lambda: defaultdict(list))
    errors = defaultdict(int)
    for key, outcome, total_ms, stages_json in rows:
        key = key or "-"
        if total_ms is not None:
            totals[key].append(total_ms)
        if outcome and outcome != "ok":
            errors[key] += 1
        try:
            for name, ms in (json.loads(stages_json or "{}")).items():
                stages[key][name].append(ms)
        except Exception:
            pass

    print(f"\n=== {args.hours}h — {len(rows)} requests, by {args.by} ===\n")
    print(f"{args.by:<18} {'n':>6} {'p50':>7} {'p90':>7} {'p95':>7} "
          f"{'p99':>7} {'err':>5}  budget")
    print("-" * 78)
    for key in sorted(totals, key=lambda k: -len(totals[k])):
        v = totals[key]
        p95 = pct(v, 95)
        budget = BUDGET_P95_MS.get(key)
        verdict = ""
        if budget:
            verdict = f"{'PASS' if p95 <= budget else 'FAIL'} (<={budget}ms)"
        if len(v) < 20:
            verdict += "  [n<20: indicative only]"
        print(f"{key[:17]:<18} {len(v):>6} {pct(v,50):>7} {pct(v,90):>7} "
              f"{p95:>7} {pct(v,99):>7} {errors.get(key,0):>5}  {verdict}")

    print("\n--- p95 by stage ---")
    for key in sorted(stages, key=lambda k: -len(totals.get(k, []))):
        parts = [f"{n}:{pct(v, 95)}ms" for n, v in
                 sorted(stages[key].items(), key=lambda kv: -pct(kv[1], 95))]
        if parts:
            print(f"  {key[:24]:<26} {'  '.join(parts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
