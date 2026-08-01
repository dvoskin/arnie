"""An edit is a turn — the iOS exercise editor on the mutation contract.

This surface was not silent like water: it already recorded `updated` and
`deleted` events through `record_surface_mutation`. What it did not have was
identity or atomicity.

  * The event was written in a SECOND commit, after the row's write had
    already committed. A process that dies between them leaves a changed row
    whose previous values exist nowhere — an edit that cannot be rolled back
    and never appears in the audit trail.
  * `record_surface_mutation` minted a synthetic turn id from
    `(surface, event_type, entry_id)`. That is STABLE, not unique: every edit
    of entry 41 shared the id `ios_edit:updated:41`, so the turn↔operation
    join could not tell one edit from another, or from an edit made a week
    later.
  * A retried PATCH re-applied the edit and wrote a second event.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.exercise_edit import (
    ExerciseUpdateBody,
    delete_exercise,
    update_exercise,
)
from api.quick_log import ExerciseLogBody, log_exercise_entry
from db.models import ExerciseEntry, LedgerEvent


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import exercise_edit, quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(exercise_edit, "AsyncSessionLocal", factory)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


async def _events(db, user_id, event_type=None):
    q = select(LedgerEvent).where(LedgerEvent.user_id == user_id,
                                  LedgerEvent.domain == "exercise")
    if event_type:
        q = q.where(LedgerEvent.event_type == event_type)
    return (await db.execute(q.order_by(LedgerEvent.id))).scalars().all()


async def _log_one(identity, key="SEED", name="Back squat"):
    return await log_exercise_entry(
        ExerciseLogBody(exercise_name=name, sets=3, reps="5,5,5", weight=100.0),
        identity=identity, client_request_id=key)


# ── the edit names the turn that made it ─────────────────────────────────────


@pytest.mark.asyncio
async def test_an_edit_event_carries_the_requests_turn_id(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:ex-edit-turn")
    logged = await _log_one("ios:ex-edit-turn")

    await update_exercise(logged["entry_id"], ExerciseUpdateBody(sets=4),
                          identity="ios:ex-edit-turn",
                          client_request_id="EDIT-TURN-1")

    events = await _events(db, user.id, "updated")
    assert len(events) == 1
    assert events[0].turn_id == "ios:EDIT-TURN-1", (
        f"the edit event carries {events[0].turn_id!r} — a synthetic id "
        f"derived from the row, not the turn the request actually was"
    )


@pytest.mark.asyncio
async def test_two_edits_of_one_row_are_two_distinguishable_turns(
    patched_session_local, db, make_user,
):
    """The defect the synthetic id caused, stated as behaviour.

    `ios_edit:updated:{entry_id}` is stable, so N edits of one row all claimed
    the same turn. The join could not answer "which request changed this to
    5 sets" once a second edit existed.
    """
    user = await make_user(telegram_id="ios:ex-two-edits")
    logged = await _log_one("ios:ex-two-edits")

    await update_exercise(logged["entry_id"], ExerciseUpdateBody(sets=4),
                          identity="ios:ex-two-edits",
                          client_request_id="E1")
    await update_exercise(logged["entry_id"], ExerciseUpdateBody(sets=5),
                          identity="ios:ex-two-edits",
                          client_request_id="E2")

    turns = [e.turn_id for e in await _events(db, user.id, "updated")]
    assert len(turns) == 2
    assert len(set(turns)) == 2, (
        f"both edits claim the same turn id {turns} — the turn↔operation join "
        f"cannot tell them apart"
    )


@pytest.mark.asyncio
async def test_the_edit_event_holds_the_before_state(
    patched_session_local, db, make_user,
):
    import json

    user = await make_user(telegram_id="ios:ex-before")
    logged = await _log_one("ios:ex-before")

    await update_exercise(logged["entry_id"], ExerciseUpdateBody(sets=4),
                          identity="ios:ex-before", client_request_id="B1")

    payload = json.loads((await _events(db, user.id, "updated"))[0].payload_json)
    assert payload["before"]["sets"] == 3, (
        "without the previous value the edit cannot be rolled back"
    )


@pytest.mark.asyncio
async def test_a_delete_event_carries_its_turn_and_stays_restorable(
    patched_session_local, db, make_user,
):
    import json

    user = await make_user(telegram_id="ios:ex-del")
    logged = await _log_one("ios:ex-del", key="DEL-SEED")

    await delete_exercise(logged["entry_id"], identity="ios:ex-del",
                          client_request_id="DEL-T1")

    events = await _events(db, user.id, "deleted")
    assert len(events) == 1
    assert events[0].turn_id == "ios:DEL-T1"
    payload = json.loads(events[0].payload_json)
    assert payload.get("exercise_name") == "Back squat", (
        "a deleted event with no payload describes a row that no longer "
        "exists — nothing can restore it"
    )


# ── a retried edit is applied once ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_replayed_edit_writes_one_event(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:ex-retry")
    logged = await _log_one("ios:ex-retry", key="R-SEED")

    first = await update_exercise(logged["entry_id"],
                                  ExerciseUpdateBody(sets=4),
                                  identity="ios:ex-retry",
                                  client_request_id="RETRY-E")
    second = await update_exercise(logged["entry_id"],
                                   ExerciseUpdateBody(sets=4),
                                   identity="ios:ex-retry",
                                   client_request_id="RETRY-E")

    assert second.get("idempotent_replay") is True
    assert second["entry"]["sets"] == first["entry"]["sets"]
    assert len(await _events(db, user.id, "updated")) == 1, (
        "the retry recorded a second `updated` event — history shows two "
        "corrections the user made once"
    )


@pytest.mark.asyncio
async def test_a_replayed_delete_reports_the_original_success(
    patched_session_local, db, make_user,
):
    await make_user(telegram_id="ios:ex-del-retry")
    logged = await _log_one("ios:ex-del-retry", key="DR-SEED")

    first = await delete_exercise(logged["entry_id"],
                                  identity="ios:ex-del-retry",
                                  client_request_id="DR-E")
    second = await delete_exercise(logged["entry_id"],
                                   identity="ios:ex-del-retry",
                                   client_request_id="DR-E")

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_a_failed_edit_leaves_the_row_alone(
    patched_session_local, db, make_user,
):
    """Ownership scoping survives the rewrite: the claim is taken before the
    row is read, and a rejected edit must not have changed anything."""
    from fastapi import HTTPException

    await make_user(telegram_id="ios:ex-owner")
    await make_user(telegram_id="ios:ex-thief")
    logged = await _log_one("ios:ex-owner", key="OWN-SEED")

    with pytest.raises(HTTPException) as excinfo:
        await update_exercise(logged["entry_id"],
                              ExerciseUpdateBody(sets=99),
                              identity="ios:ex-thief",
                              client_request_id="THIEF-E")
    assert excinfo.value.status_code in (403, 404)

    row = await db.get(ExerciseEntry, logged["entry_id"])
    await db.refresh(row)
    assert row.sets == 3


# ── the fallback turn id never overrides a real one ──────────────────────────


@pytest.mark.asyncio
async def test_a_surface_mutation_keeps_an_already_canonical_turn_id(db, make_user):
    """`record_surface_mutation` used to `CURRENT_TURN_ID.set(...)`
    unconditionally.

    Every surface that moves onto the contract sets the canonical id and then
    calls helpers that reach this function — which would overwrite it, so the
    surface would look migrated while its events stayed unjoinable. The
    synthetic id is a floor for surfaces with no identity of their own, never
    an override.
    """
    from api.quick_log import _turn_scope
    from db.queries import record_surface_mutation

    user = await make_user(telegram_id="ios:surface-turn")

    with _turn_scope("ios:REAL-TURN"):
        await record_surface_mutation(
            db, user.id, "updated", domain="water", entry_id=41,
            payload={"amount_ml": 100}, surface="ios_edit")

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].turn_id == "ios:REAL-TURN", (
        f"the canonical turn id was overwritten with {events[0].turn_id!r}"
    )


@pytest.mark.asyncio
async def test_a_surface_mutation_restores_the_turn_id_it_set(db, make_user):
    """It ran mid-request and left its synthetic id behind, so every LATER
    write in the same request was stamped with it."""
    from core.turn_identity import CURRENT_TURN_ID
    from db.queries import record_surface_mutation

    user = await make_user(telegram_id="ios:surface-reset")
    assert CURRENT_TURN_ID.get() is None

    await record_surface_mutation(
        db, user.id, "updated", domain="water", entry_id=7,
        payload={"amount_ml": 100}, surface="dashboard")

    assert CURRENT_TURN_ID.get() is None, (
        f"a synthetic turn id was left set ({CURRENT_TURN_ID.get()!r}) — the "
        f"next write in this request inherits it"
    )
