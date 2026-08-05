"""Every state-changing surface, its DECLARED policy, and whether it holds.

    python scripts/mutation_inventory.py                 # summary
    python scripts/mutation_inventory.py --json FILE     # machine-readable
    python scripts/mutation_inventory.py --check         # CI gate (exit 1 on fail)

WHAT THIS MEASURES, AND WHY IT CHANGED
──────────────────────────────────────
The first version counted one thing: how many routes carried the food-logging
architecture. It answered "3 of 60", and that number could only be improved by
bolting an idempotency claim and a ledger event onto 57 routes that mostly
should not have either. A percentage is not a safety property.

What matters is that no mutation is UNKNOWN. So `core/mutation_policy.py`
declares, for every route, which contract it owes — including the explicit
policy "idempotency not required, because this operation is naturally
idempotent". This script joins that declaration against what it can actually
observe in the source, and fails when they disagree.

  DECLARED  — core/mutation_policy.py: class, auth, idempotency policy,
              transaction owner, ledger behaviour, replay, rollback, owner.
  OBSERVED  — read here from the handler's source and the test suite: turn
              identity, build attribution, the contract markers, whether a
              concurrency test exercises it.

Neither half is trusted alone. A declaration with no implementation is a
wish; an implementation with no declaration is an accident nobody reviewed.

THE LIMIT OF A STATIC READ is unchanged and still matters: a handler that
mutates through three layers of helper looks empty from here. A marker that
is not found is `unknown`, never `false`. Unknown is not pass — for a Class A
route it is a FAILURE, because a launch-critical guarantee nobody can see is
a guarantee nobody has.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.mutation_policy import (  # noqa: E402
    CLASS_REQUIREMENTS,
    BY_KEY,
    policy_for,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
MUTATING = {"post", "patch", "delete", "put"}
BASELINE = ROOT / "docs" / "mutation_baseline.json"

#: What proves each guarantee, by the names a handler would call. Deliberately
#: narrow — a loose match reports coverage that is not there, and an inventory
#: that overstates completeness is worse than none.
#
#: `mutation_turn` (core/mutation_contract) counts for turn identity, trace and
#: build attribution because it provably provides all three — it is the ONE
#: implementation of that shape and is pinned by
#: `tests/test_the_mutation_contract_helper.py`. Crediting a named, tested
#: helper is not the same as a loose match: what it credits is verified
#: elsewhere, which is the only reason a static read can trust it.

#: Entering the chat turn pipeline. VERIFIED, not assumed — the four chat
#: routes hand off to it and it owns all of the contract they are credited
#: with:
#:   * `core.conversation.run_turn` opens a RequestTrace for the whole turn and
#:     persists it on an isolated session, carrying `build_sha` (B5).
#:   * it sets the canonical `CURRENT_TURN_ID`, which `record_ledger_event`
#:     stamps on every write the turn makes.
#:   * the executor (`execute_tool_calls`) appends a ledger event per operation.
#:   * the structured food stage claims the turn via `claim_processed_turn`,
#:     so a redelivered message cannot double-log — the `claim_write_only`
#:     policy those routes declare.
#: All of that is three levels below the handler, so a one-level static read
#: reported the best-traced surface in the codebase as having nothing.
_CHAT_LANE = ("run_turn", "run_chat_turn")

MARKERS = {
    "canonical_turn_id": ("make_turn_id", "_turn_scope", "CURRENT_TURN_ID",
                          "turn_id=", "mutation_turn") + _CHAT_LANE,
    "idempotency": ("claim_request", "idempotency_key", "Idempotency-Key",
                    "claim=True") + _CHAT_LANE,
    # `execute_tool_calls` is the chat lane's ledger writer — it appends an
    # event per operation it runs. Routes that hand off to the executor own
    # the turn's identity, not the write, so this is where their history comes
    # from and reading only the handler reported them as leaving none.
    # `write_canonical_meal` writes the `created` event INSIDE the same
    # transaction as the rows it describes (core/canonical_writer.py, proven
    # by test_history_is_written_with_the_rows) — a promoted route carries
    # provenance by construction, so the spine's entry points are markers.
    "ledger_event": ("ledger_source", "record_ledger_event",
                     "record_created_from_row", "record_surface_mutation",
                     "turn.audit", "execute_tool_calls",
                     "write_canonical_meal", "commit_or_load_existing")
                    + _CHAT_LANE,
    "request_trace": ("RequestTrace", "trace.stage", "mutation_turn")
                     + _CHAT_LANE,
    # `turn.complete` counts, but it is the WEAKER form — a second commit, with
    # a crash window the in-transaction `claim_id=` does not have. The gate
    # cannot express "compliant but weaker", so the distinction lives in
    # `MutationTurn.complete`'s docstring and in each route's declared
    # transaction owner.
    "durable_result": ("claim_id=", "complete_claim", "turn.claim_id",
                       "turn.complete"),
    # A persisted trace row carries `build_sha` (core/request_trace._sha), so
    # build attribution is what persisting buys — not a separate mechanism.
    "build_attribution": ("trace.persist", "persist_isolated", "build_sha",
                          "_build_stamp", "mutation_turn") + _CHAT_LANE,
    # Class B owes an audit trail rather than a ledger event: the question
    # asked of a settings change later is "when did this change, and to what".
    # A RequestTrace is deliberately NOT evidence here — it is already its own
    # required guarantee, and counting it twice would let a route satisfy two
    # requirements with one mechanism and look complete on neither.
    "audit_trail": ("record_ledger_event", "record_surface_mutation",
                    "log_conversation", "ledger_source", "turn.audit",
                    "write_canonical_meal"),
    # Includes the webhook shapes: signature verification IS authorization,
    # and B7 made these fail closed. Reading only for a `Depends(...)`
    # identity would have called every signed webhook unauthorized.
    "authorized": ("current_identity", "get_user_by_webhook_token",
                   "require_admin", "_admin", "verify_signature",
                   "_verify_signature", "resolve_user", "construct_event",
                   "compare_digest", "WEBHOOK_SECRET", "verify_bb_signature"),
    "logged": ("logger.", "logging.", "log_conversation"),
}


def _router_prefixes(tree) -> dict:
    """`{variable_name: prefix}` for every APIRouter declared in the module.

    The decorator argument is only the tail of the path: `api/water.py` mounts
    at `/api/v1/water` and declares `@router.post("")`. Read naively that is
    route `""`, indistinguishable from every other prefix-only route — which
    makes the inventory unusable as a scoreboard exactly when it starts having
    rows to track.
    """
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not (isinstance(call, ast.Call)
                and getattr(call.func, "id", getattr(call.func, "attr", ""))
                == "APIRouter"):
            continue
        prefix = ""
        for kw in call.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = str(kw.value.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = prefix
    return out


def handlers(path: pathlib.Path):
    """(route, method, function node) for every mutating route in a file."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return
    prefixes = _router_prefixes(tree)
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
            # `@router.post(...)` carries its router's mount prefix;
            # `@app.post(...)` already spells the full path.
            holder = getattr(dec.func.value, "id", "")
            route = prefixes.get(holder, "") + route
            yield route or "/", dec.func.attr, node


