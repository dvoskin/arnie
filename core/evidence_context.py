"""ONE TURN'S EVIDENCE WORK, shared by every consumer that needs it.

    turn starts -> EvidenceContext()
        field A asks for evidence about X   -> starts the work
        field B asks for evidence about X   -> AWAITS THE SAME FUTURE
    turn ends   -> context is dropped

IN-FLIGHT, NOT COMPLETED-VALUE. A cache of finished results only helps the
consumer that arrives second-and-later; two fields evaluated CONCURRENTLY both
miss it and both pay. Memoizing the coroutine instead means the first caller
starts the work and every other caller — concurrent or not — awaits that same
future. One retrieval and one semantic classification per evidence set, which
is the property §2 asks for and a value cache cannot give.

TURN-SCOPED BY CONSTRUCTION, not by a key someone remembered to include. The
previous version was a module-level dict keyed `(food, resolver_version)` and
described as turn-scoped; nothing cleared it, so a later turn could recall
assessments made against evidence a previous turn retrieved. Keying on the
turn id fixed the symptom. This removes the shape: the context is created by
the turn, referenced by that turn's work, and garbage when the turn ends.

CORE HOLDS NO DOMAIN KNOWLEDGE. The context does not know what a food is or
how to fetch one. Callers pass an `acquire` coroutine; the context guarantees
it runs at most once per key per turn.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class EvidenceContext:
    """Per-turn evidence memoization. Created by the turn, dropped with it."""

    __slots__ = ("_inflight", "_meta")

    def __init__(self):
        self._inflight: dict = {}
        #: Free-form per-turn notes for the activation trace (counts,
        #: latencies, whether a supplemental lookup ran). Written by domains,
        #: read by tracing; never load-bearing for a decision.
        self._meta: dict = {}

    async def shared(self, key: str, acquire: Callable) -> Any:
        """`acquire()`'s result, computed at most once per key per turn.

        A FAILURE IS SHARED TOO, and deliberately: if acquisition raised, every
        waiter sees the same exception rather than each retrying a provider
        that just failed. The caller decides what a failure means — here it
        always means "no evidence", never "guess".

        ⭐ A WAITER'S TIMEOUT MUST NOT KILL THE WORK. This read

            await asyncio.shield(task) if task.done() else await task

        which shields the case that cannot be cancelled (already done) and
        leaves the case that can (still pending) bare. `preparation_space`
        wraps this in `wait_for(..., 1.5)`, so on expiry the cancellation
        propagated into the SHARED future and destroyed the acquisition for
        every other consumer of that key — the timeout of one waiter deleting
        evidence nobody else had asked to abandon. Shielding unconditionally
        is the whole point of a shared future: a waiter may stop waiting, and
        that is all it may do.
        """
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(acquire())
            self._inflight[key] = task
        return await asyncio.shield(task)

    def reused(self, key: str) -> bool:
        """Whether this key's work was already started by someone else — the
        trace's `assessments_reused` answer."""
        return key in self._inflight

    def note(self, **kw) -> None:
        self._meta.update(kw)

    @property
    def meta(self) -> dict:
        return dict(self._meta)


#: THE TURN'S CONTEXT, AMBIENT. Set once at turn entry beside `CURRENT_TURN_ID`
#: and reset with its token at exit.
#:
#: ⭐ WHY AMBIENT AND NOT THREADED. The two callers that must share are far
#: apart: speculative enrichment starts while the interpreter is still
#: streaming, and B-1 ownership runs after it. Threading a parameter between
#: them means every intermediate function carries evidence plumbing it has no
#: use for — and MEASURED IN PRODUCTION 2026-08-07, a missing thread is
#: invisible: `derive_unresolved` created its own context, the pricing path
#: created another, nothing shared, and the only symptom was a slow turn with
#: a field that never opened. Ambient makes sharing the default and a missed
#: site impossible rather than silent.
CURRENT_EVIDENCE: ContextVar[Optional["EvidenceContext"]] = ContextVar(
    "CURRENT_EVIDENCE", default=None)


def ensure(context=None) -> EvidenceContext:
    """The context to use: an explicit one, else THE TURN'S ambient one.

    NO SILENT THROWAWAY when the turn has one. The previous version created a
    fresh context whenever none was passed, which turned "the plumbing is
    incomplete" into "everything still works, just slower and worse" — the
    exact failure that cost a production turn 6.8 seconds and opened nothing.

    A throwaway is still returned when there is no ambient context at all
    (scripts, background jobs, tests that never opened a turn): those genuinely
    have nothing to share, and refusing to run would be worse than not sharing.
    """
    if isinstance(context, EvidenceContext):
        return context
    ambient = CURRENT_EVIDENCE.get()
    if ambient is not None:
        return ambient
    logger.debug("no ambient evidence context — nothing to share this call")
    return EvidenceContext()
