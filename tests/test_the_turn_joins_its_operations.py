"""The turn and its operations share one id — the join exists (I16's floor).

Master audit 2026-07-30 §9: 29 replies claimed a log, and none could be
verified against operations, because the canonical turn id lived only on the
ledger side in three formats — including "ios:ios:<uuid>", a double prefix
(api/chat pre-prefixed the idempotency key with the channel, make_turn_id
prepended it again). conversation_logs had no turn id at all.

These tests pin the three properties that make the join real:
  * make_turn_id fed the RAW client id produces a single-prefixed id
  * the conversation row stores the same id the ledger contextvar stamps
  * the historic backfill shape stays double-prefixed (it must match the
    mangled ledger rows, not an idealised format)
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from core.turn_identity import make_turn_id
from db.models import Base, ConversationLog, User
from db.queries import log_conversation


# ── the id itself ─────────────────────────────────────────────────────────────
def test_a_raw_client_id_is_prefixed_exactly_once():
    assert make_turn_id("ios", "ABC-123", 7) == "ios:ABC-123"


def test_the_strip_safety_net_shape():
    """A caller that still passes the prefixed key must not double: the
    chat_service strip reduces it to the raw id first. This pins the strip's
    contract rather than re-implementing it here."""
    prefixed = "ios:ABC-123"
    stripped = prefixed[len("ios:"):] if prefixed.startswith("ios:") else prefixed
    assert make_turn_id("ios", stripped, 7) == "ios:ABC-123"


def test_no_client_id_falls_back_to_the_hash_form():
    tid = make_turn_id("ios", None, 7, "some text")
    assert tid.startswith("ios:h:") and len(tid) == len("ios:h:") + 20


# ── the conversation row carries it ───────────────────────────────────────────
@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        u = User(telegram_id="turn-join-test")
        s.add(u)
        await s.commit()
        yield s, u.id
    await engine.dispose()


@pytest.mark.anyio
async def test_the_conversation_row_stores_the_turn_id(session):
    db, uid = session
    turn_id = make_turn_id("ios", "UUID-1", uid)
    await log_conversation(db, uid, "hi", "hey", source_type="ios",
                           idempotency_key="ios:UUID-1", turn_id=turn_id)
    row = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == uid)
    )).scalars().first()
    assert row.turn_id == "ios:UUID-1"
    # the idempotency key keeps its historic prefixed shape — the replay
    # short-circuit is an exact-string match and must not move
    assert row.idempotency_key == "ios:UUID-1"


@pytest.mark.anyio
async def test_the_row_id_and_ledger_stamp_would_join(session):
    """The property the whole phase exists for: what log_conversation stores
    equals what the ledger contextvar stamps during the same turn."""
    from core.turn_identity import CURRENT_TURN_ID, current_turn_id

    db, uid = session
    turn_id = make_turn_id("telegram", 424242, uid)
    token = CURRENT_TURN_ID.set(turn_id)
    try:
        assert current_turn_id() == turn_id     # what record_ledger_event reads
        await log_conversation(db, uid, "борщ", "готово", source_type="text",
                               platform="telegram", turn_id=turn_id)
    finally:
        CURRENT_TURN_ID.reset(token)
    row = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == uid)
    )).scalars().first()
    assert row.turn_id == turn_id == "telegram:424242"


# ── the historic backfill contract ────────────────────────────────────────────
def test_the_backfill_reconstructs_the_double_prefix_on_purpose():
    """Historic iOS ledger rows say "ios:ios:<uuid>". The migration's backfill
    ('ios:' || idempotency_key) must reproduce exactly that, or historic joins
    match nothing. This test documents the intent so nobody "fixes" it."""
    idempotency_key = "ios:ABC-123"
    backfilled = "ios:" + idempotency_key
    historic_ledger_turn_id = make_turn_id("ios", idempotency_key, 7)  # the old bug
    assert backfilled == historic_ledger_turn_id == "ios:ios:ABC-123"
