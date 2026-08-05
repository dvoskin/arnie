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


# test_a_failure_while_BUILDING_the_shadow_is_contained was DELETED at the
# quick_log promotion: it exercised `_shadow_canonical`, the builder the
# promotion replaced with the real canonical write. A test must protect a
# product invariant, not a deleted function. The containment it guarded lives
# on in the handler's CommitInProgress -> 409 path and compare_with_legacy's
# never-raises contract, both still tested.


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


def test_the_shadow_flag_is_reportable_from_outside(monkeypatch):
    """A FLAG NOBODY CAN SEE IS A DECISION NOBODY MAKES — and for a SHADOW it
    is worse than that.

    The 593bd19 deploy landed with no way to tell from outside whether the
    shadow was running. An unset shadow produces a clean, empty,
    zero-divergence window that is indistinguishable from a lane in perfect
    agreement — so the evidence used to promote a mutation owner and DELETE its
    predecessor could be the evidence of nothing having happened.
    """
    from api.diagnostics import public_pipeline_summary

    monkeypatch.setenv("CANONICAL_WRITER_SHADOW", "true")
    on = public_pipeline_summary()["CANONICAL_WRITER_SHADOW"]
    assert on["effective"] is True and on["env_set"] is True

    monkeypatch.delenv("CANONICAL_WRITER_SHADOW", raising=False)
    off = public_pipeline_summary()["CANONICAL_WRITER_SHADOW"]
    assert off["effective"] is False and off["env_set"] is False, (
        "defaulted-off and deliberately-off must be distinguishable: they "
        "behave identically and need opposite fixes")


# ── promotion follow-ups ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nutrition_provenance_survives_into_the_stored_result(pg):
    """WHO PRICED IT is a different fact from who chose it.

    A quick-log tap carries client-calculated macros: the user picked
    "Chicken breast" (USER_SELECTED on the event) but the numbers came from
    the client's local computation. Structured input is not authority, and a
    later reader — including a duplicate replay answered from storage — must
    still be able to tell client-priced from catalog- or server-priced.
    """
    from core.canonical_writer import write_canonical_meal
    from core.commit_coordinator import commit_or_load_existing

    priced = ResolvedFood(
        event=CanonicalEvent(id="e", domain="food", surface_text="Chicken",
                             resolution_status=ResolutionStatus.RESOLVED),
        calories=320.0, protein=43.0, nutrition_provenance="client_estimated")
    meal = ResolvedMeal(operation_id="op_prov", revision=0, user_id=1,
                        logging_day=DAY, user_timezone=TZ, items=(priced,))

    class _Op:
        id, revision, user_id = "op_prov", 0, 1

    async with pg() as s:
        result = await commit_or_load_existing(
            s, operation=_Op(), resolved_meal=meal,
            writer=write_canonical_meal)
        await s.commit()

    assert result.committed_items[0]["nutrition_provenance"] == "client_estimated"

    from core import meal_commit
    async with pg() as s:
        stored = await meal_commit.existing_result(s, operation_id="op_prov")
    assert stored.committed_items[0]["nutrition_provenance"] == "client_estimated", \
        "provenance did not survive storage — a replay could not distinguish " \
        "a client-priced log from a resolved one"


def test_the_quick_log_food_writer_is_reported_on_health():
    """"Which writer serves taps on this deployment" must be readable from
    OUTSIDE. The promotion verification record keys on it, and inferring it
    from a commit sha is exactly the guesswork /health exists to end."""
    from api.diagnostics import public_pipeline_summary

    assert public_pipeline_summary().get("QUICK_LOG_FOOD_WRITER") == "canonical"


def test_post_commit_actions_go_through_one_dispatcher():
    """An unknown action is skipped, not fatal — a newer writer emitting a new
    action must not break an older endpoint. A failing action does not undo a
    committed mutation either."""
    from core import render_actions

    calls = []
    original = render_actions._HANDLERS.copy()
    render_actions._HANDLERS["ok"] = lambda a: calls.append(a)
    render_actions._HANDLERS["boom"] = lambda a: (_ for _ in ()).throw(
        RuntimeError("cache host down"))
    try:
        ran = render_actions.dispatch((
            {"action": "ok", "user_id": 1},
            {"action": "from_a_newer_writer"},
            {"action": "boom"},
        ))
    finally:
        render_actions._HANDLERS.clear()
        render_actions._HANDLERS.update(original)

    assert ran == 1 and len(calls) == 1


