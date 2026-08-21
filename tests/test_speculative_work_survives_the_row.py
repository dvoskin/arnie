"""⛔⛔ SPECULATIVE WORK MUST REACH THE ROW, NOT JUST THE OBJECT.

D2's contract says speculative work stays "visible, but never summed into the
turn's latency" — auditable, because it costs money and API budget and can
fail. The lifecycle D2 also documents is that the detached prewarm RUNS TO
COMPLETION after the response.

⛔ THOSE TWO STATEMENTS CONTRADICTED EACH OTHER. `persist_isolated()` writes
`turn_metrics.stages_json` when the turn ends. A prewarm finishing after that
appends its stage to the in-memory `RequestTrace` and to nothing else — the row
on disk never receives `speculative.pricing.*`. The code said that completion
was "simply dropped", which is honest about the mechanism and incompatible with
the contract built on top of it.

⭐ Either the row gets updated, or the contract has to say post-response
speculation is not durable. The second would mean D2 separated the domains and
then lost the half it separated out, so: the row gets updated.

The proof is deliberately about the ROW, reloaded from the database, because
that is the only thing a reader of `turn_metrics` ever sees.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.request_trace import RequestTrace, active as _trace_active, timed
from db.models import TurnMetric


@pytest_asyncio.fixture
async def isolated_sessions(monkeypatch, engine):
    """`persist_isolated` reaches for its own session; point that at the test
    engine so the row it writes is the row this test can reload."""
    import db.database as DB
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(DB, "AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_a_prewarm_that_finishes_after_the_row_still_reaches_it(
        isolated_sessions, db):
    """⛔⛔ THE DURABILITY BLOCKER, over the real row.

    1. start a deliberately slow speculative stage
    2. persist the trace BEFORE it completes — the documented lifecycle
    3. let it complete
    4. reload that exact row
    5. the namespaced speculative stage is there, and the critical path is
       byte-for-byte what it was
    """
    trace = RequestTrace(turn_id="d2:durable", channel="ios", command="turn")

    async def _slow_speculative():
        from core.request_trace import speculative
        with _trace_active(trace), speculative():
            with timed("pricing.qualification"):
                await asyncio.sleep(0.15)
        await trace.flush_speculative()

    task = asyncio.ensure_future(_slow_speculative())

    with _trace_active(trace):
        with timed("llm"):
            await asyncio.sleep(0.01)
    critical_at_persist = dict(trace.stage_totals())
    await trace.persist_isolated()          # the turn ends here

    await task                              # the prewarm finishes afterwards

    row = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "d2:durable")
    )).scalars().one()
    stages = row.stages_json
    if isinstance(stages, str):
        import json
        stages = json.loads(stages)

    assert "speculative.pricing.qualification" in stages, (
        "the prewarm completed after the row was written and never reached it: "
        "%r — D2 claims speculative work stays auditable in the persisted row"
        % (stages,))
    for name, ms in critical_at_persist.items():
        assert stages.get(name) == ms, (
            "the late update changed the critical path: %s was %r, row says %r"
            % (name, ms, stages.get(name)))
    assert not any(k.startswith("speculative.") and k in critical_at_persist
                   for k in stages), "a speculative key leaked into the critical path"


@pytest.mark.asyncio
async def test_one_row_per_turn_survives_the_late_update(isolated_sessions, db):
    """⭐ THE GUARD ON THE FIX. Updating the row late must UPDATE it, not insert
    a second one — D1 exists because one request writing two `turn_metrics`
    rows is exactly how a turn reads as two."""
    trace = RequestTrace(turn_id="d2:one-row", channel="ios", command="turn")
    with _trace_active(trace):
        with timed("llm"):
            await asyncio.sleep(0.01)
    await trace.persist_isolated()

    from core.request_trace import speculative
    with _trace_active(trace), speculative():
        with timed("pricing.qualification"):
            await asyncio.sleep(0.01)
    await trace.flush_speculative()

    rows = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "d2:one-row")
    )).scalars().all()
    assert len(rows) == 1, (
        "the late speculative update inserted a SECOND turn_metrics row (%d) — "
        "that is the D1 defect arriving through the D2 fix" % len(rows))


@pytest.mark.asyncio
async def test_flushing_before_the_row_exists_is_harmless(isolated_sessions, db):
    """A prewarm can finish BEFORE the turn does — the ordinary fast case. The
    flush must then do nothing and leave the normal persist to carry it, rather
    than inserting a row of its own or raising into a detached task nobody
    awaits."""
    trace = RequestTrace(turn_id="d2:early", channel="ios", command="turn")
    from core.request_trace import speculative
    with _trace_active(trace), speculative():
        with timed("pricing.qualification"):
            await asyncio.sleep(0.01)
    await trace.flush_speculative()          # no row yet

    rows = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "d2:early")
    )).scalars().all()
    assert rows == [], "flush_speculative inserted a row before the turn ended"

    await trace.persist_isolated()
    row = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "d2:early")
    )).scalars().one()
    stages = row.stages_json
    if isinstance(stages, str):
        import json
        stages = json.loads(stages)
    assert "speculative.pricing.qualification" in stages, (
        "a prewarm that finished in time did not make the normal persist")
