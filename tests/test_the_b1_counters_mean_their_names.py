"""`repairs`, `rounds`, `cohort` and `latency_ms` must report what they claim.

MEASURED 2026-08-08. One iOS B-1 quantity clarification — a single chip tap,
answered cleanly, no repair anywhere in the turn — produced:

    b1_answered  … cohort=- latency_ms=10894 provenance=user_selected
    b1_committed … repairs=1 cohort=- latency_ms=10919 rounds=1

Four numbers, four different failures, none of which changed what the user got:

    repairs      read `owned.revision`, which this codebase documents as
                 deliberately NOT moving on a repair. It moves 0→1 exactly once
                 per committed operation, so the metric was a restatement of
                 "did this commit" wearing the name of the rate B-1.8 is judged
                 by.
    rounds       never passed by the only caller, so it reported its signature
                 default of 1 forever — while `round_index` sat durably in the
                 observation rows the whole time.
    cohort       never persisted on the operation, so the answer turn had
                 nothing to read. The funnel could count asks per cohort and
                 neither answers nor commits: it broke at the conversion step,
                 which is the only step promotion asks about.
    latency_ms   measured from `row.created_at`, which Postgres stamps with the
                 TRANSACTION's start. The user answered in 2,560 ms; 8,334 ms
                 of the reported 10,894 was our own interpreter.

Every one of them reads plausible. That is why they survived a green suite.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


class TestRepairsAreCountedNotInferred:
    def test_the_revision_is_not_a_repair_count(self):
        """The claim, from the code itself. `core/b1_quantity_operation.py`
        states it as a design property and `core/b1_answer_turn.py` implements
        it — a repair returns before the revision moves. Anything reading the
        revision as a repair count contradicts both.
        """
        ops = open("core/b1_quantity_operation.py").read()
        turn = open("core/b1_answer_turn.py").read()
        assert "a repair deliberately does not bump it" in ops
        assert "revision does NOT move" in turn

    def test_the_commit_metric_no_longer_reads_the_revision(self):
        source = open("core/b1_answer_turn.py").read()
        assert 'repairs=max(0, int(getattr(owned, "revision", 0) or 0))' \
            not in source, \
            "repairs is back to reading the revision, which does not move on " \
            "a repair"
        assert "_answer_counts" in source

    @pytest.mark.asyncio
    async def test_a_clean_single_tap_reports_no_repairs(self):
        from core.b1_answer_turn import _answer_counts

        rounds, repairs = await _answer_counts(_CountingDB([("applied", 1)]),
                                               "op1")
        assert (rounds, repairs) == (1, 0)

    @pytest.mark.asyncio
    async def test_repairs_are_counted_from_the_durable_observations(self):
        from core.b1_answer_turn import _answer_counts

        rounds, repairs = await _answer_counts(
            _CountingDB([("repair", 2), ("applied", 1)]), "op1")
        assert repairs == 2, "two repairs preceded this commit"
        assert rounds == 3, "three answer attempts reached the operation"

    @pytest.mark.asyncio
    async def test_a_failed_count_degrades_to_the_common_shape(self):
        """A commit metric must not be lost to a failed aggregate, and
        `(1, 0)` is the shape of the overwhelming majority of answers — an
        honest default rather than a guess that inflates either number.
        """
        from core.b1_answer_turn import _answer_counts

        assert await _answer_counts(_ExplodingDB(), "op1") == (1, 0)


class TestRoundsIsPassed:
    def test_the_caller_supplies_rounds(self):
        source = open("core/b1_answer_turn.py").read()
        assert "repairs=repairs, rounds=rounds" in source, \
            "rounds is back to its unpassed signature default of 1"

    def test_the_durable_counter_still_exists_to_be_read(self):
        """`round_index` is written per attempt and is the value `rounds`
        reports. If this bookkeeping goes, the metric silently flattens again.
        """
        source = open("core/b1_answer_turn.py").read()
        assert "round_index=int(prior) + 1" in source


class TestCohortSurvivesTheTurnBoundary:
    def test_the_cohort_is_persisted_on_the_operation(self):
        """Not a dropped argument — it was structurally absent. `_encode` had
        no such key and `OwnedOperation` had no such field, which is why
        `_observe` reached for it with a `getattr` default and wrote an empty
        cohort into the promotion evidence table.
        """
        source = open("core/b1_quantity_operation.py").read()
        assert '"cohort": cohort,' in source, \
            "the ask no longer pins its cohort to the operation"
        assert 'cohort=str(data.get("cohort") or "")' in source, \
            "the answer turn no longer reads the cohort back"

    def test_the_answer_and_the_commit_both_report_it(self):
        source = open("core/b1_answer_turn.py").read()
        assert source.count('cohort=str(getattr(owned, "cohort", "") or "")') >= 3, \
            "answered, committed and the observation must all carry the cohort"

    def test_an_operation_written_before_the_field_existed_still_reads(self):
        """Old rows carry no cohort. `-` is honest for those; re-deriving one
        from today's rollout would attach a label the operation was never
        decided under.
        """
        import json

        from core.b1_quantity_operation import _decode_asked_at

        legacy = json.loads(json.dumps({"slice": "b1_quantity"}))
        assert legacy.get("cohort", "") == ""
        assert _decode_asked_at(legacy) is None


class TestLatencyMeasuresTheUser:
    def test_the_ask_is_stamped_by_the_application(self):
        """`created_at` is `server_default=func.now()`, and Postgres `now()` is
        `transaction_timestamp()` — the time the enclosing transaction began,
        not the time the row was inserted. The insert rides the turn's
        transaction, which opens before the interpreter's model call.
        """
        source = open("core/b1_quantity_operation.py").read()
        assert '"asked_at": asked_at,' in source
        assert "asked_at=_now().isoformat()" in source

    def test_the_stamp_wins_over_the_rows_birthday(self):
        from core.b1_quantity_operation import OwnedOperation

        transaction_start = datetime(2026, 8, 8, 20, 38, 56)
        question_shown = datetime(2026, 8, 8, 20, 39, 5)
        owned = OwnedOperation(
            row=SimpleNamespace(created_at=transaction_start,
                                operation_id="op1", revision=0,
                                status="awaiting_answer", expires_at=None),
            interaction=None, item={}, asked_at_stamp=question_shown)

        assert owned.asked_at == question_shown

    def test_an_operation_without_a_stamp_falls_back(self):
        """Rows opened before the stamp existed must still be answerable. The
        approximation is exactly as good as the behaviour it replaced, and the
        error is bounded by that turn's own duration.
        """
        from core.b1_quantity_operation import OwnedOperation

        created = datetime(2026, 8, 8, 20, 38, 56)
        owned = OwnedOperation(
            row=SimpleNamespace(created_at=created, operation_id="op1",
                                revision=0, status="awaiting_answer",
                                expires_at=None),
            interaction=None, item={})

        assert owned.asked_at == created

    def test_the_reported_latency_excludes_backend_time(self, caplog):
        """The production arithmetic, as a test. An answer given 2,560 ms after
        the chips appeared, on a turn whose backend spent 8,334 ms before them,
        must report 2,560 — not 10,894.
        """
        import logging

        from core import b1_metrics

        shown = b1_metrics._ms_since  # noqa: F841 — documents the helper used
        question_shown = _clock_now() - timedelta(milliseconds=2560)

        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            b1_metrics.answered(operation_id="op1", user_id=26,
                                outcome="applied", modality="chip",
                                cohort="allowlist", asked_at=question_shown,
                                provenance="user_selected", grams=200.0)

        line = next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("event=b1_answered"))
        reported = int(next(t.split("=", 1)[1] for t in line.split()
                            if t.startswith("latency_ms=")))
        assert 2400 <= reported <= 3200, \
            f"latency should be the user's 2.56s, got {reported}ms"


def _clock_now():
    from core.clock import now
    return now()


class _CountingDB:
    """Answers the one aggregate `_answer_counts` runs."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *a, **k):
        rows = self._rows

        class _R:
            def all(self):
                return list(rows)
        return _R()


class _ExplodingDB:
    async def execute(self, *a, **k):
        raise RuntimeError("aggregate unavailable")
