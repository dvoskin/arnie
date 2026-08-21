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


# ══════════════════════════════════════════════════════════════════════════
# POST-MERGE REMEDIATION — two defects the durability fix introduced
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_prewarm_finishing_while_persist_is_in_flight_is_not_lost(
        isolated_sessions, db):
    """⛔⛔ THE PERSIST-IN-FLIGHT RACE.

    `flush_speculative()` returns early unless `_persisted` is set, and
    `persist()` sets it only AFTER its commit. A prewarm completing inside that
    window is dropped by BOTH paths: too late for `_stages_for_row()` to have
    seen it, too early for the flush to act.

    The window is narrow, which is the point — the contract this fix exists to
    honour fails precisely when the timing is tightest, and a narrow window on
    a fire-and-forget task is not a rare event, it is an ordinary one.

    Simulated deterministically by recording the stage between the row being
    built and `_persisted` being set."""
    trace = RequestTrace(turn_id="d2:race", channel="ios", command="turn")
    with _trace_active(trace):
        with timed("llm"):
            await asyncio.sleep(0.01)

    real_stages_for_row = trace._stages_for_row
    raced = {}

    def _stages_then_race():
        out = real_stages_for_row()
        # The prewarm completes HERE — after the row's payload is built and
        # before `_persisted` becomes True — and calls the flush, exactly as
        # the detached task's `finally` does. `persist` awaits its commit
        # after this, so the queued flush genuinely runs inside the window
        # rather than being simulated around it.
        trace.record_speculative("pricing.qualification", 42)
        raced["task"] = asyncio.ensure_future(trace.flush_speculative())
        return out

    trace._stages_for_row = _stages_then_race
    await trace.persist_isolated()
    trace._stages_for_row = real_stages_for_row
    await raced["task"]

    row = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "d2:race")
    )).scalars().one()
    stages = row.stages_json
    if isinstance(stages, str):
        import json
        stages = json.loads(stages)
    assert "speculative.pricing.qualification" in stages, (
        "a prewarm that completed while persist was in flight was dropped by "
        "both paths: %r" % (stages,))


@pytest.mark.asyncio
async def test_the_flush_updates_ITS_row_not_the_latest_sharing_a_turn_id(
        isolated_sessions, db):
    """⛔⛔ "LATEST ROW BY turn_id" MISATTRIBUTION.

    The flush selects `WHERE turn_id = … ORDER BY id DESC LIMIT 1`. ⭐ turn_id
    IS NOT UNIQUE, and this repository registers that as CF19: `h:`-prefixed
    ids are a content hash bucketed by the hour, so genuinely separate requests
    share one — a single `healthkit:h:` id covers six executions in production.

    Keying the update on that field means one request's speculative stage can
    land in a DIFFERENT request's row. Using the very field CF19 names as
    ambiguous is the defect; the fix is to remember which row this trace
    actually wrote."""
    shared = "ios:h:abc123sharedbucket"

    first = RequestTrace(turn_id=shared, channel="ios", command="turn")
    with _trace_active(first):
        with timed("llm"):
            await asyncio.sleep(0.01)
    await first.persist_isolated()

    second = RequestTrace(turn_id=shared, channel="ios", command="turn")
    with _trace_active(second):
        with timed("llm"):
            await asyncio.sleep(0.01)
    await second.persist_isolated()

    # the FIRST request's prewarm finishes last — as a slow one would
    from core.request_trace import speculative
    with _trace_active(first), speculative():
        with timed("pricing.qualification"):
            await asyncio.sleep(0.01)
    await first.flush_speculative()

    rows = (await db.execute(
        select(TurnMetric).where(TurnMetric.turn_id == shared)
        .order_by(TurnMetric.id)
    )).scalars().all()
    assert len(rows) == 2, "precondition: two rows share this turn id"

    import json
    def _stages(r):
        s = r.stages_json
        return json.loads(s) if isinstance(s, str) else (s or {})

    assert "speculative.pricing.qualification" in _stages(rows[0]), (
        "the first request's speculative stage did not reach its OWN row")
    assert "speculative.pricing.qualification" not in _stages(rows[1]), (
        "the first request's speculative stage was folded into the SECOND "
        "request's row — turn_id is not unique (CF19) and must not key this "
        "update: %r" % (_stages(rows[1]),))
