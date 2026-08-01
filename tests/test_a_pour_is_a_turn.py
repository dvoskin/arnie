"""A pour is a turn — the water lane is not exempt from the mutation contract.

The sibling of `test_a_tap_is_a_turn.py`, for the surface that was further
behind than either of the ones that test covers. Before B2, a water entry
logged from the iOS Today tile produced:

  * no ledger event at all — so `ledger_undo.build_plan` took the last event
    UNCONDITIONALLY and "undo that" after a pour reversed the previous
    CHAT-logged item, a row the user never mentioned. This is audit O-1's
    defect, still live on the water surface after food and exercise were fixed.
  * no turn id — the write could not be joined to the request that caused it.
  * no idempotency claim — a double tap on the tile, or a retry on a flaky
    network, logged the glass twice.

Every test here fails on `fca59a4` and asserts on BEHAVIOUR (rows and events
in the database), not on the presence of a marker in the source.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.water import (
    WaterLogBody,
    WaterUpdateBody,
    delete_water,
    log_water,
    update_water,
)
from db.models import LedgerEvent, WaterEntry


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Both modules open their own session; both must land in the test engine.

    `api.water` reuses `api.quick_log`'s `_turn_scope` / `_client_key`, but it
    holds its OWN `AsyncSessionLocal` reference — patching one does not patch
    the other, and a miss here would silently test the production database.
    """
    from api import quick_log, water
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(water, "AsyncSessionLocal", factory)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


async def _events(db, user_id, domain="water"):
    return (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user_id,
                                  LedgerEvent.domain == domain)
        .order_by(LedgerEvent.id)
    )).scalars().all()


# ── the pour is recorded, and traceable ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_tap_logged_pour_records_a_created_event(
    patched_session_local, db, make_user,
):
    """The O-1 defect on the water surface: the row landed, history did not."""
    user = await make_user(telegram_id="ios:water-event")
    await log_water(WaterLogBody(amount_ml=500), identity="ios:water-event",
                    client_request_id="POUR-1")

    events = await _events(db, user.id)
    assert len(events) == 1, (
        "a tap-logged pour wrote no ledger event — `ledger_undo` reaches past "
        "it to a row the user never mentioned"
    )
    assert events[0].event_type == "created"
    assert events[0].entry_id is not None, (
        "the event must name its row, or undo has no token to invert"
    )


