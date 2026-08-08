"""B-1's operation lifecycle, against a real database.

`test_b1_quantity_slice.py` proves the producer and the answer boundary in
memory. This proves the part that only storage can: that ownership survives a
turn boundary, that the answer commits ONCE through the canonical coordinator,
and — the rule the whole rollout design rests on — that an operation which has
taken ownership finishes canonically no matter what the gate says afterwards.

A file database with real per-session connections, not the shared `:memory:`
StaticPool: the claim under test is about state crossing a CLOSED session, and
on one shared connection that claim cannot fail.
"""
import json

import pytest

from core.canonical_pricing import PricedFood as _PricedFood
from core.canonical_pricing import Rung as _Rung


def _mass(consumed):
    """The answered mass as the old stub reported it, so the
    existing assertions keep their meaning."""
    g = getattr(consumed, 'grams', None)
    return f'{g:g}g' if g is not None else ''
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_quantity_operation as b1
from core.clarification_answer import Outcome, answer_from_chip, answer_from_text
from core.semantics import CandidateSource, CandidateValue, Provenance
from db.models import (Base, DailyLog, FoodEntry, LedgerEvent, MealCommit,
                       PendingOperation, User)
from skills.nutrition import quantity_clarification as qc
from skills.nutrition.staging import FoodIdentity, StagedFoodItem

ITEM = {"food": "chicken breast", "calories": 187, "protein": 35,
        "carbs": 0, "fats": 4, "quantity": "some"}


@pytest_asyncio.fixture
async def engine(tmp_path):
    """OVERRIDES conftest's shared :memory: engine — see the module docstring."""
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'b1.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession,
                              expire_on_commit=False)


@pytest_asyncio.fixture
async def user(sessions):
    async with sessions() as s:
        u = User(telegram_id="b1:tester", name="B1", timezone="America/New_York")
        s.add(u)
        await s.commit()
        return u


def _staged():
    return StagedFoodItem(staged_item_id="si_1",
                          original_text="some chicken breast",
                          identity=FoodIdentity(canonical_name="chicken breast"))


def _interaction(operation_id, revision=0):
    item = _staged()
    field = qc.quantity_field(operation_id=operation_id, revision=revision,
                              item=item)
    from tests._typed_candidates import candidates as _typed

    candidates = _typed(
        ("ont_low", 85.0, CandidateSource.ONTOLOGY, 0.2, 0.6),
        ("hist_last", 141.7, CandidateSource.USER_HISTORY, 0.55, 0.9),
        ("ont_high", 226.0, CandidateSource.ONTOLOGY, 0.3, 0.6))
    options = qc.select(candidates, field=field, food_name="chicken breast")
    return qc.build_interaction(operation_id=operation_id, revision=revision,
                                item=item, options=options,
                                introduction="How much chicken breast?")


@pytest.fixture(autouse=True)
def _priced(monkeypatch):
    """Pricing is stubbed at `_analyze_food` — the seam B-1 reuses — so these
    tests measure the LIFECYCLE, not the enrichment ladder. What matters here
    is that the answered quantity reaches pricing and the result reaches the
    canonical writer; what a chicken breast costs is `analyze()`'s contract and
    is tested where that lives."""
    class _Analysis:
        calories, protein, carbs, fat = 231.0, 43.0, 0.0, 5.0
        fiber = sugar = sodium = None
        micros, micros_estimated, assumptions = None, False, ()
        provenance = None
        confidence = "likely"

    seen = {}

        # REPOINTED (P1.4): the canonical lane no longer rents
        # `_analyze_food`. It calls the synchronous canonical pricer,
        # so the stub is a pricer — keyword args, `PricedFood` out.
        # The answered MASS is still what is observed; it now arrives
        # as `consumed.grams` instead of a quantity string.
    def _fake(*, entity, consumed=None, **kw):
        seen["quantity"] = _mass(consumed)
        seen["food"] = entity
        return _PricedFood(calories=231.0, protein=43.0, carbs=0.0, fats=5.0, rung=_Rung.ARTIFACT, evidence_id="usda:test")

    monkeypatch.setattr("core.canonical_pricing.price", _fake)
    return seen


async def _open(sessions, user, turn_id="t_1"):
    async with sessions() as s:
        u = await s.get(User, user.id)
        op = await b1.open_operation(
            s, user=u, interpreter_item=ITEM,
            interaction=_interaction(f"chat_quantity:{user.id}:{turn_id}"),
            turn_id=turn_id, cohort="allowlist")
        await s.commit()
    return op


