"""⛔⛔ THE FLAGS THAT DECIDE A TURN MUST BE READABLE FROM OUTSIDE THE CONTAINER.

Written the day a canary failed silently *(2026-08-16)*. General settlement was
enabled, the code was confirmed deployed, and a fully-supported meal — a banana
the predicate answered `Supported(memory)` for — was still settled by legacy.
Four gates decide that turn and NOT ONE was readable from outside, so the
diagnosis came from archaeology on `turn_metrics.stages_json`: a 4,688 ms
`pricing.qualification` proves legacy settled it, because canonical settlement
structurally cannot retrieve.

⭐ A CANARY THAT DOES NOT FIRE AND A CANARY THAT FIRED AND DECLINED WRITE THE
SAME LEDGER ROWS. The only thing that separates them is knowing which gates were
open, which is why this is an endpoint and not a log line.
"""
from __future__ import annotations

import pytest

from api.diagnostics import settlement_gates_summary

GATES = ("TURN_COORDINATOR_MODE", "TURN_COORDINATOR_LANES",
         "TURN_COORDINATOR_ALLOWLIST", "GENERAL_SETTLEMENT_ALLOWLIST")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in GATES:
        monkeypatch.delenv(name, raising=False)


def test_all_gates_closed_reports_unreachable():
    got = settlement_gates_summary()
    assert got["general_settlement_reachable"] is False
    assert got["coordinator_mode_executes"] is False
    assert got["structured_food_lane_enabled"] is False


def test_all_gates_open_reports_reachable(monkeypatch):
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_execute")
    monkeypatch.setenv("TURN_COORDINATOR_LANES", "structured_food")
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", "26")
    assert settlement_gates_summary()["general_settlement_reachable"] is True


@pytest.mark.parametrize("missing", ["TURN_COORDINATOR_MODE",
                                     "TURN_COORDINATOR_LANES",
                                     "GENERAL_SETTLEMENT_ALLOWLIST"])
def test_any_single_closed_gate_reports_unreachable(monkeypatch, missing):
    """⛔ THE CONJUNCTION IS THE POINT. Three of four open leaves the turn on
    legacy — writing a row and rendering a reply, looking exactly like success.
    That is what actually happened, twice."""
    values = {"TURN_COORDINATOR_MODE": "new_execute",
              "TURN_COORDINATOR_LANES": "structured_food",
              "GENERAL_SETTLEMENT_ALLOWLIST": "26"}
    for name, value in values.items():
        if name != missing:
            monkeypatch.setenv(name, value)
    assert settlement_gates_summary()["general_settlement_reachable"] is False


def test_an_unset_lane_list_is_an_empty_set_not_a_wildcard(monkeypatch):
    """The gate that cost a live diagnosis: unset enables NOTHING."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_execute")
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", "26")
    got = settlement_gates_summary()
    assert got["coordinator_lanes"] == []
    assert got["general_settlement_reachable"] is False


def test_cohorts_are_reported_as_sizes_never_as_ids(monkeypatch):
    """⚠ NO USER DATA ON A PUBLIC HEALTH ENDPOINT. An operator needs 'is anyone
    enrolled', never who."""
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", "26,99")
    cohort = settlement_gates_summary()["general_settlement_cohort"]
    assert cohort == {"set": True, "size": 2}
    assert "26" not in str(settlement_gates_summary())


def test_the_health_payload_carries_the_gates():
    import inspect

    import api.app as app

    source = inspect.getsource(app)
    assert "settlement_gates" in source, (
        "the health payload no longer reports the gates — the canary becomes "
        "undiagnosable again")
