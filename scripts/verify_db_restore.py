"""Verify a Postgres target for the DR drill (B9/B10).

READ-ONLY. Prints the schema version and, for every critical table, the row count
and newest `created_at`/`timestamp`. Give it a second target with `--compare` and
it diffs the two side by side — the check that a restored backup actually matches
what prod held.

Why raw psycopg and not the app engine: prior sessions found the async engine
hangs against the managed prod DB. This opens ONE synchronous connection, reads,
and closes — safe to point at prod, and the same code verifies a throwaway
restore target.

Usage:
    DATABASE_URL=<target> python scripts/verify_db_restore.py
    DATABASE_URL=<prod> python scripts/verify_db_restore.py --compare <drill_url>

The URL may carry SQLAlchemy's `+psycopg` dialect suffix; it is stripped. No
writes are ever issued.
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg

#: (table, timestamp column) — the tables a restore must bring back intact. A
#: table absent from the schema is reported as MISSING, not crashed on.
CRITICAL = [
    ("users", None),
    ("daily_logs", None),
    ("food_entries", "timestamp"),
    ("exercise_entries", "timestamp"),
    ("ledger_events", "created_at"),
    ("conversation_logs", "timestamp"),
    ("turn_metrics", "created_at"),
    ("idempotency_records", "created_at"),
]


def _dsn(url: str) -> str:
    if not url:
        print("DATABASE_URL is not set — this reads a metrics/restore target.")
        sys.exit(2)
    return url.replace("+psycopg", "")


def _snapshot(url: str) -> dict:
    """{'_schema': rev, table: {'rows': n, 'latest': ts|None} | {'missing': True}}."""
    out: dict = {}
    with psycopg.connect(_dsn(url), connect_timeout=20) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT version_num FROM alembic_version")
                row = cur.fetchone()
                out["_schema"] = row[0] if row else "(none)"
            except Exception as e:
                out["_schema"] = f"(unreadable: {e})"
            for table, ts_col in CRITICAL:
                cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                if cur.fetchone()[0] is None:
                    out[table] = {"missing": True}
                    continue
                cur.execute(f"SELECT count(*) FROM {table}")  # table name is a literal
                n = cur.fetchone()[0]
                latest = None
                if ts_col:
                    try:
                        cur.execute(f"SELECT max({ts_col}) FROM {table}")
                        latest = cur.fetchone()[0]
                    except Exception:
                        latest = None
                out[table] = {"rows": n, "latest": latest}
    return out


def _fmt(cell: dict) -> str:
    if cell.get("missing"):
        return "MISSING"
    latest = cell.get("latest")
    return f"{cell['rows']:>8}" + (f"  latest={latest:%Y-%m-%d %H:%M}" if latest else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", metavar="URL", default=os.getenv("COMPARE_DATABASE_URL"),
                    help="second target (e.g. the restore drill DB) to diff against")
    args = ap.parse_args()

    primary = _snapshot(os.getenv("DATABASE_URL", ""))
    print(f"schema (alembic): {primary['_schema']}")

    if not args.compare:
        print(f"\n{'table':22}{'rows / latest'}")
        print("-" * 60)
        for table, _ in CRITICAL:
            print(f"{table:22}{_fmt(primary[table])}")
        return 0

    other = _snapshot(args.compare)
    same_schema = primary["_schema"] == other["_schema"]
    print(f"compare schema:   {other['_schema']}  "
          f"{'MATCH' if same_schema else '*** MISMATCH ***'}")
    print(f"\n{'table':22}{'PRIMARY':>26}   {'COMPARE':>26}   drift")
    print("-" * 92)
    ok = same_schema
    for table, _ in CRITICAL:
        a, b = primary[table], other[table]
        an = -1 if a.get("missing") else a["rows"]
        bn = -1 if b.get("missing") else b["rows"]
        drift = ("" if an == bn else f"{bn - an:+d}")
        if an != bn:
            ok = False
        print(f"{table:22}{_fmt(a):>26}   {_fmt(b):>26}   {drift}")
    print("\n" + ("VERIFY OK — schema matches and row counts align."
                  if ok else
                  "VERIFY FAIL — schema or row counts differ (see drift)."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
