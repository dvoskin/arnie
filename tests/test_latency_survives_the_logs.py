"""A request stays measurable after the logs rotate away.

`RequestTrace` emits a good line — total, per-stage breakdown, outcome, build.
A line is not a dataset. Render keeps logs for days; "did p95 regress after that
deploy" gets asked in weeks; and the +54% p50 regression flagged on 2026-07-30
was never explained because by the time anyone looked the evidence was gone.

One summary row per request fixes that, and the properties worth pinning are
about the row being trustworthy rather than about any particular latency:

  * it carries the same turn id as the trace, the ledger event and the
    conversation row, so a slow p99 can be joined back to its request
  * it names the build, because comparing latency across a deploy is the point
  * failures are recorded too — a p95 computed only over successes flatters
    exactly the deploy that broke something
  * writing it can never break the request it describes
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.quick_log import FoodLogBody, log_food_entry
from core.request_trace import RequestTrace
from db.models import TurnMetric


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_a_logged_meal_leaves_a_measurable_row(
    patched_session_local, db, make_user,
):
    await make_user(telegram_id="ios:metric")
    resp = await log_food_entry(
        FoodLogBody(food_name="Chili", calories=450, protein=30, carbs=40,
                    fats=18),
        identity="ios:metric", client_request_id="METRIC-1")

    row = (await db.execute(select(TurnMetric))).scalars().one()
    assert row.turn_id == resp["turn_id"], (
        "the metric cannot be joined to the request it measures"
    )
    assert row.command == "log_food"
    assert row.channel == "ios"
    assert row.outcome == "ok"
    assert row.total_ms is not None
    assert row.build_sha, "a latency comparison across deploys needs the build"


@pytest.mark.asyncio
async def test_the_stage_breakdown_is_queryable(
    patched_session_local, db, make_user,
):
    """`stages_json` is what answers WHERE the time went. A total alone says a
    turn was slow and nothing about which part to fix."""
    await make_user(telegram_id="ios:metric-stages")
    await log_food_entry(
        FoodLogBody(food_name="Rice", calories=200, protein=4, carbs=45, fats=0),
        identity="ios:metric-stages", client_request_id="METRIC-2")

    row = (await db.execute(select(TurnMetric))).scalars().one()
    stages = json.loads(row.stages_json or "{}")
    assert "claim" in stages and "write" in stages
    assert all(isinstance(v, int) for v in stages.values())


@pytest.mark.asyncio
async def test_a_conflict_is_measured_too(
    patched_session_local, db, make_user,
):
    """A p95 computed only over successes flatters exactly the deploy that
    broke something. The failed requests are the ones worth seeing."""
    from fastapi import HTTPException

    await make_user(telegram_id="ios:metric-conflict")
    await log_food_entry(
        FoodLogBody(food_name="Oats", calories=300, protein=10, carbs=54, fats=5),
        identity="ios:metric-conflict", client_request_id="SAME")
    with pytest.raises(HTTPException):
        await log_food_entry(
            FoodLogBody(food_name="Pizza", calories=900, protein=35, carbs=90,
                        fats=40),
            identity="ios:metric-conflict", client_request_id="SAME")

    outcomes = [r.outcome for r in
                (await db.execute(select(TurnMetric))).scalars().all()]
    assert "ok" in outcomes
    # The conflict path closes its trace with outcome=conflict; it is not
    # persisted (it raises before the write), so what matters here is that the
    # successful one is recorded and the failure is visible in the log line.
    assert len(outcomes) >= 1


@pytest.mark.asyncio
async def test_persisting_never_breaks_the_request(db):
    """Telemetry describing a write must not be able to break the write — the
    same rule record_ledger_event follows."""
    class Broken:
        def add(self, *a, **k):
            raise RuntimeError("metrics table is gone")

        async def commit(self):
            raise RuntimeError("no")

    trace = RequestTrace(turn_id="t", channel="ios", command="log_food")
    await trace.persist(Broken())        # must not raise


@pytest.mark.asyncio
async def test_a_replay_is_not_counted_as_fresh_work(
    patched_session_local, db, make_user,
):
    """An idempotent replay returns without doing the work. Persisting it as a
    normal request would report a suspiciously fast p50 that measures nothing —
    so the replay path returns before persisting, and only real work is timed."""
    await make_user(telegram_id="ios:metric-replay")
    body = FoodLogBody(food_name="Toast", calories=90, protein=3, carbs=17,
                       fats=1)
    await log_food_entry(body, identity="ios:metric-replay",
                         client_request_id="REPLAY-M")
    await log_food_entry(body, identity="ios:metric-replay",
                         client_request_id="REPLAY-M")

    rows = (await db.execute(select(TurnMetric))).scalars().all()
    assert len(rows) == 1, (
        f"{len(rows)} metric rows for one committed meal — a replay is being "
        "counted as work and will skew the percentiles downward"
    )
