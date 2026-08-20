"""The ask stamp, proven on the engine the defect belongs to.

`asked_at` used to read `PendingOperation.created_at`, which is
`server_default=func.now()`. On Postgres `now()` is `transaction_timestamp()`
— it returns when the TRANSACTION began and is constant for its whole life,
unlike `clock_timestamp()`. The insert rides the turn's existing transaction,
which opens before the interpreter's model call, so a row written after an
8-second model call is stamped 8 seconds early.

That is not a rounding error. Production 2026-08-08: an answer given 2,560 ms
after the chips appeared was reported as `latency_ms=10894`, because the row
carried the transaction's birthday rather than the moment the question was
sent. 76% of a "user answer latency" was our own backend, and the abandonment
threshold that reads it fires earliest on exactly the slowest turns.

WHY THIS FILE EXISTS SEPARATELY. SQLite's `CURRENT_TIMESTAMP` is per-statement,
so the whole defect is INVISIBLE there — the suite the fix was written under
cannot fail on it in either direction. Every assertion here needs a real
Postgres and skips without one.

At the time of writing CI cannot run these: the shared Postgres fixture dies at
setup with `ModuleNotFoundError: No module named 'asyncpg'` (see
`docs/RELEASE_GATE.md`). They were run against a local PostgreSQL 16 instead.
That is worth stating rather than implying coverage nobody exercised — but the
file is the thing that will discharge it automatically once the fixture is
repaired.
"""
import os
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PG = os.getenv("TEST_POSTGRES_URL")
pg_only = pytest.mark.skipif(not PG, reason="needs a real Postgres")

#: Long enough to dwarf scheduling noise, short enough not to slow the suite.
#: Production's real gap on the measured turn was 8.3 s.
MODEL_CALL_SECONDS = 2


@pytest_asyncio.fixture
async def pg():
    from db.database import make_engine
    from db.models import Base, User

    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        user = User(telegram_id="pg:ask_stamp")
        s.add(user)
        await s.commit()
        yield s, user
    await engine.dispose()


def _interaction(operation_id, revision=0):
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.staging import FoodIdentity, StagedFoodItem
    from tests._typed_candidates import candidates as _typed

    from core.semantics import CandidateSource

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


ITEM = {"food": "chicken breast", "calories": 187, "protein": 35,
        "carbs": 0, "fats": 4, "quantity": "some"}


@pg_only
@pytest.mark.asyncio
async def test_now_is_frozen_for_the_life_of_a_transaction(pg):
    """The premise, asserted rather than assumed.

    If this ever fails, the fix below is solving a problem the engine no longer
    has, and `created_at` would be a perfectly good ask stamp again.
    """
    db, _ = pg
    opened = (await db.execute(text("SELECT clock_timestamp()"))).scalar()
    await db.execute(text(f"SELECT pg_sleep({MODEL_CALL_SECONDS})"))
    row = (await db.execute(text(
        "SELECT now() AS tx_now, clock_timestamp() AS real_now"))).one()

    drift = (row.real_now - row.tx_now).total_seconds()
    assert drift >= MODEL_CALL_SECONDS * 0.75, (
        f"now() advanced with the wall clock inside one transaction "
        f"(drift {drift:.2f}s) — Postgres would have to have changed "
        f"now() away from transaction_timestamp() for that")
    assert abs((row.tx_now - opened).total_seconds()) < 1.0, \
        "now() should sit at the transaction's start, not somewhere else"


