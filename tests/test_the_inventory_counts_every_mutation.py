"""The B2 scoreboard has to be trustworthy before the count on it means anything.

`scripts/mutation_inventory.py` is the gate B2 is measured against. Its own
docstring says an inventory that overstates completeness is worse than none,
so the ways it can overstate are pinned here.

Both of these were live defects:

  * Routes were read as the bare decorator argument, so every
    `@router.post("")` handler reported route `""` — as did every other
    prefix-only handler — and four separate files each contributed an
    indistinguishable `/{entry_id}` row. A migrated surface was not tellable
    from an unmigrated one.

  * An exclusion list matched path FRAGMENTS. The entry `"/health"`, meant for
    a liveness endpoint that is a GET and never appears here at all, swallowed
    `/api/v1/health/snapshot`, `/api/v1/health/weights` and `/health/apple` —
    three writes that record the user's BODY WEIGHT and health history. They
    were dropped from the launch-blocking set, so the denominator was short.

That exclusion list is gone: under `core/mutation_policy.py` every route is
classified rather than excluded, which is what makes "zero unknowns" a
statement about all 75 rather than about a filtered subset. The health writes
are pinned below as Class A — the strongest contract — so they cannot quietly
become someone's rounding error again.

Complementary to `test_every_mutation_declares_its_policy.py`, which pins the
declaration side; this file pins what the inventory OBSERVES.
"""
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    out = tmp_path_factory.mktemp("inv") / "inventory.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mutation_inventory.py"),
         "--json", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"the inventory failed to run: {proc.stderr}"
    return json.loads(out.read_text())


def _by_route(rows, route, method):
    return [r for r in rows if r["route"] == route and r["method"] == method]


# ── the health writes are in scope, at the strongest contract ────────────────


@pytest.mark.parametrize("route", [
    "/api/v1/health/snapshot",
    "/api/v1/health/weights",
    "/health/apple",
])
def test_health_writes_are_class_a(rows, route):
    """These write the user's weight and health history. Anything weaker than
    Class A would let them off the guarantees that protect logged data."""
    found = [r for r in rows if r["route"] == route]
    assert found, f"{route} is missing from the inventory entirely"
    for r in found:
        assert r["mutation_class"] == "A", (
            f"{route} writes the user's own health data but is classified "
            f"{r['mutation_class']}")


def test_no_route_is_silently_out_of_scope(rows):
    """Every discovered route is classified. Nothing is filtered out of the
    count — that filtering is what hid the HealthKit writes."""
    unclassified = [f"{r['method']} {r['route']}" for r in rows
                    if not r["mutation_class"]]
    assert unclassified == [], unclassified


# ── every surface is identifiable ────────────────────────────────────────────


def test_no_surface_reports_a_blank_route(rows):
    assert [r for r in rows if not r["route"] or r["route"] == ""] == []


def test_routes_carry_their_router_prefix(rows):
    """`api/water.py` mounts at `/api/v1/water` and declares `@router.post("")`.
    Reported as `""` it is indistinguishable from every other prefix-only
    route in the codebase."""
    assert _by_route(rows, "/api/v1/water", "POST"), (
        "the iOS water surface lost its mount prefix — a reader cannot tell it "
        "from the dashboard's /api/water/log")
    assert _by_route(rows, "/api/v1/food", "POST"), (
        "the reference-implementation surface is not reported at its real path")


def test_the_ios_and_dashboard_water_surfaces_are_distinct_rows(rows):
    """Two different handlers, two different states. Collapsing them would let
    one's migration report the other's."""
    ios = _by_route(rows, "/api/v1/water", "POST")
    dashboard = _by_route(rows, "/api/water/log", "POST")
    assert len(ios) == 1 and len(dashboard) == 1
    assert ios[0]["surface"] != dashboard[0]["surface"]
    assert ios[0]["status"] == "compliant"
    assert dashboard[0]["status"] == "gap", (
        "the dashboard water surface has not been migrated; reporting it as "
        "compliant would be the collapse this test exists to catch")


# ── a migrated surface is observed as compliant ──────────────────────────────


@pytest.mark.parametrize("route,method", [
    ("/api/v1/food", "POST"),
    ("/api/v1/water", "POST"),
    ("/api/v1/water/{entry_id}", "PATCH"),
    ("/api/v1/water/{entry_id}", "DELETE"),
])
def test_migrated_surfaces_observe_the_full_contract(rows, route, method):
    """The inverse failure: a surface that IS on the contract reported as
    incomplete puts a false FAIL on the scorecard."""
    found = _by_route(rows, route, method)
    assert len(found) == 1, f"{method} {route} not found exactly once"
    r = found[0]
    missing = [k for k in ("canonical_turn_id", "idempotency", "ledger_event",
                           "request_trace", "durable_result")
               if r[k] is not True]
    assert not missing, f"{method} {route} reports missing: {missing}"
