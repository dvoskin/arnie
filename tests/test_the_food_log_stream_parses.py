"""Every line the food/B-1 measurement stream emits must survive a strict parse.

These lines ARE the measurement surface — `/admin/food-traces` counts them and
the promotion gates are argued from them. `core/food_trace.py` says outright
that the format is key=value rather than JSON so it stays greppable "from a
terminal on a box with no log tooling, which is where these questions get asked
at 2am". That only holds if the lines actually parse.

Three ways it was broken in the 2026-08-08 production capture:

    event=request_done  … outcome=ok … build=2a8856035e66 outcome=ok
    event=b1_committed  … cohort= answer_provenance=user_selected
    event=b1_not_a_replay … state=settled — operation left alone; this
                            message is a new report

A duplicate key, an empty value, and a sentence — each defeating a different
reader: `dict(pairs)` silently takes the last of the duplicate, a `k=v` split
turns the empty value into a key with no value, and prose contributes bare
tokens belonging to no key.

THE RATCHET AT THE BOTTOM IS THE POINT. Asserting that the three known lines
were fixed proves only that I edited three lines. Scanning every emitter in the
stream is what catches the FOURTH — and it did: `commit_coordinator`'s duplicate
branch and `b1_replayed` were both carrying prose that the original review
missed entirely.
"""
import ast
import logging
import re
from pathlib import Path

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
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="ios:F0DC", user_id=26, mode="strict",
                                 channel="ios", cohort="live",
                                 operation_id="chat_quantity:26:ios:F0DC")
        food_trace.record(Stage.ROUTE, duration_ms=3.0)
        with food_trace.stage(Stage.INTERPRET):
            pass
        food_trace.record_ask(questions=1, interpreted=1, staged=1)
        food_trace.note(interpreter_model="claude-sonnet-5",
                        voice_profile="clarification",
                        voice_model="claude-sonnet-5")
        food_trace.mark("first_visible")
        line = trace.log_line()
        food_trace.finish(trace)

        fields = parse(line)
        assert fields["operation"] == "chat_quantity:26:ios:F0DC"
        assert fields["resolver_cohort"] == "live"

    def test_an_empty_trace_line_parses(self):
        """Every optional field absent — the shape that exposes any emitter
        that forgot its `or '-'`."""
        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin()
        food_trace.record(Stage.ROUTE)
        fields = parse(trace.log_line())
        food_trace.finish(trace)

        assert fields["operation"] == "-"
        assert fields["turn"] == "-"

    def test_a_value_containing_spaces_cannot_break_the_line(self):
        """The failure this class of bug actually takes in the wild. A food
        name, an error string or a detail with a space in it splits into bare
        tokens and silently truncates the rest of the line — which is exactly
        how `timings=` lost every stage but its first, per the comment in
        `log_line`.
        """
        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="t", user_id=1,
                                 operation_id="chat_quantity:26:has space")
        food_trace.record(Stage.ROUTE)
        food_trace.note(error="pipeline: two words", resolver_source="a b")
        line = trace.log_line()
        food_trace.finish(trace)

        with pytest.raises(AssertionError, match="bare token"):
            parse(line)

    def test_ttfb_is_absent_rather_than_zero_when_unmeasurable(self):
        """`core/llm.py` returns no `ttfb_ms` at all on the buffered path,
        because "arrived at once" and "arrived instantly" are different facts.
        The trace has to keep that distinction rather than flatten it to a zero
        beside a confidently-named model.
        """
        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="t", user_id=1)
        food_trace.record(Stage.RENDER)
        food_trace.note(voice_model="claude-sonnet-5")
        fields = parse(trace.log_line())
        food_trace.finish(trace)

        assert fields["voice_ttfb_ms"] == "-"
        assert fields["voice_model"] == "claude-sonnet-5"

    def test_a_measured_ttfb_is_reported(self):
        from core import food_trace
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="t", user_id=1)
        food_trace.record(Stage.RENDER)
        food_trace.note(voice_model="claude-sonnet-5", voice_ttfb_ms=412.0,
                        voice_ms=890.0)
        fields = parse(trace.log_line())
        food_trace.finish(trace)

        assert fields["voice_ttfb_ms"] == "412"
        assert fields["voice_ms"] == "890"


