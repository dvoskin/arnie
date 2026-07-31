"""The deploy-ordering test: code can land before `idem001` runs.

`render.yaml` documents `preDeployCommand: alembic upgrade heads`, but
arnie-bot is configured by hand in the Render dashboard and Render never reads
that file — so whether the migration runs on a given deploy is not something
the repo can guarantee. That makes "what happens if the code ships and the
table does not exist" a real production question, not a hypothetical.

The answer must be: nothing breaks. A keyless tap — which is every tap from
every shipped iOS build today — never touches `idempotency_records` at all,
because an absent client key short-circuits before the claim. So the code is
safe to deploy ahead of its migration, and the turn-id fix (which needs no new
table) takes effect immediately.

This stops being true the moment iOS starts sending `Idempotency-Key`. That
client change and this migration are coupled, and this test is the record of
why: it fails if someone makes the claim path unconditional.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.quick_log import FoodLogBody, log_food_entry
from db.models import FoodEntry, LedgerEvent


@pytest_asyncio.fixture
async def session_without_the_idempotency_table(monkeypatch, engine):
    """Exactly the production shape on a deploy whose migration has not run."""
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    async with factory() as db:
        await db.execute(text("DROP TABLE IF EXISTS idempotency_records"))
        await db.commit()

    from api import quick_log
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_a_keyless_tap_works_with_no_idempotency_table(
    session_without_the_idempotency_table, db, make_user,
):
    user = await make_user(telegram_id="ios:unmigrated")

    resp = await log_food_entry(
        FoodLogBody(food_name="Toast", calories=90, protein=3, carbs=17, fats=1),
        identity="ios:unmigrated",
    )

    assert resp["ok"] is True
    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Toast")
    )).scalars().all()
    assert len(rows) == 1, "the food was lost on an unmigrated database"

    # And the half of the fix that needs no new table still works.
    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].turn_id, (
        "turn identity must not depend on the idempotency table — it is the "
        "part of the fix that takes effect before the migration runs"
    )


@pytest.mark.asyncio
async def test_a_keyed_tap_still_logs_the_food_with_no_idempotency_table(
    session_without_the_idempotency_table, db, make_user,
):
    """The coupling risk between the two halves of this change.

    Once iOS ships `Idempotency-Key`, the claim path runs on every tap. If the
    migration has not been applied by then, the insert hits a table that does
    not exist — and the correct outcome is NOT a 500. A missing bookkeeping
    row must never cost the user the meal they just logged.

    Degraded, loudly, is the contract: the food is written, the turn id is
    stamped, and duplicate protection is off until `idem001` runs.
    """
    user = await make_user(telegram_id="ios:unmigrated-keyed")

    resp = await log_food_entry(
        FoodLogBody(food_name="Soup", calories=150, protein=6, carbs=18, fats=5),
        identity="ios:unmigrated-keyed",
        client_request_id="KEY-BEFORE-MIGRATION",
    )

    assert resp["ok"] is True, "a keyed tap 500'd on an unmigrated database"
    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Soup")
    )).scalars().all()
    assert len(rows) == 1, "the food was lost because a bookkeeping table was absent"

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].turn_id == "ios:KEY-BEFORE-MIGRATION", (
        "traceability must survive the degraded path"
    )
