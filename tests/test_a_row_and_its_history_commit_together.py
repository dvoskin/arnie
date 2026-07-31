"""A food row and its `created` event are one transaction, or neither happened.

`add_food_entry` commits the row (db/queries.py:726) and the caller then
commits the ledger event separately. Between those two commits the process can
die — a Render deploy restart, an OOM, a dropped connection — and what survives
is a food row with no history at all:

  * `ledger_undo.build_plan` cannot invert it, so "undo that" reaches PAST it
    to a row the user never mentioned;
  * the turn↔operation join (I16) is missing the operation entirely, so the
    turn reads as a reply that claimed a log and did not make one.

Both are silent. Nothing in the schema says the event is owed.

The window is small and the failure is real: two commits where one would do.
These tests pin that the row and its history share a transaction, in both
directions — the event is written, and a failure to write it does not leave a
half-logged day behind.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import FoodEntry, LedgerEvent


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_the_row_and_its_event_are_written_in_one_transaction(
    db, make_user,
):
    """The happy path still produces exactly one row and one event — the
    refactor must not cost the history it exists to guarantee."""
    from db.queries import add_food_entry, get_or_create_today_log

    user = await make_user(telegram_id="atomic:happy")
    log = await get_or_create_today_log(db, user.id, "UTC")

    entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Lentil soup",
        raw_input="Lentil soup", calories=180, protein=12, carbs=30, fats=2,
        source_type="ios", ledger_source="quick_log:ios", user_id=user.id,
    )

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Lentil soup")
    )).scalars().all()
    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.entry_id == entry.id,
                                  LedgerEvent.domain == "food")
    )).scalars().all()

    assert len(rows) == 1
    assert len(events) == 1, (
        "the row committed without its created event — history is owed and "
        "nothing in the schema says so"
    )
    assert events[0].event_type == "created"
    assert events[0].source == "quick_log:ios"


@pytest.mark.asyncio
async def test_a_failed_history_write_does_not_leave_an_orphan_row(
    db, make_user, monkeypatch,
):
    """The crash window, made deterministic.

    If the event cannot be written, the row must not be left behind on its own.
    An orphan food row is worse than a failed request: the request is visible
    and retryable, the orphan is silent and breaks undo."""
    from db import queries as Q

    user = await make_user(telegram_id="atomic:crash")
    log = await Q.get_or_create_today_log(db, user.id, "UTC")

    async def _explode(*a, **kw):
        raise RuntimeError("ledger write died mid-transaction")

    monkeypatch.setattr(Q, "record_ledger_event", _explode)

    with pytest.raises(RuntimeError):
        await Q.add_food_entry(
            db, daily_log_id=log.id, parsed_food_name="Ghost toast",
            raw_input="Ghost toast", calories=90, protein=3, carbs=17, fats=1,
            source_type="ios", ledger_source="quick_log:ios", user_id=user.id,
        )

    await db.rollback()
    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Ghost toast")
    )).scalars().all()
    assert rows == [], (
        f"{len(rows)} orphan food row(s) survived a failed history write — "
        "invisible to ledger_undo and missing from the turn join"
    )


@pytest.mark.asyncio
async def test_the_quick_log_endpoint_still_writes_exactly_one_event(
    patched_session_local, db, make_user,
):
    """The endpoint must not double-record now that the helper owns the event —
    the exact defect the 2026-07-30 master audit found on the exercise side,
    where two writers produced two `created` events 0s apart."""
    from api.quick_log import FoodLogBody, log_food_entry

    user = await make_user(telegram_id="ios:one-event")
    await log_food_entry(
        FoodLogBody(food_name="Yogurt", calories=120, protein=18, carbs=8, fats=0),
        identity="ios:one-event",
    )

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()
    assert len(events) == 1, (
        f"{len(events)} created events for one tap — two writers again"
    )
    assert events[0].turn_id, "the event still carries its turn"