class TestTheRequestDoneLine:
    def _line(self, caplog):
        return next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("event=request_done"))

    def test_outcome_appears_exactly_once(self, caplog):
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            RequestTrace(turn_id="ios:F0DC", channel="ios", command="turn",
                         user_id=26).done(outcome="ok")

        assert parse(self._line(caplog))["outcome"] == "ok"

    def test_a_noted_outcome_wins_and_does_not_double_up(self, caplog):
        """The dangerous half, and the one a duplicate-key check alone would
        miss. `setdefault` preserved a previously-noted outcome in `fields`
        while the positional argument still printed first — so one line
        asserted two DIFFERENT outcomes for one request and a `dict(pairs)`
        reader silently took whichever came last.
        """
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            trace = RequestTrace(turn_id="t", channel="ios", command="turn",
                                 user_id=1)
            trace.note(outcome="error:Timeout")
            trace.done(outcome="ok")

        assert parse(self._line(caplog))["outcome"] == "error:Timeout"

    def test_the_line_and_the_persisted_row_cannot_disagree(self, caplog):
        """`persist()` writes `fields["outcome"]`; the line now resolves from
        the same place. Without this they were two independent readings of one
        request."""
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            trace = RequestTrace(turn_id="t", channel="ios", command="turn",
                                 user_id=1)
            trace.note(outcome="error:Boom")
            trace.done(outcome="ok")

        assert parse(self._line(caplog))["outcome"] == trace.fields["outcome"]

    def test_other_noted_fields_still_ride_the_line(self, caplog):
        """Excluding `outcome` from `extra` must not drop everything else with
        it — the obvious way to get this fix wrong."""
        from core.request_trace import RequestTrace

        with caplog.at_level(logging.INFO, logger="core.request_trace"):
            trace = RequestTrace(turn_id="t", channel="ios", command="turn",
                                 user_id=1)
            trace.note(idempotency="replay", lane="canonical")
            trace.done()

        fields = parse(self._line(caplog))
        assert fields["idempotency"] == "replay"
        assert fields["lane"] == "canonical"


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
        """`b1_shown` printed its cohort with no `or '-'` — which is how a
        neighbouring line came to read `cohort=` with nothing after it."""
        from types import SimpleNamespace

        from core import b1_metrics

        field = SimpleNamespace(options=[SimpleNamespace(source=None)],
                                attribute=SimpleNamespace(value="quantity"))

        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            b1_metrics.shown(operation_id="op1", user_id=26, cohort="",
                             locale="en", field=field)
            b1_metrics.committed(operation_id="op1", user_id=26, entry_id=1,
                                 calories=1.0)

        for line in self._lines(caplog):
            assert parse(line)["b1_cohort"] == "-"

    def test_the_two_rollouts_do_not_share_a_key(self, caplog):
        """`food_trace` carries the nutrition-resolver rollout; the `b1_*`
        events carry the B-1 quantity rollout. On 2026-08-08 they printed
        `live` and `allowlist` for one turn under one key called `cohort`, so a
        query filtering either got a population neither describes.
        """
        from types import SimpleNamespace

        from core import b1_metrics, food_trace
        from core.food_trace import Stage

        trace = food_trace.begin(turn_id="t", user_id=26, cohort="live")
        food_trace.record(Stage.ROUTE)
        trace_fields = parse(trace.log_line())
        food_trace.finish(trace)

        field = SimpleNamespace(
            options=[SimpleNamespace(source=SimpleNamespace(value="ontology"))],
            attribute=SimpleNamespace(value="quantity"))
        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            b1_metrics.shown(operation_id="op1", user_id=26,
                             cohort="allowlist", locale="en", field=field)
        b1_fields = parse(self._lines(caplog)[0])

        assert trace_fields["resolver_cohort"] == "live"
        assert b1_fields["b1_cohort"] == "allowlist"
        # The whole point: no key means both things at once.
        assert "cohort" not in trace_fields and "cohort" not in b1_fields
        assert set(trace_fields) & set(b1_fields) & {"resolver_cohort",
                                                     "b1_cohort"} == set()


