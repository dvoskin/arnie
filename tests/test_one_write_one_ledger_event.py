"""One user action produces exactly one committed ledger operation (I3).

Master audit, 2026-07-30, `OBSERVED`: every exercise creation in the 18-hour
window was recorded TWICE, 0 seconds apart — once by `add_exercise_entry`'s
internal recorder under `domain="fitness"`, once by its caller under
`domain="exercise"`. Two writers, two vocabularies. And because
`ledger_undo._invert` handles only "exercise", the internal event was
uninvertible on its own — the caller's duplicate had been masking that.

The fix: `add_exercise_entry` is the ONLY writer of the exercise `created`
event, records it under the domain undo actually speaks, and callers pass
their provenance label as `ledger_source` instead of writing a second event.

Through the real boundary: rows written to a database, ledger read back.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from db.models import Base, DailyLog, LedgerEvent, User
from db.queries import add_exercise_entry, get_or_create_today_log


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        u = User(telegram_id="one-event-test")
        s.add(u)
        await s.commit()
        log = await get_or_create_today_log(s, u.id, "UTC")
        yield s, u.id, log.id
    await engine.dispose()


async def _events(db, uid):
    rows = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == uid)
        .order_by(LedgerEvent.id))).scalars().all()
    return rows


@pytest.mark.anyio
async def test_one_creation_writes_exactly_one_created_event(session):
    db, uid, log_id = session
    entry = await add_exercise_entry(
        db, log_id, exercise_name="Incline press", sets=3, reps="12,12,10",
        weight=60.0, source_type="ios",
        ledger_source="legacy:ios")
    events = await _events(db, uid)
    created = [e for e in events
               if e.event_type == "created" and e.entry_id == entry.id]
    assert len(created) == 1, (
        f"expected exactly one created event, got {len(created)} — "
        f"the double-write is back")


@pytest.mark.anyio
async def test_the_event_speaks_the_domain_undo_reads(session):
    """`_invert` handles dom == "exercise" only. A "fitness" event is
    uninvertible — the exact defect the caller's duplicate was masking."""
    from core.ledger_undo import _invert

    db, uid, log_id = session
    await add_exercise_entry(db, log_id, exercise_name="Row", sets=3,
                             source_type="ios", ledger_source="quick_log:ios")
    (event,) = await _events(db, uid)
    assert event.domain == "exercise"
    plan = _invert(event)
    assert plan is not None, "the created event must be invertible"
    assert plan["tool_calls"][0]["name"] == "delete_exercise_entry"
    assert plan["tool_calls"][0]["input"]["entry_id"] == event.entry_id


@pytest.mark.anyio
async def test_the_callers_provenance_survives_as_the_source(session):
    db, uid, log_id = session
    await add_exercise_entry(db, log_id, exercise_name="Squat", sets=5,
                             source_type="ios", ledger_source="quick_log:ios")
    (event,) = await _events(db, uid)
    assert event.source == "quick_log:ios", (
        "the caller's label must ride the single event, not a second one")


@pytest.mark.anyio
async def test_without_a_label_the_source_falls_back_to_source_type(session):
    db, uid, log_id = session
    await add_exercise_entry(db, log_id, exercise_name="Curl",
                             source_type="telegram")
    (event,) = await _events(db, uid)
    assert event.source == "telegram"
