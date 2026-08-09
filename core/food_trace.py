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

import hashlib
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
    ROUTE = "route"              # does this lane own the turn
    CONTEXT = "context"          # board, regulars, day state, open question
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


#: Said ONCE per process. A warning on every food turn would be noise nobody
#: reads, and this is a deployment fact rather than a per-turn event.
_SALT_WARNED = [False]


def _salt_warning() -> None:
    if _SALT_WARNED[0]:
        return
    _SALT_WARNED[0] = True
    # STRICTLY k=v, like every other line here — including the one warning that
    # the lines are weaker than they look. What this would have said in prose
    # is in `user_ref`'s docstring: the pseudonyms are unsalted digests of small
    # integer account ids, reversible by enumeration, so `user=u…` is an
    # account identifier and not an anonymisation.
    logger.warning(
        "event=food_trace_config outcome=unsalted setting=FOOD_TRACE_SALT "
        "effect=pseudonyms_reversible")


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
    #: THE JOIN KEY ACROSS TURNS. A canonical clarification is one operation
    #: spanning two turns — the ask and the answer — and they carry different
    #: `turn_id`s by construction, so a turn-scoped trace cannot follow one
    #: without this. Every `b1_*` event already keys on the same string, which
    #: is why this is the operation id and not a new correlation id.
    operation_id: str = ""
    stages: Tuple[StageRecord, ...] = ()
    #: ═══ THE FUNNEL: FIVE STATE BOUNDARIES, PLUS ONE EXECUTION COUNTER ══════
    #:
    #: FIVE BOUNDARIES. Each is a strictly stronger claim about the SAME item
    #: than the one above it, so each count is a subset of the one before, and
    #: no two of them may be proxies for one another:
    #:
    #:     interpreted   the model produced an item
    #:     staged        canonical staging ACCEPTED it, with typed identity
    #:     written       a row was flushed into the transaction
    #:     committed     that transaction COMMITTED
    #:     visible       the committed truth reached the reply (a `mark`)
    #:
    #: ONE EXECUTION COUNTER, which is `attempted`, and it is deliberately NOT
    #: on that ladder. It counts what the executor TRIED — a fact about
    #: execution, not a state an item reached. Reading it as a sixth boundary is
    #: how these get misused: `attempted=3 written=2` is a healthy partial write
    #: and must never be flagged, while `committed=3 written=2` is impossible.
    #: `written <= attempted` still holds, because a row cannot be flushed by a
    #: write nobody made — that is a bound, not a membership.
    #:
    #: `visible` is also not a count. It is a `mark` — an event with a timestamp
    #: — so it is checked as an implication (`visible` ⇒ `committed > 0`) rather
    #: than compared as a magnitude. `FoodTurnTrace.impossible()` holds all four
    #: of these checks and the log line reports the verdict as `funnel=`.
    #:
    #: Every telemetry defect this module has carried was one term standing in
    #: for another: `items_ready` (the clarifier's approval) reported as
    #: `committed`, so a turn whose every write was blocked showed a full commit
    #: rate; raw interpreter output reported as `staged`, so rows that never
    #: reached typed staging inflated the funnel's mouth; a flush into an open
    #: transaction reported as `committed`, so a write that later rolled back
    #: scored as a success.
    #:
    #: They collapse so easily because on the LEGACY lane several of them
    #: genuinely coincide — its helpers commit independently, so written and
    #: committed happen together and one number is honestly both. The canonical
    #: lane writes into a caller-owned transaction, where they come apart. A
    #: name that was true on one lane is not automatically true on the other.
    items_interpreted: int = 0
    items_staged: int = 0
    #: The clarifier's verdict — approved to write. NOT evidence of a write.
    items_ready: int = 0
    #: Writes ATTEMPTED. On the legacy lane this counts the calls made, failures
    #: included; the canonical lane counts the items it handed the writer. Both
    #: mean "we tried this many", which is what makes `failed` derivable.
    items_attempted: int = 0
    #: Rows FLUSHED into a transaction that has not necessarily committed. The
    #: term the canonical lane needs and the legacy lane does not.
    items_written: int = 0
    items_committed: int = 0
    items_failed: int = 0
    items_held: int = 0
    questions_asked: int = 0
    assumptions_made: int = 0
    resolver_source: str = ""
    promoted: Optional[bool] = None
    cohort: str = ""
    error: str = ""

    # ── who decided, and what it cost ─────────────────────────────────────────
    #: Which signal owned the routing decision — `prior`, `photo`, `thread`,
    #: `board_destructive`, `undo`, `confirm`, `gate_regex`, `gate_model`. The
    #: last two are the only ones that cost a model call, so "how often do we
    #: pay Haiku to be told something the free signals already knew" is a
    #: `route_owner=` histogram rather than an argument.
    route_owner: str = ""
    #: Set ONLY when the turn actually left this lane. `conversation.py` has
    #: carried `_legacy_reason` since the silent-`None` incident; it lived in a
    #: different log line from the timings, so "which escapes are slow" needed
    #: two greps and a join.
    legacy_escape_reason: str = ""

    #: The interpreter pass — the largest single block in a food turn.
    #: `cached` separates a warm prefix from a cold one: they are different
    #: latencies wearing the same stage name, and averaging them hides both.
    interpreter_model: str = ""
    interpreter_ttfb_ms: float = 0.0
    interpreter_input_tokens: int = 0
    interpreter_output_tokens: int = 0
    interpreter_cached_tokens: int = 0

    #: How much of enrichment was paid for while the interpreter was still
    #: writing. Overlap is the whole point of the speculative fetch, and an
    #: enrichment total alone cannot tell you whether it worked.
    enrichment_overlap_ms: float = 0.0

    #: The voice layer. `profile` is the compiled brief this turn used; until
    #: the compiler lands it records which renderer spoke, which is the same
    #: question asked of today's code.
    voice_profile: str = ""
    voice_model: str = ""
    #: `None`, NOT 0.0, when the voice call could not report a first byte.
    #:
    #: Only the streaming path produces `ttfb_ms` — `core/llm.py` returns none
    #: at all on the buffered path rather than a zero, for the stated reason
    #: that "the whole response arrived at once" and "it arrived instantly" are
    #: different facts a latency report must not average. The composer does not
    #: stream, so this field printed `voice_ttfb_ms=0` beside a named model on
    #: every single turn — the same lie, one layer up. Rendered `-` when unset,
    #: exactly as the marks are.
    voice_ttfb_ms: Optional[float] = None
    #: What the voice call actually cost, which IS measurable on the buffered
    #: path. Added because the field above can only ever be absent for today's
    #: composer, and a voice layer with no measurable latency at all is how an
    #: 8-second turn gets attributed entirely to the interpreter.
    voice_ms: float = 0.0
    #: Model calls beyond the first on ONE stage. Stacked retries are the
    #: documented way a bounded turn becomes an unbounded one.
    retry_count: int = 0
    #: Which floor caught the turn: `composer`, `deterministic`,
    #: `model_unavailable`, `validation`. Empty means nothing fell back.
    fallback_path: str = ""

    #: Moments, in ms from `started_at`. Kept as a dict rather than a field
    #: each because a moment is stamped by whoever makes it TRUE, and that
    #: caller should not also have to know how to subtract two clocks.
    marks: Dict[str, float] = field(default_factory=dict)

    started_at: float = field(default_factory=time.monotonic)
    version: str = TRACE_VERSION
    #: ContextVar reset token, set by `begin`. Not part of the record.
    _token: Any = None

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

    def claim_route(self, owner: str) -> None:
        """Record WHICH signal owned the routing decision. FIRST claim wins.

        Not `note(route_owner=…)`, because this field has a property the
        others do not: it is written by more than one caller and only the
        earliest is the answer. The free signals claim it before the gate is
        ever consulted (`or` short-circuits, so the model does not run), and
        the shadow coordinator calls `food_relevance` again near the end of
        the same turn — with plain overwrite semantics that second call would
        relabel every free-signal turn as `gate_model` and make the histogram
        say we pay Haiku on every turn, which is the exact opposite of what it
        exists to measure.
        """
        if owner and not self.route_owner:
            self.route_owner = owner

    def mark(self, moment: str) -> None:
        """Stamp when something became true, in ms from the turn's start.

        FIRST occurrence wins. `first_visible` is the question "when did the
        user stop waiting", and a later bubble overwriting it would answer a
        different question — the one `complete_ms` already answers.
        """
        self.marks.setdefault(
            moment, round((time.monotonic() - self.started_at) * 1000.0, 1))

    # ── derived ───────────────────────────────────────────────────────────────
    @property
    def total_ms(self) -> float:
        return round((time.monotonic() - self.started_at) * 1000.0, 1)

    def stage_ms(self, stage) -> float:
        """Total time in one stage. SUMMED, not last-wins: `resolve` runs once
        per item, and reporting the last one would make a four-item meal look
        like a one-item meal that got unlucky."""
        want = getattr(stage, "value", stage)
        return round(sum(s.duration_ms for s in self.stages
                         if s.stage == want), 1)

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
            "turn_id": self.turn_id, "user": self.user_ref,
            "mode": self.mode, "channel": self.channel,
            "operation_id": self.operation_id,
            "meal_group_id": self.meal_group_id, "cohort": self.cohort,
            "items_interpreted": self.items_interpreted,
            "items_staged": self.items_staged,
            "items_ready": self.items_ready,
            "items_attempted": self.items_attempted,
            "items_written": self.items_written,
            "items_committed": self.items_committed,
            "items_failed": self.items_failed,
            "items_held": self.items_held,
            "questions_asked": self.questions_asked,
            "assumptions_made": self.assumptions_made,
            "resolver_source": self.resolver_source,
            "promoted": self.promoted, "error": self.error,
            "total_ms": self.total_ms, "stopped_at": self.stopped_at,
            "stages": [s.as_dict() for s in self.stages],
            "version": self.version,
            # Per-stage millisecond names the latency report asks for, DERIVED
            # from `stages` rather than stored beside them. A second copy is a
            # second thing to keep true, and the stage records are already the
            # owner of how long a stage took.
            #
            "route_ms": self.stage_ms(Stage.ROUTE),
            "context_load_ms": self.stage_ms(Stage.CONTEXT),
            "interpreter_total_ms": self.stage_ms(Stage.INTERPRET),
            "policy_ms": self.stage_ms(Stage.CLARIFY),
            "enrichment_total_ms": self.stage_ms(Stage.RESOLVE),
            "execution_ms": self.stage_ms(Stage.EXECUTE),
            "voice_total_ms": self.stage_ms(Stage.RENDER),
            "route_owner": self.route_owner,
            "legacy_escape_reason": self.legacy_escape_reason,
            "interpreter_model": self.interpreter_model,
            "interpreter_ttfb_ms": self.interpreter_ttfb_ms,
            "interpreter_input_tokens": self.interpreter_input_tokens,
            "interpreter_output_tokens": self.interpreter_output_tokens,
            "interpreter_cached_tokens": self.interpreter_cached_tokens,
            "enrichment_overlap_ms": self.enrichment_overlap_ms,
            "voice_profile": self.voice_profile,
            "voice_model": self.voice_model,
            "voice_ttfb_ms": self.voice_ttfb_ms,
            "voice_ms": self.voice_ms,
            "retry_count": self.retry_count,
            "fallback_path": self.fallback_path,
            "marks": dict(self.marks),
        }

    @property
    def user_ref(self) -> str:
        """A stable pseudonym for the log line.

        The trace exists to be grepped and shipped to wherever logs go, and a raw
        account id in it makes every one of those places a system holding user
        identifiers. The hash is stable, so "find this user's other turns" still
        works from a trace you already have; it is one-way, so a log reader
        cannot turn a trace back into an account. Triage that genuinely needs the
        account has the turn id and the database.

        Salted per deployment where a salt is configured, so the same account
        does not carry one recognizable pseudonym across environments.

        ⚠ IT PROTECTS NOTHING UNLESS TWO THINGS HOLD, and on 2026-08-08 neither
        did. Stated here rather than in a document, because a control believed
        to be working is worse than one known to be off:

        1. `FOOD_TRACE_SALT` MUST BE SET. Account ids are small integers, so an
           unsalted digest is reversible by counting to a million — the whole id
           space rainbow-tables in seconds. The salt appears in no deployment
           config in this repository, which means production runs the `""`
           branch. `_salt_warning()` now says so once per process instead of
           degrading silently.

        2. THE RAW ID MUST NOT BE ON NEIGHBOURING LINES. It is. `b1_metrics`,
           `b1_quantity_operation`, `b1_answer_turn`, `request_trace` and
           `conversation` all print `user=26` in the clear, joinable to this
           line by `turn=` and now `operation=`. Pseudonymising one line of a
           stream that carries the identifier ten times over buys nothing and
           costs triage a single greppable id.

        Closing (2) is a stream-wide policy decision — it belongs at the logging
        handler, not in one module's field — and it is not made here. What is
        made here is the refusal to keep claiming the protection.
        """
        if self.user_id is None:
            return "-"
        salt = os.getenv("FOOD_TRACE_SALT", "")
        if not salt:
            _salt_warning()
        digest = hashlib.sha256(
            f"{salt}:{self.user_id}".encode("utf-8")).hexdigest()
        return f"u{digest[:12]}"

    def impossible(self) -> Tuple[str, ...]:
        """Which funnel facts this trace contradicts. Empty means self-consistent.

        FIVE STATE BOUNDARIES PLUS ONE EXECUTION COUNTER — the distinction
        matters and forcing all six into one ladder is how they get misused.

        The five boundaries are progressively stronger claims about the SAME
        item, so each is a subset of the one before:

            interpreted → staged → written → committed → visible

        `attempted` is not one of them. It counts what the executor TRIED,
        which is a fact about execution rather than a state the item reached —
        which is exactly why `attempted=3 written=2` is expected and healthy,
        while `committed=3 written=2` is impossible. Bounding `written` by
        `attempted` still holds, because a row cannot be flushed by a write
        that was never made.

        WHY THIS IS A METHOD ON THE TRACE AND NOT AN ASSERTION AT EACH CALL
        SITE. Every counter here is set by a different module, and each one is
        locally correct — the funnel goes impossible only in COMBINATION, which
        no single call site can see. This runs where the whole record finally
        exists, so a future call site cannot produce a shape nobody checks.

        Returns names rather than raising. A tracer that raises changes the
        control flow of the turn it is describing, and the failures it would
        hide are the ones it exists to surface.
        """
        broken = []
        if self.items_staged > self.items_interpreted:
            broken.append("staged>interpreted")
        if self.items_written > self.items_attempted:
            broken.append("written>attempted")
        if self.items_committed > self.items_written:
            broken.append("committed>written")
        # A visibility mark is a claim that COMMITTED TRUTH reached the reply.
        # Stamped with nothing committed, it dates an event that did not happen
        # — and because `commit_visible_ms` is a latency, the bad mark reads as
        # a fast turn rather than a missing one.
        if "commit_visible" in self.marks and self.items_committed <= 0:
            broken.append("visible_without_commit")
        return tuple(broken)

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
            f"operation={self.operation_id or '-'} "
            f"user={self.user_ref} "
            f"mode={self.mode or '-'} channel={self.channel or '-'} "
            # `resolver_cohort`, NOT `cohort`. Two unrelated rollouts were
            # printing a key of that name into one log stream with overlapping
            # vocabularies: this one is `skills/nutrition/canary.cohort_label`
            # answering "is the NUTRITION RESOLVER live for this user"
            # (`off·shadow·allowlist·canary·control·live`), while the `b1_*`
            # events carry `skills/nutrition/quantity_rollout.cohort_label`
            # answering "is this user on the B-1 QUANTITY rollout"
            # (`allowlist·cohort·control·off`). Both were correct and they
            # disagreed on the same turn — `live` here beside `allowlist`
            # there — so a query filtering `cohort=live` for natural traffic
            # swept in allowlist-only canonical turns. That is the evidence
            # class the migration directive forbids mixing.
            f"resolver_cohort={self.cohort or '-'} "
            f"stopped_at={self.stopped_at or '-'} total_ms={self.total_ms:.0f} "
            f"interpreted={self.items_interpreted} "
            f"staged={self.items_staged} ready={self.items_ready} "
            f"attempted={self.items_attempted} written={self.items_written} "
            f"committed={self.items_committed} failed={self.items_failed} "
            f"held={self.items_held} asked={self.questions_asked} "
            f"assumed={self.assumptions_made} "
            f"source={self.resolver_source or '-'} "
            f"promoted={'-' if self.promoted is None else str(self.promoted).lower()} "
            f"error={self.error or '-'} "
            # THE LINE SAYING WHETHER IT CAN BE BELIEVED. A trace whose counts
            # contradict each other is worse than a missing one: it reads as
            # measurement. This makes the contradiction greppable rather than
            # leaving it to be inferred by whoever compares two fields.
            f"funnel={','.join(self.impossible()) or 'ok'} "
            f"meal={self.meal_group_id or '-'} timings={timings or '-'} "
            # THE LATENCY HALF. Everything above answers "what did the turn
            # decide"; everything below answers "what did it cost, and who
            # paid". They are one line because joining two is how the last
            # report ended up unable to say which escapes were the slow ones.
            f"route_owner={self.route_owner or '-'} "
            f"legacy_escape={self.legacy_escape_reason or '-'} "
            f"interp_model={self.interpreter_model or '-'} "
            f"interp_ttfb_ms={self.interpreter_ttfb_ms:.0f} "
            f"interp_in={self.interpreter_input_tokens} "
            f"interp_out={self.interpreter_output_tokens} "
            f"interp_cached={self.interpreter_cached_tokens} "
            f"enrich_overlap_ms={self.enrichment_overlap_ms:.0f} "
            f"voice_profile={self.voice_profile or '-'} "
            f"voice_model={self.voice_model or '-'} "
            f"voice_ttfb_ms="
            f"{'-' if self.voice_ttfb_ms is None else format(self.voice_ttfb_ms, '.0f')} "
            f"voice_ms={self.voice_ms:.0f} "
            f"retries={self.retry_count} "
            f"fallback={self.fallback_path or '-'} "
            f"first_visible_ms={self._mark_str('first_visible')} "
            f"commit_visible_ms={self._mark_str('commit_visible')} "
            f"complete_ms={self.total_ms:.0f}")

    def _mark_str(self, moment: str) -> str:
        """`-` rather than 0 for a moment that never happened. Zero is a real
        and very different reading, and a report that cannot tell them apart
        scores every turn with no visible result as instantaneous."""
        value = self.marks.get(moment)
        return "-" if value is None else f"{value:.0f}"


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
          channel: str = "", cohort: str = "",
          operation_id: str = "") -> Optional[FoodTurnTrace]:
    """Start a trace for this turn and make it ambient. Returns None when
    tracing is off, which every caller must tolerate.

    The reset token is kept ON the trace so `finish` can restore whatever was
    ambient before rather than blanking the variable. Setting it to None
    unconditionally is wrong in any nested or inherited context: an inner
    finish would blind the outer turn for the rest of its life.
    """
    if not tracing_enabled():
        return None
    try:
        trace = FoodTurnTrace(turn_id=turn_id or "", user_id=user_id,
                              mode=mode or "", channel=channel or "",
                              cohort=cohort or "",
                              operation_id=operation_id or "")
        trace._token = CURRENT_TRACE.set(trace)
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