# ── ownership across the turn boundary ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ownership_survives_a_closed_session(sessions, user):
    """The ask turn ends. The row is what remembers."""
    operation_id = await _open(sessions, user)

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)

    assert owned is not None and owned.awaiting and owned.readable
    assert owned.operation_id == operation_id
    assert owned.item["food"] == "chicken breast", \
        "the interpreter's reading must cross the boundary, or the answer " \
        "turn re-interprets and re-prices"
    field = owned.interaction.groups[0].fields[0]
    assert [o.option_id for o in field.options] == [
        "opt_ont_low", "opt_hist_last", "opt_ont_high"]


@pytest.mark.asyncio
async def test_a_user_with_no_operation_is_not_owned(sessions, user):
    async with sessions() as s:
        u = await s.get(User, user.id)
        assert await b1.owning(s, u) is None


@pytest.mark.asyncio
async def test_an_unreadable_payload_still_owns_the_meal(sessions, user):
    """Pretending nothing is pending is how a held meal disappears. The
    operation comes back with readable=False so the turn REPAIRS."""
    await _open(sessions, user)
    async with sessions() as s:
        row = (await s.execute(select(PendingOperation))).scalar_one()
        payload = json.loads(row.canonical_payload)
        payload["interaction"] = {"schema_version": 99}     # unreadable
        row.canonical_payload = json.dumps(payload)
        await s.commit()

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
    assert owned is not None, "an unreadable payload must not read as 'nothing pending'"
    assert owned.readable is False


# ── settling ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_chip_answer_commits_once_through_the_canonical_spine(
        sessions, user, _priced):
    await _open(sessions, user)

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
        field_id = owned.interaction.groups[0].fields[0].field_id
        answer = answer_from_chip(owned.interaction, field_id=field_id,
                                  option_id="opt_hist_last",
                                  revision=owned.revision)
        assert answer.outcome is Outcome.APPLIED
        result = await b1.settle(s, user=u, owned=owned,
                                 resolved=b1.resolved_fields(
                                     {answer.patch.field_id: answer.patch}),
                                 source_turn_id="t_2", cohort="allowlist")
        await s.commit()

    assert len(result.committed_items) == 1
    assert _priced["quantity"] == "141.7g", \
        "the answered mass must reach pricing, not the original hedge"

    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(FoodEntry))).scalar() == 1
        assert (await s.execute(
            select(func.count()).select_from(MealCommit))).scalar() == 1
        commit = (await s.execute(select(MealCommit))).scalar_one()
        assert commit.status == "committed"
        events = (await s.execute(select(LedgerEvent))).scalars().all()
        assert [e.source for e in events] == ["canonical:create"], \
            "no legacy-sourced write may appear on an eligible turn"
        row = (await s.execute(select(PendingOperation))).scalar_one()
        assert row.status == b1.COMMITTED
        entry = (await s.execute(select(FoodEntry))).scalar_one()
        log = await s.get(DailyLog, entry.daily_log_id)
        assert log.user_id == user.id


@pytest.mark.asyncio
async def test_a_typed_answer_records_a_different_provenance(sessions, user,
                                                             _priced):
    """A tap is a selection; typing is a statement. The distinction has to
    survive all the way to the committed event."""
    await _open(sessions, user, turn_id="t_typed")

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
        field_id = owned.interaction.groups[0].fields[0].field_id
        answer = answer_from_text(owned.interaction, field_id=field_id,
                                  text="about 6 ounces",
                                  revision=owned.revision,
                                  food_name="chicken breast")
        assert answer.outcome is Outcome.APPLIED
        assert answer.patch.provenance is Provenance.USER_STATED
        await b1.settle(s, user=u, owned=owned,
                                 resolved=b1.resolved_fields(
                                     {answer.patch.field_id: answer.patch}),
                        source_turn_id="t_typed_2")
        await s.commit()

    assert _priced["quantity"] == "170.1g"


