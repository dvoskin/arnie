"""Every line the food/B-1 stream emits must survive a strict `k=v` parse.

These lines are the measurement surface — `/admin/food-traces` counts them, the
promotion gates are argued from them, and `core/food_trace.py` says outright
that the format is key=value rather than JSON so it stays greppable "from a
terminal on a box with no log tooling, which is where these questions get asked
at 2am".

Three ways that promise was broken in the 2026-08-08 production capture, one
class each below:

    event=request_done  … outcome=ok … build=2a8856035e66 outcome=ok
    event=b1_committed  … cohort= answer_provenance=user_selected
    event=b1_not_a_replay … state=settled — operation left alone; this
                            message is a new report

A duplicate key, an empty value, and a sentence. Each is survivable alone and
each defeats a different reader: `dict(pairs)` silently takes the last of the
duplicate, a `k=v` split turns the empty value into a key with no value, and the
prose contributes bare tokens that belong to no key at all.
"""
import logging

import pytest


def parse(line: str) -> dict:
    """A strict reader — the kind anything consuming this stream would write.

    Deliberately unforgiving: every whitespace-separated token must be exactly
    one `k=v` pair, and no key may repeat. A tolerant parser is what let all
    three defects live, because each one still "worked" for a reader that
    shrugged.
    """
    fields = {}
    for token in line.split():
        assert "=" in token, f"bare token {token!r} in {line!r}"
        key, _, value = token.partition("=")
        assert key, f"empty key in {token!r}"
        assert value != "", (
            f"{key}= has an empty value in {line!r} — use '-' for unknown, "
            f"which is what every other emitter does")
        assert key not in fields, f"duplicate key {key!r} in {line!r}"
        fields[key] = value
    return fields


class TestTheTraceLine:
    def test_a_full_trace_line_parses(self):
        from core import food_trace
        from core.food_trace import Outcome, Stage

        trace = food_trace.begin(turn_id="ios:F0DC", user_id=26, mode="strict",
                                 channel="ios", cohort="live",
                                 operation_id="chat_quantity:26:ios:F0DC")
        food_trace.record(Stage.ROUTE, duration_ms=3.0)
        food_trace.record(Stage.CONTEXT, duration_ms=3.0)
        with food_trace.stage(Stage.INTERPRET):
            pass
        food_trace.record_ask(questions=1, staged=1)
        food_trace.note(interpreter_model="claude-sonnet-5",
                        voice_profile="clarification",
                        voice_model="claude-sonnet-5")
        food_trace.mark("first_visible")
        line = trace.log_line()
        food_trace.finish(trace)

        fields = parse(line)
        assert fields["event"] == "food_trace"
        assert fields["operation"] == "chat_quantity:26:ios:F0DC"

    def test_an_empty_trace_line_parses(self):
        """Every optional field absent — the shape that produces empty values
        if any emitter forgot its `or '-'`."""
        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin()
        food_trace.record(Stage.ROUTE)
        line = trace.log_line()
        food_trace.finish(trace)

        fields = parse(line)
        assert fields["operation"] == "-"
        assert fields["turn"] == "-"

    def test_ttfb_is_absent_rather_than_zero_when_unmeasurable(self):
        """`core/llm.py` returns no `ttfb_ms` at all on the buffered path,
        because "arrived at once" and "arrived instantly" are different facts.
        The trace field has to keep that distinction rather than flatten it to
        a zero next to a confidently-named model.
        """
        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="t", user_id=1)
        food_trace.record(Stage.RENDER)
        food_trace.note(voice_model="claude-sonnet-5")
        fields = parse(trace.log_line())
        food_trace.finish(trace)

        assert fields["voice_ttfb_ms"] == "-", \
            "a model that cannot report a first byte must not report zero"
        assert fields["voice_model"] == "claude-sonnet-5"