@pg_only
@pytest.mark.asyncio
async def test_the_row_birthday_predates_the_question_it_stamps(pg):
    """THE DEFECT ITSELF, reproduced end to end on the engine that has it.

    The transaction is held open across a simulated model call before the
    operation is written — which is what a real ask turn does — and the row's
    `created_at` comes back stamped BEFORE the question existed.
    """
    from core import b1_quantity_operation as b1

    db, user = pg
    await db.execute(text("SELECT 1"))                 # transaction opens here
    await db.execute(text(f"SELECT pg_sleep({MODEL_CALL_SECONDS})"))

    await b1.open_operation(
        db, user=user, interpreter_item=ITEM,
        interaction=_interaction("chat_quantity:1:pg1"),
        turn_id="pg1", cohort="allowlist", locale="en", capability="id_addressed")
    await db.commit()

    owned = await b1.owning(db, user)
    assert owned is not None
    lag = (owned.asked_at_stamp - owned.row.created_at).total_seconds()
    assert lag >= MODEL_CALL_SECONDS * 0.75, (
        f"the row's created_at was only {lag:.2f}s behind the ask stamp — "
        f"expected roughly {MODEL_CALL_SECONDS}s, the length of the model "
        f"call the transaction was held across")


@pg_only
@pytest.mark.asyncio
async def test_latency_measures_the_user_not_the_backend(pg):
    """What the defect cost, and what the fix buys, in the units the metric
    reports. `asked_at` must follow the stamp, so a latency computed from it
    excludes everything that happened before the question was sent.
    """
    from core import b1_metrics, b1_quantity_operation as b1

    db, user = pg
    await db.execute(text("SELECT 1"))
    await db.execute(text(f"SELECT pg_sleep({MODEL_CALL_SECONDS})"))
    await b1.open_operation(
        db, user=user, interpreter_item=ITEM,
        interaction=_interaction("chat_quantity:1:pg2"),
        turn_id="pg2", cohort="allowlist", locale="en", capability="id_addressed")
    await db.commit()

    owned = await b1.owning(db, user)
    honest = b1_metrics._ms_since(owned.asked_at)
    as_it_was = b1_metrics._ms_since(owned.row.created_at)

    assert honest is not None and as_it_was is not None
    assert as_it_was - honest >= MODEL_CALL_SECONDS * 750, (
        "the two readings agree, so either the stamp is not being used or the "
        "transaction was not actually held open — the defect this measures "
        "cannot be observed either way")
    assert honest < as_it_was, "the stamp must be the LATER of the two"


@pg_only
@pytest.mark.asyncio
async def test_a_row_without_a_stamp_still_falls_back(pg):
    """Rows already in production carry no stamp and must stay answerable.
    The approximation is exactly what shipped before, and its error is bounded
    by that turn's own duration — which is the honest trade, not a silent one.
    """
    import json

    from core import b1_quantity_operation as b1

    db, user = pg
    await b1.open_operation(
        db, user=user, interpreter_item=ITEM,
        interaction=_interaction("chat_quantity:1:pg3"),
        turn_id="pg3", cohort="allowlist", locale="en", capability="id_addressed")
    await db.commit()

    owned = await b1.owning(db, user)
    payload = json.loads(owned.row.canonical_payload)
    payload.pop("asked_at", None)
    owned.row.canonical_payload = json.dumps(payload)
    db.add(owned.row)
    await db.commit()

    legacy = await b1.owning(db, user)
    assert legacy.asked_at_stamp is None
    assert legacy.asked_at == legacy.row.created_at
    assert isinstance(legacy.asked_at, datetime)


@pg_only
@pytest.mark.asyncio
async def test_the_round_aggregate_runs_on_postgres(pg):
    """`rounds` is `max(round_index)` and `repairs` a `CASE` sum, chosen over
    `count(...).filter(...)` so the metric does not depend on the engine.
    Both dialects compile it; this proves Postgres also EXECUTES it.
    """
    from db.models import B1AnswerObservation

    from core.b1_answer_turn import _answer_counts

    db, user = pg
    for index, outcome in ((1, "repair"), (2, "repair"), (3, "applied")):
        db.add(B1AnswerObservation(
            operation_id="op_pg", user_id=user.id,
            source_turn_id=f"t{index}", attribute="quantity",
            outcome=outcome, round_index=index))
    await db.commit()

    assert await _answer_counts(db, "op_pg") == (3, 2)
    assert await _answer_counts(db, "op_absent") == (1, 0), \
        "max() over no rows is NULL, and a commit reporting zero rounds would " \
        "say the meal was never asked about"
