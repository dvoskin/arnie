"""The canonical lane must appear in its own trace spine.

MEASURED IN PRODUCTION 2026-08-08, build `2a8856035e66`. One iOS B-1 quantity
clarification — asked, answered by chip, committed entry 2938 at 250 kcal — left
this single `food_trace` line:

    stopped_at=context staged=0 ready=0 attempted=0 committed=0 asked=0
    timings=route:3,context:3 commit_visible_ms=- total_ms=8283

Every count zero, the funnel's drop-off reported as `context`, and 8,277 of the
8,283 ms unaccounted for. Not a sparse trace — a WRONG one, and silently so: the
line looks like a healthy turn that simply did nothing.

The spine exists to answer "this user says their lunch logged wrong, what
happened on that turn?" (`core/food_trace.py`). For the lane being migrated TO,
it answered "nothing happened after context."
"""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.pool import StaticPool

from core import food_trace
from core.food_trace import Outcome, Stage


def _traces(caplog):
    """The trace lines, and ONLY those.

    The trailing space matters: `event=food_trace_config` shares the prefix,
    fires once per process from whichever test runs first, and under a shuffled
    order that made this helper return two lines in a randomly-chosen test.
    A prefix match on a namespaced event stream is a latent order dependency.
    """
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("event=food_trace ")]


def _line(caplog):
    lines = _traces(caplog)
    assert len(lines) == 1, f"expected exactly one trace line, got {lines}"
    return lines[0]


def _field(line, key):
    for token in line.split():
        if token.startswith(f"{key}="):
            return token[len(key) + 1:]
    raise AssertionError(f"{key}= missing from {line}")


@pytest_asyncio.fixture
async def db():
    """A real session. The coordinator claims through the database, and a fake
    that returns whatever it is asked cannot tell a won claim from a duplicate
    — which is the branch that decides whether the count moves at all."""
    from db import models  # noqa: F401 — registers tables
    from db.database import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _operation(operation_id="op_trace", revision=0, user_id=1):
    return SimpleNamespace(operation_id=operation_id, id=None,
                           revision=revision, user_id=user_id)


def _meal(items=1):
    """The minimum a `ResolvedMeal` needs to be counted as ATTEMPTED: how many
    items we are about to hand the writer. Stamped before the writer runs, so a
    writer that raises still reports `attempted=N written=0`."""
    return SimpleNamespace(items=tuple(SimpleNamespace() for _ in range(items)))


def _result(items=1):
    from core.meal_commit import MealCommitResult
    return MealCommitResult(
        committed_items=tuple({"entry_id": 900 + i} for i in range(items)))


class TestAnAskIsVisibleAsAnAsk:
    """`stopped_at` is DERIVED — it scans the stages for the first
    ASKED/HELD/FAILED outcome and otherwise falls back to whatever ran last.

    So an ask origin that records no stage does not merely under-report: it
    reports the last stage that DID record as the place the turn stopped. That
    is how a turn holding a question on the user's screen said `context`.
    """

    def test_record_ask_moves_stopped_at_off_the_last_stage(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="t1", user_id=1, channel="ios")
            food_trace.record(Stage.ROUTE, duration_ms=3.0)
            food_trace.record(Stage.CONTEXT, duration_ms=3.0)
            food_trace.record_ask(questions=1, staged=1)
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "stopped_at") == "clarify"
        assert _field(line, "asked") == "1"

    def test_the_counter_and_the_outcome_move_together(self):
        """THE CONTRACT THAT KEEPS THE TWO ORIGINS HONEST. `stopped_at` reads
        the stage outcome and the funnel reads `questions_asked`; an origin
        setting only one produces a trace saying the turn asked nothing while
        stopping at a question the user is looking at. One function owns both,
        so a future third origin cannot get half of it right.
        """
        trace = food_trace.begin(turn_id="t2", user_id=1)
        food_trace.record_ask(questions=2, staged=3, ready=1, held=2)
        assert trace.questions_asked == 2
        assert trace.items_staged == 3
        assert trace.items_held == 2
        assert trace.stopped_at == "clarify"
        assert trace.stages[-1].outcome == Outcome.ASKED.value
        food_trace.finish(trace)

    def test_an_ask_outranks_a_later_stage_for_stopped_at(self):
        """The property the docstring promises and the funnel depends on: a
        turn that asked stopped at the ask, even though RENDER ran afterwards
        to produce the question. Reporting RENDER would put every
        clarification at the bottom of the funnel."""
        trace = food_trace.begin(turn_id="t3", user_id=1)
        food_trace.record(Stage.ROUTE)
        food_trace.record_ask(questions=1)
        food_trace.record(Stage.RENDER, duration_ms=5.0)
        assert trace.stopped_at == "clarify"
        food_trace.finish(trace)


