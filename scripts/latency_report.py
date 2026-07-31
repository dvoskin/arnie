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
#: the reader to remember them. quick-log taps should feel instant; a
#: conversational turn runs one or two model calls plus a tool batch, so its
#: budget is the turn DEADLINE, not a tap's.
#:
#: `turn` / `turn:log` budgets (B5) are PROVISIONAL — set at the 6s turn
#: deadline (core/deadline) so a p95 AT the cap means turns are routinely
#: degrading, which is the signal worth catching. Calibrate down once a week of
#: production rows exists; until then a PASS here only means "not hitting the
#: hard cap", not "fast".
BUDGET_P95_MS = {
    "log_food": 2500, "log_exercise": 2500, "log_weight": 2500,
    "turn:log": 5000, "turn": 6000,
}


def pct(values: list, p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(int(round((p / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return int(ordered[idx])


def summarize(rows: list) -> list:
    """Per-key latency summary from `(key, outcome, total_ms, stages_json)` rows.

    Pure — no DB, no printing — so the percentile and budget logic is testable
    without a Postgres. `main()` reads the rows and prints what this returns.
    Sorted by request count descending (the busiest route is the one that
    matters most). `verdict` is PASS/FAIL against BUDGET_P95_MS when a budget
    exists for that key, else "" — and n<20 is flagged indicative, because a p95
    over a handful of requests is a number, not a measurement.
    """
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

    out = []
    for key in sorted(totals, key=lambda k: -len(totals[k])):
        v = totals[key]
        p95 = pct(v, 95)
        budget = BUDGET_P95_MS.get(key)
        verdict = ""
        if budget:
            verdict = "PASS" if p95 <= budget else "FAIL"
        out.append({
            "key": key, "n": len(v),
            "p50": pct(v, 50), "p90": pct(v, 90), "p95": p95, "p99": pct(v, 99),
            "err": errors.get(key, 0), "budget": budget, "verdict": verdict,
            "indicative": len(v) < 20,
            "stage_p95": {n: pct(s, 95) for n, s in stages[key].items()},
        })
    return out


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

    summary = summarize(rows)

    print(f"\n=== {args.hours}h — {len(rows)} requests, by {args.by} ===\n")
    print(f"{args.by:<18} {'n':>6} {'p50':>7} {'p90':>7} {'p95':>7} "
          f"{'p99':>7} {'err':>5}  budget")
    print("-" * 78)
    for r in summary:
        verdict = ""
        if r["budget"]:
            verdict = f"{r['verdict']} (<={r['budget']}ms)"
        if r["indicative"]:
            verdict += "  [n<20: indicative only]"
        print(f"{r['key'][:17]:<18} {r['n']:>6} {r['p50']:>7} {r['p90']:>7} "
              f"{r['p95']:>7} {r['p99']:>7} {r['err']:>5}  {verdict}")

    print("\n--- p95 by stage ---")
    for r in summary:
        parts = [f"{n}:{ms}ms" for n, ms in
                 sorted(r["stage_p95"].items(), key=lambda kv: -kv[1])]
        if parts:
            print(f"  {r['key'][:24]:<26} {'  '.join(parts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
