"""The canonical lane must appear in its own trace spine.

MEASURED IN PRODUCTION 2026-08-08, build `2a8856035e66`. One iOS B-1 quantity
clarification — asked, answered by chip, committed entry 2938 at 250 kcal — left
this single `food_trace` line:

    stopped_at=context staged=0 ready=0 attempted=0 committed=0 asked=0
    timings=route:3,context:3 commit_visible_ms=- total_ms=8283

Every count zero, the funnel's drop-off reported as `context`, and 8,277 of the
8,283 ms unaccounted for. Not a sparse trace — a WRONG one, and silently so: the
line looks like a healthy turn that simply did nothing. Three separate causes,
one per test class below.

The spine exists to answer "this user says their lunch logged wrong, what
happened on that turn?" (`core/food_trace.py`). For the lane we are migrating
TO, it answered "nothing happened after context."
"""
import logging

import pytest

from core import food_trace
from core.food_trace import Outcome, Stage


def _line(caplog):
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("event=food_trace")]
    assert len(lines) == 1, f"expected exactly one trace line, got {lines}"
    return lines[0]


def _field(line, key):
    for token in line.split():
        if token.startswith(f"{key}="):
            return token[len(key) + 1:]
    raise AssertionError(f"{key}= missing from {line}")


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
            # Without this the trace stops at `context` — the production line.
            food_trace.record_ask(questions=1, staged=1)
            food_trace.finish(trace)

        line = _line(caplog)
        assert _field(line, "stopped_at") == "clarify"
        assert _field(line, "asked") == "1"

    def test_the_counter_and_the_outcome_move_together(self):
        """Two readers, one fact. `stopped_at` reads the stage outcome and the
        funnel reads `questions_asked`; an origin that set only one of them
        produced a trace saying the turn asked nothing while stopping at a
        question. `record_ask` is the single definition so they cannot drift.
        """
        trace = food_trace.begin(turn_id="t2", user_id=1)
        food_trace.record_ask(questions=2, staged=3, ready=1, held=2)
        assert trace.questions_asked == 2
        assert trace.items_staged == 3
        assert trace.items_held == 2
        assert trace.stopped_at == "clarify"
        assert trace.stages[-1].outcome == Outcome.ASKED.value
        food_trace.finish(trace)

    def test_both_ask_origins_have_a_recorder(self):
        """`core/food_turn.py` has two ask origins and they are not variants of
        one thing (`tests/test_b1_reaches_both_ask_origins.py`). B-1 was once
        wired to the minority producer and emitted ZERO events in production;
        the same split then cost the trace its CLARIFY stage. Pin that both
        origins record, so the next reader cannot fix one and miss the other.
        """
        pipeline = open("core/food_pipeline.py").read()
        interpreter = open("core/food_turn.py").read()
        assert "Outcome.ASKED" in pipeline, \
            "the pipeline ask origin no longer marks its CLARIFY stage ASKED"
        assert "record_ask" in interpreter, \
            "the interpreter ask origin — where most asks come from — no " \
            "longer records an ask on the trace"


