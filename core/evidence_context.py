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
        """
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(acquire())
            self._inflight[key] = task
        return await asyncio.shield(task) if task.done() else await task

    def reused(self, key: str) -> bool:
        """Whether this key's work was already started by someone else — the
        trace's `assessments_reused` answer."""
        return key in self._inflight

    def note(self, **kw) -> None:
        self._meta.update(kw)

    @property
    def meta(self) -> dict:
        return dict(self._meta)


def ensure(context) -> EvidenceContext:
    """The turn's context, or a fresh throwaway.

    A caller with no context still works and simply shares nothing — the
    behaviour must not depend on plumbing being complete, or a missed call
    site becomes a wrong answer instead of a slower one.
    """
    return context if isinstance(context, EvidenceContext) else EvidenceContext()