# ── the ratchet ───────────────────────────────────────────────────────────────
#: The events that are COUNTED — the measurement stream a reader parses, as
#: distinct from the diagnostic warnings that exist to be read by a person. A
#: new name belongs here the moment something aggregates it.
MEASUREMENT_EVENTS = frozenset({
    "food_trace", "request_done",
    "b1_shown", "b1_answered", "b1_committed", "b1_abandoned", "b1_corrected",
    "b1_declined", "b1_partial", "b1_not_a_replay", "b1_replayed",
    "b1_answer_held", "b1_owns_turn", "b1_answer",
    "meal_commit", "commit_coordinator", "canonical_meal_written",
})

#: An em-dash starts prose in every instance this codebase has produced, and a
#: `k=v` stream has no legitimate use for one.
_PROSE = re.compile(r"—")

_SCANNED = ("core", "api", "handlers", "skills")


def _emitted_format_strings():
    """Every string literal that begins a `k=v` event line, with its location.

    Read from the AST rather than by grepping lines, because these format
    strings are routinely split across several source lines by the formatter —
    which is exactly how the prose in `b1_not_a_replay` stayed invisible to a
    line-oriented search for two months.
    """
    root = Path(__file__).resolve().parent.parent
    for package in _SCANNED:
        for path in (root / package).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:                       # not ours to police
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, str):
                    continue
                if not node.value.startswith("event="):
                    continue
                name = node.value[len("event="):].split()[0].split("=")[0]
                yield (f"{path.relative_to(root)}:{node.lineno}",
                       name, node.value)


class TestNoEmitterMayCarryProse:
    """THE TEST THAT FOUND SOMETHING. Written to protect two lines the review
    had already fixed, it immediately failed on two it had missed —
    `commit_coordinator`'s duplicate branch and `b1_replayed`, both counted
    events, both trailing a sentence. That is the difference between asserting
    an edit happened and asserting a property holds.
    """

    def test_the_scanner_sees_the_stream_it_claims_to_police(self):
        """A scanner that silently matches nothing is a green test that
        protects nothing — the failure mode this whole file exists to catch,
        one level up."""
        found = {name for _, name, _ in _emitted_format_strings()}
        missing = MEASUREMENT_EVENTS - found
        assert not missing, (
            f"these measurement events have no emitter the scanner can see, "
            f"so nothing below is checking them: {sorted(missing)}")

    def test_no_measurement_event_trails_prose(self):
        offenders = [
            (where, name) for where, name, text in _emitted_format_strings()
            if name in MEASUREMENT_EVENTS and _PROSE.search(text)]
        assert not offenders, (
            "these lines are parsed by readers and must stay strictly k=v; "
            f"move the explanation to the docstring: {offenders}")

    def test_no_measurement_event_declares_a_key_twice(self):
        """`request_done` printed `outcome=` twice for its whole life because
        the duplicate came from a dict appended after the format string. This
        catches the simpler case — the same key written twice in one literal —
        which is the version a copy-paste produces.
        """
        offenders = []
        for where, name, text in _emitted_format_strings():
            if name not in MEASUREMENT_EVENTS:
                continue
            keys = re.findall(r"(\w+)=", text)
            duplicated = {k for k in keys if keys.count(k) > 1}
            if duplicated:
                offenders.append((where, name, sorted(duplicated)))
        assert not offenders, f"duplicate keys in one line: {offenders}"