def _local_defs(tree) -> dict:
    """Module-level functions by name, so a handler's delegate can be read.

    Without this `/api/v1/food` reports no ledger event — its write lives in
    `_write_food`. An inventory that calls a complete surface incomplete is
    not conservative, it is wrong.
    """
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}


def _called_names(node) -> set:
    """Every name this handler's body invokes, plus its FastAPI dependencies.

    A `Depends(require_admin)` passes the function as an ARGUMENT, so it never
    appears as a call and a plain read of the body misses it entirely. It runs
    on every request to the route regardless — which is exactly why the admin
    audit line lives in `require_admin` and not repeated in seven handlers —
    so a dependency is part of the route's effective behaviour and is read as
    such.
    """
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                names.add(f.id)
                # Depends(x) / Security(x): the callable is the argument.
                if f.id in ("Depends", "Security"):
                    for a in sub.args:
                        if isinstance(a, ast.Name):
                            names.add(a.id)
                        elif isinstance(a, ast.Attribute):
                            names.add(a.attr)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def effective_source(node, lines: list, local: dict) -> str:
    """The handler's body plus the bodies of module-level helpers it calls.

    ONE level deep, deliberately. Following the whole graph would reach
    `db.queries` and mark every surface complete because something downstream
    touches a ledger — the opposite failure.
    """
    src = ["\n".join(lines[node.lineno - 1: node.end_lineno])]
    for name in _called_names(node):
        helper = local.get(name)
        if helper is not None and helper is not node:
            src.append("\n".join(lines[helper.lineno - 1: helper.end_lineno]))
    return "\n".join(src)


