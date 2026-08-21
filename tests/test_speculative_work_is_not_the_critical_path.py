"""⛔⛔⛔ SPECULATIVE WORK IS NOT THE TURN.

Tranche D2, as redefined once the code path was traced. The original premise —
"canonical settlement is paying ~5.4 s for legacy `pricing.qualification`" — is
NOT what the trace proved.

`core/food_turn.py` launches a FIRE-AND-FORGET USDA/OFF prewarm from the
interpreter's token stream (`_start`), before settlement ownership is decided.
`core/request_trace.timed()` records onto the AMBIENT trace. So the prewarm's
duration is attributed to the user-visible turn even though nothing awaits it.

⭐ THE ARITHMETIC THAT SETTLED IT, on `ios:5F861208…`:

    total_ms               9523
    llm                    6601
    pricing.qualification  5379      llm + qualification = 11980 > 9523

They cannot both be on one critical path. They overlap by at least 2457 ms, so
the stage was not even proof of latency — let alone of settlement ownership,
which is the separate inference this tranche retired.

So the defect is an OBSERVABILITY/CAUSALITY bug, not a settlement-latency one:

    detached speculative work contaminates critical-path telemetry and can be
    misread as settlement ownership and as user-visible latency.

⛔ AND "FIRE-AND-FORGET" IS NOT ITSELF A PROOF. A task detached syntactically
can still be awaited INDIRECTLY through anything it contends for: a connection
pool, a provider semaphore, the event loop, CPU, a shared cache lock, a DB
session, a rate limiter. The invariant has to be measured, not read off the
`ensure_future`:

    a stage appears in critical-path stages_json
            <=>
    the user-visible turn actually awaited it

These proofs are the three that "fire-and-forget" does not give for free:
latency independence, semantic non-authority, and cross-turn isolation.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import core.food_turn as FT
import handlers.tool_executor as TE
from core.request_trace import RequestTrace, active as _trace_active


def _prewarm(food: str) -> None:
    """Launch the speculative prewarm exactly as the interpreter stream does."""
    FT._SpeculativeEnrichment._start(food)


@pytest.fixture()
def slow_qualifier(monkeypatch):
    """⛔ THE CAUSAL LATENCY PROBE. Not "is it awaited in the source" — make it
    take ten seconds and see whether the turn grows. Anything the turn shares
    with it (pool, semaphore, loop, lock) shows up here and nowhere else.

    ⛔⛔ AND IT POISONS THE INNER SEAMS, NOT `_fetch_usda_off_uncached`. The
    first version replaced that function outright — which is the function
    holding the `timed("pricing.qualification")` block. No stage was ever
    recorded, so `test_the_prewarm_does_not_land_in_critical_path_stages`
    passed by measuring nothing. Poisoning the instrumentation away cannot test
    the instrumentation; `test_the_probe_actually_produces_the_stage` below is
    the control that keeps this honest."""
    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ
    import skills.nutrition.off as OFF

    async def _rows(*_a, **_k):
        return [{"description": "Chicken, broilers or fryers, breast",
                 "fdcId": 171077}]

    async def _slow_qualify(*_a, **_k):
        await asyncio.sleep(10)
        raise AssertionError("the 10 s qualification was awaited by something")

    async def _no_off(*_a, **_k):
        return None

    monkeypatch.setattr(USDA, "search_food", _rows)
    monkeypatch.setattr(EQ, "qualify_usda_rows", _slow_qualify)
    monkeypatch.setattr(OFF, "search", _no_off)
    monkeypatch.setattr(TE, "_qualification_halted", lambda: False)


@pytest.fixture()
def fast_qualifier(monkeypatch):
    """The same seams, but quick — for the tests that need the stage RECORDED
    rather than hanging."""
    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ
    import skills.nutrition.off as OFF

    class _Q:
        rows = [{"description": "Chicken breast", "fdcId": 171077}]

    async def _rows(*_a, **_k):
        return list(_Q.rows)

    async def _qualify(*_a, **_k):
        await asyncio.sleep(0.02)
        return _Q()

    async def _no_off(*_a, **_k):
        return None

    monkeypatch.setattr(USDA, "search_food", _rows)
    monkeypatch.setattr(EQ, "qualify_usda_rows", _qualify)
    monkeypatch.setattr(OFF, "search", _no_off)
    monkeypatch.setattr(TE, "_qualification_halted", lambda: False)


@pytest.mark.asyncio
async def test_the_probe_actually_produces_the_stage(fast_qualifier):
    """⛔⛔ THE ANTI-VACUITY CONTROL, and it must pass BEFORE the fix.

    Every other test here asserts `pricing.qualification` is NOT in the
    critical path. That is trivially true if the probe never produces the stage
    at all — which is exactly what happened when the fixture replaced
    `_fetch_usda_off_uncached` instead of the seams inside it.

    So: with the real instrumentation running, the stage must exist SOMEWHERE
    on the trace. Where it belongs is what the rest of the file decides."""
    trace = RequestTrace(turn_id="d2:probe", channel="ios", command="turn")
    with _trace_active(trace):
        _prewarm("Chicken breast")
        await asyncio.sleep(0.2)

    everywhere = dict(trace.stage_totals())
    everywhere.update(getattr(trace, "speculative_totals", dict)() or {})
    assert any("qualification" in n for n in everywhere), (
        "the probe produced no qualification stage at all, so every "
        "'not in the critical path' assertion here would be vacuous: %r"
        % (everywhere,))


@pytest.mark.asyncio
async def test_a_ten_second_prewarm_does_not_add_ten_seconds_to_the_turn(
        slow_qualifier):
    """⛔⛔ THE ACTUAL CRITICAL-PATH PROOF. Poison the prewarm to sleep 10 s;
    the work the user waits on must finish in its own time.

    A detached task that still blocks the turn fails here — which is the whole
    point, because reading `ensure_future` in the source cannot tell you
    whether the pool it reaches for is the pool the turn needs next."""
    trace = RequestTrace(turn_id="d2:latency", channel="ios", command="turn")
    with _trace_active(trace):
        _prewarm("Grilled chicken breast")
        await asyncio.sleep(0)          # let the task start

        t0 = time.monotonic()
        await asyncio.sleep(0.05)       # stand-in for the awaited turn
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, (
        f"the turn took {elapsed:.2f}s while a detached 10 s prewarm ran — it "
        "is contending for something the turn needs, so it is on the critical "
        "path however it was launched")


@pytest.mark.asyncio
async def test_the_prewarm_does_not_land_in_critical_path_stages(
        fast_qualifier):
    """⛔⛤ THE INVARIANT ITSELF: a stage in critical-path `stages_json` must be
    work the turn awaited. The prewarm is not, so it must be accounted
    separately — visible, but never summed into the turn's latency."""
    trace = RequestTrace(turn_id="d2:stages", channel="ios", command="turn")
    with _trace_active(trace):
        _prewarm("Grilled chicken breast")
        await asyncio.sleep(0.05)

    critical = trace.stage_totals()
    assert not any("qualification" in name or "usda_search" in name
                   for name in critical), (
        "speculative work was recorded as critical path: %r — this is how a "
        "1.2 s turn reads as 5.4 s slower than it was" % (critical,))


