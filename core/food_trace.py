"""End-to-end food turn tracing (PR #29).

There are twenty-six structured event types across the food path today, and
every one of them is honest about the thing it reports. What none of them can
answer is the question that actually gets asked in triage:

    "This user says their lunch logged wrong. What happened on that turn?"

Answering it means joining `structured_food`, `item_trace`, `nutrition_shadow`,
`nutrition_promotion` and `turn_native` on a turn id — across five modules that
name their fields differently and emit at different times. That join is a log
pipeline nobody has built, so in practice the question is answered by reading
code and guessing.

So this adds a SPINE: one accumulating record per food turn, with a stage per
phase of the pipeline, and one line at the end carrying the whole thing. The
existing per-stage events stay exactly as they are — they are the detail, and
deleting them to make room for a summary would trade depth for convenience.
What the spine adds is the shape: which stages ran, how long each took, what
each decided, and where the turn stopped.

Three properties it has to have, because a tracer that lacks them gets turned
off and then rots:

**Free when off.** `FOOD_TRACE` unset means every call here is a few attribute
reads and no allocation beyond the record itself. No serialization, no logging,
no timing syscalls in the hot path beyond one monotonic read per stage.

**Never the reason a turn fails.** Every public entry point swallows its own
exceptions. A tracer that can raise is a tracer that takes down the feature it
was added to observe.

**Ambient, not threaded.** The stages live in five modules that do not call each
other directly, and adding a trace parameter to each would be a refactor of the
call graph in service of observability. A contextvar — the same pattern turn
identity and execution results already use — keeps the change local to the
places that actually record something.

The line it emits is deliberately one line of key=value rather than JSON: it
has to be greppable from a terminal on a box with no log tooling, which is
where these questions get asked at 2am.
"""
from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

TRACE_VERSION = "food_trace_v1"

#: The ambient trace for the turn in flight. None when tracing is off or no
#: food turn is running, which is the common case and must stay cheap.
CURRENT_TRACE: ContextVar[Optional["FoodTurnTrace"]] = ContextVar(
    "CURRENT_FOOD_TRACE", default=None)


class Stage(str, Enum):
    """The phases a food turn passes through, in order.

    Named after what they DECIDE rather than which module runs them, so the
    trace survives the modules moving — which they have, twice.
    """
    INTERPRET = "interpret"      # words → items
    STAGE = "stage"              # items → staged rows with typed identity
    CLARIFY = "clarify"          # ambiguity → ask / assume / hold
    RESOLVE = "resolve"          # identity → nutrients
    PROMOTE = "promote"          # whose numbers own the row
    EXECUTE = "execute"          # the writes
    RENDER = "render"            # what the user sees


#: Stage order, for the funnel. A turn that never reached a stage is different
#: from one that reached it and did nothing, and the funnel needs to tell them
#: apart.
STAGE_ORDER = tuple(s.value for s in Stage)


class Outcome(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"          # the stage was not applicable
    ASKED = "asked"              # stopped here to ask the user
    HELD = "held"                # stopped here, nothing committed
    FAILED = "failed"            # an exception, recorded not raised


@dataclass
class StageRecord:
    """One phase, with what it cost and what it decided."""
    stage: str
    duration_ms: float = 0.0
    outcome: str = Outcome.OK.value
    detail: str = ""
    counts: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"stage": self.stage, "duration_ms": round(self.duration_ms, 1),
                "outcome": self.outcome, "detail": self.detail,
                "counts": dict(self.counts)}


