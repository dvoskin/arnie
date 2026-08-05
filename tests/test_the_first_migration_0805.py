"""The first mutation owner meets the canonical spine — in shadow.

`api/quick_log.py` is the first migration because a tap is already
canonical-shaped: one item, priced by the client, no clarification, no held
state, and the day resolved at the endpoint from the user's timezone.
Everything the canonical contract demands is already in hand, so a divergence
means a real disagreement rather than a missing input.

What must hold before promotion:

  * the shadow NEVER affects the request, including when it fails;
  * it writes nothing — the savepoint is rolled back either way;
  * when the two paths agree, it says so;
  * when they disagree, it says exactly how.
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import canonical_shadow
from core.canonical_shadow import compare_with_legacy
from core.canonical_writer import ResolvedFood, ResolvedMeal
from core.semantics import CanonicalEvent, ResolutionStatus
from db.database import make_engine
from db.models import Base, DailyLog, FoodEntry, MealCommit, User
from db.queries import recompute_log_totals
from datetime import date

PG = os.getenv("TEST_POSTGRES_URL")
if os.getenv("CI") and not PG:
    raise RuntimeError("TEST_POSTGRES_URL is unset in CI.")
pytestmark = pytest.mark.skipif(not PG, reason="needs a real Postgres")

DAY, TZ = date(2026, 8, 5), "America/New_York"


def _meal(oid="tap_1", name="Chicken", cal=320.0, **kw):
    return ResolvedMeal(
        operation_id=oid, revision=0, user_id=1, logging_day=DAY,
        user_timezone=TZ,
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=cal, protein=43.0),), **kw)


LEGACY_OK = {"item_count": 1, "names": ("Chicken",),
             "totals": {"calories": 320.0, "protein": 43.0},
             "day_totals": {"calories": 320.0, "protein": 43.0}}


@pytest_asyncio.fixture
async def pg(monkeypatch):
    monkeypatch.setenv("CANONICAL_WRITER_SHADOW", "true")
    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        s.add(User(telegram_id="pg:shadow"))
        await s.flush()
        s.add(DailyLog(id=1, user_id=1, date=DAY))
        await s.flush()
        # The legacy quick-log row, already COMMITTED — the state the shadow
        # actually runs against. Seeding a total with no rows behind it is what
        # made the first version of these tests pass for the wrong reason:
        # `recompute_log_totals` derives from entries, so with none present the
        # shadow's own row reproduced the seeded number by coincidence.
        s.add(FoodEntry(daily_log_id=1, parsed_food_name="Chicken",
                        calories=320.0, protein=43.0))
        await s.flush()
        await recompute_log_totals(s, 1)
        await s.commit()
    yield maker
    await engine.dispose()


async def _rows(maker, model):
    async with maker() as s:
        return int((await s.execute(
            select(func.count()).select_from(model))).scalar() or 0)


@pytest.mark.asyncio
async def test_the_shadow_writes_nothing(pg):
    """It runs the real writer — and leaves no trace of it."""
    async with pg() as s:
        diffs = await compare_with_legacy(s, meal=_meal(), legacy=LEGACY_OK)
        await s.commit()

    assert diffs == [], f"unexpected divergence: {diffs}"
    assert await _rows(pg, FoodEntry) == 1, "the shadow left rows behind"
    assert await _rows(pg, MealCommit) == 0, "the shadow left a claim behind"


@pytest.mark.asyncio
async def test_agreement_is_reported(pg, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        async with pg() as s:
            await compare_with_legacy(s, meal=_meal(), legacy=LEGACY_OK)
            await s.commit()
    assert any("outcome=agreed" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_divergence_names_the_field(pg, caplog):
    """"They disagree" is not actionable. Which number, and by how much, is."""
    import logging
    legacy = dict(LEGACY_OK, totals={"calories": 205.0, "protein": 43.0})
    with caplog.at_level(logging.WARNING):
        async with pg() as s:
            diffs = await compare_with_legacy(s, meal=_meal(), legacy=legacy)
            await s.commit()

    assert diffs and any("calories 320.0 != 205.0" in d for d in diffs), diffs
    assert any("outcome=diverged" in r.getMessage() for r in caplog.records)
    # the committed legacy row survives; only the shadow's copy is gone
    assert await _rows(pg, FoodEntry) == 1


@pytest.mark.asyncio
async def test_a_shadow_failure_does_not_reach_the_caller(pg, caplog):
    """A user's tap must not fail because the path being EVALUATED could not
    handle it. An exception here is a finding, not an outage."""
    import logging
    async with pg() as s:
        with caplog.at_level(logging.WARNING):
            # a meal whose user does not exist -> the write fails at the FK
            broken = ResolvedMeal(
                operation_id="tap_bad", revision=0, user_id=99999,
                logging_day=DAY, user_timezone=TZ, items=_meal().items)
            out = await compare_with_legacy(s, meal=broken, legacy=LEGACY_OK)
        assert out is None, "a failed shadow must not report a comparison"
        assert any("outcome=error" in r.getMessage() for r in caplog.records)

        # ...and the session is still usable, which is the part that matters.
        s.add(FoodEntry(daily_log_id=1, parsed_food_name="after", calories=1))
        await s.commit()
    assert await _rows(pg, FoodEntry) == 2


@pytest.mark.asyncio
async def test_the_shadow_is_off_by_default(pg, monkeypatch):
    """Nothing runs until it is switched on, deliberately."""
    monkeypatch.delenv("CANONICAL_WRITER_SHADOW", raising=False)
    assert canonical_shadow.shadow_enabled() is False
    async with pg() as s:
        assert await compare_with_legacy(s, meal=_meal(),
                                         legacy=LEGACY_OK) is None
    assert await _rows(pg, FoodEntry) == 1


@pytest.mark.asyncio
async def test_a_failure_while_BUILDING_the_shadow_is_contained(pg,
                                                                monkeypatch):
    """THE GAP THAT ALMOST SHIPPED.

    The earlier tests covered a failure INSIDE `compare_with_legacy`. They did
    not cover one while building the ResolvedMeal — and `api/quick_log.py` had
    no module logger, so its `except` block would have raised NameError from
    inside the handler and taken the user's tap down with it. A shadow that can
    break the request it shadows is worse than no shadow.
    """
    import api.quick_log as quick_log

    assert hasattr(quick_log, "logger"), \
        "the handler's except block logs; without a logger it raises instead"

    class _User:
        id, timezone = 1, "America/New_York"

    class _Payload:                    # missing every field the meal needs
        food_name = None
        calories = None

    class _Entry:
        id, parsed_food_name, calories = 1, "x", 1.0
        protein = carbs = fats = None

    class _Log:
        id, date, total_calories = 1, DAY, 1.0

    async with pg() as s:
        # Must return, not raise, whatever the payload looks like.
        await quick_log._shadow_canonical(s, _User(), _Payload(), _Entry(),
                                          _Log(), "tap_broken")
        s.add(FoodEntry(daily_log_id=1, parsed_food_name="after", calories=1))
        await s.commit()
    assert await _rows(pg, FoodEntry) == 2, "the request did not survive"


@pytest.mark.asyncio
async def test_the_day_total_is_normalised_for_the_additive_shadow(pg):
    """THE ARITHMETIC, with a non-zero baseline so it is unambiguous.

        day begins at              800   (breakfast, already committed)
        legacy quick log adds      320
        legacy final             1,120   <- what the user sees
        shadow temporarily adds    320
        raw canonical day        1,440   <- what a naive comparison would read
        normalised               1,120   <- agreement

    Measured before the fix: `day_calories 1440.0 != 1120.0` on every tap. That
    was not a canonical-vs-legacy disagreement; it was the shadow comparing a
    duplicated day against a non-duplicated one.
    """
    async with pg() as s:
        s.add(FoodEntry(daily_log_id=1, parsed_food_name="Breakfast",
                        calories=800.0, protein=40.0))
        await s.flush()
        await recompute_log_totals(s, 1)
        await s.commit()
        log = (await s.execute(select(DailyLog))).scalar_one()
        assert float(log.total_calories) == 1120.0

        diffs = await compare_with_legacy(
            s, meal=_meal(),
            legacy={"item_count": 1, "names": ("Chicken",),
                    "totals": {"calories": 320.0, "protein": 43.0},
                    "day_totals": {"calories": log.total_calories,
                                   "protein": log.total_protein}})
        await s.commit()

    assert diffs == [], f"the additive shadow was not normalised out: {diffs}"


@pytest.mark.asyncio
async def test_a_genuine_day_disagreement_still_shows(pg):
    """Normalisation must not blind the check — only remove the bias."""
    async with pg() as s:
        diffs = await compare_with_legacy(
            s, meal=_meal(),
            legacy={"item_count": 1, "names": ("Chicken",),
                    "totals": {"calories": 320.0, "protein": 43.0},
                    "day_totals": {"calories": 999.0, "protein": 43.0}})
        await s.commit()
    assert any(d.startswith("day_calories") for d in diffs), diffs


def test_the_operation_id_is_scoped_to_the_user():
    """`make_turn_id` returns `f"{channel}:{cid}"` VERBATIM when the client
    sends an Idempotency-Key — no user in it. Two users sending the same key
    would then share an operation id, and `meal_commits` is unique on
    (operation_id, revision) WITHOUT user_id, so the second user's tap would be
    treated as a duplicate and handed the first user's result.

    Widening the constraint is the wrong fix — global operation identity is the
    guarantee. The id carries the scope instead.
    """
    from core.canonical_shadow import operation_id_for

    a = operation_id_for("quick_log", 26, "ios:SAME-KEY")
    b = operation_id_for("quick_log", 99, "ios:SAME-KEY")
    assert a != b, "two users collide on one operation id"
    assert "26" in a and "99" in b
    assert operation_id_for("quick_log", 26, "ios:X") != \
        operation_id_for("chat", 26, "ios:X"), "lanes must not collide either"


@pytest.mark.asyncio
async def test_matching_calories_do_not_hide_a_macro_split(pg):
    """CALORIES ALONE IS NOT PARITY.

    A resolver that prices energy correctly and splits the macros wrong is one
    of the most common ways to be subtly incorrect — 320 kcal of chicken and
    320 kcal of rice are the same number and a different meal. Caught by
    mutation: reducing the compared set to calories broke no test until this
    one existed.
    """
    legacy = {"item_count": 1, "names": ("Chicken",),
              # same energy, protein off by 33g
              "totals": {"calories": 320.0, "protein": 10.0},
              "day_totals": {"calories": 320.0, "protein": 10.0}}
    async with pg() as s:
        diffs = await compare_with_legacy(s, meal=_meal(), legacy=legacy)
        await s.commit()

    assert not any(d.startswith("calories") for d in diffs), \
        "calories agree and must not be reported"
    assert any(d.startswith("protein 43.0 != 10.0") for d in diffs), diffs
    assert any(d.startswith("day_protein") for d in diffs), diffs