def claim_route(owner: str) -> None:
    """Claim the routing decision on the ambient trace. First claim wins."""
    trace = current()
    if trace is None:
        return
    try:
        trace.claim_route(owner)
    except Exception:
        pass


def mark(moment: str) -> None:
    """Stamp a moment on the ambient trace, if there is one.

    Same contract as everything else here: a turn must never fail because it
    was being measured, so no trace and any exception are both silence.
    """
    trace = current()
    if trace is None:
        return
    try:
        trace.mark(moment)
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


def committed_durably() -> None:
    """The attempted writes are now DURABLE. Called after the commit lands.

    Split from the write itself because on the canonical lane they are not the
    same event. `commit_or_load_existing` writes into the caller's transaction
    and explicitly neither commits nor rolls back, so at the moment the rows
    exist they can still be unwound by a later failure — `record_result`, the
    finaliser, or the caller's own `commit()`. A count taken there reports a
    rolled-back write as a successful one.

    The legacy lane has no such gap: its helpers commit independently, so
    counting inline was already true there. This is the canonical lane earning
    the same claim rather than inheriting it.

    PROMOTES `items_written`, and takes no argument on purpose. The executor
    owns how many rows were written — that rule predates this function — and a
    caller passing its own number would be a second opinion about a fact the
    executor already recorded.
    """
    trace = current()
    if trace is None:
        return
    try:
        trace.items_committed = trace.items_written
    except Exception:
        pass


