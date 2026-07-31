"""Every state-changing surface, and which parts of the mutation contract it has.

The contract a mutation is supposed to satisfy:

    canonical turn id -> idempotency claim -> ONE transaction holding the
    domain row, its ledger event and the claim completion -> request trace

Food satisfies all of it. Exercise and weight now do. Nothing knew how many
OTHER surfaces exist, which is the actual question before launch — "no
production user-facing mutation is UNKNOWN in the inventory" cannot be asserted
without counting them.

This walks `api/` for route decorators, reads each handler's own source, and
records what it can PROVE. Static reading has a real limit: a handler that
mutates through three layers of helper looks empty from here. So a marker that
is not found is reported as `unknown`, never as `false` — the difference
between "this surface lacks a trace" and "I could not tell" is exactly the
distinction the scorecard's third state exists for.

    python scripts/mutation_inventory.py                 # summary
    python scripts/mutation_inventory.py --json FILE     # machine-readable
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
MUTATING = {"post", "patch", "delete", "put"}

#: What proves each part of the contract, by the names a handler would call.
#: Deliberately narrow — a loose match would report coverage that is not there,
#: and an inventory that overstates completeness is worse than none.
MARKERS = {
    "canonical_turn_id": ("make_turn_id", "_turn_scope", "CURRENT_TURN_ID",
                          "turn_id="),
    "idempotency": ("claim_request", "idempotency_key", "Idempotency-Key"),
    "ledger_event": ("ledger_source", "record_ledger_event",
                     "record_created_from_row"),
    "request_trace": ("RequestTrace", "trace.stage"),
    "durable_result": ("claim_id=", "complete_claim"),
}

#: Surfaces that change server state but not a user's logged history. They are
#: listed so the count is honest, and excluded from the launch-blocking set —
#: the directive's own rule that low-risk internal operations must not block a
#: launch once their behaviour is documented.
NON_USER_STATE = (
    "/health", "/webhook", "/stripe-webhook", "/disconnect", "/session",
    "/link", "/link-code", "/exchange-pairing-code", "/apns-token",
    "/onboarding/complete", "/preregister", "/imessage",
)


def handlers(path: pathlib.Path):
    """(route, method, function node) for every mutating route in a file."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in MUTATING):
                continue
            route = ""
            if dec.args and isinstance(dec.args[0], ast.Constant):
                route = str(dec.args[0].value)
            yield route, dec.func.attr, node


def _local_defs(tree) -> dict:
    """Module-level functions, by name, so a handler's delegate can be read.

    Without this the read stops at the handler body and `/food` reports no
    ledger event — its write lives in `_write_food`. An inventory that calls a
    complete surface incomplete is not conservative, it is wrong, and it would
    put a false FAIL on the scorecard.
    """
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            out[node.name] = node
    return out


def _called_names(node) -> set:
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def effective_source(node, lines: list, local: dict) -> str:
    """The handler's own body plus the bodies of module-level helpers it calls.

    ONE level deep, deliberately. Following the whole graph would eventually
    reach `db.queries` and mark every surface complete because something
    downstream touches a ledger — which is the opposite failure.
    """
    src = ["\n".join(lines[node.lineno - 1: node.end_lineno])]
    for name in _called_names(node):
        helper = local.get(name)
        if helper is not None and helper is not node:
            src.append("\n".join(lines[helper.lineno - 1: helper.end_lineno]))
    return "\n".join(src)


def classify(src: str) -> dict:
    out = {}
    for field, names in MARKERS.items():
        out[field] = True if any(n in src for n in names) else "unknown"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args()

    rows = []
    for path in sorted((ROOT / "api").rglob("*.py")):
        text = path.read_text()
        lines = text.splitlines()
        try:
            local = _local_defs(ast.parse(text))
        except SyntaxError:
            local = {}
        for route, method, node in handlers(path):
            found = classify(effective_source(node, lines, local))
            complete = all(v is True for v in found.values())
            user_state = not any(route.startswith(p) or p in route
                                 for p in NON_USER_STATE)
            rows.append({
                "surface": f"{path.relative_to(ROOT)}::{node.name}",
                "route": route,
                "method": method.upper(),
                "command": node.name,
                "channel": "ios" if "quick_log" in str(path) else "http",
                "user_visible_state": user_state,
                **found,
                "migration_status": ("complete" if complete
                                     else "partial" if any(v is True for v in found.values())
                                     else "not_started"),
            })

    rows.sort(key=lambda r: (not r["user_visible_state"],
                             r["migration_status"], r["route"]))

    status = Counter(r["migration_status"] for r in rows)
    user_rows = [r for r in rows if r["user_visible_state"]]
    user_status = Counter(r["migration_status"] for r in user_rows)

    print(f"\n{len(rows)} state-changing surfaces "
          f"({len(user_rows)} touching user-visible state)\n")
    print(f"{'route':<44} {'method':<7} {'turn':<8} {'idem':<8} "
          f"{'ledger':<8} {'trace':<8} status")
    print("-" * 104)
    for r in rows:
        if not r["user_visible_state"]:
            continue
        m = lambda v: "yes" if v is True else "?"        # noqa: E731
        print(f"{r['route'][:43]:<44} {r['method']:<7} "
              f"{m(r['canonical_turn_id']):<8} {m(r['idempotency']):<8} "
              f"{m(r['ledger_event']):<8} {m(r['request_trace']):<8} "
              f"{r['migration_status']}")

    print(f"\nALL surfaces      : {dict(status)}")
    print(f"USER-STATE surfaces: {dict(user_status)}")
    complete = user_status.get("complete", 0)
    print(f"\nuser-visible mutations fully on the contract: "
          f"{complete}/{len(user_rows)}")
    print("\nNOTE: a marker not found is reported `unknown`, never `false` — "
          "a handler that\nmutates through helpers looks empty to a static "
          "read. Unknown is not pass.")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {len(rows)} rows to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
