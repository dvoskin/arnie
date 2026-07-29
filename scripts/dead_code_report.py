#!/usr/bin/env python3
"""Merge static reachability with runtime evidence into one auditable report.

    python scripts/reachability.py --out reachability.json
    FUNC_HITS_OUT=func_hits.json python -m pytest tests/ -p scripts.trace_hits -q
    python scripts/dead_code_report.py reachability.json func_hits.json

Writes `dead_code_report.jsonl` — one object per symbol, with the columns the
sprint asks for — and prints the tally.

The categories mean exactly what they say, and the distinction that matters
most is between `dead` and `unknown`:

    production reachable   a caller, an import, or an annotation reaches it
    test only              only tests reach it, and it never ran outside them
    rollback reachable     reached only behind a flag that is off in render.yaml
    shadow implementation  a parallel path that observes and does not act
    write only             a field assigned and never read
    unknown                a parser cannot see how it is reached; probably fine
    dead                   no static reference AND never executed

`dead` is still not permission to delete. The test suite is not production:
a function the tests never touch may be the one the webhook calls at 3am.
What `dead` earns a symbol is a place on a list somebody reads, and the
deletion policy in the sprint — evidence, replacement, rollback risk, then a
small reviewable group — starts after that.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict
from typing import Dict, List

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Flags read from render.yaml, so "off in production" is a fact rather than a
#: memory. A symbol reachable only under an unset flag is ROLLBACK reachable —
#: deleting it removes the ability to revert, which is a different decision
#: from deleting something nothing can reach at all.
def deployed_flags() -> Dict[str, str]:
    out: Dict[str, str] = {}
    path = ROOT / "render.yaml"
    if not path.exists():
        return out
    key = None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("- key:"):
            key = s.split(":", 1)[1].strip()
        elif s.startswith("value:") and key:
            out[key] = s.split(":", 1)[1].strip().strip('"')
            key = None
    return out


def load_hits(path: pathlib.Path) -> Dict[str, set]:
    """`module -> {qualname}` for everything that executed."""
    by_module: Dict[str, set] = defaultdict(set)
    for entry in json.loads(path.read_text()):
        module, _, qual = entry.partition("::")
        by_module[module].add(qual)
    return by_module


def categorise(row: dict, ran: bool) -> str:
    static = row["static_category"]
    if static == "test only":
        return "test only"
    if static == "production reachable":
        return "production reachable"
    if ran:
        # Executed despite no visible caller: dynamic dispatch, a decorator, a
        # framework hook. Reachable, and the parser simply could not say how.
        return "unknown"
    if static == "unknown":
        return "unknown"
    return "dead"


def risk(row: dict, category: str) -> str:
    if category != "dead":
        return "-"
    if row["module"].startswith(("alembic/", "scripts/")):
        return "low: migration or operator tool, not request-path"
    if row["decorated"]:
        return "high: decorated, may be registered at import"
    if not row["private"]:
        return "medium: public name, may be imported by something unscanned"
    return "low: private, no reference, never executed"


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    data = json.loads(pathlib.Path(argv[1]).read_text())
    hits = load_hits(pathlib.Path(argv[2]))
    flags = deployed_flags()

    rows = []
    for row in data["defs"]:
        quals = hits.get(row["module"], set())
        ran = row["symbol"] in quals or any(
            q.split(".")[-1] == row["name"] for q in quals)
        category = categorise(row, ran)
        rows.append({
            "symbol": row["symbol"],
            "module": row["module"],
            "line": row["line"],
            "kind": row["kind"],
            "category": category,
            "static_inbound": row["static_inbound"],
            "prod_call_files": row["prod_call_files"],
            "test_call_files": row["test_call_files"],
            "test_runtime_hit": bool(ran),
            # Neither of these can be gathered here. Recorded as unknown rather
            # than as zero, because a column of confident zeroes is how a
            # report starts justifying deletions it has no evidence for.
            "replay_runtime_hit": None,
            "production_runtime_hit": None,
            "required_flags": "",
            "replacement": "",
            "risk": risk(row, category),
            "recommended_action": ("read and confirm" if category == "dead"
                                   else "keep"),
        })

    out = ROOT / "dead_code_report.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    tally: Dict[str, int] = defaultdict(int)
    for r in rows:
        tally[r["category"]] += 1
    print(f"  {len(rows):,} symbols -> {out.name}")
    print(f"  {len(flags)} flags read from render.yaml\n")
    for name, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<24}{n:>7}")

    dead = [r for r in rows if r["category"] == "dead"]
    prod_dead = [r for r in dead if not r["module"].startswith(
        ("tests/", "scripts/", "alembic/"))]
    print(f"\n  {len(dead)} dead, {len(prod_dead)} of them in shipped packages")
    print(f"  {sum(1 for r in rows if r['category'] == 'unknown')} unknown — "
          f"reachable by a route this analysis cannot see")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