@pytest.mark.asyncio
async def test_durable_outbox_work_rides_the_transaction(pg):
    """DURABLE vs BEST-EFFORT are different guarantees and must not share a
    channel. Outbox events land in `background_jobs` inside the mutation's own
    transaction — either the meal and the work it owes are both durable, or
    neither happened."""
    from sqlalchemy import select

    from core.canonical_writer import ResolvedMeal
    from core.commit_coordinator import commit_or_load_existing
    from core.meal_commit import MealCommitResult, OutboxEvent
    from db.models import BackgroundJob

    async def writer_with_outbox(db, *, operation, resolved_meal):
        return MealCommitResult(
            committed_items=({"entry_id": 1, "daily_log_id": 1},),
            meal_totals={"calories": 100.0},
            render_actions=({"action": "invalidate_briefing", "user_id": 1},),
            outbox_events=(OutboxEvent(kind="memory_reflection",
                                       payload={"meal": "x"},
                                       dedup_key="u1:reflect:2026-08-05"),))

    class _Op:
        id, revision, user_id, source_turn_id = "op_outbox", 0, 1, "t:1"

    async with pg() as s:
        await commit_or_load_existing(
            s, operation=_Op(), resolved_meal=_meal(), writer=writer_with_outbox)
        await s.commit()

    async with pg() as s:
        jobs = (await s.execute(select(BackgroundJob))).scalars().all()
    assert len(jobs) == 1 and jobs[0].kind == "memory_reflection"


@pytest.mark.asyncio
async def test_a_duplicate_does_not_re_enqueue_the_outbox(pg):
    """The original delivery already owns the durable work. Re-enqueueing on
    every retry would multiply the work a flaky network causes — the opposite
    of what idempotency is for."""
    from sqlalchemy import func, select

    from core.commit_coordinator import commit_or_load_existing
    from core.meal_commit import MealCommitResult, OutboxEvent
    from db.models import BackgroundJob

    async def writer(db, *, operation, resolved_meal):
        return MealCommitResult(
            committed_items=({"entry_id": 1, "daily_log_id": 1},),
            meal_totals={"calories": 100.0},
            outbox_events=(OutboxEvent(kind="analytics_record",
                                       dedup_key="u1:analytics:t2"),))

    class _Op:
        id, revision, user_id, source_turn_id = "op_dup_outbox", 0, 1, "t:2"

    for _ in range(3):
        async with pg() as s:
            await commit_or_load_existing(s, operation=_Op(),
                                          resolved_meal=_meal(), writer=writer)
            await s.commit()

    async with pg() as s:
        n = (await s.execute(
            select(func.count()).select_from(BackgroundJob))).scalar()
    assert n == 1, f"three deliveries queued {n} jobs — duplicates re-enqueued"


def test_an_untyped_outbox_dict_is_normalised_or_refused_at_construction():
    """The enforcement moved EARLIER than the coordinator, and got stronger.

    Rehydration-at-construction (the C6 fix: a duplicate rebuilt from JSON
    must equal the winner) means a dict in outbox_events becomes an
    OutboxEvent immediately — passing through the SAME validation the type
    enforces. So an invalid dict cannot exist inside a result at all, and a
    well-formed one carries every guarantee the type does. There is no path
    on which an unvalidated dict reaches the queue.
    """
    from core.meal_commit import (MealCommitResult, OutboxEvent,
                                  UnserializableResult)

    # invalid: no dedup decision -> refused where the producer is on the stack
    with pytest.raises(UnserializableResult, match="dedup_key"):
        MealCommitResult(meal_totals={"calories": 1.0},
                         outbox_events=({"kind": "sneaky_dict"},))

    # well-formed: normalised into the type, equal across the round trip
    r = MealCommitResult(
        meal_totals={"calories": 1.0},
        outbox_events=({"kind": "ok", "dedup_key": "u1:ok"},))
    assert isinstance(r.outbox_events[0], OutboxEvent)
    assert r == MealCommitResult.from_payload(r.to_payload()), \
        "winner and duplicate must hold the same type (C6)"
