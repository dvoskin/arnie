"""What happened to this exact request — answerable from one line.

`core/turns/trace.py` times phases, but it is bound to the coordinator's
TurnState and the coordinator runs in `new_observe` in production, so the path
that actually executes emitted nothing from it. The REST write surfaces emitted
nothing at all: a tap-log that took four seconds, one that hit an idempotency
conflict, and one that worked left identical traces — none.

These pin the properties that make `event=request_done` worth grepping:

  * it carries the CANONICAL turn id, so the line joins `ledger_events.turn_id`
    for the same request without a correlation step
  * it names the build that served it, so "which deployment handled this" has
    an answer (the 130-turn blind spot in invariant I1 was exactly this,
    on the conversation side)
  * it records the idempotency outcome, which is the difference between "the
    user logged twice" and "the client retried once"
  * a FAILED request still leaves one — the failed request is the one someone
    is trying to explain
"""
import logging

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.quick_log import FoodLogBody, log_food_entry
from core.request_trace import RequestTrace


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


def _done_line(caplog) -> str:
    lines = [r.getMessage() for r in caplog.records
             if "event=request_done" in r.getMessage()]
    assert len(lines) == 1, f"expected exactly one summary line, got {lines}"
    return lines[0]


@pytest.mark.asyncio
async def test_a_tap_log_leaves_one_joinable_line(
    patched_session_local, db, make_user, caplog,
):
    await make_user(telegram_id="ios:trace")
    with caplog.at_level(logging.INFO):
        resp = await log_food_entry(
            FoodLogBody(food_name="Porridge", calories=200, protein=6,
                        carbs=36, fats=3),
            identity="ios:trace", client_request_id="TRACE-1",
        )

    line = _done_line(caplog)
    assert f"turn={resp['turn_id']}" in line, (
        "the trace must carry the canonical turn id — that is what joins it to "
        "the ledger event the same request wrote"
    )
    assert "channel=ios" in line and "command=log_food" in line
    assert "outcome=ok" in line
    assert "build=" in line, "the trace does not name the build that served it"
    assert "idempotency=claimed" in line
    assert "stages=" in line and "write:" in line


@pytest.mark.asyncio
async def test_a_replay_is_visible_as_a_replay(
    patched_session_local, db, make_user, caplog,
):
    """The line that distinguishes 'the client retried' from 'the user ate
    twice'. Without it, the two are indistinguishable in production."""
    await make_user(telegram_id="ios:trace-replay")
    body = FoodLogBody(food_name="Almonds", calories=170, protein=6,
                       carbs=6, fats=15)
    await log_food_entry(body, identity="ios:trace-replay",
                         client_request_id="TRACE-REPLAY")

    caplog.clear()
    with caplog.at_level(logging.INFO):
        await log_food_entry(body, identity="ios:trace-replay",
                             client_request_id="TRACE-REPLAY")

    assert "idempotency=replay" in _done_line(caplog)


@pytest.mark.asyncio
async def test_a_conflict_leaves_a_trace_too(
    patched_session_local, db, make_user, caplog,
):
    from fastapi import HTTPException

    await make_user(telegram_id="ios:trace-conflict")
    await log_food_entry(
        FoodLogBody(food_name="Rice", calories=200, protein=4, carbs=45, fats=0),
        identity="ios:trace-conflict", client_request_id="TRACE-CONFLICT")

    caplog.clear()
    with caplog.at_level(logging.INFO):
        with pytest.raises(HTTPException):
            await log_food_entry(
                FoodLogBody(food_name="Steak", calories=700, protein=60,
                            carbs=0, fats=50),
                identity="ios:trace-conflict",
                client_request_id="TRACE-CONFLICT")

    line = _done_line(caplog)
    assert "outcome=conflict" in line
    assert "IdempotencyConflict" in line


# ── the trace itself ─────────────────────────────────────────────────────────


def test_a_failing_stage_is_still_recorded(caplog):
    """The stage that raised is the one the reader is looking for."""
    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError):
            with RequestTrace(turn_id="t1", channel="ios",
                              command="log_food") as trace:
                with trace.stage("resolve"):
                    raise ValueError("boom")

    line = _done_line(caplog)
    assert "outcome=error:ValueError" in line
    assert "resolve:" in line, "the stage that raised was not timed"


def test_the_trace_never_raises_on_a_broken_field(caplog):
    """Telemetry describing a write must not break the write it describes."""
    class Hostile:
        def __str__(self): raise RuntimeError("unprintable")

    with caplog.at_level(logging.INFO):
        trace = RequestTrace(turn_id="t2", channel="ios", command="log_food")
        trace.note(bad=Hostile())
        trace.done()          # must not raise


def test_done_is_idempotent(caplog):
    """A handler that closes the trace and a `finally` that closes it again
    must not produce two summary lines for one request."""
    with caplog.at_level(logging.INFO):
        trace = RequestTrace(turn_id="t3", channel="ios", command="log_food")
        trace.done()
        trace.done(outcome="ignored")

    assert len([r for r in caplog.records
                if "event=request_done" in r.getMessage()]) == 1
