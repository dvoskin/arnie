"""The database rejects duplicate operations and stacked pendings (I2, I3).

The directive's rule: "the database should reject invalid or duplicate
operations even when upstream routing or model behavior fails." These tests
prove the two partial unique indexes do that — through a real engine, not by
reading migration files — and that both writers degrade gracefully when the
guard fires (history must never break the write it describes; a race loser
adopts the winner's row).
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from db.models import Base, LedgerEvent, PendingQuestion, User
from db.queries import (get_or_create_today_log, record_ledger_event,
                        record_pending_question)


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)   # includes both guards
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        u = User(telegram_id="db-guard-test")
        s.add(u)
        await s.commit()
        log = await get_or_create_today_log(s, u.id, "UTC")
        yield s, u.id, log.id
    await engine.dispose()


# ── I3: one created event per (domain, entry) ────────────────────────────────
@pytest.mark.anyio
async def test_a_second_created_event_is_rejected_not_stored(session):
    db, uid, log_id = session
    first = await record_ledger_event(db, uid, "created", domain="exercise",
                                      entry_id=42, daily_log_id=log_id,
                                      source="ios")
    assert first is not None
    dup = await record_ledger_event(db, uid, "created", domain="exercise",
                                    entry_id=42, daily_log_id=log_id,
                                    source="legacy:ios")
    assert dup is None, "the guard must reject the duplicate writer"
    rows = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == 42))).scalars().all()
    assert len(rows) == 1 and rows[0].source == "ios"


@pytest.mark.anyio
async def test_the_session_survives_a_blocked_duplicate(session):
    """The aborted transaction must not poison the session mid-turn — the
    next legitimate write on the same session has to succeed."""
    db, uid, log_id = session
    await record_ledger_event(db, uid, "created", domain="exercise",
                              entry_id=1, daily_log_id=log_id, source="a")
    await record_ledger_event(db, uid, "created", domain="exercise",
                              entry_id=1, daily_log_id=log_id, source="b")
    after = await record_ledger_event(db, uid, "created", domain="exercise",
                                      entry_id=2, daily_log_id=log_id,
                                      source="a")
    assert after is not None, "session was poisoned by the blocked duplicate"


@pytest.mark.anyio
async def test_same_entry_id_across_domains_is_legitimate(session):
    """Entry ids come from independent per-domain sequences — food entry 7 and
    exercise entry 7 are different rows. The guard must not conflate them;
    this is why `domain` is part of the key."""
    db, uid, log_id = session
    a = await record_ledger_event(db, uid, "created", domain="food",
                                  entry_id=7, daily_log_id=log_id, source="x")
    b = await record_ledger_event(db, uid, "created", domain="exercise",
                                  entry_id=7, daily_log_id=log_id, source="x")
    assert a is not None and b is not None


@pytest.mark.anyio
async def test_updates_and_deletes_may_repeat(session):
    """Only creations are one-per-entry. A row corrected twice is normal."""
    db, uid, log_id = session
    for _ in range(2):
        ev = await record_ledger_event(db, uid, "updated", domain="food",
                                       entry_id=9, daily_log_id=log_id,
                                       source="chat")
        assert ev is not None


# ── I2: one open pending per (user, kind) ────────────────────────────────────
@pytest.mark.anyio
async def test_the_helper_updates_in_place_and_the_db_would_reject_stacking(
        session):
    db, uid, _ = session
    p1 = await record_pending_question(db, uid, kind="food_structured_ask",
                                       question="Which flavor?")
    p2 = await record_pending_question(db, uid, kind="food_structured_ask",
                                       question="How many?")
    assert p1.id == p2.id, "helper must update in place, not stack"
    assert p2.question == "How many?"
    # a writer that SKIPS the helper hits the index
    rogue = PendingQuestion(user_id=uid, kind="food_structured_ask",
                            question="stacked")
    db.add(rogue)
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.anyio
async def test_an_answered_pending_frees_the_slot(session):
    """The index is partial: closing a question makes room for the next one —
    the normal lifecycle must not trip the guard."""
    from datetime import datetime

    db, uid, _ = session
    p1 = await record_pending_question(db, uid, kind="conversation_hook",
                                       question="first")
    p1.answered_at = datetime.utcnow()
    await db.commit()
    p2 = await record_pending_question(db, uid, kind="conversation_hook",
                                       question="second")
    assert p2.id != p1.id
    open_rows = (await db.execute(select(PendingQuestion).where(
        PendingQuestion.user_id == uid,
        PendingQuestion.answered_at.is_(None)))).scalars().all()
    assert len(open_rows) == 1


@pytest.mark.anyio
async def test_different_kinds_coexist_open(session):
    db, uid, _ = session
    a = await record_pending_question(db, uid, kind="food_structured_ask",
                                      question="q1")
    b = await record_pending_question(db, uid, kind="conversation_hook",
                                      question="q2")
    assert a.id != b.id


@pytest.mark.anyio
async def test_per_item_clarifications_coexist_open(session):
    """The purpose discriminator: one open clarification per ITEM is
    legitimate — the sandwich's cook-method question and the salad's dressing
    question must coexist. `item_referenced` is part of the unique key, which
    is why this does not trip the guard (and why a coarser (user, kind) key
    was wrong — caught by the hardening suite, not by design review)."""
    db, uid, _ = session
    a = PendingQuestion(user_id=uid, kind="food_clarification",
                        question="grilled or fried?",
                        item_referenced="chicken sandwich")
    b = PendingQuestion(user_id=uid, kind="food_clarification",
                        question="what dressing?", item_referenced="salad")
    db.add(a)
    db.add(b)
    await db.commit()
    open_rows = (await db.execute(select(PendingQuestion).where(
        PendingQuestion.user_id == uid,
        PendingQuestion.answered_at.is_(None)))).scalars().all()
    assert len(open_rows) == 2
    # …but the SAME item cannot stack a second open question
    dup = PendingQuestion(user_id=uid, kind="food_clarification",
                          question="how big?", item_referenced="salad")
    db.add(dup)
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