@pytest.mark.asyncio
async def test_a_tap_logged_pour_event_carries_its_turn_id(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:water-turn")
    result = await log_water(WaterLogBody(amount_ml=250),
                             identity="ios:water-turn",
                             client_request_id="POUR-UUID-2")

    events = await _events(db, user.id)
    assert len(events) == 1
    assert events[0].turn_id == "ios:POUR-UUID-2"
    assert result["turn_id"] == "ios:POUR-UUID-2", (
        "the handler must report the same turn id it stamped on the event — "
        "that is what makes the trace and the row join without a correlation "
        "step"
    )


@pytest.mark.asyncio
async def test_a_keyless_pour_is_still_traceable(
    patched_session_local, db, make_user,
):
    """Traceability must not depend on the client sending anything — a build
    that predates `Idempotency-Key` still has to produce a joinable event."""
    user = await make_user(telegram_id="ios:water-keyless")
    await log_water(WaterLogBody(amount_ml=330),
                    identity="ios:water-keyless")

    events = await _events(db, user.id)
    assert len(events) == 1
    assert events[0].turn_id is not None
    assert events[0].turn_id.startswith("ios:h:"), (
        "with no client key the id must come from the documented hash "
        "fallback, not from an invented format"
    )


@pytest.mark.asyncio
async def test_the_pour_event_carries_the_amount_undo_needs(
    patched_session_local, db, make_user,
):
    """`core.ledger_undo._invert` reads `amount_ml` off a water `created`
    event. An event without it produces an undo plan that cannot describe
    what it is taking back."""
    import json

    user = await make_user(telegram_id="ios:water-payload")
    await log_water(WaterLogBody(amount_ml=750, context="after workout"),
                    identity="ios:water-payload", client_request_id="POUR-P")

    events = await _events(db, user.id)
    payload = json.loads(events[0].payload_json)
    assert payload["amount_ml"] == 750
    assert payload["context"] == "after workout"


@pytest.mark.asyncio
async def test_undo_after_a_pour_takes_back_the_pour_not_the_meal(
    patched_session_local, db, make_user,
):
    """The user-visible harm, end to end — audit O-1 on the water surface.

    `ledger_undo.build_plan` takes the LAST event unconditionally. With the
    pour writing no event, the last event was still the food logged before it,
    so "undo that" right after tapping the water tile silently deleted the
    MEAL — a row the user was not looking at and had not mentioned.

    Deliberately keyless, so this fails on an ASSERTION on the pre-B2 code
    (it plans a food delete) rather than on the new signature: it measures the
    behaviour, not the refactor.
    """
    from core.ledger_undo import build_plan

    user = await make_user(telegram_id="ios:water-undo")

    from api.quick_log import FoodLogBody, log_food_entry
    await log_food_entry(
        FoodLogBody(food_name="Chicken bowl", calories=600, protein=45,
                    carbs=50, fats=20),
        identity="ios:water-undo",
    )
    await log_water(WaterLogBody(amount_ml=500), identity="ios:water-undo")

    plan = await build_plan(db, user, "undo that")

    assert plan is not None, "the pour left nothing to undo"
    called = [c["name"] for c in plan["tool_calls"]]
    assert called == ["delete_water_entry"], (
        f"'undo that' after a pour planned {called} — it reached past the "
        f"water and targeted the previous meal, a row the user never mentioned"
    )


# ── the same pour twice is one row ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_same_pour_delivered_twice_commits_one_row(
    patched_session_local, db, make_user,
):
    """A double tap on the Today tile replays the client's request id."""
    user = await make_user(telegram_id="ios:water-retry")
    body = WaterLogBody(amount_ml=500)

    first = await log_water(body, identity="ios:water-retry",
                            client_request_id="RETRY-POUR")
    second = await log_water(body, identity="ios:water-retry",
                             client_request_id="RETRY-POUR")

    rows = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()

    assert len(rows) == 1, "a replayed pour created a duplicate water row"
    assert second["entry_id"] == first["entry_id"], (
        "the replay must return the ORIGINAL committed result"
    )
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_a_replayed_pour_does_not_double_the_day_total(
    patched_session_local, db, make_user,
):
    """The cached aggregate is what the Today tile reads. A replay that left
    it inflated would show the user hydration they never drank — visible even
    though the duplicate row was correctly refused."""
    user = await make_user(telegram_id="ios:water-total")
    body = WaterLogBody(amount_ml=600)

    await log_water(body, identity="ios:water-total",
                    client_request_id="TOTAL-POUR")
    second = await log_water(body, identity="ios:water-total",
                             client_request_id="TOTAL-POUR")

    assert second["total_water_ml"] == 600, (
        f"the replay reported {second['total_water_ml']}ml — the cached total "
        f"counted the same pour twice"
    )


@pytest.mark.asyncio
async def test_two_concurrent_deliveries_of_one_pour_commit_one_row(
    patched_session_local, db, make_user,
):
    """The double-tap race. The invariant is ONE ROW; the loser may receive
    the winner's result or a retryable 409, and which one depends on
    scheduling."""
    from fastapi import HTTPException

    user = await make_user(telegram_id="ios:water-race")
    body = WaterLogBody(amount_ml=400)

    results = await asyncio.gather(
        log_water(body, identity="ios:water-race", client_request_id="RACE-W"),
        log_water(body, identity="ios:water-race", client_request_id="RACE-W"),
        return_exceptions=True,
    )

    rows = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()
    assert len(rows) == 1, (
        f"the double-tap race committed {len(rows)} rows (results: {results})")

    for r in results:
        assert isinstance(r, (dict, HTTPException)), (
            f"a delivery failed in an unhandled way: {r!r}")
        if isinstance(r, HTTPException):
            assert r.status_code == 409


@pytest.mark.asyncio
async def test_two_different_pours_are_not_deduplicated(
    patched_session_local, db, make_user,
):
    """The failure the contract must NOT cause. Two genuine glasses, logged
    separately, are two rows — dropping the second because it looks like the
    first is the same class of bug as double-writing, pointed the other way."""
    user = await make_user(telegram_id="ios:water-distinct")

    await log_water(WaterLogBody(amount_ml=500), identity="ios:water-distinct",
                    client_request_id="GLASS-1")
    await log_water(WaterLogBody(amount_ml=500), identity="ios:water-distinct",
                    client_request_id="GLASS-2")

    rows = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()
    assert len(rows) == 2, "two real glasses collapsed into one row"


@pytest.mark.asyncio
async def test_a_reused_key_with_a_different_amount_fails_loudly(
    patched_session_local, db, make_user,
):
    from fastapi import HTTPException

    await make_user(telegram_id="ios:water-conflict")
    await log_water(WaterLogBody(amount_ml=500),
                    identity="ios:water-conflict", client_request_id="SAME-W")

    with pytest.raises(HTTPException) as excinfo:
        await log_water(WaterLogBody(amount_ml=250),
                        identity="ios:water-conflict",
                        client_request_id="SAME-W")
    assert excinfo.value.status_code == 409