class TestTheRequestDoneLine:
    def test_outcome_appears_exactly_once(self, caplog):
        """`fields.setdefault("outcome", …)` put the key into the same dict the
        trailing `extra` is built from, so the key was duplicated on every line
        this ever emitted."""
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            trace = RequestTrace(turn_id="ios:F0DC", channel="ios",
                                 command="turn", user_id=26)
            trace.done(outcome="ok")

        line = next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("event=request_done"))
        assert parse(line)["outcome"] == "ok"

    def test_a_noted_outcome_wins_and_does_not_double_up(self, caplog):
        """The dangerous half. `setdefault` preserved a previously-noted
        outcome in `fields` while the positional argument still printed first —
        so one line asserted two DIFFERENT outcomes for one request, and a
        `dict(pairs)` reader silently took whichever came last.
        """
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            trace = RequestTrace(turn_id="t", channel="ios", command="turn",
                                 user_id=1)
            trace.note(outcome="error:Timeout")
            trace.done(outcome="ok")

        line = next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("event=request_done"))
        fields = parse(line)
        assert fields["outcome"] == "error:Timeout", \
            "the explicitly noted outcome must be the one reported"

    def test_the_line_and_the_persisted_row_agree(self, caplog):
        """`persist()` writes `fields["outcome"]`. The line now resolves from
        the same place, so a row and its line cannot disagree."""
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            trace = RequestTrace(turn_id="t", channel="ios", command="turn",
                                 user_id=1)
            trace.note(outcome="error:Boom")
            trace.done(outcome="ok")

        line = next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("event=request_done"))
        assert parse(line)["outcome"] == trace.fields.get("outcome")


class TestTheB1Lines:
    """`b1_metrics` is the funnel B-1 promotion is argued from."""

    def _lines(self, caplog):
        return [r.getMessage() for r in caplog.records
                if r.getMessage().startswith("event=b1_")]

    def test_every_b1_metric_line_parses(self, caplog):
        from types import SimpleNamespace

        from core import b1_metrics

        field = SimpleNamespace(
            options=[SimpleNamespace(source=SimpleNamespace(value="ontology"))],
            attribute=SimpleNamespace(value="quantity"))

        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            b1_metrics.shown(operation_id="op1", user_id=26, cohort="allowlist",
                             locale="en", field=field)
            b1_metrics.answered(operation_id="op1", user_id=26,
                                outcome="applied", modality="chip",
                                cohort="allowlist", selected_source="ontology",
                                provenance="user_selected", grams=200.0)
            b1_metrics.committed(operation_id="op1", user_id=26, entry_id=2938,
                                 calories=250.0, cohort="allowlist",
                                 selected_source="ontology", repairs=0,
                                 rounds=1)
            b1_metrics.abandoned(operation_id="op1", user_id=26,
                                 cohort="allowlist")
            b1_metrics.declined(user_id=26, reason="not_in_cohort",
                                cohort="control")
            b1_metrics.corrected(operation_id="op1", user_id=26, entry_id=2938,
                                 minutes=4.0, cohort="allowlist")

        lines = self._lines(caplog)
        assert len(lines) == 6
        for line in lines:
            parse(line)

    def test_an_absent_cohort_reads_as_a_dash_on_every_line(self, caplog):
        """`b1_shown` printed its cohort with no `or '-'`, which is how a
        neighbouring line came to read `cohort=` with nothing after it."""
        from types import SimpleNamespace

        from core import b1_metrics

        field = SimpleNamespace(
            options=[SimpleNamespace(source=None)],
            attribute=SimpleNamespace(value="quantity"))

        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            b1_metrics.shown(operation_id="op1", user_id=26, cohort="",
                             locale="en", field=field)
            b1_metrics.committed(operation_id="op1", user_id=26, entry_id=1,
                                 calories=1.0)

        for line in self._lines(caplog):
            assert parse(line)["b1_cohort"] == "-"

    def test_the_two_rollouts_do_not_share_a_key(self):
        """`food_trace` carries the nutrition-resolver rollout and the `b1_*`
        events carry the B-1 quantity rollout. They printed `live` and
        `allowlist` for one turn under one key called `cohort`, so a query
        filtering either name got a population neither describes.
        """
        from types import SimpleNamespace

        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="t", user_id=26, cohort="live")
        food_trace.record(Stage.ROUTE)
        trace_fields = parse(trace.log_line())
        food_trace.finish(trace)

        assert "resolver_cohort" in trace_fields
        assert "cohort" not in trace_fields, \
            "the bare key is what made the two rollouts indistinguishable"
        assert trace_fields["resolver_cohort"] == "live"

    def test_not_a_replay_carries_no_prose(self):
        """The behaviour is correct and proven — a settled operation declining
        a message that was never addressed to it. Only its encoding was wrong.
        """
        source = open("core/b1_answer_turn.py").read()
        assert "operation left alone; this message is a new report" not in source
        assert "disposition=left_alone" in source

    def test_meal_commit_duplicate_carries_no_prose(self):
        source = open("core/meal_commit.py").read()
        assert "the write already happened; returning the original result" \
            not in source
        assert "resolution=original_result" in source
