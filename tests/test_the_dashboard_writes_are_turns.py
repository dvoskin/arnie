"""The dashboard surfaces owe the same contract as the iOS ones.

Same data, same helpers, different auth — a meal logged from the web
dashboard and one tapped in the app land in the same rows, so a duplicate or
an untraceable write costs the user exactly as much either way. Before B2
none of these ten routes took an idempotency claim, and most recorded their
ledger event in a second commit after the row was already durable.

Two of them were worse than that. `PATCH /api/water/{entry_id}` wrote no
ledger event at all — the same defect as the iOS water lane, where "undo
that" after an untracked mutation reached past it to a row the user never
mentioned. And `POST /api/water/log` recorded its event through
`record_surface_mutation`, which minted a synthetic turn id derived from the
entry, so the pour could not be joined to the request that made it.

The concurrency cases here are what the inventory counts as the Class A
`concurrency_test` guarantee for these routes.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import api.app as A
from db.models import FoodEntry, LedgerEvent, WaterEntry

TOKEN = "tok-dash"


@pytest_asyncio.fixture
async def dash(monkeypatch, engine, db, make_user):
    """A dashboard user, their token, and app.py pointed at the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(A, "AsyncSessionLocal", factory)

    async def _noop(*a, **k):
        return None
    # The handlers fire this on a background task; it reaches the network.
    monkeypatch.setattr(A, "_send_dashboard_notification", _noop)
    monkeypatch.setattr(A, "resolve_send_target", _noop)

    user = await make_user(telegram_id="dash:1")
    user.webhook_token = TOKEN
    await db.commit()
    return user


async def _events(db, user_id, domain, event_type=None):
    q = select(LedgerEvent).where(LedgerEvent.user_id == user_id,
                                  LedgerEvent.domain == domain)
    if event_type:
        q = q.where(LedgerEvent.event_type == event_type)
    return (await db.execute(q.order_by(LedgerEvent.id))).scalars().all()


# ── the pour that had no history ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_dashboard_pour_records_a_created_event_on_its_own_turn(
    dash, db,
):
    out = await A.api_log_water(A.WaterLogBody(amount_ml=500), token=TOKEN,
                                client_request_id="DW-1")
    events = await _events(db, dash.id, "water", "created")
    assert len(events) == 1
    assert events[0].turn_id == "dashboard:DW-1", (
        f"the pour's event carries {events[0].turn_id!r} — a synthetic id, not "
        f"the request that made it")
    assert out["turn_id"] == "dashboard:DW-1"


@pytest.mark.asyncio
async def test_a_dashboard_water_edit_records_an_event_at_all(dash, db):
    """This surface wrote none. `ledger_undo` takes the last event
    unconditionally, so an unrecorded edit is invisible to undo."""
    logged = await A.api_log_water(A.WaterLogBody(amount_ml=500), token=TOKEN,
                                   client_request_id="DW-BASE")
    await A.api_edit_water(logged["id"], A.WaterPatch(amount_ml=750),
                           token=TOKEN, client_request_id="DW-EDIT")

    updated = await _events(db, dash.id, "water", "updated")
    assert len(updated) == 1, "the dashboard water edit left no history"
    assert updated[0].turn_id == "dashboard:DW-EDIT"


# ── replay ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_replayed_dashboard_food_log_writes_one_row(dash, db):
    body = A.FoodLogBody(name="Pad thai", calories=700, protein=25, carbs=90,
                         fats=25)
    first = await A.api_log_food(body, token=TOKEN, client_request_id="DF-1")
    second = await A.api_log_food(body, token=TOKEN, client_request_id="DF-1")

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Pad thai")
    )).scalars().all()
    assert len(rows) == 1, "a replayed dashboard log wrote a duplicate row"
    assert second["id"] == first["id"]
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_a_replayed_dashboard_delete_reports_the_original_success(
    dash, db,
):
    logged = await A.api_log_water(A.WaterLogBody(amount_ml=250), token=TOKEN,
                                   client_request_id="DD-BASE")
    first = await A.api_delete_water(logged["id"], token=TOKEN,
                                     client_request_id="DD-1")
    second = await A.api_delete_water(logged["id"], token=TOKEN,
                                      client_request_id="DD-1")
    assert first["status"] == "ok" and second["status"] == "ok"
    assert second.get("idempotent_replay") is True
    assert len(await _events(db, dash.id, "water", "deleted")) == 1


@pytest.mark.asyncio
async def test_two_different_dashboard_logs_are_not_deduplicated(dash, db):
    """The failure the contract must NOT cause."""
    await A.api_log_water(A.WaterLogBody(amount_ml=500), token=TOKEN,
                          client_request_id="G1")
    await A.api_log_water(A.WaterLogBody(amount_ml=500), token=TOKEN,
                          client_request_id="G2")
    rows = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == dash.id)
    )).scalars().all()
    assert len(rows) == 2, "two real glasses collapsed into one row"


