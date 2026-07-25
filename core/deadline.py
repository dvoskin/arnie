"""Per-turn time budget (PR #30).

Individual calls have timeouts. OpenFoodFacts uses six seconds with a retry;
the model client uses forty-five. Both are reasonable in isolation and neither
bounds the thing the user experiences, because a turn makes SEVERAL of them: a
four-item meal that hits a degraded product API can spend most of a minute
inside per-call timeouts that each behaved exactly as configured.

A per-call timeout answers "how long may this call take". Nobody was answering
"how long may this TURN take", and that is the number the user feels.

So: one deadline for the turn, set at the top, consulted by anything about to
wait. `remaining()` shrinks as the turn proceeds, so the fourth lookup gets
what is left rather than a fresh six seconds.

"At the top" is load-bearing, and the first version of this got it wrong: the
budget opened inside `execute_tool_calls`, so it began after the interpreter
model call and ended before the response composer — a tool-batch budget with a
turn budget's name. It now opens in `core.conversation.run_turn`, and these
consult it:

    the food interpreter model call      core/food_turn.py
    the conversational model call        core/conversation.py
      and its self-heal retry
    every remote candidate source        skills/nutrition/candidates.py
      (USDA, OpenFoodFacts, web label)
    the OpenFoodFacts HTTP retries       skills/nutrition/off.py
    the tool batch                       handlers/tool_executor.py

A blocking food operation that consults NEITHER `cap()` nor `wait_for()` is
outside the guarantee. That list is the guarantee's actual extent — keep it
honest when adding one.

Three rules that make it usable rather than merely present:

**Expiry degrades, it does not fail.** Past the deadline, `wait_for` raises
`DeadlineExceeded` and callers are expected to fall back to what they have.
A food turn whose enrichment ran out of time should log an estimate and say so;
one that raises has turned a slow lookup into a lost meal.

**A floor, not just a ceiling.** `remaining()` never returns a sliver. A
50-millisecond budget handed to an HTTP call guarantees a timeout after paying
the connection setup — worse than not making the call, because it costs the
time AND produces nothing. Below the floor, the honest answer is zero.

**No deadline is not a zero deadline.** With nothing set, `remaining()` is
infinite and `wait_for` is a plain await. Background jobs and tests have no
user waiting on them and must not inherit an interactive budget.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextvars import ContextVar
from typing import Awaitable, Optional, TypeVar

T = TypeVar("T")

#: The turn's deadline as a monotonic timestamp, or None for unbounded.
CURRENT_DEADLINE: ContextVar[Optional[float]] = ContextVar(
    "CURRENT_DEADLINE", default=None)

#: Below this, a remaining budget is not worth handing to a network call: it
#: would be spent on connection setup and produce a timeout instead of an
#: answer. Reported as zero so the caller skips the call outright.
MIN_USEFUL_S = 0.25

#: A turn budget must exceed the LARGEST SINGLE blocking call it contains, or it
#: fails work the system would otherwise have finished. The model client is
#: constructed with a 45-second timeout, so a 20-second turn budget — which is
#: what this was while it only covered the tool batch — would now abort the main
#: model call on any turn that had already spent a few seconds interpreting,
#: turning a slow turn into a lost one. That is precisely the failure mode this
#: module's "expiry degrades, it does not fail" rule exists to prevent.
#:
#: 60s is one full model call plus room for the interpreter and the tool batch
#: around it. It bounds the pathological case — several sequential timeouts
#: against a degraded source — without touching turns that are merely slow.
DEFAULT_TURN_BUDGET_S = 60.0


class DeadlineExceeded(TimeoutError):
    """The turn ran out of time. Callers fall back; they do not propagate."""


def turn_budget_s() -> float:
    raw = (os.getenv("FOOD_TURN_BUDGET_S", "") or "").strip()
    try:
        budget = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TURN_BUDGET_S
    return budget if budget > 0 else DEFAULT_TURN_BUDGET_S


class budget:
    """Set a deadline for the enclosed work.

        with deadline.budget():
            ...

    Nested budgets take the EARLIER deadline. An inner block asking for more
    time than the turn has left does not get it — a nested budget can only
    tighten, which is what makes the outer one a guarantee rather than a
    suggestion.
    """

    __slots__ = ("_seconds", "_token")

    def __init__(self, seconds: Optional[float] = None):
        self._seconds = turn_budget_s() if seconds is None else seconds
        self._token = None

    def __enter__(self) -> "budget":
        proposed = time.monotonic() + max(0.0, self._seconds)
        existing = CURRENT_DEADLINE.get()
        self._token = CURRENT_DEADLINE.set(
            proposed if existing is None else min(existing, proposed))
        return self

    def __exit__(self, *exc) -> bool:
        if self._token is not None:
            CURRENT_DEADLINE.reset(self._token)
        return False


def remaining() -> float:
    """Seconds left, `inf` when unbounded, 0.0 when there is no useful time.

    The floor is why this returns 0.0 rather than 0.04: a caller that checks
    `if remaining():` should skip the call, and a truthy sliver would have it
    make one that can only fail.
    """
    deadline = CURRENT_DEADLINE.get()
    if deadline is None:
        return float("inf")
    left = deadline - time.monotonic()
    return left if left >= MIN_USEFUL_S else 0.0


def expired() -> bool:
    return remaining() <= 0.0


def cap(seconds: float) -> float:
    """This call's timeout, clamped to what the turn has left.

    The point of the whole module in one function: a six-second per-call
    timeout is fine until it is the fourth six-second timeout in a
    twenty-second turn.
    """
    left = remaining()
    return seconds if left == float("inf") else min(seconds, left)


async def wait_for(awaitable: Awaitable[T],
                   seconds: Optional[float] = None) -> T:
    """Await under the turn's remaining budget.

    Raises `DeadlineExceeded` — a distinct type from `asyncio.TimeoutError`
    on purpose, so a caller can tell "this one call was slow" from "the turn is
    over", and stop trying rather than retrying into a budget that is gone.
    """
    left = remaining()
    if left <= 0.0:
        raise DeadlineExceeded("turn budget exhausted before the call started")

    limit = left if seconds is None else min(seconds, left)
    if limit == float("inf"):
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=limit)
    except (asyncio.TimeoutError, TimeoutError) as e:
        raise DeadlineExceeded(f"exceeded {limit:.1f}s of turn budget") from e


def log_line() -> str:
    left = remaining()
    return ("event=turn_budget remaining=unbounded" if left == float("inf")
            else f"event=turn_budget remaining={left:.2f}")
