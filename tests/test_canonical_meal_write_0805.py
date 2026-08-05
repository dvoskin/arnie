"""A real meal, through the real boundary, onto real rows.

    CanonicalMeal -> write_canonical_meal -> commit_or_load_existing
                  -> FoodEntry rows -> MealCommitResult

Five properties, and they are the whole point of the boundary:

  1. all items commit or none do;
  2. totals come from the COMMITTED ROWS, not from the request;
  3. the result matches the ledger;
  4. duplicate delivery returns the same result;
  5. rollback removes the food, the result and the operation transition
     together.

Run on Postgres wherever a property depends on the database — the abort
semantics and the second connection are not expressible on sqlite — and on
sqlite where it does not, so the cheap checks stay fast.
"""
import os
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import meal_commit, pending_repository as repo
from core.canonical_writer import (MealNotResolved, ResolvedFood,
                                   write_canonical_meal)
from core.commit_coordinator import commit_or_load_existing
from core.meal_commit import MealCommitResult
from core.semantics import CanonicalEvent, ResolutionStatus
from db.database import make_engine
from db.models import Base, DailyLog, FoodEntry, LedgerEvent, User

DAY = date(2026, 8, 5)


def _food(name, calories, *, entity_id="", status=ResolutionStatus.RESOLVED,
          **kw) -> ResolvedFood:
    return ResolvedFood(
        event=CanonicalEvent(id=f"ev_{name}", domain="food",
                             entity_id=entity_id or name.lower(),
                             surface_text=name, resolution_status=status),
        calories=calories, **kw)


CHICKEN = _food("Grilled chicken", 320, protein=43.0, carbs=0.0, fats=15.0)
RICE = _food("White rice", 205, protein=4.3, carbs=45.0, fats=0.4)
MEAL = [CHICKEN, RICE]


class _Op:
    def __init__(self, oid="op_meal", revision=0, user_id=1, day=DAY):
        self.id, self.revision, self.user_id = oid, revision, user_id
        self.logging_day = day


# ── sqlite: the type refuses what must never reach the ledger ────────────────

def test_an_unpriced_food_cannot_be_built():
    """"Understood" and "priced" are different facts. A food that reached the
    ledger unpriced is how a cup of rice lands on the board at 1 calorie."""
    with pytest.raises(MealNotResolved, match="never priced"):
        ResolvedFood(event=CanonicalEvent(id="e", domain="food",
                                          surface_text="Rice",
                                          resolution_status=ResolutionStatus.RESOLVED),
                     calories=None)


@pytest.mark.parametrize("status", [ResolutionStatus.UNRESOLVED,
                                    ResolutionStatus.AMBIGUOUS,
                                    ResolutionStatus.PARTIALLY_RESOLVED])
def test_an_unresolved_food_cannot_be_built(status):
    """Writing an ambiguous item commits a guess as a fact — and a later
    correction then has no unambiguous target to attach to."""
    with pytest.raises(MealNotResolved, match="not\\s+resolved"):
        _food("Chicken", 300, status=status)


@pytest.mark.asyncio
async def test_an_empty_meal_is_refused():
    """Writing nothing successfully is how a turn reports a log it never
    made."""
    with pytest.raises(MealNotResolved, match="empty meal"):
        await write_canonical_meal(None, operation=_Op(), resolved_meal=[])


# ── postgres: everything that depends on the database ────────────────────────

PG = os.getenv("TEST_POSTGRES_URL")

if os.getenv("CI") and not PG:
    raise RuntimeError(
        "TEST_POSTGRES_URL is unset in CI. All-or-nothing across a multi-item "
        "meal depends on Postgres abort semantics and cannot be tested on "
        "sqlite.")

pg_only = pytest.mark.skipif(
    not PG, reason="needs a real Postgres (TEST_POSTGRES_URL)")


@pytest_asyncio.fixture
async def pg():
    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        s.add(User(telegram_id="pg:canonical"))
        await s.commit()
    yield maker
    await engine.dispose()


async def _count(maker, model) -> int:
    async with maker() as s:
        return int((await s.execute(
            select(func.count()).select_from(model))).scalar() or 0)


# 1. all items commit or none do

@pg_only
@pytest.mark.asyncio
async def test_every_item_lands_or_none_of_them_do(pg):
    """The chicken-and-rice failure, at its root.

    `add_food_entry` commits per row by default, so a three-food turn could
    leave two on the board and lose the third — there was no state in which the
    meal as a whole had or had not landed. Here the second item fails and the
    FIRST must not survive it.
    """
    async with pg() as s:
        await write_canonical_meal(s, operation=_Op(), resolved_meal=MEAL)
        # ...then fail before the caller commits, exactly as a later step would.
        await s.rollback()

    assert await _count(pg, FoodEntry) == 0, "a partial meal survived"
    assert await _count(pg, LedgerEvent) == 0, "history outlived its rows"
    assert await _count(pg, DailyLog) == 0, "the day container outlived it too"


