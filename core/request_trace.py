"""One trace per request, on any surface — including the ones that are not turns.

`core/turns/trace.py` already times phases, but it is bound to the coordinator's
`TurnState`, and the coordinator runs in `new_observe` in production — so the
path that actually executes emits nothing from it. The REST write surfaces
(`api/quick_log.py` above all) had no timing, no outcome, and no build stamp at
all: a tap-log that took four seconds or committed nothing left the same trace
as one that worked, which is to say none.

This is the transport-agnostic half. It keys on the canonical turn id from
`core/turn_identity`, so a line here joins the ledger events (`ledger_events.turn_id`)
and the conversation row for the same request without a correlation step.

    trace = RequestTrace(turn_id=tid, channel="ios", command="log_food",
                         user_id=user.id)
    with trace.stage("claim"):
        ...
    trace.note(idempotency="replay")
    trace.done()

Two lines per stage is deliberate noise-control: stages log at DEBUG, and the
single `event=request_done` summary at INFO carries the whole shape — total,
per-stage breakdown, outcome, build sha. One greppable line answers "what
happened to this exact request, how long did it take, and which deployment
handled it".

NEVER RAISES. Every method swallows its own failure, for the same reason
`record_ledger_event` does: telemetry describing a write must not be able to
break the write it describes.
"""
from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The active trace for THIS request, ambiently. The turn pipeline
# (core/conversation.run_turn) is a 3,000-line branch — threading a trace
# through every leaf that does real work (the LLM call, the tool batch, the log
# voicing) would be twenty signatures to keep in step. Instead run_turn sets the
# trace here once, and those leaves record into it via `timed()` if one is
# active and do nothing if not. A contextvar (not a global) so concurrent turns
# on the same event loop never write into each other's trace.
_CURRENT: contextvars.ContextVar[Optional["RequestTrace"]] = contextvars.ContextVar(
    "current_request_trace", default=None)


def current_trace() -> Optional["RequestTrace"]:
    return _CURRENT.get()


@contextmanager
def active(trace: "RequestTrace"):
    """Make `trace` the ambient trace for the duration of the block. Restores
    the prior trace on exit (so a nested turn can't strand the outer one)."""
    token = _CURRENT.set(trace)
    try:
        yield trace
    finally:
        try:
            _CURRENT.reset(token)
        except Exception:
            pass


@contextmanager
def timed(stage: str):
    """Time a block and record it on the ambient trace as a stage, if one is
    active. A NO-OP when none is — so the LLM call and the tool executor can be
    instrumented once and stay correct whether they run inside a traced turn, a
    quick-log, or a bare unit test. Never raises; the timing must not be able to
    break the work it measures."""
    t = _CURRENT.get()
    if t is None:
        yield
        return
    start = time.monotonic()
    try:
        yield
    finally:
        try:
            t.record(stage, int((time.monotonic() - start) * 1000))
        except Exception:
            pass