class TestTheInterpreterIsOnTheClock:
    """Audit finding C5, `audits/NUTRITION_LANE_AUDIT_2026-07-28.md`:
    *"`Stage.INTERPRET` has no `record()` or `stage()` call site anywhere."*
    Eleven days later it was still the 8,277 ms this trace could not see.
    """

    def test_interpret_lands_in_the_timings_map(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="t4", user_id=1)
            food_trace.record(Stage.ROUTE, duration_ms=3.0)
            with food_trace.stage(Stage.INTERPRET):
                pass
            food_trace.record_ask(questions=1)
            food_trace.finish(trace)

        timings = _field(_line(caplog), "timings")
        assert "interpret:" in timings, \
            f"the interpreter pass is missing from the breakdown: {timings}"

    def test_a_failed_interpret_is_recorded_and_re_raised(self):
        """A tracer that swallows is a tracer that changes control flow. The
        failures this would hide are the exact ones it exists to surface."""
        trace = food_trace.begin(turn_id="t5", user_id=1)
        with pytest.raises(ValueError):
            with food_trace.stage(Stage.INTERPRET):
                raise ValueError("model exploded")
        assert trace.stages[-1].outcome == Outcome.FAILED.value
        assert trace.stopped_at == "interpret"
        assert trace.error == "interpret:ValueError"
        food_trace.finish(trace)


