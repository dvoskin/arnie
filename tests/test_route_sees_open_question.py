"""The router knows a question is open before it routes.

Audit A4/B1. `RouteStage` has always had a `pending_clarification` branch and
`ConfirmReplayPlanStage` has always looked for `food_prior` — and
`build_request` set neither, so both were dead on the live path. Only the
shadow-observation hook passed them, and `observe_turn` then discarded its
request in favour of the ambient route computed without them.

The consequence was not "a branch is unused". An answer turn is not
recognisable from its own text: "half of it", "the big bag", "yes" read as
food to no gate ever written. Legacy routes them structured because it holds
the pending question; the coordinator predicted GENERAL. So the agreement rate
that gates the entire rollout was worst on exactly the turns the native lane
is least ready for, and it looked like a disagreement about food detection
rather than the coordinator being handed less information.
"""
import json
from datetime import datetime, timedelta

import pytest

from core.turns import entrypoint as EP
from core.turns.models import TurnLane
from core.turns.stages.route import RouteStage


class _PQ:
    """A pending_questions row, only the fields the TTL rule reads."""

    def __init__(self, payload: dict, *, age_min: int = 1):
        self.payload_json = json.dumps(payload)
        self.asked_at = datetime.utcnow() - timedelta(minutes=age_min)
        self.last_asked_at = None
        self.answered_at = None


def _request(text: str, **meta):
    return EP.build_request(
        turn_id="t1", user=type("U", (), {"id": 1})(), platform="ios",
        source_type="text", text=text, **meta)


# ── the request carries it ────────────────────────────────────────────────────

def test_build_request_carries_the_open_question():
    prior = {"question": "one or two tablespoons?", "kind": "clarify"}
    req = _request("half of it", food_prior=prior, food_pending=True)
    assert req.metadata["food_pending"] is True
    assert req.metadata["food_prior"] == prior


def test_build_request_defaults_to_no_pending():
    """A caller that does not look must not accidentally assert one exists."""
    req = _request("had 2 eggs")
    assert req.metadata["food_pending"] is False
    assert req.metadata["food_prior"] is None


# ── the router acts on it ─────────────────────────────────────────────────────

async def test_an_answer_turn_routes_structured_even_though_it_is_not_food():
    """The point of the whole change.

    "half of it" is not food to any gate. With the open question on the
    request it routes structured anyway — which is what legacy has always
    done, and what the coordinator could not do.
    """
    decision = await RouteStage().run(
        _request("half of it", food_prior={"question": "how much?"},
                 food_pending=True))
    assert decision.lane is TurnLane.STRUCTURED_FOOD
    assert decision.reason_code == "pending_clarification"


async def test_the_same_words_route_general_with_no_question_open():
    """The control. Without a pending, "half of it" is not a food turn, and
    treating it as one would be its own bug — the branch must be driven by the
    open question, not by having been added."""
    decision = await RouteStage().run(_request("half of it"))
    assert decision.lane is not TurnLane.STRUCTURED_FOOD


# ── reading the pending ───────────────────────────────────────────────────────

async def test_a_live_pending_is_returned_with_its_payload(monkeypatch):
    payload = {"question": "one or two tablespoons?", "kind": "clarify",
               "response_schema": "quantity", "staged_item_id": "sid-1"}
    pq = _PQ(payload)

    async def _get(db, user_id, kind):
        return pq

    monkeypatch.setattr("db.queries.get_open_pending_question", _get)
    got_pq, got_prior = await EP.open_food_pending(object(), 1)
    assert got_pq is pq
    # The schema rides along, which is what makes the answer parseable at all.
    assert got_prior["response_schema"] == "quantity"


async def test_an_expired_pending_reads_as_absent(monkeypatch):
    """A stale confirm must never bind a fresh turn — and reporting it absent
    is the whole of this function's job, because it may not write."""
    pq = _PQ({"kind": "confirm"}, age_min=60)      # confirm TTL is 20 min

    async def _get(db, user_id, kind):
        return pq

    monkeypatch.setattr("db.queries.get_open_pending_question", _get)
    assert await EP.open_food_pending(object(), 1) == (None, None)
    # ...and it did NOT resolve the row. Two writers on one pending is how the
    # legacy path's own expiry starts disagreeing with the router's.
    assert pq.answered_at is None


async def test_a_failing_lookup_routes_cold_rather_than_losing_the_turn(
        monkeypatch):
    async def _boom(db, user_id, kind):
        raise RuntimeError("db gone")

    monkeypatch.setattr("db.queries.get_open_pending_question", _boom)
    assert await EP.open_food_pending(object(), 1) == (None, None)


@pytest.mark.parametrize("db,user_id", [(None, 1), (object(), 0)])
async def test_no_session_or_no_user_is_not_an_error(db, user_id):
    assert await EP.open_food_pending(db, user_id) == (None, None)