def time_stage(stage: str):
    """Decorator form of `timed`, for an async leaf: each call records its wall
    time as `stage` on the ambient trace. If the call raises, the elapsed time
    is still recorded and the exception propagates — the wrapper never retries
    and never depends on the telemetry."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        async def _wrapped(*a, **k):
            with timed(stage):
                return await fn(*a, **k)
        return _wrapped
    return deco


def _sha() -> str:
    """The deployed build, from the stamp the conversation rows already use.

    Reuses `db.queries._build_stamp` rather than reading RENDER_GIT_COMMIT
    again: two readers of one fact drift, and this one would drift silently
    (a trace claiming the wrong build is worse than a trace with no build).
    """
    try:
        from db.queries import _build_stamp
        return _build_stamp().get("sha", "unknown")
    except Exception:
        return "unknown"


class RequestTrace:
    """The shape of one request: stages, outcome, and which build served it."""

    def __init__(self, *, turn_id: str, channel: str, command: str,
                 user_id: Optional[int] = None):
        self.turn_id = turn_id
        self.channel = channel
        self.command = command
        self.user_id = user_id
        self.fields: dict[str, Any] = {}
        self.stages: list[tuple[str, int]] = []
        self._t0 = time.monotonic()
        self._done = False

    @contextmanager
    def stage(self, name: str):
        """Time one stage. A stage that RAISES is still recorded — that is the
        stage the reader is looking for."""
        start = time.monotonic()
        try:
            yield
        finally:
            try:
                self.stages.append((name, int((time.monotonic() - start) * 1000)))
                logger.debug(f"event=stage turn={self.turn_id} stage={name} "
                             f"ms={self.stages[-1][1]}")
            except Exception:
                pass

    def record(self, name: str, ms: int) -> None:
        """Add a timed stage directly (used by `timed()` from a leaf). Same list
        as `stage()` appends to; duplicates are SUMMED at breakdown time, so a
        turn that calls the model three times reports one `llm` figure that is
        the total time in the model, not the last call."""
        try:
            self.stages.append((name, int(ms)))
        except Exception:
            pass

    def stage_totals(self) -> dict:
        """Per-stage milliseconds, duplicates summed, insertion order kept."""
        out: dict[str, int] = {}
        for name, ms in self.stages:
            out[name] = out.get(name, 0) + ms
        return out

    def note(self, **fields: Any) -> None:
        """Attach facts the summary should carry — idempotency outcome, entry
        id, fallback use. Silently ignored on failure."""
        try:
            self.fields.update(fields)
        except Exception:
            pass

    def total_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def done(self, outcome: str = "ok") -> None:
        """The one line worth grepping. Idempotent — a handler that returns
        early and a `finally` that also closes the trace must not log twice."""
        if self._done:
            return
        self._done = True
        # `setdefault`, so an explicit `note(outcome=…)` beats this argument —
        # and `persist()` reads the resolved value back out of `fields`.
        self.fields.setdefault("outcome", outcome)
        try:
            breakdown = ",".join(f"{n}:{ms}" for n, ms in self.stage_totals().items())
            # ONE `outcome=` PER LINE. `setdefault` above puts the key into
            # `fields`, and `extra` is built from `fields` — so every line this
            # ever emitted carried `outcome=` twice. Harmless only while the two
            # agreed: a caller who had already noted a different outcome got the
            # ARGUMENT printed first and their own value printed last, one line
            # asserting two outcomes for one request, and any `dict(pairs)`
            # parser silently taking whichever came last.
            #
            # Resolved once here, from `fields`, which is the same value
            # `persist()` writes to the row — so the line and the row cannot
            # disagree either.
            resolved = self.fields.get("outcome") or outcome
            extra = " ".join(f"{k}={v}" for k, v in self.fields.items()
                             if k != "outcome")
            logger.info(
                f"event=request_done turn={self.turn_id} channel={self.channel} "
                f"command={self.command} user={self.user_id} outcome={resolved} "
                f"total_ms={self.total_ms()} stages={breakdown or '-'} "
                f"build={_sha()}" + (f" {extra}" if extra else ""))
        except Exception:
            pass

    async def persist(self, db) -> None:
        """Write the summary row, so this request is still measurable in a week.

        EXPLICIT, not automatic. `done()` runs in `__exit__`, which is
        synchronous, and reaching for a database from there would mean either
        blocking IO in a context-manager exit or a fire-and-forget task whose
        failure nobody sees. The caller already holds a session; asking for it
        is cheaper than hiding it.

        Never raises. Telemetry describing a write must not be able to break
        the write it describes — the same rule `record_ledger_event` follows.
        """
        try:
            import json

            from db.models import TurnMetric
            db.add(TurnMetric(
                turn_id=self.turn_id, user_id=self.user_id,
                channel=self.channel, command=self.command,
                outcome=self.fields.get("outcome") or "ok",
                total_ms=self.total_ms(),
                stages_json=json.dumps(self.stage_totals()),
                build_sha=_sha()))
            await db.commit()
        except Exception as e:
            logger.warning(f"turn metric not persisted turn={self.turn_id}: {e}")

    async def persist_isolated(self) -> None:
        """Persist on a FRESH session, never the caller's.

        The turn pipeline's session may be mid-transaction, or in a failed state
        after an errored turn — and a metric write that reached for it could
        commit half a turn, or be rolled back with it. A telemetry row must not
        be able to do either, so it gets its own connection and its own commit,
        entirely outside the turn's transaction. `quick_log` uses `persist(db)`
        because there it already owns a clean, finished session; `run_turn` uses
        this because at its boundary the session's state is not something the
        trace should assume. Never raises."""
        try:
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as mdb:
                await self.persist(mdb)
        except Exception as e:
            logger.warning(f"turn metric (isolated) not persisted turn={self.turn_id}: {e}")

    def __enter__(self) -> "RequestTrace":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # An exception is an OUTCOME, not a reason to lose the trace — the
        # failed request is the one someone is trying to explain. Never
        # suppresses: returning True here would swallow the caller's error.
        self.done(outcome="ok" if exc_type is None else f"error:{exc_type.__name__}")
        return False