class TestTheCommitIsVisible:
    """A canonical commit reported `committed=0` — indistinguishable from a
    turn that wrote nothing. These drive `commit_or_load_existing` for real,
    because the question is not whether `food_trace` can count (it always
    could) but whether the coordinator tells it to.
    """

    @pytest.mark.asyncio
    async def test_the_coordinator_reports_attempted_not_committed(
            self, db, caplog):
        """THE WRITE IS NOT THE COMMIT, and the trace must not say it is.

        `commit_or_load_existing` writes into the CALLER'S transaction and
        neither commits nor rolls back. At the moment it returns, the rows are
        flushed and can still be unwound by `record_result`, the finaliser or
        the caller's own `commit()`. Counting them as committed there reports a
        rolled-back write as a successful one — a trace claiming what it does
        not know, which is the defect class this whole branch removes.
        """
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=1)

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1,
                                     operation_id="op_trace")
            await commit_or_load_existing(
                db, operation=_operation(), resolved_meal=_meal(1), writer=writer)
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "1"
        assert _field(line, "committed") == "0", \
            "the coordinator claimed a commit it had not made"
        assert "execute:" in _field(line, "timings")

    @pytest.mark.asyncio
    async def test_the_count_becomes_committed_at_the_durability_boundary(
            self, db, caplog):
        """And the promotion happens where the commit does — otherwise the
        count would simply never be true, which is not an improvement."""
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=1)

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            await commit_or_load_existing(
                db, operation=_operation("op_durable"), resolved_meal=_meal(1),
                writer=writer)
            await db.commit()
            food_trace.committed_durably()
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "1"
        assert _field(line, "committed") == "1"

    @pytest.mark.asyncio
    async def test_a_write_that_never_commits_is_never_counted(
            self, db, caplog):
        """The case the split exists for: rows written, transaction rolled
        back. The old shape reported `committed=1` for this."""
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=2)

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            await commit_or_load_existing(
                db, operation=_operation("op_rolled_back"), resolved_meal=_meal(2),
                writer=writer)
            await db.rollback()          # the caller's transaction fails
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "2", "the attempt still happened"
        assert _field(line, "committed") == "0", \
            "a rolled-back write was reported as a commit"

    @pytest.mark.asyncio
    async def test_a_multi_item_meal_counts_every_row(self, db, caplog):
        """`items_committed` is a count, not a flag. A writer that lands three
        rows and a trace that says one is the under-report this field replaced.
        """
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=3)

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            await commit_or_load_existing(
                db, operation=_operation("op_multi"), resolved_meal=_meal(3),
                writer=writer)
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "3", \
            "`items_attempted` is a count, not a flag"
        assert _field(line, "committed") == "0", \
            "nothing is committed until the caller's transaction is"

    @pytest.mark.asyncio
    async def test_a_failed_write_records_execute_as_failed(self, db, caplog):
        """The case that matters most in triage and that a count alone cannot
        express: the write was attempted and did not land. Without the stage
        wrapping the writer, this is indistinguishable from a turn that never
        tried."""
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            raise RuntimeError("ledger unavailable")

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            with pytest.raises(RuntimeError):
                await commit_or_load_existing(
                    db, operation=_operation("op_fail"), resolved_meal=_meal(1),
                    writer=writer)
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "stopped_at") == "execute"
        assert _field(line, "committed") == "0", \
            "a write that raised must not report a commit"
        assert _field(line, "error") == "execute:RuntimeError"

    @pytest.mark.asyncio
    async def test_a_writer_returning_the_wrong_type_fails_the_stage(
            self, db, caplog):
        """The type check moved inside the timed block deliberately: a writer
        that returns the wrong thing IS a failed execution, and recording it as
        a clean one would hide the only signal that something is misassembled.
        """
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return {"entry_id": 1}          # a dict, not a MealCommitResult

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            with pytest.raises(TypeError):
                await commit_or_load_existing(
                    db, operation=_operation("op_type"), resolved_meal=_meal(1),
                    writer=writer)
            food_trace.finish(trace)

        assert _field(_line(caplog), "error") == "execute:TypeError"

    @pytest.mark.asyncio
    async def test_a_duplicate_delivery_does_not_count_a_second_commit(
            self, db, caplog):
        """THE ONE THAT WOULD INFLATE THE RATE. A retried tap returns the
        original result without writing, so the second delivery must not move
        `items_committed` — otherwise every flaky network doubles the commit
        count the promotion evidence is read from.
        """
        from core.commit_coordinator import commit_or_load_existing

        calls = []

        async def writer(db_, *, operation, resolved_meal):
            calls.append(1)
            return _result(items=1)

        await commit_or_load_existing(
            db, operation=_operation("op_dupe"), resolved_meal=_meal(1),
            writer=writer)
        await db.commit()

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="redelivery", user_id=1)
            await commit_or_load_existing(
                db, operation=_operation("op_dupe"), resolved_meal=_meal(1),
                writer=writer)
            food_trace.finish(trace)

        assert len(calls) == 1, "the duplicate re-ran the writer"
        assert not [l for l in _traces(caplog)
                    if _field(l, "committed") != "0"], \
            "a duplicate delivery reported a commit it did not make"


