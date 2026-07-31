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

import logging
import time
from contextlib import contextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
        try:
            breakdown = ",".join(f"{n}:{ms}" for n, ms in self.stages)
            extra = " ".join(f"{k}={v}" for k, v in self.fields.items())
            logger.info(
                f"event=request_done turn={self.turn_id} channel={self.channel} "
                f"command={self.command} user={self.user_id} outcome={outcome} "
                f"total_ms={self.total_ms()} stages={breakdown or '-'} "
                f"build={_sha()}" + (f" {extra}" if extra else ""))
        except Exception:
            pass

    def __enter__(self) -> "RequestTrace":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # An exception is an OUTCOME, not a reason to lose the trace — the
        # failed request is the one someone is trying to explain. Never
        # suppresses: returning True here would swallow the caller's error.
        self.done(outcome="ok" if exc_type is None else f"error:{exc_type.__name__}")
        return False