def record_ask(*, questions: int, interpreted: int, staged: int = 0,
               ready: int = 0, held: int = 0, assumptions: int = 0,
               duration_ms: float = 0.0) -> None:
    """Record that this turn ASKED — for an origin that did not run its work
    inside a `stage(CLARIFY)` block.

    `interpreted` IS REQUIRED, and it is the only count here that is. Everything
    else defaults to zero because absent and zero mean the same thing for them —
    a turn with nothing held really did hold nothing. Not so for the funnel's
    mouth: `staged=3 interpreted=0` says typed staging accepted three items the
    model never produced, which is not a low reading but an impossible one. A
    default would let a new origin build that silently, so the signature refuses
    it instead. This is the API-level half of `FoodTurnTrace.impossible()`; the
    method catches the combinations no single call site can see, and this stops
    the one it can.

    ONE DEFINITION OF WHAT AN ASK LOOKS LIKE IN THE TRACE, because there are
    two ask origins and they are not variants of one thing
    (`tests/test_b1_reaches_both_ask_origins.py`). The pipeline origin reaches
    the same state from inside its own timing block —
    `clarifying.outcome = Outcome.ASKED` plus `note(questions_asked=…)` in
    `core/food_pipeline.py` — because that block also times `derive_semantics`
    and `decide`, which this origin has already done by the time it gets here.

    Both must set the CLARIFY stage's outcome AND the turn counter: `stopped_at`
    reads the outcome, the funnel reads the counter, and an origin that sets
    only one of them produces a trace that says a turn asked nothing while
    stopping at a question the user is looking at.
    """
    record(Stage.CLARIFY, duration_ms=duration_ms, outcome=Outcome.ASKED,
           questions=questions, ready=ready, held=held,
           assumptions=assumptions)
    note(questions_asked=questions, items_staged=staged, items_ready=ready,
         items_held=held, assumptions_made=assumptions,
         items_interpreted=interpreted)


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
    """Emit the summary line and release the ambient trace.

    Safe to call twice — the second call finds nothing and does nothing, which
    matters because the food path has more than one exit and making each of
    them prove it is the last would be worse than an idempotent finish.

    A trace that recorded NO stages is not emitted. The trace now opens at the
    top of the turn, before anything knows whether food is involved, so most
    turns end here with an empty record — and a food_trace line per non-food
    turn would swamp every rate in the dashboards with turns that never had a
    food path to measure.
    """
    trace = trace if trace is not None else current()
    if trace is None:
        return None
    try:
        token = getattr(trace, "_token", None)
        if token is not None:
            CURRENT_TRACE.reset(token)
            trace._token = None
        else:
            CURRENT_TRACE.set(None)
    except Exception:
        pass
    try:
        if trace.stages or trace.error:
            logger.info(trace.log_line())
    except Exception:
        pass
    return trace