@pytest.mark.asyncio
async def test_two_deliveries_of_one_answer_write_one_meal(sessions, user,
                                                           _priced):
    """The SAME delivery arriving twice — a retried request, a double-fire.
    Both read the operation at the same revision, so both compute the same
    `(operation_id, revision)` claim and the second is answered from storage.
    """
    await _open(sessions, user)

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
        field_id = owned.interaction.groups[0].fields[0].field_id
        answer = answer_from_chip(owned.interaction, field_id=field_id,
                                  option_id="opt_ont_low",
                                  revision=owned.revision)
        first = await b1.settle(s, user=u, owned=owned,
                                 resolved=b1.resolved_fields(
                                     {answer.patch.field_id: answer.patch}),
                                source_turn_id="t_2")
        # The retry carries the state it read, which is the pre-answer one.
        second = await b1.settle(s, user=u, owned=owned,
                                 resolved=b1.resolved_fields(
                                     {answer.patch.field_id: answer.patch}),
                                 source_turn_id="t_2")
        await s.commit()

    assert first.committed_items == second.committed_items
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(FoodEntry))).scalar() == 1, \
            "a duplicate delivery must not write a second meal"
        assert (await s.execute(
            select(func.count()).select_from(MealCommit))).scalar() == 1


@pytest.mark.asyncio
async def test_a_tap_after_the_meal_landed_replays_instead_of_logging_again(
        sessions, user, _priced):
    """THE BUG THIS TEST WAS WRITTEN FOR.

    The chip stays on screen after the meal lands, so a later tap is a real
    delivery — and it cannot be answered by settling again: `settle` advances
    the revision, so a second pass computes a DIFFERENT (operation_id,
    revision) pair, forms its own valid claim, and writes a second meal. The
    coordinator cannot catch that; the two claims are genuinely distinct. The
    guard is the operation's terminal status.
    """
    await _open(sessions, user)
    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
        field_id = owned.interaction.groups[0].fields[0].field_id
        answer = answer_from_chip(owned.interaction, field_id=field_id,
                                  option_id="opt_ont_low",
                                  revision=owned.revision)
        first = await b1.settle(s, user=u, owned=owned,
                                 resolved=b1.resolved_fields(
                                     {answer.patch.field_id: answer.patch}),
                                source_turn_id="t_2")
        await s.commit()

    # A fresh turn, reading fresh state: the operation is COMMITTED now.
    async with sessions() as s:
        u = await s.get(User, user.id)
        again = await b1.owning(s, u)
        assert again is not None and not again.awaiting, \
            "ownership must outlive the commit, or the tap goes to the " \
            "interpreter and becomes a second meal"
        assert again.status == b1.COMMITTED
        replayed = await b1.settle(
            s, user=u, owned=again,
            resolved=b1.resolved_fields({answer.patch.field_id: answer.patch}),
            source_turn_id="t_3")
        await s.commit()

    assert replayed.committed_items == first.committed_items
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(FoodEntry))).scalar() == 1, \
            "a tap after commit must replay, never write a second meal"


@pytest.mark.asyncio
async def test_a_cancelled_operation_writes_nothing_and_closes(sessions, user):
    await _open(sessions, user)
    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
        answer = answer_from_text(
            owned.interaction,
            field_id=owned.interaction.groups[0].fields[0].field_id,
            text="never mind", revision=owned.revision)
        assert answer.outcome is Outcome.CANCELLED
        await b1.cancel(s, owned=owned, user=u, reason="user_cancelled")
        await s.commit()

    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(FoodEntry))).scalar() == 0
        row = (await s.execute(select(PendingOperation))).scalar_one()
        assert row.status == b1.CANCELLED
        assert row.storage_status == "closed"


# ── C10: terminal ownership ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tripped_kill_switch_cannot_strand_a_meal_in_flight(
        sessions, user, _priced, monkeypatch):
    """C10, the rule the whole rollout design rests on.

    The gate is asked ONCE, before ownership. Halting it stops NEW operations;
    an operation already in flight still commits canonically. Anything else
    loses the meal: the answer becomes a second meal, the pending row is
    dropped, or the user answers twice.
    """
    from skills.nutrition import quantity_rollout as qr

    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(user.id))
    assert qr.may_take_ownership(user.id) is True
    await _open(sessions, user)

    monkeypatch.setenv("B1_QUANTITY_HALT", "true")
    assert qr.may_take_ownership(user.id) is False, "the halt must stop NEW work"

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
        assert owned is not None and owned.awaiting, \
            "a halt must not disown a meal already in flight"
        field_id = owned.interaction.groups[0].fields[0].field_id
        answer = answer_from_chip(owned.interaction, field_id=field_id,
                                  option_id="opt_hist_last",
                                  revision=owned.revision)
        await b1.settle(s, user=u, owned=owned,
                                 resolved=b1.resolved_fields(
                                     {answer.patch.field_id: answer.patch}),
                        source_turn_id="t_2")
        await s.commit()

    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(FoodEntry))).scalar() == 1, \
            "the halted-mid-flight meal must still have committed"