class TestTheInterpreterIsOnTheClock:
    """Audit finding C5, `audits/NUTRITION_LANE_AUDIT_2026-07-28.md`:
    *"`Stage.INTERPRET` has no `record()` or `stage()` call site anywhere; so
    the funnel cannot answer 'how many turns died in interpretation' — the
    largest single block in a food turn."* Eleven days later it was still the
    8,277 ms this trace could not see.
    """

    def test_interpret_is_recorded_somewhere_in_production(self):
        source = open("core/food_turn.py").read()
        assert "Stage.INTERPRET" in source, \
            "Stage.INTERPRET has no production call site — audit finding C5"

    def test_interpret_lands_in_the_timings_map(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="t3", user_id=1)
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
        failures this would hide are the exact ones it exists to surface.
        """
        trace = food_trace.begin(turn_id="t4", user_id=1)
        with pytest.raises(ValueError):
            with food_trace.stage(Stage.INTERPRET):
                raise ValueError("model exploded")
        assert trace.stages[-1].outcome == Outcome.FAILED.value
        assert trace.stopped_at == "interpret"
        food_trace.finish(trace)


class TestTheCommitIsVisible:
    """A canonical commit reported `committed=0` — indistinguishable from a turn
    that wrote nothing. Only the executor may move `items_committed`, so the
    count moves where the write happens, not where settlement decided to write.
    """

    def test_the_executor_moves_the_committed_count(self):
        trace = food_trace.begin(turn_id="t5", user_id=1)
        with food_trace.stage(Stage.EXECUTE) as writing:
            writing.counts["committed"] = 1
        food_trace.note(items_attempted=1, items_committed=1)
        assert trace.items_committed == 1
        assert "execute" in trace.reached
        food_trace.finish(trace)

    def test_commit_visible_is_bound_when_a_row_lands(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="t6", user_id=1)
            food_trace.record(Stage.EXECUTE, outcome=Outcome.OK)
            food_trace.mark("commit_visible")
            food_trace.finish(trace)

        assert _field(_line(caplog), "commit_visible_ms") != "-", \
            "a committed meal must say when its truth got words"

    def test_the_canonical_commit_path_records_execute(self):
        """The coordinator is the one place every canonical lane's write passes
        through, which is why the count moves there and not in each caller.
        """
        source = open("core/commit_coordinator.py").read()
        assert "Stage.EXECUTE" in source
        assert "items_committed" in source


class TestOneOperationSpansTwoTurns:
    """The ask and the answer are different turns with different `turn_id`s, so
    a turn-scoped trace cannot follow one operation without a join key. Every
    `b1_*` event already keys on the operation id; the trace now says the same
    word rather than inventing a second correlation id.
    """

    def test_the_operation_id_is_on_the_line(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="ask-turn", user_id=1,
                                     operation_id="chat_quantity:26:ask-turn")
            food_trace.record_ask(questions=1)
            food_trace.finish(trace)

        assert _field(_line(caplog), "operation") == "chat_quantity:26:ask-turn"

    def test_absent_reads_as_a_dash_not_an_empty_token(self, caplog):
        """An empty value breaks a `k=v` split into a bare token, which is how
        a neighbouring line already prints `cohort=` with nothing after it.
        """
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="plain", user_id=1)
            food_trace.record(Stage.ROUTE)
            food_trace.finish(trace)

        assert _field(_line(caplog), "operation") == "-"

    def test_the_two_halves_carry_the_same_key(self, caplog):
        """What the join actually has to survive: two lines, two turn ids, one
        operation. This is the query that answers "what happened to this meal".
        """
        operation = "chat_quantity:26:F0DC3424"
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            ask = food_trace.begin(turn_id="ios:ask", user_id=26,
                                   operation_id=operation)
            food_trace.record_ask(questions=1, staged=1)
            food_trace.finish(ask)

            answer = food_trace.begin(turn_id="ios:answer", user_id=26,
                                      operation_id=operation)
            food_trace.record(Stage.EXECUTE, outcome=Outcome.OK)
            food_trace.note(items_committed=1)
            food_trace.mark("commit_visible")
            food_trace.finish(answer)

        lines = [r.getMessage() for r in caplog.records
                 if r.getMessage().startswith("event=food_trace")]
        assert len(lines) == 2, "the answer turn emitted no trace of its own"
        assert {_field(line, "operation") for line in lines} == {operation}
        assert {_field(line, "turn") for line in lines} == {"ios:ask", "ios:answer"}
        # The half that committed says so; the half that asked does not.
        by_turn = {_field(line, "turn"): line for line in lines}
        assert _field(by_turn["ios:answer"], "committed") == "1"
        assert _field(by_turn["ios:ask"], "asked") == "1"


class TestBothAnswerRoutesAreTraced:
    """A typed answer and a chip tap reach settlement by different routes, and
    NEITHER opened a span. The typed path returns from `run_turn` before
    `Stage.ROUTE` is recorded, so `finish()` found an empty record and logged
    nothing at all; the chip path never called `run_turn`.
    """

    def test_the_chip_endpoint_opens_a_span(self):
        source = open("api/chat.py").read()
        assert "food_trace" in source, \
            "POST /chat/answer commits meals and opens no trace"
        assert "operation_id=req.operation_id" in source, \
            "the answer trace must carry the join key"

    def test_the_typed_answer_branch_records_before_it_returns(self):
        source = open("core/conversation.py").read()
        marker = "THE TRACE THIS BRANCH NEVER LEFT"
        assert marker in source, \
            "the B-1 answer branch returns before any stage is recorded, so " \
            "finish() emits nothing"

    def test_a_trace_with_no_stages_is_still_not_emitted(self, caplog):
        """The guard that caused the blackout is CORRECT and stays. Most turns
        open a span before anything knows whether food is involved, and a line
        per non-food turn would swamp every rate in the dashboards. The fix was
        to record on the answer path, not to loosen this.
        """
        with caplog.at_level(logging.INFO, logger="core.food_trace"):
            trace = food_trace.begin(turn_id="not-food", user_id=1)
            food_trace.finish(trace)

        assert not [r for r in caplog.records
                    if r.getMessage().startswith("event=food_trace")]