class span:
    """Own the ambient trace for one turn, deferring to an outer owner.

        with food_trace.span(turn_id=..., channel="imessage"):
            ...

    Nesting is the point. The turn now opens its trace in the coordinator, well
    before `food_turn.run()`, so that resolution, the writes and the render all
    land inside it. But `food_turn.run()` is also called directly — by tests, by
    the simulator — and it still needs a trace when nobody above it made one.

    An inner span therefore does NOT begin or finish anything; it fills in any
    turn-level fields the outer span could not know yet and leaves ownership
    where it is. Two owners would mean the inner `finish` emitted a half-turn
    and blinded the rest of it.
    """

    __slots__ = ("_fields", "_trace", "_owner")

    def __init__(self, **fields):
        self._fields = fields
        self._trace = None
        self._owner = False

    def __enter__(self) -> Optional[FoodTurnTrace]:
        existing = current()
        if existing is not None:
            self._trace, self._owner = existing, False
            note(**self._fields)
            return existing
        self._trace = begin(**self._fields)
        self._owner = self._trace is not None
        return self._trace

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            note(error=f"turn:{exc_type.__name__}")
        if self._owner:
            finish(self._trace)
        return False           # never suppress


# ── correction linkage ────────────────────────────────────────────────────────
# There is deliberately NO correction emitter here.
#
# `preferences.CorrectionRecord.log_line()` already emits `event=food_correction`
# with the ranking snapshot and the candidate ids, and a second event carrying
# the same fact under a different name is exactly the fragmentation this module
# exists to end. What the funnel needed was one missing FIELD on that record —
# whether the corrected value was assumed by us or stated by the user — so that
# is where it was added.