def concurrency_tested() -> set:
    """Handler names exercised by a test that runs deliveries concurrently.

    Coarse on purpose: a name counts if it appears in a test module that also
    uses `asyncio.gather`. It cannot prove the gather covers THAT handler, so
    it is evidence a concurrency test exists, not proof it is a good one — and
    it is reported as an observation, not as a guarantee.
    """
    names = set()
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        try:
            text = path.read_text()
        except OSError:
            continue
        if "asyncio.gather" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    names.add(f.id)
                elif isinstance(f, ast.Attribute):
                    # `import api.app as A` then `A.api_log_food(...)`. Missing
                    # this reported every module-qualified concurrency test as
                    # absent, which is the coverage-understating direction but
                    # still wrong.
                    names.add(f.attr)
            elif isinstance(node, ast.ImportFrom):
                names.update(a.name for a in node.names)
    return names


def classify(src: str) -> dict:
    return {field: (True if any(n in src for n in names) else "unknown")
            for field, names in MARKERS.items()}


def build_rows() -> list:
    concurrent = concurrency_tested()
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
            found["concurrency_test"] = (True if node.name in concurrent
                                         else "unknown")
            policy = policy_for(method.upper(), route)
            # An intentionally PUBLIC route has no authorization to observe.
            # The declaration is the decision, and it was reviewed — demanding
            # a marker here would report "unauthorized" for a route that is
            # unauthenticated on purpose, which is noise that trains people to
            # ignore the gate.
            if policy is not None and policy.auth == "public":
                found["authorized"] = True
            required = list(CLASS_REQUIREMENTS.get(
                policy.mutation_class if policy else "", ()))
            # THE REQUIREMENTS FOLLOW THE DECLARED POLICY, not the class alone.
            # `durable_result` is where a CLAIM stores its committed answer, so
            # it only means anything on a route that takes one. A Class A route
            # whose declared policy is `natural` — the health imports, which
            # upsert on a stable per-sample identity — has no claim and no
            # stored result to replay, and demanding both would report a route
            # as non-compliant for correctly implementing the policy it
            # declared. Its idempotency is proven by test instead, which is
            # what `notes` on those declarations commits it to.
            if policy is not None and policy.idempotency != "claim_required":
                drop = ["durable_result"]
                # `claim_write_only` still takes a claim — it just stores no
                # replayable result — so it keeps the `idempotency` guarantee
                # and loses only `durable_result`.
                if policy.idempotency != "claim_write_only":
                    drop.append("idempotency")
                required = [g for g in required if g not in drop]
            missing = [g for g in required if found.get(g) is not True]

            if policy is None:
                status = "UNDECLARED"
            elif missing:
                status = "gap"
            else:
                status = "compliant"

            rows.append({
                "route": route,
                "method": method.upper(),
                "surface": f"{path.relative_to(ROOT)}::{node.name}",
                "command": node.name,
                # ── declared ──
                "mutation_class": policy.mutation_class if policy else None,
                "auth": policy.auth if policy else None,
                "idempotency_policy": policy.idempotency if policy else None,
                "transaction_owner": policy.transaction_owner if policy else None,
                "ledger_behavior": policy.ledger if policy else None,
                "replay_behavior": policy.replay if policy else None,
                "rollback_behavior": policy.rollback if policy else None,
                "owner": policy.owner if policy else None,
                "notes": policy.notes if policy else "",
                # ── observed ──
                **found,
                # ── verdict ──
                "missing_guarantees": missing,
                "status": status,
            })
    rows.sort(key=lambda r: (r["mutation_class"] or "Z", r["status"] != "gap",
                             r["route"]))
    return rows


