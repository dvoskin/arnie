"""⛔ THE MODE ALONE IS NOT THE ANSWER — and reading it as one cost a diagnosis.

2026-08-14. `/health` reported `TURN_COORDINATOR_MODE: new_execute` and a
canary was run twice against it asking why canonical pricing never fired. The
mode was true. It was also not the question: `lane_executes_natively` is an AND
of THREE conditions — mode, lane enrolled, user allowlisted — and the two the
health block did not report were the two that were false.

This is [[verify_the_instrument_before_its_silence]] in its other direction. An
instrument that reports one conjunct of a predicate and is READ as reporting
the predicate is not silent — it is confidently, specifically wrong, and it
takes a real experiment down with it.

So the gates below are deliberately NEGATIVE-first: the case that matters is
the one where the mode says yes and the lane still does not execute, because
that is the exact state production was in while a canary was being blamed on
the code it was pointed at.
"""
from __future__ import annotations

import pytest

from api.diagnostics import _food_pipeline


@pytest.fixture
def lanes(monkeypatch):
    """Set the three coordinator vars; unset anything not given."""
    def _set(mode=None, lanes=None, allowlist=None):
        for name, value in (("TURN_COORDINATOR_MODE", mode),
                            ("TURN_COORDINATOR_LANES", lanes),
                            ("TURN_COORDINATOR_ALLOWLIST", allowlist)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return _food_pipeline()
    return _set


def test_new_execute_with_no_lane_enrolled_reports_that_it_does_not_execute(lanes):
    """THE PRODUCTION STATE THAT FOOLED THE CANARY, as a gate.

    Mode says new_execute; no lane is enrolled; therefore nothing executes
    natively. Before this field the block reported only the first clause.
    """
    out = lanes(mode="new_execute", lanes=None, allowlist="26")

    assert out["TURN_COORDINATOR_MODE"]["effective"] == "new_execute"
    assert out["TURN_COORDINATOR_LANES"]["effective"] == []
    assert out["structured_food_executes_natively"]["allowlisted_user"] is False


def test_new_execute_with_the_lane_enrolled_reports_that_it_does(lanes):
    """And the positive case, so the field is not vacuously False."""
    out = lanes(mode="new_execute", lanes="structured_food", allowlist="26")

    assert out["structured_food_executes_natively"]["allowlisted_user"] is True


def test_an_allowlist_excludes_the_fleet_and_the_block_says_so(lanes):
    """The distinction that made "5 unreachable" the wrong number once already:
    two cohorts are live at the same time, and a single boolean cannot say so."""
    out = lanes(mode="new_execute", lanes="structured_food", allowlist="26")

    assert out["structured_food_executes_natively"]["allowlisted_user"] is True
    assert out["structured_food_executes_natively"]["fleet"] is False


def test_no_allowlist_means_the_lane_is_fleet_wide(lanes):
    """An EMPTY allowlist is not a narrow one — `lane_executes_natively`
    reads it as "everybody". Reporting `fleet: False` here would understate a
    fleet-wide rollout, which is the more dangerous direction to be wrong in."""
    out = lanes(mode="new_execute", lanes="structured_food", allowlist=None)

    assert out["TURN_COORDINATOR_ALLOWLIST"]["effective"] == []
    assert out["structured_food_executes_natively"]["fleet"] is True


def test_observe_mode_never_executes_whatever_the_lane_says(lanes):
    """`new_observe` means the coordinator WATCHES and legacy settles. An
    enrolled lane does not change that, and the block must not imply it does."""
    out = lanes(mode="new_observe", lanes="structured_food", allowlist="26")

    assert out["structured_food_executes_natively"]["allowlisted_user"] is False


def test_the_raw_vars_distinguish_unset_from_set_to_empty(lanes):
    """`_flag`'s whole reason to exist: a var that never loaded and a var
    deliberately set empty behave identically and need opposite fixes."""
    unset = lanes(mode="new_execute", lanes=None)
    empty = lanes(mode="new_execute", lanes="")

    assert unset["TURN_COORDINATOR_LANES"]["env_set"] is False
    assert empty["TURN_COORDINATOR_LANES"]["env_set"] is True
    # Same effective value, different cause — which is the point.
    assert (unset["TURN_COORDINATOR_LANES"]["effective"]
            == empty["TURN_COORDINATOR_LANES"]["effective"] == [])


def test_the_reported_answer_is_the_predicate_itself_not_a_copy(lanes):
    """⭐ ANTI-DRIFT. A diagnostic that RE-DERIVES the conjunction it reports
    can disagree with the runtime it claims to describe — so this asserts the
    block agrees with `lane_executes_natively` across every combination,
    including the ones no deploy has used yet."""
    from core.turns.coordinator import lane_executes_natively

    for mode in ("legacy_only", "new_observe", "new_execute"):
        for lane_v in (None, "", "structured_food", "workout"):
            for allow in (None, "26", "1,2,3"):
                out = lanes(mode=mode, lanes=lane_v, allowlist=allow)
                ids = out["TURN_COORDINATOR_ALLOWLIST"]["effective"]
                expected = lane_executes_natively(
                    "structured_food", ids[0] if ids else None)
                assert (out["structured_food_executes_natively"]
                        ["allowlisted_user"]) is expected, (
                    f"health disagrees with the runtime at mode={mode!r} "
                    f"lanes={lane_v!r} allowlist={allow!r}")