# ── concurrency: the Class A guarantee for these routes ─────────────────────


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_food_logs_write_one_row(dash, db):
    from fastapi import HTTPException

    body = A.FoodLogBody(name="Katsu curry", calories=800, protein=30,
                         carbs=95, fats=30)
    results = await asyncio.gather(
        A.api_log_food(body, token=TOKEN, client_request_id="RACE-DF"),
        A.api_log_food(body, token=TOKEN, client_request_id="RACE-DF"),
        return_exceptions=True,
    )
    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Katsu curry")
    )).scalars().all()
    assert len(rows) == 1, f"the race wrote {len(rows)} rows ({results})"
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
        if isinstance(r, HTTPException):
            assert r.status_code == 409


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_edits_apply_once(dash, db):
    from fastapi import HTTPException

    logged = await A.api_log_water(A.WaterLogBody(amount_ml=500), token=TOKEN,
                                   client_request_id="RE-BASE")
    results = await asyncio.gather(
        A.api_edit_water(logged["id"], A.WaterPatch(amount_ml=900),
                         token=TOKEN, client_request_id="RACE-DE"),
        A.api_edit_water(logged["id"], A.WaterPatch(amount_ml=900),
                         token=TOKEN, client_request_id="RACE-DE"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, dash.id, "water", "updated")) == 1


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_food_edits_apply_once(dash, db):
    from fastapi import HTTPException

    logged = await A.api_log_food(
        A.FoodLogBody(name="Ramen", calories=600, protein=25, carbs=70,
                      fats=22),
        token=TOKEN, client_request_id="FE-BASE")
    results = await asyncio.gather(
        A.api_edit_food(logged["id"], A.FoodPatch(calories=800), token=TOKEN,
                        client_request_id="RACE-FE"),
        A.api_edit_food(logged["id"], A.FoodPatch(calories=800), token=TOKEN,
                        client_request_id="RACE-FE"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, dash.id, "food", "updated")) == 1


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_deletes_remove_one_row_once(dash, db):
    from fastapi import HTTPException

    logged = await A.api_log_food(
        A.FoodLogBody(name="Gyoza", calories=300, protein=12, carbs=30,
                      fats=14),
        token=TOKEN, client_request_id="RD-BASE")
    results = await asyncio.gather(
        A.api_delete_food(logged["id"], token=TOKEN,
                          client_request_id="RACE-DD"),
        A.api_delete_food(logged["id"], token=TOKEN,
                          client_request_id="RACE-DD"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, dash.id, "food", "deleted")) == 1


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_weigh_ins_record_one_metric(dash, db):
    """Weight upserts one row per (user, day, source), so the row count was
    never the risk here — the EVENT count was, and a second `created` event
    makes one weigh-in look like two operations."""
    from fastapi import HTTPException

    results = await asyncio.gather(
        A.api_log_weight(A.WeightLogBody(weight=180.0), token=TOKEN,
                         client_request_id="RACE-DW"),
        A.api_log_weight(A.WeightLogBody(weight=180.0), token=TOKEN,
                         client_request_id="RACE-DW"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, dash.id, "weight")) == 1


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_exercise_logs_write_one_row(dash, db):
    from fastapi import HTTPException

    from db.models import ExerciseEntry

    body = A.ExerciseLogBody(name="Front squat", sets=3, reps="5,5,5",
                             weight_lbs=185.0)
    results = await asyncio.gather(
        A.api_log_exercise(body, token=TOKEN, client_request_id="RACE-DX"),
        A.api_log_exercise(body, token=TOKEN, client_request_id="RACE-DX"),
        return_exceptions=True,
    )
    rows = (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.exercise_name == "Front squat")
    )).scalars().all()
    assert len(rows) <= 1, f"the race wrote {len(rows)} rows ({results})"
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_exercise_edits_apply_once(dash, db):
    from fastapi import HTTPException

    logged = await A.api_log_exercise(
        A.ExerciseLogBody(name="Row", sets=3, reps="10,10,10",
                          weight_lbs=100.0),
        token=TOKEN, client_request_id="XE-BASE")
    results = await asyncio.gather(
        A.api_edit_exercise(logged["id"], A.ExercisePatch(sets=4), token=TOKEN,
                            client_request_id="RACE-XE"),
        A.api_edit_exercise(logged["id"], A.ExercisePatch(sets=4), token=TOKEN,
                            client_request_id="RACE-XE"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, dash.id, "exercise", "updated")) == 1


@pytest.mark.asyncio
async def test_two_concurrent_dashboard_exercise_deletes_apply_once(dash, db):
    from fastapi import HTTPException

    logged = await A.api_log_exercise(
        A.ExerciseLogBody(name="Curl", sets=3, reps="12,12,12",
                          weight_lbs=30.0),
        token=TOKEN, client_request_id="XD-BASE")
    results = await asyncio.gather(
        A.api_delete_exercise(logged["id"], token=TOKEN,
                              client_request_id="RACE-XD"),
        A.api_delete_exercise(logged["id"], token=TOKEN,
                              client_request_id="RACE-XD"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, dash.id, "exercise", "deleted")) == 1


@pytest.mark.asyncio
async def test_two_concurrent_tap_log_weigh_ins_record_one_event(
    monkeypatch, engine, db, make_user,
):
    """`/api/v1/weight` — the last quick_log route without concurrency proof."""
    from fastapi import HTTPException

    from api import quick_log
    from api.quick_log import WeightLogBody, log_weight

    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    user = await make_user(telegram_id="ios:weight-race")

    results = await asyncio.gather(
        log_weight(WeightLogBody(weight_kg=82.5), identity="ios:weight-race",
                   client_request_id="RACE-W1"),
        log_weight(WeightLogBody(weight_kg=82.5), identity="ios:weight-race",
                   client_request_id="RACE-W1"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"
    assert len(await _events(db, user.id, "weight")) == 1