class TestOneOperationSpansTwoTurns:
    """The ask and the answer are different turns with different `turn_id`s, so
    a turn-scoped trace cannot follow one operation without a join key. Every
    `b1_*` event already keys on the operation id.
    """

    def test_the_operation_id_is_on_the_line(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="ask-turn", user_id=1,
                                     operation_id="chat_quantity:26:ask-turn")
            food_trace.record_ask(questions=1)
            food_trace.finish(trace)

        assert _field(_line(caplog), "operation") == "chat_quantity:26:ask-turn"

    def test_absent_reads_as_a_dash_not_an_empty_token(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="plain", user_id=1)
            food_trace.record(Stage.ROUTE)
            food_trace.finish(trace)

        assert _field(_line(caplog), "operation") == "-"

    def test_an_inner_span_can_supply_the_key_the_outer_did_not_know(self):
        """How the ask side actually gets it. The turn's span opens in the
        coordinator, before anything knows an operation will exist; the id is
        noted later, from inside. An inner span that began a second trace
        instead would emit a half-turn and blind the rest.
        """
        outer = food_trace.begin(turn_id="ask", user_id=26)
        with food_trace.span(turn_id="ask", operation_id="op_late") as inner:
            assert inner is outer
        assert outer.operation_id == "op_late"
        food_trace.finish(outer)

    @pytest.mark.asyncio
    async def test_the_two_halves_carry_the_same_key(self, db, caplog):
        """The query that answers "what happened to this meal": two lines, two
        turn ids, one operation — with the commit half driven for real."""
        from core.commit_coordinator import commit_or_load_existing

        operation = "chat_quantity:26:F0DC3424"

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=1)

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            ask = food_trace.begin(turn_id="ios:ask", user_id=26,
                                   operation_id=operation)
            food_trace.record_ask(questions=1, staged=1)
            food_trace.finish(ask)

            answer = food_trace.begin(turn_id="ios:answer", user_id=26,
                                      operation_id=operation)
            await commit_or_load_existing(
                db, operation=_operation(operation), resolved_meal=_meal(1),
                writer=writer)
            await db.commit()
            food_trace.mark("commit_visible")
            food_trace.committed_durably()
            food_trace.finish(answer)

        lines = _traces(caplog)
        assert len(lines) == 2, "the answer turn emitted no trace of its own"
        assert {_field(l, "operation") for l in lines} == {operation}
        by_turn = {_field(l, "turn"): l for l in lines}
        assert _field(by_turn["ios:answer"], "committed") == "1"
        assert _field(by_turn["ios:answer"], "commit_visible_ms") != "-"
        assert _field(by_turn["ios:ask"], "asked") == "1"
        assert _field(by_turn["ios:ask"], "commit_visible_ms") == "-", \
            "the ask committed nothing and must not claim a visible commit"