# ── edits and deletes are on the contract too ────────────────────────────────


@pytest.mark.asyncio
async def test_an_edit_records_an_updated_event_with_the_before_state(
    patched_session_local, db, make_user,
):
    """A correction that overwrites the only record of the previous amount is
    not reversible. The `updated` event holds the before-state, the same way
    food and exercise edits do."""
    import json

    user = await make_user(telegram_id="ios:water-edit")
    logged = await log_water(WaterLogBody(amount_ml=500),
                             identity="ios:water-edit",
                             client_request_id="EDIT-BASE")

    await update_water(logged["entry_id"], WaterUpdateBody(amount_ml=750),
                       identity="ios:water-edit", client_request_id="EDIT-1")

    events = await _events(db, user.id)
    updated = [e for e in events if e.event_type == "updated"]
    assert len(updated) == 1, "the edit recorded no ledger event"
    assert updated[0].turn_id == "ios:EDIT-1"

    payload = json.loads(updated[0].payload_json)
    assert payload["amount_ml"] == 750
    assert payload["before"]["amount_ml"] == 500, (
        "the event must hold what the amount USED to be, or the correction "
        "cannot be rolled back"
    )


@pytest.mark.asyncio
async def test_a_replayed_edit_is_applied_once(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:water-edit-retry")
    logged = await log_water(WaterLogBody(amount_ml=500),
                             identity="ios:water-edit-retry",
                             client_request_id="ER-BASE")

    await update_water(logged["entry_id"], WaterUpdateBody(amount_ml=800),
                       identity="ios:water-edit-retry",
                       client_request_id="ER-1")
    await update_water(logged["entry_id"], WaterUpdateBody(amount_ml=800),
                       identity="ios:water-edit-retry",
                       client_request_id="ER-1")

    events = await _events(db, user.id)
    assert len([e for e in events if e.event_type == "updated"]) == 1, (
        "the replayed edit wrote a second `updated` event — history now shows "
        "two corrections the user made once"
    )


@pytest.mark.asyncio
async def test_a_delete_records_a_restorable_event(
    patched_session_local, db, make_user,
):
    import json

    user = await make_user(telegram_id="ios:water-del")
    logged = await log_water(WaterLogBody(amount_ml=600, context="with lunch"),
                             identity="ios:water-del",
                             client_request_id="DEL-BASE")

    await delete_water(logged["entry_id"], identity="ios:water-del",
                       client_request_id="DEL-1")

    rows = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == user.id)
    )).scalars().all()
    assert rows == []

    events = await _events(db, user.id)
    deleted = [e for e in events if e.event_type == "deleted"]
    assert len(deleted) == 1, "the delete left no history to restore from"
    assert deleted[0].turn_id == "ios:DEL-1"
    payload = json.loads(deleted[0].payload_json)
    assert payload["amount_ml"] == 600, (
        "a `deleted` event with no amount cannot be restored from — the row "
        "it described is already gone"
    )


@pytest.mark.asyncio
async def test_a_replayed_delete_reports_the_original_success(
    patched_session_local, db, make_user,
):
    """The row being gone is the outcome the caller asked for. Answering 404
    to a network retry would read as a failure and prompt the client to
    surface an error for work that succeeded."""
    await make_user(telegram_id="ios:water-del-retry")
    logged = await log_water(WaterLogBody(amount_ml=300),
                             identity="ios:water-del-retry",
                             client_request_id="DR-BASE")

    first = await delete_water(logged["entry_id"],
                               identity="ios:water-del-retry",
                               client_request_id="DR-1")
    second = await delete_water(logged["entry_id"],
                                identity="ios:water-del-retry",
                                client_request_id="DR-1")

    assert first["ok"] is True
    assert second["ok"] is True
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_a_pour_belonging_to_another_user_is_not_touched(
    patched_session_local, db, make_user,
):
    """Ownership scoping survives the rewrite. The claim is taken before the
    row is read, so a 404 path must not leave someone else's row edited."""
    from fastapi import HTTPException

    owner = await make_user(telegram_id="ios:water-owner")
    await make_user(telegram_id="ios:water-thief")
    logged = await log_water(WaterLogBody(amount_ml=500),
                             identity="ios:water-owner",
                             client_request_id="OWN-1")

    with pytest.raises(HTTPException) as excinfo:
        await update_water(logged["entry_id"], WaterUpdateBody(amount_ml=5),
                           identity="ios:water-thief",
                           client_request_id="THIEF-1")
    assert excinfo.value.status_code == 404

    row = await db.get(WaterEntry, logged["entry_id"])
    await db.refresh(row)
    assert row.amount_ml == 500
    assert row.user_id == owner.id
