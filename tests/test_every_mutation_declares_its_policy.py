"""B2's exit criterion, as a test: no mutating route is UNKNOWN.

The measure this replaces was "3 of 60 routes carry the food-logging
architecture". That number could only be moved by bolting an idempotency claim
and a ledger event onto 57 routes, most of which should have neither — a claim
on a last-write-wins settings PATCH buys nothing, and a ledger event for a
device token records something no one will ever undo.

So the property is not "everything has the same contract". It is that every
route DECLARES the contract it owes, and that the declaration and the code
agree. `core/mutation_policy.py` is the declaration;
`scripts/mutation_inventory.py` reads the code and joins the two.
"""
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.mutation_policy import (  # noqa: E402
    BY_KEY,
    CLASS_REQUIREMENTS,
    IDEMPOTENCY,
    POLICIES,
)


def _run(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mutation_inventory.py"), *args],
        cwd=ROOT, capture_output=True, text=True)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    out = tmp_path_factory.mktemp("inv") / "inv.json"
    proc = _run("--json", str(out))
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.read_text())


# ── the exit criterion ───────────────────────────────────────────────────────


def test_there_are_zero_unknown_mutation_surfaces(rows):
    """The headline. Every mutating route resolves to a declared policy."""
    undeclared = [f"{r['method']} {r['route']}" for r in rows
                  if r["status"] == "UNDECLARED"]
    assert undeclared == [], (
        f"{len(undeclared)} mutation surfaces have no declared policy: "
        f"{undeclared}"
    )


def test_every_route_has_a_class_and_an_idempotency_decision(rows):
    for r in rows:
        assert r["mutation_class"] in CLASS_REQUIREMENTS, (
            f"{r['method']} {r['route']} has no mutation class")
        assert r["idempotency_policy"] in IDEMPOTENCY, (
            f"{r['method']} {r['route']} has no idempotency decision — "
            f"'naturally idempotent' is a valid answer, silence is not")


def test_no_policy_describes_a_route_that_does_not_exist(rows):
    """A stale declaration reads as coverage of something real."""
    live = {(r["method"], r["route"]) for r in rows}
    stale = sorted(set(BY_KEY) - live)
    assert stale == [], f"policies for routes that no longer exist: {stale}"


def test_the_inventory_reports_every_required_field(rows):
    """The record has to answer the questions asked of it later."""
    required = ("route", "method", "auth", "mutation_class",
                "canonical_turn_id", "build_attribution",
                "idempotency_policy", "transaction_owner", "ledger_behavior",
                "replay_behavior", "concurrency_test", "rollback_behavior",
                "owner", "status")
    for r in rows:
        missing = [f for f in required if f not in r]
        assert not missing, f"{r['route']} is missing fields: {missing}"


# ── the gate actually gates ──────────────────────────────────────────────────


def test_the_ratcheted_gate_passes_today():
    """CI runs this shape. If it is red on arrival nobody will read it."""
    proc = _run("--check")
    assert proc.returncode == 0, (
        f"the ratcheted gate is failing:\n{proc.stdout[-2000:]}")


def test_every_class_a_route_is_compliant():
    """Class A is DONE — all 29 carry the full contract with a concurrency
    proof. Pinned so it cannot quietly regress; the ratchet in `--check` would
    catch a regression too, but only against whatever the baseline last
    recorded."""
    proc = _run("--check")
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert "CLASS A GAP" not in proc.stdout, (
        f"a Class A route fell off the contract:\n{proc.stdout[-2000:]}")


def test_the_strict_gate_passes():
    """B2's exit criterion, asserted rather than described.

    `--strict` enforces every class: Class A's full contract, Class B
    authenticated + traced + auditable, Class C authorized + logged. It is
    what CI runs, so this failing means a route stopped satisfying the
    contract it declares — which is the whole point of having declared it.
    """
    proc = _run("--check", "--strict")
    assert proc.returncode == 0, (
        f"the strict gate is failing:\n{proc.stdout[-3000:]}")


def test_every_class_is_fully_compliant(rows):
    """The same property read off the data, so a failure names the route."""
    gaps = [f"{r['mutation_class']} {r['method']} {r['route']} — missing "
            f"{', '.join(r['missing_guarantees'])}"
            for r in rows if r["missing_guarantees"]]
    assert gaps == [], "\n".join(gaps)


def test_an_undeclared_route_fails_the_gate(tmp_path, monkeypatch):
    """The condition that keeps the count at zero as the codebase grows.

    Simulated by removing a policy rather than by adding a route: the check is
    that a route with no declaration is reported, and that is the same code
    path either way.
    """
    import scripts.mutation_inventory as inv

    rows = inv.build_rows()
    victim = next(r for r in rows if r["mutation_class"] == "C")
    victim = dict(victim, mutation_class=None, status="UNDECLARED",
                  missing_guarantees=[])
    failures = inv.check([victim])
    assert any(f.startswith("UNDECLARED") for f in failures), (
        f"an undeclared route did not fail the gate: {failures}")


def test_a_regression_from_compliant_fails_the_gate(monkeypatch, tmp_path):
    """A route that WAS on the contract and quietly fell off."""
    import scripts.mutation_inventory as inv

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"POST /api/v1/food": "compliant"}))
    monkeypatch.setattr(inv, "BASELINE", baseline)

    regressed = {"method": "POST", "route": "/api/v1/food",
                 "mutation_class": "A", "status": "gap",
                 "missing_guarantees": ["idempotency"], "surface": "x::y"}
    failures = inv.check([regressed])
    assert any(f.startswith("REGRESSION") for f in failures), failures


# ── the declarations are coherent ────────────────────────────────────────────


def test_class_a_routes_all_require_a_claim_or_justify_not_needing_one(rows):
    """A Class A route may declare `natural` idempotency, but only with a
    stated reason — that is the difference between a decision and an omission."""
    for p in POLICIES:
        if p.mutation_class == "A" and p.idempotency != "claim_required":
            assert p.notes, (
                f"{p.method} {p.route} is Class A and does not take a claim, "
                f"but gives no reason. 'Naturally idempotent' needs to say why."
            )


def test_health_imports_declare_their_tombstone_behaviour():
    """The reconciliation surface. A user's delete has to survive the next
    sync, or the row they removed comes back."""
    for route in ("/api/v1/health/snapshot", "/api/v1/health/weights",
                  "/health/apple", "/api/whoop/sync/{token}"):
        p = BY_KEY[("POST", route)]
        assert "tombstone" in p.rollback.lower(), (
            f"{route} does not declare how a deleted import stays deleted")
