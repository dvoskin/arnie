"""One-tap undo: the server side of the token the card already carried.

Every food macro_card ships the `event_id` of the write behind it, and the
client renders "· Undo" from it. Nothing accepted that token — the affordance
existed with no endpoint, so a card could offer an undo it had no way to
perform.

The rule these tests protect is that typing "undo" and tapping Undo reach the
SAME inverse: `plan_for_event` and `build_plan` share `_invert` and share the
TTLs. Two ways of taking something back that behave differently is the failure
this codebase keeps rediscovering, and a tap is the one a user trusts least if
it surprises them.
"""
from types import SimpleNamespace

import pytest

from core.ledger_undo import plan_for_event


class _Event:
    def __init__(self, *, id=1, user_id=7, domain="food",
                 event_type="created", entry_id=42, payload=None,
                 created_at=None):
        import datetime as _dt
        import json as _json
        self.id = id
        self.user_id = user_id
        self.domain = domain
        self.event_type = event_type
        self.entry_id = entry_id
        # `payload_json`, not `payload` — the column is a JSON STRING and
        # `_payload` parses it. A dict here silently reads as {}, which makes
        # every "before"-dependent inverse look uninvertible.
        self.payload_json = _json.dumps(payload if payload is not None else {
            "food_name": "Birria taco", "calories": 180, "protein": 12})
        self.created_at = created_at or _dt.datetime.utcnow()


class _DB:
    """Just enough session for `db.get(LedgerEvent, id)`."""
    def __init__(self, event=None):
        self._event = event

    async def get(self, _model, _id):
        if self._event is not None and int(_id) == self._event.id:
            return self._event
        return None


def _user(uid=7, linked=None):
    return SimpleNamespace(id=uid, linked_to_user_id=linked)


async def test_a_created_event_inverts_to_a_delete():
    """Tapping undo on a logged card removes that entry."""
    plan = await plan_for_event(_DB(_Event()), _user(), 1)
    assert plan is not None
    assert plan["action"] == "delete"
    assert plan["tool_calls"][0]["name"] == "delete_food_entry"
    assert plan["tool_calls"][0]["input"]["entry_id"] == 42


async def test_the_named_event_is_inverted_not_the_newest():
    """The whole point of taking an event_id. `build_plan` deliberately targets
    the most recent action because that is what "undo" means in conversation;
    a TAP means "this card", and reversing a different write than the one the
    user pointed at is the worst thing this endpoint could do."""
    target = _Event(id=99, entry_id=555, payload={"food_name": "Quest chips"})
    plan = await plan_for_event(_DB(target), _user(), 99)
    assert plan["tool_calls"][0]["input"]["entry_id"] == 555


async def test_another_users_event_is_refused():
    plan = await plan_for_event(_DB(_Event(user_id=1234)), _user(uid=7), 1)
    assert plan is None


async def test_a_linked_account_may_undo_its_own_family_event():
    """A phone and a desktop login are one person, the way every other read
    resolves a user."""
    ev = _Event(user_id=3)
    plan = await plan_for_event(_DB(ev), _user(uid=7, linked=3), 1)
    assert plan is not None


async def test_a_stale_event_is_refused():
    """Same freshness rule as the conversational path — undo is a recent-action
    affordance, not a time machine."""
    import datetime as _dt
    old = _Event(created_at=_dt.datetime.utcnow() - _dt.timedelta(days=3))
    assert await plan_for_event(_DB(old), _user(), 1) is None


async def test_a_missing_event_is_refused():
    assert await plan_for_event(_DB(None), _user(), 404) is None


async def test_an_uninvertible_event_is_refused_not_skipped_past():
    """Weight has no safe inverse. Refusing is right; quietly reversing the
    next thing down would be a silent wrong action."""
    ev = _Event(domain="weight", event_type="created")
    assert await plan_for_event(_DB(ev), _user(), 1) is None


async def test_water_and_exercise_invert_too():
    """The ledger is domain-general by design, and so is the tap."""
    water = await plan_for_event(
        _DB(_Event(domain="water", event_type="created")), _user(), 1)
    assert water["tool_calls"][0]["name"] == "delete_water_entry"
    ex = await plan_for_event(
        _DB(_Event(domain="exercise", event_type="created",
                   payload={"exercise_name": "Squats"})), _user(), 1)
    assert ex["tool_calls"][0]["name"] == "delete_exercise_entry"


async def test_an_update_rolls_back_to_the_before_state():
    ev = _Event(event_type="updated",
                payload={"food_name": "Rice",
                         "before": {"food_name": "Rice", "calories": 200,
                                    "quantity": "200g"}})
    plan = await plan_for_event(_DB(ev), _user(), 1)
    assert plan["action"] == "update"
    assert plan["tool_calls"][0]["input"]["calories"] == 200


async def test_a_broken_event_never_raises():
    """A tap must never 500. `plan_for_event` refuses instead."""
    class _Boom:
        async def get(self, *a):
            raise RuntimeError("db down")
    assert await plan_for_event(_Boom(), _user(), 1) is None


def test_undo_rows_do_not_render_in_chat():
    """The user watched it happen on the card they tapped; narrating it back is
    noise. The row stays so the model's context knows the board moved — the
    same treatment dashboard edits get."""
    import pathlib
    src = pathlib.Path("api/chat.py").read_text()
    assert '"ledger_undo"' in src, "undo rows must be filtered from history"


def test_the_endpoint_is_mounted():
    from api.app import app
    assert any(getattr(r, "path", "") == "/api/v1/ledger/undo"
               for r in app.routes)
