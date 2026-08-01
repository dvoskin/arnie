"""The B2 scoreboard has to be trustworthy before the count on it means anything.

`scripts/mutation_inventory.py` is the gate the migration is measured against.
Its own docstring says an inventory that overstates completeness is worse than
none — so the two ways it can overstate are pinned here:

  * a mutation missing from the user-visible set entirely (the denominator
    shrinks and the percentage improves for free)
  * two different routes sharing one label, so a migrated surface appears to
    cover an unmigrated one

Both were live. Routes were read as the bare decorator argument, so every
`@router.post("")` handler reported route `""` and four separate files each
contributed a `/{entry_id}` row. And `NON_USER_STATE` matched path FRAGMENTS,
so the entry `"/health"` — meant for a liveness endpoint that is a GET and
never appears here at all — swallowed `/api/v1/health/snapshot`,
`/api/v1/health/weights` and `/health/apple`: three writes that record the
user's body weight and health history.
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


# ── the denominator is honest ────────────────────────────────────────────────


@pytest.mark.parametrize("route", [
    "/api/v1/health/snapshot",
    "/api/v1/health/weights",
    "/health/apple",
])
def test_health_writes_are_counted_as_user_visible(rows, route):
    """These write the user's weight and health history. Excluding them makes
    the migration look further along than it is."""
    found = [r for r in rows if r["route"] == route]
    assert found, f"{route} is missing from the inventory entirely"
    assert all(r["user_visible_state"] for r in found), (
        f"{route} writes the user's own health data but is excluded from the "
        f"launch-blocking set — the denominator is understated"
    )


def test_no_route_is_excluded_by_a_fragment_match(rows):
    """Exclusion must name a full path. A fragment silently takes everything
    mounted beneath it, which is how the HealthKit writes disappeared."""
    from scripts.mutation_inventory import NON_USER_STATE

    excluded = {r["route"] for r in rows if not r["user_visible_state"]}
    assert excluded <= set(NON_USER_STATE), (
        f"routes excluded without being named: {excluded - set(NON_USER_STATE)}"
    )


def test_every_named_exclusion_still_exists(rows):
    """A stale entry is how a route quietly re-enters the excluded set later
    under a name nobody rechecked."""
    from scripts.mutation_inventory import NON_USER_STATE

    live = {r["route"] for r in rows}
    assert set(NON_USER_STATE) <= live, (
        f"NON_USER_STATE names routes that no longer exist: "
        f"{set(NON_USER_STATE) - live}"
    )


# ── every surface is identifiable ────────────────────────────────────────────


def test_no_surface_reports_a_blank_route(rows):
    assert [r for r in rows if r["route"] == ""] == []


def test_routes_carry_their_router_prefix(rows):
    """`api/water.py` mounts at `/api/v1/water` and declares `@router.post("")`.
    Reported as `""` it is indistinguishable from every other prefix-only
    route in the codebase."""
    assert _by_route(rows, "/api/v1/water", "POST"), (
        "the iOS water surface lost its mount prefix — a reader cannot tell it "
        "from the dashboard's /api/water/log"
    )
    assert _by_route(rows, "/api/v1/food", "POST"), (
        "the reference-implementation surface is not reported at its real path"
    )


def test_the_ios_and_dashboard_water_surfaces_are_distinct_rows(rows):
    """Two different handlers, two different contracts, two different states.
    Collapsing them would let one's migration report the other's."""
    ios = _by_route(rows, "/api/v1/water", "POST")
    dashboard = _by_route(rows, "/api/water/log", "POST")
    assert len(ios) == 1 and len(dashboard) == 1
    assert ios[0]["surface"] != dashboard[0]["surface"]


# ── a complete surface is reported complete ──────────────────────────────────


@pytest.mark.parametrize("route,method", [
    ("/api/v1/food", "POST"),
    ("/api/v1/water", "POST"),
    ("/api/v1/water/{entry_id}", "PATCH"),
    ("/api/v1/water/{entry_id}", "DELETE"),
])
def test_migrated_surfaces_report_all_four_parts(rows, route, method):
    """The inverse failure: a surface that IS on the contract reported as
    incomplete puts a false FAIL on the scorecard."""
    found = _by_route(rows, route, method)
    assert len(found) == 1, f"{method} {route} not found exactly once"
    r = found[0]
    missing = [k for k in ("canonical_turn_id", "idempotency", "ledger_event",
                           "request_trace", "durable_result")
               if r[k] is not True]
    assert not missing, f"{method} {route} reports missing: {missing}"
    assert r["migration_status"] == "complete"