class TestNoTermIsAProxyForAnother:
    """THE FUNNEL'S ONE RULE, exercised where it can actually break.

    `interpreted → staged → written → committed → visible` is a chain of
    strictly strengthening claims. Every telemetry defect in this module was one
    term silently standing in for the next, and each collapse was invisible in
    the cases where the two numbers happen to be equal — which is most cases.

    So these drive the turns where they DIVERGE. A test whose meal size, write
    count and commit count all agree cannot tell a correct implementation from
    any of the three broken ones this replaced.
    """

    @pytest.mark.asyncio
    async def test_a_partial_write_promotes_only_what_landed(self, db, caplog):
        """Three items handed to a writer that lands two.

        `committed_durably()` promotes WRITTEN, and this is the turn that says
        so: promoting `attempted` instead would report three committed rows for
        two written ones — inventing a meal item at the durability boundary.
        Every existing coordinator test hands the writer exactly as many items
        as it returns, where the two implementations are indistinguishable.
        """
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=2)          # two of the three landed

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            await commit_or_load_existing(
                db, operation=_operation("op_partial"), resolved_meal=_meal(3),
                writer=writer)
            await db.commit()
            food_trace.committed_durably()
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "3"
        assert _field(line, "written") == "2"
        assert _field(line, "committed") == "2", \
            "the durability boundary promoted what was ATTEMPTED, not written"

    @pytest.mark.asyncio
    async def test_a_writer_that_raises_still_reports_the_attempt(
            self, db, caplog):
        """`attempted=1 written=0` — the shape a failure investigation must be
        able to rule out.

        Stamped after the writer returns, a raising writer reported
        `attempted=0`: a turn that tried to write and failed looked exactly like
        a turn that never tried. The stage outcome alone does not fix it,
        because the count is what the funnel aggregates.
        """
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            raise RuntimeError("ledger unavailable")

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="answer", user_id=1)
            with pytest.raises(RuntimeError):
                await commit_or_load_existing(
                    db, operation=_operation("op_raise"),
                    resolved_meal=_meal(1), writer=writer)
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "1", \
            "a write that was tried and failed reported as never tried"
        assert _field(line, "written") == "0"
        assert _field(line, "committed") == "0"

    @pytest.mark.asyncio
    async def test_a_duplicate_delivery_attempts_nothing_and_writes_nothing(
            self, db, caplog):
        """A redelivery returns the ORIGINAL result without calling the writer.

        Counting its `committed_items` as this turn's work would double-count
        every retry a flaky network causes — the funnel would show more writes
        than there were meals. The early return is what keeps both terms zero,
        so it must stay ahead of the `attempted` stamp.
        """
        from core.commit_coordinator import commit_or_load_existing

        async def writer(db_, *, operation, resolved_meal):
            return _result(items=2)

        await commit_or_load_existing(
            db, operation=_operation("op_replay"), resolved_meal=_meal(2),
            writer=writer)
        await db.commit()

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="redelivery", user_id=1)
            await commit_or_load_existing(
                db, operation=_operation("op_replay"), resolved_meal=_meal(2),
                writer=writer)
            food_trace.note(error="redelivery")   # keep the empty-trace guard out of it
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "attempted") == "0", \
            "a redelivery counted the original write as a second attempt"
        assert _field(line, "written") == "0"

    @pytest.mark.asyncio
    async def test_the_staging_drop_is_visible_at_the_pipeline_origin(
            self, caplog):
        """`interpreted` and `staged` are different numbers, and the gap is the
        fact worth having.

        `stage_items` silently skips a raw row that is not a mapping or carries
        no food name. Reporting only the survivors made a staging REJECTION —
        the model proposed something the canonical types would not accept —
        indistinguishable from the model never proposing it. That is the mouth
        of the funnel, so an error there under-reports everything below it.
        """
        from core import food_pipeline

        data = {"items": [{"food": "chicken", "amount": 200, "unit": "g"},
                          {"food": "", "amount": 1},        # no name — dropped
                          "not a mapping",                  # not a row at all
                          {"food": "rice", "amount": 1, "unit": "cup"}]}

        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="pipeline", user_id=1)
            food_pipeline.plan_turn(data, turn_id="pipeline", message="lunch")
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "interpreted") == "4", \
            "the interpreter's own output is missing from the funnel's mouth"
        assert _field(line, "staged") == "2", \
            "rows the canonical types rejected were counted as staged"

    def test_every_origin_that_reports_staged_also_reports_interpreted(self):
        """The split that caused D1(a), applied to the new term — and aimed at
        the origin that does not exist yet.

        B-1 was once wired to the minority ask producer and emitted zero events
        in production; the same two-origin split then cost the canonical lane
        its whole trace. A term only SOME origins emit is worse than no term at
        all: a real number on one path and a structural zero on the other read
        identically in the log, so the zero looks like a measurement.

        This is a ledger over call sites, not a grep for my own edit. It fails
        when a THIRD origin starts reporting `items_staged` without the number
        it is a subset of — the shape both existing origins already got wrong
        once, and the one nobody will think to check.
        """
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for package in ("core", "api", "handlers", "skills"):
            for path in (root / package).rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text())
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    keys = {k.arg for k in node.keywords if k.arg}
                    if "items_staged" not in keys and "staged" not in keys:
                        continue
                    if keys & {"items_interpreted", "interpreted"}:
                        continue
                    offenders.append(
                        f"{path.relative_to(root)}:{node.lineno}")

        assert not offenders, (
            f"these report how many items STAGING accepted without reporting "
            f"how many the model proposed, so a staging rejection is "
            f"indistinguishable from the model proposing nothing: {offenders}")


