"""Turn the endpoint inventory into a gate, not just a report (B7).

The inventory catalogues auth for every live route. These assertions freeze the
B7 outcome: an admin route may never again take its credential from the URL or
drop its rate limit, and no route may be silently unauthenticated unless it is
on the reviewed public list. A PR that regresses any of these fails here instead
of shipping.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "endpoint_inventory", ROOT / "scripts" / "endpoint_inventory.py")
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)


@pytest.fixture(scope="module")
def rows():
    from api.app import app
    return [inv.classify(r) for r in app.routes if hasattr(r, "dependant")]


def test_no_admin_route_takes_a_url_credential(rows):
    offenders = [r["path"] for r in rows if r["admin"] and r["credential_in_url"]]
    assert offenders == [], f"admin credential back in the URL: {offenders}"


def test_every_admin_route_is_rate_limited(rows):
    unlimited = [r["path"] for r in rows if r["admin"] and not r["rate_limited"]]
    assert unlimited == [], f"admin route lost its rate limit: {unlimited}"


def test_every_admin_route_is_gated_by_the_admin_dependency(rows):
    ungated = [r["path"] for r in rows
               if r["admin"] and "admin_header" not in r["auth"]]
    assert ungated == [], f"admin route not behind require_admin: {ungated}"


def test_no_route_is_unauthenticated_unless_declared_public(rows):
    leaks = [r["path"] for r in rows
             if r["auth"] == ["none"] and not r["public_by_design"]]
    assert leaks == [], f"unauthenticated and not on the reviewed public list: {leaks}"


def test_the_only_urlcred_findings_are_the_known_capability_tokens(rows):
    # 36 capability-token URLs remain (iOS API + dashboard) — a documented scope
    # item, NOT admin. If this count moves, the inventory and scorecard must be
    # re-read: a new one is a regression, a removed one is progress to record.
    urlcred = [r for r in rows if r["credential_in_url"]]
    assert all(not r["admin"] for r in urlcred)
    assert len(urlcred) == 36, (
        f"capability-token-in-URL count changed to {len(urlcred)} — "
        "re-run scripts/endpoint_inventory.py and update the scorecard")