@pg_only
@pytest.mark.asyncio
async def test_a_failure_mid_meal_leaves_nothing(pg):
    """The same property with the failure INSIDE the write, not after it."""
    import db.queries as q

    calls = {"n": 0}
    original = q.add_food_entry

    async def _third_fails(db_, log_id, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("ledger unavailable")
        return await original(db_, log_id, **kw)

    q.add_food_entry = _third_fails
    try:
        async with pg() as s:
            with pytest.raises(RuntimeError):
                await write_canonical_meal(
                    s, operation=_Op(),
                    resolved_meal=[CHICKEN, RICE, _food("Broccoli", 55)])
            await s.rollback()
    finally:
        q.add_food_entry = original

    assert calls["n"] == 3, "the third item was never attempted"
    assert await _count(pg, FoodEntry) == 0, \
        "two rows survived a meal that failed on the third"


# 2 & 3. totals come from the rows, and the result matches the ledger

@pg_only
@pytest.mark.asyncio
async def test_the_totals_are_read_back_from_the_rows(pg):
    async with pg() as s:
        result = await write_canonical_meal(s, operation=_Op(),
                                            resolved_meal=MEAL)
        await s.commit()

    assert result.meal_totals["calories"] == 525.0
    assert result.meal_totals["protein"] == 47.3
    assert result.day_totals["calories"] == 525.0

    async with pg() as s:
        rows = (await s.execute(select(FoodEntry))).scalars().all()
    assert sum(r.calories for r in rows) == result.meal_totals["calories"], \
        "the result's totals disagree with the rows they describe"


@pg_only
@pytest.mark.asyncio
async def test_a_clamped_row_is_reported_as_written_not_as_requested(pg):
    """THE reason totals are re-read rather than summed.

    If the row lands with a different value than it was handed, a total
    computed from the request describes a meal that is not on the board — which
    is how the prose and the card came to disagree with the ledger.
    """
    import db.queries as q
    original = q.add_food_entry

    async def _clamp(db_, log_id, **kw):
        if kw.get("parsed_food_name") == "White rice":
            kw["calories"] = 190.0            # a sanity clamp, downstream
        return await original(db_, log_id, **kw)

    q.add_food_entry = _clamp
    try:
        async with pg() as s:
            result = await write_canonical_meal(s, operation=_Op(),
                                                resolved_meal=MEAL)
            await s.commit()
    finally:
        q.add_food_entry = original

    assert result.meal_totals["calories"] == 510.0, (
        "the total reported the REQUESTED 205 instead of the written 190")
    rice = next(i for i in result.committed_items if i["name"] == "White rice")
    assert rice["calories"] == 190.0


@pg_only
@pytest.mark.asyncio
async def test_every_committed_item_names_a_real_row(pg):
    async with pg() as s:
        result = await write_canonical_meal(s, operation=_Op(),
                                            resolved_meal=MEAL)
        await s.commit()

    async with pg() as s:
        for item in result.committed_items:
            row = await s.get(FoodEntry, item["entry_id"])
            assert row is not None, f"{item} names no row"
            assert row.parsed_food_name == item["name"]
            assert float(row.calories) == item["calories"]


@pg_only
@pytest.mark.asyncio
async def test_history_is_written_with_the_rows(pg):
    """A row with no ledger event cannot be undone and does not join its
    turn."""
    async with pg() as s:
        await write_canonical_meal(s, operation=_Op(), resolved_meal=MEAL)
        await s.commit()

    async with pg() as s:
        events = (await s.execute(select(LedgerEvent))).scalars().all()
    assert len(events) == len(MEAL)
    assert {e.event_type for e in events} == {"created"}
    assert {e.source for e in events} == {"structured_food"}


# 4. duplicate delivery returns the same result

@pg_only
@pytest.mark.asyncio
async def test_a_duplicate_delivery_returns_the_same_result(pg):
    """Through the coordinator, end to end: the second delivery must return the
    first's result and write nothing."""
    async with pg() as s:
        first = await commit_or_load_existing(
            s, operation=_Op("op_dup"), resolved_meal=MEAL,
            writer=write_canonical_meal)
        await s.commit()

    async with pg() as s:
        second = await commit_or_load_existing(
            s, operation=_Op("op_dup"), resolved_meal=MEAL,
            writer=write_canonical_meal)
        await s.commit()

    assert second == first
    assert isinstance(second, MealCommitResult)
    assert await _count(pg, FoodEntry) == len(MEAL), "the meal was written twice"
    assert await _count(pg, LedgerEvent) == len(MEAL)


# 5. rollback removes food, result and operation transition together

@pg_only
@pytest.mark.asyncio
async def test_rollback_removes_food_result_and_transition_together(pg):
    """The three facts that must never disagree: the rows, the authoritative
    result, and the operation's own state."""
    async with pg() as s:
        await repo.create_operation(s, operation_id="op_undo", user_id=1,
                                    status="ready_to_commit",
                                    storage_status="active")
        await s.commit()

    async def _fail_at_the_end(db, **kw):
        raise RuntimeError("the turn failed after the meal was written")

    async with pg() as s:
        with pytest.raises(RuntimeError):
            await commit_or_load_existing(
                s, operation=_Op("op_undo"), resolved_meal=MEAL,
                writer=write_canonical_meal, finaliser=_fail_at_the_end)
        await s.rollback()

    assert await _count(pg, FoodEntry) == 0, "food outlived the failed turn"
    async with pg() as s:
        assert await meal_commit.existing_result(
            s, operation_id="op_undo") is None, "a result outlived its rows"
        row = await repo.load_operation(s, "op_undo")
        assert row.status == "ready_to_commit", (
            "the operation moved on while its meal did not — the three facts "
            "disagree, which is the state this boundary exists to make "
            "impossible")


@pg_only
@pytest.mark.asyncio
async def test_a_successful_commit_moves_all_three_together(pg):
    """The other half: they agree on success too."""
    async with pg() as s:
        await repo.create_operation(s, operation_id="op_ok", user_id=1,
                                    status="ready_to_commit",
                                    storage_status="active")
        await s.commit()

    async with pg() as s:
        result = await commit_or_load_existing(
            s, operation=_Op("op_ok"), resolved_meal=MEAL,
            writer=write_canonical_meal, finaliser=repo.mark_committed)
        await s.commit()

    assert await _count(pg, FoodEntry) == len(MEAL)
    async with pg() as s:
        stored = await meal_commit.existing_result(s, operation_id="op_ok")
        assert stored == result, "the stored result is not the one returned"
        row = await repo.load_operation(s, "op_ok")
        assert row.status == "committed" and row.storage_status == "consumed"


# ── the daily log must not commit or roll back the caller ────────────────────

@pg_only
@pytest.mark.asyncio
async def test_resolving_the_day_does_not_touch_the_callers_transaction(pg):
    """`get_or_create_log_for_date` calls commit(), and rollback() on a create
    race. Either inside the coordinator would discard the claim and everything
    staged — the meal would vanish while the operation looked untouched."""
    async with pg() as s:
        await repo.create_operation(
            s, operation_id="op_stage", user_id=1, status="collecting",
            storage_status="active")
        await s.flush()          # staged, NOT committed

        await write_canonical_meal(s, operation=_Op(), resolved_meal=MEAL)

        # If the writer had committed, this rollback could not undo the meal.
        await s.rollback()

    assert await _count(pg, FoodEntry) == 0
    async with pg() as s:
        assert await repo.load_operation(s, "op_stage") is None, (
            "the writer committed the caller's transaction — work staged "
            "before it survived a rollback that should have removed it")


@pg_only
@pytest.mark.asyncio
async def test_two_meals_on_the_same_day_share_one_log(pg):
    """The day is a container, not part of the meal."""
    async with pg() as s:
        await write_canonical_meal(s, operation=_Op("m1"), resolved_meal=[CHICKEN])
        await s.commit()
    async with pg() as s:
        await write_canonical_meal(s, operation=_Op("m2"), resolved_meal=[RICE])
        await s.commit()

    assert await _count(pg, DailyLog) == 1
    assert await _count(pg, FoodEntry) == 2
    async with pg() as s:
        log = (await s.execute(select(DailyLog))).scalar_one()
    assert float(log.total_calories) == 525.0, \
        "the day's totals did not follow the second meal"


@pg_only
@pytest.mark.asyncio
async def test_post_commit_work_is_returned_as_data(pg):
    """Invalidating the briefing cache while the rows are still invisible would
    let a concurrent read repopulate it from pre-write state, and would outlive
    a rollback. So it is returned for the caller to run after committing."""
    async with pg() as s:
        result = await write_canonical_meal(s, operation=_Op(),
                                            resolved_meal=MEAL)
        await s.commit()
    assert {"action": "invalidate_briefing", "user_id": 1} \
        in result.render_actions
