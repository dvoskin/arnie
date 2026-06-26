"""
Regression tests for proactive-message platform tagging.

Background: _log_proactive recorded every proactive send via log_conversation
WITHOUT platform=, so it fell back to the column default ("telegram"). A morning
check-in delivered to an iOS device via APNs (or to iMessage) was therefore
stored as platform="telegram" and showed a misleading "Telegram" chip in the
cross-platform chat history. Fleet audit on 2026-06-25 found 152 such rows
(67 iOS, 85 iMessage). Same mislabel class as the iOS-edit/iMessage fix (53ae161);
the proactive path was the straggler. These pin the channel mapping + threading.
"""
import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.database import Base, _migrate
from db import models  # noqa: F401
from db.models import User, ConversationLog
from scheduler.proactive_scheduler import _channel_for, _log_proactive


@pytest_asyncio.fixture
async def fk_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(eng.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(fk_engine):
    Session = async_sessionmaker(fk_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


def test_channel_for_maps_identity_prefix():
    assert _channel_for("ios:82BBB33A-D3A5") == "ios"
    assert _channel_for("apple:001234.abc") == "ios"
    assert _channel_for("im:+19176354658") == "imessage"
    assert _channel_for("6996307425") == "telegram"
    assert _channel_for(None) == "telegram"
    assert _channel_for("") == "telegram"


@pytest.mark.asyncio
@pytest.mark.parametrize("tg_id,expected", [
    ("ios:abc", "ios"),
    ("im:+1555", "imessage"),
    ("12345", "telegram"),
])
async def test_log_proactive_threads_channel_to_row(db, tg_id, expected):
    u = User(telegram_id=tg_id, name="P", timezone="UTC", onboarding_completed=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)

    await _log_proactive(db, u.id, "morning check-in", "morning_checkin",
                         platform=_channel_for(tg_id))

    row = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == u.id)
    )).scalars().first()
    assert row is not None
    assert row.source_type == "proactive"
    assert row.skills_fired == "morning_checkin"
    assert row.platform == expected, (
        f"proactive row for {tg_id} tagged {row.platform!r}, expected {expected!r}"
    )