class TestTheEmptyTraceGuardStays:
    def test_a_trace_with_no_stages_is_not_emitted(self, caplog):
        """The guard that caused the answer-turn blackout is CORRECT and stays.
        Most turns open a span before anything knows whether food is involved,
        and a line per non-food turn would swamp every rate in the dashboards.
        The fix was to record on the answer path, not to loosen this.
        """
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="not-food", user_id=1)
            food_trace.finish(trace)

        assert not _traces(caplog)

    def test_an_error_alone_is_still_emitted(self, caplog):
        """A turn that died before reaching a stage is the one you most need to
        see. `stages or error` — not `stages` — is what makes that true."""
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="died", user_id=1)
            food_trace.note(error="turn:ValueError")
            food_trace.finish(trace)

        assert _field(_line(caplog), "error") == "turn:ValueError"


# ── the coverage ledger ───────────────────────────────────────────────────────
#: Which stages a production caller actually records, as of this commit.
#:
#: A LEDGER, NOT AN ASSERTION THAT MY EDIT SURVIVED. The audit's finding was
#: "trace coverage is 5 of 7 stages" and it sat open for eleven days because
#: nothing named the gap in a place that fails. This fails in BOTH directions:
#: coverage regressing, and coverage improving without the ledger being
#: updated — so the number in the audit cannot drift away from the code again.
_RECORDED = {"route", "context", "interpret", "stage", "clarify", "resolve",
             "execute", "render"}
#: `Stage.PROMOTE` is only ever a `note()`, never a timed stage — the remaining
#: half of audit finding C5, still open.
_NOT_RECORDED = {"promote"}


def _stages_with_a_production_recorder():
    """Every `Stage.X` named in a `record()`/`stage()` call outside tests."""
    root = Path(__file__).resolve().parent.parent
    seen = set()
    for package in ("core", "api", "handlers", "skills"):
        for path in (root / package).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name not in ("record", "stage", "record_ask"):
                    continue
                if name == "record_ask":
                    seen.add("clarify")
                for arg in node.args:
                    if isinstance(arg, ast.Attribute):
                        seen.add(arg.attr.lower())
    return seen


class TestTheFunnelCoverageLedgerIsTrue:
    def test_every_stage_the_ledger_claims_has_a_recorder(self):
        recorded = _stages_with_a_production_recorder()
        missing = _RECORDED - recorded
        assert not missing, (
            f"the ledger claims these stages are timed and nothing records "
            f"them — the funnel cannot say where those turns went: "
            f"{sorted(missing)}")

    def test_the_known_gap_has_not_silently_closed(self):
        """If someone gives PROMOTE a recorder, this fails — and the audit gets
        updated instead of the finding quietly rotting as fixed-but-recorded-
        open, which is the state INTERPRET was in."""
        recorded = _stages_with_a_production_recorder()
        closed = _NOT_RECORDED & recorded
        assert not closed, (
            f"{sorted(closed)} now has a recorder — close it in "
            f"audits/NUTRITION_LANE_AUDIT_2026-07-28.md finding C5 and move it "
            f"into the recorded set")

    def test_the_ledger_covers_every_stage_in_the_enum(self):
        """No stage may be absent from both lists. A new phase that nobody
        classified is a hole in the funnel that reads as full coverage."""
        declared = {s.value for s in Stage}
        assert declared == _RECORDED | _NOT_RECORDED, (
            f"unclassified stages: "
            f"{sorted(declared ^ (_RECORDED | _NOT_RECORDED))}")