def check(rows: list, strict: bool = False) -> list:
    """The CI failure conditions. Returns a list of failure strings.

    Two of the three are absolute: an undeclared route and a regression fail
    immediately, always.

    The Class A requirement is RATCHETED against the baseline rather than
    enforced outright, because 24 Class A routes are already short of it. A
    gate that is red on the day it lands teaches everyone to ignore it, and an
    ignored gate is worse than no gate — so the rule is "you may not add a new
    Class A gap, and the existing ones must shrink". `--strict` enforces the
    rule outright and is the launch gate: B2 is done when `--strict` passes.
    """
    failures = []
    base = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}

    # 1. A mutating route with no declared policy.
    for r in rows:
        if r["status"] == "UNDECLARED":
            failures.append(
                f"UNDECLARED  {r['method']} {r['route']} ({r['surface']}) — "
                f"add it to core/mutation_policy.py with its class and policy")

    # A declaration for a route that no longer exists is the same problem
    # pointed the other way: it makes the table read as covering something.
    live = {(r["method"], r["route"]) for r in rows}
    for key in sorted(set(BY_KEY) - live):
        failures.append(
            f"STALE       {key[0]} {key[1]} — declared in mutation_policy.py "
            f"but no such route exists")

    # 2. A route missing one of its class's required guarantees.
    #
    # Normally this is enforced for Class A only and ratcheted: new Class A
    # gaps fail immediately, the ones the baseline records are tracked debt.
    # `--strict` enforces EVERY class, because B2's exit criteria are not just
    # about Class A — "every Class B route authenticated, traced and
    # auditable; every Class C route authorized and logged". A strict gate
    # that passed while 29 Class B routes were untraced would report B2 as
    # finished when a third of it was outstanding.
    known_gap = 0
    for r in rows:
        if not r["missing_guarantees"]:
            continue
        cls = r["mutation_class"]
        if cls != "A" and not strict:
            continue
        key = f"{r['method']} {r['route']}"
        if strict or base.get(key) != "gap":
            failures.append(
                f"CLASS {cls} GAP {r['method']} {r['route']} — missing "
                f"{', '.join(r['missing_guarantees'])}")
        elif cls == "A":
            known_gap += 1

    # 3. A previously covered route that regressed.
    for r in rows:
        was = base.get(f"{r['method']} {r['route']}")
        if was == "compliant" and r["status"] != "compliant":
            failures.append(
                f"REGRESSION  {r['method']} {r['route']} — was compliant, "
                f"now {r['status']} (missing "
                f"{', '.join(r['missing_guarantees'])})")

    # The ratchet only tightens: a route recorded as a gap that is still a gap
    # is tolerated, but the COUNT may never grow beyond what was recorded.
    baseline_gaps = sum(1 for k, v in base.items() if v == "gap"
                        and (policy_for(*k.split(" ", 1)) or _N).mutation_class == "A")
    if not strict and known_gap > baseline_gaps:
        failures.append(
            f"RATCHET     Class A gaps grew from {baseline_gaps} to "
            f"{known_gap} — the debt list may only shrink")
    return failures


class _N:
    mutation_class = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on any gate failure (CI)")
    ap.add_argument("--strict", action="store_true",
                    help="enforce the Class A rule outright rather than "
                         "ratcheting — the launch gate. B2 is done when "
                         "`--check --strict` passes.")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record current statuses as the regression floor")
    args = ap.parse_args()

    rows = build_rows()

    print(f"\n{len(rows)} state-changing surfaces\n")
    print(f"{'cls':<4}{'route':<48}{'method':<8}{'idempotency':<20}status")
    print("-" * 104)
    for r in rows:
        print(f"{r['mutation_class'] or '?':<4}{r['route'][:47]:<48}"
              f"{r['method']:<8}{(r['idempotency_policy'] or '-'):<20}"
              f"{r['status']}"
              + (f"  ← {', '.join(r['missing_guarantees'])}"
                 if r["missing_guarantees"] else ""))

    by_class = Counter(r["mutation_class"] or "UNDECLARED" for r in rows)
    status = Counter(r["status"] for r in rows)
    print(f"\nby class : {dict(sorted(by_class.items()))}")
    print(f"by status: {dict(status)}")

    unknown = status.get("UNDECLARED", 0)
    print(f"\nUNKNOWN mutation surfaces: {unknown}   "
          f"(B2 exit criterion: 0)")
    for cls in ("A", "B", "C"):
        rs = [r for r in rows if r["mutation_class"] == cls]
        ok = sum(1 for r in rs if r["status"] == "compliant")
        print(f"  class {cls}: {ok}/{len(rs)} compliant with "
              f"{', '.join(CLASS_REQUIREMENTS[cls])}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {len(rows)} rows to {args.json}")

    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(
            {f"{r['method']} {r['route']}": r["status"] for r in rows},
            indent=2, sort_keys=True) + "\n")
        print(f"wrote regression floor to {BASELINE.relative_to(ROOT)}")

    # The one number B2 is finished by.
    open_a = sum(1 for r in rows
                 if r["mutation_class"] == "A" and r["missing_guarantees"])
    print(f"\nClass A routes still short of the full contract: {open_a} "
          f"(B2 exit criterion: 0 — `--check --strict`)")

    failures = check(rows, strict=args.strict)
    if failures:
        print(f"\n{len(failures)} gate failure(s):")
        for f in failures:
            print(f"  {f}")
        if args.check:
            return 1
        print("\n(run with --check to make these fail CI)")
    elif args.check:
        print("\ngate: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
