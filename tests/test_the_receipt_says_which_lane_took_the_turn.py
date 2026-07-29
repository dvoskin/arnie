"""Which lane took the turn, and why — on the receipt, not only in the log.

`_to_legacy` already notes its reason onto the food trace, and the trace is a
log line. So "which turns escaped the structured lane, and why" could only be
asked of whoever held the Render logs, inside a window that had not rotated.
Asked of the database, the only answer available was the ledger's `source`
column — which INFERS the lane from a call that arrived unstamped, rather than
reading the decision that was actually made.

Production, 2026-07-28/29: 16 of 41 ledger events in an 18-hour window read
`legacy*`, and nothing could say which of them were the gate declining, the
interpreter returning nothing, or a shape the lane never covered. Establishing
that the four which survived the sprint's routing work were two correction
turns took a hand reconstruction from timestamps.

The route rides beside `steps` the way `duration_ms` does: diagnostic, and
rendered by nothing.
"""
import json

from core.reasoning import build_reasoning


def _calls():
    return [{"name": "log_food", "input": {"food_name": "Cucumber"}}]


# ── absent rather than empty ─────────────────────────────────────────────────

def test_a_turn_with_no_route_carries_no_route_key():
    """A receipt that could not read the route must not be mistaken for one
    that read `legacy`. Absent is a third state and it has to survive."""
    rec = build_reasoning(_calls(), {"log_food": "Logged Cucumber."})
    assert "route" not in rec


def test_an_empty_route_is_also_absent():
    rec = build_reasoning(_calls(), {}, None, None, None, route={})
    assert "route" not in rec


# ── what it says when it does say something ──────────────────────────────────

def test_the_structured_lane_names_itself_and_claims_no_reason():
    """`legacy_reason` on a structured turn would be a contradiction — the
    reason exists only to explain a hand-back."""
    rec = build_reasoning(_calls(), {}, None, None, None,
                          route={"lane": "structured_log"})
    assert rec["route"]["lane"] == "structured_log"
    assert "legacy_reason" not in rec["route"]


def test_a_hand_back_carries_the_reason_that_caused_it():
    rec = build_reasoning(_calls(), {}, None, None, None,
                          route={"lane": "legacy",
                                 "legacy_reason": "interpreter_none"})
    assert rec["route"] == {"lane": "legacy",
                            "legacy_reason": "interpreter_none"}


def test_a_gate_decline_and_an_interpreter_hand_back_are_distinguishable():
    """The distinction the ledger's `source` column cannot make: both write
    through the legacy lane, and only one of them is the lane working."""
    declined = build_reasoning(_calls(), {}, None, None, None,
                               route={"lane": "legacy",
                                      "legacy_reason": "not_food_shaped"})
    handed_back = build_reasoning(_calls(), {}, None, None, None,
                                  route={"lane": "legacy",
                                         "legacy_reason": "interpreter_none"})
    assert (declined["route"]["legacy_reason"]
            != handed_back["route"]["legacy_reason"])


def test_the_owner_of_the_decision_rides_along():
    """`route_owner` is first-claim-wins on the trace — a free signal that
    claimed before the gate ran is a Haiku round trip not paid for, and that
    is only countable if it is stored."""
    rec = build_reasoning(_calls(), {}, None, None, None,
                          route={"lane": "structured_log", "owner": "thread"})
    assert rec["route"]["owner"] == "thread"


# ── it must not disturb what was already there ───────────────────────────────

def test_the_route_does_not_displace_the_steps_or_the_duration():
    rec = build_reasoning(_calls(), {"log_food": "Logged Cucumber."}, None,
                          1234, None, route={"lane": "structured_log"})
    assert rec["duration_ms"] == 1234
    assert rec["steps"], "the receipt still shows what the turn did"


def test_the_receipt_survives_the_json_round_trip_it_is_stored_through():
    """`log_conversation` persists this with `json.dumps`; a receipt that
    cannot make that trip is a receipt that is never queryable."""
    rec = build_reasoning(_calls(), {}, None, 900, None,
                          route={"lane": "legacy",
                                 "legacy_reason": "ask_stash_failed",
                                 "owner": "gate_model"})
    assert json.loads(json.dumps(rec))["route"]["owner"] == "gate_model"