@dataclass
class FoodTurnTrace:
    """One food turn, end to end.

    Mutable on purpose: it is written to from five places over the life of a
    turn, and a frozen record would mean rebuilding it at every step.
    """
    turn_id: str = ""
    user_id: Optional[int] = None
    mode: str = ""
    channel: str = ""
    meal_group_id: str = ""
    stages: Tuple[StageRecord, ...] = ()
    items_staged: int = 0
    items_committed: int = 0
    items_held: int = 0
    questions_asked: int = 0
    assumptions_made: int = 0
    resolver_source: str = ""
    promoted: Optional[bool] = None
    cohort: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.monotonic)
    version: str = TRACE_VERSION

    # ── accumulation ──────────────────────────────────────────────────────────
    def record(self, stage: Stage, *, duration_ms: float = 0.0,
               outcome: Outcome = Outcome.OK, detail: str = "",
               **counts) -> None:
        self.stages = self.stages + (StageRecord(
            stage=stage.value, duration_ms=duration_ms,
            outcome=outcome.value, detail=detail,
            counts={k: int(v) for k, v in counts.items()}),)

    def note(self, **fields) -> None:
        """Set turn-level facts as they become known. Unknown names are
        ignored rather than raising — a tracer must not fail a turn because a
        caller passed a field it does not have."""
        for name, value in fields.items():
            if hasattr(self, name) and value is not None:
                setattr(self, name, value)

    # ── derived ───────────────────────────────────────────────────────────────
    @property
    def total_ms(self) -> float:
        return round((time.monotonic() - self.started_at) * 1000.0, 1)

    @property
    def reached(self) -> Tuple[str, ...]:
        return tuple(s.stage for s in self.stages)

    @property
    def last_stage(self) -> str:
        return self.stages[-1].stage if self.stages else ""

    @property
    def stopped_at(self) -> str:
        """Where the turn ENDED, which is the funnel's drop-off point.

        Not the same as the last stage recorded: a turn that asked a question
        stopped at CLARIFY even though RENDER ran afterwards to produce the
        question. Reporting RENDER there would put every clarification at the
        bottom of the funnel and hide the fact that nothing committed.
        """
        for record in self.stages:
            if record.outcome in (Outcome.ASKED.value, Outcome.HELD.value,
                                  Outcome.FAILED.value):
                return record.stage
        return self.last_stage

    def as_dict(self) -> dict:
        return {
            "turn_id": self.turn_id, "user_id": self.user_id,
            "mode": self.mode, "channel": self.channel,
            "meal_group_id": self.meal_group_id, "cohort": self.cohort,
            "items_staged": self.items_staged,
            "items_committed": self.items_committed,
            "items_held": self.items_held,
            "questions_asked": self.questions_asked,
            "assumptions_made": self.assumptions_made,
            "resolver_source": self.resolver_source,
            "promoted": self.promoted, "error": self.error,
            "total_ms": self.total_ms, "stopped_at": self.stopped_at,
            "stages": [s.as_dict() for s in self.stages],
            "version": self.version,
        }

    def log_line(self) -> str:
        """The greppable summary.

        Field order is triage order: what turn, whose, what mode, where it
        stopped, how long, then the counts. Per-stage timings ride at the end
        as `stage:ms` pairs so `grep food_trace | grep resolve:` still finds
        the slow ones without a parser.
        """
        # Comma-separated, no spaces: the whole thing has to survive as ONE
        # key=value token, and a space-separated list silently truncates to its
        # first pair when read back — which showed up as every stage but the
        # first vanishing from the latency report.
        timings = ",".join(f"{s.stage}:{s.duration_ms:.0f}"
                           for s in self.stages)
        return (
            f"event=food_trace turn={self.turn_id or '-'} "
            f"user={self.user_id if self.user_id is not None else '-'} "
            f"mode={self.mode or '-'} cohort={self.cohort or '-'} "
            f"stopped_at={self.stopped_at or '-'} total_ms={self.total_ms:.0f} "
            f"staged={self.items_staged} committed={self.items_committed} "
            f"held={self.items_held} asked={self.questions_asked} "
            f"assumed={self.assumptions_made} "
            f"source={self.resolver_source or '-'} "
            f"promoted={'-' if self.promoted is None else str(self.promoted).lower()} "
            f"error={self.error or '-'} "
            f"meal={self.meal_group_id or '-'} timings={timings or '-'}")