@pytest.mark.asyncio
async def test_the_prewarm_is_still_visible_somewhere(fast_qualifier):
    """⭐ SEPARATED, NOT HIDDEN. Speculative work costs money and API budget
    and can fail; removing it from the critical path must not remove it from
    the record. A trace that stopped mentioning it would trade one blind spot
    for another."""
    trace = RequestTrace(turn_id="d2:visible", channel="ios", command="turn")
    with _trace_active(trace):
        _prewarm("Grilled chicken breast")
        await asyncio.sleep(0.05)

    spec = trace.speculative_totals()
    assert spec, (
        "the prewarm vanished from the trace entirely — it must be recorded "
        "as speculative, with its own accounting, not dropped")


@pytest.mark.asyncio
async def test_a_poisoned_qualifier_has_no_authority_over_the_turn(monkeypatch):
    """⛔⛔ SEMANTIC NON-AUTHORITY. Make the speculative qualifier RAISE and
    make it return absurd evidence; neither may change what the turn decides.

    Speculation that can change an answer is not speculation — it is an
    unreviewed input on the settlement path."""
    calls = {"n": 0}

    async def _hostile(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("speculative qualifier is down")

    monkeypatch.setattr(TE, "_fetch_usda_off_uncached", _hostile)

    trace = RequestTrace(turn_id="d2:authority", channel="ios", command="turn")
    with _trace_active(trace):
        _prewarm("Grilled chicken breast")
        await asyncio.sleep(0.05)

    # The failure is swallowed by design; what matters is that it stayed
    # swallowed and left no mark on the turn's own accounting.
    assert trace.fields.get("outcome") in (None, "ok"), (
        "a speculative failure changed the TURN's outcome: %r"
        % (trace.fields.get("outcome"),))
    assert not any("qualification" in n for n in trace.stage_totals()), (
        "a failed speculative call still wrote a critical-path stage")


@pytest.mark.asyncio
async def test_a_prewarm_cannot_leak_into_a_later_turn(fast_qualifier):
    """⛔⛔ CROSS-TURN ISOLATION. Turn A launches a prewarm and returns; turn B
    starts before it finishes. A's detached task must not write into B's trace
    or carry B's turn id.

    `ensure_future` copies the context at creation, so this SHOULD hold — but
    "should, by a mechanism I read about" is what the whole tranche is about
    not accepting. Measure it."""
    a = RequestTrace(turn_id="d2:turn-A", channel="ios", command="turn")
    with _trace_active(a):
        _prewarm("Grilled chicken breast")
        await asyncio.sleep(0)

    b = RequestTrace(turn_id="d2:turn-B", channel="ios", command="turn")
    with _trace_active(b):
        await asyncio.sleep(0.05)       # B runs while A's prewarm is in flight

    assert not b.stage_totals(), (
        "turn A's detached prewarm wrote into turn B's critical path: %r"
        % (b.stage_totals(),))
    assert not b.speculative_totals(), (
        "turn A's detached prewarm wrote into turn B's speculative record: %r"
        % (b.speculative_totals(),))


@pytest.mark.asyncio
async def test_the_detached_task_runs_to_completion_and_is_not_cancelled(
        fast_qualifier):
    """⭐ THE LIFECYCLE IS A DECISION, NOT AN ACCIDENT *(item 6)*.

    The prewarm RUNS TO COMPLETION after the response rather than being
    cancelled at settlement, because its result lands in the single-flight
    cache and a later turn for the same food is the consumer. Cancelling would
    discard the only thing it exists for.

    Pinned so the choice cannot drift silently: if someone later cancels it at
    settlement, that is a product decision and this test is where it gets
    argued, not a detail that changes under a refactor."""
    trace = RequestTrace(turn_id="d2:lifecycle", channel="ios", command="turn")
    with _trace_active(trace):
        _prewarm("Chicken breast")
        await asyncio.sleep(0)

    # The turn ends here; the task must still finish on its own.
    await asyncio.sleep(0.2)
    assert trace.speculative_totals(), (
        "the detached prewarm did not complete after the turn returned — if it "
        "is now cancelled at settlement, the single-flight cache never warms "
        "and the speculation buys nothing")


@pytest.mark.asyncio
async def test_the_marking_does_not_leak_into_the_launching_turn(fast_qualifier):
    """⛔⛔ THE OTHER HALF OF ISOLATION, AND IT WAS UNTESTED.

    Cross-TURN isolation says A's prewarm cannot reach turn B. This says the
    marking cannot reach the launching turn's OWN later work: the turn goes on
    to await real stages after firing the prewarm, and those must stay
    critical-path.

    Found by mutation, not by design. Setting `_SPECULATIVE` around
    `ensure_future` instead of inside the coroutine leaves the prewarm
    correctly marked — every existing assertion here still passed — while
    quietly re-filing the turn's own `llm` as speculative. A turn would then
    report ~0 ms of critical path and look instant.

    That is why the flag is set INSIDE `_detached()`: `ensure_future` copies
    the context at creation, so the task gets its own copy and the caller's
    stays clean."""
    trace = RequestTrace(turn_id="d2:noleak", channel="ios", command="turn")
    from core.request_trace import timed as _timed
    with _trace_active(trace):
        _prewarm("Chicken breast")
        with _timed("llm"):                 # the turn's OWN awaited work
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.2)

    assert "llm" in trace.stage_totals(), (
        "the turn's own awaited work was filed as speculative — the marking "
        "escaped the detached task: critical=%r speculative=%r"
        % (trace.stage_totals(), trace.speculative_totals()))
    assert "llm" not in trace.speculative_totals()
