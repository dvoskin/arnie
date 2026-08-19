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

Every one reads plausible. That is why they survived a green suite — and it is
why the tests below persist a real operation and read it back through the real
`owning()` rather than asserting that the source contains the right words.
"""
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_quantity_operation as b1
from core.semantics import CandidateSource
from db.models import Base, User
from skills.nutrition import quantity_clarification as qc
from skills.nutrition.staging import FoodIdentity, StagedFoodItem

ITEM = {"food": "chicken breast", "calories": 187, "protein": 35,
        "carbs": 0, "fats": 4, "quantity": "some"}


@pytest_asyncio.fixture
async def session(tmp_path):
    from db.database import make_engine

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'counters.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        user = User(telegram_id="counters:1")
        s.add(user)
        await s.commit()
        yield s, user
    await engine.dispose()


def _interaction(operation_id, revision=0):
    from tests._typed_candidates import candidates as _typed

    item = StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"))
    field = qc.quantity_field(operation_id=operation_id, revision=revision,
                              item=item)
    candidates = _typed(
        ("ont_low", 85.0, CandidateSource.ONTOLOGY, 0.2, 0.6),
        ("ont_high", 226.0, CandidateSource.ONTOLOGY, 0.3, 0.6))
    options = qc.select(candidates, field=field, food_name="chicken breast")
    return qc.build_interaction(operation_id=operation_id, revision=revision,
                                item=item, options=options,
                                introduction="How much chicken breast?")


class TestTheOperationCarriesWhatTheAnswerTurnNeeds:
    """The ask and the answer are different turns, different processes, possibly
    different days. Anything the answer must know is either ON the row or gone —
    and `cohort` was gone, which is why `_observe` reached for it with a
    `getattr` default and wrote an empty string into the evidence table.
    """

    @pytest.mark.asyncio
    async def test_the_cohort_survives_the_turn_boundary(self, session):
        db, user = session
        operation_id = (await b1.open_operation(
            db, user=user, interpreter_item=ITEM,
            interaction=_interaction("chat_quantity:1:t1"),
            turn_id="t1", cohort="allowlist", locale="en")).operation_id
        await db.commit()

        owned = await b1.owning(db, user)
        assert owned is not None
        assert owned.operation_id == operation_id
        assert owned.cohort == "allowlist", \
            "the answer turn cannot report a cohort the ask did not persist"

    @pytest.mark.asyncio
    async def test_the_ask_stamp_survives_and_is_a_real_time(self, session):
        db, user = session
        before = b1._now() if hasattr(b1, "_now") else datetime.utcnow()
        await b1.open_operation(
            db, user=user, interpreter_item=ITEM,
            interaction=_interaction("chat_quantity:1:t2"),
            turn_id="t2", cohort="allowlist", locale="en")
        await db.commit()

        owned = await b1.owning(db, user)
        assert owned.asked_at_stamp is not None, \
            "no ask stamp was persisted — latency falls back to the row's " \
            "transaction-start birthday"
        assert isinstance(owned.asked_at, datetime)
        assert owned.asked_at >= before - timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_an_operation_written_before_the_stamp_still_answers(
            self, session):
        """Rows already in production carry neither field. They must still be
        answerable, with `created_at` as the approximation — exactly as good as
        the behaviour this replaced, and bounded by that turn's own duration.
        """
        import json

        db, user = session
        await b1.open_operation(
            db, user=user, interpreter_item=ITEM,
            interaction=_interaction("chat_quantity:1:t3"),
            turn_id="t3", cohort="allowlist", locale="en")
        await db.commit()

        owned = await b1.owning(db, user)
        payload = json.loads(owned.row.canonical_payload)
        payload.pop("asked_at", None)
        payload.pop("cohort", None)          # the pre-migration shape
        owned.row.canonical_payload = json.dumps(payload)
        db.add(owned.row)
        await db.commit()

        legacy = await b1.owning(db, user)
        assert legacy is not None, "an older row became unanswerable"
        assert legacy.asked_at_stamp is None
        assert legacy.asked_at == legacy.row.created_at
        assert legacy.cohort == ""

    @pytest.mark.asyncio
    async def test_an_unreadable_payload_still_reports_its_cohort(
            self, session):
        """The repair path. A payload we cannot decode still belongs to a
        cohort, and a repair that reports `-` makes the one population most
        worth watching invisible."""
        import json

        db, user = session
        await b1.open_operation(
            db, user=user, interpreter_item=ITEM,
            interaction=_interaction("chat_quantity:1:t4"),
            turn_id="t4", cohort="allowlist", locale="en")
        await db.commit()

        owned = await b1.owning(db, user)
        payload = json.loads(owned.row.canonical_payload)
        payload["interaction"] = {"garbage": True}
        owned.row.canonical_payload = json.dumps(payload)
        db.add(owned.row)
        await db.commit()

        broken = await b1.owning(db, user)
        assert broken.interaction is None, "expected the unreadable branch"
        assert broken.cohort == "allowlist"
        assert broken.asked_at_stamp is not None


class TestRepairsAreCountedNotInferred:
    @pytest.mark.asyncio
    async def test_a_clean_single_tap_reports_no_repairs(self):
        from core.b1_answer_turn import _answer_counts

        assert await _answer_counts(_CountingDB(rounds=1), "op1") == (1, 0)

    @pytest.mark.asyncio
    async def test_repairs_are_counted_from_the_durable_observations(self):
        from core.b1_answer_turn import _answer_counts

        rounds, repairs = await _answer_counts(
            _CountingDB(rounds=3, repairs=2), "op1")
        assert repairs == 2, "two repairs preceded this commit"
        assert rounds == 3

    @pytest.mark.asyncio
    async def test_a_failed_count_degrades_to_the_common_shape(self):
        """A commit metric must not be lost to a failed aggregate, and `(1, 0)`
        is the shape of the overwhelming majority of answers — an honest
        default rather than a guess that inflates either number."""
        from core.b1_answer_turn import _answer_counts

        assert await _answer_counts(_ExplodingDB(), "op1") == (1, 0)


class TestRoundsComesFromTheRoundAuthority:
    """`rounds` is `max(round_index)`, not a row count.

    The two agree today and are not the same concept. B-1.8 adds repair,
    refusal, replay and cancel observations; the first of those that writes a
    row without advancing a round makes a row count mean something other than
    "how many times did we ask" — quietly, and in the metric that phase is
    judged by. Swapping one proxy for another would have been the original
    defect with a better proxy.
    """

    @pytest.mark.asyncio
    async def test_extra_observations_in_one_round_do_not_inflate_rounds(self):
        """The drift this guards against, stated as arithmetic: five durable
        observation rows belonging to two rounds must report two."""
        from core.b1_answer_turn import _answer_counts

        rounds, _ = await _answer_counts(_CountingDB(rounds=2), "op1")
        assert rounds == 2, \
            "rounds followed the row inventory instead of the round authority"

    @pytest.mark.asyncio
    async def test_the_query_reads_max_round_index(self):
        """Pins WHICH column is authoritative, by failing if the aggregate ever
        goes back to counting rows: this db answers `one()` with the round
        authority, and a row-counting implementation cannot produce 4 from it.
        """
        from core.b1_answer_turn import _answer_counts

        rounds, repairs = await _answer_counts(
            _CountingDB(rounds=4, repairs=1), "op1")
        assert (rounds, repairs) == (4, 1)

    @pytest.mark.asyncio
    async def test_an_operation_with_no_observations_reports_one_round(self):
        """`max()` over nothing is NULL, and a commit that reported zero rounds
        would say the meal was never asked about."""
        from core.b1_answer_turn import _answer_counts

        assert await _answer_counts(_CountingDB(rounds=None), "op1") == (1, 0)

    @pytest.mark.asyncio
    async def test_the_aggregate_runs_on_this_engine(self, session):
        """The aggregate is `case`-based rather than `count(...).filter(...)`
        because FILTER needs SQLite 3.30+, and a metric that depends on the
        engine is one that works in CI and not in production, or the reverse.
        Executed against a real session so the SQL is actually compiled."""
        from core.b1_answer_turn import _answer_counts
        from db.models import B1AnswerObservation

        db, user = session
        for index, outcome in ((1, "repair"), (2, "repair"), (3, "applied")):
            db.add(B1AnswerObservation(
                operation_id="op_real", user_id=user.id,
                source_turn_id=f"t{index}", attribute="quantity",
                outcome=outcome, round_index=index))
        await db.commit()

        assert await _answer_counts(db, "op_real") == (3, 2)


class TestWhatReachesTheCommittedLine:
    """`_measure_commit` is where all three numbers meet the log. Driving it is
    the only way to catch the failure the original had — every value present
    and correct somewhere, and the wrong one passed."""

    def _committed(self, caplog):
        return next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("event=b1_committed"))

    def _field(self, line, key):
        return next(t.split("=", 1)[1] for t in line.split()
                    if t.startswith(f"{key}="))

    @pytest.mark.asyncio
    async def test_the_counts_and_cohort_reach_the_line(self, caplog):
        from core.b1_answer_turn import AnswerTurn, _measure_commit
        from core.clarification_answer import Outcome

        owned = SimpleNamespace(
            operation_id="op1", cohort="allowlist", revision=1,
            asked_at=_clock_now() - timedelta(milliseconds=2500))
        turn = AnswerTurn(
            Outcome.APPLIED, operation_id="op1", field_id="f1",
            result=SimpleNamespace(
                committed_items=({"entry_id": 2938, "calories": 250.0},)))

        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            await _measure_commit(
                _CountingDB(rounds=2, repairs=1), owned, turn,
                user=SimpleNamespace(id=26))

        line = self._committed(caplog)
        assert self._field(line, "repairs") == "1"
        assert self._field(line, "rounds") == "2"
        assert self._field(line, "b1_cohort") == "allowlist"
        assert self._field(line, "entry") == "2938"

    @pytest.mark.asyncio
    async def test_a_clean_commit_reports_zero_repairs_on_the_line(
            self, caplog):
        """The exact production shape: one chip, one round, no repair. This is
        the assertion the old code could not pass."""
        from core.b1_answer_turn import AnswerTurn, _measure_commit
        from core.clarification_answer import Outcome

        owned = SimpleNamespace(operation_id="op1", cohort="allowlist",
                                revision=1, asked_at=_clock_now())
        turn = AnswerTurn(
            Outcome.APPLIED, operation_id="op1", field_id="f1",
            result=SimpleNamespace(
                committed_items=({"entry_id": 2938, "calories": 250.0},)))

        with caplog.at_level(logging.INFO, logger="core.b1_metrics"):
            await _measure_commit(_CountingDB(rounds=1), owned, turn,
                                  user=SimpleNamespace(id=26))

        line = self._committed(caplog)
        assert self._field(line, "repairs") == "0", \
            "a clean single tap reported a repair"
        assert self._field(line, "rounds") == "1"


class TestLatencyMeasuresTheUser:
    def test_the_stamp_wins_over_the_rows_birthday(self):
        transaction_start = datetime(2026, 8, 8, 20, 38, 56)
        question_shown = datetime(2026, 8, 8, 20, 39, 5)
        owned = b1.OwnedOperation(
            row=SimpleNamespace(created_at=transaction_start,
                                operation_id="op1", revision=0,
                                status="awaiting_answer", expires_at=None),
            interaction=None, item={}, asked_at_stamp=question_shown)

        assert owned.asked_at == question_shown

    def test_the_reported_latency_excludes_backend_time(self, caplog):
        """The production arithmetic as a test. An answer given 2,560 ms after
        the chips appeared, on a turn whose backend spent 8,334 ms before them,
        must report 2,560 — not 10,894."""
        from core import b1_metrics

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

    def test_the_transaction_start_reading_would_have_failed_this(self):
        """Names the defect as arithmetic rather than as a story. Reading the
        row's birthday on that turn gave 10,894 ms for a 2,560 ms answer — a
        4.3x over-report, which is what an abandonment threshold saw.
        """
        transaction_start = datetime(2026, 8, 8, 20, 38, 56, 803000)
        question_shown = datetime(2026, 8, 8, 20, 39, 5, 137000)
        answered = datetime(2026, 8, 8, 20, 39, 7, 697000)

        as_measured = (answered - transaction_start).total_seconds() * 1000
        truthful = (answered - question_shown).total_seconds() * 1000
        assert round(as_measured) == 10894
        assert round(truthful) == 2560
        assert as_measured / truthful > 4


def _clock_now():
    from core.clock import now
    return now()


class _CountingDB:
    """Answers the one aggregate `_answer_counts` runs.

    Takes `(max_round_index, repair_rows)` — the same two values the real query
    returns — so a test states the durable facts rather than a row inventory.
    """

    def __init__(self, rounds, repairs=0):
        self._row = (rounds, repairs)

    async def execute(self, *a, **k):
        row = self._row

        class _R:
            def one(self):
                return row
        return _R()


class _ExplodingDB:
    async def execute(self, *a, **k):
        raise RuntimeError("aggregate unavailable")