# ── enablement ────────────────────────────────────────────────────────────────
def tracing_enabled() -> bool:
    """Default ON.

    A tracer that ships disabled is a tracer nobody turns on until the incident
    it was meant to explain is already over. The cost is one log line per food
    turn and a monotonic read per stage; the kill switch exists for the case
    where that is genuinely too much, not as the default posture.
    """
    raw = (os.getenv("FOOD_TRACE", "true") or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


# ── the ambient API ───────────────────────────────────────────────────────────
def begin(*, turn_id: str = "", user_id=None, mode: str = "",
          channel: str = "", cohort: str = "") -> Optional[FoodTurnTrace]:
    """Start a trace for this turn and make it ambient. Returns None when
    tracing is off, which every caller must tolerate."""
    if not tracing_enabled():
        return None
    try:
        trace = FoodTurnTrace(turn_id=turn_id or "", user_id=user_id,
                              mode=mode or "", channel=channel or "",
                              cohort=cohort or "")
        CURRENT_TRACE.set(trace)
        return trace
    except Exception:
        return None


def current() -> Optional[FoodTurnTrace]:
    try:
        return CURRENT_TRACE.get()
    except Exception:
        return None


def note(**fields) -> None:
    """Record turn-level facts on the ambient trace, if there is one."""
    trace = current()
    if trace is None:
        return
    try:
        trace.note(**fields)
    except Exception:
        pass


def record(stage: Stage, *, duration_ms: float = 0.0,
           outcome: Outcome = Outcome.OK, detail: str = "", **counts) -> None:
    trace = current()
    if trace is None:
        return
    try:
        trace.record(stage, duration_ms=duration_ms, outcome=outcome,
                     detail=detail, **counts)
    except Exception:
        pass


class stage:
    """Time one stage and record it, whatever happens inside.

        with food_trace.stage(Stage.RESOLVE) as s:
            resolution = resolve(request, candidates)
            s.counts["candidates"] = len(candidates)

    An exception inside the block is recorded as FAILED and then RE-RAISED.
    Swallowing it here would make the tracer change control flow, which is the
    one thing an observer must never do — the failures this hides would be the
    exact ones it exists to surface.
    """

    __slots__ = ("_stage", "_started", "outcome", "detail", "counts")

    def __init__(self, which: Stage, **counts):
        self._stage = which
        self._started = 0.0
        self.outcome = Outcome.OK
        self.detail = ""
        self.counts = {k: int(v) for k, v in counts.items()}

    def __enter__(self) -> "stage":
        self._started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = (time.monotonic() - self._started) * 1000.0
        if exc_type is not None:
            self.outcome = Outcome.FAILED
            self.detail = self.detail or f"{exc_type.__name__}: {exc}"[:160]
            note(error=f"{self._stage.value}:{exc_type.__name__}")
        record(self._stage, duration_ms=elapsed, outcome=self.outcome,
               detail=self.detail, **self.counts)
        return False           # never suppress


def finish(trace: Optional[FoodTurnTrace] = None) -> Optional[FoodTurnTrace]:
    """Emit the summary line and clear the ambient trace.

    Safe to call twice — the second call finds nothing and does nothing, which
    matters because the food path has more than one exit and making each of
    them prove it is the last would be worse than an idempotent finish.
    """
    trace = trace if trace is not None else current()
    if trace is None:
        return None
    try:
        CURRENT_TRACE.set(None)
        logger.info(trace.log_line())
    except Exception:
        pass
    return trace


# ── correction linkage ────────────────────────────────────────────────────────
# There is deliberately NO correction emitter here.
#
# `preferences.CorrectionRecord.log_line()` already emits `event=food_correction`
# with the ranking snapshot and the candidate ids, and a second event carrying
# the same fact under a different name is exactly the fragmentation this module
# exists to end. What the funnel needed was one missing FIELD on that record —
# whether the corrected value was assumed by us or stated by the user — so that
# is where it was added.
