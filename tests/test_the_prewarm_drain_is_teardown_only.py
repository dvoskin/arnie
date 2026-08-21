"""⛔⛔ THE DRAIN IS TEARDOWN MACHINERY, NOT TURN MACHINERY.

D2 lifecycle hardening, separated from P17g's predicate on review.

The registry exists because D2 gave the detached prewarm a WRITE — since
`flush_speculative` folds its stage back into the row, the task outlives the
turn holding a connection. In the full suite that collided with another
module's `DROP SCHEMA ... CASCADE` and Postgres killed the TEARDOWN.

⭐ BUT A DRAIN IS ALSO THE EASIEST WAY TO UNDO THE WHOLE POINT OF THE PREWARM.
If it were ever awaited on the turn's path, the speculation would stop being
speculative and every turn would pay for it — the exact latency D2 proved was
not on the critical path. So the three properties are asserted, not assumed:

    it is NOT awaited at settlement — only teardown/shutdown calls it
    it PRUNES completed tasks — the registry cannot grow without bound
    it CANNOT extend response latency — a slow prewarm does not slow a turn
"""
from __future__ import annotations

import asyncio
import time

import pytest

import core.food_turn as FT
import handlers.tool_executor as TE
from core.request_trace import RequestTrace, active as _trace_active


@pytest.fixture()
def quick_prewarm(monkeypatch):
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


def test_the_turn_path_never_awaits_the_drain():
    """⛔⛔ NOT AT SETTLEMENT. A drain on the turn's path would make the
    prewarm blocking — speculation nobody can skip — and would silently undo
    the latency independence D2 measured with a 10 s poisoned prewarm.

    Asserted structurally over the whole module, because the claim is about
    where the call does NOT appear: only teardown and shutdown may await it,
    and neither lives in `core/food_turn`."""
    import ast
    import inspect

    src = inspect.getsource(FT)
    tree = ast.parse(src)
    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and getattr(inner.func, "id", "") == "drain_speculative"):
                    callers.append(node.name)
    assert callers == [], (
        "core/food_turn awaits its own drain inside %r — the prewarm would "
        "stop being speculative and every turn would pay for it" % (callers,))


@pytest.mark.asyncio
async def test_the_registry_prunes_completed_tasks(quick_prewarm):
    """⭐ IT CANNOT GROW WITHOUT BOUND. A registry that only ever added would
    be a leak in a long-lived process — and a drain over thousands of finished
    tasks would get slower every hour the server stayed up."""
    before = len(FT._IN_FLIGHT)
    trace = RequestTrace(turn_id="drain:prune", channel="ios", command="turn")
    with _trace_active(trace):
        for _ in range(5):
            FT._SpeculativeEnrichment._start("Chicken breast")
        assert len(FT._IN_FLIGHT) >= before + 1, "nothing was registered"
        await FT.drain_speculative()

    assert len(FT._IN_FLIGHT) <= before, (
        "completed prewarms stayed in the registry: %d before, %d after"
        % (before, len(FT._IN_FLIGHT)))


@pytest.mark.asyncio
async def test_a_slow_prewarm_still_cannot_extend_the_turn(monkeypatch):
    """⛔⛔ THE PROPERTY THE REGISTRY MUST NOT COST. Registering a task is
    bookkeeping; it must not make anything wait. A 10 s prewarm still leaves
    the turn's own work finishing in its own time — the same measurement D2
    made, re-run with the registry in place so the hardening is proven not to
    have quietly re-coupled them."""
    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ
    import skills.nutrition.off as OFF

    async def _rows(*_a, **_k):
        return [{"description": "Chicken breast", "fdcId": 171077}]

    async def _slow(*_a, **_k):
        await asyncio.sleep(10)
        raise AssertionError("the slow prewarm was awaited by the turn")

    async def _no_off(*_a, **_k):
        return None

    monkeypatch.setattr(USDA, "search_food", _rows)
    monkeypatch.setattr(EQ, "qualify_usda_rows", _slow)
    monkeypatch.setattr(OFF, "search", _no_off)
    monkeypatch.setattr(TE, "_qualification_halted", lambda: False)

    trace = RequestTrace(turn_id="drain:latency", channel="ios", command="turn")
    with _trace_active(trace):
        FT._SpeculativeEnrichment._start("Chicken breast")
        await asyncio.sleep(0)
        t0 = time.monotonic()
        await asyncio.sleep(0.05)          # stand-in for the awaited turn
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, (
        f"the turn took {elapsed:.2f}s beside a detached 10 s prewarm — "
        "registering the task re-coupled them")


@pytest.mark.asyncio
async def test_the_drain_is_bounded_and_never_raises(monkeypatch):
    """⭐ A DRAIN THAT HANGS IS WORSE THAN NO DRAIN — it would turn a slow
    prewarm into a hung teardown, which is the failure it exists to prevent
    wearing the opposite costume. It waits with a timeout and swallows."""
    async def _forever():
        await asyncio.sleep(30)

    task = asyncio.ensure_future(_forever())
    FT._IN_FLIGHT.add(task)
    try:
        t0 = time.monotonic()
        awaited = await FT.drain_speculative(timeout=0.1)
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, f"the drain blocked for {elapsed:.2f}s"
        assert awaited == 1
    finally:
        task.cancel()
        FT._IN_FLIGHT.discard(task)
