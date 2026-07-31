"""The ambient turn trace and its isolated write (B5).

The main pipeline never wrote to `turn_metrics`, so a p50 regression across a
deploy — the 2026-07-30 question — had no data. These pin the three parts of the
fix: a leaf records its own time on the ambient trace only when a turn is being
traced, the stages of a turn accumulate, and the metric row is written on a
SEPARATE session so it can never commit or roll back with the turn.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core import request_trace as RT
from core.request_trace import RequestTrace, active, timed, time_stage


# ── the ambient contextvar ───────────────────────────────────────────────────

def test_timed_is_a_noop_without_an_active_trace():
    assert RT.current_trace() is None
    with timed("llm"):        # must not raise, must record nothing
        pass
    assert RT.current_trace() is None


@pytest.mark.asyncio
async def test_leaf_records_only_inside_active_and_stages_sum():
    @time_stage("llm")
    async def model_call():
        await asyncio.sleep(0.005)

    @time_stage("tools")
    async def tool_batch():
        await asyncio.sleep(0.002)

    t = RequestTrace(turn_id="t", channel="ios", command="turn", user_id=1)
    with active(t):
        await model_call()
        await model_call()      # a second model call SUMS into one llm figure
        await tool_batch()
    totals = t.stage_totals()
    assert set(totals) == {"llm", "tools"}
    assert totals["llm"] >= totals["tools"]     # two llm calls vs one tool batch
    # ambient is restored after the block, so the next turn starts clean
    assert RT.current_trace() is None
    # off-path: the same decorated leaf runs and records nothing
    await model_call()
    assert t.stage_totals() == totals


@pytest.mark.asyncio
async def test_a_raising_leaf_records_once_and_propagates():
    calls = {"n": 0}

    @time_stage("llm")
    async def boom():
        calls["n"] += 1
        raise ValueError("model blew up")

    t = RequestTrace(turn_id="t", channel="ios", command="turn")
    with pytest.raises(ValueError):
        with active(t):
            await boom()
    assert calls["n"] == 1                 # NOT retried by the timer
    assert "llm" in t.stage_totals()       # its time was still recorded


# ── the isolated write ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_isolated_writes_a_row_with_summed_stages():
    from db.database import engine, Base, AsyncSessionLocal
    import db.models as m
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    t = RequestTrace(turn_id="tid-iso", channel="ios", command="turn", user_id=7)
    t.record("llm", 800)
    t.record("llm", 200)      # summed → 1000
    t.record("tools", 120)
    t.done(outcome="ok")
    await t.persist_isolated()

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(m.TurnMetric).where(m.TurnMetric.turn_id == "tid-iso"))
        ).scalar_one()
    import json
    assert row.channel == "ios" and row.command == "turn"
    assert json.loads(row.stages_json) == {"llm": 1000, "tools": 120}
    assert row.build_sha


# ── the run_turn wrapper end to end ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_turn_writes_a_metric_row_for_the_turn(monkeypatch):
    from db.database import engine, Base, AsyncSessionLocal
    import db.models as m
    import core.conversation as C
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    # A trivial _run_turn that "makes a model call" (records an llm stage the way
    # a real leaf would) and reports a food log, so the wrapper labels it turn:log.
    async def fake_run_turn(*a, **k):
        with timed("llm"):
            await asyncio.sleep(0.001)
        return SimpleNamespace(skills_fired="log_food")
    monkeypatch.setattr(C, "_run_turn", fake_run_turn)

    user = SimpleNamespace(id=42)
    result = await C.run_turn(user, object(), [], "SYS", "ios",
                              in_onboarding=False, was_onboarding=False,
                              turn_id="tid-wrap")
    assert result.skills_fired == "log_food"

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(m.TurnMetric).where(m.TurnMetric.turn_id == "tid-wrap"))
        ).scalar_one()
    assert row.command == "turn:log"       # skills_fired carried a log tool
    assert row.channel == "ios"
    assert row.outcome == "ok"
    assert row.total_ms >= 0


@pytest.mark.asyncio
async def test_run_turn_records_an_error_outcome_and_still_persists(monkeypatch):
    from db.database import engine, Base, AsyncSessionLocal
    import db.models as m
    import core.conversation as C
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async def boom_run_turn(*a, **k):
        raise RuntimeError("turn blew up")
    monkeypatch.setattr(C, "_run_turn", boom_run_turn)

    with pytest.raises(RuntimeError):
        await C.run_turn(SimpleNamespace(id=1), object(), [], "SYS", "telegram",
                         in_onboarding=False, was_onboarding=False,
                         turn_id="tid-err")

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(m.TurnMetric).where(m.TurnMetric.turn_id == "tid-err"))
        ).scalar_one()
    assert row.outcome == "error:RuntimeError"    # the failed turn is the one to explain
